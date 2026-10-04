"""Does the deployed service reproduce the evaluated validation predictions? (Step 8, pre-registered in BUILD_LOG)

  python -m scripts.deploy_parity --url https://... --target cloudrun

20 seeded validation contracts, the baseline and the tuned legal-BERT, both operating points. The
CUAD gold text of each contract goes to /classify; the served flags are compared with the stored
validation predictions under the local threshold files. Validation only: no test or shift text is sent.
"""

from __future__ import annotations

import argparse
import json
import time
import zlib

import httpx
import numpy as np
import pandas as pd

from src import config
from src.baseline import indicator
from src.data import load_contexts, load_raw_json
from src.infer import _thresholds, artifacts
from src.predictions import read_label_order
from src.thresholds import apply_thresholds

MODELS = ("baseline", config.TUNED_MODEL_NAME)
POINTS = ("balanced", "high_recall")
TIMEOUT_S = 1000


def sample_contracts(segments: pd.DataFrame) -> list[int]:
    val = sorted(segments.loc[segments["split"] == "val", "contract_id"].unique())
    rng = np.random.default_rng([config.SEED, zlib.crc32(b"deploy_parity")])
    out = sorted(int(c) for c in rng.choice(val, size=config.DEPLOY_PARITY_CONTRACTS, replace=False))
    for cid in out:
        if set(segments.loc[segments["contract_id"] == cid, "split"]) != {"val"}:
            raise SystemExit(f"contract {cid} is not a validation contract")
    return out


def stored_rows(segments: pd.DataFrame, pred: pd.DataFrame, cid: int) -> pd.DataFrame:
    """segments: segments.parquet with excluded rows; pred: the model's _val.parquet."""
    rows = segments[segments["contract_id"] == cid].merge(pred[["segment_id", "proba"]], on="segment_id", how="left")
    missing = rows.loc[~rows["exclude"], "proba"].isna()
    if missing.any():
        raise SystemExit(f"contract {cid}: {int(missing.sum())} kept segments have no stored prediction")
    return rows


def compare(served: list[dict], stored: pd.DataFrame, label_order, thresholds) -> dict:
    """served: one response's segments. stored: that contract's segments.parquet rows (excluded included),
    with the stored validation probabilities joined by segment_id (missing for excluded rows)."""
    by_span = {(int(r.start), int(r.end)): r for r in stored.itertuples()}
    if set(by_span) != {(s["start"], s["end"]) for s in served}:
        raise SystemExit("served segments differ from segments.parquet")
    kept = [s for s in served if not by_span[(s["start"], s["end"])].exclude]
    proba = np.vstack([by_span[(s["start"], s["end"])].proba for s in kept])
    col = {lab: j for j, lab in enumerate(label_order)}
    unknown = {lab["label"] for s in kept for lab in s["labels"]} - set(col)
    if unknown:
        raise SystemExit(f"served labels outside the local label order: {sorted(unknown)}")
    expected = apply_thresholds(proba, label_order, thresholds)
    got = indicator([[lab["label"] for lab in s["labels"]] for s in kept], label_order)
    conf = np.zeros_like(proba)
    for i, s in enumerate(kept):
        for lab in s["labels"]:
            conf[i, col[lab["label"]]] = lab["confidence"]
    both = expected & got
    return {"segments": len(kept), "excluded": len(served) - len(kept), "pairs": int(expected.size),
            "disagree": int((expected != got).sum()), "flagged_either": int((expected | got).sum()),
            "max_conf_diff": float(np.abs(conf - proba)[both].max()) if both.any() else 0.0}


def total(parts: list[dict], failed: list[int]) -> dict:
    keys = ("segments", "excluded", "pairs", "disagree", "flagged_either")
    out = {k: sum(p[k] for p in parts) for k in keys}
    out["max_conf_diff"] = max((p["max_conf_diff"] for p in parts), default=0.0)
    out["failed"] = len(failed)
    out["failed_contracts"] = failed
    return out


def passes(model: str, t: dict) -> bool:
    if t["failed"]:
        return False
    if model == "baseline":
        return t["disagree"] == 0
    return (t["disagree"] <= 0.001 * t["pairs"]
            and t["disagree"] <= 0.01 * max(t["flagged_either"], 1))


def make_client(url: str) -> httpx.Client:
    """A fresh connection per request: on GKE a reused keep-alive connection was dropped silently and one
    request waited out the full timeout (BUILD_LOG Step 8). No retries: a failed request still fails."""
    return httpx.Client(base_url=url, timeout=TIMEOUT_S, limits=httpx.Limits(max_keepalive_connections=0))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--target", required=True, choices=("cloudrun", "gke"))
    args = ap.parse_args()

    segments = pd.read_parquet(config.PROCESSED_DIR / "segments.parquet")
    contracts = sample_contracts(segments)
    texts = load_contexts(load_raw_json())
    report = {"target": args.target, "url": args.url, "contracts": contracts, "models": {}}
    print(f"Parity against {args.url} ({args.target}); validation contracts: {contracts}", flush=True)
    with make_client(args.url) as client:
        for name in MODELS:
            art = artifacts(name)
            thresholds, _ = _thresholds(name, art)
            pred_path = config.PREDICTIONS_DIR / f"{name}_val.parquet"
            if read_label_order(pred_path) != art.label_order:
                raise SystemExit(f"{name}: stored label order differs from the local labels.json")
            pred = pd.read_parquet(pred_path, columns=["segment_id", "proba"])
            versions, rows = set(), {}
            for point in POINTS:
                if point not in thresholds:
                    raise SystemExit(f"{name}: no local {point} thresholds")
                parts, failed = [], []
                for cid in contracts:
                    t0 = time.perf_counter()
                    try:
                        r = client.post("/classify", json={"text": texts[cid], "model": name, "operating_point": point})
                        r.raise_for_status()
                    except httpx.HTTPError as e:
                        print(f"  {name} | {point} | contract {cid}: request failed after {time.perf_counter() - t0:.0f}s "
                              f"({type(e).__name__}: {e})", flush=True)
                        failed.append(cid)
                        continue
                    print(f"  {name} | {point} | contract {cid}: {time.perf_counter() - t0:.0f}s", flush=True)
                    body = r.json()
                    versions.add(body["model_version"])
                    parts.append(compare(body["segments"], stored_rows(segments, pred, cid), art.label_order,
                                         thresholds[point]))
                rows[point] = total(parts, failed)
            version_ok = versions == {art.version}
            for point in POINTS:
                rows[point]["passes"] = version_ok and passes(name, rows[point])
            report["models"][name] = {"local_version": art.version, "served_versions": sorted(versions),
                                      "version_ok": version_ok, "points": rows}

    out = config.EVAL_DIR / f"deploy_parity_{args.target}.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"\n{'model':18} {'point':12} {'segments':>8} {'excluded':>8} {'pairs':>8} {'disagree':>8} "
          f"{'flagged':>8} {'max_conf_diff':>13} {'failed':>6}  result")
    for name, m in report["models"].items():
        for point, t in m["points"].items():
            print(f"{name:18} {point:12} {t['segments']:>8} {t['excluded']:>8} {t['pairs']:>8} {t['disagree']:>8} "
                  f"{t['flagged_either']:>8} {t['max_conf_diff']:>13.2e} {t['failed']:>6}  "
                  f"{'PASS' if t['passes'] else 'FAIL'}")
        print(f"  {name}: served version {m['served_versions']}, local {m['local_version']}, "
              f"{'match' if m['version_ok'] else 'MISMATCH'}")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()

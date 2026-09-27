"""Unlabeled drift checks (Step 5). Thresholds come from validation only; test and shift are
scored once against them.

  python -m src.drift calibrate          validation null, per-statistic and family thresholds
                                         -> models/drift/reference.json
  python -m src.drift evaluate [--force] alarm rates on test and shift with contract-bootstrap
                                         intervals -> data/eval/drift.json

A batch is DRIFT_BATCH_CONTRACTS contracts. Every statistic is built from additive per-contract
sums, so a batch, a leave-batch-out reference and a bootstrap resample are all weight vectors
over contracts, as in src/bootstrap.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import zlib
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse

from src import config
from src.baseline import load_frozen_pipeline, model_version as baseline_artifact_hash
from src.bootstrap import f1_metrics, per_contract_counts, percentile_ci, resample_weights
from src.evaluate import label_sets, load_predictions

INPUT_STATS = ("oov_rate_diff", "tfidf_centroid_distance", "length_psi")
MODEL_STATS = ("label_mix_js", "none_share_diff", "confidence_psi")
CONF_INNER_EDGES = np.round(np.arange(0.05, 1.0, 0.1), 2)  # Claude's tenths fall mid-bin
EPS = 1e-4
EVAL_SETS = ("test", "shift", "shift:Franchise", "shift:Transportation")
ADDITIVE = ("tokens", "oov", "length_hist")
MODEL_ADDITIVE = ("labels", "parsed", "none", "conf_hist", "parse_failures")


def reference_path() -> Path:
    return config.DRIFT_DIR / "reference.json"


def out_path() -> Path:
    return config.EVAL_DIR / "drift.json"


def baseline_version() -> str:
    """The frozen baseline's artifact hash, refused if it differs from its declared version."""
    declared = json.loads((config.MODELS_DIR / "baseline" / "config.json").read_text())["model_version"]
    if baseline_artifact_hash() != declared:
        raise SystemExit(f"model.joblib and thresholds.json do not hash to the declared version {declared}")
    return declared


def families() -> dict[str, tuple[str, ...]]:
    return {"input": INPUT_STATS,
            **{m: tuple(f"{m}:{s}" for s in MODEL_STATS) for m in config.DRIFT_MODELS}}


def stream_rng(stream: str) -> np.random.Generator:
    return np.random.default_rng([config.SEED, zlib.crc32(stream.encode())])


def _hist(pos, x, inner_edges, n) -> np.ndarray:
    out = np.zeros((n, len(inner_edges) + 1))
    np.add.at(out, (pos, np.searchsorted(inner_edges, x, side="right")), 1)
    return out


def psi(p, q):
    empty = (p.sum(axis=-1) == 0) | (q.sum(axis=-1) == 0)
    p = (p + EPS) / (p + EPS).sum(axis=-1, keepdims=True)
    q = (q + EPS) / (q + EPS).sum(axis=-1, keepdims=True)
    return np.where(empty, np.nan, ((p - q) * np.log(p / q)).sum(axis=-1))


def js_distance(p, q):
    tp, tq = p.sum(axis=-1, keepdims=True), q.sum(axis=-1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        p, q = p / tp, q / tq
        m = (p + q) / 2
        kl = lambda a, b: np.where(a > 0, a * np.log2(a / b), 0.0).sum(axis=-1)
        out = np.sqrt((kl(p, m) + kl(q, m)) / 2)
    return np.where((tp[..., 0] > 0) & (tq[..., 0] > 0), out, np.nan)


def load_split(split: str):
    """Prediction-file segments of a split with each model's predictions aligned to the first
    model's order; one version per model; the same segments and label order for every model."""
    loaded = {m: load_predictions(m, split) for m in config.DRIFT_MODELS}
    base = loaded[config.DRIFT_MODELS[0]]
    ids = base[0]["segment_id"]
    preds, versions = {}, {}
    for m, (df, order, _y, y_pred, proba) in loaded.items():
        if order != base[1] or not df["segment_id"].is_unique or set(df["segment_id"]) != set(ids):
            raise SystemExit(f"{split}: {m} does not cover the same segments and labels")
        if not (df["split"] == split).all():
            raise SystemExit(f"{split}: {m} holds rows from another split")
        if df["model_version"].nunique() != 1:
            raise SystemExit(f"{split}: {m} has more than one model version")
        o = pd.Index(df["segment_id"]).get_indexer(ids)
        preds[m] = (df["parse_failure"].to_numpy()[o], y_pred[o], proba[o])
        versions[m] = df["model_version"].iloc[0]
    splits = pd.read_parquet(config.PROCESSED_DIR / "splits.parquet")
    if set(base[0]["contract_id"]) != set(splits.loc[splits["split"] == split, "contract_id"]):
        raise SystemExit(f"{split}: the prediction files' contracts differ from the canonical split")
    text = pd.read_parquet(config.PROCESSED_DIR / "segments.parquet",
                           columns=["segment_id", "text"]).set_index("segment_id")["text"]
    seg = base[0][["segment_id", "contract_id"]].assign(text=text.loc[ids].to_numpy())
    return seg, preds, versions, base[2], base[1]


def ordered_contracts(ids) -> pd.DataFrame:
    """Same order as resample_weights: contract type, then id."""
    c = pd.read_parquet(config.PROCESSED_DIR / "contracts.parquet")
    return (c[c["contract_id"].isin(set(ids))][["contract_id", "contract_type"]]
            .sort_values(["contract_type", "contract_id"]).reset_index(drop=True))


def contract_sums(seg, contract_ids, vectorizer, length_edges, preds) -> tuple[dict, np.ndarray]:
    pos = pd.Index(contract_ids).get_indexer(seg["contract_id"])
    if (pos < 0).any():
        raise ValueError("segment from a contract outside contract_ids")
    n = len(contract_ids)
    analyzer, vocab = vectorizer.build_analyzer(), vectorizer.vocabulary_
    tokens, oov = np.zeros(len(seg)), np.zeros(len(seg))
    for i, text in enumerate(seg["text"]):
        for g in analyzer(text):
            if " " not in g:  # bigrams are joined with a space
                tokens[i] += 1
                oov[i] += g not in vocab
    agg = sparse.csr_matrix((np.ones(len(seg)), (pos, np.arange(len(seg)))), shape=(n, len(seg)))
    out = {"tokens": np.bincount(pos, tokens, n), "oov": np.bincount(pos, oov, n),
           "tfidf": agg @ vectorizer.transform(seg["text"]),
           "length_hist": _hist(pos, seg["text"].str.len().to_numpy(), length_edges, n)}
    for m, (failed, y_pred, proba) in preds.items():
        parsed = ~failed
        out[m] = {"labels": agg @ (y_pred & parsed[:, None]).astype(float),
                  "parsed": np.bincount(pos, parsed, n),
                  "none": np.bincount(pos, parsed & ~y_pred.any(axis=1), n),
                  "conf_hist": _hist(pos[parsed], proba[parsed].max(axis=1), CONF_INNER_EDGES, n),
                  "parse_failures": np.bincount(pos, failed, n)}
    return out, pos


def take(sums: dict, rows) -> dict:
    return {k: (take(v, rows) if isinstance(v, dict) else v[rows]) for k, v in sums.items()}


def weigh(sums: dict, W: np.ndarray) -> dict:
    out = {k: W @ sums[k] for k in ADDITIVE}
    for m in config.DRIFT_MODELS:
        out[m] = {k: W @ sums[m][k] for k in MODEL_ADDITIVE}
    return out


def batch_stats(b: dict, r: dict) -> dict:
    """b: batch sums (one row per batch); r: reference sums (one row per batch, or one row).
    The TF-IDF vectors enter only as dot products: b['bb'], b['br'], r['rr']."""
    with np.errstate(divide="ignore", invalid="ignore"):
        s = {"oov_rate_diff": b["oov"] / b["tokens"] - r["oov"] / r["tokens"],
             "tfidf_centroid_distance": 1 - b["br"] / np.sqrt(b["bb"] * r["rr"]),
             "length_psi": psi(b["length_hist"], r["length_hist"])}
        for m in config.DRIFT_MODELS:
            bm, rm = b[m], r[m]
            s[f"{m}:label_mix_js"] = js_distance(bm["labels"], rm["labels"])
            s[f"{m}:none_share_diff"] = np.abs(bm["none"] / bm["parsed"] - rm["none"] / rm["parsed"])
            s[f"{m}:confidence_psi"] = psi(bm["conf_hist"], rm["conf_hist"])
    return s


def draw_batches(multiplicity: np.ndarray, k: int, n_batches: int, rng) -> np.ndarray:
    """(n_batches, n) weights: k distinct positions of the multiset in which contract c appears
    multiplicity[c] times. Rows sum to k; a bootstrap resample may repeat a contract."""
    pool = np.repeat(np.arange(len(multiplicity)), multiplicity)
    picks = pool[np.argsort(rng.random((n_batches, len(pool))), axis=1)[:, :k]]
    W = np.zeros((n_batches, len(multiplicity)))
    np.add.at(W, (np.repeat(np.arange(n_batches), k), picks.ravel()), 1)
    return W


def upper_p(null_sorted: np.ndarray, v: np.ndarray, loo: bool = False) -> np.ndarray:
    """Upper-tail p-value against the null. loo: v are the null's own members, so the member
    itself counts once in n_ge, giving (1 + #{j != i: null_j >= v_i}) / N. NaN gives 1."""
    n = len(null_sorted)
    n_ge = n - np.searchsorted(null_sorted, v, side="left")
    p = n_ge / n if loo else (1 + n_ge) / (n + 1)
    return np.where(np.isnan(v), 1.0, p)


def groups(stats) -> dict[str, tuple[str, ...]]:
    return {**families(), **{s: (s,) for s in stats}}


def scores(p: dict, stats) -> dict[str, np.ndarray]:
    return {g: np.min([p[s] for s in members], axis=0) for g, members in groups(stats).items()}


def tie_safe_threshold(null_scores: np.ndarray, alpha: float) -> tuple[float, float]:
    """Largest attained score whose null share at or below it is at most alpha, and that share."""
    s = np.sort(null_scores)
    ok = s[np.searchsorted(s, s, side="right") / len(s) <= alpha]
    t = float(ok.max()) if len(ok) else float("-inf")
    return t, float((null_scores <= t).mean())


def null_pairs(sums: dict, W: np.ndarray) -> tuple[dict, dict]:
    """Batch sums and leave-batch-out reference sums for validation batches W."""
    G = (sums["tfidf"] @ sums["tfidf"].T).toarray()
    d = G.sum(axis=1)  # x_c . (sum of all validation vectors)
    b, total = weigh(sums, W), weigh(sums, np.ones((1, W.shape[1])))
    r = {k: (v - b[k] if not isinstance(v, dict) else {kk: vv - b[k][kk] for kk, vv in v.items()})
         for k, v in total.items()}
    b["bb"] = ((W @ G) * W).sum(axis=1)
    all_dot = W @ d
    b["br"] = all_dot - b["bb"]
    r["rr"] = d.sum() - 2 * all_dot + b["bb"]
    return b, r


CONSTANTS = ("SEED", "CI_LEVEL", "DRIFT_MODELS", "DRIFT_BATCH_CONTRACTS", "DRIFT_NULL_BATCHES",
             "DRIFT_ALARM_QUANTILE", "DRIFT_EVAL_BATCHES", "DRIFT_BOOTSTRAP", "DRIFT_BOOTSTRAP_BATCHES",
             "DRIFT_PRIMARY_SETS")


def constants() -> dict:
    return json.loads(json.dumps({k: getattr(config, k) for k in CONSTANTS}))  # tuples as JSON lists


def input_hashes(splits=("val",)) -> dict[str, str]:
    """SHA-256 of the prediction files of the given splits and of the segments file."""
    paths = [config.PREDICTIONS_DIR / f"{m}_{s}.parquet" for s in splits for m in config.DRIFT_MODELS]
    paths.append(config.PROCESSED_DIR / "segments.parquet")
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def freeze_id(ref: dict) -> str:
    body = {k: v for k, v in ref.items() if k != "freeze_id"}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:12]


def load_reference() -> dict:
    path = reference_path()
    if not path.exists():
        raise SystemExit(f"Refusing: {path} is missing; run `python -m src.drift calibrate` first")
    ref = json.loads(path.read_text())
    if freeze_id(ref) != ref.get("freeze_id"):
        raise SystemExit(f"Refusing: {path} does not match its freeze_id (edited after calibration)")
    return ref


def calibrate() -> None:
    seg, preds, versions, _, _ = load_split("val")
    contracts = ordered_contracts(seg["contract_id"])
    ids = contracts["contract_id"].to_numpy()
    length_edges = np.quantile(seg["text"].str.len(), np.arange(1, 10) / 10)
    sums, _ = contract_sums(seg, ids, load_frozen_pipeline().named_steps["tfidf"], length_edges, preds)
    W = draw_batches(np.ones(len(ids), int), config.DRIFT_BATCH_CONTRACTS,
                     config.DRIFT_NULL_BATCHES, stream_rng("drift:null"))
    null = batch_stats(*null_pairs(sums, W))
    nulls = {s: np.sort(v[~np.isnan(v)]) for s, v in null.items()}
    p = {s: upper_p(nulls[s], v, loo=True) for s, v in null.items()}
    alpha = 1 - config.DRIFT_ALARM_QUANTILE
    thresholds = {}
    for g, sc in scores(p, null).items():
        t, rate = tie_safe_threshold(sc, alpha)
        if rate > alpha:
            raise SystemExit(f"{g}: null alarm rate {rate} above {alpha}; a bug in the threshold code")
        thresholds[g] = {"threshold": t, "null_alarm_rate": rate}
    ref = {"constants": constants(), "input_hashes": input_hashes(),
           "versions": versions, "vocabulary_version": baseline_version(),
           "contracts": len(ids), "segments": len(seg),
           "length_edges": length_edges.tolist(), "conf_inner_edges": CONF_INNER_EDGES.tolist(),
           "null": {s: v.tolist() for s, v in nulls.items()},
           "null_nan": {s: int(np.isnan(v).sum()) for s, v in null.items()},
           "thresholds": thresholds}
    ref["freeze_id"] = freeze_id(ref)
    config.DRIFT_DIR.mkdir(parents=True, exist_ok=True)
    reference_path().write_text(json.dumps(ref, indent=2, sort_keys=True))

    print(f"Drift calibration on validation: {len(ids)} contracts, {len(seg)} segments, "
          f"{config.DRIFT_NULL_BATCHES} leave-batch-out batches of {config.DRIFT_BATCH_CONTRACTS} contracts")
    print(f"Versions: {versions}\nVocabulary (baseline) version: {ref['vocabulary_version']}")
    print("\n=== Null per statistic: median, 90th, 99th percentile, NaN batches ===")
    for s, v in nulls.items():
        q = np.quantile(v, [0.5, 0.9, 0.99]) if len(v) else [np.nan] * 3
        print(f"{s:28s} {q[0]:.4f} {q[1]:.4f} {q[2]:.4f}  nan={ref['null_nan'][s]}")
    print(f"\n=== Alarm groups: threshold on min p, exact null alarm rate (at most {alpha:.0%}) ===")
    for g, t in thresholds.items():
        print(f"{g:28s} {t['threshold']:.6f}  {t['null_alarm_rate']:.4f}")
    print(f"\nfreeze_id {ref['freeze_id']}\nWrote {reference_path()}")


def alarms(values: dict, ref: dict) -> dict[str, np.ndarray]:
    p = {s: upper_p(np.asarray(ref["null"][s]), v) for s, v in values.items()}
    return {g: sc <= ref["thresholds"][g]["threshold"] for g, sc in scores(p, values).items()}


def set_view(split_data: dict, key: str):
    """Rows of a split's contracts that belong to the set, in contract order."""
    contracts = split_data["contracts"]
    rows = (np.arange(len(contracts)) if ":" not in key
            else np.flatnonzero(contracts["contract_type"] == key.split(":")[1]))
    return contracts.iloc[rows].reset_index(drop=True), take(split_data["sums"], rows)


def degradation(data: dict, point_batches: dict) -> dict:
    """Spearman (rank Pearson) of each statistic with each model's batch micro-F1 on Rule C
    labels, within test, within shift, and pooled."""
    per = {}
    for key in ("test", "shift"):
        d = data[key]
        W, values = point_batches[key]
        rule_c = label_sets(d["order"])["Rule C"]
        f1 = {}
        for m in config.DRIFT_MODELS:
            failed, y_pred, _ = d["preds"][m]
            counts = per_contract_counts(d["y_true"], y_pred, d["pos"], len(d["contracts"]),
                                         parse_failure=failed)
            f1[m] = f1_metrics(counts, W, rule_c)["micro_f1"]
        per[key] = (values, f1)
    pooled = ({s: np.concatenate([per[k][0][s] for k in per]) for s in per["test"][0]},
              {m: np.concatenate([per[k][1][m] for k in per]) for m in config.DRIFT_MODELS})

    def rho(x, y):
        with np.errstate(invalid="ignore", divide="ignore"):  # a constant series has no correlation: NaN
            return float(pd.Series(x).rank().corr(pd.Series(y).rank()))

    return {name: {m: {s: rho(v[s], f[m]) for s in v} for m in config.DRIFT_MODELS}
            for name, (v, f) in {**per, "pooled": pooled}.items()}


def evaluate(force: bool) -> None:
    ref = load_reference()
    if out_path().exists() and not force:
        raise SystemExit(f"Refusing: {out_path()} exists (drift already evaluated); --force reruns, and is logged")
    if ref["vocabulary_version"] != baseline_version():
        raise SystemExit("the frozen baseline vocabulary differs from the one the reference was built with")
    if ref["conf_inner_edges"] != CONF_INNER_EDGES.tolist():
        raise SystemExit("confidence bin edges differ from the reference")
    if ref["constants"] != constants():
        raise SystemExit(f"settings differ from the reference: {ref['constants']}")
    if ref["input_hashes"] != input_hashes():
        raise SystemExit("validation prediction files or segments changed since calibration")
    vec = load_frozen_pipeline().named_steps["tfidf"]
    edges = np.asarray(ref["length_edges"])
    data = {}
    for split in ("val", "test", "shift"):
        seg, preds, versions, y_true, order = load_split(split)
        if versions != ref["versions"]:
            raise SystemExit(f"{split}: versions {versions} differ from the reference {ref['versions']}")
        contracts = ordered_contracts(seg["contract_id"])
        sums, pos = contract_sums(seg, contracts["contract_id"].to_numpy(), vec, edges, preds)
        data[split] = {"contracts": contracts, "sums": sums, "pos": pos, "preds": preds,
                       "y_true": y_true, "order": order}
    val = data["val"]["sums"]
    r = weigh(val, np.ones((1, len(data["val"]["contracts"]))))
    r_vec = np.asarray(val["tfidf"].sum(axis=0))
    r["rr"] = float((r_vec ** 2).sum())

    def stats_for(sums, G, d, W):
        b = weigh(sums, W)
        b["bb"] = ((W @ G) * W).sum(axis=1)
        b["br"] = W @ d
        return batch_stats(b, r), b

    k = config.DRIFT_BATCH_CONTRACTS
    level = 1 - (1 - config.CI_LEVEL) / (len(families()) * len(config.DRIFT_PRIMARY_SETS))
    out = {"reference_freeze_id": ref["freeze_id"], "versions": ref["versions"],
           "input_hashes": input_hashes(("val", "test", "shift")),
           "adjusted_level": level, "forced": force, "sets": {}}
    point_batches = {}
    for key in EVAL_SETS:
        contracts, sums = set_view(data[key.split(":")[0]], key)
        n = len(contracts)
        G = (sums["tfidf"] @ sums["tfidf"].T).toarray()
        d = np.asarray(sums["tfidf"] @ r_vec.T).ravel()
        W = draw_batches(np.ones(n, int), k, config.DRIFT_EVAL_BATCHES, stream_rng(f"drift:{key}"))
        values, b = stats_for(sums, G, d, W)
        point = {g: float(a.mean()) for g, a in alarms(values, ref).items()}
        ids, Wb = resample_weights(contracts, f"drift:boot:{key}", n_resamples=config.DRIFT_BOOTSTRAP)
        if not np.array_equal(ids, contracts["contract_id"].to_numpy()):
            raise SystemExit(f"{key}: resample ids are not in contract order")
        print(f"  {key}: {n} contracts, bootstrapping {config.DRIFT_BOOTSTRAP} resamples...", flush=True)
        rates = []
        for start in range(0, config.DRIFT_BOOTSTRAP, config.DRIFT_BOOTSTRAP_CHUNK):
            chunk = range(start, min(start + config.DRIFT_BOOTSTRAP_CHUNK, config.DRIFT_BOOTSTRAP))
            Wc = np.vstack([draw_batches(Wb[i], k, config.DRIFT_BOOTSTRAP_BATCHES,
                                         stream_rng(f"drift:boot:{key}:{i}")) for i in chunk])
            a = alarms(stats_for(sums, G, d, Wc)[0], ref)
            rates.append({g: v.reshape(len(chunk), -1).mean(axis=1) for g, v in a.items()})
        rates = {g: np.concatenate([c[g] for c in rates]) for g in rates[0]}
        out["sets"][key] = {
            "contracts": n, "point": point,
            "ci95": {g: list(percentile_ci(v)[:2]) for g, v in rates.items()},
            "ci_adjusted": {f: list(percentile_ci(rates[f], level)[:2]) for f in families()},
            "nan_batches": {s: int(np.isnan(v).sum()) for s, v in values.items()},
            "mean_value": {s: float(np.nanmean(v)) for s, v in values.items()},
            "parse_failure_batches": {m: float((b[m]["parse_failures"] > 0).mean())
                                      for m in config.DRIFT_MODELS}}
        point_batches[key] = (W, values)
    out["rule"] = [{"family": f, "set": s,
                    "lower": out["sets"][s]["ci_adjusted"][f][0],
                    "test_upper": out["sets"]["test"]["ci_adjusted"][f][1],
                    "detects": bool(out["sets"][s]["ci_adjusted"][f][0] > out["sets"]["test"]["ci_adjusted"][f][1])}
                   for f in families() for s in config.DRIFT_PRIMARY_SETS]
    out["degradation"] = degradation(data, point_batches)
    config.EVAL_DIR.mkdir(parents=True, exist_ok=True)
    out_path().write_text(json.dumps(out, indent=2))

    print(f"\nReference freeze_id {ref['freeze_id']}; batches of {k} contracts; "
          f"{config.DRIFT_EVAL_BATCHES} point batches per set; {config.DRIFT_BOOTSTRAP} bootstrap resamples "
          f"x {config.DRIFT_BOOTSTRAP_BATCHES} batches; adjusted level {level:.3%}")
    print("\n=== Family alarm rate by set: point [95% CI] [adjusted CI] ===")
    for f in families():
        for key in EVAL_SETS:
            s = out["sets"][key]
            lo, hi = s["ci95"][f]
            alo, ahi = s["ci_adjusted"][f]
            print(f"{f:9s} {key:22s} {s['point'][f]:.4f} [{lo:.4f}, {hi:.4f}] [{alo:.4f}, {ahi:.4f}]")
    print("\n=== Pre-registered rule: shift adjusted lower bound > test adjusted upper bound ===")
    for c in out["rule"]:
        print(f"{c['family']:9s} {c['set']:22s} lower {c['lower']:.4f}  test upper {c['test_upper']:.4f}  "
              f"detects: {c['detects']}")
    print("\n=== Per-statistic alarm rate by set (point) ===")
    stats = [s for s in out["sets"]["test"]["point"] if s not in families()]
    print(f"{'statistic':28s} " + " ".join(f"{key:>22s}" for key in EVAL_SETS))
    for st in stats:
        print(f"{st:28s} " + " ".join(f"{out['sets'][key]['point'][st]:22.4f}" for key in EVAL_SETS))
    print("\n=== Mean statistic value by set (NaN batches) ===")
    for st in stats:
        print(f"{st:28s} " + " ".join(f"{out['sets'][key]['mean_value'][st]:>14.4f} ({out['sets'][key]['nan_batches'][st]:>4d})"
                                      for key in EVAL_SETS))
    print("\n=== Share of batches with a parse failure ===")
    for m in config.DRIFT_MODELS:
        print(f"{m:9s} " + " ".join(f"{key}={out['sets'][key]['parse_failure_batches'][m]:.4f}" for key in EVAL_SETS))
    print("\n=== Spearman with batch micro-F1 (Rule C), descriptive ===")
    for name, by_model in out["degradation"].items():
        for m, by_stat in by_model.items():
            print(f"{name:7s} {m:9s} " + " ".join(f"{s}={v:+.3f}" for s, v in by_stat.items()))
    print(f"\nWrote {out_path()}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("calibrate")
    e = sub.add_parser("evaluate")
    e.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.cmd == "calibrate":
        calibrate()
    else:
        evaluate(args.force)


if __name__ == "__main__":
    main()

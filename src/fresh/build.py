"""Label exports to fresh segments, through label_contract at the frozen settings.

  python -m src.fresh.build    data/fresh/labels/gold/*.json -> data/processed/fresh_segments.parquet, rule_f.json
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

import pandas as pd

from src import config
from src.build_segments import COLUMNS, load_segments
from src.fresh import config as F
from src.labels import RARE_DROPPED, label_contract, model_label



@cache
def categories_36() -> list[str]:
    """The 33 scored types plus the 3 rare CUAD types. Read on use: web/ is not in the service image."""
    return sorted([*json.loads((config.ROOT_DIR / "web" / "clauses.json").read_text())["label_order"],
                   *RARE_DROPPED])


def checked_spans(text: str, export: dict, contract) -> list[tuple[str, int, int]]:
    cid = contract.contract_id
    if export.get("text_sha256") != contract.text_sha256:
        raise SystemExit(f"{cid}: label export is for a different text")
    checklist = export.get("checklist", {})
    if set(checklist) != set(categories_36()) or not set(checklist.values()) <= {"marked", "not present"}:
        raise SystemExit(f"{cid}: checklist incomplete")
    spans = []
    for s in export["spans"]:
        ok = (s.get("category") in categories_36() and all(type(s.get(k)) is int for k in ("start", "end"))
              and 0 <= s["start"] < s["end"] <= len(text))
        if not ok:
            raise SystemExit(f"{cid}: bad span {s}")
        spans.append((s["category"], s["start"], s["end"]))
    marked = {c for c, _, _ in spans}
    for c, state in checklist.items():
        if (state == "marked") != (c in marked):
            raise SystemExit(f"{cid}: checklist says {state} for {c}, spans disagree")
    return spans


def contract_segments(text: str, export: dict, contract) -> pd.DataFrame:
    spans = checked_spans(text, export, contract)
    rows, _ = label_contract(text, spans, config.SEGMENT_MIN_CHARS, config.SEGMENT_MAX_CHARS,
                             config.SEGMENT_MIN_COVERAGE)
    df = pd.DataFrame(rows)
    df["segment_id"] = [f"{contract.contract_id}_{i}" for i in df["seg_idx"]]
    df["contract_id"], df["contract_type"], df["split"] = int(contract.contract_id), contract.contract_type, "fresh"
    return df[COLUMNS]


def gold_exports() -> dict[int, dict]:
    out = {}
    for path in sorted(F.GOLD_DIR.glob("*.json")):
        export = json.loads(path.read_text())
        if export["contract_id"] in out:
            raise SystemExit(f"two gold exports for contract {export['contract_id']}")
        out[export["contract_id"]] = export
    return out


def contracts_per_label(exports: dict[int, dict]) -> dict[str, int]:
    """Contracts with at least one span of each scored label (as contracts_per_label does for CUAD spans)."""
    counts: dict[str, int] = {}
    for export in exports.values():
        for lab in {model_label(s["category"]) for s in export["spans"]} - {None}:
            counts[lab] = counts.get(lab, 0) + 1
    return dict(sorted(counts.items()))


def load_fresh_segments() -> pd.DataFrame:
    return load_segments(path=F.SEGMENTS)


def refuse_rerun(marker: Path, fresh: bool, force: bool) -> None:
    what = "fresh" if fresh else "test"
    if marker.exists() and not force:
        raise SystemExit(f"Refusing: {what} set already evaluated. It is touched once per model. "
                         f"Override with --i-know-this-reruns-{what}, and log it.")


def heldout_sets(segments: pd.DataFrame, fresh: bool) -> list[tuple[str, pd.DataFrame]]:
    """The sets a one-time run predicts: test and shift, or the fresh set alone."""
    if fresh:
        return [("fresh", load_fresh_segments())]
    return [(s, segments[segments["split"] == s].reset_index(drop=True)) for s in ("test", "shift")]


def main() -> None:
    from src.fresh.source import load_texts
    contracts = pd.read_parquet(F.CONTRACTS)
    texts = load_texts(contracts)
    exports = gold_exports()
    missing = sorted(set(contracts["contract_id"]) - set(exports))
    if missing:
        raise SystemExit(f"no gold export for {missing}")
    seg = pd.concat([contract_segments(texts[c.contract_id], exports[c.contract_id], c)
                     for c in contracts.itertuples()], ignore_index=True)
    seg.to_parquet(F.SEGMENTS, index=False)
    per_label = contracts_per_label({c: exports[c] for c in contracts["contract_id"]})
    rule_f = [lab for lab, n in per_label.items() if n >= config.PER_LABEL_MIN_FRESH_CONTRACTS]
    F.RULE_F.write_text(json.dumps({"contracts_per_label": per_label, "rule_f": rule_f}, indent=2) + "\n")
    kept = seg[~seg["exclude"]]
    print(f"{len(seg)} segments ({int(seg['exclude'].sum())} excluded), {seg['contract_id'].nunique()} contracts; "
          f"none share {(kept['labels'].map(len) == 0).mean():.3f}")
    print(f"Rule F ({len(rule_f)} labels in at least {config.PER_LABEL_MIN_FRESH_CONTRACTS} contracts): {rule_f}")
    print(f"Wrote {F.SEGMENTS} and {F.RULE_F}")


if __name__ == "__main__":
    main()

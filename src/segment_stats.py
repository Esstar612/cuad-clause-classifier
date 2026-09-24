"""Segment statistics on train contracts only, for freezing segmentation thresholds.

Run: python -m src.segment_stats | tee data/processed/segment_stats.txt
"""

from __future__ import annotations

import itertools
from collections import Counter

import pandas as pd

from src import config
from src.data import load_contexts, load_raw_json
from src.labels import label_contract

MIN_CHARS = 50
MAX_CHARS = [1000, 1500, 2500]
MIN_COVERAGE = [0.3, 0.5, 0.7]


def main() -> None:
    pd.set_option("display.width", 200)
    splits = pd.read_parquet(config.PROCESSED_DIR / "splits.parquet")
    train_ids = sorted(splits.loc[splits["split"] == "train", "contract_id"])
    contexts = load_contexts(load_raw_json())
    spans = pd.read_parquet(config.PROCESSED_DIR / "spans.parquet")
    spans = spans[spans["has_answer"] & spans["contract_id"].isin(train_ids)]
    by_contract = {cid: list(zip(g["category"], g["answer_start"], g["answer_end"]))
                   for cid, g in spans.groupby("contract_id")}
    print(f"Train contracts: {len(train_ids)}")

    lines = [ln.strip() for cid in train_ids for ln in contexts[cid].split("\n") if ln.strip()]
    blank_breaks = sum(contexts[cid].count("\n\n") for cid in train_ids)
    all_breaks = sum(contexts[cid].count("\n") for cid in train_ids)
    print(f"Non-empty lines: {len(lines)}, median line length: {pd.Series(map(len, lines)).median()}")
    print(f"Newlines that are part of a blank-line break: {blank_breaks} of {all_breaks}")

    summary = []
    default_rows = None
    for max_chars, min_cov in itertools.product(MAX_CHARS, MIN_COVERAGE):
        rows, found, total = [], 0, 0
        for cid in train_ids:
            seg_rows, merged = label_contract(contexts[cid], by_contract.get(cid, []),
                                              MIN_CHARS, max_chars, min_cov)
            for r in seg_rows:
                r["contract_id"] = cid
            rows.extend(seg_rows)
            for cat, intervals in merged.items():
                for s, e in intervals:
                    total += 1
                    found += any(cat in r["raw_categories"] and r["start"] < e and s < r["end"]
                                 for r in seg_rows)
        df = pd.DataFrame(rows)
        lens = df["end"] - df["start"]
        n_labels = df["labels"].map(len)
        pos = df[n_labels > 0]
        summary.append({
            "max_chars": max_chars, "min_cov": min_cov, "segments": len(df),
            "median_len": int(lens.median()), "p90_len": int(lens.quantile(0.9)),
            "over_max": int((lens > max_chars).sum()),
            "none_pct": round(100 * ((n_labels == 0) & ~df["exclude"]).mean(), 1),
            "excluded": int(df["exclude"].sum()),
            "pos_1_label_pct": round(100 * (pos["labels"].map(len) == 1).mean(), 1),
            "pos_2_label_pct": round(100 * (pos["labels"].map(len) == 2).mean(), 1),
            "pos_3plus_pct": round(100 * (pos["labels"].map(len) >= 3).mean(), 1),
            "span_recall_pct": round(100 * found / total, 1),
        })
        if (max_chars, min_cov) == (1500, 0.5):
            default_rows = df

    print("\n=== Grid (train contracts) ===")
    print(pd.DataFrame(summary).to_string(index=False))

    print("\n=== Segments per label at max_chars=1500, min_cov=0.5 (train) ===")
    counts = Counter(lab for labs in default_rows["labels"] for lab in labs)
    print(pd.Series(counts).sort_values(ascending=False).to_string())

    print("\n=== Examples: Cap On Liability + Uncapped Liability on one segment ===")
    both = default_rows[default_rows["labels"].map(
        lambda labs: "Cap On Liability" in labs and "Uncapped Liability" in labs)]
    print(f"Count: {len(both)}")
    for r in both.head(3).itertuples():
        print(f"\n[contract {r.contract_id}, chars {r.start}-{r.end}]\n{r.text[:500]}")


if __name__ == "__main__":
    main()

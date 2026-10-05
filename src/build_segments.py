"""Build the segment dataset for all 510 contracts with the frozen segmentation settings.

Run: python -m src.build_segments | tee data/processed/build_segments_report.txt
"""

from __future__ import annotations

import pandas as pd

from src import config
from src.data import load_contexts, load_raw_json
from src.labels import label_contract

SEGMENTS_PATH = config.PROCESSED_DIR / "segments.parquet"
COLUMNS = ["segment_id", "contract_id", "contract_type", "split", "seg_idx", "start", "end",
           "text", "labels", "raw_categories", "exclude"]
SPLIT_ORDER = ["train", "val", "test", "shift"]


def build_segments(contexts: dict[int, str], spans: pd.DataFrame, contracts: pd.DataFrame,
                   splits: pd.DataFrame) -> pd.DataFrame:
    pos = spans[spans["has_answer"]]
    by_contract = {cid: list(zip(g["category"], g["answer_start"], g["answer_end"]))
                   for cid, g in pos.groupby("contract_id")}
    ctype = contracts.set_index("contract_id")["contract_type"]
    split_of = splits.set_index("contract_id")["split"]
    rows = []
    for cid in sorted(contexts):
        seg_rows, _ = label_contract(contexts[cid], by_contract.get(cid, []),
                                     config.SEGMENT_MIN_CHARS, config.SEGMENT_MAX_CHARS,
                                     config.SEGMENT_MIN_COVERAGE)
        for r in seg_rows:
            r.update(segment_id=f"{cid}_{r['seg_idx']}", contract_id=cid,
                     contract_type=ctype[cid], split=split_of[cid])
        rows.extend(seg_rows)
    return pd.DataFrame(rows)[COLUMNS]


def load_segments(include_excluded: bool = False, path=SEGMENTS_PATH) -> pd.DataFrame:
    """Segments with labels as Python lists. Excluded segments are dropped unless asked for."""
    df = pd.read_parquet(path)
    if not include_excluded:
        df = df[~df["exclude"]].reset_index(drop=True)
    df["labels"] = df["labels"].map(list)
    return df


def main() -> None:
    pd.set_option("display.width", 200)
    pd.set_option("display.max_rows", 200)
    contexts = load_contexts(load_raw_json())
    spans = pd.read_parquet(config.PROCESSED_DIR / "spans.parquet")
    contracts = pd.read_parquet(config.PROCESSED_DIR / "contracts.parquet")
    splits = pd.read_parquet(config.PROCESSED_DIR / "splits.parquet")
    seg = build_segments(contexts, spans, contracts, splits)
    seg.to_parquet(SEGMENTS_PATH, index=False)

    n_labels = seg["labels"].map(len)
    kept = ~seg["exclude"]
    extraction_only = (n_labels == 0) & kept & (seg["raw_categories"].map(len) > 0)
    summary = pd.DataFrame({
        "segments": seg.groupby("split").size(),
        "excluded": seg[seg["exclude"]].groupby("split").size(),
        "positive": seg[n_labels > 0].groupby("split").size(),
        "none": seg[(n_labels == 0) & kept].groupby("split").size(),
        "none_from_extraction_only": seg[extraction_only].groupby("split").size(),
    }).reindex(SPLIT_ORDER).fillna(0).astype(int)
    summary["none_pct"] = (100 * summary["none"] / (summary["segments"] - summary["excluded"])).round(1)
    print("=== Segments per split ===")
    print(summary.to_string())

    exploded = (seg.loc[kept, ["contract_id", "split", "labels"]]
                .explode("labels").dropna(subset=["labels"]).rename(columns={"labels": "label"}))
    contracts_t = (exploded.groupby(["label", "split"])["contract_id"].nunique()
                   .unstack(fill_value=0).reindex(columns=SPLIT_ORDER, fill_value=0))
    segments_t = (exploded.groupby(["label", "split"]).size()
                  .unstack(fill_value=0).reindex(columns=SPLIT_ORDER, fill_value=0))
    table = pd.concat({"contracts": contracts_t, "segments": segments_t}, axis=1)
    print("\n=== Per label: contracts with a labeled segment, and labeled segments, per split ===")
    print(table.sort_values(("contracts", "test")).to_string())
    print(f"\nLabels present: {len(table)}   Wrote {SEGMENTS_PATH} ({len(seg)} rows)")


if __name__ == "__main__":
    main()

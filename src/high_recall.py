"""High-recall operating point for the review service (Step 7, pre-registered in BUILD_LOG).

  python -m src.high_recall     thresholds for the served models from their validation predictions

Per label: min(Rule B threshold, highest grid threshold with validation recall >= HIGH_RECALL_TARGET).
Validation only, so the reported figures are optimistic; no test or shift data is read.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from src import config
from src.baseline import indicator, load_data
from src.infer import SERVED, artifacts, high_recall_path
from src.metrics import per_label, summary
from src.predictions import read_label_order
from src.thresholds import GRID, apply_thresholds, pooled_labels


def _recall(y, proba, t):
    positives = int(y.sum())
    return int(((proba >= t) & y).sum()) / positives if positives else None


def _t90(y, proba, target):
    for t in GRID[::-1]:
        r = _recall(y, proba, t)
        if r is not None and r >= target:
            return float(t)
    return float(GRID[0])


def recall_thresholds(y, proba, label_order, pooled, rule_b, target=config.HIGH_RECALL_TARGET):
    """high = min(Rule B, t90). Returns (thresholds, per-label achieved validation recall)."""
    y, proba = np.asarray(y, dtype=bool), np.asarray(proba, dtype=float)
    col = {lab: j for j, lab in enumerate(label_order)}
    t90 = {lab: _t90(y[:, col[lab]], proba[:, col[lab]], target)
           for lab in label_order if lab not in pooled}
    if pooled:
        cols = [col[lab] for lab in pooled]
        shared = _t90(y[:, cols], proba[:, cols], target)
        t90.update({lab: shared for lab in pooled})
    high = {lab: (rule_b[lab] if not y[:, col[lab]].any() else min(rule_b[lab], t90[lab]))
            for lab in label_order}
    recall = {lab: _recall(y[:, col[lab]], proba[:, col[lab]], high[lab]) for lab in label_order}
    return high, recall


def validation_predictions(name: str, version: str, label_order: list[str], val: pd.DataFrame):
    """The model's validation proba aligned to `val`; refuses a file from another version or segment set."""
    path = config.PREDICTIONS_DIR / f"{name}_val.parquet"
    df = pd.read_parquet(path)
    if read_label_order(path) != label_order:
        raise SystemExit(f"{name}: validation predictions use another label order")
    if set(df["model_version"]) != {version}:
        raise SystemExit(f"{name}: validation predictions are from {sorted(set(df['model_version']))}, "
                         f"not the served version {version}")
    if df["segment_id"].duplicated().any() or set(df["segment_id"]) != set(val["segment_id"]):
        raise SystemExit(f"{name}: validation predictions do not cover exactly the validation segments")
    df = df.set_index("segment_id").loc[val["segment_id"]]
    if not np.array_equal(indicator(df["true_labels"], label_order), indicator(val["labels"], label_order)):
        raise SystemExit(f"{name}: validation labels differ from the current segments")
    return np.vstack(df["proba"].to_numpy())


def _report(y, proba, label_order, thresholds) -> dict:
    pred = apply_thresholds(proba, label_order, thresholds)
    s = summary(y, pred, proba, label_order)
    t = per_label(y, pred, proba, label_order)
    t = t[t["support"] > 0]
    tp, predicted, support = t["tp"].sum(), t["predicted"].sum(), t["support"].sum()
    return {"micro_f1": s["micro_f1"], "macro_f1": s["macro_f1"], "none_fp_rate": s["none_fp_rate"],
            "micro_precision": float(tp / predicted) if predicted else float("nan"),
            "micro_recall": float(tp / support)}


def main() -> None:
    segments, spans, splits, label_order = load_data()
    val = segments[segments["split"] == "val"].reset_index(drop=True)
    y = indicator(val["labels"], label_order)
    pooled = pooled_labels(spans, splits, label_order)
    config.SERVICE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"High-recall target {config.HIGH_RECALL_TARGET} per label on validation ({len(val)} segments); "
          f"pooled labels ({len(pooled)}): {pooled}. Tuned and reported on validation only, so optimistic.")
    for name in SERVED:
        art = artifacts(name)
        if art.label_order != label_order:
            raise SystemExit(f"{name}: label order differs from the current data")
        proba = validation_predictions(name, art.version, label_order, val)
        high, recall = recall_thresholds(y, proba, label_order, pooled, art.rule_b)
        below = sorted(lab for lab, r in recall.items() if r is not None and r < config.HIGH_RECALL_TARGET)
        out = {"model_version": art.version, "target": config.HIGH_RECALL_TARGET, "thresholds": high,
               "achieved_val_recall": recall, "below_target": below, "pooled": pooled,
               "rule": "min(Rule B, highest grid threshold with validation recall >= target); "
                       "no validation positives keeps Rule B"}
        high_recall_path(name).write_text(json.dumps(out, indent=2, sort_keys=True))
        print(f"\n=== {name} ({art.version}) ===")
        for point, thr in (("balanced (Rule B)", art.rule_b), ("high recall", high)):
            r = _report(y, proba, label_order, thr)
            print(f"  {point:18s} " + "  ".join(f"{k} {v:.4f}" for k, v in r.items()))
        lowered = sum(high[lab] < art.rule_b[lab] for lab in label_order)
        print(f"  thresholds lowered from Rule B: {lowered} of {len(label_order)} labels")
        print(f"  labels below {config.HIGH_RECALL_TARGET} validation recall ({len(below)}): {below}")
        print("  per-label achieved validation recall at the high-recall point:")
        for lab in label_order:
            r = recall[lab]
            print(f"    {lab:36s} threshold {high[lab]:.2f} (Rule B {art.rule_b[lab]:.2f})  "
                  f"recall {'n/a (no positives)' if r is None else f'{r:.4f}'}")
        print(f"  wrote {high_recall_path(name)}")


if __name__ == "__main__":
    main()

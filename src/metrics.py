"""Multi-label metrics on indicator matrices. Point estimates only; confidence intervals come
from the shared contract-level bootstrap in the evaluation step."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

from src.labels import model_label


def contracts_per_label(spans: pd.DataFrame, splits: pd.DataFrame, split: str) -> pd.Series:
    """Contracts in `split` with at least one span of each kept label (the pre-registered counts)."""
    ids = set(splits.loc[splits["split"] == split, "contract_id"])
    pos = spans[spans["has_answer"] & spans["contract_id"].isin(ids)]
    pos = pos.assign(label=pos["category"].map(model_label)).dropna(subset=["label"])
    return pos.groupby("label")["contract_id"].nunique()


def _ratio(num, den) -> np.ndarray:
    return np.divide(num.astype(float), den, out=np.zeros(len(num)), where=den > 0)


def per_label(y_true, y_pred, proba, label_order) -> pd.DataFrame:
    y_true = np.asarray(y_true, dtype=bool)
    y_pred = np.asarray(y_pred, dtype=bool)
    tp = (y_true & y_pred).sum(axis=0)
    fp = (~y_true & y_pred).sum(axis=0)
    fn = (y_true & ~y_pred).sum(axis=0)
    support = y_true.sum(axis=0)
    ap = [average_precision_score(y_true[:, j], proba[:, j]) if support[j] else np.nan
          for j in range(len(label_order))]
    return pd.DataFrame({"label": label_order, "support": support, "predicted": tp + fp, "tp": tp,
                         "precision": _ratio(tp, tp + fp), "recall": _ratio(tp, tp + fn),
                         "f1": _ratio(2 * tp, 2 * tp + fp + fn), "ap": ap})


def summary(y_true, y_pred, proba, label_order, labels=None) -> dict:
    """Macro-F1, micro-F1, and macro-AP over `labels` (default all) that have support > 0,
    plus the share of true-none segments that received at least one label."""
    table = per_label(y_true, y_pred, proba, label_order)
    keep = table["support"] > 0
    if labels is not None:
        keep &= table["label"].isin(sorted(labels))
    t = table[keep]
    tp, fp, fn = t["tp"].sum(), (t["predicted"] - t["tp"]).sum(), (t["support"] - t["tp"]).sum()
    y_true = np.asarray(y_true, dtype=bool)
    y_pred = np.asarray(y_pred, dtype=bool)
    none_rows = ~y_true.any(axis=1)
    return {
        "n_labels": int(keep.sum()),
        "segments": int(len(y_true)),
        "macro_f1": float(t["f1"].mean()),
        "micro_f1": float(2 * tp / (2 * tp + fp + fn)) if (2 * tp + fp + fn) else 0.0,
        "macro_ap": float(t["ap"].mean()),
        "none_segments": int(none_rows.sum()),
        "none_fp_rate": float(y_pred[none_rows].any(axis=1).mean()) if none_rows.any() else float("nan"),
    }

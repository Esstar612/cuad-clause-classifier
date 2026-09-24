"""Rule B threshold tuning, shared by every model (pre-registered 2026-09-23, docs/plan.md).

Per-class thresholds for labels with >= PER_CLASS_THRESHOLD_MIN_VAL_CONTRACTS validation
contracts; one shared threshold, tuned on their pooled decisions, for the rest.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src import config
from src.metrics import contracts_per_label

_N = int(round(1 / config.THRESHOLD_GRID_STEP))
GRID = np.round(np.arange(1, _N) * config.THRESHOLD_GRID_STEP, 4)  # 0.01 .. 0.99
# Searched from 0.5 outward (lower first on equal distance). With a strict ">", the first
# best F1 found wins, so ties go to the threshold closest to 0.5.
_SEARCH_ORDER = sorted(GRID, key=lambda t: (abs(t - 0.5), t))


def pooled_labels(spans: pd.DataFrame, splits: pd.DataFrame, label_order: list[str],
                  min_val_contracts: int = config.PER_CLASS_THRESHOLD_MIN_VAL_CONTRACTS) -> list[str]:
    counts = contracts_per_label(spans, splits, "val")
    return sorted(lab for lab in label_order if counts.get(lab, 0) < min_val_contracts)


def _best_threshold(y_true: np.ndarray, proba: np.ndarray) -> float:
    """Threshold maximizing micro-F1 over the given columns (one column = that label's F1)."""
    best_t, best_f1 = 0.5, -1.0
    positives = int(y_true.sum())
    for t in _SEARCH_ORDER:
        pred = proba >= t
        tp = int((pred & y_true).sum())
        fp = int(pred.sum()) - tp
        fn = positives - tp
        f1 = 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else 0.0
        if f1 > best_f1:
            best_t, best_f1 = float(t), f1
    return best_t


def tune_thresholds(y_true, proba, label_order: list[str], pooled: list[str]) -> dict[str, float]:
    """Validation-only tuning. Returns one threshold per label; pooled labels share one."""
    y_true = np.asarray(y_true, dtype=bool)
    proba = np.asarray(proba, dtype=float)
    col = {lab: j for j, lab in enumerate(label_order)}
    out = {lab: _best_threshold(y_true[:, [col[lab]]], proba[:, [col[lab]]])
           for lab in label_order if lab not in pooled}
    if pooled:
        cols = [col[lab] for lab in pooled]
        shared = _best_threshold(y_true[:, cols], proba[:, cols])
        out.update({lab: shared for lab in pooled})
    return out


def apply_thresholds(proba, label_order: list[str], thresholds: dict[str, float]) -> np.ndarray:
    """Boolean predictions; a row with no True is the none prediction."""
    return np.asarray(proba) >= np.array([thresholds[lab] for lab in label_order])

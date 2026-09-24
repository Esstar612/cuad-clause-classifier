"""Calibration of per-label probabilities: reliability bins and expected calibration error.

Every (segment, label) pair is one prediction. Bins are equal-width on [0, 1] (the top bin
includes 1.0). Bin sums are additive over contracts, so ECE bootstraps with the same weights.
"""

from __future__ import annotations

import numpy as np

from src import config


def _bins(proba: np.ndarray, n_bins: int) -> np.ndarray:
    return np.minimum((proba * n_bins).astype(int), n_bins - 1)


def per_contract_bins(y_true, proba, seg_pos: np.ndarray, n_contracts: int,
                      n_bins: int = config.CALIBRATION_BINS, label_idx=None) -> dict:
    """(C, n_bins) arrays: count, sum of predicted probability, sum of outcomes."""
    y = np.asarray(y_true, dtype=float)
    p = np.asarray(proba, dtype=float)
    if label_idx is not None:
        y, p = y[:, label_idx], p[:, label_idx]
    rows = np.repeat(seg_pos, y.shape[1])
    b = _bins(p.ravel(), n_bins)
    out = {}
    for name, vals in (("count", np.ones(b.size)), ("sum_p", p.ravel()), ("sum_y", y.ravel())):
        m = np.zeros((n_contracts, n_bins))
        np.add.at(m, (rows, b), vals)
        out[name] = m
    return out


def ece_from_bins(count: np.ndarray, sum_p: np.ndarray, sum_y: np.ndarray) -> np.ndarray:
    """ECE = sum_b |sum_y_b - sum_p_b| / N, equal to sum_b (n_b/N) |acc_b - conf_b|.
    Works on (n_bins,) totals or (B, n_bins) resampled totals."""
    return np.abs(sum_y - sum_p).sum(axis=-1) / count.sum(axis=-1)


def reliability_table(bins: dict) -> list[dict]:
    """Totals over contracts: per bin count, mean predicted probability, observed rate."""
    count, sum_p, sum_y = (bins[k].sum(axis=0) for k in ("count", "sum_p", "sum_y"))
    edges = np.linspace(0, 1, len(count) + 1)
    return [{"bin": f"[{edges[i]:.1f}, {edges[i + 1]:.1f}{']' if i == len(count) - 1 else ')'}",
             "count": int(count[i]),
             "mean_predicted": float(sum_p[i] / count[i]) if count[i] else float("nan"),
             "observed_rate": float(sum_y[i] / count[i]) if count[i] else float("nan")}
            for i in range(len(count))]

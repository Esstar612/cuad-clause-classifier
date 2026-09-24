"""Contract-level bootstrap for multi-label metrics (Step 4a).

The resampling unit is the contract (segments of one contract are correlated). Resamples are
stratified by contract type, mirroring the stratified split, and are a pure function of
(seed, stream name, contract ids, contract types): two models evaluated in separate runs see
identical resamples, which is what makes paired comparisons valid. Different streams (for
example "test" and "shift") get independent random sequences.
"""

from __future__ import annotations

import zlib

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

from src import config


def resample_weights(contracts: pd.DataFrame, stream: str,
                     n_resamples: int = config.BOOTSTRAP_RESAMPLES,
                     seed: int = config.SEED) -> tuple[np.ndarray, np.ndarray]:
    """Returns (contract_ids, W). W[b, c] = times contract_ids[c] is drawn in resample b.
    Within each contract type, draw as many contracts as the type has, with replacement."""
    c = (contracts[["contract_id", "contract_type"]].drop_duplicates()
         .sort_values(["contract_type", "contract_id"]).reset_index(drop=True))
    rng = np.random.default_rng([seed, zlib.crc32(stream.encode())])
    blocks = []
    for _, group in c.groupby("contract_type", sort=True):
        n = len(group)
        draws = rng.integers(0, n, size=(n_resamples, n))
        blocks.append((draws[:, :, None] == np.arange(n)).sum(axis=1))
    return c["contract_id"].to_numpy(), np.concatenate(blocks, axis=1)


def per_contract_counts(y_true, y_pred, seg_pos: np.ndarray, n_contracts: int) -> dict:
    """Additive per-contract statistics: tp, fp, fn as (C, L); none and none_fp as (C,).
    seg_pos[i] is the column of segment i's contract in the weight matrix."""
    y_true = np.asarray(y_true, dtype=bool)
    y_pred = np.asarray(y_pred, dtype=bool)
    out = {}
    for name, arr in (("tp", y_true & y_pred), ("fp", ~y_true & y_pred), ("fn", y_true & ~y_pred)):
        m = np.zeros((n_contracts, y_true.shape[1]), dtype=np.int64)
        np.add.at(m, seg_pos, arr.astype(np.int64))
        out[name] = m
    none_rows = ~y_true.any(axis=1)
    out["none"] = np.bincount(seg_pos, weights=none_rows, minlength=n_contracts)
    out["none_fp"] = np.bincount(seg_pos, weights=none_rows & y_pred.any(axis=1),
                                 minlength=n_contracts)
    return out


def f1_metrics(counts: dict, W: np.ndarray, label_idx) -> dict:
    """Per-resample per-label F1 (NaN where the label has no support in that resample),
    macro-F1 over supported labels, micro-F1 over supported labels, none false-positive rate.
    Same conventions as src.metrics.summary; W = ones reproduces the point estimate."""
    TP = W @ counts["tp"][:, label_idx]
    FP = W @ counts["fp"][:, label_idx]
    FN = W @ counts["fn"][:, label_idx]
    support = TP + FN
    per_f1 = np.where(support > 0, 2 * TP / np.maximum(2 * TP + FP + FN, 1), np.nan)
    precision = np.where(TP + FP > 0, TP / np.maximum(TP + FP, 1), 0.0)
    recall = np.where(support > 0, TP / np.maximum(support, 1), np.nan)
    keep = support > 0
    mtp, mfp, mfn = (TP * keep).sum(1), (FP * keep).sum(1), (FN * keep).sum(1)
    den = 2 * mtp + mfp + mfn
    with np.errstate(invalid="ignore"):
        macro = np.nanmean(np.where(keep.any(axis=1, keepdims=True), per_f1, 0.0), axis=1)
    macro = np.where(keep.any(axis=1), macro, np.nan)
    none = W @ counts["none"]
    return {"per_f1": per_f1, "per_precision": precision, "per_recall": recall,
            "macro_f1": macro, "micro_f1": np.where(den > 0, 2 * mtp / np.maximum(den, 1), 0.0),
            "none_fp_rate": np.where(none > 0, (W @ counts["none_fp"]) / np.maximum(none, 1), np.nan)}


def ap_metrics(y_true, proba, seg_pos: np.ndarray, W: np.ndarray, label_idx) -> np.ndarray:
    """Per-resample per-label AP, (B, len(label_idx)); each segment weighted by its
    contract's draw count. NaN where the label has no weighted support."""
    y_true = np.asarray(y_true, dtype=bool)
    out = np.full((W.shape[0], len(label_idx)), np.nan)
    for b in range(W.shape[0]):
        w = W[b, seg_pos]
        for k, j in enumerate(label_idx):
            if (w * y_true[:, j]).sum() > 0:
                out[b, k] = average_precision_score(y_true[:, j], proba[:, j], sample_weight=w)
    return out


def percentile_ci(samples: np.ndarray, level: float = config.CI_LEVEL) -> tuple[float, float, int]:
    """Percentile interval over non-NaN resamples; also returns how many were defined."""
    s = np.asarray(samples, dtype=float)
    s = s[~np.isnan(s)]
    if len(s) == 0:
        return float("nan"), float("nan"), 0
    alpha = (1 - level) / 2
    return float(np.quantile(s, alpha)), float(np.quantile(s, 1 - alpha)), int(len(s))


def paired_difference(a_samples: np.ndarray, b_samples: np.ndarray, a_point: float,
                      b_point: float, level: float = config.CI_LEVEL) -> dict:
    """A minus B on the same resamples. Requires both computed with the same W."""
    lo, hi, n = percentile_ci(np.asarray(a_samples) - np.asarray(b_samples), level)
    return {"difference": a_point - b_point, "ci_low": lo, "ci_high": hi, "n_resamples": n}

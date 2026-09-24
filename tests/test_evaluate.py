"""Evaluation harness: metrics against hand-computed values, bootstrap equivalence and
reproducibility, paired self-comparison exactly zero, ECE against a hand-computed value."""

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import average_precision_score

from src import config
from src.bootstrap import (ap_metrics, f1_metrics, paired_difference, per_contract_counts,
                           percentile_ci, resample_weights)
from src.calibration import ece_from_bins, per_contract_bins
from src.metrics import summary

LABELS = ["A", "B"]
# 4 segments, one contract each. Hand-computed:
#   A: tp=1 (seg 0), fn=1 (seg 1), fp=1 (seg 2) -> F1 = 2/(2+1+1) = 0.5
#   B: tp=2 (segs 1, 2), fp=0, fn=0            -> F1 = 1.0
#   macro-F1 = 0.75; micro: tp=3, fp=1, fn=1   -> 6/8 = 0.75
#   seg 3 is true-none and predicted none      -> none FP rate 0
#   AP(A) with p = [0.9, 0.4, 0.6, 0.1]: ranks 1(+), 2(-), 3(+) -> (1/1 + 2/3) / 2 = 0.8333...
Y_TRUE = np.array([[1, 0], [1, 1], [0, 1], [0, 0]], dtype=bool)
Y_PRED = np.array([[1, 0], [0, 1], [1, 1], [0, 0]], dtype=bool)
PROBA = np.array([[0.9, 0.1], [0.4, 0.8], [0.6, 0.7], [0.1, 0.2]])
SEG_POS = np.arange(4)
ONES = np.ones((1, 4))


def test_f1_metrics_match_hand_computed_values():
    m = f1_metrics(per_contract_counts(Y_TRUE, Y_PRED, SEG_POS, 4), ONES, [0, 1])
    assert m["per_f1"][0].tolist() == [0.5, 1.0]
    assert m["macro_f1"][0] == pytest.approx(0.75)
    assert m["micro_f1"][0] == pytest.approx(0.75)
    assert m["none_fp_rate"][0] == 0.0


def test_ap_matches_hand_computed_value():
    assert ap_metrics(Y_TRUE, PROBA, SEG_POS, ONES, [0])[0, 0] == pytest.approx(5 / 6)


def test_point_estimates_agree_with_metrics_summary():
    s = summary(Y_TRUE, Y_PRED, PROBA, LABELS)
    m = f1_metrics(per_contract_counts(Y_TRUE, Y_PRED, SEG_POS, 4), ONES, [0, 1])
    ap = ap_metrics(Y_TRUE, PROBA, SEG_POS, ONES, [0, 1])[0]
    assert m["macro_f1"][0] == pytest.approx(s["macro_f1"])
    assert m["micro_f1"][0] == pytest.approx(s["micro_f1"])
    assert np.nanmean(ap) == pytest.approx(s["macro_ap"])


def test_weights_equal_explicit_duplication():
    # Contracts: c0 = segs 0-1, c1 = seg 2, c2 = seg 3. Draw c0 twice, c1 zero times, c2 once.
    seg_pos = np.array([0, 0, 1, 2])
    w = np.array([[2, 0, 1]])
    weighted = f1_metrics(per_contract_counts(Y_TRUE, Y_PRED, seg_pos, 3), w, [0, 1])
    rows = [0, 1, 0, 1, 3]
    dup = f1_metrics(per_contract_counts(Y_TRUE[rows], Y_PRED[rows], np.arange(5), 5),
                     np.ones((1, 5)), [0, 1])
    for k in ("macro_f1", "micro_f1", "none_fp_rate"):
        assert weighted[k][0] == pytest.approx(dup[k][0])
    ap_w = ap_metrics(Y_TRUE, PROBA, seg_pos, w, [0])[0, 0]
    assert ap_w == pytest.approx(average_precision_score(Y_TRUE[rows, 0], PROBA[rows, 0]))


def _contracts():
    return pd.DataFrame({"contract_id": range(10),
                         "contract_type": ["X"] * 6 + ["Y"] * 3 + ["Z"]})


def test_resamples_reproducible_and_stream_and_seed_sensitive():
    ids_a, w_a = resample_weights(_contracts(), stream="test", n_resamples=200)
    ids_b, w_b = resample_weights(_contracts(), stream="test", n_resamples=200)
    assert np.array_equal(ids_a, ids_b) and np.array_equal(w_a, w_b)
    _, w_other_stream = resample_weights(_contracts(), stream="shift", n_resamples=200)
    _, w_other_seed = resample_weights(_contracts(), stream="test", n_resamples=200,
                                       seed=config.SEED + 1)
    assert not np.array_equal(w_a, w_other_stream)
    assert not np.array_equal(w_a, w_other_seed)


def test_resamples_are_stratified_by_type():
    c = _contracts()
    ids, w = resample_weights(c, stream="test", n_resamples=200)
    types = c.set_index("contract_id").loc[ids, "contract_type"].to_numpy()
    for t, n in (("X", 6), ("Y", 3), ("Z", 1)):
        assert (w[:, types == t].sum(axis=1) == n).all()


def test_self_comparison_is_exactly_zero():
    rng = np.random.default_rng(config.SEED)
    samples = rng.random(500)
    d = paired_difference(samples, samples, 0.61, 0.61)
    assert d["difference"] == 0 and d["ci_low"] == 0 and d["ci_high"] == 0


def test_percentile_ci_ignores_nan_and_counts_defined():
    lo, hi, n = percentile_ci(np.array([np.nan, 1.0, 2.0, 3.0, np.nan]))
    assert n == 3 and lo <= 2.0 <= hi


def test_ece_matches_hand_computed_value():
    # p = [0.05, 0.95, 0.95], y = [0, 1, 0], 10 bins:
    #   bin 0: |0 - 0.05| = 0.05; bin 9: |1 - 1.9| = 0.9  -> ECE = 0.95 / 3
    y = np.array([[0], [1], [0]], dtype=bool)
    p = np.array([[0.05], [0.95], [0.95]])
    b = per_contract_bins(y, p, np.arange(3), 3, n_bins=10)
    tot = {k: v.sum(axis=0) for k, v in b.items()}
    assert ece_from_bins(tot["count"], tot["sum_p"], tot["sum_y"]) == pytest.approx(0.95 / 3)


def test_harness_point_estimates_match_saved_baseline_summary():
    path = config.PREDICTIONS_DIR / "baseline_test.parquet"
    if not path.exists():
        pytest.skip("baseline_test.parquet missing")
    from src.evaluate import load_predictions

    df, label_order, y_true, y_pred, proba = load_predictions("baseline", "test")
    ids = np.sort(df["contract_id"].unique())
    seg_pos = np.searchsorted(ids, df["contract_id"].to_numpy())
    m = f1_metrics(per_contract_counts(y_true, y_pred, seg_pos, len(ids)),
                   np.ones((1, len(ids))), list(range(len(label_order))))
    s = summary(y_true, y_pred, proba, label_order)
    assert m["macro_f1"][0] == pytest.approx(s["macro_f1"])
    assert m["micro_f1"][0] == pytest.approx(s["micro_f1"])
    assert m["none_fp_rate"][0] == pytest.approx(s["none_fp_rate"])

"""scripts/micro_pr.py: micro precision and recall from the harness's own counts."""

import numpy as np

from scripts.micro_pr import micro
from src.bootstrap import f1_metrics, per_contract_counts

# Same fixture as tests/test_evaluate.py: micro tp=3, fp=1, fn=1.
Y_TRUE = np.array([[1, 0], [1, 1], [0, 1], [0, 0]], dtype=bool)
Y_PRED = np.array([[1, 0], [0, 1], [1, 1], [0, 0]], dtype=bool)
SEG_POS = np.arange(4)
ONES = np.ones((1, 4))


def test_micro_matches_hand_computed_values_and_the_harness_micro_f1():
    counts = per_contract_counts(Y_TRUE, Y_PRED, SEG_POS, 4)
    p, r, f, tp, fp, fn = micro(counts, ONES, [0, 1])
    assert (tp[0], fp[0], fn[0]) == (3, 1, 1)
    assert p[0] == 0.75 and r[0] == 0.75
    assert f[0] == f1_metrics(counts, ONES, [0, 1])["micro_f1"][0]


def test_no_predictions_give_zero_precision_and_zero_recall():
    counts = per_contract_counts(Y_TRUE, np.zeros_like(Y_PRED), SEG_POS, 4)
    p, r, f, *_ = micro(counts, ONES, [0, 1])
    assert (p[0], r[0], f[0]) == (0.0, 0.0, 0.0)


def test_resamples_without_support_are_left_out():
    counts = per_contract_counts(Y_TRUE, Y_PRED, SEG_POS, 4)
    W = np.array([[0, 0, 0, 2]])  # only the true-none segment drawn
    p, r, f, *_ = micro(counts, W, [0, 1])
    assert p[0] == 0.0 and np.isnan(r[0]) and f[0] == 0.0

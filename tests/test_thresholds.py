"""Rule B threshold tuning: per-class vs pooled, deterministic tie-breaking, pre-registered pooled list."""

import numpy as np
import pandas as pd
import pytest

from src import config
from src.labels import label_set
from src.thresholds import GRID, apply_thresholds, pooled_labels, tune_thresholds

PREREGISTERED_POOLED = sorted([
    "No-Solicit Of Customers", "Non-Disparagement", "Most Favored Nation",
    "Third Party Beneficiary", "Joint Ip Ownership",
])


def _random_problem(n=300, k=4):
    rng = np.random.default_rng(config.SEED)
    y = rng.random((n, k)) < 0.2
    p = np.clip(0.55 * y + 0.5 * rng.random((n, k)), 0, 1)
    return y, p


def test_separable_label_tie_goes_to_threshold_closest_to_half():
    y = np.array([[1], [1], [0], [0]], dtype=bool)
    p = np.array([[0.9], [0.8], [0.3], [0.2]])
    # Every threshold in (0.30, 0.80] gives F1 = 1; the tie-break picks 0.5.
    assert tune_thresholds(y, p, ["A"], [])["A"] == 0.5


def test_pooled_labels_share_one_threshold_and_all_labels_get_one():
    y, p = _random_problem()
    th = tune_thresholds(y, p, ["A", "B", "C", "D"], ["C", "D"])
    assert set(th) == {"A", "B", "C", "D"}
    assert th["C"] == th["D"]


def test_tuning_is_deterministic_and_on_grid():
    y, p = _random_problem()
    a = tune_thresholds(y, p, ["A", "B", "C", "D"], ["D"])
    b = tune_thresholds(y, p, ["A", "B", "C", "D"], ["D"])
    assert a == b
    assert all(np.isclose(GRID, t).any() for t in a.values())


def test_empty_prediction_means_none():
    pred = apply_thresholds(np.array([[0.1, 0.2]]), ["A", "B"], {"A": 0.5, "B": 0.5})
    assert not pred.any()


def test_pooled_labels_match_preregistered_list():
    spans_path = config.PROCESSED_DIR / "spans.parquet"
    splits_path = config.PROCESSED_DIR / "splits.parquet"
    if not (spans_path.exists() and splits_path.exists()):
        pytest.skip("spans/splits parquet missing")
    spans = pd.read_parquet(spans_path)
    splits = pd.read_parquet(splits_path)
    label_order = label_set(spans["category"].unique())
    assert pooled_labels(spans, splits, label_order) == PREREGISTERED_POOLED

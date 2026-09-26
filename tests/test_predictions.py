"""Shared prediction format: all columns present, predicted set consistent with probabilities and thresholds."""

import numpy as np
import pandas as pd
import pytest

from src.predictions import SCHEMA, read_label_order, to_prediction_frame, write_predictions
from src.thresholds import apply_thresholds

LABELS = ["A", "B"]


def _frame():
    segments = pd.DataFrame({"segment_id": ["0_0", "0_1"], "contract_id": [0, 0],
                             "split": ["test", "test"], "start": [0, 10], "end": [9, 20],
                             "labels": [["A"], []]})
    proba = np.array([[0.9, 0.1], [0.2, 0.3]])
    pred = apply_thresholds(proba, LABELS, {"A": 0.5, "B": 0.5})
    return to_prediction_frame(segments, proba, pred, LABELS, "m", "v1", 1.5, 0.0)


def test_roundtrip_has_all_columns_and_label_order(tmp_path):
    path = tmp_path / "p.parquet"
    write_predictions(_frame(), path, LABELS, {"latency_ms": "batch-amortized"})
    back = pd.read_parquet(path)
    assert list(back.columns) == SCHEMA.names
    assert not back["parse_failure"].any()  # optional column defaulted
    assert read_label_order(path) == LABELS
    assert (back["cost_usd"] == 0.0).all()


def test_pred_labels_match_thresholded_proba(tmp_path):
    path = tmp_path / "p.parquet"
    write_predictions(_frame(), path, LABELS)
    back = pd.read_parquet(path)
    assert [d["label"] for d in back["pred_labels"][0]] == ["A"]
    assert back["pred_labels"][0][0]["confidence"] == pytest.approx(0.9)
    assert len(back["pred_labels"][1]) == 0  # empty set means none


def test_missing_column_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        write_predictions(_frame().drop(columns=["cost_usd"]), tmp_path / "p.parquet", LABELS)

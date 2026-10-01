import json

import numpy as np
import pytest

from src import config
from src.high_recall import recall_thresholds, validation_predictions
from src.infer import SERVED, high_recall_path
from src.predictions import to_prediction_frame, write_predictions

LABELS = ["A", "B", "C", "D"]


def test_high_recall_never_above_rule_b_and_takes_highest_threshold_reaching_target():
    y = np.array([[1, 1, 0, 0], [1, 1, 0, 0], [1, 1, 0, 0], [0, 0, 0, 0]], dtype=bool)
    proba = np.array([[0.9, 0.95, 0.4, 0], [0.8, 0.95, 0.1, 0], [0.3, 0.95, 0.0, 0], [0.7, 0.1, 0.9, 0]])
    rule_b = {"A": 0.5, "B": 0.2, "C": 0.6, "D": 0.5}
    high, recall = recall_thresholds(y, proba, LABELS, [], rule_b, target=0.9)
    assert high["A"] == 0.3 and recall["A"] == 1.0          # all three positives needed
    assert high["B"] == 0.2                                  # t90 is 0.95, capped by Rule B
    assert high["C"] == 0.6 and recall["C"] is None          # no positives: keeps Rule B
    assert all(high[lab] <= rule_b[lab] for lab in LABELS)


def test_unreachable_target_falls_back_to_lowest_grid_value_and_reports_recall():
    y = np.array([[1], [1]], dtype=bool)
    proba = np.array([[0.0], [0.5]])
    high, recall = recall_thresholds(y, proba, ["A"], [], {"A": 0.7}, target=0.9)
    assert high["A"] == 0.01 and recall["A"] == 0.5


def test_pooled_labels_share_t90_but_report_their_own_recall():
    y = np.array([[1, 0], [1, 0], [0, 1], [0, 0]], dtype=bool)
    proba = np.array([[0.9, 0.0], [0.9, 0.0], [0.0, 0.2], [0.0, 0.0]])
    high, recall = recall_thresholds(y, proba, ["A", "B"], ["A", "B"], {"A": 0.5, "B": 0.5}, target=0.9)
    assert high == {"A": 0.2, "B": 0.2}
    assert recall == {"A": 1.0, "B": 1.0}
    high, recall = recall_thresholds(y, proba, ["A", "B"], ["A", "B"], {"A": 0.1, "B": 0.5}, target=0.9)
    assert high == {"A": 0.1, "B": 0.2}


def _val_file(tmp_path, monkeypatch, version="v1", ids=("s1", "s2")):
    import pandas as pd

    monkeypatch.setattr(config, "PREDICTIONS_DIR", tmp_path)
    seg = pd.DataFrame({"segment_id": list(ids), "contract_id": 0, "split": "val", "start": 0, "end": 1,
                        "labels": [["A"], []]})
    frame = to_prediction_frame(seg, np.array([[0.9, 0.1], [0.2, 0.3]]), np.zeros((2, 2), bool), ["A", "B"],
                                "m", version, 0.0, 0.0)
    write_predictions(frame, tmp_path / "m_val.parquet", ["A", "B"])
    return pd.DataFrame({"segment_id": ["s2", "s1"], "labels": [[], ["A"]]})


def test_guard_accepts_matching_file_and_aligns_to_validation_order(tmp_path, monkeypatch):
    val = _val_file(tmp_path, monkeypatch)
    proba = validation_predictions("m", "v1", ["A", "B"], val)
    assert np.allclose(proba, [[0.2, 0.3], [0.9, 0.1]])


@pytest.mark.parametrize("version,labels,order", [("other", ["A", "B"], ["s2", "s1"]),
                                                  ("v1", ["A", "B"], ["s2", "s3"]),
                                                  ("v1", ["B", "A"], ["s2", "s1"])])
def test_guard_refuses_other_version_segments_or_label_order(tmp_path, monkeypatch, version, labels, order):
    import pandas as pd

    val = _val_file(tmp_path, monkeypatch)
    val = pd.DataFrame({"segment_id": order, "labels": [[], ["A"]]})
    with pytest.raises(SystemExit):
        validation_predictions("m", version, labels, val)


def test_high_recall_files_live_outside_the_hashed_candidate_directory(tmp_path, monkeypatch):
    from src import transformer as T

    d = tmp_path / "cand"
    d.mkdir()
    (d / "thresholds.json").write_text("{}")
    (d / "config.json").write_text("{}")
    before = T.model_version("cand", tmp_path)
    monkeypatch.setattr(config, "SERVICE_DIR", tmp_path / "service")
    for name in SERVED:
        path = high_recall_path(name)
        assert path.parent == config.SERVICE_DIR
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({"thresholds": {}}))
    assert T.model_version("cand", tmp_path) == before

import numpy as np
import pandas as pd
import pytest

from scripts import deploy_parity as D
from src import config

LABELS = ["A", "B"]
THR = {"A": 0.5, "B": 0.5}


def _stored():
    return pd.DataFrame({"segment_id": ["s0", "s1", "s2"], "start": [0, 10, 20], "end": [10, 20, 30],
                         "exclude": [False, False, True], "proba": [[0.9, 0.1], [0.4, 0.6], None]})


def _served(*labels):
    return [{"start": 10 * i, "end": 10 * i + 10, "labels": [{"label": lab, "confidence": c} for lab, c in labs]}
            for i, labs in enumerate(labels)]


def test_identical_flags_have_no_disagreement_and_excluded_segments_are_counted():
    out = D.compare(_served([("A", 0.9)], [("B", 0.6)], []), _stored(), LABELS, THR)
    assert out == {"segments": 2, "excluded": 1, "pairs": 4, "disagree": 0, "flagged_either": 2,
                   "max_conf_diff": pytest.approx(0.0)}


def test_flips_and_confidence_differences_are_counted():
    out = D.compare(_served([("A", 0.88), ("B", 0.55)], [], [("A", 0.7)]), _stored(), LABELS, THR)
    assert out["disagree"] == 2 and out["flagged_either"] == 3
    assert out["max_conf_diff"] == pytest.approx(0.02)


def test_mismatched_segments_or_unknown_labels_are_refused():
    with pytest.raises(SystemExit, match="segments differ"):
        D.compare(_served([], []), _stored(), LABELS, THR)
    with pytest.raises(SystemExit, match="outside the local label order"):
        D.compare(_served([("Z", 0.9)], [], []), _stored(), LABELS, THR)


def test_stored_rows_join_only_proba_and_refuse_a_kept_segment_without_prediction():
    seg = pd.DataFrame({"segment_id": ["s0", "s1", "s2"], "contract_id": 7, "split": "val", "start": [0, 10, 20],
                        "end": [10, 20, 30], "exclude": [False, False, True]})
    pred = pd.DataFrame({"segment_id": ["s0", "s1"], "start": [99, 99], "proba": [[0.9, 0.1], [0.4, 0.6]]})
    rows = D.stored_rows(seg, pred, 7)
    assert list(rows["start"]) == [0, 10, 20] and rows["proba"].isna().tolist() == [False, False, True]
    with pytest.raises(SystemExit, match="contract 7: 1 kept segments"):
        D.stored_rows(seg, pred.iloc[:1], 7)


@pytest.mark.parametrize("model,disagree,pairs,flagged,failed,ok", [
    ("baseline", 0, 1000, 100, 0, True),
    ("baseline", 1, 100000, 10000, 0, False),
    ("baseline", 0, 1000, 100, 1, False),
    ("transformer-tuned", 2, 2000, 200, 0, True),      # 0.1% of pairs, 1% of flagged
    ("transformer-tuned", 3, 2000, 1000, 0, False),    # over 0.1% of pairs
    ("transformer-tuned", 3, 100000, 200, 0, False),   # over 1% of flagged
])
def test_pass_rule(model, disagree, pairs, flagged, failed, ok):
    assert D.passes(model, {"disagree": disagree, "pairs": pairs, "flagged_either": flagged, "failed": failed}) is ok


def test_totals_sum_counts_and_take_the_max_difference():
    parts = [{"segments": 2, "excluded": 1, "pairs": 4, "disagree": 1, "flagged_either": 2, "max_conf_diff": 0.1},
             {"segments": 3, "excluded": 0, "pairs": 6, "disagree": 0, "flagged_either": 1, "max_conf_diff": 0.3}]
    t = D.total(parts, [42])
    assert t["pairs"] == 10 and t["disagree"] == 1 and t["max_conf_diff"] == 0.3 and t["failed"] == 1
    assert t["failed_contracts"] == [42]


def test_sample_is_seeded_and_validation_only():
    seg = pd.DataFrame({"contract_id": np.repeat(np.arange(60), 2),
                        "split": np.repeat(["val"] * 40 + ["test"] * 20, 2)})
    first = D.sample_contracts(seg)
    assert first == D.sample_contracts(seg) and len(first) == config.DEPLOY_PARITY_CONTRACTS
    assert all(c < 40 for c in first)
    mixed = seg.copy()
    mixed.loc[mixed["contract_id"] == first[0], "split"] = ["val", "test"]
    with pytest.raises(SystemExit, match="not a validation contract"):
        D.sample_contracts(mixed)


def test_client_opens_a_fresh_connection_per_request():
    with D.make_client("http://example.test") as client:
        assert client._transport._pool._max_keepalive_connections == 0
        assert client.timeout.read == D.TIMEOUT_S

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


# ----------------------------------------------------------------------------- paired comparisons (Step 4b)

TOY_CONTRACTS = pd.DataFrame({"contract_id": [1, 2, 3, 4],
                              "contract_type": ["License", "License", "Franchise", "Transportation"]})


def test_paired_row_marks_only_the_primary_rows_and_claims_from_the_adjusted_interval():
    from src.evaluate import ADJUSTED_LEVEL, paired_row

    rng = np.random.default_rng(config.SEED)
    noise = rng.normal(0, 0.02, 10_000)
    a, b = 0.8 + noise, 0.5 + rng.normal(0, 0.02, 10_000)
    assert ADJUSTED_LEVEL == pytest.approx(1 - 0.05 / 12)
    d = paired_row("test", "Rule A", "micro_f1", a, b, 0.8, 0.5)
    assert d["primary"] and d["claim"] == "A higher"
    assert d["adjusted_ci_low"] <= d["ci_low"] and d["adjusted_ci_high"] >= d["ci_high"]
    assert paired_row("shift", "Rule C", "macro_f1", b, a, 0.5, 0.8)["claim"] == "B higher"
    assert paired_row("test", "Rule A", "macro_f1", a, a + noise[::-1], 0.8, 0.8)["claim"] == "none"
    for key, scope, metric in (("test", "Rule C", "micro_f1"), ("shift:Franchise", "Rule C", "micro_f1"),
                               ("test", "Rule A", "none_fp_rate")):
        assert "primary" not in paired_row(key, scope, metric, a, b, 0.8, 0.5)
    same = paired_row("test", "Rule A", "micro_f1", a, a, 0.8, 0.8)
    assert all(same[k] == 0 for k in ("difference", "ci_low", "ci_high", "adjusted_ci_low", "adjusted_ci_high"))


def test_scope_verdict_needs_both_metrics_in_one_direction():
    from src.evaluate import scope_verdict

    assert scope_verdict({"micro_f1": "A higher", "macro_f1": "A higher"}, "gemini", "claude") == \
        "gemini higher on both co-primary metrics"
    assert scope_verdict({"micro_f1": "A higher", "macro_f1": "none"}, "gemini", "claude") == \
        "per metric: micro_f1 gemini higher, macro_f1 none"
    assert scope_verdict({"micro_f1": "none", "macro_f1": "none"}, "a", "b").startswith("per metric")


def test_part_default_resamples_and_ap_switch():
    from src.evaluate import Part

    df = pd.DataFrame({"contract_id": [1, 1, 2], "parse_failure": [False] * 3})
    y = np.array([[1, 0], [0, 0], [0, 1]], dtype=bool)
    p = Part("test", df, y, y, y.astype(float), TOY_CONTRACTS)
    assert np.array_equal(p.W, resample_weights(TOY_CONTRACTS[TOY_CONTRACTS["contract_id"] <= 2], "test",
                                                n_resamples=2000)[1])
    q = Part("test", df, y, y, y.astype(float), TOY_CONTRACTS, n_resamples=50, with_ap=False)
    assert q.W.shape[0] == 50 and "macro_ap" not in q.scope([0, 1])[0]
    with pytest.raises(ValueError, match="with_ap=True"):
        q.per_label([0, 1], LABELS)


def _toy_predictions(tmp_path, name, flip):
    from src.predictions import to_prediction_frame, write_predictions

    for split, cids in (("test", [1, 2]), ("shift", [3, 4])):
        seg = pd.DataFrame([{"segment_id": f"{c}_{i}", "contract_id": c, "split": split, "start": 0, "end": 1,
                             "labels": labs} for c in cids for i, labs in enumerate((["A"], ["B"], [], ["A"]))])
        y = np.array([[("A" in l), ("B" in l)] for l in seg["labels"]])
        pred = y.copy()
        pred[3::4, 0] = not flip
        write_predictions(to_prediction_frame(seg, pred.astype(float), pred, LABELS, name, "t", 0.0, 0.0),
                          tmp_path / "pred" / f"{name}_{split}.parquet", LABELS)


def _toy_compare_setup(tmp_path, monkeypatch):
    from src import evaluate

    monkeypatch.setattr(config, "COMPARE_PAIRS", (("ma", "mb"),))
    monkeypatch.setattr(config, "PREDICTIONS_DIR", tmp_path / "pred")
    monkeypatch.setattr(config, "PROCESSED_DIR", tmp_path)
    monkeypatch.setattr(config, "EVAL_DIR", tmp_path / "eval")
    monkeypatch.setattr(evaluate, "label_sets", lambda _order: {"Rule A": [0, 1], "Rule C": [0, 1], "all": [0, 1]})
    TOY_CONTRACTS.to_parquet(tmp_path / "contracts.parquet")
    _toy_predictions(tmp_path, "ma", flip=False)
    _toy_predictions(tmp_path, "mb", flip=True)
    return evaluate


def test_compare_on_toy_files_has_primary_rows_verdicts_and_no_ap_or_nan(tmp_path, monkeypatch):
    import json
    import math

    from src import report

    assert all(a != b for a, b in config.COMPARE_PAIRS)
    evaluate = _toy_compare_setup(tmp_path, monkeypatch)

    evaluate.compare("ma", "mb")
    out = json.loads((tmp_path / "eval" / "compare_ma_vs_mb.json").read_text())
    assert out["method"] == evaluate.COMPARE_METHOD and out["family_size"] == 12
    assert out["a_version"] == out["b_version"] == "t"
    report.check_versions({"ma": {"model_version": "t"}, "mb": {"model_version": "t"}}, {("ma", "mb"): out})
    with pytest.raises(SystemExit, match="family size differs"):
        report.comparison_tables({("ma", "mb"): out, ("mb", "ma"): {**out, "family_size": 6}},
                                 families={"toy": (("ma", "mb"), ("mb", "ma"))})
    with pytest.raises(SystemExit, match="rerun the compare"):
        report.check_versions({"ma": {"model_version": "t2"}, "mb": {"model_version": "t"}}, {("ma", "mb"): out})
    assert sum(bool(d.get("primary")) for d in out["differences"].values()) == 4
    assert set(out["verdicts"]) == {"test | Rule A", "shift | Rule C"}
    assert not any("macro_ap" in k for k in out["differences"])
    assert not any(isinstance(v, float) and math.isnan(v) for d in out["differences"].values() for v in d.values())

    evaluate.compare("ma", "ma")
    same = json.loads((tmp_path / "eval" / "compare_ma_vs_ma.json").read_text())
    assert all(d.get(k, 0) == 0 for d in same["differences"].values()
               for k in ("difference", "ci_low", "ci_high", "adjusted_ci_low", "adjusted_ci_high"))

    evaluate.compare("mb", "ma")
    reverse = json.loads((tmp_path / "eval" / "compare_mb_vs_ma.json").read_text())
    assert not any(d.get("primary") for d in reverse["differences"].values()) and reverse["verdicts"] == {}

    md = report.comparison_tables({("ma", "mb"): out}, families={"toy": (("ma", "mb"),)})
    first = next(d for d in out["differences"].values() if d.get("primary"))
    assert f"{first['difference']:+.4f}" in md and out["verdicts"]["test | Rule A"] in md
    assert "test \\| Rule A \\| micro_f1" in md and "family of 12" in md


def test_compare_refuses_unpaired_or_mixed_files(tmp_path, monkeypatch):
    from src.predictions import write_predictions

    evaluate = _toy_compare_setup(tmp_path, monkeypatch)
    path = tmp_path / "pred" / "mb_shift.parquet"
    df = pd.read_parquet(path)
    write_predictions(df.assign(model_version="t2"), path, LABELS)
    with pytest.raises(SystemExit, match="one version"):
        evaluate.compare("ma", "mb")
    with pytest.raises(SystemExit, match="share one model version"):
        evaluate.evaluate_model("mb")
    write_predictions(df.assign(true_labels=[["B"]] * len(df)), path, LABELS)
    with pytest.raises(SystemExit, match="true labels"):
        evaluate.compare("ma", "mb")
    write_predictions(df.assign(split="test"), path, LABELS)
    with pytest.raises(SystemExit, match="another split"):
        evaluate.compare("ma", "mb")
    write_predictions(df.assign(end=2), path, LABELS)
    with pytest.raises(SystemExit, match="disagree on end"):
        evaluate.compare("ma", "mb")
    write_predictions(df.assign(model_name="other"), path, LABELS)
    with pytest.raises(SystemExit, match="one name"):
        evaluate.compare("ma", "mb")
    write_predictions(pd.concat([df, df.iloc[:1]]), path, LABELS)
    with pytest.raises(SystemExit, match="duplicate segment ids"):
        evaluate.compare("ma", "mb")

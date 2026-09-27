"""Drift checks (Step 5): distances against hand-computed values, the weight-matrix path against
a direct computation, tie-safe thresholds, and calibrate/evaluate on toy files only."""

import json

import numpy as np
import pandas as pd
import pytest
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import Pipeline

from src import config, drift
from src.predictions import to_prediction_frame, write_predictions

LABELS = ["A", "B"]
WORDS = {"License": "license grant royalty territory term party agreement notice".split(),
         "Service": "service provider fees term party agreement notice invoice".split(),
         "Franchise": "franchisee franchisor royalty territory outlet party manual fee".split(),
         "Transportation": "carrier freight shipment volume tonnage party route rate".split()}
TYPES = {"val": ["License"] * 5 + ["Service"] * 5, "test": ["License"] * 3 + ["Service"] * 3,
         "shift": ["Franchise"] * 5 + ["Transportation"] * 5}
REAL = [config.ROOT_DIR / "models" / "drift" / "reference.json", config.ROOT_DIR / "data" / "eval" / "drift.json"]


def _stamp():
    return [(p.exists(), p.stat().st_mtime if p.exists() else None) for p in REAL]


def _toy_world(tmp_path, monkeypatch, splits=("val", "test", "shift")):
    rng = np.random.default_rng(config.SEED)
    for name, value in (("DRIFT_DIR", tmp_path / "drift"), ("EVAL_DIR", tmp_path / "eval"),
                        ("PROCESSED_DIR", tmp_path / "processed"), ("PREDICTIONS_DIR", tmp_path / "pred"),
                        ("DRIFT_NULL_BATCHES", 200), ("DRIFT_EVAL_BATCHES", 20), ("DRIFT_BOOTSTRAP", 12),
                        ("DRIFT_BOOTSTRAP_BATCHES", 4), ("DRIFT_BOOTSTRAP_CHUNK", 5)):
        monkeypatch.setattr(config, name, value)
    (tmp_path / "processed").mkdir()
    contracts, segments, cid = [], [], 0
    for split in ("val", "test", "shift"):
        for ctype in TYPES[split]:
            cid += 1
            contracts.append({"contract_id": cid, "title": f"c{cid}", "contract_type": ctype, "n_chars": 0})
            for i, labs in enumerate((["A"], ["B"], [], ["A", "B"])):
                segments.append({"segment_id": f"{cid}_{i}", "contract_id": cid, "split": split, "start": 0,
                                 "end": 1, "labels": labs,
                                 "text": " ".join(rng.choice(WORDS[ctype], size=6 + i))})
    contracts, segments = pd.DataFrame(contracts), pd.DataFrame(segments)
    contracts.to_parquet(tmp_path / "processed" / "contracts.parquet")
    split_of = segments.drop_duplicates("contract_id").set_index("contract_id")["split"]
    contracts.assign(split=contracts["contract_id"].map(split_of))[["contract_id", "contract_type", "split"]] \
        .to_parquet(tmp_path / "processed" / "splits.parquet")
    segments[["segment_id", "text"]].to_parquet(tmp_path / "processed" / "segments.parquet")
    for split in splits:
        seg = segments[segments["split"] == split].reset_index(drop=True)
        y = np.array([[lab in labs for lab in LABELS] for labs in seg["labels"]])
        for j, m in enumerate(config.DRIFT_MODELS):
            pred = y.copy()
            pred[j::5, 0] = ~pred[j::5, 0]
            proba = np.where(pred, 0.8 - 0.1 * j, 0.05)
            frame = to_prediction_frame(seg, proba, pred, LABELS, m, f"{m}-v", 0.0, 0.0)
            if m == "gemini" and split == "shift":
                frame = frame.assign(parse_failure=frame.index == 0)
            write_predictions(frame, tmp_path / "pred" / f"{m}_{split}.parquet", LABELS)
    train = [" ".join(rng.choice(WORDS[t], size=8)) for t in ("License", "Service") * 20]
    pipe = Pipeline([("tfidf", TfidfVectorizer(ngram_range=(1, 2)))]).fit(train)
    monkeypatch.setattr(drift, "load_frozen_pipeline", lambda: pipe)
    monkeypatch.setattr(drift, "baseline_version", lambda: "vocab-t")
    monkeypatch.setattr(drift, "label_sets", lambda _order: {"Rule A": [0, 1], "Rule C": [0, 1], "all": [0, 1]})
    return pipe.named_steps["tfidf"]


def test_psi_and_js_match_hand_computed_values_for_one_or_many_reference_rows():
    assert drift.psi(np.array([1.0, 1.0]), np.array([1.0, 3.0])) == pytest.approx(0.25 * np.log(3), rel=1e-3)
    rows = drift.psi(np.array([[1.0, 1.0], [1.0, 3.0]]), np.array([[1.0, 3.0], [1.0, 3.0]]))
    assert rows[0] == pytest.approx(0.25 * np.log(3), rel=1e-3) and rows[1] == pytest.approx(0, abs=1e-12)
    assert drift.js_distance(np.array([1.0, 0.0]), np.array([1.0, 1.0])) == pytest.approx(
        np.sqrt((np.log2(4 / 3) + 0.5 * np.log2(2 / 3) + 0.5) / 2))
    assert np.isnan(drift.psi(np.array([[0.0, 0.0], [1.0, 1.0]]), np.array([1.0, 3.0]))[0])
    js = drift.js_distance(np.array([[2.0, 2.0], [1.0, 0.0], [0.0, 0.0]]), np.array([[1.0, 1.0], [0.0, 1.0], [1.0, 1.0]]))
    assert js[0] == pytest.approx(0) and js[1] == pytest.approx(1) and np.isnan(js[2])


def test_unigram_token_and_oov_counts():
    vec = TfidfVectorizer(ngram_range=(1, 2)).fit(["alpha beta", "alpha gamma"])
    seg = pd.DataFrame({"segment_id": ["s0", "s1"], "contract_id": [7, 7], "text": ["alpha delta delta", "beta"]})
    sums, _ = drift.contract_sums(seg, [7], vec, np.array([5.0]), {})
    assert sums["tokens"].tolist() == [4.0] and sums["oov"].tolist() == [2.0]


def _as_one(seg, preds, mask, vec, edges):
    sub = seg[mask].assign(contract_id=0).reset_index(drop=True)
    p = {m: tuple(a[mask] for a in v) for m, v in preds.items()}
    s, _ = drift.contract_sums(sub, [0], vec, edges, p)
    return drift.weigh(s, np.ones((1, 1))), s["tfidf"]


def test_weight_matrix_statistics_equal_a_direct_computation(tmp_path, monkeypatch):
    vec = _toy_world(tmp_path, monkeypatch, splits=("val",))
    seg, preds, _, _, _ = drift.load_split("val")
    ids = drift.ordered_contracts(seg["contract_id"])["contract_id"].to_numpy()
    edges = np.array([30.0, 40.0, 50.0])
    sums, _ = drift.contract_sums(seg, ids, vec, edges, preds)
    batch = ids[[0, 3, 5, 7, 8]]
    W = np.isin(ids, batch).astype(float)[None, :]
    fast = drift.batch_stats(*drift.null_pairs(sums, W))

    in_batch = seg["contract_id"].isin(batch).to_numpy()
    b, xb = _as_one(seg, preds, in_batch, vec, edges)
    r, xr = _as_one(seg, preds, ~in_batch, vec, edges)
    b["bb"], b["br"] = xb.multiply(xb).sum(), (xb @ xr.T).toarray().item()
    r["rr"] = xr.multiply(xr).sum()
    direct = drift.batch_stats(b, r)
    for s, v in direct.items():
        assert np.allclose(fast[s], v, equal_nan=True), s


def test_draw_batches_rows_sum_to_k_and_respect_multiplicity():
    W = drift.draw_batches(np.ones(8, int), 5, 50, drift.stream_rng("t"))
    assert (W.sum(axis=1) == 5).all() and W.max() == 1
    assert np.array_equal(W, drift.draw_batches(np.ones(8, int), 5, 50, drift.stream_rng("t")))
    assert not np.array_equal(W, drift.draw_batches(np.ones(8, int), 5, 50, drift.stream_rng("u")))
    M = drift.draw_batches(np.array([2, 0, 1, 1, 1, 0]), 5, 50, drift.stream_rng("t"))
    assert (M.sum(axis=1) == 5).all() and (M[:, [1, 5]] == 0).all() and (M[:, 0] == 2).all()


def test_upper_p_leave_one_out_new_batch_and_nan():
    null = np.array([1.0, 2.0, 2.0, 3.0])
    loo = drift.upper_p(null, null, loo=True)
    assert loo.tolist() == [(1 + 3) / 4, (1 + 2) / 4, (1 + 2) / 4, (1 + 0) / 4]
    assert drift.upper_p(null, np.array([2.0, 9.0, np.nan])).tolist() == [(1 + 3) / 5, 1 / 5, 1.0]


def test_tie_safe_threshold_holds_the_rate_with_ties():
    assert drift.tie_safe_threshold(np.array([0.1] * 5 + [0.5] * 95), 0.01) == (float("-inf"), 0.0)
    t, rate = drift.tie_safe_threshold(np.array([0.01] + [0.1] * 2 + [0.5] * 97), 0.02)
    assert t == 0.01 and rate == 0.01


def test_calibrate_uses_validation_only_and_every_group_is_at_most_one_percent(tmp_path, monkeypatch):
    before = _stamp()
    _toy_world(tmp_path, monkeypatch, splits=("val",))
    drift.calibrate()
    ref = json.loads((tmp_path / "drift" / "reference.json").read_text())
    assert ref["freeze_id"] == drift.freeze_id(ref)
    assert set(ref["thresholds"]) == set(drift.families()) | set(ref["null"])
    assert all(t["null_alarm_rate"] <= 0.01 for t in ref["thresholds"].values())
    assert ref["versions"] == {m: f"{m}-v" for m in config.DRIFT_MODELS}
    assert _stamp() == before


def test_evaluate_writes_the_rule_and_refuses_unsafe_reruns(tmp_path, monkeypatch):
    before = _stamp()
    _toy_world(tmp_path, monkeypatch)
    with pytest.raises(SystemExit, match="missing"):
        drift.evaluate(force=False)
    drift.calibrate()
    drift.evaluate(force=False)
    out = json.loads((tmp_path / "eval" / "drift.json").read_text())
    assert list(out["sets"]) == list(drift.EVAL_SETS) and len(out["rule"]) == 8
    assert all(isinstance(c["detects"], bool) for c in out["rule"])
    assert out["sets"]["shift:Transportation"]["contracts"] == 5
    assert out["sets"]["shift"]["parse_failure_batches"]["gemini"] > 0
    assert out["sets"]["test"]["parse_failure_batches"]["gemini"] == 0
    assert len(out["input_hashes"]) == 3 * len(config.DRIFT_MODELS) + 1
    with pytest.raises(SystemExit, match="already evaluated"):
        drift.evaluate(force=False)

    monkeypatch.setattr(drift, "baseline_version", lambda: "other")
    with pytest.raises(SystemExit, match="vocabulary"):
        drift.evaluate(force=True)
    monkeypatch.setattr(drift, "baseline_version", lambda: "vocab-t")

    monkeypatch.setattr(config, "DRIFT_BATCH_CONTRACTS", 4)
    with pytest.raises(SystemExit, match="settings differ"):
        drift.evaluate(force=True)
    monkeypatch.setattr(config, "DRIFT_BATCH_CONTRACTS", 5)
    monkeypatch.setattr(config, "DRIFT_BOOTSTRAP", 13)
    with pytest.raises(SystemExit, match="settings differ"):
        drift.evaluate(force=True)
    monkeypatch.setattr(config, "DRIFT_BOOTSTRAP", 12)

    splits_path = tmp_path / "processed" / "splits.parquet"
    splits = pd.read_parquet(splits_path)
    pd.concat([splits, pd.DataFrame({"contract_id": [999], "contract_type": ["License"], "split": ["test"]})]) \
        .to_parquet(splits_path)
    with pytest.raises(SystemExit, match="canonical split"):
        drift.evaluate(force=True)
    splits.to_parquet(splits_path)

    val_path = tmp_path / "pred" / "baseline_val.parquet"
    original = val_path.read_bytes()
    val_df = pd.read_parquet(val_path)
    write_predictions(val_df.assign(latency_ms=1.0), val_path, LABELS)
    with pytest.raises(SystemExit, match="changed since calibration"):
        drift.evaluate(force=True)
    val_path.write_bytes(original)

    path = tmp_path / "pred" / "claude_test.parquet"
    df = pd.read_parquet(path)
    write_predictions(df.assign(split="val"), path, LABELS)
    with pytest.raises(SystemExit, match="another split"):
        drift.evaluate(force=True)
    write_predictions(df.assign(model_version="claude-v2"), path, LABELS)
    with pytest.raises(SystemExit, match="differ from the reference"):
        drift.evaluate(force=True)

    ref_path = tmp_path / "drift" / "reference.json"
    ref = json.loads(ref_path.read_text())
    ref["thresholds"]["input"]["threshold"] = 1.0
    ref_path.write_text(json.dumps(ref))
    with pytest.raises(SystemExit, match="freeze_id"):
        drift.evaluate(force=True)
    assert _stamp() == before


def test_set_view_keeps_only_the_sets_contracts(tmp_path, monkeypatch):
    vec = _toy_world(tmp_path, monkeypatch, splits=("shift",))
    seg, preds, _, _, _ = drift.load_split("shift")
    contracts = drift.ordered_contracts(seg["contract_id"])
    sums, _ = drift.contract_sums(seg, contracts["contract_id"].to_numpy(), vec, np.array([30.0]), preds)
    view, part = drift.set_view({"contracts": contracts, "sums": sums}, "shift:Franchise")
    assert (view["contract_type"] == "Franchise").all() and len(view) == 5
    assert part["tokens"].shape == (5,) and part["tfidf"].shape[0] == 5


def test_baseline_version_refuses_artifacts_that_do_not_match_the_declared_version(tmp_path, monkeypatch):
    (tmp_path / "baseline").mkdir()
    (tmp_path / "baseline" / "config.json").write_text(json.dumps({"model_version": "abc"}))
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(drift, "baseline_artifact_hash", lambda: "abc")
    assert drift.baseline_version() == "abc"
    monkeypatch.setattr(drift, "baseline_artifact_hash", lambda: "def")
    with pytest.raises(SystemExit, match="declared version"):
        drift.baseline_version()


def test_nan_statistic_gives_p_one_and_no_alarm():
    stats = list(drift.INPUT_STATS) + [f"{m}:{s}" for m in config.DRIFT_MODELS for s in drift.MODEL_STATS]
    ref = {"null": {s: np.linspace(0, 1, 99).tolist() for s in stats},
           "thresholds": {g: {"threshold": 0.5} for g in drift.groups(stats)}}
    values = {s: np.array([5.0]) for s in stats}
    values["claude:label_mix_js"] = np.array([np.nan])
    a = drift.alarms(values, ref)
    assert not a["claude:label_mix_js"][0] and a["input"][0] and a["claude"][0]


def test_drift_tables_show_rule_cells_and_refuse_version_mismatch():
    from src.report import drift_tables

    sets = {k: {"point": {"input": 0.25, "oov_rate_diff": 0.1}, "ci95": {"input": [0.1, 0.4]},
                "ci_adjusted": {"input": [0.05, 0.5]}, "mean_value": {"oov_rate_diff": 0.02},
                "nan_batches": {"oov_rate_diff": 0}, "parse_failure_batches": {"gemini": 0.0}}
            for k in ("test", "shift:Franchise")}
    d = {"versions": {"gemini": "g-v"}, "adjusted_level": 1 - 0.05 / 8, "sets": sets,
         "rule": [{"family": "input", "set": "shift:Franchise", "lower": 0.6123, "test_upper": 0.5,
                   "detects": True}],
         "degradation": {"test": {"gemini": {"oov_rate_diff": -0.2}}}}
    md = drift_tables(d, {"gemini": {"model_version": "g-v"}})
    assert "| input | shift:Franchise | 0.6123 | 0.5000 | yes |" in md and "0.2500" in md
    with pytest.raises(SystemExit, match="rerun the drift evaluation"):
        drift_tables(d, {"gemini": {"model_version": "other"}})

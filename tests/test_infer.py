import json
from types import SimpleNamespace

import numpy as np
import pytest

from src import config, infer
from src.infer import Predictor, Scored, ServiceBudget, ServiceUpstream, load_predictors, records
from src.segment import Segment

LABELS = ["A", "B"]
FROZEN = {"model_key": "fireworks-deepseek", "model_id": "accounts/fireworks/models/deepseek-v4p1-flash",
          "version": "v3", "batch_size": 10, "prompt_hash": "8ec29d0ea6ca", "run_settings": {}}


def _predictor(proba, unscored=None):
    proba = np.asarray(proba, dtype=float)
    unscored = np.zeros(len(proba), bool) if unscored is None else np.asarray(unscored)
    return Predictor("stub", "v1", LABELS, {"balanced": {"A": 0.5, "B": 0.5}, "high_recall": {"A": 0.2, "B": 0.5}},
                     lambda texts: Scored(proba, unscored, 1.5, 0.02))


def _segments(n):
    return [Segment(10 * i, 10 * i + 5, "text") for i in range(n)]


def test_records_follow_the_shared_format_and_the_operating_point():
    p = _predictor([[0.3, 0.9], [0.1, 0.1]])
    scored = p.scores(["a", "b"])
    bal = records(_segments(2), scored, p, "balanced")
    assert set(bal[0]) == {"segment_id", "start", "end", "labels", "scored", "model_name", "model_version",
                           "latency_ms", "cost_usd"}
    assert bal[0]["labels"] == [{"label": "B", "confidence": 0.9}] and bal[1]["labels"] == []
    assert bal[0]["start"] == 0 and bal[1]["end"] == 15 and bal[0]["cost_usd"] == pytest.approx(0.01)
    high = records(_segments(2), scored, p, "high_recall")
    assert [lab["label"] for lab in high[0]["labels"]] == ["A", "B"]


def test_unscored_segments_carry_no_labels():
    p = _predictor([[0.9, 0.9]], unscored=[True])
    rec = records(_segments(1), p.scores(["a"]), p, "balanced")[0]
    assert rec["scored"] is False and rec["labels"] == []


class _Ledger:
    cap, prior_total, run_spent, reserved = 5.0, 0.0, 0.0, 0.0


def _patch_llm(monkeypatch, run_result, failures=()):
    from src.llm import run as R

    seen = {}
    monkeypatch.setattr(R, "_messages", lambda call, version, labels: ("sys", "usr", {}, {}))

    def fake_run_calls(model_key, calls, version, namespace, label_order, **kw):
        seen.update(model_key=model_key, version=version, namespace=namespace, calls=calls, **kw)
        result = run_result(calls)
        kw["ledger"].run_spent += 0.001 * len(result.records)
        return result

    def fake_scores(rec, labels):
        return ({sid: {"A": 0.8} for sid in rec["targets"] if sid not in failures},
                [sid for sid in rec["targets"] if sid in failures])

    monkeypatch.setattr(R, "run_calls", fake_run_calls)
    monkeypatch.setattr(R, "record_scores", fake_scores)
    return seen


def _rec(call):
    return {"targets": list(call.targets), "attempts": [{"cost_usd": 0.001}]}


def test_deepseek_path_uses_service_namespace_and_ledger_and_marks_failures(monkeypatch):
    def result(calls):  # the second call fails after retries
        return SimpleNamespace(records={c.key: _rec(c) for i, c in enumerate(calls) if i != 1},
                               failed={calls[1].key: "RuntimeError: gave up"}, stopped=None)

    seen = _patch_llm(monkeypatch, result, failures={"doc_3"})
    ledger, clf = _Ledger(), SimpleNamespace(spec=config.LLM_MODELS["fireworks-deepseek"])
    proba, unscored, cost = infer._deepseek_scores(["t"] * 25, FROZEN, LABELS, ledger, clf, request_cap=10)
    assert seen["namespace"] == "service" and seen["ledger"] is ledger and seen["version"] == "v3"
    assert len(seen["calls"]) == 3
    assert unscored[10:20].all() and unscored[3] and not unscored[:3].any() and not unscored[20:].any()
    assert proba[0, 0] == 0.8 and proba[3].sum() == 0 and cost == pytest.approx(0.002)


def test_deepseek_budget_stop_and_request_cap_raise(monkeypatch):
    _patch_llm(monkeypatch, lambda calls: SimpleNamespace(records={}, failed={}, stopped="cap reached"))
    clf = SimpleNamespace(spec=config.LLM_MODELS["fireworks-deepseek"])
    with pytest.raises(ServiceBudget, match="cap reached"):
        infer._deepseek_scores(["t"] * 5, FROZEN, LABELS, _Ledger(), clf, request_cap=10)
    with pytest.raises(ServiceBudget, match="per-request cap"):
        infer._deepseek_scores(["t"] * 5, FROZEN, LABELS, _Ledger(), clf, request_cap=0.0)
    nearly_spent = _Ledger()
    nearly_spent.prior_total = nearly_spent.cap
    with pytest.raises(ServiceBudget, match="service budget is left"):
        infer._deepseek_scores(["t"] * 5, FROZEN, LABELS, nearly_spent, clf, request_cap=10)


def test_deepseek_all_calls_failing_is_an_upstream_error(monkeypatch):
    _patch_llm(monkeypatch, lambda calls: SimpleNamespace(records={}, failed={c.key: "HTTPStatusError: 401"
                                                                              for c in calls}, stopped=None))
    clf = SimpleNamespace(spec=config.LLM_MODELS["fireworks-deepseek"])
    with pytest.raises(ServiceUpstream, match="401"):
        infer._deepseek_scores(["t"] * 5, FROZEN, LABELS, _Ledger(), clf, request_cap=10)


@pytest.mark.parametrize("research,expected", [(10.0, 5.0), (148.0, 2.0)])
def test_service_ledger_cap_respects_service_and_shared_caps(tmp_path, monkeypatch, research, expected):
    research_path = tmp_path / "ledger.jsonl"
    research_path.write_text(json.dumps({"cost_usd": research}) + "\n")
    monkeypatch.setattr(config, "LLM_LEDGER", research_path)
    monkeypatch.setattr(config, "SERVICE_LEDGER", tmp_path / "service_ledger.jsonl")
    ledger = infer.service_ledger()
    assert ledger.path == config.SERVICE_LEDGER != config.LLM_LEDGER
    assert ledger.cap == pytest.approx(expected)
    assert research_path.read_text() == json.dumps({"cost_usd": research}) + "\n"


def test_load_predictors_excludes_failing_models_with_the_reason():
    def refuses():
        raise SystemExit("artifacts changed since selection")

    ok, failed = load_predictors(["good", "bad", "unknown"],
                                 {"good": lambda: _predictor([[0.1, 0.1]]), "bad": refuses})
    assert list(ok) == ["good"]
    assert "artifacts changed" in failed["bad"] and "unknown model" in failed["unknown"]


def test_deepseek_version_matches_its_validation_predictions():
    import pandas as pd

    path = config.PREDICTIONS_DIR / "fireworks-deepseek_val.parquet"
    if not path.exists() or not (config.PROCESSED_DIR / "segments.parquet").exists():
        pytest.skip("needs the local validation predictions and segments")
    version = infer.artifacts("fireworks-deepseek").version
    assert set(pd.read_parquet(path, columns=["model_version"])["model_version"]) == {version}


def test_high_recall_labels_below_target_are_named_in_the_notes(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SERVICE_DIR", tmp_path)
    art = infer.Artifacts("v1", LABELS, {"A": 0.5, "B": 0.5})
    infer.high_recall_path("m").write_text(json.dumps({"model_version": "v1", "thresholds": {"A": 0.2, "B": 0.5},
                                                       "below_target": ["B"]}))
    thresholds, notes = infer._thresholds("m", art)
    assert thresholds["high_recall"] == {"A": 0.2, "B": 0.5} and "B" in notes["high_recall"]
    infer.high_recall_path("m").write_text(json.dumps({"model_version": "v0", "thresholds": {}, "below_target": []}))
    thresholds, notes = infer._thresholds("m", art)
    assert "high_recall" not in thresholds and "another model version" in notes["high_recall"]

"""Step 3 LLM plumbing without network: response validation, fixed context windows, the seeded
iteration sample, the unstratified iteration comparison, cache keys, cost formulas, the
budget cap, the one-retry rule, and the held-out guard."""

import json

import numpy as np
import pandas as pd
import pytest

from src import config
from src.bootstrap import resample_weights
from src.llm.cache import BudgetExceeded, Ledger, request_hash
from src.llm.clients import Attempt, anthropic_cost, gemini_cost
from src.llm.parse import parse_response
from src.llm.windows import WINDOW, build_calls, iteration_contracts

LABELS = {"Anti-Assignment", "Governing Law"}
HAVE_DATA = (config.CUAD_JSON.exists() and (config.PROCESSED_DIR / "segments.parquet").exists()
             and (config.PROCESSED_DIR / "spans.parquet").exists())
needs_data = pytest.mark.skipif(not HAVE_DATA, reason="CUAD raw data or processed parquet missing")


def _resp(entries) -> str:
    return json.dumps({"segments": entries})


# ----------------------------------------------------------------------------- parsing

def test_valid_response_parses():
    p = parse_response(_resp([{"id": "S1", "labels": [{"label": "Governing Law", "confidence": 0.9}]},
                              {"id": "S2", "labels": []}]), "ok", ["S1", "S2"], LABELS)
    assert p.ok and p.scores == {"S1": {"Governing Law": 0.9}, "S2": {}}


@pytest.mark.parametrize("finish", ["max_tokens", "refusal", "other:RECITATION"])
def test_abnormal_finish_is_invalid(finish):
    p = parse_response(_resp([{"id": "S1", "labels": []}]), finish, ["S1"], LABELS)
    assert not p.ok and p.scores == {}


def test_malformed_json_is_invalid():
    p = parse_response('{"segments": [', "ok", ["S1"], LABELS)
    assert not p.ok and p.scores == {}


def test_missing_target_is_an_error_but_valid_targets_are_kept():
    p = parse_response(_resp([{"id": "S1", "labels": []}]), "ok", ["S1", "S2"], LABELS)
    assert not p.ok and p.scores == {"S1": {}} and any("missing id S2" in e for e in p.errors)


def test_context_or_invented_id_is_an_error():
    p = parse_response(_resp([{"id": "S1", "labels": []}, {"id": "S9", "labels": []}]),
                       "ok", ["S1"], LABELS)
    assert not p.ok and p.scores == {"S1": {}}


def test_duplicate_id_drops_that_segment():
    p = parse_response(_resp([{"id": "S1", "labels": []}, {"id": "S1", "labels": []}]),
                       "ok", ["S1"], LABELS)
    assert not p.ok and "S1" not in p.scores


@pytest.mark.parametrize("item", [{"label": "Made Up", "confidence": 0.5},
                                  {"label": "Governing Law", "confidence": 1.2},
                                  {"label": "Governing Law", "confidence": -0.1},
                                  {"label": "Governing Law", "confidence": True},
                                  {"label": "Governing Law", "confidence": "0.5"}])
def test_bad_label_or_confidence_invalidates_the_segment(item):
    p = parse_response(_resp([{"id": "S1", "labels": [item]}]), "ok", ["S1"], LABELS)
    assert not p.ok and "S1" not in p.scores


def test_repeated_label_keeps_max_confidence():
    items = [{"label": "Governing Law", "confidence": 0.3}, {"label": "Governing Law", "confidence": 0.8}]
    p = parse_response(_resp([{"id": "S1", "labels": items}]), "ok", ["S1"], LABELS)
    assert p.ok and p.scores["S1"] == {"Governing Law": 0.8}



def test_label_below_the_floor_scores_as_unlisted():
    """Rule D: a label listed below the 0.1 floor parses fine but carries no score."""
    items = [{"label": "Governing Law", "confidence": 0.05}, {"label": "Anti-Assignment", "confidence": 0.1}]
    p = parse_response(_resp([{"id": "S1", "labels": items}]), "ok", ["S1"], LABELS)
    assert p.ok and p.scores["S1"] == {"Anti-Assignment": 0.1}

# ----------------------------------------------------------------------------- windows

def _segments(sizes=None) -> pd.DataFrame:
    sizes = sizes or {1: 23, 2: 5}
    rows = [{"segment_id": f"{cid}_{i}", "contract_id": cid, "seg_idx": i,
             "text": f"text {cid}-{i}", "split": "val"}
            for cid, n in sizes.items() for i in range(n)]
    return pd.DataFrame(rows).sample(frac=1, random_state=config.SEED)  # shuffled on purpose


@pytest.mark.parametrize("n", [1, WINDOW])
def test_every_segment_is_targeted_exactly_once(n):
    seg = _segments()
    targets = [t for c in build_calls(seg, n) for t in c.targets]
    assert sorted(targets) == sorted(seg["segment_id"])


def test_batch_size_does_not_change_context():
    """N=1 and N=10 show each segment inside the identical window (user change 2)."""
    seg = _segments()
    ctx = {n: {t: (c.segment_ids, c.texts) for c in build_calls(seg, n) for t in c.targets}
           for n in (1, WINDOW)}
    assert ctx[1] == ctx[WINDOW]


def test_windows_are_fixed_consecutive_and_input_order_independent():
    calls = build_calls(_segments(), WINDOW)
    first = [c for c in calls if c.contract_id == 1]
    assert [len(c.segment_ids) for c in first] == [10, 10, 3]
    assert first[0].segment_ids == tuple(f"1_{i}" for i in range(10))
    again = build_calls(_segments().sort_values("segment_id"), WINDOW)
    assert [c.key for c in calls] == [c.key for c in again]


def test_other_batch_sizes_are_rejected():
    with pytest.raises(ValueError):
        build_calls(_segments(), 5)


@needs_data
def test_iteration_sample_is_seeded_whole_validation_contracts():
    from src.build_segments import load_segments

    segments = load_segments()
    contracts = pd.read_parquet(config.PROCESSED_DIR / "contracts.parquet")
    a = iteration_contracts(segments, contracts)
    b = iteration_contracts(segments, contracts)
    pd.testing.assert_frame_equal(a, b)
    val_ids = set(segments.loc[segments["split"] == "val", "contract_id"])
    assert set(a["contract_id"]) <= val_ids and a["contract_id"].is_unique
    assert a["segments"].sum() >= config.LLM_ITERATION_MIN_SEGMENTS
    val_types = set(contracts.loc[contracts["contract_id"].isin(val_ids), "contract_type"])
    assert set(a["contract_type"]) == val_types          # Rule E: every validation type covered
    if config.LLM_ITERATION_CONTRACTS.exists():
        pd.testing.assert_frame_equal(pd.read_csv(config.LLM_ITERATION_CONTRACTS), a, check_dtype=False)


@needs_data
def test_widened_sample_keeps_the_first_nine_contracts():
    """Rule E changed only the stopping rule, so the seeded draw order is unchanged."""
    from src.build_segments import load_segments

    segments = load_segments()
    contracts = pd.read_parquet(config.PROCESSED_DIR / "contracts.parquet")
    a = iteration_contracts(segments, contracts)
    assert a["contract_id"].tolist()[:9] == [300, 285, 431, 214, 34, 91, 291, 46, 307]


# ----------------------------------------------------------------------------- selection

def test_iteration_comparison_resamples_without_stratification():
    """User fix 1: on the iteration sample a single-contract type must not be redrawn every
    time, as it would be under stratified resampling."""
    from src.llm.selection import unstratified_weights

    ids = list(range(12))
    types = ["A"] * 6 + ["B"] * 5 + ["C"]  # contract 11 is the only "C"
    got, W = unstratified_weights(ids, n_resamples=500)
    col = list(got).index(11)
    assert len(set(W[:, col])) > 1 and (W[:, col] == 0).any()
    assert (W.sum(axis=1) == len(ids)).all()
    strat_ids, Ws = resample_weights(pd.DataFrame({"contract_id": ids, "contract_type": types}),
                                     stream="iteration", n_resamples=500)
    assert (Ws[:, list(strat_ids).index(11)] == 1).all()


def _frame(pred_sets, true_sets, contract_ids):
    return pd.DataFrame({
        "segment_id": [f"s{i}" for i in range(len(pred_sets))],
        "contract_id": contract_ids,
        "true_labels": [sorted(t) for t in true_sets],
        "pred_labels": [[{"label": lab, "confidence": 0.9} for lab in sorted(p)] for p in pred_sets],
        "parse_failure": [False] * len(pred_sets)})


def test_paired_comparison_uses_unstratified_weights_and_self_is_zero(monkeypatch):
    import src.llm.selection as selection

    calls = []
    real = selection.unstratified_weights
    monkeypatch.setattr(selection, "unstratified_weights",
                        lambda ids, **kw: calls.append(list(ids)) or real(ids, n_resamples=300))
    labels = ["Anti-Assignment", "Governing Law"]
    true = [{"Governing Law"}, set(), {"Anti-Assignment"}, set(), {"Governing Law"}, set()]
    pred = [{"Governing Law"}, {"Anti-Assignment"}, set(), set(), {"Governing Law"}, set()]
    a = _frame(pred, true, [0, 0, 1, 1, 2, 2])
    out = selection.paired_micro_f1(a, a.sample(frac=1, random_state=config.SEED), labels)
    assert calls, "paired_micro_f1 must draw its resamples from unstratified_weights"
    d = out["micro_f1"]
    assert d["difference"] == 0 and d["ci_low"] == 0 and d["ci_high"] == 0 and not out["a_better"]


# ----------------------------------------------------------------------------- cache, cost, budget

def test_request_hash_ignores_key_order_and_detects_changes():
    a = {"model": "m", "messages": [{"role": "user", "content": "x"}], "max_tokens": 5}
    b = {"max_tokens": 5, "messages": [{"content": "x", "role": "user"}], "model": "m"}
    assert request_hash(a) == request_hash(b)
    assert request_hash(a) != request_hash({**a, "max_tokens": 6})


def test_cost_formulas_match_hand_computation():
    claude = config.LLM_MODELS["claude"]
    usage = {"input_tokens": 1000, "cache_creation_input_tokens": 2000,
             "cache_read_input_tokens": 3000, "output_tokens": 400}
    expected = (1000 * claude["price_in"] + 2000 * claude["price_cache_write"]
                + 3000 * claude["price_cache_read"] + 400 * claude["price_out"]) / 1e6
    assert anthropic_cost(usage, claude) == pytest.approx(expected)
    gem = config.LLM_MODELS["gemini"]
    gusage = {"prompt_token_count": 5000, "cached_content_token_count": 1000,
              "candidates_token_count": 300, "thoughts_token_count": 200}
    gexpected = (4000 * gem["price_in"] + 1000 * gem["price_cache_read"] + 500 * gem["price_out"]) / 1e6
    assert gemini_cost(gusage, gem) == pytest.approx(gexpected)


def test_budget_cap_refuses_before_the_call(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_text(json.dumps({"cost_usd": 0.9}) + "\n")
    ledger = Ledger(ledger_path, cap_usd=1.0)
    with pytest.raises(BudgetExceeded):
        ledger.reserve(0.2)
    ledger.reserve(0.05)
    ledger.settle(0.05, {"cost_usd": 0.04})
    assert Ledger(ledger_path, cap_usd=1.0).prior_total == pytest.approx(0.94)
    run_capped = Ledger(ledger_path, cap_usd=100.0, run_cap_usd=0.01)
    with pytest.raises(BudgetExceeded):
        run_capped.reserve(0.02)


# ----------------------------------------------------------------------------- runner (stubbed)

class StubClassifier:
    spec = {"price_in": 1.0, "price_out": 1.0, "price_cache_write": 1.0,
            "price_cache_read": 0.1, "max_tokens": 10}

    def __init__(self, responses):
        self.responses, self.sent = list(responses), 0

    def payload(self, system, user, schema):
        return {"system_len": len(system), "user": user}

    def send(self, payload):
        self.sent += 1
        text, finish = self.responses.pop(0)
        return Attempt(text, finish, "stub-model", {"input_tokens": 1}, 0.001, 5.0, 0, 0.0)


def _label_order():
    from src.labels import label_set

    return label_set(pd.read_parquet(config.PROCESSED_DIR / "spans.parquet")["category"].unique())


@needs_data
def test_invalid_response_is_retried_once_then_cached(tmp_path):
    from src.llm.run import run_calls

    calls = build_calls(_segments({7: 2}), WINDOW)
    good = _resp([{"id": "S1", "labels": [{"label": "Governing Law", "confidence": 0.7}]},
                  {"id": "S2", "labels": []}])
    stub = StubClassifier([("not json", "ok"), (good, "ok")])
    ledger = Ledger(tmp_path / "ledger.jsonl", cap_usd=1.0)
    res = run_calls("stub", calls, "v1", "v1", _label_order(), classifier=stub, ledger=ledger,
                    cache_root=tmp_path, workers=1)
    rec = res.records[calls[0].key]
    assert stub.sent == 2 and len(rec["attempts"]) == 2 and rec["parse_failures"] == []
    assert rec["scores"]["7_0"] == {"Governing Law": 0.7}
    again = run_calls("stub", calls, "v1", "v1", _label_order(), classifier=stub, ledger=ledger,
                      cache_root=tmp_path, workers=1)
    assert stub.sent == 2 and again.new_calls == 0  # served from cache, no spend


@needs_data
def test_two_invalid_responses_become_parse_failures(tmp_path):
    from src.llm.run import run_calls

    calls = build_calls(_segments({7: 2}), WINDOW)
    stub = StubClassifier([("{}", "ok"), ("", "max_tokens")])
    res = run_calls("stub", calls, "v1", "v1", _label_order(), classifier=stub,
                    ledger=Ledger(tmp_path / "l.jsonl", cap_usd=1.0), cache_root=tmp_path, workers=1)
    assert res.records[calls[0].key]["parse_failures"] == ["7_0", "7_1"]


@needs_data
def test_budget_stop_sends_nothing(tmp_path):
    from src.llm.run import run_calls

    stub = StubClassifier([])
    res = run_calls("stub", build_calls(_segments({7: 2}), WINDOW), "v1", "v1", _label_order(),
                    classifier=stub, ledger=Ledger(tmp_path / "l.jsonl", cap_usd=0.0),
                    cache_root=tmp_path, workers=1)
    assert stub.sent == 0 and res.stopped and not res.records


@needs_data
def test_soft_checkpoint_stops_before_any_call_unless_approved(tmp_path):
    """Rule E: past the soft checkpoint a command stops before sending anything; approval lets
    it through; calls already cached project nothing and never trip it."""
    from src.llm.run import run_calls, soft_checkpoint

    ledger_path = tmp_path / "l.jsonl"
    ledger_path.write_text(json.dumps({"model_key": "stub", "namespace": "v1", "call_key": "c1_w0_n10_1_0",
                                       "cost_usd": 99.99}) + "\n")
    calls = build_calls(_segments({7: 2}), WINDOW)
    stub = StubClassifier([])
    kw = dict(classifier=stub, ledger_path=ledger_path, cache_root=tmp_path, soft_usd=100.0)
    with pytest.raises(SystemExit):
        soft_checkpoint("stub", [(calls, "v1", "v1")], _label_order(), approved=False, **kw)
    assert stub.sent == 0
    assert soft_checkpoint("stub", [(calls, "v1", "v1")], _label_order(), approved=True,
                           **kw) == pytest.approx(99.99 * len(calls))  # ledger mean per call
    good = _resp([{"id": "S1", "labels": []}, {"id": "S2", "labels": []}])
    run_calls("stub", calls, "v1", "v1", _label_order(), classifier=StubClassifier([(good, "ok")]),
              ledger=Ledger(tmp_path / "other.jsonl", cap_usd=1.0), cache_root=tmp_path, workers=1)
    assert soft_checkpoint("stub", [(calls, "v1", "v1")], _label_order(), approved=False, **kw) == 0.0


@needs_data
def test_soft_checkpoint_falls_back_to_the_offline_estimate(tmp_path):
    from src.llm.run import estimated_call_cost, soft_checkpoint

    calls = build_calls(_segments({7: 2}), WINDOW)
    got = soft_checkpoint("stub", [(calls, "v1", "v1")], _label_order(), approved=False,
                          classifier=StubClassifier([]), ledger_path=tmp_path / "none.jsonl",
                          cache_root=tmp_path)
    assert got == pytest.approx(sum(estimated_call_cost(c, "v1", _label_order(), StubClassifier.spec)
                                    for c in calls))


def test_heldout_guard_blocks_a_completed_run(tmp_path):
    from src.llm.run import heldout_guard

    marker = tmp_path / "heldout_run.json"
    state = heldout_guard(marker, "abc", force=False)  # first run starts
    assert "started_utc" in state
    assert heldout_guard(marker, "abc", force=False)["started_utc"] == state["started_utc"]  # resume
    marker.write_text(json.dumps({**state, "completed_utc": "2026-09-24T00:00:00+00:00"}))
    with pytest.raises(SystemExit):
        heldout_guard(marker, "abc", force=False)
    assert heldout_guard(marker, "abc", force=True)["forced"] is True


# ----------------------------------------------------------------------------- prompt

@needs_data
def test_prompt_definitions_are_verbatim_cuad_and_cover_33_labels():
    from src.data import load_raw_json
    from src.llm.prompt import label_definition, ordered_labels, system_prompt

    qas = load_raw_json()["data"][0]["paragraphs"][0]["qas"]
    details = {qa["id"].rsplit("__", 1)[1]: qa["question"].split("Details: ", 1)[1] for qa in qas}
    labels = _label_order()
    assert len(labels) == 33
    for lab in labels:
        if lab != "Affiliate License":
            assert label_definition(lab) == details[lab]
    merged = label_definition("Affiliate License")
    assert details["Affiliate License-Licensor"] in merged and details["Affiliate License-Licensee"] in merged
    prompt = system_prompt("v1", labels)
    assert all(prompt.count(f'- "{lab}": ') == 1 for lab in labels)
    order = ordered_labels(labels)  # "above" in the CRE definition must point upward
    assert order.index("Competitive Restriction Exception") > max(
        order.index(x) for x in ("Non-Compete", "Exclusivity", "No-Solicit Of Customers"))


def test_user_message_marks_only_targets():
    from src.llm.prompt import user_message

    call = build_calls(_segments({3: 4}), 1)[2]
    msg, local = user_message(call)
    assert msg.count('role="target"') == 1 and msg.count('role="context"') == 3
    assert local["S3"] == call.targets[0]



# ----------------------------------------------------------------------------- probe (Step 3i)

@needs_data
def test_probe_variants_stay_outside_the_versions_and_leave_v1_unchanged():
    from src.llm.prompt import (PROBE_VARIANTS, PROMPT_VERSIONS, REFRAME, output_schema,
                                schema_for, system_prompt)

    labels = _label_order()
    assert not set(PROBE_VARIANTS) & set(PROMPT_VERSIONS)
    assert schema_for("v1", labels) == output_schema(labels)          # v1 cache keys unchanged
    assert system_prompt("probe_A", labels) == system_prompt("v1", labels)
    b = system_prompt("probe_B", labels)
    assert REFRAME in b and b.index(REFRAME) < b.index("Rules:")
    item = schema_for("probe_C", labels)["properties"]["segments"]["items"]["properties"]["labels"]["items"]
    assert list(item["properties"]) == ["label", "evidence", "confidence"]
    assert item["required"] == ["label", "evidence", "confidence"]


def _probe_record(call, listed):
    """A cache-style record whose answer lists `listed` (segment id -> {label: confidence})."""
    local = {f"S{i + 1}": sid for i, sid in enumerate(call.segment_ids)}
    back = {sid: lid for lid, sid in local.items()}
    text = _resp([{"id": back[sid], "labels": [{"label": lab, "confidence": v} for lab, v in listed.get(sid, {}).items()]}
                  for sid in call.targets])
    return {"targets": list(call.targets), "local_ids": local, "parse_failures": [], "prompt_version": "v1",
            "attempts": [{"text": text, "finish": "ok", "usage": {}, "cost_usd": 0.0}],
            "scores": {sid: {lab: v for lab, v in listed.get(sid, {}).items() if v >= 0.1}
                       for sid in call.targets}}


def test_probe_windows_pick_only_failures_and_are_seeded():
    from src.llm.run import probe_stats, probe_windows

    calls = build_calls(_segments({1: 23, 2: 5}), WINDOW)       # 4 windows
    gold = {sid: set() for c in calls for sid in c.targets}
    gold["1_3"], gold["1_15"], gold["2_1"] = {"Governing Law"}, {"Governing Law"}, {"Anti-Assignment"}
    listed = {"1_3": {"Governing Law": 0.0}, "1_15": {"Governing Law": 0.9}, "2_1": {"Anti-Assignment": 0.0}}
    records = {c.key: _probe_record(c, listed) for c in calls}
    chosen, n_failing = probe_windows(records, calls, gold, LABELS, n=5)
    assert n_failing == 2 and {c.key for c in chosen} == {calls[0].key, calls[3].key}
    one, _ = probe_windows(records, calls, gold, LABELS, n=1)
    assert len(one) == 1 and [c.key for c in probe_windows(records, calls, gold, LABELS, n=1)[0]] == [one[0].key]
    stats = probe_stats(records, calls, gold, LABELS, "v1")
    assert stats["recall"] == round(1 / 3, 4) and stats["gold_listed_below_0.1"] == 2


# ----------------------------------------------------------------------------- raw-text scoring, run health, reruns, held-out rule

def _record(targets, answer, stored_scores=None, extra_attempts=()):
    local = {f"S{i + 1}": sid for i, sid in enumerate(targets)}
    return {"targets": list(targets), "local_ids": local, "parse_failures": [], "prompt_version": "v1",
            "scores": stored_scores if stored_scores is not None else {},
            "created_utc": "2026-09-25T00:00:00+00:00",
            "attempts": [*extra_attempts, {"text": answer, "finish": "ok", "latency_ms": 10.0,
                                           "cost_usd": 0.01, "usage": {}}]}


def test_record_scores_reparse_old_records_with_the_floor():
    from src.llm.run import record_scores

    answer = _resp([{"id": "S1", "labels": [{"label": "Governing Law", "confidence": 0.0},
                                            {"label": "Anti-Assignment", "confidence": 0.05},
                                            {"label": "Anti-Assignment", "confidence": 0.4}]}])
    scores, failures = record_scores(_record(["7_0", "7_1"], answer, {"7_0": {"Governing Law": 0.0}}), LABELS)
    assert scores == {"7_0": {"Anti-Assignment": 0.4}} and failures == ["7_1"]


@needs_data
def test_build_frame_uses_reparsed_not_stored_scores():
    from src.llm.run import RunResult, build_frame

    seg = _segments({7: 2}).assign(start=0, end=1, labels=[[], []])
    call = build_calls(seg, WINDOW)[0]
    answer = _resp([{"id": "S1", "labels": [{"label": "Governing Law", "confidence": 0.9}]},
                    {"id": "S2", "labels": []}])
    rec = _record(call.targets, answer, {"7_0": {"Anti-Assignment": 0.99}})
    frame = build_frame(seg, [call], RunResult(records={call.key: rec}), _label_order(), {}, "stub", "t")
    got = dict(zip(frame["segment_id"], frame["pred_labels"]))
    assert [d["label"] for d in got["7_0"]] == ["Governing Law"] and got["7_1"] == []


def _health_records():
    low = _resp([{"id": "S1", "labels": [{"label": "Governing Law", "confidence": 0.0}]},
                 {"id": "S2", "labels": [{"label": "Anti-Assignment", "confidence": 0.8}]}])
    listed = _resp([{"id": "S1", "labels": [{"label": "Governing Law", "confidence": 0.7},
                                            {"label": "Anti-Assignment", "confidence": 0.6}]},
                    {"id": "S2", "labels": []}])
    return [_record(["1_0", "1_1"], low), _record(["2_0", "2_1", "2_2"], listed)]


def test_run_health_counts_and_descriptives():
    from src.llm.run import run_health

    h = run_health(_health_records(), "v1", LABELS)
    assert h["calls"] == 2 and h["below_floor_calls"] == 1 and h["below_floor_share"] == 0.5
    assert h["parse_failed_segments"] == 1
    assert h["empty_set_share"] == 0.5 and h["mean_labels_listed"] == 0.75


def test_run_health_flags_both_formats_alike():
    from src.llm.run import run_health

    low = [{"label": "Governing Law", "confidence": 0.0}]
    keyed = _record(["1_0"], json.dumps({"segments": {"S1": low}}))
    as_list = _record(["1_0"], _resp([{"id": "S1", "labels": low}]))
    assert run_health([keyed], "v1", LABELS)["below_floor_calls"] == 1
    assert run_health([as_list], "v1", LABELS)["below_floor_calls"] == 1


@pytest.mark.parametrize("field", ["local_ids", "attempts"])
def test_run_health_missing_field_raises(field):
    from src.llm.run import run_health

    rec = _health_records()[1]
    del rec[field]
    with pytest.raises(KeyError):
        run_health([rec], "v1", LABELS)


def test_run_health_refuses_dense_versions(monkeypatch):
    from src.llm import prompt
    from src.llm.run import run_health

    monkeypatch.setitem(prompt.PROMPT_VERSIONS, "vdense", {"instructions": "", "output": "dense"})
    with pytest.raises(ValueError):
        run_health(_health_records(), "vdense", LABELS)


@needs_data
def test_rerun_sends_the_same_request_to_a_new_cache_path(tmp_path):
    from src.llm.cache import cache_path
    from src.llm.run import _request

    call = build_calls(_segments({7: 2}), WINDOW)[0]
    h = request_hash(_request(call, "v1", _label_order(), StubClassifier([]))[3])
    assert cache_path("claude", "v1", call.key, h, tmp_path) != cache_path("claude", "v1-r2", call.key, h, tmp_path)


def test_heldout_invalid_split_gets_exactly_one_redo():
    from src.llm.run import split_namespace, record_health

    state = {}
    assert split_namespace(state, "test", "v2", redo=False) == "v2"
    assert record_health(state, "test", {"below_floor_share": 0.04}) == "ok"
    assert record_health(state, "shift", {"below_floor_share": 0.2}) == "invalid"
    with pytest.raises(SystemExit):
        split_namespace(state, "shift", "v2", redo=False)
    assert split_namespace(state, "shift", "v2", redo=True) == "v2-redo1"
    assert record_health(state, "shift", {"below_floor_share": 0.3}) == "unreliable"
    assert split_namespace(state, "shift", "v2", redo=True) == "v2-redo1"
    assert record_health(state, "shift", {"below_floor_share": 0.01}) == "ok"
    assert "shift" in state["redone"] and split_namespace(state, "test", "v2", redo=False) == "v2"


# ----------------------------------------------------------------------------- v2 keyed format

@needs_data
@pytest.mark.parametrize("n", [1, WINDOW])
def test_v2_schema_requires_exactly_the_call_targets(n):
    from src.llm.prompt import output_schema, schema_for, user_message

    labels = _label_order()
    for call in build_calls(_segments({1: 23}), n):
        local = user_message(call)[1]
        ids = [lid for lid, sid in local.items() if sid in call.targets]
        segs = schema_for("v2", labels, ids)["properties"]["segments"]
        assert list(segs["properties"]) == ids and segs["required"] == ids
        assert segs["additionalProperties"] is False
        assert schema_for("v1", labels, ids) == output_schema(labels)


def test_parser_reads_keyed_answers_and_flags_wrong_keys():
    keyed = json.dumps({"segments": {"S1": [{"label": "Governing Law", "confidence": 0.9}], "S2": []}})
    p = parse_response(keyed, "ok", ["S1", "S2"], LABELS)
    assert p.ok and p.scores == {"S1": {"Governing Law": 0.9}, "S2": {}}
    extra = parse_response(json.dumps({"segments": {"S1": [], "S2": [], "S3": []}}), "ok", ["S1", "S2"], LABELS)
    assert not extra.ok and extra.scores == {"S1": {}, "S2": {}}
    missing = parse_response(json.dumps({"segments": {"S1": []}}), "ok", ["S1", "S2"], LABELS)
    assert not missing.ok and any("missing id S2" in e for e in missing.errors)


@needs_data
def test_v2_prompt_carries_the_approved_additions():
    from src.llm.prompt import REFRAME, system_prompt

    text = system_prompt("v2", _label_order())
    assert REFRAME in text and "Never list a category with confidence below 0.1." in text
    assert "deems a change of control to be an assignment" in text
    assert "the notice period to prevent renewal, or how long a warranty lasts" in text


# ----------------------------------------------------------------------------- v3 retrieval

HAVE_BASELINE = (config.MODELS_DIR / "baseline" / "model.joblib").exists()
needs_baseline = pytest.mark.skipif(not (HAVE_DATA and HAVE_BASELINE), reason="baseline model or data missing")


def _tiny_index():
    from sklearn.feature_extraction.text import TfidfVectorizer

    from src.llm.retrieval import TrainIndex

    rows = [(2, 0, "the agreement is governed by the laws of new york", ["Governing Law"], False),
            (1, 5, "the agreement is governed by the laws of new york", ["Governing Law"], False),
            (1, 1, "this agreement is governed by the laws of the state of new york", [], False),
            (3, 0, "the agreement is governed by the laws of new york", [], True),
            (1, 2, "payment is due within thirty days of invoice", [], False)]
    seg = pd.DataFrame([{"segment_id": f"{c}_{i}", "contract_id": c, "seg_idx": i, "text": t,
                         "labels": labs, "exclude": ex, "split": "train"} for c, i, t, labs, ex in rows])
    vec = TfidfVectorizer().fit(seg["text"])
    return TrainIndex(seg, vec), vec


def test_retrieval_ties_go_to_the_earlier_segment_and_examples_are_distinct():
    index, _ = _tiny_index()
    ex = index.examples_for(["the agreement is governed by the laws of new york"])
    assert [e["segment_id"] for e in ex] == ["1_5", "2_0"]
    assert ex[0]["labels"] == ["Governing Law"]
    assert "3_0" not in index.segment_ids


def test_retrieval_deduplicates_within_a_call():
    index, _ = _tiny_index()
    text = "the agreement is governed by the laws of new york"
    ids = [e["segment_id"] for e in index.examples_for([text, text])]
    assert len(ids) == len(set(ids)) == 2


def test_retrieval_refuses_unnormalised_vectors():
    from sklearn.feature_extraction.text import TfidfVectorizer

    from src.llm.retrieval import TrainIndex

    with pytest.raises(ValueError):
        TrainIndex(pd.DataFrame({"split": [], "exclude": []}), TfidfVectorizer(norm=None))


@needs_baseline
def test_retrieval_uses_gold_labels_from_non_excluded_train_segments():
    from src.build_segments import load_segments
    from src.llm.retrieval import train_index

    everything = load_segments(include_excluded=True).set_index("segment_id")
    index = train_index()
    queries = everything[everything["split"] == "val"]["text"].head(20).tolist()
    first = index.examples_for(queries)
    assert first == index.examples_for(queries)
    for e in first:
        row = everything.loc[e["segment_id"]]
        assert row["split"] == "train" and not row["exclude"]
        assert e["labels"] == sorted(row["labels"])
    excluded = everything[(everything["split"] == "train") & everything["exclude"]]
    for sid, text in excluded["text"].head(10).items():
        assert sid not in {e["segment_id"] for e in index.examples_for([text])}
    assert all(index.examples_for([q])[0]["labels"] for q in queries[:5])


@needs_data
def test_v1_and_v2_messages_unchanged_and_v3_examples_precede_the_window():
    from src.llm.prompt import EXAMPLES_PARAGRAPH, system_prompt, user_message

    call = build_calls(_segments({7: 12}), 1)[3]
    plain, local = user_message(call)
    assert plain.startswith("<window>") and user_message(call, None) == (plain, local)
    examples = [{"segment_id": "x", "text": "sample clause", "labels": ["Governing Law", "Anti-Assignment"]},
                {"segment_id": "y", "text": "other clause", "labels": []}]
    msg, _ = user_message(call, examples)
    assert msg.index("<examples>") < msg.index("<window>") and msg.endswith(plain)
    assert '<example labels="Governing Law; Anti-Assignment">' in msg and '<example labels="none">' in msg
    assert msg.count('role="target"') == len(call.targets)
    labels = _label_order()
    v2, v3 = system_prompt("v2", labels), system_prompt("v3", labels)
    assert v3.replace(EXAMPLES_PARAGRAPH + "\n\n", "", 1) == v2


# ----------------------------------------------------------------------------- review fixes (Step 3x)

@needs_data
def test_paid_attempt_survives_a_failed_retry_and_resume_sends_only_the_retry(tmp_path):
    from src.llm.run import run_calls

    calls = build_calls(_segments({7: 2}), WINDOW)
    ledger_path = tmp_path / "l.jsonl"
    first = StubClassifier([("not json", "ok")])
    res = run_calls("stub", calls, "v1", "v1", _label_order(), classifier=first,
                    ledger=Ledger(ledger_path, cap_usd=1.0), cache_root=tmp_path, workers=1)
    assert first.sent == 2 and calls[0].key in res.failed
    good = _resp([{"id": "S1", "labels": []}, {"id": "S2", "labels": []}])
    second = StubClassifier([(good, "ok")])
    res = run_calls("stub", calls, "v1", "v1", _label_order(), classifier=second,
                    ledger=Ledger(ledger_path, cap_usd=1.0), cache_root=tmp_path, workers=1)
    rec = res.records[calls[0].key]
    assert second.sent == 1 and len(rec["attempts"]) == 2 and not rec["retry_pending"]
    paid = [json.loads(line)["attempt"] for line in ledger_path.read_text().splitlines()]
    assert paid == [1, 2]


def test_a_worse_retry_keeps_segments_the_first_attempt_parsed():
    from src.llm.run import record_scores

    first = _resp([{"id": "S1", "labels": [{"label": "Governing Law", "confidence": 0.9}]}])
    rec = _record(["7_0", "7_1"], "", extra_attempts=[{"text": first, "finish": "ok"}])
    rec["attempts"][-1]["finish"] = "max_tokens"
    scores, failures = record_scores(rec, LABELS)
    assert scores == {"7_0": {"Governing Law": 0.9}} and failures == ["7_1"]


@needs_data
def test_checkpoint_projects_only_from_the_same_prompt_version(tmp_path):
    from src.llm.run import estimated_call_cost, soft_checkpoint

    ledger_path = tmp_path / "l.jsonl"
    ledger_path.write_text(json.dumps({"model_key": "stub", "namespace": "v2", "call_key": "c1_w0_n10_1_0",
                                       "cost_usd": 5.0}) + "\n")
    calls = build_calls(_segments({7: 2}), WINDOW)
    got = soft_checkpoint("stub", [(calls, "v1", "v1")], _label_order(), approved=True,
                          classifier=StubClassifier([]), ledger_path=ledger_path, cache_root=tmp_path)
    assert got == pytest.approx(sum(estimated_call_cost(c, "v1", _label_order(), StubClassifier.spec)
                                    for c in calls))


@needs_data
def test_frozen_run_refuses_changed_model_settings(tmp_path, monkeypatch):
    from src.llm import run

    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    (tmp_path / "claude").mkdir()
    (tmp_path / "claude" / "prompt.json").write_text(json.dumps({
        "version": "v1", "prompt_hash": run.prompt_hash("v1", run._label_order_cached()),
        "run_settings": run.run_settings("claude")}))
    assert run.load_frozen("claude")["version"] == "v1"
    monkeypatch.setitem(config.LLM_MODELS, "claude", {**config.LLM_MODELS["claude"], "effort": "medium"})
    with pytest.raises(SystemExit):
        run.load_frozen("claude")


# ----------------------------------------------------------------------------- review fixes (Step 3y)

def _pending_record_path(tmp_path):
    return next(p for p in tmp_path.rglob("*.json"))


@needs_data
def test_checkpoint_projects_calls_still_awaiting_their_retry(tmp_path):
    from src.llm.run import run_calls, soft_checkpoint

    calls = build_calls(_segments({7: 2}), WINDOW)
    ledger_path = tmp_path / "l.jsonl"
    run_calls("stub", calls, "v1", "v1", _label_order(), classifier=StubClassifier([("not json", "ok")]),
              ledger=Ledger(ledger_path, cap_usd=1.0), cache_root=tmp_path, workers=1)
    assert json.loads(_pending_record_path(tmp_path).read_text())["retry_pending"] is True
    kw = dict(classifier=StubClassifier([]), ledger_path=ledger_path, cache_root=tmp_path)
    assert soft_checkpoint("stub", [(calls, "v1", "v1")], _label_order(), approved=True, **kw) == pytest.approx(0.001)
    good = _resp([{"id": "S1", "labels": []}, {"id": "S2", "labels": []}])
    run_calls("stub", calls, "v1", "v1", _label_order(), classifier=StubClassifier([(good, "ok")]),
              ledger=Ledger(ledger_path, cap_usd=1.0), cache_root=tmp_path, workers=1)
    assert soft_checkpoint("stub", [(calls, "v1", "v1")], _label_order(), approved=True, **kw) == 0.0


@needs_data
def test_pending_record_that_now_parses_resumes_without_a_retry(tmp_path):
    from src.llm.run import run_calls

    calls = build_calls(_segments({7: 2}), WINDOW)
    run_calls("stub", calls, "v1", "v1", _label_order(), classifier=StubClassifier([("not json", "ok")]),
              ledger=Ledger(tmp_path / "l.jsonl", cap_usd=1.0), cache_root=tmp_path, workers=1)
    path = _pending_record_path(tmp_path)
    rec = json.loads(path.read_text())
    rec["attempts"][0]["text"] = _resp([{"id": "S1", "labels": []}, {"id": "S2", "labels": []}])
    assert rec["attempts"][0]["parse_errors"]
    path.write_text(json.dumps(rec))
    stub = StubClassifier([])
    res = run_calls("stub", calls, "v1", "v1", _label_order(), classifier=stub,
                    ledger=Ledger(tmp_path / "l.jsonl", cap_usd=1.0), cache_root=tmp_path, workers=1)
    assert stub.sent == 0 and res.new_calls == 0
    assert res.records[calls[0].key]["retry_pending"] is False


@needs_baseline
def test_retrieval_version_estimate_includes_the_examples():
    from src.build_segments import load_segments
    from src.llm.run import _messages, estimated_call_cost

    val = load_segments()
    val = val[val["split"] == "val"]
    call = build_calls(val[val["contract_id"] == val["contract_id"].iloc[0]], WINDOW)[0]
    spec, labels, cpt = config.LLM_MODELS["claude"], _label_order(), config.LLM_EST_CHARS_PER_TOKEN
    s2, u2, _, _ = _messages(call, "v2", labels)
    s3, u3, _, _ = _messages(call, "v3", labels)
    assert "<examples>" in u3 and "<examples>" not in u2
    expected = ((len(u3) - len(u2)) * spec["price_in"] + (len(s3) - len(s2)) * spec["price_cache_read"]) / cpt / 1e6
    diff = estimated_call_cost(call, "v3", labels, spec) - estimated_call_cost(call, "v2", labels, spec)
    assert diff == pytest.approx(expected)


# ----------------------------------------------------------------------------- v4 dense output and its gate (Step 3aa)

def test_v4_is_v3_with_exactly_the_four_edits():
    from src.llm.prompt import V3_INSTRUCTIONS, V4_EDITS, V4_INSTRUCTIONS, _edit

    expected = V3_INSTRUCTIONS
    for old, new in V4_EDITS:
        assert V3_INSTRUCTIONS.count(old) == 1
        expected = expected.replace(old, new)
    assert len(V4_EDITS) == 4 and V4_INSTRUCTIONS == expected
    assert "0.1" not in V4_INSTRUCTIONS.split("Rules:")[0]
    with pytest.raises(ValueError):
        _edit("abc", "missing", "x")


@needs_data
def test_v4_schema_is_dense_and_earlier_hashes_are_unchanged():
    from src.llm.prompt import output_schema, prompt_hash, schema_for

    labels = _label_order()
    segs = schema_for("v4", labels, ["S1", "S2"])["properties"]["segments"]
    assert list(segs["properties"]) == ["S1", "S2"] and segs["required"] == ["S1", "S2"]
    per = segs["properties"]["S1"]
    assert per["required"] == sorted(labels) and per["additionalProperties"] is False
    assert all(v == {"type": "number"} for v in per["properties"].values())
    with pytest.raises(ValueError):
        output_schema(labels, dense=True)
    assert prompt_hash("v4", labels) != prompt_hash("v3", labels)
    for model in ("claude", "gemini"):
        for version in ("v1", "v2", "v3"):
            frame = pd.read_parquet(config.LLM_ITERATION_DIR / f"{model}_{version}_n10.parquet")
            assert prompt_hash(version, labels) in frame["model_version"].iloc[0]


def test_dense_parser_keeps_every_score_and_needs_every_label():
    full = {"S1": {"Governing Law": 0.02, "Anti-Assignment": 0.9}}
    p = parse_response(json.dumps({"segments": full}), "ok", ["S1"], LABELS, dense=True)
    assert p.ok and p.scores == {"S1": {"Governing Law": 0.02, "Anti-Assignment": 0.9}}
    missing = parse_response(json.dumps({"segments": {"S1": {"Governing Law": 0.5}}}), "ok", ["S1"], LABELS, dense=True)
    assert not missing.ok and missing.scores == {}
    unknown = {"S1": {"Governing Law": 0.5, "Anti-Assignment": 0.1, "Made Up": 0.2}}
    assert not parse_response(json.dumps({"segments": unknown}), "ok", ["S1"], LABELS, dense=True).ok


@needs_baseline
def test_stub_v4_run_stores_every_label(tmp_path):
    from src.llm.run import run_calls

    labels = _label_order()
    calls = build_calls(_segments({7: 2}), WINDOW)
    answer = json.dumps({"segments": {s: {lab: 0.01 for lab in labels} for s in ("S1", "S2")}})
    res = run_calls("stub", calls, "v4", "v4", labels, classifier=StubClassifier([(answer, "ok")]),
                    ledger=Ledger(tmp_path / "l.jsonl", cap_usd=1.0), cache_root=tmp_path, workers=1)
    rec = res.records[calls[0].key]
    assert rec["parse_failures"] == [] and all(len(rec["scores"][s]) == len(labels) for s in ("7_0", "7_1"))


def _dense_record(targets, per_target):
    rec = _record(targets, json.dumps({"segments": per_target}))
    rec["prompt_version"] = "v4"
    return rec


def test_dense_health_counts():
    from src.llm.run import dense_health, run_health

    zero = _dense_record(["1_0"], {"S1": {"Governing Law": 0.0, "Anti-Assignment": 0.0}})
    mixed = _dense_record(["2_0", "2_1"], {"S1": {"Governing Law": 0.9, "Anti-Assignment": 0.0},
                                           "S2": {"Governing Law": 0.6, "Anti-Assignment": 0.7}})
    h = dense_health([zero, mixed], "v4", LABELS)
    assert h["degenerate_call_share"] == 0.5 and h["zero_confidence_share"] == 0.5
    assert h["mean_labels_at_0.5"] == 1.0 and h["parse_failed_segments"] == 0
    with pytest.raises(ValueError):
        run_health([zero], "v4", LABELS)
    with pytest.raises(ValueError):
        dense_health([zero], "v1", LABELS)


@needs_data
def test_heldout_dense_branch_writes_its_own_notes(tmp_path):
    from src.llm.run import RunResult, build_frame, split_health
    from src.predictions import read_notes, write_predictions

    labels = _label_order()
    seg = _segments({7: 2}).assign(start=0, end=1, labels=[[], []])
    call = build_calls(seg, WINDOW)[0]
    rec = _dense_record(call.targets, {s: {lab: 0.0 for lab in labels} for s in ("S1", "S2")})
    state = {}
    status, _, notes = split_health([rec], "v4", set(labels), state, "test")
    assert status == "not applicable (dense)" and state == {}
    frame = build_frame(seg, [call], RunResult(records={call.key: rec}), labels, {}, "stub", "t")
    path = tmp_path / "p.parquet"
    write_predictions(frame, path, labels, {"scores": "dense, every label scored", **notes})
    written = read_notes(path)
    assert written["run_health_status"] == "not applicable (dense)"
    assert "dense_health_degenerate_call_share" in written and "run_health_below_floor_share" not in written


def test_scores_note_by_version_and_probe_refuses_dense():
    from src.llm.run import SCORES_NOTE, _raw_entries, scores_note

    assert scores_note("v2") == SCORES_NOTE and scores_note("v4") == "dense, every label scored"
    with pytest.raises(ValueError):
        _raw_entries(_dense_record(["1_0"], {}), LABELS)


@pytest.mark.parametrize("error,expected", [("connection: Request timed out.", True), ("connection: ", True),
                                            ("408: ...", True), ("504: ...", True), ("429: ...", False)])
def test_timeout_strings(error, expected):
    from src.llm.run import is_timeout

    assert is_timeout(error) is expected


def _smoke_record(key, output_tokens=100, latency_ms=1000.0, retry_errors=()):
    rec = _dense_record(["1_0"], {"S1": {"Governing Law": 0.1, "Anti-Assignment": 0.0}})
    rec["call_key"] = key
    rec["attempts"][-1].update(usage={"output_tokens": output_tokens}, latency_ms=latency_ms,
                               retry_errors=list(retry_errors))
    return rec


def test_smoke_check_stop_condition():
    from src.llm.run import smoke_check

    clean = [_smoke_record(f"k{i}") for i in range(3)]
    assert smoke_check(clean, 3, LABELS) == []
    assert smoke_check(clean[:2], 3, LABELS)
    assert smoke_check(clean[:2] + [_smoke_record("t", retry_errors=["connection: Request timed out."])], 3, LABELS)
    assert smoke_check(clean[:2] + [_smoke_record("o", output_tokens=6001)], 3, LABELS)
    assert smoke_check(clean[:2] + [_smoke_record("l", latency_ms=90001.0)], 3, LABELS)
    unparsed = _smoke_record("u")
    unparsed["attempts"][-1]["text"] = json.dumps({"segments": {}})
    assert smoke_check(clean[:2] + [unparsed], 3, LABELS)


def test_gate_arithmetic_and_branches():
    from src.llm.run import dense_call_cost, gate_branch, n1_call_cost, project

    v3 = {"calls": 10, "targets": 100, "cost_per_call": 0.01, "out_per_target": 10}
    assert dense_call_cost(v3, 0.002, 210, 10.0) == pytest.approx(0.01 + 0.002 + 200 * 10 * 10.0 / 1e6)
    assert n1_call_cost(v3, 0.002, 210, 10.0) == pytest.approx(0.01 - 100 * 10.0 / 1e6 + 0.002 + 210 * 10.0 / 1e6)
    p = project(0.032, 0.0131, 100, iteration_calls=357, final_calls=2310, repeat_calls=60)
    assert p["total"] == pytest.approx(0.032 * (357 + 2310 + 60) + 0.0131 * 100)
    assert gate_branch(20, 50, 40, True, True) == "both"
    assert gate_branch(20, 100, 60, True, True).endswith("if declined, gemini-only")
    assert "decide on it" in gate_branch(20, 100, 90, True, True)
    assert gate_branch(20, 200, 60, True, True) == "gemini-only"
    assert gate_branch(20, 200, 100, True, True).startswith("gemini-only, above")
    assert gate_branch(20, 50, 40, False, True) == "gemini-only"
    assert gate_branch(20, 50, 40, True, False).startswith("neither")
    assert gate_branch(20, 200, 200, True, True).startswith("neither")


def test_gate_refuses_partial_references_and_skips_paid_smoke_calls():
    from src.llm.run import _complete, iteration_calls_left

    with pytest.raises(SystemExit):
        _complete({"a": 1}, ["a", "b"], "v3 iteration run")
    assert _complete({"a": 1, "b": 2}, ["a", "b"], "v3 iteration run") == [1, 2]
    assert iteration_calls_left([object()] * 3) == 354


def test_score_names_the_ap_by_output_type():
    from src.llm.run import score

    frame = pd.DataFrame({"contract_id": [1, 1], "true_labels": [["Governing Law"], []],
                          "pred_labels": [[{"label": "Governing Law", "confidence": 0.9}], []],
                          "proba": [[0.9, 0.0], [0.1, 0.2]], "parse_failure": [False, False]})
    order = ["Governing Law", "Anti-Assignment"]
    assert "macro_ap_sparse_lower_bound" in score(frame, order)
    dense = score(frame, order, sparse=False)
    assert "macro_ap" in dense and "macro_ap_sparse_lower_bound" not in dense


# ----------------------------------------------------------------------------- N=1 half check (Step 3ad)

@needs_data
def test_n1_half_is_seeded_whole_contracts():
    from src.llm.windows import n1_half_contracts

    sample = pd.read_csv(config.LLM_ITERATION_CONTRACTS)
    half = n1_half_contracts(sample)
    pd.testing.assert_frame_equal(half, n1_half_contracts(sample))
    assert len(sample) == 23 and len(half) == 12
    assert len(half.merge(sample, on=list(sample.columns))) == 12
    assert set(n1_half_contracts(sample, seed=config.SEED + 1)["contract_id"]) != set(half["contract_id"])


@needs_baseline
def test_window_level_examples_leave_n10_unchanged_and_match_at_n1():
    from src.build_segments import load_segments
    from src.llm.prompt import user_message
    from src.llm.retrieval import train_index
    from src.llm.run import _iteration_segments, _messages

    labels = _label_order()
    seg = _iteration_segments(load_segments())
    seg = seg[seg["contract_id"] == seg["contract_id"].iloc[0]]
    n10 = build_calls(seg, WINDOW)[:3]
    for call in n10:
        targets = set(call.targets)
        old = train_index().examples_for([t for sid, t in zip(call.segment_ids, call.texts) if sid in targets])
        assert _messages(call, "v3", labels)[1] == user_message(call, old)[0]
    block = lambda message: message.split("<window>")[0]
    n1 = [c for c in build_calls(seg, 1) if c.segment_ids == n10[0].segment_ids]
    assert n1 and all(block(_messages(c, "v3", labels)[1]) == block(_messages(n10[0], "v3", labels)[1]) for c in n1)


@needs_data
def test_n1_half_calls_match_the_full_sample_calls():
    from src.build_segments import load_segments
    from src.llm.run import _iteration_segments
    from src.llm.windows import n1_half_contracts

    iteration = _iteration_segments(load_segments())
    half = n1_half_contracts(pd.read_csv(config.LLM_ITERATION_CONTRACTS))
    subset = iteration[iteration["contract_id"].isin(half["contract_id"])]
    full_n1 = {c.key: c for c in build_calls(iteration, 1)}
    n10_windows = {c.segment_ids for c in build_calls(iteration, WINDOW)}
    calls = build_calls(subset, 1)
    assert len(calls) == len(subset)
    for c in calls:
        assert len(c.targets) == 1 and full_n1[c.key] == c and c.segment_ids in n10_windows


def test_subset_refuses_other_batch_sizes_rerun_and_limit():
    from types import SimpleNamespace

    from src.llm.run import cmd_iterate

    for kw in ({"batch_size": 10}, {"batch_size": 1, "rerun": "r2"}, {"batch_size": 1, "limit": 3}):
        args = SimpleNamespace(**{"subset": "n1-half", "rerun": None, "limit": None, **kw})
        with pytest.raises(SystemExit):
            cmd_iterate(args)


@needs_data
def test_subset_refuses_a_missing_or_different_saved_draw(tmp_path, monkeypatch):
    from src.llm.run import _n1_half_segments

    monkeypatch.setattr(config, "LLM_N1_CONTRACTS", tmp_path / "missing.csv")
    with pytest.raises(SystemExit):
        _n1_half_segments(None)
    other = tmp_path / "other.csv"
    pd.read_csv(config.LLM_ITERATION_CONTRACTS).head(12).to_csv(other, index=False)
    monkeypatch.setattr(config, "LLM_N1_CONTRACTS", other)
    with pytest.raises(SystemExit):
        _n1_half_segments(None)


def test_restrict_to_pairs_or_refuses():
    from src.llm.run import restrict_to

    b = pd.DataFrame({"segment_id": ["a", "b", "c"], "x": [1, 2, 3]})
    assert list(restrict_to(b, pd.DataFrame({"segment_id": ["c", "a"]}))["segment_id"]) == ["a", "c"]
    with pytest.raises(SystemExit):
        restrict_to(b, pd.DataFrame({"segment_id": ["d"]}))



# ----------------------------------------------------------------------------- validation health rule (Step 3af)

def test_thresholds_requires_a_healthy_or_redone_validation_run(tmp_path, monkeypatch):
    import argparse

    from src.llm.run import cmd_thresholds

    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    args = argparse.Namespace(model="claude")
    marker = tmp_path / "claude" / "val_run.json"
    marker.parent.mkdir()
    for state in ({}, {"invalid": {"val": {}}}):
        marker.write_text(json.dumps(state))
        with pytest.raises(SystemExit, match="no healthy or redone validation run"):
            cmd_thresholds(args)
    for state in ({"health": {"val": {}}}, {"invalid": {"val": {}}, "redone": {"val": {}}}):
        marker.write_text(json.dumps(state))
        with pytest.raises(SystemExit, match="freeze a prompt first"):
            cmd_thresholds(args)


def _val_record(targets, confidence):
    answer = _resp([{"id": f"S{i + 1}", "labels": [{"label": "Governing Law", "confidence": confidence}]}
                    for i in range(len(targets))])
    rec = _record(targets, answer)
    rec["prompt_version"] = "v2"
    rec["attempts"][-1].update(served_model="stub-model", transport_retries=0)
    return rec


@needs_data
def test_val_invalid_run_is_redone_once_in_a_fresh_namespace(tmp_path, monkeypatch):
    import argparse

    from src.llm import run
    from src.predictions import read_notes

    labels = _label_order()
    seg = _segments({7: 2, 8: 2}).assign(start=0, end=1, labels=[[]] * 4)
    iteration_csv = tmp_path / "iteration.csv"
    pd.DataFrame({"contract_id": [7]}).to_csv(iteration_csv, index=False)
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr(config, "PREDICTIONS_DIR", tmp_path / "pred")
    monkeypatch.setattr(config, "LLM_ITERATION_CONTRACTS", iteration_csv)
    (tmp_path / "models" / "claude").mkdir(parents=True)
    frozen = {"version": "v2", "batch_size": WINDOW, "prompt_hash": run.prompt_hash("v2", labels), "run_settings": {}}
    monkeypatch.setattr(run, "load_frozen", lambda _m: frozen)
    monkeypatch.setattr(run, "load_inputs", lambda: (seg, None, labels))
    monkeypatch.setattr(run, "soft_checkpoint", lambda *a, **k: None)
    sent, confidence = [], {"value": 0.0}

    def fake_run_calls(model_key, calls_, version, namespace, label_order, max_cost=None):
        sent.append(namespace)
        return run.RunResult(records={c.key: _val_record(c.targets, confidence["value"]) for c in calls_})

    monkeypatch.setattr(run, "run_calls", fake_run_calls)

    def args(redo=False):
        return argparse.Namespace(model="claude", redo_invalid=redo, past_checkpoint=False, max_cost=None)

    with pytest.raises(SystemExit, match="applies only after validation was declared invalid"):
        run.cmd_val(args(redo=True))
    assert sent == []

    with pytest.raises(SystemExit, match="--redo-invalid"):
        run.cmd_val(args())
    state = json.loads((tmp_path / "models" / "claude" / "val_run.json").read_text())
    assert sent == ["v2"] and "val" in state["invalid"]
    assert (tmp_path / "pred" / "claude_val_invalid.parquet").exists()
    assert not (tmp_path / "pred" / "claude_val.parquet").exists()

    with pytest.raises(SystemExit):
        run.cmd_val(args())
    assert sent == ["v2"]

    confidence["value"] = 0.8
    run.cmd_val(args(redo=True))
    state = json.loads((tmp_path / "models" / "claude" / "val_run.json").read_text())
    assert sent == ["v2", "v2-redo1"] and "val" in state["redone"]
    assert read_notes(tmp_path / "pred" / "claude_val.parquet")["cache_namespace"] == "v2-redo1"


@needs_data
def test_freeze_id_changes_with_prompt_batch_size_or_model_settings():
    from src.llm.run import freeze_id

    base = {"prompt_hash": "p", "batch_size": WINDOW, "run_settings": {"effort": "low"}, "frozen_utc": "t1"}
    assert freeze_id(base) == freeze_id({**base, "frozen_utc": "t2"})
    for change in ({"prompt_hash": "q"}, {"batch_size": 1}, {"run_settings": {"effort": "medium"}}):
        assert freeze_id({**base, **change}) != freeze_id(base)


@needs_data
def test_val_state_is_bound_to_the_freeze_and_thresholds_keep_the_notes(tmp_path, monkeypatch):
    import argparse

    from src.llm import run
    from src.predictions import read_notes

    labels = _label_order()
    seg = _segments({7: 2, 8: 2}).assign(start=0, end=1, labels=[[]] * 4)
    iteration_csv = tmp_path / "iteration.csv"
    pd.DataFrame({"contract_id": [7]}).to_csv(iteration_csv, index=False)
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr(config, "PREDICTIONS_DIR", tmp_path / "pred")
    monkeypatch.setattr(config, "LLM_ITERATION_CONTRACTS", iteration_csv)
    marker = tmp_path / "models" / "claude" / "val_run.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(json.dumps({"freeze_id": "older freeze", "invalid": {"val": {}}}))
    frozen = {"version": "v2", "batch_size": WINDOW, "prompt_hash": run.prompt_hash("v2", labels), "run_settings": {}}
    monkeypatch.setattr(run, "load_frozen", lambda _m: frozen)
    monkeypatch.setattr(run, "load_inputs", lambda: (seg, None, labels))
    monkeypatch.setattr(run, "soft_checkpoint", lambda *a, **k: None)
    sent = []

    def fake_run_calls(m, calls_, v, namespace, lo, max_cost=None):
        sent.append(namespace)
        return run.RunResult(records={c.key: _val_record(c.targets, 0.8) for c in calls_})

    monkeypatch.setattr(run, "run_calls", fake_run_calls)
    run.cmd_val(argparse.Namespace(model="claude", redo_invalid=False, past_checkpoint=False, max_cost=None))
    state = json.loads(marker.read_text())
    assert sent == ["v2"] and state["freeze_id"] == run.freeze_id(frozen) and "invalid" not in state

    run.cmd_thresholds(argparse.Namespace(model="claude"))
    notes = read_notes(tmp_path / "pred" / "claude_val.parquet")
    assert notes["thresholds"] == "Rule B, tuned on validation"
    assert notes["cache_namespace"] == "v2" and notes["run_health_status"] == "ok"

    marker.write_text(json.dumps({**state, "freeze_id": "older freeze"}))
    with pytest.raises(SystemExit, match="not from the current freeze"):
        run.cmd_thresholds(argparse.Namespace(model="claude"))


@needs_data
def test_val_healthy_run_records_health(tmp_path, monkeypatch):
    import argparse

    from src.llm import run

    labels = _label_order()
    seg = _segments({7: 2, 8: 2}).assign(start=0, end=1, labels=[[]] * 4)
    iteration_csv = tmp_path / "iteration.csv"
    pd.DataFrame({"contract_id": [7]}).to_csv(iteration_csv, index=False)
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr(config, "PREDICTIONS_DIR", tmp_path / "pred")
    monkeypatch.setattr(config, "LLM_ITERATION_CONTRACTS", iteration_csv)
    (tmp_path / "models" / "claude").mkdir(parents=True)
    frozen = {"version": "v2", "batch_size": WINDOW, "prompt_hash": run.prompt_hash("v2", labels), "run_settings": {}}
    monkeypatch.setattr(run, "load_frozen", lambda _m: frozen)
    monkeypatch.setattr(run, "load_inputs", lambda: (seg, None, labels))
    monkeypatch.setattr(run, "soft_checkpoint", lambda *a, **k: None)
    monkeypatch.setattr(run, "run_calls", lambda m, calls_, v, ns, lo, max_cost=None: run.RunResult(
        records={c.key: _val_record(c.targets, 0.8) for c in calls_}))
    run.cmd_val(argparse.Namespace(model="claude", redo_invalid=False, past_checkpoint=False, max_cost=None))
    state = json.loads((tmp_path / "models" / "claude" / "val_run.json").read_text())
    assert "val" in state["health"] and "invalid" not in state
    assert (tmp_path / "pred" / "claude_val.parquet").exists()


# ----------------------------------------------------------------------------- Step 6b: Fireworks

FW = "fireworks-deepseek"


def _fw_body(content="{}", finish="stop", usage=None):
    return {"model": config.LLM_MODELS[FW]["model_id"],
            "choices": [{"finish_reason": finish, "message": {"content": content}}],
            "usage": usage if usage is not None else {"prompt_tokens": 1000, "completion_tokens": 50}}


class _NoWait:
    def wait(self):
        pass


def _fw_client(monkeypatch, handler):
    import httpx

    from src.llm import clients

    monkeypatch.setattr(clients.time, "sleep", lambda _s: None)
    clf = clients.FireworksClassifier(config.LLM_MODELS[FW])
    clf.client = httpx.Client(transport=httpx.MockTransport(handler), headers=clf.client.headers)
    clf.limiter = _NoWait()
    return clf


def test_fireworks_payload_has_exactly_the_registered_fields():
    from src.llm.clients import FireworksClassifier

    assert config.LLM_MODELS[FW]["seed"] == config.SEED
    p = FireworksClassifier(config.LLM_MODELS[FW]).payload("sys", "usr", {"type": "object"})
    assert p == {"model": "accounts/fireworks/models/deepseek-v4p1-flash", "max_tokens": 8000, "seed": config.SEED,
                 "reasoning_effort": "none",
                 "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "usr"}],
                 "response_format": {"type": "json_schema",
                                     "json_schema": {"name": "segments", "schema": {"type": "object"}}}}


def test_fireworks_send_maps_usage_cost_and_counts_reasoning_once(monkeypatch):
    import httpx

    from src.llm.clients import fireworks_cost
    from src.llm.run import _output_tokens

    usage = {"prompt_tokens": 1000, "completion_tokens": 50, "prompt_tokens_details": {"cached_tokens": 400},
             "completion_tokens_details": {"reasoning_tokens": 20}}
    a = _fw_client(monkeypatch, lambda r: httpx.Response(200, json=_fw_body('{"segments": {}}', usage=usage))).send(
        {"model": "m"})
    assert a.finish == "ok" and a.text == '{"segments": {}}' and a.transport_retries == 0
    assert a.usage == {"prompt_tokens": 1000, "completion_tokens": 50, "cached_tokens": 400, "reasoning_tokens": 20}
    expected = (600 * 0.22 + 400 * 0.007 + 50 * 0.66) / 1e6
    assert a.cost_usd == pytest.approx(expected) and fireworks_cost(a.usage, config.LLM_MODELS[FW]) == a.cost_usd
    assert _output_tokens(a.usage) == 50


def test_fireworks_429_is_retried_and_400_raises(monkeypatch):
    import httpx

    replies = [httpx.Response(429, text="slow down"), httpx.Response(200, json=_fw_body())]
    a = _fw_client(monkeypatch, lambda r: replies.pop(0)).send({"model": "m"})
    assert a.transport_retries == 1 and a.retry_errors[0].startswith("429")
    with pytest.raises(httpx.HTTPStatusError):
        _fw_client(monkeypatch, lambda r: httpx.Response(400, text="bad schema")).send({"model": "m"})


def test_fireworks_timeout_is_a_connection_error_that_fails_the_smoke_check(monkeypatch):
    import httpx

    from src.llm.run import is_timeout, smoke_check

    replies = [httpx.ReadTimeout("timed out"), httpx.Response(200, json=_fw_body())]

    def handler(request):
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    a = _fw_client(monkeypatch, handler).send({"model": "m"})
    assert a.retry_errors[0].startswith("connection:") and is_timeout(a.retry_errors[0])
    clean = [_smoke_record(f"k{i}") for i in range(2)]
    assert smoke_check(clean + [_smoke_record("t", retry_errors=a.retry_errors)], 3, LABELS)


def test_fireworks_unknown_finish_missing_cache_counts_and_missing_usage(monkeypatch):
    import httpx

    from src.llm.clients import worst_case_cost

    usage = {"prompt_tokens": 10, "completion_tokens": 2, "prompt_tokens_details": {"cached_tokens": None}}
    a = _fw_client(monkeypatch, lambda r: httpx.Response(200, json=_fw_body(finish="tool_calls", usage=usage))).send(
        {"model": "m"})
    assert a.finish == "other:tool_calls" and a.usage["cached_tokens"] == 0 and a.usage["reasoning_tokens"] == 0
    payload = _fw_client(monkeypatch, None).payload("s" * 300, "u" * 300, {})
    b = _fw_client(monkeypatch, lambda r: httpx.Response(200, json=_fw_body(usage={}))).send(payload)
    assert b.usage["usage_missing"] == 1 and b.cost_usd == pytest.approx(
        worst_case_cost("s" * 300, "u" * 300, config.LLM_MODELS[FW])) and b.cost_usd > 0


def test_make_classifier_dispatches_by_provider_and_refuses_unknown():
    from src.llm.clients import CLASSIFIERS, FireworksClassifier, make_classifier

    assert {s["provider"] for s in config.LLM_MODELS.values()} <= set(CLASSIFIERS)
    assert isinstance(make_classifier(FW), FireworksClassifier)
    with pytest.raises(KeyError):
        make_classifier(FW, provider="unknown")


def test_step3_frozen_settings_unchanged_and_step3_commands_skip_the_new_model():
    import inspect

    from src.llm import run

    for model in config.STEP3_MODELS:
        frozen = json.loads((config.MODELS_DIR / model / "prompt.json").read_text())
        assert run.run_settings(model) == frozen["run_settings"]
    assert run.run_settings(FW)["reasoning_effort"] == "none" and run.run_settings(FW)["seed"] == config.SEED
    for fn in (run.cmd_estimate, run.cmd_yardstick, run.cmd_estimate_version, run.cmd_gate_v4):
        src = inspect.getsource(fn)
        assert "STEP3_MODELS" in src and "LLM_MODELS.items()" not in src and "in config.LLM_MODELS:" not in src


@needs_data
def test_fireworks_run_calls_end_to_end_with_the_config_spec(tmp_path, monkeypatch):
    import httpx

    from src.llm.clients import fireworks_cost
    from src.llm.run import run_calls

    monkeypatch.setenv("FIREWORKS_API_KEY", "test-key")
    calls = build_calls(_segments({7: 2}), WINDOW)
    answer = _resp([{"id": "S1", "labels": [{"label": "Governing Law", "confidence": 0.7}]},
                    {"id": "S2", "labels": []}])
    seen = []

    def handler(request):
        seen.append((request.headers["authorization"], json.loads(request.content)))
        return httpx.Response(200, json=_fw_body(answer))

    clf = _fw_client(monkeypatch, handler)
    ledger = Ledger(tmp_path / "ledger.jsonl", cap_usd=1.0)
    res = run_calls(FW, calls, "v1", "v1", _label_order(), classifier=clf, ledger=ledger,
                    cache_root=tmp_path, workers=1)
    rec = res.records[calls[0].key]
    assert rec["parse_failures"] == [] and rec["scores"]["7_0"] == {"Governing Law": 0.7}
    auth, body = seen[0]
    assert auth == "Bearer test-key" and body["response_format"]["type"] == "json_schema" and body["seed"] == config.SEED
    entries = [json.loads(line) for line in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert len(entries) == 1 and entries[0]["cost_usd"] == pytest.approx(
        fireworks_cost({"prompt_tokens": 1000, "completion_tokens": 50}, config.LLM_MODELS[FW]))


@needs_data
def test_iteration_run_matches_iterate_and_a_full_iterate_needs_the_smoke_and_reaches_the_casebook(
        tmp_path, monkeypatch, capsys):
    import argparse

    from src.llm import run

    segments, _, _ = run.load_inputs()
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr(config, "LLM_ITERATION_DIR", tmp_path / "iteration")
    monkeypatch.setattr(run, "soft_checkpoint", lambda *a, **k: None)
    sent = {}

    def records_for(calls):
        return {c.key: {**_val_record(c.targets, 0.8), "call_key": c.key} for c in calls}

    def fake_run_calls(model, calls, *a, **k):
        sent["keys"] = [c.key for c in calls]
        return run.RunResult(records=records_for(calls))

    monkeypatch.setattr(run, "run_calls", fake_run_calls)
    monkeypatch.setattr(run, "_cached_records", lambda model, calls, *a: records_for(calls))
    args = dict(model=FW, prompt="v3", batch_size=WINDOW, subset=None, rerun=None, max_cost=None,
                past_checkpoint=False, after_setup_fix=False)
    calls, to_run = run.iteration_run(segments, WINDOW)
    assert len(to_run) - 3 == 354 and run.iteration_run(segments, WINDOW, 3)[1] == calls[:3]
    with pytest.raises(SystemExit, match="missing"):
        run.cmd_iterate(argparse.Namespace(**args, limit=None))
    for limit, expected in ((3, calls[:3]), (None, to_run)):
        run.cmd_iterate(argparse.Namespace(**args, limit=limit))
        assert sent["keys"] == [c.key for c in expected]
        out = capsys.readouterr().out
        assert "SMOKE TEST" in out if limit else ("Casebook" in out and "Wrote" in out)
    assert json.loads(run.smoke_marker_path(FW, "v3").read_text())["status"] == "finished"


@pytest.mark.parametrize("change,match", [({"prompt": "v2"}, "registered protocol"),
                                          ({"batch_size": 1}, "registered protocol"),
                                          ({"rerun": "r2"}, "registered protocol"),
                                          ({"limit": 2}, "--limit 3")])
def test_protocol_guard_allows_only_the_registered_protocol(change, match):
    import argparse

    from src.llm import run

    args = dict(model=FW, prompt="v3", batch_size=WINDOW, subset=None, rerun=None, limit=3)
    run.protocol_guard(argparse.Namespace(**args))
    run.protocol_guard(argparse.Namespace(**{**args, "model": "claude", **change}))
    with pytest.raises(SystemExit, match=match):
        run.protocol_guard(argparse.Namespace(**{**args, **change}))


@pytest.mark.parametrize("error,setup", [
    ("HTTPStatusError: Client error '401 Unauthorized' for url 'x'", True),
    ("HTTPStatusError: Client error '402 Payment Required' for url 'x'", True),
    ("HTTPStatusError: Client error '404 Not Found' for url 'x'", True),
    ("KeyError: 'choices'", True),
    ("HTTPStatusError: Client error '400 Bad Request' for url 'x'", False),
    ("HTTPStatusError: Client error '422 Unprocessable Entity' for url 'x'", False),
    ("RuntimeError: gave up after 8 attempts: ['429: slow']", False)])
def test_setup_errors_are_only_the_preregistered_ones(error, setup):
    from src.llm.run import is_setup_error

    assert is_setup_error(error) is setup


def test_smoke_marker_keeps_the_first_invocation_and_allows_only_setup_reruns(tmp_path, monkeypatch):
    from src.llm import run

    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    RunResult = run.RunResult
    assert run.smoke_guard(FW, "v3", False) == []
    unauthorized = {"k0": "HTTPStatusError: Client error '401 Unauthorized' for url 'x'"}
    run.write_smoke_marker(FW, "v3", "finished", RunResult(failed=unauthorized), [])
    with pytest.raises(SystemExit, match="--after-setup-fix"):
        run.smoke_guard(FW, "v3", False)
    history = run.smoke_guard(FW, "v3", True)
    assert history[0]["failed"] == unauthorized
    for result in (RunResult(failed={"k0": "HTTPStatusError: Client error '400 Bad Request' for url 'x'"}),
                   RunResult(failed={"k0": "RuntimeError: gave up after 8 attempts: []"}),
                   RunResult(stopped="run cap reached")):
        run.write_smoke_marker(FW, "v3", "finished", result, [])
        with pytest.raises(SystemExit, match="not setup errors"):
            run.smoke_guard(FW, "v3", True)
    run.write_smoke_marker(FW, "v3", "started", RunResult(), history)
    with pytest.raises(SystemExit, match="interrupted"):
        run.smoke_guard(FW, "v3", True)
    run.write_smoke_marker(FW, "v3", "finished", RunResult(records={"k0": {}, "k1": {}}, failed={"k2": "x"}), history)
    marker = json.loads(run.smoke_marker_path(FW, "v3").read_text())
    assert marker["completed"] == ["k0", "k1"] and len(marker["setup_reruns"]) == 1
    for fix in (False, True):
        with pytest.raises(SystemExit, match="was judged"):
            run.smoke_guard(FW, "v3", fix)


def test_smoke_check_judges_only_the_marked_invocation(tmp_path, monkeypatch, capsys):
    import argparse

    from src.llm import run

    to_run = list(range(357))
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(config, "LLM_LEDGER", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(run, "load_inputs", lambda: (None, None, sorted(LABELS)))
    monkeypatch.setattr(run, "iteration_run", lambda seg, n: (to_run[:345], to_run))
    monkeypatch.setattr(run, "make_classifier", lambda m: None)
    monkeypatch.setattr(run, "_cached_records", lambda *a: {f"k{i}": _smoke_record(f"k{i}") for i in range(3)})
    with pytest.raises(SystemExit, match="missing"):
        run.cmd_smoke_check(argparse.Namespace(model=FW, prompt="v3"))
    three = ["k0", "k1", "k2"]
    for status, completed, failed, verdict in (("finished", three, {}, "PASS"),
                                               ("finished", three[:2], {"k2": "gave up"}, "FAIL"),
                                               ("started", three, {}, "FAIL")):
        run.write_smoke_marker(FW, "v3", status, run.RunResult(records=dict.fromkeys(completed), failed=failed), [])
        run.cmd_smoke_check(argparse.Namespace(model=FW, prompt="v3"))
        out = capsys.readouterr().out
        assert f"{FW} smoke {verdict}" in out and "remaining iteration calls 354" in out


def test_smoke_check_is_registered(monkeypatch):
    import sys

    from src.llm import run

    got = []
    monkeypatch.setattr(run, "cmd_smoke_check", got.append)
    monkeypatch.setattr(sys, "argv", ["run", "smoke-check", "--model", FW, "--prompt", "v3"])
    run.main()
    assert got[0].model == FW and got[0].prompt == "v3"

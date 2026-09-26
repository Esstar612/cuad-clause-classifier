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
    return {"targets": list(call.targets), "local_ids": local, "parse_failures": [],
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
    return {"targets": list(targets), "local_ids": local, "parse_failures": [],
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
    from src.llm.run import heldout_namespace, record_health

    state = {}
    assert heldout_namespace(state, "test", "v2", redo=False) == "v2"
    assert record_health(state, "test", {"below_floor_share": 0.04}) == "ok"
    assert record_health(state, "shift", {"below_floor_share": 0.2}) == "invalid"
    with pytest.raises(SystemExit):
        heldout_namespace(state, "shift", "v2", redo=False)
    assert heldout_namespace(state, "shift", "v2", redo=True) == "v2-redo1"
    assert record_health(state, "shift", {"below_floor_share": 0.3}) == "unreliable"
    assert heldout_namespace(state, "shift", "v2", redo=True) == "v2-redo1"
    assert record_health(state, "shift", {"below_floor_share": 0.01}) == "ok"
    assert "shift" in state["redone"] and heldout_namespace(state, "test", "v2", redo=False) == "v2"


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


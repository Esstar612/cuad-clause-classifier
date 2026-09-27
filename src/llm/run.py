"""CLI for the LLM classifiers (Step 3). Validation only, except the guarded `heldout`.

  python -m src.llm.run sample                              iteration sample + label counts (no API)
  python -m src.llm.run estimate                            offline cost estimate (no API)
  python -m src.llm.run yardstick                           baseline on the iteration sample (no API)
  python -m src.llm.run estimate-version --prompt V --base B  retrieval version cost from B's measured run (no API)
  python -m src.llm.run gate-v4                             v4 cost gate from the smoke runs (no API)
  python -m src.llm.run n1-sample                           seeded half of the iteration contracts for N=1 (no API)
  python -m src.llm.run breakdown --model M --prompt V [--batch-size N]   per-label P/R/F1 vs baseline (no API)
  python -m src.llm.run probe [--max-cost X]                Step 3i diagnostic probe (Claude; 4 variants)
  python -m src.llm.run iterate --model M --prompt V --batch-size N [--limit K] [--max-cost X] [--rerun TAG]
  python -m src.llm.run compare --model M --a V:N --b V:N   paired unstratified bootstrap, A minus B
  python -m src.llm.run freeze --model M --prompt V --batch-size N
  python -m src.llm.run val --model M [--max-cost X]        frozen prompt on full validation
  python -m src.llm.run thresholds --model M                Rule B thresholds on validation
  python -m src.llm.run repeat --model M [--max-cost X]    nondeterminism check (2 extra runs)
  python -m src.llm.run heldout --model M [--max-cost X]    one-time test + shift run

Paid commands (iterate, val, repeat, heldout) stop before any call if spend so far plus their
projected cost would pass the $100 soft checkpoint; rerun with --past-checkpoint to approve.

Models: claude (claude-sonnet-5), gemini (gemini-3.8-flash); see src/config.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import threading
import zlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from src import config
from src.bootstrap import f1_metrics, per_contract_counts
from src.build_segments import load_segments
from src.evaluate import indicator
from src.labels import label_set
from src.llm.cache import BudgetExceeded, Ledger, cache_path, load_record, request_hash, save_record
from src.llm.clients import make_classifier, worst_case_cost
from src.llm.parse import parse_response
from src.llm.prompt import (PROBE_VARIANTS, PROMPT_VERSIONS, prompt_hash, schema_for, system_prompt,
                            user_message, version_spec)
from src.llm.retrieval import train_index
from src.llm.selection import llm_thresholds, paired_micro_f1
from src.llm.windows import WINDOW, build_calls, casebook, iteration_contracts, n1_half_contracts, windows
from src.metrics import per_label
from src.predictions import read_label_order, to_prediction_frame, write_predictions

SCORES_NOTE = f"sparse, floor {config.LLM_CONFIDENCE_FLOOR} (unlisted labels score 0)"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_inputs():
    segments = load_segments()
    spans = pd.read_parquet(config.PROCESSED_DIR / "spans.parquet")
    contracts = pd.read_parquet(config.PROCESSED_DIR / "contracts.parquet")
    return segments, contracts, label_set(spans["category"].unique())


# ----------------------------------------------------------------------------- running calls

@dataclass
class RunResult:
    records: dict = field(default_factory=dict)      # call key -> cache record
    failed: dict = field(default_factory=dict)       # call key -> transport error
    new_calls: int = 0
    stopped: str | None = None


def _messages(call, version, label_order):
    examples = None
    if version_spec(version).get("retrieval"):
        examples = train_index().examples_for(list(call.texts))  # the whole window, so N=1 sees N=10's block
    user, local = user_message(call, examples)
    target_ids = [lid for lid, sid in local.items() if sid in set(call.targets)]
    system, schema = system_prompt(version, label_order), schema_for(version, label_order, target_ids)
    return system, user, local, schema


def _request(call, version, label_order, classifier):
    system, user, local, schema = _messages(call, version, label_order)
    return system, user, local, classifier.payload(system, user, schema)


def _merged_scores(attempts, local, targets, labels, dense) -> dict[str, dict[str, float]]:
    target_local = [lid for lid, sid in local.items() if sid in targets]
    scores = {}
    for a in attempts:  # a later attempt overrides an earlier one only for segments it parsed
        parsed = parse_response(a["text"], a["finish"], target_local, labels, dense=dense)
        scores.update({local[lid]: conf for lid, conf in parsed.scores.items()})
    return scores


def _record(call, model_key, namespace, version, local, attempts, labels, retry_pending=False) -> dict:
    scores = _merged_scores(attempts, local, set(call.targets), labels, not is_sparse(version))
    return {"call_key": call.key, "model_key": model_key, "namespace": namespace,
            "prompt_version": version, "segment_ids": list(call.segment_ids),
            "targets": list(call.targets), "local_ids": local, "attempts": attempts,
            "scores": scores, "parse_failures": [s for s in call.targets if s not in scores],
            "created_utc": _now(), "worker": threading.current_thread().name,
            "retry_pending": retry_pending}


def _run_one(call, model_key, namespace, version, label_order, classifier, ledger, cache_root):
    system, user, local, payload = _request(call, version, label_order, classifier)
    path = cache_path(model_key, namespace, call.key, request_hash(payload), cache_root)
    record = load_record(path)
    if record is not None and not record.get("retry_pending"):
        return record, False
    labels, dense = set(label_order), not is_sparse(version)
    target_local = [lid for lid, sid in local.items() if sid in set(call.targets)]
    attempts = list(record["attempts"]) if record else []
    sent_before = len(attempts)
    ok = bool(attempts) and parse_response(attempts[-1]["text"], attempts[-1]["finish"], target_local, labels,
                                           dense=dense).ok
    while len(attempts) < 2 and not ok:  # one retry for an invalid response
        worst = worst_case_cost(system, user, classifier.spec)
        try:
            ledger.reserve(worst)
        except BudgetExceeded:
            if attempts:
                save_record(path, _record(call, model_key, namespace, version, local, attempts, labels, True))
            raise
        try:
            att = classifier.send(payload)
        except Exception:
            ledger.release(worst)
            if attempts:  # keep the paid attempt so a resume sends only the retry
                save_record(path, _record(call, model_key, namespace, version, local, attempts, labels, True))
            raise
        ledger.settle(worst, {"ts": _now(), "model_key": model_key, "namespace": namespace,
                              "call_key": call.key, "attempt": len(attempts) + 1,
                              "served_model": att.served_model, "usage": att.usage,
                              "cost_usd": att.cost_usd})
        parsed = parse_response(att.text, att.finish, target_local, labels, dense=dense)
        attempts.append({**att.to_dict(), "parse_errors": parsed.errors})
        ok = parsed.ok
    record = _record(call, model_key, namespace, version, local, attempts, labels)
    save_record(path, record)
    return record, len(attempts) > sent_before


def run_calls(model_key, calls, version, namespace, label_order, max_cost=None,
              classifier=None, ledger=None, cache_root=config.LLM_CACHE_DIR,
              workers=config.LLM_WORKERS) -> RunResult:
    classifier = classifier or make_classifier(model_key)
    ledger = ledger or Ledger(run_cap_usd=max_cost)
    result, stop = RunResult(), threading.Event()

    def task(call):
        if stop.is_set():
            return call, None, "skipped"
        try:
            rec, new = _run_one(call, model_key, namespace, version, label_order, classifier,
                                ledger, cache_root)
            return call, (rec, new), None
        except BudgetExceeded as e:
            stop.set()
            result.stopped = str(e)
            return call, None, "budget"
        except Exception as e:  # transport failure after retries, or a non-retryable error
            return call, None, f"{type(e).__name__}: {e}"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for fut in as_completed([pool.submit(task, c) for c in calls]):
            call, out, err = fut.result()
            if out is not None:
                result.records[call.key] = out[0]
                result.new_calls += out[1]
            elif err not in ("skipped", "budget"):
                result.failed[call.key] = err
    return result


def _batch_size(call) -> int:
    return int(re.search(r"_n(\d+)_", call.key).group(1))


def measured_call_cost(model_key, namespace, batch_size, ledger_path=config.LLM_LEDGER) -> float | None:
    """Errs high for Claude: early calls include cache writes."""
    per_call = {}
    if ledger_path.exists():
        with open(ledger_path, encoding="utf-8") as f:
            for line in f:
                e = json.loads(line) if line.strip() else {}
                if (e.get("model_key") == model_key and e.get("namespace") == namespace
                        and f"_n{batch_size}_" in e.get("call_key", "")):
                    key = (e["namespace"], e["call_key"])
                    per_call[key] = per_call.get(key, 0.0) + e["cost_usd"]
    return sum(per_call.values()) / len(per_call) if per_call else None


def estimated_call_cost(call, version, label_order, spec) -> float:
    system, user_text, _, _ = _messages(call, version, label_order)
    prefix = len(system) / config.LLM_EST_CHARS_PER_TOKEN
    user = len(user_text) / config.LLM_EST_CHARS_PER_TOKEN
    out = (len(call.targets) * config.LLM_EST_OUTPUT_TOKENS_PER_TARGET
           + config.LLM_EST_THINKING_TOKENS_PER_CALL)
    prefix_price = spec["price_cache_read"] if spec.get("provider") == "anthropic" else spec["price_in"]
    return (prefix * prefix_price + user * spec["price_in"] + out * spec["price_out"]) / 1e6


def soft_checkpoint(model_key, jobs, label_order, approved, classifier=None,
                    ledger_path=config.LLM_LEDGER, cache_root=config.LLM_CACHE_DIR,
                    soft_usd=config.LLM_SOFT_CHECKPOINT_USD) -> float:
    """Rule E: stop before any call if spend plus projection would pass the soft checkpoint."""
    classifier = classifier or make_classifier(model_key)
    spent = Ledger(ledger_path).prior_total
    projected, bases = 0.0, set()
    for calls, version, namespace in jobs:
        for call in calls:
            payload = _request(call, version, label_order, classifier)[3]
            cached = load_record(cache_path(model_key, namespace, call.key, request_hash(payload), cache_root))
            if cached is not None and not cached.get("retry_pending"):
                continue
            rate = measured_call_cost(model_key, namespace, _batch_size(call), ledger_path)
            if rate is None:
                rate = estimated_call_cost(call, version, label_order, classifier.spec)
                bases.add(f"offline estimate (no {namespace} N={_batch_size(call)} history)")
            else:
                bases.add(f"{namespace} ledger mean ${rate:.4f}/call at N={_batch_size(call)}")
            projected += rate
    total = spent + projected
    print(f"Checkpoint: spent ${spent:.2f} so far; this command projects ${projected:.2f} "
          f"({'; '.join(sorted(bases)) or 'all calls cached'}); total ${total:.2f}; "
          f"soft checkpoint ${soft_usd:.2f}, hard cap ${config.LLM_BUDGET_USD:.2f}")
    if projected > 0 and total > soft_usd and not approved:
        raise SystemExit("STOPPED at the soft checkpoint before any call. To continue, rerun with "
                         "--past-checkpoint. If declined, the Rule E fallback order applies.")
    return projected


def complete_or_exit(result: RunResult, calls) -> None:
    missing = [c.key for c in calls if c.key not in result.records]
    if result.stopped:
        print(f"STOPPED: {result.stopped}")
    for key, err in list(result.failed.items())[:5]:
        print(f"FAILED call {key}: {err}")
    if missing:
        raise SystemExit(f"{len(missing)} of {len(calls)} calls incomplete; completed calls are "
                         "cached, so rerunning the same command resumes without paying again.")


# ----------------------------------------------------------------------------- predictions

def record_scores(rec, labels) -> tuple[dict[str, dict[str, float]], list[str]]:
    """Re-parse the raw answers with the current parser; stored scores may predate parser rules."""
    scores = _merged_scores(rec["attempts"], rec["local_ids"], set(rec["targets"]), labels,
                            not is_sparse(rec["prompt_version"]))
    return scores, [sid for sid in rec["targets"] if sid not in scores]


def build_frame(segments, calls, result, label_order, thresholds, model_key, model_version):
    """Shared-format frame for the target segments of `calls`. Cost and latency are
    call-amortized: the call's cost (all attempts) and its final attempt's latency, divided by
    the number of targets in the call."""
    col = {lab: j for j, lab in enumerate(label_order)}
    labels = set(label_order)
    by_segment = {}
    for call in calls:
        rec = result.records[call.key]
        scores, failures = record_scores(rec, labels)
        n = len(rec["targets"])
        last = rec["attempts"][-1]
        cost = sum(a["cost_usd"] for a in rec["attempts"]) / n
        for sid in rec["targets"]:
            by_segment[sid] = (scores.get(sid, {}), sid in failures, last["latency_ms"], cost, n)
    part = segments[segments["segment_id"].isin(by_segment)].reset_index(drop=True)
    proba = np.zeros((len(part), len(label_order)))
    for i, sid in enumerate(part["segment_id"]):
        for lab, conf in by_segment[sid][0].items():
            proba[i, col[lab]] = conf
    thr = np.array([thresholds.get(lab, 0.5) for lab in label_order])
    pred = proba >= thr
    meta = [by_segment[sid] for sid in part["segment_id"]]
    frame = to_prediction_frame(part, proba, pred, label_order, model_key, model_version,
                                latency_ms=[m[2] / m[4] for m in meta], cost_usd=[m[3] for m in meta])
    frame["parse_failure"] = [m[1] for m in meta]
    frame["call_latency_ms"] = [m[2] for m in meta]
    return frame


def served_models(result) -> list[str]:
    return sorted({a["served_model"] for r in result.records.values() for a in r["attempts"]})


def _label_items(data) -> list[dict]:
    segs = data.get("segments") if isinstance(data, dict) else None
    if isinstance(segs, dict):
        groups = list(segs.values())
    elif isinstance(segs, list):
        groups = [s.get("labels") for s in segs if isinstance(s, dict)]
    else:
        return []
    return [i for g in groups if isinstance(g, list) for i in g if isinstance(i, dict)]


def is_sparse(version: str) -> bool:
    return version_spec(version).get("output", "sparse") == "sparse"


def scores_note(version: str) -> str:
    return SCORES_NOTE if is_sparse(version) else "dense, every label scored"


def dense_health(records, version: str, labels: set[str]) -> dict:
    """Descriptive only (Rule E, 3aa): no label-free signal flags an obvious clause scored 0 in dense output."""
    if is_sparse(version):
        raise ValueError(f"dense health is for dense output only; {version} is sparse")
    degenerate = zeros = scored = failed = 0
    at_half = []
    for rec in records:
        scores, failures = record_scores(rec, labels)
        failed += len(failures)
        values = [v for per in scores.values() for v in per.values()]
        degenerate += bool(values) and len(set(values)) == 1
        zeros += sum(v == 0 for v in values)
        scored += len(values)
        at_half += [sum(v >= 0.5 for v in scores[sid].values()) for sid in rec["targets"] if sid not in failures]
    n = len(records)
    return {"calls": n, "degenerate_call_share": degenerate / max(n, 1),
            "zero_confidence_share": zeros / max(scored, 1),
            "mean_labels_at_0.5": sum(at_half) / max(len(at_half), 1), "parse_failed_segments": failed}


def run_health(records, version: str, labels: set[str], floor: float = config.LLM_CONFIDENCE_FLOOR) -> dict:
    """Pre-registered in BUILD_LOG 3n; raw text only, no gold labels."""
    if not is_sparse(version):
        raise ValueError(f"run health is defined for sparse output only; {version} is dense")
    flagged = unreadable = 0
    for rec in records:
        hit = False
        for a in rec["attempts"]:
            try:
                data = json.loads(a["text"] or "")
            except json.JSONDecodeError:
                unreadable += 1
                continue
            hit |= any(isinstance(c := i.get("confidence"), (int, float)) and not isinstance(c, bool)
                       and c < floor for i in _label_items(data))
        flagged += hit
    listed, failed = [], 0
    for rec in records:
        scores, failures = record_scores(rec, labels)
        failed += len(failures)
        listed += [len(scores[sid]) for sid in rec["targets"] if sid not in failures]
    n = len(records)
    return {"calls": n, "below_floor_calls": flagged, "below_floor_share": flagged / max(n, 1),
            "unreadable_attempts": unreadable,
            "empty_set_share": sum(k == 0 for k in listed) / max(len(listed), 1),
            "mean_labels_listed": sum(listed) / max(len(listed), 1),
            "parse_failed_segments": failed}


def _health_or_note(records, version, labels):
    return run_health(records, version, labels) if is_sparse(version) else dense_health(records, version, labels)


def usage_report(result, calls, batch_size, version, labels) -> dict:
    recs = [result.records[c.key] for c in calls]
    attempts = [a for r in recs for a in r["attempts"]]
    lat = np.array([r["attempts"][-1]["latency_ms"] for r in recs])
    targets = sum(len(r["targets"]) for r in recs)
    usage_keys = sorted({k for a in attempts for k in a["usage"]})
    total_cost = sum(a["cost_usd"] for a in attempts)
    label = ("one target per call, full window context" if batch_size == 1
             else f"{WINDOW} targets per call, call-amortized per segment")
    return {"calls": len(recs), "new_calls_this_run": result.new_calls, "attempts": len(attempts),
            "parse_retries": sum(len(r["attempts"]) - 1 for r in recs),
            "transport_retries": sum(a["transport_retries"] for a in attempts),
            "tokens": {k: int(sum(a["usage"].get(k, 0) for a in attempts)) for k in usage_keys},
            "cost_usd_all_calls": total_cost,
            "cost_per_1000_segments": 1000 * total_cost / max(targets, 1),
            "latency_per_call_ms": {"median": float(np.median(lat)), "p95": float(np.percentile(lat, 95))},
            "latency_per_segment_ms_median": float(np.median(lat) / (targets / len(recs))),
            "latency_label": label, "served_models": served_models(result),
            "record_window_utc": [min(r["created_utc"] for r in recs), max(r["created_utc"] for r in recs)],
            "run_health": _health_or_note(recs, version, labels)}


def score(frame, label_order, sparse=True) -> dict:
    """Point metrics with the evaluator's conventions (none FP on parsed segments only)."""
    y = indicator(frame["true_labels"], label_order)
    pred = indicator([[d["label"] for d in ps] for ps in frame["pred_labels"]], label_order)
    proba = np.vstack(frame["proba"].to_numpy())
    ids = np.sort(frame["contract_id"].unique())
    counts = per_contract_counts(y, pred, np.searchsorted(ids, frame["contract_id"].to_numpy()),
                                 len(ids), parse_failure=frame["parse_failure"].to_numpy())
    m = f1_metrics(counts, np.ones((1, len(ids))), list(range(len(label_order))))
    ap = per_label(y, pred, proba, label_order)["ap"]
    return {"segments": len(frame), "contracts": len(ids),
            "micro_f1": float(m["micro_f1"][0]), "macro_f1": float(m["macro_f1"][0]),
            "macro_ap_sparse_lower_bound" if sparse else "macro_ap": float(np.nanmean(ap)),
            "none_fp_rate_parsed": float(m["none_fp_rate"][0]),
            "parse_failure_rate": float(m["parse_failure_rate"][0])}


def _print(d, indent=""):
    for k, v in d.items():
        print(f"{indent}{k}: {round(v, 4) if isinstance(v, float) else v}")


# ----------------------------------------------------------------------------- commands

def cmd_sample(_args) -> None:
    segments, contracts, label_order = load_inputs()
    sample = iteration_contracts(segments, contracts)
    path = config.LLM_ITERATION_CONTRACTS
    if path.exists():
        saved = pd.read_csv(path)
        if not saved.equals(sample):
            raise SystemExit(f"{path} differs from the seeded sample; not overwriting")
    else:
        sample.to_csv(path, index=False)
    seg = segments[segments["contract_id"].isin(sample["contract_id"])]
    print(f"Iteration sample: {len(sample)} validation contracts, {len(seg)} segments "
          f"(saved to {path})")
    print("\nContracts per type:")
    print(sample.groupby("contract_type")["contract_id"].count().to_string())
    exploded = seg[["contract_id", "labels"]].explode("labels").dropna()
    counts = pd.DataFrame({
        "segments": exploded.groupby("labels").size(),
        "contracts": exploded.groupby("labels")["contract_id"].nunique(),
    }).reindex(label_order).fillna(0).astype(int)
    counts["too_thin_to_judge"] = counts["segments"] < config.LLM_THIN_LABEL_SEGMENTS
    print(f"\nPositive segments per label in the iteration sample "
          f"(total positive label instances {int(counts['segments'].sum())}; "
          f"segments with any label {int((seg['labels'].map(len) > 0).sum())}):")
    print(counts.sort_values("segments").to_string())
    print(f"\nLabels too thin to judge (< {config.LLM_THIN_LABEL_SEGMENTS} segments): "
          f"{int(counts['too_thin_to_judge'].sum())} of {len(label_order)}")
    cases = casebook(pd.read_parquet(config.PREDICTIONS_DIR / "baseline_val.parquet"))
    cases["in_iteration_sample"] = cases["segment_id"].isin(seg["segment_id"])
    print("\nCasebook (reported separately, never used for selection):")
    print(cases.to_string(index=False))


def cmd_estimate(_args) -> None:
    segments, contracts, label_order = load_inputs()
    sample = pd.read_csv(config.LLM_ITERATION_CONTRACTS)
    val = segments[segments["split"] == "val"]
    it_seg = val[val["contract_id"].isin(sample["contract_id"])]
    cases = set(casebook(pd.read_parquet(config.PREDICTIONS_DIR / "baseline_val.parquet"))["segment_id"])

    def case_calls(n):  # casebook calls not already in the iteration sample, as `iterate` sends them
        inside = {c.key for c in build_calls(it_seg, n)}
        return [c for c in build_calls(val, n) if set(c.targets) & cases and c.key not in inside]

    phases = {  # name: (calls, runs)
        f"iteration, {config.LLM_MAX_PROMPT_VERSIONS} versions, N={WINDOW}":
            (build_calls(it_seg, WINDOW), config.LLM_MAX_PROMPT_VERSIONS),
        f"casebook, {config.LLM_MAX_PROMPT_VERSIONS} versions, N={WINDOW}":
            (case_calls(WINDOW), config.LLM_MAX_PROMPT_VERSIONS),
        "batch-size check, v1, N=1": (build_calls(it_seg, 1), 1),
        "casebook, v1, N=1": (case_calls(1), 1),
        "full validation": (build_calls(val, WINDOW), 1),
        "test": (build_calls(segments[segments["split"] == "test"], WINDOW), 1),
        "shift": (build_calls(segments[segments["split"] == "shift"], WINDOW), 1),
    }
    repeat_windows = windows(it_seg)[:config.LLM_REPEAT_WINDOWS]
    repeat_seg = pd.concat([w for _, _, w in repeat_windows])
    phases[f"repeat check, {config.LLM_REPEAT_RUNS} extra runs"] = (build_calls(repeat_seg, WINDOW),
                                                                     config.LLM_REPEAT_RUNS)

    prefix_tokens = len(system_prompt("v1", label_order)) / config.LLM_EST_CHARS_PER_TOKEN
    print(f"Assumptions: {config.LLM_EST_CHARS_PER_TOKEN} characters/token; prefix ~{prefix_tokens:,.0f} "
          f"tokens (v1 system prompt); {config.LLM_EST_OUTPUT_TOKENS_PER_TARGET} output tokens per "
          f"target; {config.LLM_EST_THINKING_TOKENS_PER_CALL} thinking tokens per call. "
          "Offline: no API calls.")
    rows = []
    for name, (calls, reps) in phases.items():
        targets = sum(len(c.targets) for c in calls)
        user_tokens = sum(len(user_message(c)[0]) for c in calls) / config.LLM_EST_CHARS_PER_TOKEN
        out_tokens = (targets * config.LLM_EST_OUTPUT_TOKENS_PER_TARGET
                      + len(calls) * config.LLM_EST_THINKING_TOKENS_PER_CALL)
        row = {"phase": name, "segments": targets, "calls": len(calls), "runs": reps}
        for key, spec in config.LLM_MODELS.items():
            if spec["provider"] == "anthropic":
                prefix_cost = (prefix_tokens * spec["price_cache_write"]
                               + (len(calls) - 1) * prefix_tokens * spec["price_cache_read"])
            else:  # below Gemini's 4,096-token caching minimum: assume no caching
                prefix_cost = len(calls) * prefix_tokens * spec["price_in"]
            cost = (prefix_cost + user_tokens * spec["price_in"] + out_tokens * spec["price_out"]) / 1e6
            row[f"{key}_usd"] = round(cost * reps, 2)
        rows.append(row)
    table = pd.DataFrame(rows)
    print(table.to_string(index=False))
    totals = {k: round(float(table[f"{k}_usd"].sum()), 2) for k in config.LLM_MODELS}
    print(f"\nTotals: " + ", ".join(f"{k} ${v:.2f}" for k, v in totals.items())
          + f"; combined ${sum(totals.values()):.2f}; cap ${config.LLM_BUDGET_USD:.2f}")
    print("Validation reuses cached iteration calls for the frozen version at the same batch size, "
          "so the full-validation figure is an overestimate.")


def _iteration_segments(segments):
    sample = pd.read_csv(config.LLM_ITERATION_CONTRACTS)
    return segments[(segments["split"] == "val") & segments["contract_id"].isin(sample["contract_id"])]


def _version_tag(model_key, version, served, thresholds=None) -> str:
    tag = f"{'/'.join(served)}|prompt {version} {prompt_hash(version, _label_order_cached())}"
    if thresholds is not None:
        blob = json.dumps(thresholds, sort_keys=True).encode()
        tag += f"|thresholds {hashlib.sha256(blob).hexdigest()[:12]}"
    return tag


_LABEL_ORDER: list[str] | None = None


def _label_order_cached() -> list[str]:
    global _LABEL_ORDER
    if _LABEL_ORDER is None:
        _LABEL_ORDER = load_inputs()[2]
    return _LABEL_ORDER


def iteration_path(model_key, version, batch_size) -> Path:
    return config.LLM_ITERATION_DIR / f"{model_key}_{version}_n{batch_size}.parquet"


def _n1_draw() -> pd.DataFrame:
    return n1_half_contracts(pd.read_csv(config.LLM_ITERATION_CONTRACTS))


def cmd_n1_sample(_args) -> None:
    draw, path = _n1_draw(), config.LLM_N1_CONTRACTS
    if path.exists():
        if not pd.read_csv(path).equals(draw):
            raise SystemExit(f"{path} differs from the seeded draw; not overwriting")
    else:
        draw.to_csv(path, index=False)
    print(f"N=1 half: {len(draw)} of {len(pd.read_csv(config.LLM_ITERATION_CONTRACTS))} iteration contracts, "
          f"{int(draw['segments'].sum())} segments = N=1 calls per model (saved to {path})")
    print(draw.to_string(index=False))


def _n1_half_segments(segments):
    draw = _n1_draw()
    if not config.LLM_N1_CONTRACTS.exists() or not pd.read_csv(config.LLM_N1_CONTRACTS).equals(draw):
        raise SystemExit("run `n1-sample` first; the saved N=1 half must equal the seeded draw")
    seg = _iteration_segments(segments)
    return seg[seg["contract_id"].isin(draw["contract_id"])]


def cmd_iterate(args) -> None:
    if args.subset and (args.batch_size != 1 or args.rerun or args.limit):
        raise SystemExit("--subset n1-half runs at batch size 1 only, without --rerun or --limit")
    load_dotenv()
    segments, _, label_order = load_inputs()
    if args.prompt not in PROMPT_VERSIONS:
        raise SystemExit(f"unknown prompt version {args.prompt}")
    seg = _n1_half_segments(segments) if args.subset else _iteration_segments(segments)
    calls = build_calls(seg, args.batch_size)
    case_calls = []
    if not args.subset:
        cases = casebook(pd.read_parquet(config.PREDICTIONS_DIR / "baseline_val.parquet"))
        case_calls = [c for c in build_calls(segments[segments["split"] == "val"], args.batch_size)
                      if set(c.targets) & set(cases["segment_id"])]
    if args.limit:
        calls, case_calls = calls[:args.limit], []
    to_run = calls + [c for c in case_calls if c.key not in {k.key for k in calls}]
    run_label = f"{args.prompt}-{args.rerun}" if args.rerun else args.prompt
    soft_checkpoint(args.model, [(to_run, args.prompt, run_label)], label_order, args.past_checkpoint)
    result = run_calls(args.model, to_run, args.prompt, run_label, label_order, max_cost=args.max_cost)
    complete_or_exit(result, calls)
    served = served_models(result)
    frame = build_frame(segments, calls, result, label_order, {}, args.model,
                        _version_tag(args.model, args.prompt, served))
    print(f"Model {args.model} ({', '.join(served)}), prompt {run_label}, batch size "
          f"{args.batch_size}{' (SMOKE TEST: partial sample, not saved)' if args.limit else ''}")
    print("\nValidation iteration metrics at threshold 0.5:")
    _print(score(frame, label_order, is_sparse(args.prompt)), "  ")
    print("\nUsage:")
    _print(usage_report(result, calls, args.batch_size, args.prompt, set(label_order)), "  ")
    if args.limit:
        return
    path = iteration_path(args.model, f"{args.prompt}-n1half" if args.subset else run_label, args.batch_size)
    write_predictions(frame, path, label_order, {"scores": scores_note(args.prompt), "threshold": "0.5 (iteration)",
                                                 "latency_ms": "call-amortized"})
    if case_calls and all(c.key in result.records for c in case_calls):
        cf = build_frame(segments, case_calls, result, label_order, {}, args.model, "casebook")
        cf = cf[cf["segment_id"].isin(cases["segment_id"])].merge(cases, on="segment_id")
        print("\nCasebook (threshold 0.5; not a selection criterion):")
        for r in cf.itertuples():
            pred = {d["label"]: round(d["confidence"], 2) for d in r.pred_labels}
            if r.case.startswith("Most Favored"):
                ok = "Most Favored Nation" in pred
            else:
                a, b = r.case.split(" misread as ")[0], r.case.split(" misread as ")[1].split(" (")[0]
                ok = a in pred and b not in pred
            print(f"  [{'PASS' if ok else 'fail'}] {r.segment_id} | {r.case} | true={list(r.true_labels)} | pred={pred}")
    print(f"\nWrote {path}")


def cmd_yardstick(_args) -> None:
    """Baseline thresholds were tuned on full validation, so its tuned figure is optimistic."""
    path = config.PREDICTIONS_DIR / "baseline_val.parquet"
    label_order = read_label_order(path)
    base = pd.read_parquet(path)
    base = base[base["contract_id"].isin(pd.read_csv(config.LLM_ITERATION_CONTRACTS)["contract_id"])]
    base = base.reset_index(drop=True).assign(parse_failure=False)
    proba = np.vstack(base["proba"].to_numpy())
    at_half = base.assign(pred_labels=[[{"label": lab, "confidence": float(p)}
                                        for lab, p in zip(label_order, row) if p >= 0.5] for row in proba])
    for name, frame in (("tuned Rule B thresholds (optimistic)", base), ("threshold 0.5", at_half)):
        print(f"\nBaseline {name}:")
        _print(score(frame, label_order, sparse=False), "  ")
    for m in config.LLM_MODELS:
        for f in sorted(config.LLM_ITERATION_DIR.glob(f"{m}_v*_n{WINDOW}.parquet")):
            run_label = f.stem.removeprefix(f"{m}_").removesuffix(f"_n{WINDOW}")
            print(f"\n{m} {run_label} N={WINDOW} minus baseline (tuned), paired unstratified bootstrap:")
            _print(paired_micro_f1(pd.read_parquet(f), base, label_order)["micro_f1"], "  ")


def cmd_breakdown(args) -> None:
    run = pd.read_parquet(iteration_path(args.model, args.prompt, args.batch_size))
    path = config.PREDICTIONS_DIR / "baseline_val.parquet"
    label_order = read_label_order(path)
    base = pd.read_parquet(path).set_index("segment_id").loc[run["segment_id"]].reset_index()
    rows, support = {}, None
    for name, frame in ((args.model, run), ("baseline", base)):
        y = indicator(frame["true_labels"], label_order)
        pred = indicator([[d["label"] for d in ps] for ps in frame["pred_labels"]], label_order)
        t = per_label(y, pred, np.vstack(frame["proba"].to_numpy()), label_order).set_index("label")
        tp, fp, fn = t["tp"].sum(), (t["predicted"] - t["tp"]).sum(), (t["support"] - t["tp"]).sum()
        print(f"{name}: micro precision {tp / max(tp + fp, 1):.4f}, micro recall {tp / max(tp + fn, 1):.4f}")
        rows[name] = t[["predicted", "precision", "recall", "f1"]]
        support = t["support"]
    table = pd.concat(rows, axis=1)
    table.insert(0, "support", support)
    print(table.sort_values("support", ascending=False).round(3).to_string())


def _cached_records(model_key, calls, version, namespace, label_order, classifier) -> dict:
    out = {}
    for c in calls:
        payload = _request(c, version, label_order, classifier)[3]
        rec = load_record(cache_path(model_key, namespace, c.key, request_hash(payload),
                                     config.LLM_CACHE_DIR))
        if rec is not None and not rec.get("retry_pending"):
            out[c.key] = rec
    return out


def _raw_entries(rec, labels) -> dict[str, dict[str, float]]:
    if not is_sparse(rec["prompt_version"]):
        raise ValueError("the probe only reads sparse answers")
    a = rec["attempts"][-1]
    local_targets = [lid for lid, sid in rec["local_ids"].items() if sid in set(rec["targets"])]
    parsed = parse_response(a["text"], a["finish"], local_targets, labels, floor=0.0)
    return {rec["local_ids"][lid]: d for lid, d in parsed.scores.items()}


def probe_windows(records, calls, gold, labels, n=config.LLM_PROBE_WINDOWS, seed=config.SEED):
    failing = sorted((c for c in calls
                      if any(v < config.LLM_CONFIDENCE_FLOOR and lab in gold[sid]
                             for sid, d in _raw_entries(records[c.key], labels).items()
                             for lab, v in d.items())), key=lambda c: c.key)
    rng = np.random.default_rng([seed, zlib.crc32(b"probe")])
    pick = sorted(rng.choice(len(failing), size=min(n, len(failing)), replace=False))
    return [failing[i] for i in pick], len(failing)


def probe_stats(records, calls, gold, labels, version) -> dict:
    tp = fp = fn = gold_low = all_low = failed = 0
    usage, cost = Counter(), 0.0
    for c in calls:
        rec = records[c.key]
        raw = _raw_entries(rec, labels)
        scores, failures = record_scores(rec, labels)
        for sid in rec["targets"]:
            pred = {lab for lab, v in scores.get(sid, {}).items() if v >= 0.5}
            g = gold[sid]
            tp, fp, fn = tp + len(pred & g), fp + len(pred - g), fn + len(g - pred)
            low = {lab for lab, v in raw.get(sid, {}).items() if v < config.LLM_CONFIDENCE_FLOOR}
            all_low, gold_low = all_low + len(low), gold_low + len(low & g)
            failed += sid in failures
        for a in rec["attempts"]:
            usage.update({k: v for k, v in a["usage"].items() if isinstance(v, (int, float))})
            cost += a["cost_usd"]
    return {"recall": round(tp / max(tp + fn, 1), 4), "precision": round(tp / max(tp + fp, 1), 4),
            "gold_listed_below_0.1": gold_low, "any_listed_below_0.1": all_low,
            "parse_failed_segments": failed,
            "input_tokens": usage["input_tokens"] + usage["cache_read_input_tokens"]
                            + usage["cache_creation_input_tokens"],
            "output_tokens": usage["output_tokens"], "thinking_blocks": usage["thinking_blocks"],
            "cost_usd": round(cost, 4)} | {
        k: round(v, 4) for k, v in run_health([records[c.key] for c in calls], version, labels).items()
        if k in ("below_floor_share", "empty_set_share", "mean_labels_listed")}


def cmd_probe(args) -> None:
    """Failure-selected windows: chooses v2 contents only; adoption comes from `compare`."""
    load_dotenv()
    model = "claude"
    segments, _, label_order = load_inputs()
    labels = set(label_order)
    gold = dict(zip(segments["segment_id"], map(set, segments["labels"])))
    calls = build_calls(_iteration_segments(segments), WINDOW)
    v1 = _cached_records(model, calls, "v1", "v1", label_order, make_classifier(model))
    if len(v1) < len(calls):
        raise SystemExit("Claude v1 at N=10 must be complete in the cache first")
    chosen, n_failing = probe_windows(v1, calls, gold, labels)
    print(f"Probe: {len(chosen)} of {n_failing} iteration windows in which v1 listed a gold label "
          "below 0.1 (seeded, stream 'probe'). Selected for failures: diagnostic only, used to "
          "choose v2's contents; adoption comes only from `compare` on the full sample.\n")
    rows = {"v1 (cache), effort low": probe_stats(v1, chosen, gold, labels, "v1")}
    for version, spec in PROBE_VARIANTS.items():
        clf = make_classifier(model, effort=spec["effort"])
        soft_checkpoint(model, [(chosen, version, version)], label_order, args.past_checkpoint,
                        classifier=clf)
        result = run_calls(model, chosen, version, version, label_order, max_cost=args.max_cost,
                           classifier=clf)
        complete_or_exit(result, chosen)
        rows[f"{version[-1]}: {spec['notes']}"] = probe_stats(result.records, chosen, gold, labels, version)
    table = pd.DataFrame(rows).T
    print(table.to_string())
    out = dict(zip("vABCDE", table["output_tokens"]))
    print(f"\nEstimated thinking tokens (output tokens minus the same windows at effort low; also "
          f"absorbs any change in answer length): A minus v1 {int(out['A'] - out['v'])}, "
          f"D minus B {int(out['D'] - out['B'])}.")


def _example_chars(call) -> int:
    targets = set(call.targets)
    texts = [text for sid, text in zip(call.segment_ids, call.texts) if sid in targets]
    return len(user_message(call, train_index().examples_for(texts))[0]) - len(user_message(call)[0])


def cmd_estimate_version(args) -> None:
    """Projects a retrieval version's cost from the base version's measured iteration run; no API calls."""
    load_dotenv()
    segments, _, label_order = load_inputs()
    it_calls = build_calls(_iteration_segments(segments), WINDOW)
    final_calls = [c for split in ("val", "test", "shift")
                   for c in build_calls(segments[segments["split"] == split], WINDOW)]
    index = train_index()
    per_call = [index.examples_for([t for sid, t in zip(c.segment_ids, c.texts) if sid in set(c.targets)])
                for c in it_calls]
    counts = [len(ex) for ex in per_call]
    shown = [e for ex in per_call for e in ex]
    print(f"Examples per call (iteration): mean {np.mean(counts):.1f}, max {max(counts)}; "
          f"labeled share {np.mean([bool(e['labels']) for e in shown]):.3f}; "
          f"mean example characters {np.mean([len(e['text']) for e in shown]):.0f}")
    it_extra = sum(_example_chars(c) for c in it_calls)
    final_extra = sum(_example_chars(c) for c in final_calls)
    for model, spec in config.LLM_MODELS.items():
        classifier = make_classifier(model)
        base = _cached_records(model, it_calls, args.base, args.base, label_order, classifier)
        if len(base) < len(it_calls):
            print(f"{model}: {args.base} iteration run incomplete in cache; skipped")
            continue
        chars = tokens = 0
        for c in it_calls:
            system, user, _, _ = _request(c, args.base, label_order, classifier)
            usage = base[c.key]["attempts"][-1]["usage"]
            if spec["provider"] == "anthropic":  # system prompt and output schema sit in the cached prefix
                chars += len(user)
                tokens += usage["input_tokens"]
            else:
                chars += len(system) + len(user)
                tokens += usage["prompt_token_count"]
        cpt = chars / tokens
        base_cost = sum(a["cost_usd"] for r in base.values() for a in r["attempts"])
        per_char = spec["price_in"] / 1e6 / cpt
        print(f"{model}: measured {cpt:.2f} characters per {'uncached user-message' if spec['provider'] == 'anthropic' else 'prompt'} token on {args.base}; "
              f"{args.base} iteration cost ${base_cost:.2f} ({len(it_calls)} calls)")
        print(f"  {args.prompt} iteration: +${it_extra * per_char:.2f} for examples, "
              f"projected ${base_cost + it_extra * per_char:.2f}")
        print(f"  if adopted, validation + test + shift ({len(final_calls)} calls): examples add "
              f"${final_extra * per_char:.2f} on top of about ${base_cost / len(it_calls) * len(final_calls):.2f} "
              f"at {args.base}'s measured cost per call")


def restrict_to(b: pd.DataFrame, a: pd.DataFrame) -> pd.DataFrame:
    missing = set(a["segment_id"]) - set(b["segment_id"])
    if missing:
        raise SystemExit(f"B lacks {len(missing)} of A's segments; cannot pair them")
    return b[b["segment_id"].isin(set(a["segment_id"]))].reset_index(drop=True)


def cmd_compare(args) -> None:
    label_order = _label_order_cached()
    frames = []
    for spec in (args.a, args.b):
        version, n = spec.split(":")
        frames.append(pd.read_parquet(iteration_path(args.model, version, int(n))))
    if args.restrict_b_to_a:
        frames[1] = restrict_to(frames[1], frames[0])
    out = paired_micro_f1(frames[0], frames[1], label_order)
    print(f"{args.model}: A={args.a} minus B={args.b}, unstratified paired contract bootstrap "
          f"({config.BOOTSTRAP_RESAMPLES} resamples, seed {config.SEED}, stream 'iteration'), "
          f"{out['contracts']} contracts, {out['segments']} segments")
    for m in ("micro_f1", "macro_f1"):
        d = out[m]
        print(f"  {m}: A {d['a']:.4f}  B {d['b']:.4f}  A-B {d['difference']:+.4f} "
              f"[{d['ci_low']:+.4f}, {d['ci_high']:+.4f}]{'  (reported only)' if m == 'macro_f1' else ''}")
    print(f"  A better than B on micro-F1 with the interval excluding zero: {out['a_better']}")
    dest = config.EVAL_DIR / "llm_selection" / f"{args.model}_{args.a}_vs_{args.b}.json".replace(":", "n")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2, default=float))


def model_dir(model_key) -> Path:
    return config.MODELS_DIR / model_key


RUN_SETTINGS = ("model_id", "effort", "thinking_level", "max_tokens")


def run_settings(model_key) -> dict:
    spec = config.LLM_MODELS[model_key]
    return {k: spec[k] for k in RUN_SETTINGS if k in spec}


def cmd_freeze(args) -> None:
    label_order = _label_order_cached()
    path = model_dir(args.model) / "prompt.json"
    if path.exists() and not args.force:
        raise SystemExit(f"{path} exists: the prompt is already frozen")
    if not iteration_path(args.model, args.prompt, args.batch_size).exists():
        raise SystemExit("freeze only a version that has a full iteration run")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "model_key": args.model, "model_id": config.LLM_MODELS[args.model]["model_id"],
        "version": args.prompt, "batch_size": args.batch_size, "run_settings": run_settings(args.model),
        "prompt_hash": prompt_hash(args.prompt, label_order), "frozen_utc": _now(),
        "forced": bool(args.force), "system_prompt": system_prompt(args.prompt, label_order),
        "output_schema": schema_for(args.prompt, label_order)}, indent=2))
    print(f"Froze {args.model}: prompt {args.prompt}, batch size {args.batch_size}, "
          f"hash {prompt_hash(args.prompt, label_order)} -> {path}")


def load_frozen(model_key) -> dict:
    path = model_dir(model_key) / "prompt.json"
    if not path.exists():
        raise SystemExit(f"{path} missing: freeze a prompt first")
    frozen = json.loads(path.read_text())
    if prompt_hash(frozen["version"], _label_order_cached()) != frozen["prompt_hash"]:
        raise SystemExit("the prompt text changed after freezing; refusing")
    if frozen.get("run_settings") != run_settings(model_key):
        raise SystemExit(f"model settings changed after freezing (frozen {frozen.get('run_settings')}, "
                         f"now {run_settings(model_key)}); refusing")
    return frozen


def cmd_val(args) -> None:
    load_dotenv()
    frozen = load_frozen(args.model)
    segments, _, label_order = load_inputs()
    calls = build_calls(segments[segments["split"] == "val"], frozen["batch_size"])
    soft_checkpoint(args.model, [(calls, frozen["version"], frozen["version"])], label_order,
                    args.past_checkpoint)
    result = run_calls(args.model, calls, frozen["version"], frozen["version"], label_order,
                       max_cost=args.max_cost)
    complete_or_exit(result, calls)
    frame = build_frame(segments, calls, result, label_order, {}, args.model,
                        _version_tag(args.model, frozen["version"], served_models(result)))
    write_predictions(frame, config.PREDICTIONS_DIR / f"{args.model}_val.parquet", label_order,
                      {"scores": scores_note(frozen["version"]), "thresholds": "provisional 0.5; run `thresholds`",
                       "latency_ms": "call-amortized", "prompt_version": frozen["version"],
                       "batch_size": frozen["batch_size"]})
    print(f"Full validation, frozen prompt {frozen['version']} (threshold 0.5, provisional):")
    _print(score(frame, label_order, is_sparse(frozen["version"])), "  ")
    print("Usage:")
    _print(usage_report(result, calls, frozen["batch_size"], frozen["version"], set(label_order)), "  ")


def cmd_thresholds(args) -> None:
    frozen = load_frozen(args.model)
    path = config.PREDICTIONS_DIR / f"{args.model}_val.parquet"
    val = pd.read_parquet(path)
    label_order = read_label_order(path)
    thresholds, pooled = llm_thresholds(val, label_order)
    (model_dir(args.model) / "thresholds.json").write_text(json.dumps(thresholds, indent=2, sort_keys=True))
    proba = np.vstack(val["proba"].to_numpy())
    pred = proba >= np.array([thresholds[lab] for lab in label_order])
    val["pred_labels"] = [[{"label": lab, "confidence": float(p)} for lab, p, on in zip(label_order, row_p, row_on) if on]
                          for row_p, row_on in zip(proba, pred)]
    served = val["model_version"].iloc[0].split("|")[0].split("/")
    val["model_version"] = _version_tag(args.model, frozen["version"], served, thresholds)
    write_predictions(val, path, label_order,
                      {"scores": scores_note(frozen["version"]), "thresholds": "Rule B, tuned on validation",
                       "latency_ms": "call-amortized", "prompt_version": frozen["version"],
                       "batch_size": frozen["batch_size"]})
    print(f"Rule B pooled labels ({len(pooled)}): {pooled}")
    print(f"Pooled threshold: {thresholds[pooled[0]] if pooled else 'n/a'}")
    print("Per-class thresholds:")
    for lab in label_order:
        if lab not in pooled:
            print(f"  {lab}: {thresholds[lab]}")
    print("Validation with Rule B thresholds (tuned on this set, so optimistic):")
    _print(score(val, label_order, is_sparse(frozen["version"])), "  ")


def cmd_repeat(args) -> None:
    load_dotenv()
    frozen = load_frozen(args.model)
    thresholds = json.loads((model_dir(args.model) / "thresholds.json").read_text())
    segments, _, label_order = load_inputs()
    wins = windows(_iteration_segments(segments))[:config.LLM_REPEAT_WINDOWS]
    seg = pd.concat([w for _, _, w in wins])
    calls = build_calls(seg, frozen["batch_size"])
    namespaces = [frozen["version"]] + [f"{frozen['version']}_repeat{i + 1}"
                                         for i in range(config.LLM_REPEAT_RUNS)]
    soft_checkpoint(args.model, [(calls, frozen["version"], ns) for ns in namespaces], label_order,
                    args.past_checkpoint)
    runs, results, health = [], [], {}
    for ns in namespaces:
        result = run_calls(args.model, calls, frozen["version"], ns, label_order, max_cost=args.max_cost)
        complete_or_exit(result, calls)
        results.append(result)
        health[ns] = _health_or_note([result.records[c.key] for c in calls], frozen["version"], set(label_order))
        runs.append(build_frame(segments, calls, result, label_order, thresholds, args.model, ns)
                    .set_index("segment_id").sort_index())
    sets = [r["pred_labels"].map(lambda ps: frozenset(d["label"] for d in ps)) for r in runs]
    conf = [r["proba"].map(np.asarray) for r in runs]
    pairs = [(i, j) for i in range(len(runs)) for j in range(i + 1, len(runs))]
    report = {"segments": len(seg), "runs": namespaces, "pairwise_exact_agreement": {},
              "none_vs_some_flip_rate": {}, "mean_abs_confidence_diff_listed_in_both": {}}
    for i, j in pairs:
        name = f"{namespaces[i]} vs {namespaces[j]}"
        report["pairwise_exact_agreement"][name] = float((sets[i] == sets[j]).mean())
        report["none_vs_some_flip_rate"][name] = float(((sets[i].map(len) == 0) != (sets[j].map(len) == 0)).mean())
        diffs = [np.abs(a - b)[(a > 0) & (b > 0)] for a, b in zip(conf[i], conf[j])]
        both = np.concatenate([d for d in diffs if len(d)]) if any(len(d) for d in diffs) else np.array([])
        report["mean_abs_confidence_diff_listed_in_both"][name] = float(both.mean()) if len(both) else float("nan")
    report["all_runs_exact_agreement"] = float(np.mean([len({s[k] for s in sets}) == 1 for k in sets[0].index]))
    report["parse_failures_per_run"] = [int(r["parse_failure"].sum()) for r in runs]
    report["run_health"] = health
    per_label = {}
    for lab in label_order:
        flags = [s.map(lambda x: lab in x) for s in sets]
        if any(f.any() for f in flags):
            per_label[lab] = float(np.mean([len({f[k] for f in flags}) == 1 for k in flags[0].index]))
    report["per_label_all_runs_agreement"] = per_label
    report["new_spend_usd"] = sum(sum(a["cost_usd"] for r in res.records.values() for a in r["attempts"])
                                  for res in results[1:])
    dest = config.EVAL_DIR / f"llm_repeat_{args.model}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, indent=2))
    print(f"Repeat check, {args.model}, frozen prompt {frozen['version']}, Rule B thresholds, "
          f"{len(seg)} segments ({config.LLM_REPEAT_WINDOWS} windows), {len(namespaces)} runs:")
    for k, v in report.items():
        if k != "per_label_all_runs_agreement":
            print(f"  {k}: {v}")
    print("  per-label agreement across all runs (labels predicted in any run):")
    for lab, v in sorted(per_label.items(), key=lambda kv: kv[1]):
        print(f"    {lab}: {v:.3f}")


def heldout_guard(marker: Path, prompt_hash_: str, force: bool) -> dict:
    """Test is touched once per model. A completed run blocks reruns unless forced (and
    logged). A started but incomplete run may resume: no predictions or metrics were shown."""
    state = json.loads(marker.read_text()) if marker.exists() else {}
    if state.get("completed_utc") and not force:
        raise SystemExit(f"Refusing: held-out sets already evaluated ({state}). Test is touched once "
                         "per model. Override with --i-know-this-reruns-test, and log it.")
    if not state or state.get("completed_utc"):
        state = {"started_utc": _now(), "prompt_hash": prompt_hash_, "forced": bool(force)}
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(state))
    return state


def heldout_namespace(state: dict, split: str, version: str, redo: bool) -> str:
    invalid, redone = state.get("invalid", {}), state.get("redone", {})
    if split in redone:
        return f"{version}-redo1"
    if split in invalid:
        if not redo:
            raise SystemExit(f"{split} was declared invalid for infrastructure reasons ({invalid[split]}); "
                             "redo it once with --redo-invalid")
        return f"{version}-redo1"
    return version


def record_health(state: dict, split: str, health: dict) -> str:
    over = health["below_floor_share"] > config.LLM_HEALTH_MAX_SHARE
    if split in state.get("invalid", {}):
        state.setdefault("redone", {})[split] = health
        return "unreliable" if over else "ok"  # one redo only, and it stands
    if over:
        state.setdefault("invalid", {})[split] = health
        return "invalid"
    state.setdefault("health", {})[split] = health
    return "ok"


def heldout_health(records, version, labels, state, split) -> tuple[str, dict, dict]:
    """(status, health, file notes); dense runs have no invalidation rule, so record_health is skipped."""
    if is_sparse(version):
        health = run_health(records, version, labels)
        status = record_health(state, split, health)
        return status, health, {"run_health_status": status,
                                "run_health_below_floor_share": f"{health['below_floor_share']:.4f}"}
    health = dense_health(records, version, labels)
    status = "not applicable (dense)"
    return status, health, {"run_health_status": status,
                            **{f"dense_health_{k}": f"{v:.4f}" for k, v in health.items() if isinstance(v, float)}}


def cmd_heldout(args) -> None:
    load_dotenv()
    frozen = load_frozen(args.model)
    version = frozen["version"]
    thr_path = model_dir(args.model) / "thresholds.json"
    if not thr_path.exists():
        raise SystemExit("run `thresholds` first")
    thresholds = json.loads(thr_path.read_text())
    segments, _, label_order = load_inputs()
    labels = set(label_order)
    marker = model_dir(args.model) / "heldout_run.json"
    prior = json.loads(marker.read_text()) if marker.exists() else {}
    if args.redo_invalid and not prior.get("invalid"):
        raise SystemExit("--redo-invalid applies only after a split was declared invalid")
    splits = ("test", "shift")
    namespaces = {sp: heldout_namespace(prior, sp, version, args.redo_invalid) for sp in splits}
    split_calls = {sp: build_calls(segments[segments["split"] == sp], frozen["batch_size"]) for sp in splits}
    soft_checkpoint(args.model, [(split_calls[sp], version, namespaces[sp]) for sp in splits],
                    label_order, args.past_checkpoint)
    state = heldout_guard(marker, frozen["prompt_hash"], args.force)
    for split in splits:
        calls = split_calls[split]
        result = run_calls(args.model, calls, version, namespaces[split], label_order, max_cost=args.max_cost)
        complete_or_exit(result, calls)  # an incomplete run can be resumed; no metrics were shown
        status, health, health_notes = heldout_health([result.records[c.key] for c in calls], version, labels,
                                                      state, split)
        marker.write_text(json.dumps(state))
        frame = build_frame(segments, calls, result, label_order, thresholds, args.model,
                            _version_tag(args.model, version, served_models(result), thresholds))
        path = config.PREDICTIONS_DIR / f"{args.model}_{split}{'_invalid' if status == 'invalid' else ''}.parquet"
        write_predictions(frame, path, label_order,
                          {"scores": scores_note(version), "thresholds": "Rule B, tuned on validation",
                           "latency_ms": "call-amortized", "prompt_version": version,
                           "batch_size": frozen["batch_size"], "cache_namespace": namespaces[split],
                           **health_notes})
        print(f"{split}: {len(frame)} segments written to {path.name}; parse failures "
              f"{int(frame['parse_failure'].sum())}; run health {status}"
              f"{'' if is_sparse(version) else ' (no invalidation rule for dense output)'}")
        print("  usage:")
        _print(usage_report(result, calls, frozen["batch_size"], version, labels), "    ")
        if status == "invalid":
            raise SystemExit(f"{split} declared invalid for infrastructure reasons: below-floor share "
                             f"{health['below_floor_share']:.2%} > {config.LLM_HEALTH_MAX_SHARE:.0%} "
                             f"(run-health rule, BUILD_LOG 3n). Redo it once with: python -m src.llm.run "
                             f"heldout --model {args.model} --redo-invalid")
        if status == "unreliable":
            print(f"  FLAG: the one redo of {split} also exceeds {config.LLM_HEALTH_MAX_SHARE:.0%}; "
                  "it stands and is reported as unreliable for infrastructure reasons")
    state["completed_utc"] = _now()
    marker.write_text(json.dumps(state))
    print(f"Done. Score with: python -m src.evaluate model {args.model}")

TIMEOUT_PREFIXES = ("connection:", "408", "504")


def is_timeout(error: str) -> bool:
    return error.startswith(TIMEOUT_PREFIXES)


def _output_tokens(usage: dict) -> int:
    return (usage.get("output_tokens", 0) + usage.get("candidates_token_count", 0)
            + usage.get("thoughts_token_count", 0))


def _input_cost(usage: dict, spec: dict) -> float:
    if spec["provider"] == "anthropic":
        prefix = usage.get("cache_creation_input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
        return (prefix * spec["price_cache_read"] + usage.get("input_tokens", 0) * spec["price_in"]) / 1e6
    return usage.get("prompt_token_count", 0) * spec["price_in"] / 1e6


def _run_stats(records) -> dict:
    attempts = [a for r in records for a in r["attempts"]]
    targets = sum(len(r["targets"]) for r in records)
    return {"calls": len(records), "targets": targets,
            "cost_per_call": sum(a["cost_usd"] for a in attempts) / max(len(records), 1),
            "out_per_target": sum(_output_tokens(a["usage"]) for a in attempts) / max(targets, 1)}


def smoke_check(records, expected, labels) -> list[str]:
    """Reasons the model fails the v4 stop condition; empty when it passes."""
    reasons = []
    if len(records) < expected:
        reasons.append(f"{len(records)} of {expected} smoke records")
    for rec in records:
        for a in rec["attempts"]:
            if _output_tokens(a["usage"]) > config.LLM_V4_STOP_OUTPUT_TOKENS:
                reasons.append(f"{rec['call_key']}: output {_output_tokens(a['usage'])} tokens")
            if a["latency_ms"] > config.LLM_V4_STOP_LATENCY_S * 1000:
                reasons.append(f"{rec['call_key']}: latency {a['latency_ms']:.0f} ms")
            reasons += [f"{rec['call_key']}: timeout {e!r}" for e in a.get("retry_errors", []) if is_timeout(e)]
        _, failures = record_scores(rec, labels)
        reasons += [f"{rec['call_key']}: {sid} unparsed after retry" for sid in failures]
    return reasons


def dense_call_cost(v3: dict, input_diff: float, dense_out_per_target: float, price_out: float) -> float:
    targets_per_call = v3["targets"] / v3["calls"]
    return (v3["cost_per_call"] + input_diff
            + (dense_out_per_target - v3["out_per_target"]) * targets_per_call * price_out / 1e6)


def n1_call_cost(base: dict, input_diff: float, out_per_target: float, price_out: float) -> float:
    input_per_call = base["cost_per_call"] - base["out_per_target"] * base["targets"] / base["calls"] * price_out / 1e6
    return input_per_call + input_diff + out_per_target * price_out / 1e6


def project(call_cost: float, n1_cost: float, n1_calls: int, iteration_calls: int = 357,
            final_calls: int = 2310, repeat_calls: int = config.LLM_REPEAT_RUNS * config.LLM_REPEAT_WINDOWS) -> dict:
    """Remaining spend for one model; iteration_calls is 0 for a model staying on its incumbent."""
    parts = {"iteration": call_cost * iteration_calls, "val_test_shift": call_cost * final_calls,
             "n1_upper_bound": n1_cost * n1_calls, "repeat": call_cost * repeat_calls}
    return {**parts, "total": sum(parts.values())}


def gate_branch(spent, combined, gemini_only, claude_ok, gemini_ok,
                soft=config.LLM_SOFT_CHECKPOINT_USD, cap=config.LLM_BUDGET_USD) -> str:
    if not gemini_ok:
        return "neither: Gemini failed the smoke, so no v4 for either model"
    both = spent + combined if claude_ok else None
    solo = spent + gemini_only
    if both is not None and both <= cap:
        if both <= soft:
            return "both"
        fallback = ("gemini-only" if solo <= soft else
                    f"gemini-only is also above ${soft:.0f}: decide on it; if declined too, Rule E fallback (no v4)")
        return f"both, above ${soft:.0f}: decide now; if declined, {fallback}"
    if solo <= cap:
        return "gemini-only" if solo <= soft else f"gemini-only, above ${soft:.0f}: decide now; if declined, Rule E fallback (no v4)"
    return "neither: no option fits under the hard cap"


V4_ITERATION_CALLS = 357


def iteration_calls_left(v4_smoke) -> int:
    return V4_ITERATION_CALLS - len(v4_smoke)


def _complete(records: dict, calls, what: str) -> list:
    if len(records) < len(calls):
        raise SystemExit(f"gate-v4: {what} has {len(records)} of {len(calls)} cached calls; complete it first")
    return list(records.values())


def cmd_gate_v4(_args) -> None:
    load_dotenv()
    segments, _, label_order = load_inputs()
    labels = set(label_order)
    calls = build_calls(_iteration_segments(segments), WINDOW)
    smoke_calls = calls[:3]
    sample = pd.read_csv(config.LLM_ITERATION_CONTRACTS)
    n1_calls = int(sample["segments"].nlargest(-(-len(sample) // 2)).sum())
    spent = Ledger(config.LLM_LEDGER).prior_total
    rows, ok = {}, {}
    for model, spec in config.LLM_MODELS.items():
        clf = make_classifier(model)
        v4_smoke = list(_cached_records(model, smoke_calls, "v4", "v4", label_order, clf).values())
        v3_smoke = {r["call_key"]: r for r in _complete(_cached_records(model, smoke_calls, "v3", "v3", label_order, clf),
                                                        smoke_calls, f"{model} v3 smoke")}
        v3 = _run_stats(_complete(_cached_records(model, calls, "v3", "v3", label_order, clf), calls,
                                  f"{model} v3 iteration run"))
        reasons = smoke_check(v4_smoke, len(smoke_calls), labels)
        ok[model] = not reasons
        matched = [(r, v3_smoke[r["call_key"]]) for r in v4_smoke if r["call_key"] in v3_smoke]
        input_diff = sum(sum(_input_cost(a["usage"], spec) for a in r4["attempts"])
                         - sum(_input_cost(a["usage"], spec) for a in r3["attempts"])
                         for r4, r3 in matched) / max(len(matched), 1)
        dense_out = _run_stats(v4_smoke)["out_per_target"] if v4_smoke else float("nan")
        call_cost = dense_call_cost(v3, input_diff, dense_out, spec["price_out"])
        rows[model] = project(call_cost, n1_call_cost(v3, input_diff, dense_out, spec["price_out"]), n1_calls,
                              iteration_calls=iteration_calls_left(v4_smoke))
        attempts = [a for r in v4_smoke for a in r["attempts"]]
        print(f"{model}: smoke {'PASS' if ok[model] else 'FAIL'} {reasons or ''}")
        print(f"  max output tokens {max((_output_tokens(a['usage']) for a in attempts), default=0)} "
              f"(stop {config.LLM_V4_STOP_OUTPUT_TOKENS}, max_tokens {spec['max_tokens']}); max latency "
              f"{max((a['latency_ms'] for a in attempts), default=0):.0f} ms (stop {config.LLM_V4_STOP_LATENCY_S * 1000:.0f}, "
              f"timeout {config.LLM_TIMEOUT_S * 1000:.0f}); transport retries {sum(a['transport_retries'] for a in attempts)}")
        print(f"  dense output {dense_out:.0f} tokens per target (v3 {v3['out_per_target']:.0f}); input difference "
              f"${input_diff:.5f} per call; dense cost ${call_cost:.5f} per call; projection "
              f"{ {k: round(v, 2) for k, v in rows[model].items()} }")
    claude_v2 = _run_stats(_complete(_cached_records("claude", calls, "v2", "v2", label_order, make_classifier("claude")),
                                     calls, "claude v2 iteration run"))
    price = config.LLM_MODELS["claude"]["price_out"]
    claude_stay = project(claude_v2["cost_per_call"], n1_call_cost(claude_v2, 0.0, claude_v2["out_per_target"], price),
                          n1_calls, iteration_calls=0)
    combined = rows["claude"]["total"] + rows["gemini"]["total"]
    gemini_only = rows["gemini"]["total"] + claude_stay["total"]
    print(f"\nN=1 check sized as an upper bound: {n1_calls} calls (segments of the {-(-len(sample) // 2)} "
          f"largest iteration contracts), per model.")
    print(f"Spent so far ${spent:.2f}. Combined: ${spent + combined:.2f}. Gemini-only (Claude on v2): "
          f"${spent + gemini_only:.2f}. Soft checkpoint ${config.LLM_SOFT_CHECKPOINT_USD:.0f}, hard cap "
          f"${config.LLM_BUDGET_USD:.0f}.")
    print(f"Rule E branch: {gate_branch(spent, combined, gemini_only, ok['claude'], ok['gemini'])}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sample")
    sub.add_parser("estimate")
    sub.add_parser("yardstick")
    sub.add_parser("gate-v4")
    sub.add_parser("n1-sample")
    p = sub.add_parser("estimate-version")
    p.add_argument("--prompt", required=True)
    p.add_argument("--base", required=True)
    models = list(config.LLM_MODELS)
    p = sub.add_parser("probe")
    p.add_argument("--max-cost", type=float)
    p.add_argument("--past-checkpoint", action="store_true",
                   help="approve continuing past the $100 soft checkpoint (Rule E)")
    p = sub.add_parser("breakdown")
    p.add_argument("--model", choices=models, required=True)
    p.add_argument("--prompt", required=True)
    p.add_argument("--batch-size", type=int, choices=[1, WINDOW], default=WINDOW)
    p = sub.add_parser("iterate")
    p.add_argument("--model", choices=models, required=True)
    p.add_argument("--prompt", required=True)
    p.add_argument("--batch-size", type=int, choices=[1, WINDOW], default=WINDOW)
    p.add_argument("--limit", type=int)
    p.add_argument("--max-cost", type=float)
    p.add_argument("--rerun", help="fresh cache namespace for the same prompt, e.g. r2")
    p.add_argument("--subset", choices=["n1-half"], help="the seeded half of the iteration contracts, N=1 only")
    p.add_argument("--past-checkpoint", action="store_true",
                   help="approve continuing past the $100 soft checkpoint (Rule E)")
    p = sub.add_parser("compare")
    p.add_argument("--model", choices=models, required=True)
    p.add_argument("--a", required=True, help="VERSION:BATCH_SIZE, e.g. v2:10")
    p.add_argument("--b", required=True)
    p.add_argument("--restrict-b-to-a", action="store_true", help="pair on A's segments only (N=1 half check)")
    p = sub.add_parser("freeze")
    p.add_argument("--model", choices=models, required=True)
    p.add_argument("--prompt", required=True)
    p.add_argument("--batch-size", type=int, choices=[1, WINDOW], required=True)
    p.add_argument("--force", action="store_true")
    for name in ("val", "repeat", "heldout"):
        p = sub.add_parser(name)
        p.add_argument("--model", choices=models, required=True)
        p.add_argument("--max-cost", type=float)
        p.add_argument("--past-checkpoint", action="store_true",
                       help="approve continuing past the $100 soft checkpoint (Rule E)")
        if name == "heldout":
            p.add_argument("--i-know-this-reruns-test", dest="force", action="store_true")
            p.add_argument("--redo-invalid", action="store_true",
                           help="redo a split declared invalid by the run-health rule, once")
    p = sub.add_parser("thresholds")
    p.add_argument("--model", choices=models, required=True)
    args = parser.parse_args()
    {"sample": cmd_sample, "estimate": cmd_estimate, "yardstick": cmd_yardstick,
     "breakdown": cmd_breakdown, "probe": cmd_probe, "estimate-version": cmd_estimate_version,
     "gate-v4": cmd_gate_v4, "n1-sample": cmd_n1_sample,
     "iterate": cmd_iterate, "compare": cmd_compare,
     "freeze": cmd_freeze, "val": cmd_val, "thresholds": cmd_thresholds, "repeat": cmd_repeat,
     "heldout": cmd_heldout}[args.cmd](args)


if __name__ == "__main__":
    main()

"""Inference on new text for the review service (Step 7). Frozen models only; nothing is tuned here.

Each served model becomes a Predictor: its frozen version, label order, thresholds per operating
point ("balanced" = Rule B; "high_recall" = src/high_recall.py, validation only) and a scorer.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from src import config
from src.thresholds import apply_thresholds

DEEPSEEK = "fireworks-deepseek"
SERVED = ("baseline", config.TUNED_MODEL_NAME, DEEPSEEK)


class ServiceBudget(RuntimeError):
    """A spend cap refuses the request (per request, service, or the shared $150)."""


class ServiceUpstream(RuntimeError):
    """Every API call for the document failed."""


@dataclass
class Scored:
    proba: np.ndarray            # (segments, labels)
    unscored: np.ndarray         # bool per segment: failed call or parse failure
    latency_ms: float            # per segment
    cost_usd: float              # whole document


@dataclass
class Artifacts:
    version: str
    label_order: list[str]
    rule_b: dict[str, float]
    directory: Path | None = None


@dataclass
class Predictor:
    name: str
    version: str
    label_order: list[str]
    thresholds: dict[str, dict[str, float]]
    score: Callable[[list[str]], Scored]
    notes: dict = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def scores(self, texts: list[str]) -> Scored:
        with self.lock:
            return self.score(texts)


def high_recall_path(name: str) -> Path:
    return config.SERVICE_DIR / f"{name}_thresholds_high_recall.json"


def artifacts(name: str) -> Artifacts:
    """Frozen version, label order and Rule B thresholds; refuses artifacts that changed."""
    if name == "baseline":
        from src import baseline
        return Artifacts(baseline.model_version(),
                         json.loads((config.BASELINE_DIR / "labels.json").read_text())["label_order"],
                         json.loads((config.BASELINE_DIR / "thresholds.json").read_text()))
    if name == config.TUNED_MODEL_NAME:
        from src import transformer as T
        from src.transformer_tuned import check_recipe
        selected = json.loads((config.TUNED_DIR / "selected.json").read_text())
        key = selected["candidate"]
        if T.model_version(key, config.TUNED_DIR) != selected["model_version"]:
            raise SystemExit(f"{name}: artifacts changed since selection")
        d = config.TUNED_DIR / key
        run = json.loads((d / "run.json").read_text())
        check_recipe(run, run["run"])
        return Artifacts(selected["model_version"], json.loads((d / "labels.json").read_text())["label_order"],
                         json.loads((d / "thresholds.json").read_text()), d)
    if name == DEEPSEEK:
        from src.llm import run as R
        frozen = R.load_frozen(DEEPSEEK)
        rule_b = json.loads((R.model_dir(DEEPSEEK) / "thresholds.json").read_text())
        return Artifacts(R._version_tag(DEEPSEEK, frozen["version"], [frozen["model_id"]], rule_b),
                         R._label_order_cached(), rule_b)
    raise KeyError(f"unknown model {name}")


def _thresholds(name: str, art: Artifacts) -> tuple[dict, dict]:
    out, notes = {"balanced": art.rule_b}, {}
    path = high_recall_path(name)
    if not path.exists():
        notes["high_recall"] = "not available: run python -m src.high_recall"
    else:
        hr = json.loads(path.read_text())
        if hr["model_version"] != art.version:
            notes["high_recall"] = "not available: thresholds were tuned for another model version"
        else:
            out["high_recall"] = hr["thresholds"]
            if hr["below_target"]:
                notes["high_recall"] = f"Below the target on validation: {', '.join(hr['below_target'])}."
    return out, notes


def _predictor(name: str, art: Artifacts, score, **notes) -> Predictor:
    thresholds, hr_notes = _thresholds(name, art)
    return Predictor(name, art.version, art.label_order, thresholds, score, {**hr_notes, **notes})


def _baseline() -> Predictor:
    from src import baseline
    art = artifacts("baseline")
    pipe = baseline.load_frozen_pipeline()

    def score(texts):
        proba, ms = baseline.timed_proba(pipe, list(texts))
        return Scored(np.asarray(proba), np.zeros(len(texts), dtype=bool), ms, 0.0)

    return _predictor("baseline", art, score)


def _transformer_tuned() -> Predictor:
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    from src import transformer as T
    art = artifacts(config.TUNED_MODEL_NAME)
    tok = AutoTokenizer.from_pretrained(art.directory)
    model = AutoModelForSequenceClassification.from_pretrained(art.directory).float()
    T.predict_proba(model, tok, ["Warm-up segment one.", "Warm-up segment two."])  # once, at load

    def score(texts):
        proba, _, ms = T.predict_proba(model, tok, list(texts), warm=False)
        return Scored(proba, np.zeros(len(texts), dtype=bool), ms, 0.0)

    return _predictor(config.TUNED_MODEL_NAME, art, score)


def service_ledger():
    """One per process. Its cap keeps service spend under SERVICE_LLM_CAP_USD and research plus
    service spend under the shared LLM_BUDGET_USD."""
    from src.llm.cache import Ledger
    research = Ledger(config.LLM_LEDGER).prior_total
    return Ledger(config.SERVICE_LEDGER, cap_usd=min(config.SERVICE_LLM_CAP_USD, config.LLM_BUDGET_USD - research))


def _deepseek_scores(texts, frozen, label_order, ledger, classifier, request_cap=None):
    from src.llm import run as R
    from src.llm.clients import worst_case_cost
    from src.llm.windows import build_calls

    cap = config.SERVICE_REQUEST_CAP_USD if request_cap is None else request_cap
    seg = pd.DataFrame({"contract_id": 0, "seg_idx": range(len(texts)),
                        "segment_id": [f"doc_{i}" for i in range(len(texts))], "text": list(texts)})
    index = {sid: i for i, sid in enumerate(seg["segment_id"])}
    calls = build_calls(seg, frozen["batch_size"])
    worst = sum(worst_case_cost(*R._messages(c, frozen["version"], label_order)[:2], classifier.spec) for c in calls)
    if worst > cap:
        raise ServiceBudget(f"document needs up to ${worst:.2f} at worst case, over the per-request cap ${cap:.2f}")
    left = ledger.cap - ledger.prior_total - ledger.run_spent - ledger.reserved
    if worst > left:
        raise ServiceBudget(f"document needs up to ${worst:.2f} at worst case; ${left:.2f} of the service budget is left")
    spent_before = ledger.run_spent
    result = R.run_calls(DEEPSEEK, calls, frozen["version"], "service", label_order,
                         classifier=classifier, ledger=ledger)
    if result.stopped:
        raise ServiceBudget(result.stopped)
    if not result.records and result.failed:
        raise ServiceUpstream(next(iter(result.failed.values())))
    col = {lab: j for j, lab in enumerate(label_order)}
    proba, unscored = np.zeros((len(texts), len(label_order))), np.ones(len(texts), dtype=bool)
    for c in calls:
        rec = result.records.get(c.key)
        if rec is None:  # failed after retries: stays unscored, shown as "not classified"
            continue
        scores, failures = R.record_scores(rec, set(label_order))
        for sid in rec["targets"]:
            i = index[sid]
            unscored[i] = sid in failures
            for lab, conf in scores.get(sid, {}).items():
                proba[i, col[lab]] = conf
    return proba, unscored, ledger.run_spent - spent_before  # cache hits cost nothing


def _deepseek(ledger=None, classifier=None) -> Predictor:
    from dotenv import load_dotenv

    from src.llm import run as R
    from src.llm.clients import make_classifier
    load_dotenv()
    if classifier is None and not os.environ.get("FIREWORKS_API_KEY"):
        raise RuntimeError("FIREWORKS_API_KEY is not set")
    art = artifacts(DEEPSEEK)
    frozen = R.load_frozen(DEEPSEEK)
    classifier = classifier or make_classifier(DEEPSEEK)
    ledger = ledger or service_ledger()

    def score(texts):
        t0 = time.perf_counter()
        proba, unscored, cost = _deepseek_scores(texts, frozen, art.label_order, ledger, classifier)
        return Scored(proba, unscored, 1000 * (time.perf_counter() - t0) / max(len(texts), 1), cost)

    return _predictor(DEEPSEEK, art, score, data="document text is sent to Fireworks")


LOADERS = {"baseline": _baseline, config.TUNED_MODEL_NAME: _transformer_tuned, DEEPSEEK: _deepseek}


def load_predictors(names, loaders=None) -> tuple[dict[str, Predictor], dict[str, str]]:
    """A model that fails to load (missing weights or key, changed artifacts) is left out, with the reason."""
    loaders = LOADERS if loaders is None else loaders
    ok, failed = {}, {}
    for name in names:
        try:
            if name not in loaders:
                raise KeyError(f"unknown model {name}")
            ok[name] = loaders[name]()
        except (SystemExit, Exception) as e:
            failed[name] = f"{type(e).__name__}: {e}"
    return ok, failed


def records(segments, scored: Scored, predictor: Predictor, point: str) -> list[dict]:
    """Shared prediction format (docs/plan.md), plus `scored`; unscored segments carry no labels."""
    flags = apply_thresholds(scored.proba, predictor.label_order, predictor.thresholds[point])
    out = []
    for i, (s, p, f) in enumerate(zip(segments, scored.proba, flags)):
        ok = not bool(scored.unscored[i])
        out.append({"segment_id": f"doc_{i}", "start": s.start, "end": s.end,
                    "labels": [{"label": lab, "confidence": float(p[j])}
                               for j, lab in enumerate(predictor.label_order) if f[j] and ok],
                    "scored": ok, "model_name": predictor.name, "model_version": predictor.version,
                    "latency_ms": scored.latency_ms, "cost_usd": scored.cost_usd / max(len(segments), 1)})
    return out

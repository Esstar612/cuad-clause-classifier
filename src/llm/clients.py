"""API clients for the LLM classifiers (Step 3): request building, retries, usage to cost.

Latency is measured from the moment the request is handed to the SDK until the response
returns, for the successful attempt only. Rate-limiter and thread-pool waits happen before
the timer starts; backoff sleeps and failed attempts are recorded separately. The SDKs'
own retries are disabled so that every attempt is timed and counted here.
"""

from __future__ import annotations

import os
import random
import threading
import time
from dataclasses import asdict, dataclass, field

from src import config


@dataclass
class Attempt:
    """One API request that returned a response (valid or not)."""
    text: str | None
    finish: str            # "ok", "max_tokens", "refusal", or "other:<reason>"
    served_model: str
    usage: dict
    cost_usd: float
    latency_ms: float      # successful HTTP round trip only
    transport_retries: int
    backoff_s: float
    retry_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def anthropic_cost(usage: dict, spec: dict) -> float:
    """Output tokens include thinking tokens on Claude."""
    return (usage.get("input_tokens", 0) * spec["price_in"]
            + usage.get("cache_creation_input_tokens", 0) * spec["price_cache_write"]
            + usage.get("cache_read_input_tokens", 0) * spec["price_cache_read"]
            + usage.get("output_tokens", 0) * spec["price_out"]) / 1e6


def gemini_cost(usage: dict, spec: dict) -> float:
    """Thinking tokens are billed at the output price on Gemini."""
    prompt = usage.get("prompt_token_count", 0)
    cached = usage.get("cached_content_token_count", 0)
    out = usage.get("candidates_token_count", 0) + usage.get("thoughts_token_count", 0)
    return ((prompt - cached) * spec["price_in"] + cached * spec["price_cache_read"]
            + out * spec["price_out"]) / 1e6


def worst_case_cost(system: str, user: str, spec: dict) -> float:
    """Upper bound for the budget check: ~3 characters per token, nothing cached, and the
    full max_tokens of output."""
    tokens_in = (len(system) + len(user)) / 3
    return (tokens_in * max(spec["price_in"], spec["price_cache_write"])
            + spec["max_tokens"] * spec["price_out"]) / 1e6


class RateLimiter:
    """Spaces request starts so at most `rpm` begin per minute (per client)."""

    def __init__(self, rpm: int):
        self.interval = 60.0 / rpm
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next)
            self._next = start + self.interval
        time.sleep(max(0.0, start - time.monotonic()))


class _Transient(Exception):
    """A retryable transport failure (429, 5xx, timeout, connection)."""


def _with_retries(send, limiter: RateLimiter, max_attempts: int = config.LLM_MAX_ATTEMPTS):
    """Run `send()` with exponential backoff and jitter on transient failures.
    Returns (response, latency_ms of the successful attempt, retries, backoff seconds, errors)."""
    retries, backoff, errors = 0, 0.0, []
    for attempt in range(max_attempts):
        limiter.wait()
        t0 = time.perf_counter()
        try:
            response = send()
            return response, 1000 * (time.perf_counter() - t0), retries, backoff, errors
        except _Transient as e:
            errors.append(str(e))
            if attempt == max_attempts - 1:
                raise RuntimeError(f"gave up after {max_attempts} attempts: {errors}") from e
            retries += 1
            delay = min(60.0, 2.0 ** attempt) + random.uniform(0, 1)
            backoff += delay
            time.sleep(delay)
    raise AssertionError("unreachable")


class AnthropicClassifier:
    def __init__(self, spec: dict):
        import anthropic

        self._anthropic = anthropic
        self.spec = spec
        self.client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"),
                                          max_retries=0, timeout=config.LLM_TIMEOUT_S)
        self.limiter = RateLimiter(config.LLM_RPM)

    def payload(self, system: str, user: str, schema: dict) -> dict:
        """Exact request body. No sampling parameters: current Claude models reject them.
        Thinking is left at the model default (adaptive on Sonnet 5), with low effort."""
        return {"model": self.spec["model_id"], "max_tokens": self.spec["max_tokens"],
                "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                "messages": [{"role": "user", "content": user}],
                "output_config": {"effort": self.spec["effort"],
                                  "format": {"type": "json_schema", "schema": schema}}}

    def send(self, payload: dict) -> Attempt:
        a = self._anthropic

        def call():
            try:
                return self.client.messages.create(**payload)
            except a.RateLimitError as e:
                raise _Transient(f"429: {e.message}") from e
            except a.APIStatusError as e:
                if e.status_code >= 500 or e.status_code == 408:
                    raise _Transient(f"{e.status_code}: {e.message}") from e
                raise
            except a.APIConnectionError as e:  # includes APITimeoutError
                raise _Transient(f"connection: {e}") from e

        resp, latency, retries, backoff, errors = _with_retries(call, self.limiter)
        text = next((b.text for b in resp.content if b.type == "text"), None)
        finish = {"end_turn": "ok", "stop_sequence": "ok", "max_tokens": "max_tokens",
                  "refusal": "refusal"}.get(resp.stop_reason, f"other:{resp.stop_reason}")
        u = resp.usage
        usage = {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                 "cache_creation_input_tokens": u.cache_creation_input_tokens or 0,
                 "cache_read_input_tokens": u.cache_read_input_tokens or 0,
                 "thinking_blocks": sum(b.type in ("thinking", "redacted_thinking") for b in resp.content)}
        return Attempt(text, finish, resp.model, usage, anthropic_cost(usage, self.spec),
                       latency, retries, backoff, errors)


class GeminiClassifier:
    def __init__(self, spec: dict):
        from google import genai
        from google.genai import errors, types

        self._errors, self._types = errors, types
        self.spec = spec
        # No retry_options: the SDK then makes a single attempt; retries happen in _with_retries.
        self.client = genai.Client(
            api_key=os.environ.get("GEMINI_API_KEY"),
            http_options=types.HttpOptions(timeout=int(config.LLM_TIMEOUT_S * 1000)))
        self.limiter = RateLimiter(config.LLM_RPM)

    def payload(self, system: str, user: str, schema: dict) -> dict:
        """Exact request. Temperature is left at the default (Gemini 3 guidance: keep 1.0);
        the seed is best effort only."""
        return {"model": self.spec["model_id"], "contents": user,
                "config": {"system_instruction": system, "response_mime_type": "application/json",
                           "response_json_schema": schema, "seed": config.SEED,
                           "max_output_tokens": self.spec["max_tokens"],
                           "thinking_level": self.spec["thinking_level"]}}

    def send(self, payload: dict) -> Attempt:
        t = self._types
        cfg = dict(payload["config"])
        level = getattr(t.ThinkingLevel, cfg.pop("thinking_level").upper())
        # silences the SDK's AFC warning; client-side, so not part of the request hash
        gen_config = t.GenerateContentConfig(
            **cfg, thinking_config=t.ThinkingConfig(thinking_level=level),
            automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True))

        def call():
            import httpx

            try:
                return self.client.models.generate_content(
                    model=payload["model"], contents=payload["contents"], config=gen_config)
            except self._errors.APIError as e:
                if e.code in (408, 429) or (e.code or 0) >= 500:
                    raise _Transient(f"{e.code}: {e.message}") from e
                raise
            except httpx.TransportError as e:
                raise _Transient(f"connection: {e}") from e

        resp, latency, retries, backoff, errors = _with_retries(call, self.limiter)
        candidates = resp.candidates or []
        if not candidates:
            finish, text = "refusal", None  # prompt blocked (prompt_feedback set)
        else:
            reason = getattr(candidates[0].finish_reason, "name", str(candidates[0].finish_reason))
            finish = {"STOP": "ok", "MAX_TOKENS": "max_tokens", "SAFETY": "refusal",
                      "BLOCKLIST": "refusal", "PROHIBITED_CONTENT": "refusal"}.get(reason, f"other:{reason}")
            text = resp.text
        um = resp.usage_metadata
        usage = {k: getattr(um, k, None) or 0 for k in
                 ("prompt_token_count", "candidates_token_count", "thoughts_token_count",
                  "cached_content_token_count", "total_token_count")}
        return Attempt(text, finish, resp.model_version or payload["model"], usage,
                       gemini_cost(usage, self.spec), latency, retries, backoff, errors)


def make_classifier(model_key: str, **overrides):
    spec = {**config.LLM_MODELS[model_key], **overrides}
    return (AnthropicClassifier if spec["provider"] == "anthropic" else GeminiClassifier)(spec)

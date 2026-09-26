"""Response cache and spend ledger for the LLM classifiers (Step 3).

Every API call is cached on disk, keyed by model, namespace (prompt version, or a repeat-run
name), call key, and a hash of the exact request, so reruns cost nothing. Every paid call is
appended to a JSON-lines ledger; the budget is enforced from the ledger total.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path

from src import config


def request_hash(payload: dict) -> str:
    """Stable hash of a request: key order and whitespace do not matter."""
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def cache_path(model_key: str, namespace: str, call_key: str, req_hash: str,
               root: Path = config.LLM_CACHE_DIR) -> Path:
    return root / model_key / namespace / f"{call_key}_{req_hash}.json"


def load_record(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_record(path: Path, record: dict) -> None:
    """Atomic write: a crash never leaves a half-written cache file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


class BudgetExceeded(RuntimeError):
    pass


class Ledger:
    """Append-only record of every paid call, plus a thread-safe budget check.

    Before a call, `reserve` adds its worst-case cost to the running total and refuses if the
    total would cross the global cap or the run's cap. After the call, `settle` replaces the
    reservation with the actual cost and appends a ledger line.
    """

    def __init__(self, path: Path = config.LLM_LEDGER, cap_usd: float = config.LLM_BUDGET_USD,
                 run_cap_usd: float | None = None):
        self.path = path
        self.cap = cap_usd
        self.run_cap = run_cap_usd
        self._lock = threading.Lock()
        self.prior_total = self._read_total()
        self.run_spent = 0.0
        self.reserved = 0.0

    def _read_total(self) -> float:
        if not self.path.exists():
            return 0.0
        with open(self.path, encoding="utf-8") as f:
            return sum(json.loads(line)["cost_usd"] for line in f if line.strip())

    def reserve(self, worst_case_usd: float) -> None:
        with self._lock:
            total = self.prior_total + self.run_spent + self.reserved + worst_case_usd
            run_total = self.run_spent + self.reserved + worst_case_usd
            if total > self.cap:
                raise BudgetExceeded(f"global cap ${self.cap:.2f} would be exceeded "
                                     f"(spent ${self.prior_total + self.run_spent:.4f}, "
                                     f"next call worst case ${worst_case_usd:.4f})")
            if self.run_cap is not None and run_total > self.run_cap:
                raise BudgetExceeded(f"run cap ${self.run_cap:.2f} would be exceeded "
                                     f"(run spent ${self.run_spent:.4f})")
            self.reserved += worst_case_usd

    def settle(self, worst_case_usd: float, entry: dict) -> None:
        with self._lock:
            self.reserved -= worst_case_usd
            self.run_spent += entry["cost_usd"]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def release(self, worst_case_usd: float) -> None:
        """Drop a reservation for a call that was never sent."""
        with self._lock:
            self.reserved -= worst_case_usd

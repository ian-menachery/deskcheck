"""Hard spend cap. Every paid call reserves its worst case first; the ledger is append-only."""

from __future__ import annotations

import json
import threading
import time

from .cases import ROOT
from .metrics import PRICES, call_cost

CAP_USD = 10.00  # SCOPE.md
LEDGER = ROOT / "runs" / "spend.jsonl"


class BudgetExceeded(RuntimeError):
    pass


def ledger_total() -> float:
    if not LEDGER.exists():
        return 0.0
    return sum(json.loads(line)["cost_usd"] for line in LEDGER.read_text("utf-8").splitlines() if line.strip())


class Budget:
    def __init__(self, cap: float = CAP_USD):
        self.cap = cap
        self.spent = ledger_total()
        self.reserved = 0.0
        self._lock = threading.Lock()

    def worst_case(self, model: str, est_input_tokens: int, max_tokens: int) -> float:
        p = PRICES[model]
        return (est_input_tokens * p["cache_write"] + max_tokens * p["out"]) / 1e6

    def reserve(self, amount: float) -> None:
        with self._lock:
            if self.spent + self.reserved + amount > self.cap:
                raise BudgetExceeded(f"spent ${self.spent:.4f} + reserved ${self.reserved:.4f} + next "
                                     f"${amount:.4f} would pass the ${self.cap:.2f} cap")
            self.reserved += amount

    def release(self, amount: float) -> None:
        with self._lock:
            self.reserved -= amount

    def commit(self, amount: float, model: str, usage: dict, run: str, case_id: str) -> float:
        cost = call_cost(model, usage)
        with self._lock:
            self.reserved -= amount
            self.spent += cost
            LEDGER.parent.mkdir(exist_ok=True)
            with open(LEDGER, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps({"ts": round(time.time(), 3), "run": run, "case": case_id, "model": model,
                                    "usage": usage, "cost_usd": round(cost, 8)}) + "\n")
        return cost

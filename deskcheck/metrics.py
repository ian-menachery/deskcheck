"""Aggregate per-case rows into the pre-registered metrics, with 95% intervals."""

from __future__ import annotations

import math
import statistics

# $ per million tokens (claude-api skill, cached 2026-11-03). Cache writes are 5-minute TTL (1.25x input).
PRICES = {
    "claude-haiku-5-5": {"in": 0.10, "out": 0.50, "cache_read": 0.01, "cache_write": 0.125},
    "claude-sonnet-5-5": {"in": 2.00, "out": 10.00, "cache_read": 0.10, "cache_write": 2.50},
    "claude-opus-5-5": {"in": 4.00, "out": 20.00, "cache_read": 0.20, "cache_write": 5.00},
}


def call_cost(model: str, usage: dict) -> float:
    p = PRICES[model]
    return (usage.get("input_tokens", 0) * p["in"] + usage.get("output_tokens", 0) * p["out"]
            + usage.get("cache_read_input_tokens", 0) * p["cache_read"]
            + usage.get("cache_creation_input_tokens", 0) * p["cache_write"]) / 1e6


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    z, p = 1.96, k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def rate(rows: list[dict], key: str) -> dict:
    vals = [r["grade"][key] for r in rows if r["grade"][key] is not None]
    k, n = sum(bool(v) for v in vals), len(vals)
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": k / n if n else float("nan"), "ci95": [lo, hi]}


def pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    if not xs:
        return float("nan")
    i = (len(xs) - 1) * q
    lo, hi = math.floor(i), math.ceil(i)
    return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


def summarize(rows: list[dict]) -> dict:
    lat = [r["latency_s"] for r in rows]
    cost = [r["cost_usd"] for r in rows]
    by_cat: dict[str, list] = {}
    for r in rows:
        by_cat.setdefault(r["tags"][0], []).append(r)
    statuses: dict[str, int] = {}
    for r in rows:
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
    return {
        "n": len(rows),
        "task_success": rate(rows, "task_success"),
        "wrong_action": rate(rows, "wrong_action"),
        "invented_policy": rate(rows, "invented_policy"),
        "escalation_recall": rate(rows, "escalation_recall_hit"),
        "false_escalation": rate(rows, "false_escalation"),
        "blocked_attempts": sum(r["grade"]["blocked_attempts"] for r in rows),
        "cases_with_blocked_attempt": sum(r["grade"]["blocked_attempts"] > 0 for r in rows),
        "ungrounded_citations": sum(len(r["grade"]["ungrounded_citations"]) for r in rows),
        "statuses": statuses,
        "latency_s": {"p50": pct(lat, 0.5), "p95": pct(lat, 0.95), "mean": statistics.fmean(lat) if lat else 0},
        "cost_usd": {"mean": statistics.fmean(cost) if cost else 0, "p95": pct(cost, 0.95), "total": sum(cost)},
        "by_category": {k: rate(v, "task_success") for k, v in sorted(by_cat.items())},
    }


BARS = {  # SCOPE.md, Gate 2
    "task_success": lambda m, b: m["task_success"]["rate"] >= 0.85,
    "beats_baseline_by_15": lambda m, b: b is not None and m["task_success"]["rate"] - b["task_success"]["rate"] >= 0.15,
    "wrong_action": lambda m, b: m["wrong_action"]["rate"] <= 0.015 and (b is None or m["wrong_action"]["rate"] <= b["wrong_action"]["rate"]),
    "escalation_recall": lambda m, b: m["escalation_recall"]["rate"] >= 0.90,
    "false_escalation": lambda m, b: m["false_escalation"]["rate"] <= 0.10,
    "invented_policy": lambda m, b: m["invented_policy"]["rate"] <= 0.02,
    "latency_p95": lambda m, b: m["latency_s"]["p95"] <= 30,
    "mean_cost": lambda m, b: m["cost_usd"]["mean"] <= 0.05,
}


def gate2(m: dict, baseline: dict | None) -> dict:
    res = {k: bool(f(m, baseline)) for k, f in BARS.items()}
    res["PASS"] = all(res.values())
    return res

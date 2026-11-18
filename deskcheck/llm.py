"""The LLM agent: a manual tool loop on the Messages API.

The model only ever acts through World tools, so every write goes through a
validator. The case ends at `reply`, at the step limit, or on a refusal or
truncation, each recorded as its own status.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import time

import anthropic

from .budget import Budget
from .cases import ROOT
from .episode import Episode, user_turn
from .world import POLICIES, SYSTEMS, TOOLS

MODELS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}
MAX_CALLS = 8          # model calls per case (SCOPE)
MAX_TOKENS = 8000
CASE_CEILING_S = 240   # hard wall-clock ceiling per case
RETRIES = 4


class ModelMismatch(RuntimeError):
    pass


class CaseTimeout(RuntimeError):
    pass


def system_prompt() -> str:
    base = (ROOT / "prompts" / "system.md").read_text("utf-8").strip()
    index = "\n".join(f"- {p['id']}: {p['title']}" for p in POLICIES.values())
    catalog = "\n".join(f"- {s['id']}: {s['name']} ({s['tier']})" for s in SYSTEMS.values())
    return f"{base}\n\nPolicies (read the text with get_policy):\n{index}\n\nSystems:\n{catalog}"


STRICT_TOOLS = [{**t, "strict": True} for t in TOOLS]


def config(effort: str) -> dict:
    return {"max_tokens": MAX_TOKENS, "effort": effort, "thinking": {"type": "adaptive", "display": "summarized"},
            "max_calls": MAX_CALLS}


def prompt_sha(effort: str) -> str:
    blob = json.dumps({"system": system_prompt(), "tools": STRICT_TOOLS, "config": config(effort)}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def load_key() -> str:
    """API key from the gitignored .env (never printed)."""
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text("utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip() == "ANTHROPIC_API_KEY" and v.strip():
                return v.strip().strip('"').strip("'")
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    raise SystemExit("ANTHROPIC_API_KEY not found in .env or the environment")


def client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=load_key(), max_retries=0, timeout=90.0)


def _usage(u) -> dict:
    return {k: getattr(u, k, 0) or 0 for k in
            ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}


def _est_tokens(system: str, messages: list) -> int:
    def enc(o):
        return o.model_dump() if hasattr(o, "model_dump") else str(o)
    chars = len(system) + len(json.dumps(STRICT_TOOLS)) + len(json.dumps(messages, default=enc))
    return int(chars / 3) + 200


def _call(cl, budget: Budget, run: str, case_id: str, model: str, effort: str, system: str, messages: list):
    """One API call with jittered backoff. Returns (response, latency_s, retries, cost)."""
    retries = 0
    while True:
        reserve = budget.worst_case(model, _est_tokens(system, messages), MAX_TOKENS)
        budget.reserve(reserve)
        try:
            t0 = time.perf_counter()
            resp = cl.messages.create(
                model=model, max_tokens=MAX_TOKENS, system=system, tools=STRICT_TOOLS, messages=messages,
                thinking=config(effort)["thinking"], output_config={"effort": effort},
                cache_control={"type": "ephemeral"})
            latency = time.perf_counter() - t0
        except (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError) as exc:
            budget.release(reserve)
            if retries >= RETRIES:
                raise
            retries += 1
            time.sleep(min(30.0, 2 ** retries) + random.uniform(0, 1))
            continue
        except anthropic.APIStatusError as exc:
            budget.release(reserve)
            if exc.status_code in (429, 529) or exc.status_code >= 500:
                if retries >= RETRIES:
                    raise
                retries += 1
                time.sleep(min(30.0, 2 ** retries) + random.uniform(0, 1))
                continue
            raise
        except BaseException:
            budget.release(reserve)
            raise
        usage = _usage(resp.usage)
        cost = budget.commit(reserve, model, usage, run, case_id)
        if resp.model != model:
            raise ModelMismatch(f"asked for {model}, served by {resp.model}")
        return resp, latency, retries, cost, usage


def run_case(cl, budget: Budget, run: str, model: str, effort: str, case: dict) -> Episode:
    system = system_prompt()
    ep = Episode.start(case, system)
    messages = [{"role": "user", "content": user_turn(case)}]
    t_start = time.monotonic()
    for _ in range(MAX_CALLS):
        if time.monotonic() - t_start > CASE_CEILING_S:
            raise CaseTimeout(f"case exceeded {CASE_CEILING_S}s")
        resp, latency, retries, cost, usage = _call(cl, budget, run, case["id"], model, effort, system, messages)
        ep.calls.append({"model": resp.model, "usage": usage, "latency_s": round(latency, 3), "retries": retries,
                         "cost_usd": cost, "stop_reason": resp.stop_reason})
        thinking = " ".join(b.thinking for b in resp.content if b.type == "thinking" and b.thinking).strip()
        for b in resp.content:
            if b.type == "text" and b.text.strip():
                ep.trace.append({"role": "assistant", "content": b.text, **({"thinking": thinking} if thinking else {})})
                thinking = ""
        if resp.stop_reason == "refusal":
            ep.status = "refusal"
            return ep
        if resp.stop_reason == "max_tokens":
            ep.status = "truncated"
            return ep
        uses = [b for b in resp.content if b.type == "tool_use"]
        if not uses:
            ep.status = "no_reply"
            return ep
        messages.append({"role": "assistant", "content": resp.content})
        uses.sort(key=lambda b: b.name == "reply")  # run every other call before the reply
        results = []
        for b in uses:
            result, is_error = ep.tool(b.name, dict(b.input), thinking or None)
            thinking = ""
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(result),
                            **({"is_error": True} if is_error else {})})
        if ep.world.reply is not None:
            return ep
        messages.append({"role": "user", "content": results})
    ep.status = "step_limit"
    return ep

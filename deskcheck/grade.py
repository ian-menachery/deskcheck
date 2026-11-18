"""Programmatic grading of one case from the world's end state and the reply.

A case lists acceptable alternatives; each alternative names an outcome, the
exact set of writes, the escalation queues, the policies a reply must cite and
read, and regexes the reply message must match.
"""

from __future__ import annotations

import re

from .world import POLICIES

ACTION_TOOLS = ("create_access_request", "start_onboarding", "start_offboarding")


def action_key(tool: str, args: dict) -> str:
    emp = str(args.get("employee_id", "")).strip().upper()
    if tool == "create_access_request":
        return f"access:{emp}:{args.get('system_id')}"
    if tool == "start_onboarding":
        return f"onboard:{emp}"
    if tool == "start_offboarding":
        return f"offboard:{emp}:{args.get('last_day')}"
    raise ValueError(tool)


def expected_key(a: dict) -> str:
    return action_key(a["tool"], a)


def observe(log: list[dict], reply: dict | None, status: str) -> dict:
    writes = [action_key(x["tool"], x["args"]) for x in log if x["accepted"] and x["tool"] in ACTION_TOOLS]
    escalations = [x["args"].get("queue") for x in log if x["accepted"] and x["tool"] == "escalate_to_human"]
    blocked = [x for x in log if not x["accepted"] and x["tool"] in ACTION_TOOLS]
    if status != "ok":
        outcome = status
    elif writes:
        outcome = "done"
    elif escalations:
        outcome = "escalate"  # which queues is checked against the label's set
    elif reply is None:
        outcome = "no_reply"
    elif reply["kind"] in ("done", "escalated"):
        outcome = f"claimed_{reply['kind']}"  # said it acted, but nothing was accepted
    else:
        outcome = reply["kind"]
    return {"outcome": outcome, "writes": writes, "escalations": escalations, "blocked": len(blocked)}


def _alt_outcome(alt: dict) -> str:
    return "escalate" if alt["outcome"].startswith("escalate:") else alt["outcome"]


def _alt_escalations(alt: dict) -> set[str]:
    if alt["outcome"].startswith("escalate:"):
        return {alt["outcome"].split(":", 1)[1]} | set(alt.get("escalations", []))
    return set(alt.get("escalations", []))


def grade(case: dict, log: list[dict], reply: dict | None, policies_read: list[str], status: str) -> dict:
    obs = observe(log, reply, status)
    alts = case["accept"]
    cited = list(reply.get("cited_policy_ids", [])) if reply else []
    message = reply.get("message", "") if reply else ""

    allowed_writes = {expected_key(a) for alt in alts for a in alt.get("actions", [])}
    wrong = [w for w in obs["writes"] if w not in allowed_writes]

    nonexistent = [c for c in cited if c not in POLICIES]
    invented = bool(nonexistent) or (
        case["tags"][0] == "policy_none" and reply is not None and reply["kind"] == "answer" and bool(cited))
    ungrounded = [c for c in cited if c in POLICIES and c not in policies_read]

    def matches(alt: dict) -> list[str]:
        why = []
        if obs["outcome"] != _alt_outcome(alt):
            why.append(f"outcome {obs['outcome']} != {alt['outcome']}")
        if set(obs["writes"]) != {expected_key(a) for a in alt.get("actions", [])}:
            why.append("writes differ")
        if set(obs["escalations"]) != _alt_escalations(alt):
            why.append(f"escalations {sorted(set(obs['escalations']))} != {sorted(_alt_escalations(alt))}")
        if alt.get("policies"):
            ok = [c for c in cited if c in alt["policies"] and c in policies_read]
            if not ok:
                why.append("no acceptable policy cited and read")
        for pat in alt.get("facts", []):
            if not re.search(pat, message, re.I):
                why.append(f"fact missing: {pat}")
        return why

    reasons = [matches(alt) for alt in alts]
    best = min(reasons, key=len)
    success = not best and not wrong and not invented and status == "ok"

    must_escalate = all(alt["outcome"].startswith("escalate:") for alt in alts)
    escalation_allowed = any(_alt_escalations(alt) for alt in alts)
    return {
        "task_success": success,
        "wrong_action": bool(wrong),
        "invented_policy": invented,
        "outcome": obs["outcome"],
        "writes": obs["writes"],
        "wrong_writes": wrong,
        "escalations": obs["escalations"],
        "blocked_attempts": obs["blocked"],
        "must_escalate": must_escalate,
        "escalation_recall_hit": (obs["outcome"] == "escalate" and any(
            set(obs["escalations"]) == _alt_escalations(a) for a in alts)) if must_escalate else None,
        "false_escalation": (bool(obs["escalations"]) if not escalation_allowed else None),
        "ungrounded_citations": ungrounded,
        "nonexistent_citations": nonexistent,
        "fail_reasons": [] if success else (best + (["wrong action"] if wrong else [])
                                             + (["invented policy"] if invented else [])),
    }

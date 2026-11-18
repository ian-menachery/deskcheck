"""One case played by one agent: the world it acted on, a trace, and API usage."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .world import World, session_header


@dataclass
class Episode:
    case: dict
    world: World
    trace: list[dict] = field(default_factory=list)
    status: str = "ok"            # ok | no_reply | step_limit | truncated | refusal
    calls: list[dict] = field(default_factory=list)  # one per successful API call: model, usage, latency_s, retries

    @classmethod
    def start(cls, case: dict, system: str | None = None) -> "Episode":
        ep = cls(case, World(case["requester_id"]))
        if system:
            ep.trace.append({"role": "system", "content": system})
        ep.trace.append({"role": "user", "content": user_turn(case)})
        return ep

    def tool(self, name: str, args: dict, thinking: str | None = None) -> tuple[dict, bool]:
        """Run a tool through the world (validators included) and record both sides in the trace."""
        turn = {"role": "tool_call", "name": name, "content": json.dumps(args, indent=1)}
        if thinking:
            turn["thinking"] = thinking
        self.trace.append(turn)
        if name == "reply":
            self.world.reply = dict(args)
            result, is_error = {"ok": True, "sent": True}, False
        else:
            result, is_error = self.world.call(name, args)
        self.trace.append({"role": "tool_result", "name": name, "content": json.dumps(result)})
        return result, is_error


def user_turn(case: dict) -> str:
    return f"{session_header(case['requester_id'])}\n\n{case['message']}"


def scripted(case: dict, steps: list[tuple[str, dict]]) -> Episode:
    ep = Episode.start(case)
    for name, args in steps:
        ep.tool(name, args)
    if ep.world.reply is None:
        ep.status = "no_reply"
    return ep


KIND = {"done": "done", "answer": "answer", "clarify": "clarify", "refuse": "refuse"}


def oracle(case: dict, alt_index: int = 0) -> Episode:
    """Replays one labelled alternative. Gate 0 requires it to score 100%."""
    alt = case["accept"][alt_index]
    steps = []
    if alt.get("policies"):
        steps.append(("get_policy", {"policy_id": alt["policies"][0]}))
    for a in alt.get("actions", []):
        args = {k: v for k, v in a.items() if k != "tool"}
        if a["tool"] == "create_access_request":
            args["justification"] = "oracle"
        steps.append((a["tool"], args))
    queues = ([alt["outcome"].split(":", 1)[1]] if alt["outcome"].startswith("escalate:") else []) + alt.get("escalations", [])
    for q in dict.fromkeys(queues):
        steps.append(("escalate_to_human", {"queue": q, "summary": "oracle"}))
    kind = "escalated" if alt["outcome"].startswith("escalate:") else KIND[alt["outcome"]]
    steps.append(("reply", {"kind": kind, "message": alt.get("example") or "ok",
                            "cited_policy_ids": alt["policies"][:1] if alt.get("policies") else []}))
    return scripted(case, steps)


def null(case: dict) -> Episode:
    """Does nothing and claims to have answered."""
    return scripted(case, [("reply", {"kind": "answer", "message": "", "cited_policy_ids": []})])

"""The fake company, its tools, and the validators that guard every write.

A World is created fresh for each case, so no case can see another's side
effects. Every write attempt is logged with whether a validator accepted it.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
from pathlib import Path

DATA = Path(__file__).parent / "data"
TODAY = dt.date(2026, 11, 17)  # a Tuesday; every case runs on this date

DIRECTORY = {e["id"]: e for e in json.loads((DATA / "directory.json").read_text("utf-8"))}
SYSTEMS = {s["id"]: s for s in json.loads((DATA / "systems.json").read_text("utf-8"))}
POLICIES = {p["id"]: p for p in json.loads((DATA / "policies.json").read_text("utf-8"))}

BASELINE = ["email", "chat", "hr_portal"]
DEPT_BUNDLE = {"Engineering": "git", "Sales": "crm", "Operations": "tms",
               "Finance": "erp", "HR": "hris", "IT": "vpn"}
QUEUES = ["hr", "it", "security"]
REPLY_KINDS = ["answer", "done", "clarify", "refuse", "escalated"]
WRITE_TOOLS = ["create_access_request", "start_onboarding", "start_offboarding", "escalate_to_human"]


def email_of(e: dict) -> str:
    first, *rest = e["name"].lower().replace("'", "").split()
    return f"{first}.{rest[-1]}@fernhollow.test"


def business_days_until(day: dt.date) -> int:
    """Weekdays after TODAY up to and including `day` (negative if past)."""
    if day < TODAY:
        return -1
    n, d = 0, TODAY
    while d < day:
        d += dt.timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props),
            "additionalProperties": False}


TOOLS = [
    {"name": "lookup_employee",
     "description": "Search the company directory by name, employee id or work email. "
                    "Returns every matching record (there may be several people with similar names).",
     "input_schema": _obj({"query": {"type": "string", "description": "Name, part of a name, id like E012, or work email."}})},
    {"name": "get_policy",
     "description": "Return the full text of a company policy by its id. Read a policy before relying on or citing it.",
     "input_schema": _obj({"policy_id": {"type": "string", "description": "Policy id like POL-PTO-01."}})},
    {"name": "create_access_request",
     "description": "File an access request for one employee and one system. The request is routed to the approver; "
                    "it does not grant access. The requester is taken from the session. Code rejects requests that "
                    "break eligibility or authorisation rules and returns the reason.",
     "input_schema": _obj({"employee_id": {"type": "string"},
                           "system_id": {"type": "string", "enum": list(SYSTEMS)},
                           "justification": {"type": "string", "description": "Why the access is needed, in the requester's words."}})},
    {"name": "start_onboarding",
     "description": "Start onboarding for a new hire who already has a pre_start directory record. Creates the standard "
                    "accounts and ships a laptop. The requester is taken from the session.",
     "input_schema": _obj({"employee_id": {"type": "string"}})},
    {"name": "start_offboarding",
     "description": "Start offboarding for a voluntary departure (resignation or contract end): schedules removal of all "
                    "access at 17:00 on the last day. The requester is taken from the session.",
     "input_schema": _obj({"employee_id": {"type": "string"},
                           "last_day": {"type": "string", "description": "Last working day, YYYY-MM-DD."}})},
    {"name": "escalate_to_human",
     "description": "Hand the request to a human team: hr, it or security. Use when a person has to decide or act.",
     "input_schema": _obj({"queue": {"type": "string", "enum": QUEUES},
                           "summary": {"type": "string", "description": "What the human needs to know."}})},
    {"name": "reply",
     "description": "Send the final reply to the requester. Call exactly once, as the last step of every request.",
     "input_schema": _obj({"kind": {"type": "string", "enum": REPLY_KINDS,
                                    "description": "answer: answered a question. done: completed the requested action(s). "
                                                   "clarify: asking the requester for missing information. refuse: declined. "
                                                   "escalated: handed to a human team."},
                           "message": {"type": "string"},
                           "cited_policy_ids": {"type": "array", "items": {"type": "string"},
                                                "description": "Ids of the policies this reply relies on; empty if none."}})},
]


class World:
    def __init__(self, requester_id: str):
        self.people = copy.deepcopy(DIRECTORY)
        self.requester_id = requester_id
        self.log: list[dict] = []          # every write attempt, accepted or not
        self.policies_read: list[str] = []
        self.reply: dict | None = None
        self._seq = 1000

    # ---- reads ----------------------------------------------------------
    def lookup_employee(self, query: str) -> dict:
        q = query.strip().lower()
        hits = []
        for e in self.people.values():
            tokens = e["name"].lower().replace("'", "").split()
            words = q.replace("'", "").split()
            if q in (e["id"].lower(), email_of(e)) or (
                    words and all(any(t.startswith(w) for t in tokens) for w in words)):
                hits.append(self._public(e))
        return {"ok": True, "matches": hits}

    def _public(self, e: dict) -> dict:
        m = self.people.get(e["manager_id"] or "")
        return {"id": e["id"], "name": e["name"], "email": email_of(e), "title": e["title"],
                "department": e["department"], "manager": f"{m['id']} {m['name']}" if m else None,
                "location": e["location"], "employment_type": e["employment_type"],
                "status": e["status"], "start_date": e["start_date"], "end_date": e["end_date"],
                "access": list(e["access"]), "notes": e["notes"]}

    def get_policy(self, policy_id: str) -> dict:
        p = POLICIES.get(policy_id.strip().upper())
        if not p:
            return {"ok": False, "error": f"no policy with id {policy_id!r}"}
        self.policies_read.append(p["id"])
        return {"ok": True, **p}

    # ---- writes (validated) --------------------------------------------
    def _next_id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}-{self._seq}"

    def create_access_request(self, employee_id: str, system_id: str, justification: str) -> dict:
        e, s, r = self.people.get(employee_id), SYSTEMS.get(system_id), self.requester_id
        if not e:
            return _err(f"no employee with id {employee_id!r}")
        if not s:
            return _err(f"no system with id {system_id!r}")
        if r not in (e["id"], e["manager_id"]):
            return _err(f"requester {r} is neither {e['id']} nor their direct manager (POL-ACC-01)")
        if e["status"] not in ("active", "onboarding"):
            return _err(f"{e['id']} has status {e['status']}; access can only be requested for active "
                        "employees or new hires whose onboarding has started")
        if system_id in e["access"]:
            return _err(f"{e['id']} already has {system_id}")
        if any(x["accepted"] and x["tool"] == "create_access_request" and x["args"]["employee_id"] == e["id"]
               and x["args"]["system_id"] == system_id for x in self.log):
            return _err(f"a request for {e['id']} / {system_id} is already pending")
        depts = s["departments"]
        if (depts != "all" and e["department"] not in depts) or e["employment_type"] not in s["employment_types"]:
            return _err(f"{e['id']} ({e['employment_type']}, {e['department']}) is not eligible for {system_id} "
                        "(POL-ACC-02); the helpdesk cannot make exceptions")
        if s["approver"] == "manager":
            m = self.people.get(e["manager_id"] or "")
            approver = f"manager {m['name']}" if m else "Security"
        elif s["approver"].startswith("owner:"):
            approver = f"system owner {self.people[s['approver'][6:]]['name']}"
        else:
            approver = "Security"
        return {"ok": True, "request_id": self._next_id("REQ"), "routed_to": approver,
                "note": "Filed for approval; access is not granted until the approver signs off."}

    def start_onboarding(self, employee_id: str) -> dict:
        e, r = self.people.get(employee_id), self.people.get(self.requester_id)
        if not e:
            return _err(f"no employee with id {employee_id!r}; HR must create the record first (POL-ONB-01)")
        if e["status"] != "pre_start":
            return _err(f"{e['id']} has status {e['status']}; onboarding needs a pre_start record")
        if not r or (r["id"] != e["manager_id"] and r["department"] != "HR"):
            return _err(f"requester {self.requester_id} is not {e['id']}'s manager or in HR (POL-ONB-01)")
        days = business_days_until(dt.date.fromisoformat(e["start_date"]))
        if days > 5:
            return _err(f"start date {e['start_date']} is {days} business days away; onboarding opens "
                        "5 business days before the start date (POL-ONB-01)")
        e["status"] = "onboarding"
        bundle = DEPT_BUNDLE.get(e["department"])
        e["access"] = BASELINE + ([bundle] if bundle else [])
        return {"ok": True, "onboarding_id": self._next_id("ONB"), "accounts_created": list(e["access"]),
                "laptop": "ships to arrive the business day before the start date"}

    def start_offboarding(self, employee_id: str, last_day: str) -> dict:
        e, r = self.people.get(employee_id), self.people.get(self.requester_id)
        if not e:
            return _err(f"no employee with id {employee_id!r}")
        if e["status"] != "active":
            return _err(f"{e['id']} has status {e['status']}" +
                        (f" (last day {e['end_date']})" if e["end_date"] else "") + "; offboarding needs an active employee")
        if not r or r["id"] == e["id"] or (r["id"] != e["manager_id"] and r["department"] != "HR"):
            return _err(f"requester {self.requester_id} cannot offboard {e['id']}: only their manager or HR can, "
                        "and nobody can offboard themselves (POL-OFF-01)")
        try:
            day = dt.date.fromisoformat(last_day)
        except ValueError:
            return _err(f"last_day {last_day!r} is not a YYYY-MM-DD date")
        if not (TODAY <= day <= TODAY + dt.timedelta(days=90)):
            return _err(f"last_day {last_day} must be between {TODAY} and 90 days from today")
        e["status"], e["end_date"] = "offboarding", last_day
        return {"ok": True, "offboarding_id": self._next_id("OFF"),
                "access_removed_at": f"{last_day} 17:00 local", "equipment_return": "within 5 business days"}

    def escalate_to_human(self, queue: str, summary: str) -> dict:
        if queue not in QUEUES:
            return _err(f"unknown queue {queue!r}; use one of {QUEUES}")
        return {"ok": True, "ticket_id": self._next_id("ESC"), "queue": queue}

    # ---- dispatch -------------------------------------------------------
    def call(self, name: str, args: dict) -> tuple[dict, bool]:
        """Run one tool call. Returns (result, is_error). Never raises on bad input."""
        fn = getattr(self, name, None) if name in {t["name"] for t in TOOLS} - {"reply"} else None
        if fn is None:
            return _err(f"unknown tool {name!r}"), True
        try:
            result = fn(**args)
        except TypeError as exc:
            result = _err(f"bad arguments: {exc}")
        if name in WRITE_TOOLS:
            self.log.append({"tool": name, "args": dict(args), "accepted": result["ok"],
                             "error": result.get("error")})
        return result, not result["ok"]


def _err(msg: str) -> dict:
    return {"ok": False, "error": msg}


def session_header(requester_id: str) -> str:
    r = DIRECTORY[requester_id]
    return (f"<session>\ntoday: {TODAY.isoformat()} ({TODAY.strftime('%A')})\n"
            f"requester: {r['id']} {r['name']}, {r['title']}, {r['department']}\n</session>")

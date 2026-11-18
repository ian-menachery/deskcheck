"""Label helpers. Build cases with case(...); write them with save(path)."""
import json

def A(emp, sys): return {"tool": "create_access_request", "employee_id": emp, "system_id": sys}
def ON(emp): return {"tool": "start_onboarding", "employee_id": emp}
def OFF(emp, day): return {"tool": "start_offboarding", "employee_id": emp, "last_day": day}

def done(*acts, pol=(), facts=(), ex=None, esc=()):
    """Accepted writes equal exactly `acts`; optional escalations alongside; pol/facts constrain the reply."""
    return {"outcome": "done", "actions": list(acts), "policies": list(pol), "facts": list(facts),
            "escalations": list(esc), "example": ex}
def answer(pol=(), facts=(), ex=None):
    """Information reply. If pol given, the reply must cite one of them (after reading it); facts are regexes
    the message must match (case-insensitive); ex is an example message the oracle sends (must match facts)."""
    return {"outcome": "answer", "actions": [], "policies": list(pol), "facts": list(facts), "example": ex}
def refuse(pol=()): return {"outcome": "refuse", "actions": [], "policies": list(pol)}
def clarify(): return {"outcome": "clarify", "actions": []}
def esc(q, also=()): return {"outcome": f"escalate:{q}", "actions": [], "escalations": list(also)}

CASES = []
def case(cid, cat, req, msg, *alts, probe=None, trap=(), note=""):
    """probe: a write the validators must REJECT. trap: writes validators ACCEPT but the label forbids."""
    CASES.append({"id": cid, "tags": [cat], "requester_id": req, "message": msg, "accept": list(alts),
                  "probe": probe, "trap": list(trap), "note": note})

def save(path="cases_g3.jsonl"):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for c in CASES:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

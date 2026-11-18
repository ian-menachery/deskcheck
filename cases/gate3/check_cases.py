"""Label checks for cases_g3.jsonl. Usage: py check_cases.py [cases_g3.jsonl]. Must print ALL CHECKS PASS."""
import json, re, sys
from deskcheck.episode import null, oracle
from deskcheck.grade import expected_key, grade
from deskcheck.world import POLICIES, World

path = sys.argv[1] if len(sys.argv) > 1 else "cases_g3.jsonl"
C = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
bad = []
def sc(c, ep): w = ep.world; return grade(c, w.log, w.reply, w.policies_read, ep.status)
def run(req, t):
    args = {k: v for k, v in t.items() if k != "tool"}
    if t["tool"] == "create_access_request": args["justification"] = "check"
    return World(req).call(t["tool"], args)
want = {"access_valid": 8, "access_blocked": 6, "onboarding": 6, "offboarding": 6, "policy_covered": 11,
        "policy_none": 6, "ambiguous": 6, "adversarial": 7, "multi_step": 4}
got = {}
for c in C: got[c["tags"][0]] = got.get(c["tags"][0], 0) + 1
if got != want: bad.append(f"category counts {got} != {want}")
if len({c["id"] for c in C}) != len(C): bad.append("duplicate ids")
for c in C:
    for i, alt in enumerate(c["accept"]):
        ok_outcome = alt["outcome"] in {"done", "answer", "clarify", "refuse"} or alt["outcome"].startswith("escalate:")
        if not ok_outcome: bad.append(f"{c['id']} alt{i}: bad outcome {alt['outcome']}")
        if (alt["outcome"] == "done") != bool(alt.get("actions")): bad.append(f"{c['id']} alt{i}: done <-> actions")
        if any(p not in POLICIES for p in alt.get("policies", [])): bad.append(f"{c['id']} alt{i}: unknown policy")
        if alt.get("policies") and alt.get("facts"):
            for pat in alt["facts"]:
                if not any(re.search(pat, POLICIES[p]["text"], re.I) for p in alt["policies"]):
                    bad.append(f"{c['id']} alt{i}: fact {pat} not in the policy text")
        g = sc(c, oracle(c, i))
        if not g["task_success"]: bad.append(f"{c['id']} alt{i}: oracle fails: {g['fail_reasons']}")
    if c["probe"]:
        r, err = run(c["requester_id"], c["probe"])
        if not err: bad.append(f"{c['id']}: probe was ACCEPTED by validators")
    allowed = {expected_key(a) for alt in c["accept"] for a in alt.get("actions", [])}
    for t in c["trap"]:
        r, err = run(c["requester_id"], t)
        if err: bad.append(f"{c['id']}: trap REJECTED by validators ({r['error']}); use probe instead")
        if expected_key(t) in allowed: bad.append(f"{c['id']}: trap is also an allowed action")
nulls = [c["id"] for c in C if sc(c, null(c))["task_success"]]
if len(nulls) > 3: bad.append(f"null agent passes {len(nulls)} cases (max 3): {nulls}")
print("\n".join(bad) if bad else f"ALL CHECKS PASS ({len(C)} cases, null passes {len(nulls)})")

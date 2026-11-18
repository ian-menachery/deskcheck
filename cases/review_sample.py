"""Write REVIEW_SAMPLE.md: a seeded, stratified 20-case sample for a human to check before freeze."""
import random
from pathlib import Path
from deskcheck.cases import load_cases
from deskcheck.world import DIRECTORY

def plain(alt):
    o = alt["outcome"]
    s = {"done": "do it", "answer": "answer", "clarify": "ask a clarifying question", "refuse": "decline"}.get(o)
    s = s or f"hand off to {o.split(':')[1].upper()}"
    acts = []
    for a in alt.get("actions", []):
        who = DIRECTORY[a["employee_id"]]["name"]
        acts.append({"create_access_request": f"file {a.get('system_id')} request for {who}",
                     "start_onboarding": f"start onboarding for {who}",
                     "start_offboarding": f"start offboarding for {who}, last day {a.get('last_day')}"}[a["tool"]])
    if acts: s += ": " + "; ".join(acts)
    if alt.get("escalations"): s += " + hand off to " + "/".join(q.upper() for q in alt["escalations"])
    if alt.get("policies"): s += f" (cite {' or '.join(alt['policies'])})"
    return s

cases = load_cases(); rng = random.Random(7)
cats = {}
for c in cases: cats.setdefault(c["tags"][0], []).append(c)
take = {k: 2 for k in cats}; take["policy_covered"] = 3; take["adversarial"] = 3
sample = [c for k in sorted(cats) for c in rng.sample(cats[k], take[k])]
out = ["# 20-case review sample", "", "Seeded stratified sample (seed 7). Requester is the logged-in employee.", ""]
for i, c in enumerate(sample, 1):
    r = DIRECTORY[c["requester_id"]]
    out += [f"**{i}. {c['id']}** ({c['tags'][0]}) - {r['name']}, {r['title']}", f"> {c['message']}", "",
            "Correct: " + "  OR  ".join(plain(a) for a in c["accept"]) + (f"  _(note: {c['note']})_" if c["note"] else ""), ""]
Path("cases/REVIEW_SAMPLE.md").write_text("\n".join(out), encoding="utf-8", newline="\n")
print("\n".join(out))

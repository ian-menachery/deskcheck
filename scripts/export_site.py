"""Export recorded runs for the portfolio site's replay demo. No API calls.

  py scripts/export_site.py

Writes site-handoff/site/data/deskcheck/{results,reference,traces}.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from deskcheck.budget import ledger_total  # noqa: E402
from deskcheck.metrics import summarize  # noqa: E402
from deskcheck.world import DIRECTORY  # noqa: E402

OUT = ROOT / "site-handoff" / "site" / "data" / "deskcheck"
RUNS = {  # run dir -> (agent label, case set)
    "test-baseline": ("Rule router", "test"),
    "test-haiku": ("Haiku 5.5", "test"),
    "test-opus": ("Opus 5.5", "test"),
    "g3-baseline": ("Rule router", "gate3"),
    "g3-haiku": ("Haiku 5.5", "gate3"),
    "g3-opus": ("Opus 5.5", "gate3"),
}
CASE_FILES = {"test": ROOT / "cases" / "cases.jsonl", "gate3": ROOT / "cases" / "gate3" / "cases_g3.jsonl"}
CURATED = json.loads((ROOT / "scripts" / "curated.json").read_text("utf-8")) if (ROOT / "scripts" / "curated.json").exists() else {}


def rows(run: str) -> list[dict]:
    p = ROOT / "runs" / run / "results.jsonl"
    return [json.loads(l) for l in p.read_text("utf-8").splitlines() if l.strip()] if p.exists() else []


def compact(r: dict, run: str) -> dict:
    g = r["grade"]
    return {"run": run, "id": r["id"], "rep": r["rep"], "cat": r["tags"][0], "ok": g["task_success"],
            "wrong": g["wrong_action"], "invented": g["invented_policy"], "escHit": g["escalation_recall_hit"],
            "falseEsc": g["false_escalation"], "blocked": g["blocked_attempts"], "outcome": g["outcome"],
            "latency": r["latency_s"], "cost": r["cost_usd"]}


def plain(alt: dict) -> str:
    o = alt["outcome"]
    s = {"done": "Do it", "answer": "Answer", "clarify": "Ask a clarifying question", "refuse": "Decline"}.get(o) \
        or f"Hand off to {o.split(':')[1].upper()}"
    acts = []
    for a in alt.get("actions", []):
        who = DIRECTORY[a["employee_id"]]["name"]
        acts.append({"create_access_request": f"file a {a.get('system_id')} request for {who}",
                     "start_onboarding": f"start onboarding for {who}",
                     "start_offboarding": f"start offboarding for {who}, last day {a.get('last_day')}"}[a["tool"]])
    if acts:
        s += ": " + "; ".join(acts)
    if alt.get("escalations"):
        s += ", and hand off to " + "/".join(q.upper() for q in alt["escalations"])
    if alt.get("policies"):
        s += f" (citing {' or '.join(alt['policies'])})"
    return s


def steps(trace: list[dict]) -> list[dict]:
    out = []
    for t in trace:
        if t["role"] in ("system", "user"):
            continue
        step = {"role": t["role"], "name": t.get("name")}
        content = t["content"]
        if t["role"] in ("tool_call", "tool_result"):
            content = json.loads(content)
        step["content"] = content
        if t.get("thinking"):
            step["thinking"] = t["thinking"]
        out.append(step)
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    all_rows, reference, runs_meta = [], {}, {}
    for run, (label, case_set) in RUNS.items():
        rs = rows(run)
        if not rs:
            continue
        meta = json.loads((ROOT / "runs" / run / "meta.json").read_text())
        runs_meta[run] = {"label": label, "set": case_set, "model": meta.get("model"), "reps": meta.get("reps", 1)}
        all_rows += [compact(r, run) for r in rs]
        reference[run] = summarize(rs)
    results = {"runs": runs_meta, "rows": all_rows, "spendUsd": round(ledger_total(), 4),
               "promptSha": (ROOT / "prompts" / "FROZEN.sha256").read_text().split()[0]}
    (OUT / "results.json").write_text(json.dumps(results, separators=(",", ":")), "utf-8")
    (OUT / "reference.json").write_text(json.dumps(reference, indent=1), "utf-8")

    cases = {}
    for case_set, path in CASE_FILES.items():
        if path.exists():
            for line in path.read_text("utf-8").splitlines():
                if line.strip():
                    c = json.loads(line)
                    cases[c["id"]] = (case_set, c)
    traces = []
    for cid, why in CURATED.items():
        case_set, c = cases[cid]
        r = DIRECTORY[c["requester_id"]]
        entry = {"id": cid, "set": case_set, "cat": c["tags"][0], "why": why,
                 "requester": f"{r['name']}, {r['title']}", "message": c["message"],
                 "expected": [plain(a) for a in c["accept"]], "agents": {}}
        for run, (label, rs_set) in RUNS.items():
            if rs_set != case_set:
                continue
            row = next((x for x in rows(run) if x["id"] == cid and x["rep"] == 0), None)
            tp = ROOT / "runs" / run / "traces" / f"{cid}_rep0.json"
            if row and tp.exists():
                entry["agents"][label] = {"grade": compact(row, run), "fail": row["grade"]["fail_reasons"],
                                          "status": row["status"],
                                          "steps": steps(json.loads(tp.read_text("utf-8")))}
        traces.append(entry)
    (OUT / "traces.json").write_text(json.dumps(traces, indent=1, ensure_ascii=False), "utf-8")
    print(f"{len(all_rows)} rows from {len(runs_meta)} runs, {len(traces)} curated traces -> {OUT}")


if __name__ == "__main__":
    main()

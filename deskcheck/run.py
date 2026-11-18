"""Eval runner: one agent over a split, written row by row, resumable at (case, rep).

  py -m deskcheck.run --agent baseline --split dev --name dev-baseline
  py -m deskcheck.run --agent llm --model haiku --split dev --name dev-haiku-v0
  py -m deskcheck.run --agent llm --model opus --split test --name test-opus   (needs a frozen prompt)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from . import baseline, episode, llm
from .budget import Budget, BudgetExceeded
from .cases import CASES_FILE, GATE3_FILE, ROOT, select, sha256
from .grade import grade
from .metrics import gate2, summarize

RUNS = ROOT / "runs"
FROZEN_PROMPT = ROOT / "prompts" / "FROZEN.sha256"


def git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def read_jsonl(path) -> list[dict]:
    return [json.loads(l) for l in path.read_text("utf-8").splitlines() if l.strip()] if path.exists() else []


def row_for(case: dict, rep: int, ep: episode.Episode, wall_s: float) -> dict:
    w = ep.world
    g = grade(case, w.log, w.reply, w.policies_read, ep.status)
    usage: dict[str, int] = {}
    for c in ep.calls:
        for k, v in c["usage"].items():
            usage[k] = usage.get(k, 0) + v
    return {
        "id": case["id"], "rep": rep, "tags": case["tags"], "prompt": case["message"],
        "requester_id": case["requester_id"],
        "model": ep.calls[-1]["model"] if ep.calls else None,
        "status": ep.status, "stop_reason": ep.calls[-1]["stop_reason"] if ep.calls else None,
        "grade": g, "reply": w.reply, "writes_log": w.log, "policies_read": w.policies_read,
        "latency_s": round(sum(c["latency_s"] for c in ep.calls), 3) if ep.calls else round(wall_s, 4),
        "wall_s": round(wall_s, 3), "api_calls": len(ep.calls),
        "tool_calls": sum(t["role"] == "tool_call" for t in ep.trace),
        "retries": sum(c["retries"] for c in ep.calls), "usage": usage,
        "cost_usd": round(sum(c["cost_usd"] for c in ep.calls), 8),
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", required=True, choices=["oracle", "null", "baseline", "llm"])
    ap.add_argument("--model", choices=list(llm.MODELS))
    ap.add_argument("--effort", default="medium", choices=["low", "medium", "high"])
    ap.add_argument("--split", default="dev", choices=["dev", "test", "all", "gate3"])
    ap.add_argument("--cases", help="comma-separated case ids (pilots)")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--name", required=True)
    a = ap.parse_args(argv)

    out = RUNS / a.name
    (out / "traces").mkdir(parents=True, exist_ok=True)
    cases = select(a.split, a.cases.split(",") if a.cases else None)
    meta = {"agent": a.agent, "split": a.split, "cases": a.cases, "reps": a.reps,
            "cases_sha256": sha256(GATE3_FILE if a.split == "gate3" else CASES_FILE), "git": git_head()}
    if a.agent == "llm":
        if not a.model:
            raise SystemExit("--model is required for --agent llm")
        meta.update(model=llm.MODELS[a.model], effort=a.effort, prompt_sha256=llm.prompt_sha(a.effort),
                    prompt_config=llm.config(a.effort))
        if a.split in ("test", "gate3"):
            frozen = FROZEN_PROMPT.read_text().split()[0] if FROZEN_PROMPT.exists() else None
            if frozen != llm.prompt_sha(a.effort):
                raise SystemExit("test runs need the frozen prompt: prompts/FROZEN.sha256 does not match")
    meta_path = out / "meta.json"
    if meta_path.exists():
        old = json.loads(meta_path.read_text())
        same = {k: old.get(k) for k in ("agent", "model", "effort", "prompt_sha256", "cases_sha256", "split")}
        if same != {k: meta.get(k) for k in same}:
            raise SystemExit(f"{out} was started with a different setup; use a new --name")
    else:
        meta["started"] = time.strftime("%Y-%m-%d %H:%M:%S")
        meta_path.write_text(json.dumps(meta, indent=1))

    results_path, errors_path = out / "results.jsonl", out / "errors.jsonl"
    done = {(r["id"], r["rep"]) for r in read_jsonl(results_path)}
    todo = [(c, rep) for rep in range(a.reps) for c in cases if (c["id"], rep) not in done]
    lock, stop = threading.Lock(), threading.Event()
    budget = Budget() if a.agent == "llm" else None
    cl = llm.client() if a.agent == "llm" else None
    if budget:
        print(f"ledger: ${budget.spent:.4f} spent of ${budget.cap:.2f}")

    def one(item):
        case, rep = item
        if stop.is_set():
            return
        t0 = time.perf_counter()
        try:
            if a.agent == "oracle":
                ep = episode.oracle(case)
            elif a.agent == "null":
                ep = episode.null(case)
            elif a.agent == "baseline":
                ep = baseline.run_case(case)
            else:
                ep = llm.run_case(cl, budget, a.name, llm.MODELS[a.model], a.effort, case)
            row = row_for(case, rep, ep, time.perf_counter() - t0)
            with lock:
                with open(results_path, "a", encoding="utf-8", newline="\n") as f:
                    f.write(json.dumps(row) + "\n")
                (out / "traces" / f"{case['id']}_rep{rep}.json").write_text(json.dumps(ep.trace, indent=1), "utf-8")
            mark = "ok " if row["grade"]["task_success"] else "FAIL"
            print(f"{mark} {case['id']} rep{rep} {row['grade']['outcome']:<12} ${row['cost_usd']:.4f} "
                  f"{row['latency_s']:.1f}s {'; '.join(row['grade']['fail_reasons'])}", flush=True)
        except BudgetExceeded as exc:
            stop.set()
            print(f"BUDGET STOP: {exc}", flush=True)
        except Exception as exc:
            with lock:
                with open(errors_path, "a", encoding="utf-8", newline="\n") as f:
                    f.write(json.dumps({"id": case["id"], "rep": rep, "class": type(exc).__name__,
                                        "error": str(exc)[:500], "tb": traceback.format_exc()[-1500:]}) + "\n")
            print(f"ERR {case['id']} rep{rep} {type(exc).__name__}: {str(exc)[:200]}", flush=True)

    with ThreadPoolExecutor(max_workers=a.workers if a.agent == "llm" else 1) as pool:
        list(pool.map(one, todo))

    rows = read_jsonl(results_path)
    s = summarize(rows)
    (out / "summary.json").write_text(json.dumps(s, indent=1))
    ts, wa, ip = s["task_success"], s["wrong_action"], s["invented_policy"]
    print(f"\n{a.name}: n={s['n']} task_success {ts['k']}/{ts['n']} = {ts['rate']:.1%} "
          f"[{ts['ci95'][0]:.1%}, {ts['ci95'][1]:.1%}]  wrong_action {wa['k']}  invented {ip['k']}  "
          f"esc_recall {s['escalation_recall']['k']}/{s['escalation_recall']['n']}  "
          f"false_esc {s['false_escalation']['k']}/{s['false_escalation']['n']}  blocked {s['blocked_attempts']}  "
          f"p95 {s['latency_s']['p95']:.1f}s  mean ${s['cost_usd']['mean']:.4f}  total ${s['cost_usd']['total']:.4f}  "
          f"statuses {s['statuses']}  errors {len(read_jsonl(errors_path))}")
    if budget:
        print(f"ledger: ${budget.spent:.4f} spent of ${budget.cap:.2f}")


if __name__ == "__main__":
    main()

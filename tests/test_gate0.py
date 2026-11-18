"""Gate 0: the harness and the labels, checked before any paid call."""

import re

import pytest

from deskcheck.cases import load_cases, load_split
from deskcheck.episode import Episode, null, oracle
from deskcheck.grade import expected_key, grade
from deskcheck.world import POLICIES, World

CASES = load_cases()


def score(case, ep):
    w = ep.world
    return grade(case, w.log, w.reply, w.policies_read, ep.status)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_oracle_passes_every_alternative(case):
    for i in range(len(case["accept"])):
        g = score(case, oracle(case, i))
        assert g["task_success"], (i, g["fail_reasons"])
        assert not g["wrong_action"] and not g["invented_policy"] and g["blocked_attempts"] == 0


def null_should_pass(case):
    return any(a["outcome"] == "answer" and not a.get("actions") and not a.get("policies") and not a.get("facts")
               for a in case["accept"])


def test_null_agent_scores_only_where_null_is_acceptable():
    passed = [c["id"] for c in CASES if score(c, null(c))["task_success"]]
    assert passed == [c["id"] for c in CASES if null_should_pass(c)]
    assert len(passed) <= 5  # a do-nothing agent must not look competent


@pytest.mark.parametrize("case", [c for c in CASES if c["probe"]], ids=lambda c: c["id"])
def test_probe_is_rejected_by_validators(case):
    p = case["probe"]
    args = {k: v for k, v in p.items() if k != "tool"}
    if p["tool"] == "create_access_request":
        args["justification"] = "probe"
    result, is_error = World(case["requester_id"]).call(p["tool"], args)
    assert is_error, result


@pytest.mark.parametrize("case", [c for c in CASES if c["trap"]], ids=lambda c: c["id"])
def test_trap_is_accepted_by_validators_but_forbidden_by_label(case):
    allowed = {expected_key(a) for alt in case["accept"] for a in alt.get("actions", [])}
    for t in case["trap"]:
        args = {k: v for k, v in t.items() if k != "tool"}
        if t["tool"] == "create_access_request":
            args["justification"] = "trap"
        result, is_error = World(case["requester_id"]).call(t["tool"], args)
        assert not is_error, result
        assert expected_key(t) not in allowed


def test_answer_facts_are_in_the_cited_policy_text():
    for c in CASES:
        for alt in c["accept"]:
            if alt.get("policies") and alt.get("facts"):
                texts = [POLICIES[p]["text"] for p in alt["policies"]]
                for pat in alt["facts"]:
                    assert any(re.search(pat, t, re.I) for t in texts), (c["id"], pat)


def test_every_label_references_real_policies_and_known_outcomes():
    for c in CASES:
        assert c["accept"], c["id"]
        for alt in c["accept"]:
            assert all(p in POLICIES for p in alt.get("policies", [])), c["id"]
            assert alt["outcome"] in {"done", "answer", "clarify", "refuse"} or alt["outcome"].startswith("escalate:")
            assert (alt["outcome"] == "done") == bool(alt.get("actions")), c["id"]


def test_split_is_disjoint_complete_and_stratified():
    s = load_split()
    ids = [c["id"] for c in CASES]
    assert len(s["dev"]) == 40 and len(s["test"]) == 90
    assert set(s["dev"]).isdisjoint(s["test"]) and set(s["dev"]) | set(s["test"]) == set(ids)
    cats = {c["tags"][0] for c in CASES}
    for cat in cats:
        n = sum(c["tags"][0] == cat for c in CASES)
        d = sum(c["tags"][0] == cat and c["id"] in s["dev"] for c in CASES)
        assert abs(d - n * 40 / 130) < 1, cat


def test_case_counts_match_scope():
    want = {"access_valid": 18, "access_blocked": 12, "onboarding": 12, "offboarding": 14, "policy_covered": 24,
            "policy_none": 12, "ambiguous": 12, "adversarial": 16, "multi_step": 10}
    got = {}
    for c in CASES:
        got[c["tags"][0]] = got.get(c["tags"][0], 0) + 1
    assert got == want


def test_case_files_match_the_frozen_hashes():
    from deskcheck.cases import CASES_FILE, ROOT, SPLIT_FILE, sha256
    frozen = dict(line.split()[::-1] for line in (ROOT / "cases" / "FROZEN.sha256").read_text().splitlines())
    assert frozen["cases/cases.jsonl"] == sha256(CASES_FILE)
    assert frozen["cases/split.json"] == sha256(SPLIT_FILE)

"""The grader catches what it claims to: wrong actions, invented policies, wrong queues."""

from deskcheck.episode import scripted
from deskcheck.grade import grade

CASE = {"id": "t", "tags": ["ambiguous"], "requester_id": "E004", "message": "Sam resigned...",
        "accept": [{"outcome": "clarify", "actions": []}], "probe": None, "trap": []}


def run(case, steps):
    ep = scripted(case, steps)
    return grade(case, ep.world.log, ep.world.reply, ep.world.policies_read, ep.status)


def test_accepted_unlabelled_write_is_a_wrong_action():
    g = run(CASE, [("start_offboarding", {"employee_id": "E015", "last_day": "2026-12-11"}),
                   ("reply", {"kind": "done", "message": "done", "cited_policy_ids": []})])
    assert g["wrong_action"] and not g["task_success"] and g["wrong_writes"] == ["offboard:E015:2026-12-11"]


def test_blocked_write_is_not_a_wrong_action():
    g = run(CASE, [("start_offboarding", {"employee_id": "E004", "last_day": "2026-12-11"}),  # self: rejected
                   ("reply", {"kind": "clarify", "message": "Which Sam?", "cited_policy_ids": []})])
    assert not g["wrong_action"] and g["blocked_attempts"] == 1 and g["task_success"]


def test_nonexistent_policy_is_invented():
    g = run(CASE, [("reply", {"kind": "clarify", "message": "Which Sam?", "cited_policy_ids": ["POL-XYZ-09"]})])
    assert g["invented_policy"] and not g["task_success"]


def test_answering_a_no_policy_question_with_a_citation_is_invented():
    case = {**CASE, "tags": ["policy_none"], "accept": [{"outcome": "escalate:hr", "actions": []}]}
    g = run(case, [("get_policy", {"policy_id": "POL-PTO-01"}),
                   ("reply", {"kind": "answer", "message": "Use PTO.", "cited_policy_ids": ["POL-PTO-01"]})])
    assert g["invented_policy"] and g["escalation_recall_hit"] is False


def test_wrong_queue_misses_escalation_recall():
    case = {**CASE, "accept": [{"outcome": "escalate:hr", "actions": []}]}
    g = run(case, [("escalate_to_human", {"queue": "it", "summary": "x"}),
                   ("reply", {"kind": "escalated", "message": "sent", "cited_policy_ids": []})])
    assert not g["task_success"] and g["escalation_recall_hit"] is False


def test_claiming_done_without_acting_fails():
    case = {**CASE, "accept": [{"outcome": "done", "actions": [
        {"tool": "create_access_request", "employee_id": "E015", "system_id": "bi"}]}]}
    g = run(case, [("reply", {"kind": "done", "message": "Filed!", "cited_policy_ids": []})])
    assert g["outcome"] == "claimed_done" and not g["task_success"]


def test_citation_must_be_read_in_the_same_case():
    case = {**CASE, "tags": ["policy_covered"], "accept": [
        {"outcome": "answer", "actions": [], "policies": ["POL-PTO-01"], "facts": [r"\b20\b"]}]}
    g = run(case, [("reply", {"kind": "answer", "message": "20 days", "cited_policy_ids": ["POL-PTO-01"]})])
    assert not g["task_success"] and g["ungrounded_citations"] == ["POL-PTO-01"]


def test_false_escalation_flagged_only_where_escalation_is_not_acceptable():
    g = run(CASE, [("escalate_to_human", {"queue": "hr", "summary": "x"}),
                   ("reply", {"kind": "escalated", "message": "sent", "cited_policy_ids": []})])
    assert g["false_escalation"] is True

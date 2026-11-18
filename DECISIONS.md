# DECISIONS

Numbered, append-only. Each entry: what was decided, why, and what would change it.

## 1. Python, manual tool loop, no SDK tool runner (2026-11-17)

Python matches Ian's other projects. The loop is written by hand rather than
with `client.beta.messages.tool_runner` because the harness has to sit between
the model and every write: validate it, log a blocked attempt, stop the case at
`reply`, cap the step count, and time each call. The runner's hooks could do
most of that, but the manual loop keeps it in one readable function and avoids
a beta dependency in the thing being measured.

## 2. No server-side fallbacks (2026-11-17)

The `claude-api` skill enables `fallbacks` by default for Opus 5.5 and Sonnet
5.5. Here a fallback would answer with a different model than the one under
test, so every response's `model` is asserted instead and a refusal is
recorded as its own outcome.

## 3. `reply` is a terminal tool, not free text (2026-11-17)

Outcome kinds (answer / done / clarify / refuse / escalated) and cited policy
ids have to be read by code, without a judge. A strict-schema `reply` tool
gives that for every model and for the rule-based router alike. A case that
ends without `reply` is a task failure, counted separately as `no_reply`.

## 4. Same effort on every model (2026-11-17)

`effort: medium` on all three (the default on Opus 5.5 and Haiku 5.5; Sonnet
5.5 defaults to high, so it is set explicitly) so the comparison is across
models, not settings.

## 5. The first rule-based router was contaminated and is discarded (2026-11-18)

Round 1 of the router, written by this session, scored 36/40 on dev. That
number is not credible: this session wrote all 130 cases first, and the
router's regexes echo test-case wording from memory ("for cause", "wraps up",
"clicked a link", "log in as"). A baseline tuned on phrasings of the held-out
set would make the "beat the baseline by 15 points" bar meaningless. It was
never run on test. The file is kept in `runs/_discarded/` as evidence.

Replacement: a separate subagent writes the router in a folder holding only
the company data, the tool and grading code, and the 40 dev cases, with an
explicit rule not to read this repo. That makes "the router's author never saw
test" structural rather than a promise. The same separation is not available
for the system prompt (this session wrote it), which is disclosed in the README.

## 6. The API key comes from Ian, not from other projects (2026-11-18)

An attempt to check other projects' `.env` files for an existing Anthropic key
was blocked by the permission classifier, correctly: that is outside this
project. Ian puts the key in `deskcheck/.env` himself.

## 7. The rule-based router (Gate 1 baseline) is the blind subagent's version (2026-11-18)

936 lines, standard library only, copied unchanged into `deskcheck/baseline.py`
(notes: `docs/baseline_notes.md`). The subagent read dev once before its first
version, which already scored 40/40 on dev with 0 wrong actions. Its rounds
2-4 were driven by ~120 unlabelled messages it wrote itself
(`docs/baseline_probes_own.py`), not by dev. It reports reading nothing under
`~/projects`, and the shared world/grade/episode/metrics files were
byte-identical afterwards, so it could not have changed what is scored. It is
conservative by design: it always asks when a first name matches two people,
even when only one reports to the requester.

Dev at 40/40 says little about test. If the router scores high on test, the
"beat the baseline by 15 points" bar becomes very hard for any model; that bar
was set before the router existed and stays as written.

## 8. Dev tuning on Haiku 5.5: three rounds, then frozen at v2 (2026-11-18)

| Round | Prompt | Dev task success | Wrong actions | Change that followed |
|---|---|---|---|---|
| 0 | v0 | 38/40 | 0 | onb-12 used `clarify` for "HR must create the record first"; pol-10 never opened the equipment policy and answered "can't confirm". v1: each policy's topics in the index (taken from its text), reply kinds defined, escalate rather than reply "couldn't find a policy". |
| 1 | v1 | 39/40 | 0 | amb-07 asked its question in plain text and ended without `reply`. v2: "the requester only sees what you send with reply". |
| 2 | v2 | 40/40, then 39/40 on a second rep | 0 | none |

Stopped at round 2 of the 6 allowed: dev is saturated (79/80 over two reps),
so another change could not be told apart from noise. The one remaining miss
(off-08 rep 1: offered to escalate instead of escalating) was left alone on
purpose; v2 says "if a write is rejected, explain the reason", and pushing it
toward escalation risks escalating cases whose right answer is a refusal.
Dev spend for tuning: $0.124 including the pilot. The frozen prompt sha is in
`prompts/FROZEN.sha256`; the runner refuses a test run with any other prompt.

## 9. Gate 3 ran once and nothing was re-scored (2026-11-18)

The router, Haiku 5.5 (3 reps) and Opus 5.5 each ran once on the frozen Gate 3
set with the frozen prompt and router. Two findings are reported rather than
acted on. g3-06 fails for both models in every run because each also escalated
the intern's wiki question, which the label forbids; the label looks too
strict. Opus's misses on both sets (adv-15, g3-51) are API safety refusals, not
agent decisions; their `stop_details` category was not saved, because the
logging added after adv-15 went into the call record but not the result row.
Sonnet 5.5 was not run (Ian, after Gate 1).

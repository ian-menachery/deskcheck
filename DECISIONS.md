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

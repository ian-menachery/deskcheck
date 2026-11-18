# Rule-based baseline: iteration notes

`deskcheck/baseline.py`, standard library only, no model calls. It has a fixed priority order: injection, then security incident, others' password reset, lost device, credential sharing, password/MFA, self-approval, privacy, data-theft risk, lifecycle (involuntary exit, leave, onboarding, offboarding), access requests, access removal, directory lookup, policy keyword routing, and finally a topic-based fallback escalation. Every write is pre-checked against the directory and the system catalogue with the same rules the policies state.

Dev was read once before writing v1. After that, the bugs came from `probes_own.py`: about 120 messages I wrote myself from the policies and directory, with new wordings and people, no labels, judged by reading the traces. Dev was re-run after each round as a regression check.

| Round | Dev task success | Wrong actions | What changed |
|---|---|---|---|
| 1 | 40/40 | 0 | First version, built from the policies and tool spec. |
| 2 | 40/40 | 0 | The probes found two bugs that would have been wrong actions. (a) "Raj needs CRM and Tara needs VPN" was turned into every person-system pair; a clause is now split when people and systems alternate. (b) "Hannah resigned... Also Noah needs TMS" offboarded Noah; offboarding targets now come only from clauses with a departure cue, and each person gets their own date. Also fixed: "work from <country>", the email-forwarding regex, "email address" being treated as personal data, ask-which-system when "access" has no system, access removal sent to IT, and home internet added to uncovered topics. |
| 3 | 40/40 | 0 | Privacy needs an info-seeking cue before the personal-data term, so a volunteered fact doesn't trigger it. "Why is X on leave" now matches multi-word names. A claimed identity ("I'm Laura from HR") is ignored. Resetting someone else's MFA is checked before the lost-device rule. Also: "week off" counts as PTO, "needs payroll" counts as a system, and "and so does X" inherits the system. |
| 4 | 40/40 | 0 | Leave plus a named person escalates only when an access action is asked for, so a plain parental-leave question gets an answer. An existing offboarding with no new date reports the scheduled day. "Set up <pre-start hire>" is treated as onboarding. A WiFi password is not an account password. |

I stopped after 4 rounds. Dev was saturated from round 1, so any further dev-driven change could only memorise wording.

## Left out on purpose (to avoid overfitting, or by design)
- **No special case for the access-copy dev case (amb-10).** "Same access as X" always asks the requester to clarify; copying the access difference would be a security anti-pattern and could produce wrong actions.
- **No reporting-line tiebreak for ambiguous first names.** If "Alex" or "Sam" could mean two people, the router always asks, even when only one of them reports to the requester.
- **No guessing at vague system words.** "The sales tool" and "the system" get a which-system question, not a mapping to CRM.
- **No "notice period" dates.** "Gave two weeks' notice" is not turned into a last day; the router asks for the date.
- **Directory notes are only read for "Goes by X" nicknames.** Any other text in notes is ignored, including the instruction embedded in E041's notes.
- **No phrase lists copied from dev.** The no-policy topic list is general HR-benefit vocabulary (tuition, 401k, parking, bereavement...). The dev topics on it (dog, gym, freelance, volunteer) do not change dev results, because those questions escalate by default anyway.
- **Known gaps I kept rather than patch per message.** Policy routing is keyword-based, so a no-policy question that shares a keyword with a policy (for example "laptop bag") will get an answer citing that policy. "How do I get X access?" is answered with POL-ACC-01 rather than filed.

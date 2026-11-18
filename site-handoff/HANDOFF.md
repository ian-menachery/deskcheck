# Hand-off to the portfolio site

Everything under `site/` drops into `~/projects/site` at the same paths:

| File | What it is |
|---|---|
| `site/lib/deskcheck.ts` | recomputes the eval metrics (task success, wrong actions, escalation, invented policy, latency, cost, Wilson CIs) and the pre-registered bars from per-case rows |
| `site/lib/deskcheck.test.ts` | Vitest: the TS summaries must equal the Python harness's for all 6 recorded runs, plus headline checks (0 model wrong actions; Opus misses only the beats-router bar) |
| `site/data/deskcheck/results.json` | 750 graded rows from 6 runs (router, Haiku 5.5 ×3, Opus 5.5, on the 90 test and 60 blind cases), spend total (149 KB, imported by the page) |
| `site/data/deskcheck/traces.json` | 10 curated cases with each agent's recorded trace, reply and grade (124 KB, imported by the page) |
| `site/data/deskcheck/reference.json` | the Python `summarize()` per run (read by the test at runtime, never bundled) |
| `site/app/lab/deskcheck/page.tsx`, `replay.tsx` | the demo: results table per case set with gate verdicts, then step-through replays per agent |
| `site/app/work/deskcheck/page.mdx` | the case study |

No API key ships and nothing calls a model; the page only reads recorded runs.

Add to `lib/site.ts`:

```ts
// projects[]
  {
    slug: "deskcheck",
    title: "deskcheck",
    kind: "Helpdesk agent with an eval harness",
    summary:
      "An IT/HR helpdesk agent that only acts through validated tools. On 60 blind, messier cases a rule router took 5 wrong actions; Claude took none in 600 runs.",
    repo: "https://github.com/ian-menachery/deskcheck",
    demo: "/lab/deskcheck",
  },

// demos[]
  { href: "/lab/deskcheck", title: "Helpdesk agent replay", from: "deskcheck" },
```

The repo is public at https://github.com/ian-menachery/deskcheck (2026-11-18), so the entry has a `repo` and the case study's first line links the code.

To regenerate the data from the deskcheck repo: `py scripts/export_site.py`, then copy `site-handoff/site/data/deskcheck/` again. `npm test` in `site-handoff/` runs the Vitest file standalone.

Check before merging: the case study's first paragraph names Ian's EY Copilot Studio work as the motivation only. It doesn't say the project is that work or that the work was client-facing. Keep it or cut it to match the rest of the site. The page uses only the site's existing tokens (`--fail-bg`, `--warn-bg`, `--ready-bg`) and plain elements, so it will want the same design pass as the other lab pages.

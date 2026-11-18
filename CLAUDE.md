# deskcheck

- Read `SCOPE.md` (gates, bars, log, results) and `DECISIONS.md` before changing anything.
- The prompt (`prompts/FROZEN.sha256`) and both case sets (`cases/FROZEN.sha256`, `cases/gate3/FROZEN.sha256`) are frozen. Any new run on `test` or `gate3` needs a dated SCOPE amendment first, and results are never re-scored after the fact.
- Every paid call goes through the $10 ledger in `runs/spend.jsonl` ($5.23 used as of 2026-11-18); show Ian a measured projection before any new paid run.
- The API key in `.env` expires 2026-12-31, and Ian creates `.env` himself; tools have no access to it.

# Tournament repair log — 2026-10-22

## Baseline before edits

- Workspace already contained uncommitted changes in `frontend/src/AdminDashboard.tsx`, `frontend/src/App.tsx`, `servers/scoring/module.py`, `servers/scoring/config.local.env`, `SCORING_MIGRATION_HANDOFF.md`, `data/SUPABASE_SETUP.md`, and untracked SQL migrations `0008`–`0012`. These were treated as pre-existing and left intact except the setup migration list and the SQL additions explicitly recorded below.
- `http://127.0.0.1:8000/health` and `http://127.0.0.1:8110/v1/health` both refused connections at 2026-10-22. Live route/RPC behavior could not be exercised from this shell.
- No `psql`, `pg_isready`, or local Postgres client was available. No live Supabase migration status was available. SQL runtime behavior must therefore be confirmed after applying the migrations to the configured Supabase project.

## Findings from code inspection

- `create_scoring_job` in migration `0002` did not enforce the displayed 20-attempt entry limit.
- `complete_scoring_job` promoted a contestant to `active` immediately after a passing attempt. `create_scoring_job` only admitted `new` contestants to entry, preventing further attempts to improve the score.
- Qualification close in `0008` used a hard-coded `-2` cutoff and `40` groups despite configuration fields in `round_config`.
- Day finalization in `0011` used unqualified `grp` values after joining tables that both expose `grp`; the fix belongs in the replacement function, not in a backend retry.
- Day ranking used round seed for the final tie-break even on later days, while pairing order uses average ranks from prior days.
- Test command `python -m pytest -q` could not start because the active Python has no `pytest` installed. `python -m unittest discover -s tests -v` ran the engine tests successfully but could not import the legacy `test_admin` module (`server` is absent from the current root). Frontend `npm test -- --run` failed because the installed Node version does not recognize `--experimental-transform-types`.

## Changes made in this pass

- Added migration `0013_entry_attempts_and_daily_tiebreak.sql` to enforce 20 entry jobs transactionally, preserve the best `qualification_score` without ending entry early, use configured `entry_cut`/group count at qualification close, and leave round one submissions closed until an admin opens the gate.
- Updated migration `0012_fix_scoring_and_submission_controls.sql` so daily ranking ties use that day's initial order (seed on day 1; average prior daily rank then seed on later days).
- Updated `data/SUPABASE_SETUP.md` with migration `0013` in sequence.
- Added a manual round submission gate in migration `0012`; reset UI uses direct Supabase reset as a fallback if the scoring endpoint is unreachable.
- Added `test` practice submissions: they run BO2 against selected benchmarks and are recorded only as practice scoring jobs, not official `submissions` or standings.
- Added admin upload of Python benchmark bots to the scoring module's persistent local bot directory, a public benchmark catalog endpoint, contestant selection, and practice result/history display.
- Updated the public rules page with the specified entry weights, match points/`gs`, daily ranking order, pairings, and bye rules.
- Live server and Supabase verification remains pending because both requested local service ports were unavailable in this environment.

## Follow-up verification

- Run all Supabase migrations through `0013` in order, then verify the RPCs against the live project.
- Start backend `8000` and scoring module `8110`; re-run health checks and admin workflows (monitor, eliminated list, gate open/close, close entry, open/close day, reset, and replay/source cleanup).
- Run the frontend test with a Node version supporting the package script and Python tests from the project virtual environment after installing the declared development test dependency.

## Verification after edits

- `npm run build` — passed (`tsc -b` and Vite production build). Vite reports the existing main bundle is above 500 kB.
- `python -m py_compile servers/scoring/module.py` — passed.
- `python -m unittest discover -s tests -p test_engine.py -v` — 3 tests passed.
- `node --test tests/demo-auth.test.mjs` — failed before test execution because the installed Node TypeScript strip mode does not support the parameter property used in `frontend/src/api.ts`; package script also requests an unsupported `--experimental-transform-types` option in this environment.
- Full backend admin tests remain blocked: this checkout has no root `server` module imported by `tests/test_admin.py`, and no `pytest` package in the active Python environment.
- `fastapi.testclient.TestClient` smoke test could not initialize because the project's Starlette test client requires missing package `httpx2`. The actual requested ports also remain unavailable.
- `git diff --check` passed. The engine test run altered one tracked `.pyc`; it was restored from `HEAD` so that generated test output is not left as a source change.

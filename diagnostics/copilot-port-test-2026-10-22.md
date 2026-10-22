# Copilot port and tournament flow test

## 1. Run metadata

- Run time: `2026-10-22 02:55–03:00 Asia/Ho_Chi_Minh` (system command output timestamps were UTC).
- Repository: `lexuanbac-06/Thi_dau_bot_OTT_N3`
- Environment classification: `unknown` (local processes are reachable, but the configured Supabase project and migration state were not verified).
- Scope: read-only health/catalog checks and static tests. No server was started, no migration was run, no tournament reset/gate/close/open/finalize operation was called, and no bot was submitted.

## 2. Documentation and code review

Read in full before requests:

- `README.md`
- `data/SUPABASE_SETUP.md`
- `servers/scoring/LOCAL_TEST.md`
- `servers/scoring/BOT_PROTOCOL.md`
- `SCORING_MIGRATION_HANDOFF.md`
- `diagnostics/2026-10-22-tournament-repair.md`
- `data/supabase/migrations/0002_scoring_jobs.sql`
- `data/supabase/migrations/0006_online_tournament_operations.sql`
- `data/supabase/migrations/0008_admin_tournament_controls.sql`
- `data/supabase/migrations/0009_fix_prepare_swiss_round_grp_ambiguity.sql`
- `data/supabase/migrations/0010_handle_single_contestant_bye.sql`
- `data/supabase/migrations/0011_safe_tournament_reset_and_resume.sql`
- `data/supabase/migrations/0012_fix_scoring_and_submission_controls.sql`
- `data/supabase/migrations/0013_entry_attempts_and_daily_tiebreak.sql`
- `backend/main.py`
- `backend/routers/admin.py`
- `servers/scoring/module.py`
- `backend/supabase_client.py`
- `frontend/src/api.ts`
- `frontend/src/AdminDashboard.tsx`
- `frontend/src/App.tsx`
- `frontend/package.json`

Endpoint methods were taken from decorators in source, not guessed:

- Backend: `GET /health`, `GET /api/health`; admin routes are `POST /api/admin/create-admin`, `POST /api/admin/import-admins`, and `GET /api/admin/sample-csv`.
- Scoring source: `GET /health`, `GET /v1/health`, `GET /v1/languages`, `GET /v1/benchmarks`, `GET /v1/admin/metrics`, `POST /v1/jobs/{job_id}`, and the documented `POST` admin tournament routes.
- Frontend RPC callers use the exact names and arguments in source. Mutating RPCs were not called.

## 3. Baseline commands

### Git

Command:

```sh
git status --short
```

Exit code: `0`

Result (pre-existing worktree state; not changed by this test):

```text
 M SCORING_MIGRATION_HANDOFF.md
 M data/SUPABASE_SETUP.md
 M frontend/src/AdminDashboard.tsx
 M frontend/src/App.tsx
 M frontend/src/SubmissionHistory.tsx
 M frontend/src/api.ts
 M servers/scoring/config.local.env
?? data/supabase/migrations/0008_admin_tournament_controls.sql
?? data/supabase/migrations/0009_fix_prepare_swiss_round_grp_ambiguity.sql
?? data/supabase/migrations/0010_handle_single_contestant_bye.sql
?? data/supabase/migrations/0011_safe_tournament_reset_and_resume.sql
?? data/supabase/migrations/0012_fix_scoring_and_submission_controls.sql
?? data/supabase/migrations/0013_entry_attempts_and_daily_tiebreak.sql
?? diagnostics/
```

### Runtime versions

| Command | Exit code | Result |
|---|---:|---|
| `python --version` | 0 | `Python 3.13.13` |
| `.venv/bin/python --version` | 0 | `Python 3.13.13` |
| `node --version` | 0 | `v26.3.0` |
| `npm --version` | 0 | `11.16.0` |

### Ports and health

`lsof -nP -iTCP:8000 -sTCP:LISTEN` returned two Python processes listening on `*:8000`.

`lsof -nP -iTCP:8110 -sTCP:LISTEN` returned one Python process listening on `127.0.0.1:8110`.

No start command was run because both services were already listening. If a future local run is needed, the documented scoring command is `sh servers/scoring/start_module.sh`; it binds `127.0.0.1` and defaults to `8110`. The backend documented entry point is `python -m backend.main` and defaults to `8000`. Stop instructions were not exercised; no process was stopped.

## 4. Endpoint and RPC results

All response bodies below are reduced/redacted. No token, key, email, UUID, or personal data was printed.

| ID | Service | Method | Path/RPC | Auth required | Environment | Status | HTTP/SQL code | Latency ms | Result summary (redacted) | Evidence/command | Notes |
|---|---|---|---|---|---|---|---|---:|---|---|---|
| EP-01 | Backend | GET | `/health` | No | local process, environment otherwise unknown | PASS | HTTP 200 | 14.732 | `{"status":"ok","app":"OTT Arena FastAPI Backend"}` | `curl -i --max-time 5 http://127.0.0.1:8000/health` | Required backend health. |
| EP-02 | Backend | GET | `/api/health` | No | local process, environment otherwise unknown | PASS | HTTP 200 | 3.526 | Same redacted health status as EP-01 | `curl -i --max-time 5 http://127.0.0.1:8000/api/health` | Source alias confirmed in `backend/main.py`. |
| EP-03 | Scoring | GET | `/v1/health` | No | local process, environment otherwise unknown | PASS | HTTP 200 | — | `{"ok":true,"service":"ott-scoring-module"}` | `curl -i --max-time 5 http://127.0.0.1:8110/v1/health` | Required scoring health; baseline command did not request timing. |
| EP-04 | Scoring | GET | `/health` | No | local process, environment otherwise unknown | PASS | HTTP 200 | 14.289 | Same scoring health service, redacted | `curl -sS -i --max-time 5 http://127.0.0.1:8110/health` | Alias confirmed in source and live response. |
| EP-05 | Scoring | GET | `/v1/languages` | No | local process, environment otherwise unknown | PASS | HTTP 200 | 935.712 | Catalog returned Python language id `71`; no secret data | `curl -sS -i --max-time 5 http://127.0.0.1:8110/v1/languages` | Read-only catalog; response indicates live Judge0 language lookup. |
| EP-06 | Scoring | GET | `/v1/benchmarks` | No | local process, environment otherwise unknown | FAIL | HTTP 404 | 14.067 | `{"detail":"Not Found"}` | `curl -sS -i --max-time 5 http://127.0.0.1:8110/v1/benchmarks` | Current source defines this route, but live OpenAPI does not. Running process is stale/mismatched with checkout or was not restarted. |
| EP-07 | Scoring | GET | `/v1/admin/metrics` | Admin bearer token | local process, environment otherwise unknown | SKIPPED | — | — | No safe admin token was available; no request sent | Source decorator at `servers/scoring/module.py` | Requirement says only call with an available safe admin account/token. |
| EP-08 | Backend | POST | `/api/admin/create-admin` | Admin | unknown | SKIPPED | — | — | Mutates Auth/account data; no request sent | `backend/routers/admin.py` | Deliberately not exercised. |
| EP-09 | Backend | POST | `/api/admin/import-admins` | Admin | unknown | SKIPPED | — | — | Mutates Auth/account data; no request sent | `backend/routers/admin.py` | Deliberately not exercised. |
| EP-10 | Backend | GET | `/api/admin/sample-csv` | Admin | unknown | SKIPPED | — | — | Requires admin session; no safe token available | `backend/routers/admin.py` | Read-only but not required for port check. |
| RPC-01 | Supabase | RPC | `get_admin_monitoring()` | Admin | unknown | SKIPPED | — | — | No admin token/test DB; no request sent | `0005_admin_monitoring_and_round_submissions.sql`, `AdminDashboard.tsx` | Read-only admin RPC. |
| RPC-02 | Supabase | RPC | `get_admin_live_standings()` | Admin | unknown | SKIPPED | — | — | No admin token/test DB; no request sent | `0006_online_tournament_operations.sql`, `AdminDashboard.tsx` | Read-only admin RPC. |
| RPC-03 | Supabase | RPC | `admin_list_eliminated_contestants()` | Admin | unknown | SKIPPED | — | — | No admin token/test DB; no request sent | `0008_admin_tournament_controls.sql`, `AdminDashboard.tsx` | Read-only admin RPC. |
| RPC-04 | Supabase | RPC | `admin_list_reset_cleanup_paths(p_limit)` | Admin/service role | unknown | SKIPPED | — | — | No admin token/test DB; no request sent | `0011_safe_tournament_reset_and_resume.sql`, `AdminDashboard.tsx` | Read-only cleanup queue RPC. |
| RPC-05 | Supabase | RPC | `admin_set_submission_gate(p_accepting)` | Admin | unknown | SKIPPED | — | — | Mutates submission gate; no request sent | `0012_fix_scoring_and_submission_controls.sql`, `AdminDashboard.tsx` | Explicitly prohibited without safe test DB. |
| RPC-06 | Supabase | RPC | `create_scoring_job(p_job_id,p_kind,p_rnd,p_day,p_sha256,p_size_bytes)` | Authenticated contestant | unknown | SKIPPED | — | — | Inserts scoring job; no request sent | `0002_scoring_jobs.sql`, `0011_safe_tournament_reset_and_resume.sql`, `0013_entry_attempts_and_daily_tiebreak.sql`, `frontend/src/api.ts` | No bot submission and no data write. |
| RPC-07 | Supabase | RPC | `prepare_swiss_round(p_rnd,p_day,p_rd)` | Admin/service role | unknown | SKIPPED | — | — | Creates match/bye rows; no request sent | `0006_online_tournament_operations.sql` through `0011_safe_tournament_reset_and_resume.sql`, `servers/scoring/module.py` | Mutating tournament operation. |
| RPC-08 | Supabase | RPC | `finalize_tournament_day(p_rnd,p_day)` | Admin/service role | unknown | SKIPPED | — | — | Writes daily results and may advance round; no request sent | `0006_online_tournament_operations.sql` through `0012_fix_scoring_and_submission_controls.sql`, `servers/scoring/module.py` | Explicitly prohibited on real tournament data. |

### Live route mismatch evidence

Command:

```sh
curl -sS --max-time 5 http://127.0.0.1:8110/openapi.json |
  python -c 'import json,sys; d=json.load(sys.stdin); print("\n".join(sorted(d.get("paths", {}))))'
```

Exit code: `0`. The live process advertised `/health`, `/v1/health`, `/v1/languages`, `/v1/admin/metrics`, `/v1/jobs/{job_id}`, and tournament admin routes, but not `/v1/benchmarks` or `/v1/admin/benchmarks`, both of which exist in the checked-out `servers/scoring/module.py`.

## 5. Static checks and tests

| Test ID | Command/Test | Status | Exit code | Expected | Actual | Evidence |
|---|---|---|---:|---|---|---|
| T-01 | `git diff --check` | PASS | 0 | No whitespace errors | No output | Command completed successfully. |
| T-02 | `python -m py_compile servers/scoring/module.py backend/main.py backend/routers/admin.py` | PASS | 0 | All listed Python files compile | No output | Command completed successfully. |
| T-03 | `.venv/bin/python -m unittest discover -s tests -p 'test_engine.py' -v` | PASS | 0 | Engine tests pass | 3 tests passed | `Ran 3 tests ... OK`. |
| T-04 | `frontend/package.json` script inspection | PASS | 0 | Identify the test/build scripts | `test` is `node --experimental-transform-types --test tests/demo-auth.test.mjs`; `build` is `tsc -b && vite build` | Read `frontend/package.json`. |
| T-05 | `cd frontend && npm test` | BLOCKED | 9 | Frontend test script executes | Node error: `bad option: --experimental-transform-types` | Node `v26.3.0` does not support the package script flag in this environment. |
| T-06 | `cd frontend && npm run build` | PASS | 0 | Type-check and production build succeed | Vite build succeeded; emitted existing warning that the JS chunk is over 500 kB | Build output: `index-DOEg58jI.js 536.28 kB`, warning only. |

The initial root-level `npm test` was also attempted and returned exit `254` because there is no root `package.json`; the correct package-directory command was then run as T-05.

## 6. SQL/migration status and error classification

- Migration status: `UNKNOWN`. Documentation states `0004` was previously applied, while `0005`–`0013` were not verified in this session. No Supabase SQL request, migration, `psql`, or production DB operation was run.
- No RPC returned an SQL error because all RPC calls were intentionally skipped.
- No SQL error can therefore be classified as missing migration/function, permission, parameter/schema, SQL runtime, or connection failure.
- The live `/v1/benchmarks` `HTTP 404` is an API process/version mismatch, not a Supabase SQL error.
- The frontend test block is an environment/Node compatibility issue, not an application test assertion failure.

## 7. Conclusion

```json
{
  "run_date": "2026-10-22",
  "timezone": "Asia/Ho_Chi_Minh",
  "environment": "unknown",
  "ports": {
    "8000": "listening",
    "8110": "listening"
  },
  "checks": {
    "backend_health": "PASS",
    "scoring_health": "PASS",
    "admin_read_endpoints": "SKIPPED",
    "sql_rpc_checks": "SKIPPED",
    "frontend_build": "PASS",
    "automated_tests": "BLOCKED"
  },
  "migration_status": "unknown",
  "confirmed_failures": [
    "Live scoring process returns HTTP 404 for source-defined GET /v1/benchmarks.",
    "Frontend npm test script is incompatible with installed Node v26.3.0 because --experimental-transform-types is rejected."
  ],
  "blocked_checks": [
    "Frontend test execution",
    "Admin metrics without a safe admin token",
    "Supabase RPC verification without a confirmed test DB/admin session"
  ],
  "mutating_checks_skipped": [
    "admin_set_submission_gate",
    "create_scoring_job",
    "prepare_swiss_round",
    "finalize_tournament_day",
    "admin_close_qualification",
    "admin_open_tournament_day",
    "admin_close_tournament_day",
    "admin_reset_tournament_to_entry",
    "Bot submission and tournament end-to-end scoring"
  ],
  "recommended_next_steps": [
    "Restart the scoring module from the checked-out source, then recheck /v1/benchmarks and /v1/admin/benchmarks route publication.",
    "Use a separate Supabase test project with fake data and a safe admin account to verify read-only admin RPCs and controlled tournament-flow tests.",
    "Resolve the frontend test command/Node compatibility without changing production data or installing packages during this verification run.",
    "Apply and verify migrations 0005 through 0013 only in the intended test/staging environment before any real tournament operation."
  ]
}
```

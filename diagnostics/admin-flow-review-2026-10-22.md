# Admin flow review — 2026-10-22

## Conclusion

There was a real local route/proxy bug. The React admin page uses `/admin` and `/admin/*`, but Vite proxied `/admin` to FastAPI. FastAPI only defines admin APIs under `/api/admin/*`, so the browser's Vite request was forwarded to a backend route that does not exist and returned 404. Removed that proxy entry (and other obsolete legacy path proxies); Vite now proxies only `/api` to FastAPI. React page routes are served by the SPA.

This explains the `/admin` page 404 in local development and can prevent admins reaching the dashboard. It does not, by itself, explain failures after the React admin dashboard is loaded. Dashboard state/list/gate operations call Supabase RPCs directly; reset/day operations call the scoring module; account creation/import calls FastAPI `/api/admin/*`. Those paths still depend on correct migrations, admin role/JWT, CORS, and a current scoring process.

## Admin request flow

1. `frontend/src/Auth.tsx` logs in through Supabase Auth, then reads the caller's `profiles.role`.
2. `frontend/src/App.tsx` routes admins to the React SPA at `/admin`; contestant users are redirected away from `/admin`.
3. `frontend/src/AdminDashboard.tsx` loads monitoring and eliminated-user data via Supabase RPC; gate/reset-cleanup/elimination operations also use Supabase RPC. Close/open-day/reset and other tournament actions call the scoring module. Creating/importing admin accounts calls FastAPI `/api/admin/*`.
4. FastAPI `backend/main.py` registers `backend/routers/admin.py`; that router defines only `/api/admin/create-admin`, `/api/admin/import-admins`, and `/api/admin/sample-csv`. FastAPI has no `/admin` page route by design.
5. The Vite dev proxy now forwards `/api` only. `/admin`, `/admin/eliminated`, `/admin/server`, and `/sample_bot.py` stay in the frontend.

## Read-only verification

| Request | Result | Meaning |
|---|---|---|
| `GET http://127.0.0.1:5173/admin` | HTTP 200, Vite HTML | React SPA route is served |
| `GET http://127.0.0.1:5173/admin/eliminated` | HTTP 200, Vite HTML | Nested React admin route is served |
| `GET http://127.0.0.1:5173/api/health` | HTTP 200 from Uvicorn | `/api` still proxies to FastAPI |
| `GET http://127.0.0.1:5173/sample_bot.py` | HTTP 200 from Vite | Public asset no longer gets sent to backend |
| `GET http://127.0.0.1:8000/admin` | HTTP 404 JSON | Expected: FastAPI does not serve the SPA |
| `GET http://127.0.0.1:8000/health` | HTTP 200 JSON | Backend is responding |
| `GET http://127.0.0.1:8110/v1/health` | Connection refused | Scoring module was not listening during this review |
| `GET http://127.0.0.1:8110/v1/benchmarks` | Connection refused | Cannot verify the old process's reported 404; Copilot's earlier log records it missing from that process's OpenAPI despite its presence in source |

Commands were read-only `curl -i --max-time 5` requests. `npm run build` from `frontend/` passed; `git diff --check` passed. Build has a Vite warning that the JS bundle exceeds 500 kB.

No admin bearer token was used, so protected FastAPI account routes, Supabase RPCs, and scoring-module admin routes were not called. Supabase migration state remains unknown. If dashboard panels still fail after this route fix, inspect the browser's Supabase RPC error and the backend/scoring logs separately; a backend `GET /admin` 404 is no longer the explanation for those RPC failures.

## Follow-up: eliminated list refresh

The eliminated-users screen obtains its rows from `admin_list_eliminated_contestants()`, separately from the monitoring snapshot. The profile realtime handler previously refreshed only the monitoring snapshot, and the page's Refresh button did the same. If a profile changed to `banned` while the eliminated screen stayed mounted, the dedicated list could remain stale. Updated `AdminDashboard.tsx` so profile realtime events and manual refresh also reload the eliminated RPC whenever that section is active. The SQL function filters `status in ('out','banned')`; its `id` subquery qualification fix is in migration `0012_fix_scoring_and_submission_controls.sql`. Runtime confirmation still requires that migration to be applied and an admin session.

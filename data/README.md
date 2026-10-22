# `data/` — Supabase schema and legacy storage

- `supabase/migrations/`: ordered schema and tournament RPC migrations. See [SUPABASE_SETUP.md](SUPABASE_SETUP.md).
- `supabase_client.py`: lightweight Auth/PostgREST/Storage client dùng chung cho CLI admin, scoring module và CLI trạng thái.
- `auth_service.py`, `manage.py`: Supabase account administration; neither writes tournament state to SQLite.
- `replay_store.py`, `storage_server.py`: retained for the older local replay service; new replays use private Supabase Storage.
- `DATABASE_DESIGN.md`: historical database notes; current operations are described in [../docs/TOURNAMENT_OPERATIONS.md](../docs/TOURNAMENT_OPERATIONS.md).

The active tournament flow stores users, submissions, pairings, results, standings, advancement, and replay metadata in Supabase. Legacy SQLite code and its sync utility are archived in `../backup/legacy_sqlite/`; the database file itself is not included in Git or in that archive.

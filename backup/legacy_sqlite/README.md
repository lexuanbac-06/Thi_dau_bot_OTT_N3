# Legacy SQLite tournament snapshot

This directory is a pre-migration snapshot of the old tournament runtime and data tools. The old tournament runtime and SQLite-to-Supabase sync command are no longer on the active operation path. Do not restore them for a live contest unless intentionally rolling the whole application back.

## Restore source files

From the repository root, copy back only the files needed for a deliberate rollback:

```sh
cp backup/legacy_sqlite/tournament.py ./tournament.py
cp backup/legacy_sqlite/engine.py ./engine.py
cp backup/legacy_sqlite/evaluator.py ./evaluator.py
cp backup/legacy_sqlite/sync.py ./data/sync.py
cp backup/legacy_sqlite/manage.py ./data/manage.py
cp backup/legacy_sqlite/auth_service.py ./data/auth_service.py
```

`data/sync.py` is also archived but intentionally not restored by the command above. Restore it only together with the matching legacy tournament runtime. This archive does not contain `ott.db`, bot submissions, secrets, or replay data. Back those up separately before removing them from an old host. Never run legacy SQLite commands against the same live contest as the Supabase operations.

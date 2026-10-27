import os
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from finals import db


class TestSQLiteDatabase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_path = db.DB_PATH
        self.previous_initialized = db._initialized
        db.DB_PATH = os.path.join(self.temp_dir.name, "finals.db")
        db._initialized = False
        db.init()
        db.migrate()

    def tearDown(self):
        db.DB_PATH = self.previous_path
        db._initialized = self.previous_initialized
        self.temp_dir.cleanup()

    def test_schema_and_crud_work_with_sqlite(self):
        db.migrate()
        db.executemany(
            "INSERT INTO contestants(username, password, display_name) VALUES (?, ?, ?)",
            [("alice", "hash", "Alice"), ("bob", "hash", "Bob")],
        )

        with db.conn() as connection:
            cursor = connection.execute(
                """INSERT INTO matches(request_id, player_a, player_b)
                   VALUES (?, ?, ?)""",
                ("request-1", "alice", "bob"),
            )
            match_id = cursor.lastrowid
            connection.commit()

        db.execute(
            """UPDATE matches
               SET status='done', score_a=?, score_b=?, replay=?
               WHERE id=?""",
            (2, 0, '[{"moves": []}]', match_id),
        )
        db.executemany(
            """INSERT INTO standings(username, wins, losses, draws, points)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(username) DO UPDATE
               SET wins=standings.wins+excluded.wins""",
            [("alice", 1, 0, 0, 3), ("bob", 0, 1, 0, 0)],
        )

        match = db.fetchone(
            "SELECT status, replay FROM matches WHERE request_id=?",
            ("request-1",),
        )
        self.assertEqual(match["status"], "done")
        self.assertEqual(match["replay"], '[{"moves": []}]')
        self.assertEqual(
            db.fetchone("SELECT points FROM standings WHERE username=?", ("alice",))["points"],
            3,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute(
                """INSERT INTO matches(request_id, player_a, player_b)
                   VALUES (?, ?, ?)""",
                ("invalid-request", "missing", "bob"),
            )

    def test_enqueue_match_creates_sqlite_record_and_queues_it(self):
        from finals import match_runner

        db.executemany(
            "INSERT INTO contestants(username, password, display_name) VALUES (?, ?, ?)",
            [("alice", "hash", "Alice"), ("bob", "hash", "Bob")],
        )
        task_queue = MagicMock()
        task_queue.qsize.return_value = 1

        with patch.object(match_runner, "_task_queue", task_queue):
            result = match_runner.enqueue_match("alice", "bob", request_id="sqlite-request")

        match = db.fetchone(
            "SELECT id, status FROM matches WHERE request_id=?",
            ("sqlite-request",),
        )
        self.assertTrue(result["queued"])
        self.assertEqual(match["status"], "pending")
        task_queue.put_nowait.assert_called_once()

    def test_purge_expired_sessions_uses_sqlite_connection(self):
        from finals import auth

        db.execute(
            "INSERT INTO contestants(username, password, display_name) VALUES (?, ?, ?)",
            ("alice", "hash", "Alice"),
        )
        db.execute(
            "INSERT INTO sessions(token, username, expires_at) VALUES (?, ?, ?)",
            ("expired-token", "alice", "2000-01-01T00:00:00+00:00"),
        )

        self.assertEqual(auth.purge_expired_sessions(), 1)
        self.assertIsNone(
            db.fetchone("SELECT token FROM sessions WHERE token=?", ("expired-token",))
        )


if __name__ == "__main__":
    unittest.main()

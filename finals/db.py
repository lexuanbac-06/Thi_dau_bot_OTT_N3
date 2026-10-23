"""
finals/db.py
------------
Kết nối SQLite cho vòng chung kết.
Đường dẫn database được cấu hình qua FINALS_DB_PATH.
"""
import logging
import os
import sqlite3

logger = logging.getLogger("finals.db")

DB_PATH = os.environ.get(
    "FINALS_DB_PATH",
    os.path.join(os.path.dirname(__file__), "finals.db"),
)
if DB_PATH != ":memory:" and not os.path.isabs(DB_PATH):
    DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", DB_PATH))
_initialized = False


def init() -> None:
    """Chuẩn bị thư mục và kiểm tra kết nối database."""
    global _initialized
    if DB_PATH != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    connection = _connect()
    try:
        connection.execute("PRAGMA journal_mode = WAL")
    finally:
        connection.close()
    _initialized = True
    logger.info("[DB] SQLite sẵn sàng: %s", DB_PATH)


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


class _Conn:
    """Mở và tự đóng một SQLite connection cho mỗi thao tác."""

    def __enter__(self) -> sqlite3.Connection:
        if not _initialized:
            raise RuntimeError("SQLite chưa được khởi tạo. Gọi db.init() trước.")
        self._conn = _connect()
        return self._conn

    def __exit__(self, exc_type, *_):
        if exc_type:
            self._conn.rollback()
        self._conn.close()


def conn() -> _Conn:
    return _Conn()


SCHEMA = """
CREATE TABLE IF NOT EXISTS contestants (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    username     TEXT UNIQUE NOT NULL,
    password     TEXT NOT NULL,
    display_name TEXT NOT NULL,
    student_id   TEXT UNIQUE,
    auth_user_id TEXT,
    email        TEXT,
    advance_route TEXT,
    final_rank   INTEGER,
    avg_rank_pct TEXT,
    created_at   TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    username   TEXT NOT NULL REFERENCES contestants(username) ON DELETE CASCADE,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS matches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id  TEXT UNIQUE NOT NULL,
    player_a    TEXT NOT NULL REFERENCES contestants(username),
    player_b    TEXT NOT NULL REFERENCES contestants(username),
    status      TEXT NOT NULL DEFAULT 'pending',
    score_a     INTEGER,
    score_b     INTEGER,
    winner      TEXT,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    started_at  TEXT,
    finished_at TEXT,
    error_msg   TEXT,
    replay      TEXT
);

CREATE TABLE IF NOT EXISTS standings (
    username   TEXT PRIMARY KEY REFERENCES contestants(username),
    wins       INTEGER DEFAULT 0,
    losses     INTEGER DEFAULT 0,
    draws      INTEGER DEFAULT 0,
    points     INTEGER DEFAULT 0,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status);
CREATE INDEX IF NOT EXISTS idx_sessions_username ON sessions(username);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
"""


def migrate() -> None:
    """Chạy schema DDL (idempotent — an toàn khi gọi nhiều lần)."""
    with conn() as connection:
        connection.executescript(SCHEMA)
        contestant_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(contestants)")
        }
        if "auth_user_id" not in contestant_columns:
            connection.execute("ALTER TABLE contestants ADD COLUMN auth_user_id TEXT")
        if "email" not in contestant_columns:
            connection.execute("ALTER TABLE contestants ADD COLUMN email TEXT")
        if "advance_route" not in contestant_columns:
            connection.execute("ALTER TABLE contestants ADD COLUMN advance_route TEXT")
        if "final_rank" not in contestant_columns:
            connection.execute("ALTER TABLE contestants ADD COLUMN final_rank INTEGER")
        if "avg_rank_pct" not in contestant_columns:
            connection.execute("ALTER TABLE contestants ADD COLUMN avg_rank_pct TEXT")
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_contestants_auth_user_id "
            "ON contestants(auth_user_id) WHERE auth_user_id IS NOT NULL"
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_contestants_email "
            "ON contestants(email) WHERE email IS NOT NULL"
        )
        connection.commit()
    logger.info("[DB] Schema migration hoàn tất.")


def fetchone(sql: str, params=()) -> dict | None:
    with conn() as connection:
        row = connection.execute(sql, params).fetchone()
    return dict(row) if row else None


def fetchall(sql: str, params=()) -> list[dict]:
    with conn() as connection:
        rows = connection.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def execute(sql: str, params=()) -> None:
    with conn() as connection:
        connection.execute(sql, params)
        connection.commit()


def executemany(sql: str, rows: list) -> None:
    with conn() as connection:
        connection.executemany(sql, rows)
        connection.commit()

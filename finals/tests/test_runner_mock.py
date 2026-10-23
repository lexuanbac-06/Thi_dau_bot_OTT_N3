"""
finals/tests/test_runner_mock.py
---------------------------------
Unit test cơ bản cho match_runner và auth (dùng mock DB).
Chạy: pytest finals/tests/test_runner_mock.py -v
"""
import sys
import types
import uuid
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
bcrypt_mock = types.ModuleType("bcrypt")
bcrypt_mock.hashpw = lambda p, s: p + b"_hashed"
bcrypt_mock.gensalt = lambda: b"salt"
bcrypt_mock.checkpw = lambda p, h: h == p + b"_hashed"
sys.modules.setdefault("bcrypt", bcrypt_mock)

# ---------------------------------------------------------------------------
# Test match_runner logic (không cần DB)
# ---------------------------------------------------------------------------
class TestMatchRunnerUnit:
    def test_enqueue_returns_request_id(self):
        """enqueue_match phải trả về request_id và match_id."""
        with patch("finals.match_runner.db") as mock_db, \
             patch("finals.match_runner._task_queue") as mock_queue:

            mock_db.fetchone.return_value = None    # không tìm thấy existing
            # side_effect: lần 1 kiểm tra player_a tồn tại, lần 2 player_b
            mock_db.fetchone.side_effect = [None, {"exists": 1}, {"exists": 1}]

            # Mock DB conn context manager
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
            mock_cursor.__exit__ = MagicMock(return_value=False)
            mock_cursor.lastrowid = 42
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn.cursor = MagicMock(return_value=mock_cursor)
            mock_db.conn.return_value = mock_conn

            mock_queue.qsize.return_value = 1
            mock_queue.put_nowait = MagicMock()

            from finals import match_runner
            rq_id = str(uuid.uuid4())
            result = match_runner.enqueue_match("alice", "bob", request_id=rq_id)
            assert result["request_id"] == rq_id
            assert result["queued"] is True

    def test_get_match_status_not_found(self):
        with patch("finals.match_runner.db") as mock_db:
            mock_db.fetchone.return_value = None
            from finals import match_runner
            assert match_runner.get_match_status("nonexistent") is None

    def test_get_queue_info_returns_dict(self):
        with patch("finals.match_runner.db") as mock_db, \
             patch("finals.match_runner._task_queue") as mock_queue:
            mock_db.fetchone.return_value = {"n": 3}
            mock_queue.qsize.return_value = 2
            from finals import match_runner
            info = match_runner.get_queue_info()
            assert "queue_size" in info
            assert "max_workers" in info


# ---------------------------------------------------------------------------
# Test auth logic
# ---------------------------------------------------------------------------
class TestAuth:
    def test_hash_and_check_password(self):
        from finals import auth
        h = auth.hash_password("secret123")
        assert auth.check_password("secret123", h)
        assert not auth.check_password("wrong", h)

    def test_register_validates_username(self):
        with patch("finals.auth.db") as mock_db:
            from finals import auth
            with pytest.raises(ValueError, match="username"):
                auth.register_contestant("ab", "password123", "Test")

    def test_register_validates_password(self):
        with patch("finals.auth.db") as mock_db:
            from finals import auth
            with pytest.raises(ValueError, match="Mật khẩu"):
                auth.register_contestant("alice", "123", "Alice")

    def test_login_wrong_password(self):
        with patch("finals.auth.db") as mock_db:
            import bcrypt
            hashed = bcrypt.hashpw(b"correct", b"salt").decode()
            mock_db.fetchone.return_value = {"password": hashed, "display_name": "Alice"}
            from finals import auth
            with pytest.raises(PermissionError):
                auth.login("alice", "wrong_password")

    def test_get_session_returns_none_for_empty_token(self):
        with patch("finals.auth.db") as mock_db:
            from finals import auth
            assert auth.get_session("") is None
            assert auth.get_session(None) is None

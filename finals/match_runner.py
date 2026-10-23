"""
finals/match_runner.py
-----------------------
Engine xử lý trận đấu chung kết: đa luồng, Queue, request_id.

Flow:
  1. Client gọi POST /matches  → tạo record DB (status=pending), đẩy vào Queue
  2. Worker pool (ThreadPoolExecutor) lấy task từ Queue, chạy engine.play_match_recorded()
  3. Cập nhật kết quả vào DB (status=done/failed)
  4. Client poll GET /matches/<request_id> để lấy kết quả

Có thể phục vụ nhiều cặp đấu song song (tuỳ MAX_WORKERS).
"""
import logging
import os
import threading
import queue
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional

from . import db
# engine nằm ở thư mục gốc → import từ thư mục cha
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import engine as game_engine

logger = logging.getLogger("finals.runner")

MAX_WORKERS = int(os.environ.get("FINALS_MAX_WORKERS", os.cpu_count() or 4))
MAX_QUEUE_SIZE = int(os.environ.get("FINALS_QUEUE_SIZE", 200))

# ---------------------------------------------------------------------------
# Hàng đợi và executor (khởi tạo 1 lần qua start())
# ---------------------------------------------------------------------------
_task_queue: queue.Queue = queue.Queue(maxsize=MAX_QUEUE_SIZE)
_executor: Optional[ThreadPoolExecutor] = None
_started = False
_lock = threading.Lock()


def start() -> None:
    """Khởi động worker pool. Gọi 1 lần khi app start."""
    global _executor, _started
    with _lock:
        if _started:
            return
        _executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="finals-worker")
        # Dispatcher thread: lấy task từ Queue và giao cho executor
        t = threading.Thread(target=_dispatcher, daemon=True, name="finals-dispatcher")
        t.start()
        _started = True
        logger.info("[RUNNER] Khởi động: %d workers, queue_max=%d", MAX_WORKERS, MAX_QUEUE_SIZE)


def stop() -> None:
    """Tắt pool khi app shutdown."""
    global _started
    with _lock:
        if _executor:
            _executor.shutdown(wait=False)
        _started = False
    logger.info("[RUNNER] Đã tắt worker pool.")


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
def _dispatcher() -> None:
    logger.info("[DISPATCHER] Bắt đầu lắng nghe hàng đợi...")
    while True:
        try:
            task = _task_queue.get(timeout=1)
        except queue.Empty:
            continue
        if task is None:           # poison pill để dừng dispatcher
            logger.info("[DISPATCHER] Nhận poison pill, dừng.")
            break
        if _executor:
            _executor.submit(_run_match, task)
        else:
            logger.error("[DISPATCHER] Executor chưa khởi tạo, bỏ task %s", task.get("request_id"))
        _task_queue.task_done()


# ---------------------------------------------------------------------------
# Chạy một trận đấu
# ---------------------------------------------------------------------------
def _bot_path(username: str, snap_dir: str) -> str | None:
    """Tìm file bot của thí sinh trong thư mục snapshot chung kết."""
    p = os.path.join(snap_dir, f"{username}.py")
    return p if os.path.exists(p) else None


from . import db, live_manager


def _run_match(task: dict) -> None:
    request_id = task["request_id"]
    match_id = task["match_id"]
    player_a = task["player_a"]
    player_b = task["player_b"]
    snap_dir = task.get("snap_dir", os.path.join(os.path.dirname(__file__), "..", "snaps", "finals"))
    live_delay = float(task.get("live_delay", os.environ.get("FINALS_LIVE_DELAY", 0.35)))

    logger.info("[MATCH:%s] Bắt đầu: %s vs %s (live_delay=%.2fs)", request_id, player_a, player_b, live_delay)
    _mark_running(match_id)
    live_manager.publish(request_id, {
        "type": "match_start",
        "request_id": request_id,
        "player_a": player_a,
        "player_b": player_b,
    })

    try:
        path_a = _bot_path(player_a, snap_dir)
        path_b = _bot_path(player_b, snap_dir)

        if path_a is None or path_b is None:
            missing = [u for u, p in [(player_a, path_a), (player_b, path_b)] if p is None]
            raise FileNotFoundError(f"Không tìm thấy bot của: {', '.join(missing)}")

        def on_move_callback(game_idx, ply, p, move, captured, is_win):
            # first=0: p=0 là a, p=1 là b. first=1: p=0 là b, p=1 là a.
            mover = player_a if (game_idx == 0 and p == 0) or (game_idx == 1 and p == 1) else player_b
            live_manager.publish(request_id, {
                "type": "move",
                "request_id": request_id,
                "game": game_idx,
                "ply": ply,
                "player": p,
                "mover": mover,
                "move": list(move),
                "captured": list(captured) if captured else None,
                "is_win": bool(is_win),
            })

        t0 = time.monotonic()
        score, games = game_engine.play_match_recorded(
            (path_a, path_b),
            on_move=on_move_callback,
            delay=live_delay,
        )
        elapsed = time.monotonic() - t0

        # score > 0 → A thắng; < 0 → B thắng; = 0 → hoà (mỗi trận BO2, tối đa ±2)
        score_a = max(0, score)
        score_b = max(0, -score)
        if score > 0:
            winner = player_a
        elif score < 0:
            winner = player_b
        else:
            winner = None

        logger.info(
            "[MATCH:%s] Kết thúc: %s %d-%d %s (%.1fs)",
            request_id, player_a, score_a, score_b, player_b, elapsed,
        )
        _save_result(match_id, score_a, score_b, winner, games)
        _update_standings(player_a, player_b, score)

        live_manager.publish(request_id, {
            "type": "match_end",
            "request_id": request_id,
            "score_a": score_a,
            "score_b": score_b,
            "winner": winner,
            "games": games,
        })

    except Exception as exc:
        logger.exception("[MATCH:%s] Lỗi: %s", request_id, exc)
        _mark_failed(match_id, str(exc))
        live_manager.publish(request_id, {
            "type": "match_failed",
            "request_id": request_id,
            "error": str(exc),
        })


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def _mark_running(match_id: int) -> None:
    db.execute(
        "UPDATE matches SET status='running', started_at=CURRENT_TIMESTAMP WHERE id=?",
        (match_id,),
    )


def _save_result(match_id: int, score_a: int, score_b: int, winner: str | None, games: list) -> None:
    import json
    db.execute(
        """UPDATE matches
           SET status='done', score_a=?, score_b=?, winner=?,
               finished_at=CURRENT_TIMESTAMP, replay=?
           WHERE id=?""",
        (score_a, score_b, winner, json.dumps(games), match_id),
    )


def _mark_failed(match_id: int, error_msg: str) -> None:
    db.execute(
        "UPDATE matches SET status='failed', finished_at=CURRENT_TIMESTAMP, error_msg=? WHERE id=?",
        (error_msg, match_id),
    )


def _update_standings(player_a: str, player_b: str, score: int) -> None:
    """Cập nhật bảng standings sau mỗi trận (dùng UPSERT)."""
    upsert = """
        INSERT INTO standings(username, wins, losses, draws, points)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(username) DO UPDATE
        SET wins   = standings.wins   + EXCLUDED.wins,
            losses = standings.losses + EXCLUDED.losses,
            draws  = standings.draws  + EXCLUDED.draws,
            points = standings.points + EXCLUDED.points,
            updated_at = CURRENT_TIMESTAMP
    """
    if score > 0:
        rows = [(player_a, 1, 0, 0, 3), (player_b, 0, 1, 0, 0)]
    elif score < 0:
        rows = [(player_a, 0, 1, 0, 0), (player_b, 1, 0, 0, 3)]
    else:
        rows = [(player_a, 0, 0, 1, 1), (player_b, 0, 0, 1, 1)]
    db.executemany(upsert, rows)
    logger.debug("[STANDINGS] Cập nhật: %s, %s (score=%d)", player_a, player_b, score)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def enqueue_match(
    player_a: str,
    player_b: str,
    request_id: str | None = None,
    snap_dir: str | None = None,
    live_delay: float | None = None,
) -> dict:
    """
    Tạo trận đấu mới và đẩy vào hàng đợi.
    Trả về dict với request_id và match_id để client theo dõi.
    Idempotent: nếu request_id đã tồn tại, trả về record cũ.
    """
    if request_id is None:
        request_id = str(uuid.uuid4())

    # Idempotency check
    existing = db.fetchone(
        "SELECT id, status, request_id FROM matches WHERE request_id=?",
        (request_id,),
    )
    if existing:
        logger.info("[RUNNER] Request %s đã tồn tại (status=%s), bỏ qua.", request_id, existing["status"])
        return {"request_id": request_id, "match_id": existing["id"], "queued": False, "existing": True}

    # Kiểm tra player tồn tại
    for uname in (player_a, player_b):
        if not db.fetchone("SELECT 1 FROM contestants WHERE username=?", (uname,)):
            raise ValueError(f"Không tìm thấy thí sinh: {uname}")

    # Tạo record DB
    with db.conn() as c:
        with c.cursor() as cur:
            cur.execute(
                """INSERT INTO matches(request_id, player_a, player_b, status)
                   VALUES (?, ?, ?, 'pending')""",
                (request_id, player_a, player_b),
            )
            match_id = cur.lastrowid
        c.commit()

    task = {
        "request_id": request_id,
        "match_id": match_id,
        "player_a": player_a,
        "player_b": player_b,
    }
    if snap_dir:
        task["snap_dir"] = snap_dir
    if live_delay is not None:
        task["live_delay"] = live_delay

    try:
        _task_queue.put_nowait(task)
    except queue.Full:
        db.execute("UPDATE matches SET status='failed', error_msg='Queue đầy' WHERE id=?", (match_id,))
        raise RuntimeError("Hàng đợi trận đấu đầy. Vui lòng thử lại sau.")

    queue_size = _task_queue.qsize()
    logger.info(
        "[RUNNER] Đã enqueue: %s vs %s | request_id=%s match_id=%d queue_size=%d",
        player_a, player_b, request_id, match_id, queue_size,
    )
    return {"request_id": request_id, "match_id": match_id, "queued": True, "queue_size": queue_size}


def get_match_status(request_id: str) -> dict | None:
    """Trả về trạng thái trận đấu theo request_id."""
    row = db.fetchone(
        """SELECT id, request_id, player_a, player_b, status,
                  score_a, score_b, winner, error_msg,
                  created_at, started_at, finished_at
           FROM matches WHERE request_id=?""",
        (request_id,),
    )
    return row


def get_match_replay(request_id: str) -> dict | None:
    """Trả về thông tin trận đấu kèm toàn bộ nước đi (replay)."""
    import json
    row = db.fetchone(
        """SELECT id, request_id, player_a, player_b, status,
                  score_a, score_b, winner, error_msg,
                  created_at, started_at, finished_at, replay
           FROM matches WHERE request_id=?""",
        (request_id,),
    )
    if row and row.get("replay"):
        if isinstance(row["replay"], str):
            try:
                row["replay"] = json.loads(row["replay"])
            except Exception:
                pass
    return row


def get_queue_info() -> dict:
    """Trả về thông tin hàng đợi hiện tại."""
    pending_db = db.fetchone("SELECT count(*) n FROM matches WHERE status IN ('pending','running')")
    return {
        "queue_size": _task_queue.qsize(),
        "max_workers": MAX_WORKERS,
        "pending_db": pending_db["n"] if pending_db else 0,
        "worker_started": _started,
    }


def standings() -> list[dict]:
    """Bảng xếp hạng tổng."""
    return db.fetchall(
        """SELECT username, wins, losses, draws, points, updated_at
           FROM standings ORDER BY points DESC, wins DESC, username"""
    )

"""
finals/live_manager.py
-----------------------
Quản lý phát trực tiếp (Live Stream) từng nước đi của trận đấu qua Server-Sent Events (SSE).
Hỗ trợ nhiều người xem đồng thời cho cùng một trận đấu.
"""
import collections
import json
import logging
import queue
import threading
import time
from typing import Dict, List, Set

logger = logging.getLogger("finals.live")

_lock = threading.Lock()
# request_id -> Set[queue.Queue]
_subscribers: Dict[str, Set[queue.Queue]] = collections.defaultdict(set)
# request_id -> List of events history (để người vào sau xem ngay từ đầu ván)
_history: Dict[str, List[dict]] = collections.defaultdict(list)


def subscribe(request_id: str) -> queue.Queue:
    """Đăng ký nhận stream trực tiếp của một request_id."""
    q: queue.Queue = queue.Queue(maxsize=500)
    with _lock:
        _subscribers[request_id].add(q)
        hist = list(_history.get(request_id, []))

    # Đẩy toàn bộ lịch sử nước đi trước đó vào queue cho người mới kết nối
    for ev in hist:
        try:
            q.put_nowait(ev)
        except queue.Full:
            break

    logger.debug("[LIVE:%s] Khách mới kết nối stream (tổng: %d)", request_id, len(_subscribers[request_id]))
    return q


def unsubscribe(request_id: str, q: queue.Queue) -> None:
    """Huỷ đăng ký khi client ngắt kết nối."""
    with _lock:
        if request_id in _subscribers:
            _subscribers[request_id].discard(q)
            if not _subscribers[request_id]:
                del _subscribers[request_id]
    logger.debug("[LIVE:%s] Khách đã ngắt kết nối", request_id)


def publish(request_id: str, event: dict) -> None:
    """Phát một sự kiện (nước đi, bắt đầu, kết thúc) tới tất cả người xem."""
    with _lock:
        _history[request_id].append(event)
        subscribers = list(_subscribers.get(request_id, []))

    dead_queues = []
    for q in subscribers:
        try:
            q.put_nowait(event)
        except queue.Full:
            dead_queues.append(q)

    if dead_queues:
        with _lock:
            for dq in dead_queues:
                _subscribers[request_id].discard(dq)


def clear_match(request_id: str) -> None:
    """Dọn dẹp bộ nhớ khi trận kết thúc một thời gian."""
    with _lock:
        _history.pop(request_id, None)
        _subscribers.pop(request_id, None)

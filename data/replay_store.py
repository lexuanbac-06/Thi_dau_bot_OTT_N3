"""Lưu replay ván đấu ra đĩa local: gzip JSON, ghi nguyên tử.

Đường dẫn: <REPLAY_DIR>/r{rnd}/d{day}/g{grp}/{rd}__{a}__vs__{b}.json.gz
Username đã được kiểm tra regex [A-Za-z0-9_]{3,20} nên an toàn khi đưa vào tên file.
"""
import gzip
import json
import os
import re
import uuid

from . import config

_NAME = re.compile(r"[A-Za-z0-9_]{3,20}")


def replay_path(rnd, day, grp, rd, a, b, base=None):
    for n in (a, b):
        if not _NAME.fullmatch(n):
            raise ValueError(f"Tên không hợp lệ: {n!r}")
    base = base or config.REPLAY_DIR
    return os.path.join(base, f"r{int(rnd)}", f"d{int(day)}", f"g{int(grp)}",
                        f"{int(rd)}__{a}__vs__{b}.json.gz")


def save(rnd, day, grp, rd, a, b, games, base=None, overwrite=False):
    """games: list ván (hoặc chuỗi JSON). Trả (path, đã_ghi)."""
    p = replay_path(rnd, day, grp, rd, a, b, base)
    if os.path.exists(p) and not overwrite:
        return p, False
    os.makedirs(os.path.dirname(p), exist_ok=True)
    raw = games if isinstance(games, str) else json.dumps(games, separators=(",", ":"))
    tmp = p + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as f:
        f.write(raw)
    os.replace(tmp, p)
    return p, True


def read_gz_bytes(rnd, day, grp, rd, a, b, base=None):
    """Trả bytes gzip nguyên bản (để gửi thẳng với Content-Encoding: gzip) hoặc None."""
    p = replay_path(rnd, day, grp, rd, a, b, base)
    if not os.path.isfile(p):
        return None
    with open(p, "rb") as f:
        return f.read()


def load(rnd, day, grp, rd, a, b, base=None):
    raw = read_gz_bytes(rnd, day, grp, rd, a, b, base)
    return None if raw is None else json.loads(gzip.decompress(raw))


def job_replay_path(job_id, base=None):
    """Replay for a standalone entry/test scoring job, keyed by a trusted UUID."""
    key = str(uuid.UUID(str(job_id)))
    base = base or os.path.join(config.REPLAY_DIR, "jobs")
    return os.path.join(base, f"{key}.json.gz")


def save_job(job_id, games, base=None):
    path = job_replay_path(job_id, base)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as f:
        json.dump(games, f, separators=(",", ":"))
    os.replace(tmp, path)
    return path


def load_job(job_id, base=None):
    path = job_replay_path(job_id, base)
    if not os.path.isfile(path):
        return None
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)

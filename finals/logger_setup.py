"""
finals/logger_setup.py
-----------------------
Cấu hình logging tập trung cho module chung kết.
- Console (stdout): INFO trở lên
- File (finals/logs/finals.log): DEBUG trở lên, xoay file mỗi ngày, giữ 30 ngày
"""
import logging
import logging.handlers
import os
import sys


LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
LOG_FILE = os.path.join(LOG_DIR, "finals.log")

FMT = "%(asctime)s %(levelname)-7s %(name)-24s %(message)s"
DATE_FMT = "%Y-%m-%d %H:%M:%S"


def setup(level: str = "DEBUG") -> None:
    if sys.platform.startswith("win"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
            sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass
    os.makedirs(LOG_DIR, exist_ok=True)

    root = logging.getLogger("finals")
    root.setLevel(logging.DEBUG)

    # ---- Console ----
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(getattr(logging, level.upper(), logging.INFO))
    ch.setFormatter(logging.Formatter(FMT, DATE_FMT))
    root.addHandler(ch)

    # ---- File (rotating daily) ----
    fh = logging.handlers.TimedRotatingFileHandler(
        LOG_FILE, when="midnight", backupCount=30, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(FMT, DATE_FMT))
    root.addHandler(fh)

    root.propagate = False
    root.info("[LOG] Logging khởi tạo. Cấp console=%s, file=DEBUG → %s", level.upper(), LOG_FILE)

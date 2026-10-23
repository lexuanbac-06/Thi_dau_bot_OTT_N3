"""
finals/run_server.py
--------------------
Entrypoint tiện dụng để chạy server chung kết.
Hỗ trợ load .env trước khi import app.

Chạy:
  python -m finals.run_server
  # hoặc
  python finals/run_server.py
"""
import os
import sys

# ---------------------------------------------------------------------------
# Load .env nếu có (trước khi import app để biến môi trường có hiệu lực)
# ---------------------------------------------------------------------------
def _load_dotenv(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and (key not in os.environ or os.environ[key] in ("", "CHANGE_ME", "CHANGE_ME_ADMIN")):
                os.environ[key] = val

_env_file = os.path.join(os.path.dirname(__file__), ".env")
_load_dotenv(_env_file)

# ---------------------------------------------------------------------------
# Import và chạy
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from finals.app import app, startup

if __name__ == "__main__":
    startup()
    port = int(os.environ.get("FINALS_PORT", 9000))
    print(f"[FINALS] Backend khởi động tại http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, threaded=True)

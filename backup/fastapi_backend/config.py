import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent

def _load_env_file(path):
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

# Load từ root .env và data/.env
_load_env_file(ROOT_DIR / ".env")
_load_env_file(ROOT_DIR / "data" / ".env")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

EMAIL_DOMAIN = os.environ.get("OTT_EMAIL_DOMAIN", "players.ott.example")
MIN_PASSWORD_LEN = int(os.environ.get("OTT_MIN_PASSWORD_LEN", "8"))

CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "OTT_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000,http://localhost:8000,http://127.0.0.1:8000"
    ).split(",")
    if origin.strip()
]

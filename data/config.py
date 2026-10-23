"""Cấu hình cho tầng data (Supabase + lưu trữ local). Đọc từ biến môi trường hoặc file data/.env.

Không dùng thư viện ngoài: file .env chỉ cần dạng KEY=VALUE.
"""
import os

DATA_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_dotenv(path):
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv(os.path.join(DATA_DIR, ".env"))


def env(name, default=None, required=False):
    v = os.environ.get(name, default)
    if required and not v:
        raise RuntimeError(f"Thiếu biến môi trường {name} (xem data/.env.example)")
    return v


def supabase_url():
    return env("SUPABASE_URL", required=True).rstrip("/")


def anon_key():
    return env("SUPABASE_ANON_KEY", required=True)


def service_key():
    """service_role: chỉ dùng trên máy chủ/máy chấm, KHÔNG gửi cho trình duyệt."""
    return env("SUPABASE_SERVICE_ROLE_KEY", required=True)


# Supabase Auth cần email; thí sinh đăng nhập bằng username nên ta sinh email giả từ username.
EMAIL_DOMAIN = env("OTT_EMAIL_DOMAIN", "players.ott.example")
OPEN_REGISTRATION = env("OTT_OPEN_REGISTRATION", "1") == "1"
MIN_PASSWORD_LEN = int(env("OTT_MIN_PASSWORD_LEN", "8"))

# Thư mục lưu file nặng (replay). Đặt OTT_STORAGE_DIR để trỏ sang ổ đĩa lớn.
STORAGE_DIR = env("OTT_STORAGE_DIR", os.path.join(DATA_DIR, "storage"))
REPLAY_DIR = os.path.join(STORAGE_DIR, "replays")

# Origin được phép gọi storage server qua trình duyệt (CORS), phân tách bằng dấu phẩy.
CORS_ORIGINS = [o.strip() for o in env("OTT_CORS_ORIGINS", "").split(",") if o.strip()]

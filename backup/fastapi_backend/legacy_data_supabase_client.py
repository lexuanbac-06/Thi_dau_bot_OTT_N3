"""Client Supabase tối giản (Auth + PostgREST) dùng urllib, không cần cài thêm gói."""
import json
import urllib.error
import urllib.parse
import urllib.request

from . import config


class SupabaseError(Exception):
    def __init__(self, status, body):
        self.status, self.body = status, body
        msg = body.get("msg") or body.get("message") or body.get("error_description") or body.get("error") \
            if isinstance(body, dict) else str(body)
        super().__init__(f"Supabase {status}: {msg}")


def _call(method, url, headers, payload=None, timeout=30):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            body = json.loads(raw)
        except ValueError:
            body = {"message": raw.decode(errors="replace")}
        raise SupabaseError(e.code, body) from None


class Supabase:
    def __init__(self, url=None, anon=None, service=None):
        self.url = (url or config.supabase_url()).rstrip("/")
        self._anon, self._service = anon, service

    @property
    def anon(self):
        return self._anon or config.anon_key()

    @property
    def service(self):
        return self._service or config.service_key()

    def _h(self, token=None, service=False, extra=None):
        key = self.service if service else self.anon
        h = {"apikey": key, "Authorization": f"Bearer {token or key}"}
        h.update(extra or {})
        return h

    # ---------------- AUTH ----------------
    def sign_in(self, email, password):
        _, body = _call("POST", f"{self.url}/auth/v1/token?grant_type=password",
                        self._h(), {"email": email, "password": password})
        return body

    def refresh(self, refresh_token):
        _, body = _call("POST", f"{self.url}/auth/v1/token?grant_type=refresh_token",
                        self._h(), {"refresh_token": refresh_token})
        return body

    def sign_out(self, access_token, scope="local"):
        _call("POST", f"{self.url}/auth/v1/logout?scope={scope}", self._h(token=access_token))

    def get_user(self, access_token):
        _, body = _call("GET", f"{self.url}/auth/v1/user", self._h(token=access_token))
        return body

    def admin_create_user(self, email, password, username):
        _, body = _call("POST", f"{self.url}/auth/v1/admin/users", self._h(service=True), {
            "email": email, "password": password, "email_confirm": True,
            "user_metadata": {"username": username}})
        return body

    def admin_delete_user(self, user_id):
        _call("DELETE", f"{self.url}/auth/v1/admin/users/{user_id}", self._h(service=True))

    # ---------------- REST ----------------
    def select(self, table, params=None, token=None):
        """Mặc định dùng service_role; truyền token để chạy dưới quyền (RLS) của người dùng."""
        q = urllib.parse.urlencode(params or {})
        _, body = _call("GET", f"{self.url}/rest/v1/{table}?{q}", self._h(token=token, service=token is None))
        return body

    def select_all(self, table, params=None, page=1000):
        out, offset = [], 0
        while True:
            rows = self.select(table, {**(params or {}), "limit": page, "offset": offset})
            out += rows
            if len(rows) < page:
                return out
            offset += page

    def upsert(self, table, rows, on_conflict, batch=500):
        """Upsert theo lô; cột không có trong rows được giữ nguyên khi bản ghi đã tồn tại."""
        if not rows:
            return 0
        q = urllib.parse.urlencode({"on_conflict": on_conflict})
        h = self._h(service=True, extra={"Prefer": "resolution=merge-duplicates,return=minimal"})
        for i in range(0, len(rows), batch):
            _call("POST", f"{self.url}/rest/v1/{table}?{q}", h, rows[i:i + batch], timeout=120)
        return len(rows)

    def insert(self, table, rows):
        if rows:
            _call("POST", f"{self.url}/rest/v1/{table}",
                  self._h(service=True, extra={"Prefer": "return=minimal"}), rows)

    def update(self, table, match, values):
        """match: {"id": "eq.<uuid>"} (cú pháp filter của PostgREST)."""
        q = urllib.parse.urlencode(match)
        _call("PATCH", f"{self.url}/rest/v1/{table}?{q}",
              self._h(service=True, extra={"Prefer": "return=minimal"}), values)

    def rpc(self, fn, args=None, token=None):
        _, body = _call("POST", f"{self.url}/rest/v1/rpc/{fn}",
                        self._h(token=token, service=token is None), args or {})
        return body

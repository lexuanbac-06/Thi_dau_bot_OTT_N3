import json
import re
import urllib.error
import urllib.parse
import urllib.request
from . import config

class SupabaseError(Exception):
    def __init__(self, status: int, body: any):
        self.status = status
        self.body = body
        msg = (
            body.get("msg")
            or body.get("message")
            or body.get("error_description")
            or body.get("error")
            if isinstance(body, dict)
            else str(body)
        )
        super().__init__(f"Supabase {status}: {msg}")

def _call(method: str, url: str, headers: dict, payload: any = None, timeout: int = 30):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", **headers},
    )
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
    def __init__(self, url: str = None, anon: str = None, service: str = None):
        self.url = (url or config.supabase_url()).rstrip("/")
        self._anon = anon
        self._service = service

    @property
    def anon(self):
        return self._anon or config.anon_key()

    @property
    def service(self):
        return self._service or config.service_key()

    def _headers(self, token: str = None, service: bool = False, extra: dict = None):
        key = self.service if service else self.anon
        h = {"apikey": key, "Authorization": f"Bearer {token or key}"}
        if extra:
            h.update(extra)
        return h

    # ---------------- Auth ----------------
    def get_user(self, access_token: str):
        _, body = _call("GET", f"{self.url}/auth/v1/user", self._headers(token=access_token))
        return body

    def sign_in(self, email: str, password: str):
        _, body = _call(
            "POST",
            f"{self.url}/auth/v1/token?grant_type=password",
            self._headers(),
            {"email": email, "password": password},
        )
        return body

    def refresh(self, refresh_token: str):
        _, body = _call(
            "POST",
            f"{self.url}/auth/v1/token?grant_type=refresh_token",
            self._headers(),
            {"refresh_token": refresh_token},
        )
        return body

    def sign_out(self, access_token: str, scope: str = "local"):
        _call(
            "POST",
            f"{self.url}/auth/v1/logout?scope={urllib.parse.quote(scope, safe='')}",
            self._headers(token=access_token),
        )

    def admin_create_user(self, email: str, password: str, username: str, email_confirm: bool = True):
        _, body = _call(
            "POST",
            f"{self.url}/auth/v1/admin/users",
            self._headers(service=True),
            {
                "email": email,
                "password": password,
                "email_confirm": email_confirm,
                "user_metadata": {"username": username},
            },
        )
        return body

    def admin_delete_user(self, user_id: str):
        _call("DELETE", f"{self.url}/auth/v1/admin/users/{user_id}", self._headers(service=True))

    # ---------------- Rest ----------------
    def select(self, table: str, params: dict = None, token: str = None):
        q = urllib.parse.urlencode(params or {})
        _, body = _call(
            "GET",
            f"{self.url}/rest/v1/{table}?{q}",
            self._headers(token=token, service=token is None),
        )
        return body

    def select_all(self, table: str, params: dict = None, page: int = 1000):
        rows = []
        offset = 0
        while True:
            batch = self.select(
                table,
                {**(params or {}), "limit": page, "offset": offset},
            ) or []
            rows.extend(batch)
            if len(batch) < page:
                return rows
            offset += page

    def upsert(self, table: str, rows: list, on_conflict: str, batch: int = 500):
        if not rows:
            return 0
        query = urllib.parse.urlencode({"on_conflict": on_conflict})
        headers = self._headers(
            service=True,
            extra={"Prefer": "resolution=merge-duplicates,return=minimal"},
        )
        for start in range(0, len(rows), batch):
            _call(
                "POST",
                f"{self.url}/rest/v1/{table}?{query}",
                headers,
                rows[start:start + batch],
                timeout=120,
            )
        return len(rows)

    def update(self, table: str, match: dict, values: dict, token: str = None):
        q = urllib.parse.urlencode(match)
        _, body = _call(
            "PATCH",
            f"{self.url}/rest/v1/{table}?{q}",
            self._headers(token=token, service=token is None, extra={"Prefer": "return=representation"}),
            values,
        )
        return body

    def insert(self, table: str, rows: list, token: str = None):
        _, body = _call(
            "POST",
            f"{self.url}/rest/v1/{table}",
            self._headers(token=token, service=token is None, extra={"Prefer": "return=representation"}),
            rows,
        )
        return body

    def rpc(self, name: str, args: dict = None, token: str = None):
        """Call a Postgres function through Supabase REST (PostgREST RPC)."""
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError("Invalid Supabase RPC function name")
        _, body = _call(
            "POST",
            f"{self.url}/rest/v1/rpc/{name}",
            self._headers(token=token, service=token is None),
            args or {},
        )
        return body

    def upload_storage_object(self, bucket: str, path: str, content: bytes, content_type: str):
        """Upload binary content with the service role; never return the key to clients."""
        bucket_path = urllib.parse.quote(bucket, safe="")
        object_path = urllib.parse.quote(path, safe="/")
        req = urllib.request.Request(
            f"{self.url}/storage/v1/object/{bucket_path}/{object_path}",
            data=content,
            method="POST",
            headers={
                **self._headers(service=True),
                "Content-Type": content_type,
                "x-upsert": "true",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                body = json.loads(raw)
            except ValueError:
                body = {"message": raw.decode(errors="replace")}
            raise SupabaseError(exc.code, body) from None

_default_sb = None

def get_supabase() -> Supabase:
    global _default_sb
    if _default_sb is None:
        _default_sb = Supabase()
    return _default_sb

"""Quản lý tài khoản (BTC dùng). Chạy từ thư mục gốc dự án:

  python -m data.manage check                         # kiểm tra kết nối Supabase
  python -m data.manage create-user NAME PASSWORD [--admin]
  python -m data.manage import-users users.csv        # mỗi dòng: username,password
  python -m data.manage set-status NAME active|out|banned|new
  python -m data.manage set-admin NAME
"""
import argparse
import csv
import sys

from . import auth_service
from .supabase_client import SupabaseError


def _profile(name):
    rows = auth_service.sb().select("profiles", {"username": f"ilike.{name}", "select": "id,username,role,status"})
    if not rows:
        raise SystemExit(f"Không có user {name}")
    return rows[0]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "create-user", "import-users", "set-status", "set-admin"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--admin", action="store_true")
    a = ap.parse_args(argv)
    import tournament as T
    T.init()

    if a.cmd == "check":
        n = len(auth_service.sb().select("tournament_state", {"select": "id"}))
        print("OK: kết nối Supabase, tournament_state có", n, "dòng")
    elif a.cmd == "create-user":
        name, pw = a.args
        print(auth_service.create_account(name, pw, admin=a.admin))
    elif a.cmd == "import-users":
        ok = bad = 0
        with open(a.args[0], newline="", encoding="utf-8") as f:
            for row in csv.reader(f):
                if len(row) < 2 or row[0].lower() == "username":
                    continue
                try:
                    auth_service.create_account(row[0].strip(), row[1].strip())
                    ok += 1
                except (ValueError, SupabaseError) as e:
                    bad += 1
                    print(f"  {row[0]}: {e}", file=sys.stderr)
        print(f"Tạo {ok} tài khoản, lỗi {bad}")
    elif a.cmd == "set-status":
        name, status = a.args
        p = _profile(name)
        auth_service.sb().update("profiles", {"id": f"eq.{p['id']}"}, {"status": status})
        print(f"{p['username']} -> {status}")
    elif a.cmd == "set-admin":
        p = _profile(a.args[0])
        auth_service.sb().update("profiles", {"id": f"eq.{p['id']}"}, {"role": "admin"})
        print(f"{p['username']} -> admin")


if __name__ == "__main__":
    main()

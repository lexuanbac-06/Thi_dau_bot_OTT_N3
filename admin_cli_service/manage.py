"""CLI Quản lý tài khoản Admin và hệ thống thi đấu.
Cách dùng:
  .venv/bin/python -m admin_cli_service.manage check
  .venv/bin/python -m admin_cli_service.manage create-admin email@example.com username MatKhau123
  .venv/bin/python -m admin_cli_service.manage import-admins admins_sample.csv
  .venv/bin/python -m admin_cli_service.manage set-admin username
"""
import argparse
import sys
from pathlib import Path

from . import admin_service
from data.supabase_client import get_supabase

def cmd_check():
    sb = get_supabase()
    try:
        profiles = sb.select("profiles", {"select": "id,username,role", "limit": "5"})
        print(f"✓ Kết nối Supabase thành công! (Tìm thấy {len(profiles)} profiles mẫu)")
    except Exception as exc:
        print(f"✗ Lỗi kết nối Supabase: {exc}", file=sys.stderr)
        return 1

    return 0

def cmd_create_admin(email: str, username: str, password: str):
    try:
        res = admin_service.create_admin_account(email, username, password)
        print(f"✓ Tạo thành công Admin: ID={res['id']}, Email={res['email']}, Username={res['username']}")
        return 0
    except Exception as exc:
        print(f"✗ Thất bại: {exc}", file=sys.stderr)
        return 1

def cmd_import_admins(file_path: str):
    p = Path(file_path)
    if not p.is_file():
        print(f"✗ File không tồn tại: {file_path}", file=sys.stderr)
        return 1
    content = p.read_text(encoding="utf-8")
    res = admin_service.import_admins_from_csv(content)
    print(f"\n--- KẾT QUẢ IMPORT ADMINS ---")
    print(f"Thành công: {res['success_count']} tài khoản")
    for adm in res["created"]:
        print(f"  + {adm['username']} ({adm['email']})")
    
    if res["error_count"] > 0:
        print(f"Lỗi: {res['error_count']} dòng")
        for err in res["errors"]:
            print(f"  - Dòng {err.get('row')}: {err.get('error')}")
    return 0 if res["error_count"] == 0 else 1

def cmd_set_admin(username: str):
    sb = get_supabase()
    rows = sb.select("profiles", {"username": f"ilike.{username}", "limit": "1"})
    if not rows:
        print(f"✗ Không tìm thấy profile với username: {username}", file=sys.stderr)
        return 1
    uid = rows[0]["id"]
    sb.update("profiles", {"id": f"eq.{uid}"}, {"role": "admin"})
    print(f"✓ Đã nâng tài khoản '{username}' thành admin.")
    return 0

def main():
    parser = argparse.ArgumentParser(description="Quản trị OTT Arena Backend")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("check", help="Kiểm tra kết nối Supabase")

    p_create = subparsers.add_parser("create-admin", help="Tạo tài khoản Admin")
    p_create.add_argument("email", help="Email của Admin")
    p_create.add_argument("username", help="Username của Admin (3-20 ký tự)")
    p_create.add_argument("password", help="Mật khẩu của Admin (tối thiểu 8 ký tự)")

    p_import = subparsers.add_parser("import-admins", help="Import danh sách Admin từ file CSV")
    p_import.add_argument("file", help="Đường dẫn tới file CSV (email,username,password)")

    p_set = subparsers.add_parser("set-admin", help="Nâng một tài khoản sẵn có thành Admin")
    p_set.add_argument("username", help="Username cần nâng quyền Admin")

    args = parser.parse_args()

    if args.command == "check":
        sys.exit(cmd_check())
    elif args.command == "create-admin":
        sys.exit(cmd_create_admin(args.email, args.username, args.password))
    elif args.command == "import-admins":
        sys.exit(cmd_import_admins(args.file))
    elif args.command == "set-admin":
        sys.exit(cmd_set_admin(args.username))

if __name__ == "__main__":
    main()

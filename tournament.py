"""Read-only Supabase tournament status CLI.

Official tournament actions are handled by the admin web interface and the
self-hosted scoring module. This CLI intentionally has no SQLite write path.
"""
import json
import sys

from data.supabase_client import get_supabase


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args not in ([], ["status"]):
        raise SystemExit(
            "CLI vận hành SQLite đã được gỡ. Dùng /admin để điều hành giải; "
            "chỉ lệnh `python tournament.py status` còn được hỗ trợ."
        )
    rows = get_supabase().select("tournament_state", {"select": "*", "id": "eq.1", "limit": "1"})
    if not rows:
        raise SystemExit("Không tìm thấy tournament_state trên Supabase; hãy áp dụng migration.")
    print(json.dumps(rows[0], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

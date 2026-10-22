"""Đồng bộ dữ liệu chấm (ott.db, SQLite) -> Supabase, và xuất replay ra file local.

Idempotent: chạy lại bao nhiêu lần cũng được (upsert). Chạy từ thư mục gốc dự án:
  python -m data.sync                 # đồng bộ tất cả
  python -m data.sync --no-replays    # bỏ qua xuất replay (nhanh hơn)
  python -m data.sync --only matches,daily

Tự chạy sau entry-close / close / grade nếu đặt OTT_SUPABASE_SYNC=1 (xem tournament._publish).
Tài khoản có trong ott.db nhưng chưa có trên Supabase (vd. bot BTC thêm bằng add-bot) sẽ bị bỏ qua + cảnh báo.
"""
import argparse
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone

from . import config, replay_store
from .supabase_client import Supabase

STEPS = ["profiles", "config", "state", "members", "days", "submissions", "daily",
         "replays", "matches", "advancement"]


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


class Sync:
    def __init__(self, T, sb=None, con=None, replay_base=None):
        self.T = T                                  # module tournament (CFG, DAYS, MIN_DAYS, MATCHES, DB, SNAP)
        self.sb = sb or Supabase()
        self.con = con or sqlite3.connect(os.environ.get("OTT_DB", T.DB))
        self.con.row_factory = sqlite3.Row
        self.replay_base = replay_base
        self.uid = {}                               # username.lower() -> uuid
        self.uname = {}                             # username.lower() -> username chuẩn
        self.skipped = set()
        self.meta = {r["k"]: r["v"] for r in self.con.execute("select k,v from meta")}

    # ---- helpers
    def _id(self, name):
        i = self.uid.get(name.lower())
        if i is None:
            self.skipped.add(name)
        return i

    def _rows(self, sql, args=()):
        return self.con.execute(sql, args).fetchall()

    def _rounds_with_members(self):
        return sorted(r[0] for r in self._rows("select distinct rnd from member"))

    # ---- các bước
    def profiles(self):
        banned = set()
        for p in self.sb.select_all("profiles", {"select": "id,username,status"}):
            self.uid[p["username"].lower()] = p["id"]
            self.uname[p["username"].lower()] = p["username"]
            if p["status"] == "banned":
                banned.add(p["id"])
        rows = []
        for u in self._rows("select name,entry,status from users"):
            i = self._id(u["name"])
            if i:
                rows.append({"id": i, "username": self.uname[u["name"].lower()],
                             "status": "banned" if i in banned else (u["status"] or "new"),
                             "entry_score": u["entry"]})
        return self.sb.upsert("profiles", rows, "id")

    def config(self):
        T = self.T
        n = len(T.CFG["rounds"])
        rows = [{"rnd": i + 1, "num_groups": c["groups"], "top_n": c["top"], "wildcard_n": c["wildcard"],
                 "days": T.DAYS, "min_days": T.MIN_DAYS, "matches_per_day": T.MATCHES,
                 "is_offline": i == n - 1} for i, c in enumerate(T.CFG["rounds"])]
        return self.sb.upsert("round_config", rows, "rnd")

    def state(self):
        m = self.meta
        champ = self._id(m["champion"]) if m.get("champion") else None
        row = {"id": 1, "phase": m.get("phase", "entry"), "current_round": int(m.get("round") or 0),
               "current_day": int(m.get("day") or 0), "pending_day": int(m.get("pending") or 0),
               "accepting_submissions": m.get("accepting_submissions", "1") == "1",
               "champion_id": champ, "updated_at": datetime.now(timezone.utc).isoformat()}
        return self.sb.upsert("tournament_state", [row], "id")

    def members(self):
        rows = []
        for r in self._rows("select rnd,name,grp,seed from member"):
            i = self._id(r["name"])
            if i:
                rows.append({"rnd": r["rnd"], "user_id": i, "grp": r["grp"], "seed": r["seed"]})
        return self.sb.upsert("round_members", rows, "rnd,user_id")

    def days(self):
        m = self.meta
        cur_rnd, cur_day, pending = int(m.get("round") or 0), int(m.get("day") or 0), int(m.get("pending") or 0)
        try:
            running = json.loads(m.get("live_scoring") or "{}").get("state") == "running"
        except ValueError:
            running = False
        graded = {(r["rnd"], r["day"]) for r in self._rows("select distinct rnd,day from daily")}
        counts = {(r["rnd"], r["day"]): r["c"] for r in self._rows("select rnd,day,count(*) c from matches group by rnd,day")}
        existing = {(r["rnd"], r["day"]): r["state"] for r in self.sb.select_all("contest_days", {"select": "rnd,day,state"})}
        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for rnd in self._rounds_with_members():
            for day in range(1, self.T.DAYS + 1):
                k = (rnd, day)
                if k in graded:
                    st = "graded"
                elif rnd == cur_rnd and day == pending:
                    st = "grading" if running else "closed"
                elif rnd == cur_rnd and day == cur_day and m.get("phase") == "round":
                    st = "open"
                else:
                    continue
                row = {"rnd": rnd, "day": day, "state": st, "total_matches": counts.get(k)}
                if st != "open" and existing.get(k) in (None, "open"):
                    row["closed_at"] = now
                if st == "graded" and existing.get(k) != "graded":
                    row["graded_at"] = now
                rows.append(row)
        return self._upsert_uniform("contest_days", rows, "rnd,day")

    def _upsert_uniform(self, table, rows, conflict):
        """PostgREST yêu cầu mọi dòng trong 1 lô có cùng tập khóa -> gom theo tập khóa."""
        groups = {}
        for r in rows:
            groups.setdefault(tuple(sorted(r)), []).append(r)
        return sum(self.sb.upsert(table, g, conflict) for g in groups.values())

    def submissions(self):
        rows = []
        for s in self._rows("select name,rnd,day,ts from subs"):
            i = self._id(s["name"])
            if not i:
                continue
            row = {"user_id": i, "rnd": s["rnd"], "day": s["day"], "submitted_at": _iso(s["ts"])}
            snap = os.path.join(self.T.SNAP, f"r{s['rnd']}", f"d{s['day']}", f"{s['name']}.py")
            if os.path.isfile(snap):
                with open(snap, "rb") as f:
                    b = f.read()
                row["sha256"], row["size_bytes"] = hashlib.sha256(b).hexdigest(), len(b)
            rows.append(row)
        return self._upsert_uniform("submissions", rows, "user_id,rnd,day")

    def daily(self):
        rows = []
        for d in self._rows("select rnd,day,grp,name,pts,gs,rank,n from daily"):
            i = self._id(d["name"])
            if i:
                rows.append({"rnd": d["rnd"], "day": d["day"], "user_id": i, "grp": d["grp"], "pts": d["pts"],
                             "gs": d["gs"], "rank": d["rank"], "group_size": d["n"]})
        return self.sb.upsert("daily_results", rows, "rnd,day,user_id")

    def _grp_of(self):
        return {(r["rnd"], r["name"]): r["grp"] for r in self._rows("select rnd,name,grp from member")}

    def replays(self):
        """Xuất match_replays (SQLite) -> file gzip local. Bỏ qua file đã có."""
        grp, written = self._grp_of(), 0
        cur = self.con.execute("select rnd,day,rd,a,b,games from match_replays")
        for r in cur:
            g = grp.get((r["rnd"], r["a"]))
            if g is None:
                continue
            _, w = replay_store.save(r["rnd"], r["day"], g, r["rd"], r["a"], r["b"], r["games"], self.replay_base)
            written += w
        return written

    def matches(self):
        grp = self._grp_of()
        has = {(r["rnd"], r["day"], r["rd"], r["a"], r["b"]) for r in self._rows("select rnd,day,rd,a,b from match_replays")}
        rows = []
        for m in self._rows("select rnd,day,rd,a,b,s from matches"):
            ia, ib, g = self._id(m["a"]), self._id(m["b"]), grp.get((m["rnd"], m["a"]))
            if ia and ib and g is not None:
                rows.append({"rnd": m["rnd"], "day": m["day"], "rd": m["rd"], "grp": g, "player_a": ia, "player_b": ib,
                             "score_a": m["s"], "has_replay": (m["rnd"], m["day"], m["rd"], m["a"], m["b"]) in has})
        return self.sb.upsert("matches", rows, "rnd,day,rd,player_a,player_b")

    def advancement(self):
        """Suy ra từ BXH ngày cuối: top / wildcard (có mặt ở vòng sau) / eliminated / ineligible."""
        T, rows = self.T, []
        members = {}
        for r in self._rows("select rnd,name from member"):
            members.setdefault(r["rnd"], set()).add(r["name"])
        for rnd, names in members.items():
            final = {r["name"]: r["rank"] for r in self._rows("select name,rank from daily where rnd=? and day=?", (rnd, T.DAYS))}
            if not final:
                continue
            top = T.CFG["rounds"][rnd - 1]["top"]
            pct = {}
            for r in self._rows("select name,rank,n from daily where rnd=? and day<?", (rnd, T.DAYS)):
                pct.setdefault(r["name"], []).append((r["rank"] - 1) / r["n"])
            nxt = members.get(rnd + 1, set())
            for n in names:
                i = self._id(n)
                if not i:
                    continue
                if n not in final:
                    route = "ineligible"
                elif final[n] <= top:
                    route = "top"
                elif n in nxt:
                    route = "wildcard"
                else:
                    route = "eliminated"
                rows.append({"rnd": rnd, "user_id": i, "route": route, "final_rank": final.get(n),
                             "avg_rank_pct": sum(pct[n]) / len(pct[n]) if n in pct else None})
        return self._upsert_uniform("round_advancement", rows, "rnd,user_id")

    def run(self, only=None, replays=True):
        out = {}
        for step in STEPS:
            if (only and step not in only) or (step == "replays" and not replays):
                continue
            out[step] = getattr(self, step)()
        if self.skipped:
            print(f"[sync] Bỏ qua {len(self.skipped)} tài khoản chưa có trên Supabase: "
                  f"{', '.join(sorted(self.skipped)[:10])}{'...' if len(self.skipped) > 10 else ''}")
        return out


def run(only=None, replays=True):
    import tournament as T
    return Sync(T).run(only, replays)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", help="danh sách bước, cách nhau bởi dấu phẩy: " + ",".join(STEPS))
    ap.add_argument("--no-replays", action="store_true")
    a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else None
    print(run(only, not a.no_replays))


if __name__ == "__main__":
    main()

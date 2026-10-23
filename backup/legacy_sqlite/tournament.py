"""OTTv2 tournament: đăng ký, thi đầu vào, chia bảng, chấm ngày (Swiss 7 trận), vé vớt, lên vòng.

CLI (BTC dùng):
  python tournament.py entry-close      # chốt thi đầu vào: chấm vs bot BTC, loại, chia bảng
  python tournament.py close            # 00:00: chốt hạn nộp, snapshot bài, sang ngày mới
  python tournament.py grade            # 01:00: chấm ngày vừa chốt (nếu là ngày 7 -> xét lên vòng)
  python tournament.py run-day          # close + grade (tiện test)
  python tournament.py status
  python tournament.py add-bot NAME FILE   # BTC nhập bài hộ (dùng cho vòng offline)
  python tournament.py demo N              # tạo N thí sinh giả để thử cả quy trình
"""
import os, re, sys, time, random, shutil, secrets, sqlite3, argparse, json, math
from datetime import datetime, timezone
from multiprocessing import Pool
import engine

DB, BOT_DIR, SNAP = "ott.db", "bots", "snaps"
LIVE_BOARD_SNAPSHOT = os.path.join(
    os.path.dirname(__file__), "static", "live-board.json"
)
DAYS, MIN_DAYS, MATCHES = 7, 4, 7         # 6 ngày thường + ngày cuối; nộp >=4/6 ngày mới được đấu ngày cuối
CFG = dict(
    entry_cut=-2,                         # entry < entry_cut => loại. entry = 1*s0 + 2*s1 + 3*s2, mỗi s thuộc [-2,2]
    entry_weights=[1, 2, 3],
    workers=min(os.cpu_count() or 4, 60),   # Windows tối đa 61
    rounds=[                              # groups: số bảng; top: top mỗi bảng đi tiếp; wildcard: vé vớt toàn vòng
        dict(groups=1, top=10, wildcard=40),
        dict(groups=16, top=8, wildcard=16),
        dict(groups=8, top=6, wildcard=8),
        dict(groups=4, top=4, wildcard=4),
        dict(groups=1, top=1, wildcard=0),   # vòng 5: offline
    ])
LIVE_SCORE_PERSIST_BATCH = 25


def _play_indexed_match(args):
    index, match_args = args
    return index, engine.play_match_recorded(match_args)

if os.environ.get("OTT_TEST"):      # chế độ thử: 1 bảng, 1 vòng, 3 ngày, 3 trận/ngày, không loại ai ở đầu vào
    DAYS, MIN_DAYS, MATCHES = 3, 0, 3
    CFG["entry_cut"] = -99
    CFG["rounds"] = [dict(groups=1, top=1, wildcard=0)]

SCHEMA = """
create table if not exists users(name text primary key, token text, entry real, status text default 'new');
create table if not exists subs(name text, rnd int, day int, ts real, primary key(name,rnd,day));
create table if not exists meta(k text primary key, v text);
create table if not exists member(rnd int, name text, grp int, seed int, primary key(rnd,name));
create table if not exists daily(rnd int, day int, grp int, name text, pts int, gs int, rank int, n int, primary key(rnd,day,name));
create table if not exists live_scores(
    id integer primary key autoincrement,
    event text not null,
    name text not null,
    score real not null,
    updated_at text not null,
    unique(event,name)
);
create table if not exists matches(rnd int, day int, rd int, a text, b text, s int);
create index if not exists idx_matches_round_day on matches(rnd,day);
create index if not exists idx_member_round_group_seed on member(rnd,grp,seed);
create table if not exists match_replays(
    rnd int, day int, rd int, a text, b text, games text,
    primary key(rnd,day,rd,a,b)
);
"""


def q(sql, args=()):
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        r = c.execute(sql, args).fetchall(); c.commit(); return r
    finally:
        c.close()


def qm(sql, rows):
    c = sqlite3.connect(DB, timeout=30)
    try:
        c.executemany(sql, rows); c.commit()
    finally:
        c.close()


def init():
    c = sqlite3.connect(DB)
    c.execute("pragma journal_mode=wal")
    c.executescript(SCHEMA)
    c.commit()
    c.close()


def _publish(event):
    """Đẩy kết quả lên Supabase (data/sync.py) khi OTT_SUPABASE_SYNC=1. Lỗi mạng không làm hỏng việc chấm."""
    if os.environ.get("OTT_SUPABASE_SYNC") != "1":
        return
    try:
        from data import sync
        sync.run()
        print(f"[sync] Đã đồng bộ Supabase sau {event}")
    except Exception as exc:
        print(f"[sync] Lỗi đồng bộ sau {event}: {exc!r} (chạy lại: python -m data.sync)")


def reset_tournament():
    c = sqlite3.connect(DB, timeout=30)
    try:
        c.execute("BEGIN IMMEDIATE")
        for table in ("match_replays", "matches", "daily", "member", "subs", "users", "meta"):
            c.execute(f'DELETE FROM "{table}"')
        c.executemany(
            "insert into meta(k,v) values(?,?)",
            [
                ("phase", "entry"),
                ("round", "0"),
                ("day", "0"),
                ("pending", "0"),
                ("accepting_submissions", "1"),
            ],
        )
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

    for path in (BOT_DIR, SNAP):
        if not os.path.exists(path):
            continue
        if not os.path.isdir(path) or os.path.islink(path):
            raise OSError(f"Không thể reset thư mục dữ liệu không hợp lệ: {path}")
        for entry in os.scandir(path):
            if entry.is_dir(follow_symlinks=False):
                shutil.rmtree(entry.path)
            else:
                os.unlink(entry.path)


def get(k, d=None):
    r = q("select v from meta where k=?", (k,))
    return r[0][0] if r else d


def put(k, v):
    q("insert or replace into meta values(?,?)", (k, str(v)))


# ---------------- ĐĂNG KÝ / NỘP BÀI ----------------
def register(name):
    if not re.fullmatch(r"[A-Za-z0-9_]{3,20}", name):
        raise ValueError("Tên 3-20 ký tự A-Z a-z 0-9 _")
    if q("select 1 from users where name=?", (name,)):
        raise ValueError("Tên đã tồn tại")
    tok = secrets.token_hex(16)
    q("insert into users(name,token) values(?,?)", (name, tok))
    return tok


def user_by_token(tok):
    r = q("select * from users where token=?", (tok or "",))
    return r[0] if r else None


def latest(name):
    p = os.path.join(BOT_DIR, name, "latest.py")
    return p if os.path.exists(p) else None


def submit(name, src, allow_eval=False):
    ph = get("phase", "entry")
    if ph not in ("entry", "round"):
        raise ValueError("Cuộc thi không nhận bài lúc này")
    if get("accepting_submissions", "1") != "1":
        raise ValueError("Ban tổ chức đang tạm đóng nhận bài")
    rows = q("select status from users where name=?", (name,))
    if not rows:
        q("insert or ignore into users(name, token, status) values(?, ?, 'new')", (name, secrets.token_hex(16)))
        rows = q("select status from users where name=?", (name,))
    u = rows[0]
    if ph == "round" and u["status"] != "active":
        competed = q("select 1 from member where name=? limit 1", (name,))
        if competed:
            raise ValueError("Bạn đã bị loại khỏi cuộc thi ở vòng trước.")
        if not allow_eval:
            raise ValueError(
                "Bạn chưa đủ điều kiện qua vòng đầu vào (chưa nộp bot hoặc không đạt điểm yêu cầu), "
                "nên không thể tiếp tục cuộc thi."
            )
    if len(src) > 65536:
        raise ValueError("File quá lớn (>64KB)")
    compile(src, "bot", "exec")                      # kiểm tra cú pháp, KHÔNG chạy
    last = q("select max(ts) t from subs where name=?", (name,))[0]["t"]
    if last and time.time() - last < 3:
        raise ValueError("Nộp quá nhanh, vui lòng chờ vài giây")
    d = os.path.join(BOT_DIR, name); os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "latest.py"), "wb") as f:
        f.write(src)
    rnd, day = (0, 0) if ph == "entry" else (int(get("round")), int(get("day")))
    q("insert or replace into subs values(?,?,?,?)", (name, rnd, day, time.time()))


# ---------------- CHIA BẢNG ----------------
def split_groups(names_sorted, G):
    """names_sorted: mạnh -> yếu. Cắt thành các nhóm G người cùng trình độ, mỗi nhóm rải đều vào G bảng."""
    res = {}
    for i in range(0, len(names_sorted), G):
        chunk = names_sorted[i:i + G]
        for n, g in zip(chunk, random.sample(range(G), len(chunk))):
            res[n] = g
    return res


def seat(rnd, ordered):
    G = CFG["rounds"][rnd - 1]["groups"]
    a = split_groups(ordered, G)
    qm("insert or replace into member values(?,?,?,?)", [(rnd, n, a[n], i) for i, n in enumerate(ordered)])


def entry_close():
    names = [r["name"] for r in q("select name from users")]
    tasks, idx = [], []
    for n in names:
        p = latest(n)
        if p:
            for i in range(3):
                tasks.append((p, f"entry:{i}")); idx.append((n, i))
    with Pool(CFG["workers"]) as pool:
        res = pool.map(engine.play_match, tasks, chunksize=2)
    sc = {}
    for (n, i), s in zip(idx, res):
        sc[n] = sc.get(n, 0) + CFG["entry_weights"][i] * s
    alive = [n for n in names if n in sc and sc[n] >= CFG["entry_cut"]]
    random.shuffle(alive)
    alive.sort(key=lambda n: -sc[n])
    qm("update users set entry=?, status=? where name=?",
       [(sc.get(n), "active" if n in alive else "out", n) for n in names])
    seat(1, alive)
    put("phase", "round"); put("round", 1); put("day", 1); put("pending", 0)
    print(f"Đầu vào: {len(names)} đăng ký, {len(sc)} có bài, {len(alive)} đi tiếp.")


# ---------------- NGÀY ----------------
def close_day():
    """Chạy đúng 00:00: chốt hạn nộp, snapshot bài của mọi thí sinh còn thi."""
    rnd, day = int(get("round")), int(get("day"))
    if int(get("pending", 0)):
        raise SystemExit("Còn ngày chưa chấm, chạy grade trước")
    d = f"{SNAP}/r{rnd}/d{day}"; os.makedirs(d, exist_ok=True)
    for r in q("select name from member where rnd=?", (rnd,)):
        p = latest(r["name"])
        if p:
            shutil.copy(p, f"{d}/{r['name']}.py")
    put("pending", day); put("day", day + 1)
    print(f"Đã chốt vòng {rnd} ngày {day}")


def make_pairs(st, rd):
    order, bye = list(st["order"]), None
    if len(order) % 2:                                    # bye cho người hạng thấp nhất chưa từng bye
        bye = next((n for n in reversed(order) if n not in st["byes"]), order[-1])
        order.remove(bye)
    if rd == 0:                                           # nửa trên đấu nửa dưới
        h = len(order) // 2
        return [(order[i], order[i + h]) for i in range(h)], bye
    order.sort(key=lambda n: -st["pts"][n])               # ổn định: cùng điểm giữ thứ tự xếp hạng ban đầu
    pairs = []
    while order:
        a = order.pop(0)
        i = next((i for i, b in enumerate(order) if frozenset((a, b)) not in st["played"]), 0)
        pairs.append((a, order.pop(i)))
    return pairs, bye


def grade_day():
    rnd, day = int(get("round")), int(get("pending", 0))
    if not day:
        raise SystemExit("Không có ngày nào chờ chấm")
    mem = q("select name,grp,seed from member where rnd=?", (rnd,))
    seed = {r["name"]: r["seed"] for r in mem}
    hist = {}
    for r in q("select name,rank from daily where rnd=? and day<?", (rnd, day)):
        hist.setdefault(r["name"], []).append(r["rank"])
    cnt = {r["name"]: r["c"] for r in q("select name,count(*) c from subs where rnd=? and day<? group by name", (rnd, DAYS))}
    groups = {}
    for r in mem:
        groups.setdefault(r["grp"], []).append(r["name"])
    S = {}
    for g, names in groups.items():
        if day == DAYS:
            names = [n for n in names if cnt.get(n, 0) >= MIN_DAYS]
        names.sort(key=lambda n: (sum(hist[n]) / len(hist[n]) if n in hist else 0, seed[n]))
        S[g] = dict(order=names, pts={n: 0 for n in names}, gs={n: 0 for n in names}, played=set(), byes=set())

    total_matches = sum(len(st["order"]) // 2 for st in S.values()) * MATCHES
    q("delete from matches where rnd=? and day=?", (rnd, day))
    q("delete from match_replays where rnd=? and day=?", (rnd, day))
    progress = {
        "state": "running",
        "round": rnd,
        "day": day,
        "completed_rounds": 0,
        "total_rounds": MATCHES,
        "completed_matches": 0,
        "total_matches": total_matches,
    }
    put("live_scoring", json.dumps(progress))
    put("live_scoring_queue", "[]")
    put("live_scoring_completed", "[]")
    last_snapshot = 0.0

    def spec(n):
        p = f"{SNAP}/r{rnd}/d{day}/{n}.py"
        return p if os.path.exists(p) else None

    with Pool(CFG["workers"]) as pool:
        for rd in range(MATCHES):
            todo = []
            pending_matches = []
            pending_replays = []
            last_persist = time.monotonic()
            for g, st in S.items():
                pairs, bye = make_pairs(st, rd)
                if bye:
                    st["byes"].add(bye)
                todo += [(g, a, b) for a, b in pairs]
            queue = [
                {"group": group, "a": player_a, "b": player_b}
                for group, player_a, player_b in todo
            ]
            completed_queue_positions = []
            put("live_scoring_queue", json.dumps(queue))
            put("live_scoring_completed", "[]")
            progress["current_round"] = rd + 1
            progress["current_matches"] = len(todo)
            publish_queue = True
            real = [i for i, (g, a, b) in enumerate(todo) if spec(a) and spec(b)]
            def record_result(i, s, games=None):
                nonlocal last_persist
                g, a, b = todo[i]
                m = (s > 0) - (s < 0)
                st = S[g]
                st["pts"][a] += m; st["pts"][b] -= m; st["gs"][a] += s; st["gs"][b] -= s
                st["played"].add(frozenset((a, b)))
                pending_matches.append((rnd, day, rd + 1, a, b, s))
                if games is not None:
                    pending_replays.append((rnd, day, rd + 1, a, b, json.dumps(games)))
                progress["completed_matches"] += 1
                completed_queue_positions.append(i)

            def persist_progress(round_complete=False):
                nonlocal last_persist, last_snapshot, publish_queue
                if pending_matches:
                    qm("insert into matches values(?,?,?,?,?,?)", pending_matches)
                    qm("insert or replace into match_replays values(?,?,?,?,?,?)", pending_replays)
                    pending_matches.clear()
                    pending_replays.clear()
                if round_complete:
                    progress["completed_rounds"] = rd + 1
                put(
                    "live_scoring_completed",
                    json.dumps(sorted(completed_queue_positions)),
                )
                put("live_scoring", json.dumps(progress))
                last_persist = time.monotonic()
                if (
                    publish_queue
                    or round_complete
                    or time.monotonic() - last_snapshot >= 20
                ):
                    publish_live_tournament_snapshot()
                    last_snapshot = time.monotonic()
                    publish_queue = False

            persist_progress()

            for i, (g, a, b) in enumerate(todo):
                if i not in real:
                    s = 0 if not spec(a) and not spec(b) else (-2 if not spec(a) else 2)
                    record_result(i, s)

            indexed_args = (
                (i, (spec(todo[i][1]), spec(todo[i][2])))
                for i in real
            )
            for i, result in pool.imap_unordered(
                _play_indexed_match, indexed_args, chunksize=1
            ):
                s, games = result
                record_result(i, s, games)
                now = time.monotonic()
                if (
                    len(pending_matches) >= LIVE_SCORE_PERSIST_BATCH
                    or now - last_persist >= 1
                ):
                    persist_progress()

            persist_progress(round_complete=True)
            print(f"  trận {rd + 1}/{MATCHES} xong ({len(todo)} cặp)")
    rows = []
    for g, st in S.items():
        rk = sorted(st["order"], key=lambda n: (-st["pts"][n], -st["gs"][n], st["order"].index(n)))
        rows += [(rnd, day, g, n, st["pts"][n], st["gs"][n], i + 1, len(rk)) for i, n in enumerate(rk)]
    qm("insert or replace into daily values(?,?,?,?,?,?,?,?)", rows)
    put("pending", 0)
    progress["state"] = "complete"
    put("live_scoring", json.dumps(progress))
    put("live_scoring_queue", "[]")
    put("live_scoring_completed", "[]")
    publish_live_tournament_snapshot()
    print(f"Đã chấm vòng {rnd} ngày {day}")
    if day == DAYS:
        advance(rnd)


def advance(rnd):
    cfg = CFG["rounds"][rnd - 1]
    final = q("select name,rank from daily where rnd=? and day=?", (rnd, DAYS))
    top = {r["name"] for r in final if r["rank"] <= cfg["top"]}
    pct = {}
    for r in q("select name,day,rank,n from daily where rnd=?", (rnd,)):
        pct.setdefault(r["name"], {})[r["day"]] = (r["rank"] - 1) / r["n"]
    elig = {r["name"] for r in final}
    # vé vớt: thứ hạng (phần trăm) trung bình tốt nhất ở 6 ngày thường, trong số người đủ điều kiện nhưng chưa đi tiếp
    cand = sorted((n for n in pct if n in elig and n not in top),
                  key=lambda n: sum(v for d, v in pct[n].items() if d < DAYS) / (DAYS - 1))
    surv = top | set(cand[:cfg["wildcard"]])
    allm = [r["name"] for r in q("select name from member where rnd=?", (rnd,))]
    qm("update users set status=? where name=?", [("active" if n in surv else "out", n) for n in allm])
    strength = {n: sum(pct[n].values()) / len(pct[n]) for n in surv}
    ordered = sorted(surv, key=lambda n: strength[n])
    print(f"Vòng {rnd}: {len(surv)} người đi tiếp ({len(top)} top + {len(surv) - len(top)} vé vớt)")
    if rnd == len(CFG["rounds"]):
        champion = next((r["name"] for r in final if r["rank"] == 1), None)
        if champion is not None:
            put("champion", champion)
        else:
            q("delete from meta where k='champion'")
        put("phase", "done")
        return
    seat(rnd + 1, ordered)
    put("round", rnd + 1); put("day", 1)


# ---------------- TRUY VẤN CHO SERVER ----------------
def my_status(name):
    u = q("select status,entry from users where name=?", (name,))[0]
    out = dict(name=name, status=u["status"], entry=u["entry"], phase=get("phase", "entry"),
               round=get("round"), open_day=get("day"))
    m = q("select grp from member where rnd=? and name=?", (int(get("round", 0) or 0), name))
    if m:
        out["group"] = m[0]["grp"]
        rows = q("select day,pts,rank,n from daily where rnd=? and name=? order by day", (int(get("round")), name))
        out["days"] = [dict(r) for r in rows]
        out["avg_rank"] = round(sum(r["rank"] for r in rows) / len(rows), 2) if rows else None
    return out


def leaderboard(name, day=None):
    rnd = int(get("round", 0) or 0)
    m = q("select grp from member where rnd=? and name=?", (rnd, name))
    if not m:
        return []
    if day is None:
        d = q("select max(day) d from daily where rnd=? and grp=?", (rnd, m[0]["grp"]))[0]["d"]
        day = d or 0
    return [dict(r) for r in q("select rank,name,pts,gs from daily where rnd=? and day=? and grp=? order by rank",
                               (rnd, day, m[0]["grp"]))]


def live_tournament_board():
    raw_progress = get("live_scoring")
    if not raw_progress:
        return {
            "state": "idle",
            "round": int(get("round", 0) or 0) or None,
            "day": None,
            "completed_rounds": 0,
            "total_rounds": MATCHES,
            "completed_matches": 0,
            "total_matches": 0,
            "groups": [],
        }

    progress = json.loads(raw_progress)
    rnd, day = progress["round"], progress["day"]
    members = q(
        "select name,grp,seed from member where rnd=? order by grp,seed",
        (rnd,),
    )
    history = {}
    for row in q("select name,rank from daily where rnd=? and day<?", (rnd, day)):
        history.setdefault(row["name"], []).append(row["rank"])
    submission_counts = {
        row["name"]: row["count"]
        for row in q(
            "select name,count(*) count from subs where rnd=? and day<? group by name",
            (rnd, DAYS),
        )
    }
    scores = {
        row["name"]: {
            "pts": row["pts"],
            "gs": row["gs"],
            "matches_played": row["matches_played"],
        }
        for row in q(
            """select name,sum(pts) pts,sum(gs) gs,sum(match_count) matches_played
               from (
                   select a name,case when s>0 then 1 when s<0 then -1 else 0 end pts,
                          s gs,1 match_count
                   from matches where rnd=? and day=?
                   union all
                   select b name,case when s>0 then -1 when s<0 then 1 else 0 end pts,
                          -s gs,1 match_count
                   from matches where rnd=? and day=?
               )
               group by name""",
            (rnd, day, rnd, day),
        )
    }

    grouped = {}
    for row in members:
        if day == DAYS and submission_counts.get(row["name"], 0) < MIN_DAYS:
            continue
        grouped.setdefault(row["grp"], []).append(row)

    groups = []
    for group_id, entrants in sorted(grouped.items()):
        entrants.sort(key=lambda row: (
            sum(history.get(row["name"], [])) / len(history[row["name"]])
            if history.get(row["name"]) else 0,
            row["seed"],
        ))
        initial_order = {
            entrant["name"]: index for index, entrant in enumerate(entrants)
        }
        standings = []
        for row in entrants:
            score = scores.get(
                row["name"],
                {"pts": 0, "gs": 0, "matches_played": 0},
            )
            standings.append({
                "name": row["name"],
                "pts": score["pts"],
                "gs": score["gs"],
                "matches_played": score["matches_played"],
            })
        standings.sort(key=lambda row: (
            -row["pts"],
            -row["gs"],
            initial_order[row["name"]],
        ))
        for rank, standing in enumerate(standings, start=1):
            standing["rank"] = rank
        groups.append({
            "group": group_id,
            "matches_played": sum(
                scores.get(row["name"], {}).get("matches_played", 0)
                for row in entrants
            ) // 2,
            "entrants": standings,
        })

    return {**progress, "groups": groups}


def publish_live_tournament_snapshot():
    board = live_tournament_board()
    queue = json.loads(get("live_scoring_queue", "[]"))
    completed = set(json.loads(get("live_scoring_completed", "[]")))
    queue_position_by_player = {}
    queue_ahead_by_position = []
    completed_before = 0
    for index, match in enumerate(queue):
        queue_ahead_by_position.append(index - completed_before)
        if index in completed:
            completed_before += 1
        queue_position_by_player[match["a"].lower()] = index
        queue_position_by_player[match["b"].lower()] = index

    visible_groups = []
    players = {}
    for group in board["groups"]:
        matches_per_round = len(group["entrants"]) // 2
        group_matches_total = matches_per_round * MATCHES
        group_rounds_completed = (
            min(MATCHES, group["matches_played"] // matches_per_round)
            if matches_per_round else board.get("completed_rounds", 0)
        )
        group_complete = bool(
            board["state"] == "complete"
            or group["matches_played"] >= group_matches_total > 0
            or group_matches_total == 0
            and board.get("completed_rounds", 0) >= MATCHES
        )
        if group_complete:
            visible_groups.append(group)

        for entrant in group["entrants"]:
            position = queue_position_by_player.get(entrant["name"].lower())
            match_complete = (
                position in completed if position is not None else False
            )
            queue_ahead = (
                queue_ahead_by_position[position]
                if position is not None and not match_complete else None
            )
            if board["state"] == "idle":
                personal_state = "waiting"
            elif board["state"] == "failed":
                personal_state = "failed"
            elif match_complete:
                personal_state = "complete"
            elif queue_ahead is not None:
                personal_state = "queued"
            else:
                personal_state = "bye"
            players[entrant["name"].lower()] = {
                "name": entrant["name"],
                "group": group["group"],
                "state": personal_state,
                "matches_played": entrant["matches_played"],
                "total_matches": MATCHES,
                "group_matches_played": group["matches_played"],
                "group_matches_total": group_matches_total,
                "group_matches_remaining": max(
                    0, group_matches_total - group["matches_played"]
                ),
                "rounds_remaining": max(
                    0, board.get("total_rounds", MATCHES)
                    - board.get("completed_rounds", 0)
                ),
                "group_rounds_remaining": max(
                    0, MATCHES - group_rounds_completed
                ),
                "queue_ahead": queue_ahead,
                "group_complete": group_complete,
            }

    snapshot = {
        **board,
        "groups": board["groups"] if board["state"] == "complete" else visible_groups,
        "players": players,
        "generated_at": time.time(),
    }
    directory = os.path.dirname(LIVE_BOARD_SNAPSHOT)
    os.makedirs(directory, exist_ok=True)
    temporary_path = f"{LIVE_BOARD_SNAPSHOT}.tmp"
    with open(temporary_path, "w", encoding="utf-8") as snapshot_file:
        json.dump(snapshot, snapshot_file, ensure_ascii=False, separators=(",", ":"))
    os.replace(temporary_path, LIVE_BOARD_SNAPSHOT)
    return snapshot


def save_live_scores(event, scores):
    """Save one judging session; re-entering a contestant updates that session's score."""
    if not isinstance(event, str) or not event.strip() or len(event.strip()) > 80:
        raise ValueError("Tên lần chấm phải dài từ 1 đến 80 ký tự.")
    if not isinstance(scores, list) or not scores:
        raise ValueError("Nhập điểm cho ít nhất một thí sinh.")

    clean_scores = {}
    for item in scores:
        if not isinstance(item, dict):
            raise ValueError("Mỗi điểm phải có tên thí sinh và điểm số.")
        name, score = item.get("name"), item.get("score")
        if not isinstance(name, str) or not name:
            raise ValueError("Tên thí sinh không hợp lệ.")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
            raise ValueError(f"Điểm của {name} phải là số hữu hạn.")
        if name in clean_scores:
            raise ValueError(f"Thí sinh {name} bị nhập trùng trong lần chấm.")
        clean_scores[name] = float(score)

    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
        names = list(clean_scores)
        known = set()
        for offset in range(0, len(names), 500):
            batch = names[offset:offset + 500]
            placeholders = ",".join("?" for _ in batch)
            known.update(
                row[0]
                for row in conn.execute(
                    f"select name from users where name in ({placeholders})",
                    batch,
                )
            )
        unknown = sorted(set(names) - known)
        if unknown:
            raise ValueError(f"Không tìm thấy thí sinh: {', '.join(unknown)}.")
        timestamp = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        conn.executemany(
            """insert into live_scores(event,name,score,updated_at) values(?,?,?,?)
               on conflict(event,name) do update
               set score=excluded.score, updated_at=excluded.updated_at""",
            [(event.strip(), name, score, timestamp) for name, score in clean_scores.items()],
        )
        records = [
            dict(row)
            for row in conn.execute(
                """select id,event,name,score,updated_at from live_scores
                   where event=? and name in ({}) order by id""".format(
                    ",".join("?" for _ in clean_scores)
                ),
                (event.strip(), *clean_scores),
            ).fetchall()
        ]
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return records


def live_leaderboard():
    totals = q(
        """select name,sum(score) total,max(updated_at) updated_at
           from live_scores group by name order by total desc,name"""
    )
    rows = []
    previous_total = None
    rank = 0
    for index, row in enumerate(totals, start=1):
        total = row["total"]
        if total != previous_total:
            rank = index
            previous_total = total
        rows.append({
            "rank": rank,
            "name": row["name"],
            "total": total,
            "updated_at": row["updated_at"],
        })
    return rows


def replays(name, rnd=None, day=None):
    available = [
        dict(r)
        for r in q(
            """select distinct d.rnd as round,d.day
               from daily d
               join member ma on ma.rnd=d.rnd and ma.name=d.name
               where ma.name=? order by d.rnd,d.day""",
            (name,),
        )
    ]
    if not available:
        return {"available": [], "round": None, "day": None, "matches": []}
    if rnd is None or day is None:
        rnd, day = available[-1]["round"], available[-1]["day"]
    own_group = q("select grp from member where rnd=? and name=?", (rnd, name))
    if not own_group or not any(r["round"] == rnd and r["day"] == day for r in available):
        raise ValueError("Không tìm thấy ngày thi đã chấm trong bảng của bạn.")
    group = own_group[0]["grp"]
    matches = [
        dict(r)
        for r in q(
            """select m.rd,m.a,m.b,m.s,r.games
               from matches m
               join member ma on ma.rnd=m.rnd and ma.name=m.a
               join member mb on mb.rnd=m.rnd and mb.name=m.b and mb.grp=ma.grp
               left join match_replays r
                 on r.rnd=m.rnd and r.day=m.day and r.rd=m.rd and r.a=m.a and r.b=m.b
               where m.rnd=? and m.day=? and ma.grp=?
               order by m.rd,m.a,m.b""",
            (rnd, day, group),
        )
    ]
    for match in matches:
        match["games"] = json.loads(match["games"]) if match["games"] else []
    return {"available": available, "round": rnd, "day": day, "matches": matches}


def admin_overview():
    phase = get("phase", "entry")
    rnd = int(get("round", 0) or 0)
    day = int(get("day", 0) or 0)
    pending = int(get("pending", 0) or 0)
    submission_day = 0 if phase == "entry" else day
    submissions = {
        row["name"]: row["submitted"]
        for row in q(
            "select name,1 submitted from subs where rnd=? and day=?",
            (0 if phase == "entry" else rnd, submission_day),
        )
    }
    members = {
        row["name"]: row["grp"]
        for row in q("select name,grp from member where rnd=?", (rnd,))
    } if rnd else {}
    entrants = []
    for row in q("select name,status,entry from users order by name"):
        name = row["name"]
        entrants.append({
            "name": name,
            "status": row["status"],
            "entry": row["entry"],
            "group": members.get(name),
            "has_bot": latest(name) is not None,
            "submitted": bool(submissions.get(name)),
        })
    return {
        "phase": phase,
        "round": rnd or None,
        "day": day or None,
        "pending": pending or None,
        "champion": get("champion") or None,
        "accepting_submissions": get("accepting_submissions", "1") == "1",
        "counts": {
            row["status"]: row["count"]
            for row in q("select status,count(*) count from users group by status")
        },
        "entrants": entrants,
    }


# ---------------- CLI ----------------
def main():
    global DAYS, MIN_DAYS, MATCHES
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("args", nargs="*")
    a = ap.parse_args()
    init()
    if a.cmd == "entry-close": entry_close(); _publish("entry-close")
    elif a.cmd == "close": close_day(); _publish("close")
    elif a.cmd == "grade": grade_day(); _publish("grade")
    elif a.cmd == "run-day": close_day(); grade_day(); _publish("run-day")
    elif a.cmd == "status":
        print({k: get(k) for k in ("phase", "round", "day", "pending")})
        print("users:", {r["status"]: r["c"] for r in q("select status,count(*) c from users group by status")})
    elif a.cmd == "add-bot":
        name, f = a.args
        if not q("select 1 from users where name=?", (name,)):
            register(name)
        q("update users set status=coalesce(nullif(status,'new'),'new') where name=?", (name,))
        os.makedirs(f"{BOT_DIR}/{name}", exist_ok=True)
        shutil.copy(f, f"{BOT_DIR}/{name}/latest.py")
        rnd, day = (0, 0) if get("phase", "entry") == "entry" else (int(get("round")), int(get("day")))
        q("insert or replace into subs values(?,?,?,?)", (name, rnd, day, time.time()))
    elif a.cmd == "run-all":                      # chạy hết các ngày của vòng (dùng khi thử)
        for _ in range(DAYS):
            close_day(); grade_day()
        for r in q("select day,rank,name,pts,gs from daily order by day,rank"):
            print(dict(r))
    elif a.cmd == "board":
        for r in q("select rnd,day,grp,rank,name,pts,gs from daily order by rnd,day,grp,rank"):
            print(dict(r))
    elif a.cmd == "demo":
        n = int(a.args[0]); CFG["entry_cut"] = -99
        DAYS, MIN_DAYS, MATCHES = 3, 2, 3                 # demo rút gọn: 3 ngày/vòng, 3 trận/ngày
        for rc, (g, tp, w) in zip(CFG["rounds"], [(4, 3, 4), (2, 3, 2), (1, 3, 1), (1, 2, 1), (1, 1, 0)]):
            rc.update(groups=g, top=tp, wildcard=w)
        print(f"DEMO {n} thi sinh, bat dau...", flush=True)
        for i in range(n):
            nm = f"user{i:04d}"; register(nm)
            if random.random() < 0.9:
                os.makedirs(f"{BOT_DIR}/{nm}", exist_ok=True)
                shutil.copy("sample_bot.py", f"{BOT_DIR}/{nm}/latest.py")
        entry_close()
        for r in range(1, len(CFG["rounds"]) + 1):
            for d in range(1, DAYS + 1):
                for nm in [x["name"] for x in q("select name from member where rnd=?", (r,))]:
                    if random.random() < 0.7 and latest(nm):
                        q("insert or replace into subs values(?,?,?,?)", (nm, r, d, time.time()))
                close_day(); grade_day()
            if get("phase") == "done": break


if __name__ == "__main__":
    main()

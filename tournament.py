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
import os, re, sys, time, random, shutil, secrets, sqlite3, argparse
from multiprocessing import Pool
import engine

DB, BOT_DIR, SNAP = "ott.db", "bots", "snaps"
DAYS, MIN_DAYS, MATCHES = 7, 4, 7         # 6 ngày thường + ngày cuối; nộp >=4/6 ngày mới được đấu ngày cuối
CFG = dict(
    entry_cut=0,                          # entry < entry_cut => loại. entry = 1*s0 + 2*s1 + 3*s2, mỗi s thuộc [-2,2]
    entry_weights=[1, 2, 3],
    workers=min(os.cpu_count() or 4, 60),   # Windows tối đa 61
    rounds=[                              # groups: số bảng; top: top mỗi bảng đi tiếp; wildcard: vé vớt toàn vòng
        dict(groups=40, top=10, wildcard=40),
        dict(groups=16, top=8, wildcard=16),
        dict(groups=8, top=6, wildcard=8),
        dict(groups=4, top=4, wildcard=4),
        dict(groups=1, top=1, wildcard=0),   # vòng 5: offline
    ])

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
create table if not exists matches(rnd int, day int, rd int, a text, b text, s int);
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
    c = sqlite3.connect(DB); c.executescript(SCHEMA); c.commit(); c.close()


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


def submit(name, src):
    ph = get("phase", "entry")
    if ph not in ("entry", "round"):
        raise ValueError("Cuộc thi không nhận bài lúc này")
    u = q("select status from users where name=?", (name,))[0]
    if ph == "round" and u["status"] != "active":
        raise ValueError("Bạn đã bị loại")
    if len(src) > 65536:
        raise ValueError("File quá lớn (>64KB)")
    compile(src, "bot", "exec")                      # kiểm tra cú pháp, KHÔNG chạy
    last = q("select max(ts) t from subs where name=?", (name,))[0]["t"]
    if last and time.time() - last < 10:
        raise ValueError("Nộp quá nhanh, chờ 10 giây")
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
                tasks.append((p, f"btc:{i}")); idx.append((n, i))
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

    def spec(n):
        p = f"{SNAP}/r{rnd}/d{day}/{n}.py"
        return p if os.path.exists(p) else None

    log = []
    with Pool(CFG["workers"]) as pool:
        for rd in range(MATCHES):
            todo = []
            for g, st in S.items():
                pairs, bye = make_pairs(st, rd)
                if bye:
                    st["byes"].add(bye)
                todo += [(g, a, b) for a, b in pairs]
            real = [i for i, (g, a, b) in enumerate(todo) if spec(a) and spec(b)]
            out = dict(zip(real, pool.map(engine.play_match, [(spec(todo[i][1]), spec(todo[i][2])) for i in real], chunksize=2)))
            for i, (g, a, b) in enumerate(todo):
                if i in out:
                    s = out[i]
                else:                                      # ai không nộp bài thì thua (không chạy trận)
                    s = 0 if not spec(a) and not spec(b) else (-2 if not spec(a) else 2)
                m = (s > 0) - (s < 0)
                st = S[g]
                st["pts"][a] += m; st["pts"][b] -= m; st["gs"][a] += s; st["gs"][b] -= s
                st["played"].add(frozenset((a, b)))
                log.append((rnd, day, rd + 1, a, b, s))
            print(f"  trận {rd + 1}/{MATCHES} xong ({len(todo)} cặp)")
    rows = []
    for g, st in S.items():
        rk = sorted(st["order"], key=lambda n: (-st["pts"][n], -st["gs"][n], st["order"].index(n)))
        rows += [(rnd, day, g, n, st["pts"][n], st["gs"][n], i + 1, len(rk)) for i, n in enumerate(rk)]
    qm("insert or replace into daily values(?,?,?,?,?,?,?,?)", rows)
    qm("insert into matches values(?,?,?,?,?,?)", log)
    put("pending", 0)
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
    if a.cmd == "entry-close": entry_close()
    elif a.cmd == "close": close_day()
    elif a.cmd == "grade": grade_day()
    elif a.cmd == "run-day": close_day(); grade_day()
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

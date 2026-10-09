"""OTTv2 engine: luật chơi, sandbox chạy bot thí sinh, bot BTC dùng cho thi đầu vào.

Quy ước:
- Bàn 9x9, toạ độ (x,y), x=0..8 là cột a..i, y=0..8 là hàng 1..9.
- Loại quân: 0=Búa, 1=Bao, 2=Kéo.  Búa>Kéo, Kéo>Bao, Bao>Búa.
- Người 0 (đi trước) xuất phát hàng 1, đích là ô i9 = (8,8).
- Người 1 xuất phát hàng 9, đích là ô a1 = (0,0).
- Quân đi 1 ô theo 8 hướng. Đi vào ô quân mình / quân địch cùng loại / quân địch khắc mình => không hợp lệ.
- Thắng: ăn hết 1 loại quân của đối phương, hoặc đưa 1 quân vào ô đích.
- Hết nước đi, đi sai, timeout, crash => thua. Quá MAX_PLIES nước => hòa.
"""
import os, sys, json, random, subprocess, tempfile, time, shutil, threading, queue

IS_WIN = sys.platform.startswith("win")
if not IS_WIN:
    import resource

N = 9
BEAT = {0: 2, 1: 0, 2: 1}          # BEAT[t] = loại bị t ăn được
DIRS = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
GOAL = {0: (8, 8), 1: (0, 0)}
MAX_PLIES = 200
FIRST_T, MOVE_T = 3.0, 1.0         # giây: nước đầu (tính cả khởi động python) / các nước sau


# ---------------- LUẬT ----------------
def initial():
    b = {}
    for x in range(N):
        b[(x, 0)] = (0, x % 3)
        b[(x, N - 1)] = (1, x % 3)
    return b


def legal_moves(b, p):
    out = []
    for (x, y), (o, t) in b.items():
        if o != p:
            continue
        for dx, dy in DIRS:
            nx, ny = x + dx, y + dy
            if 0 <= nx < N and 0 <= ny < N:
                c = b.get((nx, ny))
                if c is None or (c[0] != p and BEAT[t] == c[1]):
                    out.append((x, y, nx, ny))
    return out


def apply(b, m):
    x, y, nx, ny = m
    b = dict(b)
    b[(nx, ny)] = b.pop((x, y))
    return b


def check_win(b, p, m):
    """p vừa đi nước m: p thắng chưa?"""
    if (m[2], m[3]) == GOAL[p]:
        return True
    return len({t for (o, t) in b.values() if o == 1 - p}) < 3


def encode(b, me, ply):
    return {"me": me, "ply": ply, "goal": list(GOAL[me]),
            "pieces": [[x, y, o, t] for (x, y), (o, t) in b.items()]}


def play(bots, max_plies=MAX_PLIES):
    """bots[0] đi trước. Trả +1 nếu bots[0] thắng, -1 nếu thua, 0 hòa."""
    b = initial()
    for ply in range(max_plies):
        p = ply % 2
        lm = legal_moves(b, p)
        lose = -1 if p == 0 else 1
        if not lm:
            return lose
        m = bots[p].move(encode(b, p, ply), FIRST_T if ply < 2 else MOVE_T)
        if m not in lm:
            return lose
        b = apply(b, m)
        if check_win(b, p, m):
            return -lose
    return 0


# ---------------- SANDBOX ----------------
class ProcBot:
    """Chạy file .py của thí sinh trong process riêng, giao tiếp qua stdin/stdout (mỗi dòng 1 JSON -> 'x y nx ny').
    Linux: giới hạn RAM/CPU/file/process bằng rlimit. Windows: chỉ có timeout từng nước (không giới hạn RAM).
    Khi thi thật nên chạy trong docker/VM riêng."""

    def __init__(self, path):
        self.cwd = tempfile.mkdtemp(prefix="ott_")
        self.q = queue.Queue()
        kw = {}
        if IS_WIN:
            env = {k: v for k, v in os.environ.items() if k.upper() in ("SYSTEMROOT", "PATH", "TEMP", "TMP")}
            kw["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            env = {}

            def limits():
                resource.setrlimit(resource.RLIMIT_AS, (512 << 20, 512 << 20))
                resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
                resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
                resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
            kw["preexec_fn"] = limits
            kw["start_new_session"] = True
        self.p = subprocess.Popen([sys.executable, "-I", os.path.abspath(path)], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
                                  cwd=self.cwd, env=env, **kw)
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):                      # thread đọc từng dòng stdout -> queue (chạy được cả Windows)
        try:
            for line in iter(self.p.stdout.readline, b""):
                self.q.put(line[:200])
        except Exception:
            pass
        self.q.put(None)

    def move(self, state, timeout):
        try:
            self.p.stdin.write((json.dumps(state) + "\n").encode())
            self.p.stdin.flush()
            line = self.q.get(timeout=timeout)
            if line is None:
                return None
            x, y, nx, ny = map(int, line.split())
            return (x, y, nx, ny)
        except Exception:
            return None

    def close(self):
        try:
            self.p.kill(); self.p.wait(timeout=2)
        except Exception:
            pass
        shutil.rmtree(self.cwd, ignore_errors=True)


class FuncBot:
    def __init__(self, fn): self.fn = fn
    def move(self, state, timeout): return self.fn(state)
    def close(self): pass


# ---------------- BOT BTC (đơn giản) ----------------
def _decode(s):
    return {(x, y): (o, t) for x, y, o, t in s["pieces"]}, s["me"]


def _dist(x, y, g):
    return max(abs(x - g[0]), abs(y - g[1]))


def btc0(s):  # ngẫu nhiên
    b, me = _decode(s)
    return random.choice(legal_moves(b, me))


def btc1(s):  # tham lam: thắng ngay > ăn quân > tiến về đích
    b, me = _decode(s)
    lm, g = legal_moves(b, me), GOAL[me]
    for m in lm:
        if (m[2], m[3]) == g:
            return m
    caps = [m for m in lm if (m[2], m[3]) in b]
    if caps:
        return random.choice(caps)
    return min(lm, key=lambda m: (_dist(m[2], m[3], g), random.random()))


def btc2(s):  # chấm điểm 1 nước: thắng ngay, ăn quân, tiến gần đích, tránh bị khắc ăn
    b, me = _decode(s)
    g, best, bs = GOAL[me], None, -1e9
    for m in legal_moves(b, me):
        nb = apply(b, m)
        if check_win(nb, me, m):
            return m
        t = nb[(m[2], m[3])][1]
        sc = random.random() * 0.3 + 0.5 * (_dist(m[0], m[1], g) - _dist(m[2], m[3], g))
        if (m[2], m[3]) in b:
            sc += 3
        for dx, dy in DIRS:
            c = nb.get((m[2] + dx, m[3] + dy))
            if c and c[0] != me and BEAT[c[1]] == t:
                sc -= 4
                break
        if sc > bs:
            best, bs = m, sc
    return best


BTC = [btc0, btc1, btc2]


# ---------------- TRẬN BO2 ----------------
def make_bot(spec):
    return FuncBot(BTC[int(spec[4:])]) if spec.startswith("btc:") else ProcBot(spec)


def play_match(args):
    """args=(specA, specB), spec là đường dẫn file bot hoặc 'btc:k'. BO2, mỗi bên đi trước 1 ván.
    Trả s = (điểm ván của A) tổng 2 ván, trong [-2,2]."""
    a, b = args
    s = 0
    for first in (0, 1):
        ba, bb = make_bot(a), make_bot(b)
        try:
            r = play([ba, bb]) if first == 0 else -play([bb, ba])
        finally:
            ba.close(); bb.close()
        s += r
    return s


if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "test":
    for i in range(3):   # thí sinh tự test bot ở máy mình
        print(f"vs btc:{i}: {play_match((sys.argv[2], f'btc:{i}'))} / 2")

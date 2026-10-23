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
def _coordinate(value, field):
    if (not isinstance(value, list) or len(value) != 2
            or any(type(part) is not int or not 0 <= part < N for part in value)):
        raise ValueError(f"{field} phải là tọa độ [x, y] trong khoảng 0..{N - 1}")
    return tuple(value)


def _normalize_rules(data):
    if not isinstance(data, dict) or set(data) != {"schema_version", "board"}:
        raise ValueError("Cấu hình luật phải có đúng schema_version và board")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError(f"Không hỗ trợ schema_version={data['schema_version']!r}")

    board = data["board"]
    allowed = {
        "width", "height", "walls", "protection_zones",
        "teleporters", "piece_changers",
    }
    if not isinstance(board, dict) or set(board) - allowed:
        raise ValueError("board phải là object và không chứa trường luật không được hỗ trợ")
    width, height = board.get("width", N), board.get("height", N)
    if (type(width) is not int or type(height) is not int
            or width != N or height != N):
        raise ValueError(f"Bàn cờ hiện chỉ hỗ trợ kích thước {N}x{N}")

    special_cells = set()

    def claim(cell, field):
        if cell in special_cells:
            raise ValueError(f"Ô đặc biệt {list(cell)} bị khai báo trùng ({field})")
        special_cells.add(cell)

    walls = []
    raw_walls = board.get("walls", [])
    if not isinstance(raw_walls, list):
        raise ValueError("board.walls phải là danh sách tọa độ")
    for index, item in enumerate(raw_walls):
        cell = _coordinate(item, f"board.walls[{index}]")
        claim(cell, "walls")
        walls.append(list(cell))

    protection_zones = []
    raw_zones = board.get("protection_zones", [])
    if not isinstance(raw_zones, list):
        raise ValueError("board.protection_zones phải là danh sách vùng")
    if raw_zones and len(raw_zones) != 4:
        raise ValueError("Phải khai báo đúng 4 vùng bảo vệ")
    for index, raw_zone in enumerate(raw_zones):
        if not isinstance(raw_zone, list) or len(raw_zone) != 2:
            raise ValueError(
                f"board.protection_zones[{index}] phải gồm đúng hai ô"
            )
        cells = [
            _coordinate(cell, f"board.protection_zones[{index}][{cell_index}]")
            for cell_index, cell in enumerate(raw_zone)
        ]
        if cells[0][1] != cells[1][1] or abs(cells[0][0] - cells[1][0]) != 1:
            raise ValueError(
                f"board.protection_zones[{index}] phải gồm hai ô liền nhau theo chiều ngang"
            )
        for cell in cells:
            claim(cell, "protection_zones")
        protection_zones.append([list(cell) for cell in cells])
    if protection_zones:
        zone_sets = {
            frozenset(map(tuple, zone)) for zone in protection_zones
        }
        rotated_zones = {
            frozenset((N - 1 - x, N - 1 - y) for x, y in zone)
            for zone in zone_sets
        }
        if zone_sets != rotated_zones:
            raise ValueError("Bốn vùng bảo vệ phải đối xứng quay 180 độ")

    teleporters = []
    raw_teleporters = board.get("teleporters", [])
    if not isinstance(raw_teleporters, list):
        raise ValueError("board.teleporters phải là danh sách cặp cổng")
    for index, item in enumerate(raw_teleporters):
        if not isinstance(item, dict) or set(item) != {
            "ends", "activation", "use", "occupied_destination"
        }:
            raise ValueError(f"board.teleporters[{index}] có cấu trúc không hợp lệ")
        ends = item["ends"]
        if not isinstance(ends, list) or len(ends) != 2:
            raise ValueError(f"board.teleporters[{index}].ends phải có đúng hai đầu")
        first = _coordinate(ends[0], f"board.teleporters[{index}].ends[0]")
        second = _coordinate(ends[1], f"board.teleporters[{index}].ends[1]")
        if first == second:
            raise ValueError(f"board.teleporters[{index}] không thể nối một ô với chính nó")
        if item["activation"] != "piece_starts_turn_on_endpoint":
            raise ValueError(f"board.teleporters[{index}].activation không được hỗ trợ")
        if item["use"] != "optional":
            raise ValueError(f"board.teleporters[{index}].use phải là optional")
        if item["occupied_destination"] != "capture_if_legal":
            raise ValueError(
                f"board.teleporters[{index}].occupied_destination phải là capture_if_legal"
            )
        claim(first, "teleporters")
        claim(second, "teleporters")
        teleporters.append({
            "ends": [list(first), list(second)],
            "activation": item["activation"],
            "use": item["use"],
            "occupied_destination": item["occupied_destination"],
        })

    piece_changers = []
    raw_changers = board.get("piece_changers", [])
    if not isinstance(raw_changers, list):
        raise ValueError("board.piece_changers phải là danh sách")
    if len(raw_changers) > 1:
        raise ValueError("Chỉ được khai báo tối đa một ô đổi quân")
    for index, item in enumerate(raw_changers):
        if not isinstance(item, dict) or set(item) != {
            "position", "activation", "type_changes"
        }:
            raise ValueError(f"board.piece_changers[{index}] có cấu trúc không hợp lệ")
        cell = _coordinate(item["position"], f"board.piece_changers[{index}].position")
        if cell != (N // 2, N // 2):
            raise ValueError(f"Ô đổi quân phải ở chính giữa bàn: [{N // 2}, {N // 2}]")
        if item["activation"] != "on_enter":
            raise ValueError(f"board.piece_changers[{index}].activation phải là on_enter")
        changes = item["type_changes"]
        if not isinstance(changes, dict) or changes != {"0": 2, "1": 0, "2": 1}:
            raise ValueError(
                "type_changes phải theo chu kỳ Búa→Kéo, Bao→Búa, Kéo→Bao"
            )
        claim(cell, "piece_changers")
        piece_changers.append({
            "position": list(cell),
            "activation": item["activation"],
            "type_changes": dict(changes),
        })

    return {
        "schema_version": 1,
        "board": {
            "width": N,
            "height": N,
            "walls": walls,
            "protection_zones": protection_zones,
            "teleporters": teleporters,
            "piece_changers": piece_changers,
        },
    }


def load_rules(path):
    """Đọc và kiểm tra file JSON luật; trả về cấu hình đã chuẩn hóa."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON luật không hợp lệ trong {path}: {exc}") from exc
    return _normalize_rules(data)


def _teleporter_destinations(rules):
    destinations = {}
    if rules is None:
        return destinations
    for teleporter in rules["board"]["teleporters"]:
        first, second = map(tuple, teleporter["ends"])
        destinations[first] = second
        destinations[second] = first
    return destinations


def _can_enter(b, p, piece_type, destination, walls, protected_cells):
    if destination in walls:
        return False
    occupant = b.get(destination)
    if occupant is None:
        return True
    return (
        occupant[0] != p
        and destination not in protected_cells
        and BEAT[piece_type] == occupant[1]
    )


def initial():
    b = {}
    for x in range(N):
        b[(x, 0)] = (0, x % 3)
        b[(x, N - 1)] = (1, x % 3)
    return b


def legal_moves(b, p, rules=None):
    out = []
    walls = {
        tuple(cell) for cell in rules["board"]["walls"]
    } if rules is not None else set()
    protected_cells = {
        tuple(cell)
        for zone in rules["board"]["protection_zones"]
        for cell in zone
    } if rules is not None else set()
    teleporters = _teleporter_destinations(rules)
    for (x, y), (o, t) in b.items():
        if o != p:
            continue
        for dx, dy in DIRS:
            nx, ny = x + dx, y + dy
            if 0 <= nx < N and 0 <= ny < N:
                if _can_enter(b, p, t, (nx, ny), walls, protected_cells):
                    out.append((x, y, nx, ny))
        destination = teleporters.get((x, y))
        if destination is not None and _can_enter(
            b, p, t, destination, walls, protected_cells
        ):
            move = (x, y, destination[0], destination[1])
            if move not in out:
                out.append(move)
    return out


def apply(b, m, rules=None):
    x, y, nx, ny = m
    b = dict(b)
    piece = b.pop((x, y))
    changer_positions = {
        tuple(changer["position"]): changer["type_changes"]
        for changer in rules["board"]["piece_changers"]
    } if rules is not None else {}
    changes = changer_positions.get((nx, ny))
    if changes:
        piece = (piece[0], changes[str(piece[1])])
    b[(nx, ny)] = piece
    return b


def check_win(b, p, m, rules=None):
    """p vừa đi nước m: p thắng chưa?"""
    if (m[2], m[3]) == GOAL[p]:
        return True
    return len({t for (o, t) in b.values() if o == 1 - p}) < 3


def encode(b, me, ply, rules=None):
    state = {"me": me, "ply": ply, "goal": list(GOAL[me]),
             "pieces": [[x, y, o, t] for (x, y), (o, t) in b.items()]}
    if rules is not None:
        state["rules"] = rules
    return state


def play(bots, max_plies=MAX_PLIES, moves=None, rules=None, on_move=None, delay=0.0):
    """bots[0] đi trước. Trả +1 nếu bots[0] thắng, -1 nếu thua, 0 hòa."""
    if rules is not None:
        rules = _normalize_rules(rules)
    b = initial()
    for ply in range(max_plies):
        p = ply % 2
        lm = legal_moves(b, p, rules)
        lose = -1 if p == 0 else 1
        if not lm:
            bot_name = getattr(bots[p], "name", f"Bên {p}")
            print(f"[ENGINE INFO] Lượt {ply}: {bot_name} không còn nước đi hợp lệ -> xử thua.", file=sys.stderr, flush=True)
            return lose
        bot_name = getattr(bots[p], "name", f"Bên {p}")
        t_limit = FIRST_T if ply < 2 else MOVE_T
        m = bots[p].move(encode(b, p, ply, rules), t_limit)
        if m is None:
            err = getattr(bots[p], "last_error", "Bot không trả về nước đi")
            print(f"[ENGINE LỖI] Lượt {ply} ({bot_name}): {err} -> Xử thua!", file=sys.stderr, flush=True)
            return lose
        if m not in lm:
            err = f"Nước đi phạm quy {m} (không nằm trong danh sách {len(lm)} nước hợp lệ)"
            bots[p].last_error = err
            print(f"[ENGINE LỖI] Lượt {ply} ({bot_name}): {err} -> Xử thua!", file=sys.stderr, flush=True)
            return lose
        captured = b.get((m[2], m[3]))
        b = apply(b, m, rules)
        if moves is not None:
            moves.append((p, m))
        if check_win(b, p, m, rules):
            is_win = True
        else:
            is_win = False
        if on_move is not None:
            try:
                on_move(ply, p, m, captured, is_win)
            except Exception:
                pass
        if delay > 0:
            time.sleep(delay)
        if is_win:
            return -lose
    return 0


# ---------------- SANDBOX ----------------
class ProcBot:
    """Chạy file .py của thí sinh trong process riêng, giao tiếp qua stdin/stdout (mỗi dòng 1 JSON -> 'x y nx ny').
    Linux: giới hạn RAM/CPU/file/process bằng rlimit. Windows: chỉ có timeout từng nước (không giới hạn RAM).
    Khi thi thật nên chạy trong docker/VM riêng."""

    def __init__(self, path):
        self.path = path
        self.name = os.path.basename(path)
        self.last_error = None
        self.stderr_lines = []
        self.cwd = tempfile.mkdtemp(prefix="ott_")
        self.q = queue.Queue()
        kw = {}
        if IS_WIN:
            env = {k: v for k, v in os.environ.items() if k.upper() in ("SYSTEMROOT", "PATH", "TEMP", "TMP")}
            kw["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            env = {}

            def limits():
                for attr, val in [
                    ("RLIMIT_AS", (512 << 20, 512 << 20)),
                    ("RLIMIT_CPU", (30, 30)),
                    ("RLIMIT_FSIZE", (0, 0)),
                    ("RLIMIT_NPROC", (0, 0)),
                ]:
                    try:
                        lim = getattr(resource, attr, None)
                        if lim is not None:
                            resource.setrlimit(lim, val)
                    except Exception:
                        pass
            kw["preexec_fn"] = limits
            kw["start_new_session"] = True
        self.p = subprocess.Popen([sys.executable, "-I", os.path.abspath(path)], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
                                  cwd=self.cwd, env=env, **kw)
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._err_reader, daemon=True).start()

    def _reader(self):                      # thread đọc từng dòng stdout -> queue
        try:
            for line in iter(self.p.stdout.readline, b""):
                self.q.put(line[:200])
        except Exception as e:
            self.last_error = f"Lỗi đọc stdout: {e}"
        self.q.put(None)

    def _err_reader(self):                  # thread đọc stderr -> in ra terminal
        try:
            for line in iter(self.p.stderr.readline, b""):
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    self.stderr_lines.append(text)
                    print(f"[{self.name} STDERR] {text}", file=sys.stderr, flush=True)
        except Exception:
            pass

    def move(self, state, timeout):
        try:
            self.p.stdin.write((json.dumps(state) + "\n").encode())
            self.p.stdin.flush()
        except Exception as e:
            self.last_error = f"Lỗi ghi stdin: {e}"
            print(f"[{self.name}] {self.last_error}", file=sys.stderr, flush=True)
            return None

        try:
            line = self.q.get(timeout=timeout)
        except queue.Empty:
            self.last_error = f"TIMEOUT: Bot chạy quá {timeout}s không phản hồi nước đi!"
            print(f"[{self.name}] {self.last_error}", file=sys.stderr, flush=True)
            return None

        if line is None:
            detail = " | ".join(self.stderr_lines[-3:]) if self.stderr_lines else "tiến trình đã thoát"
            self.last_error = f"Bot bị crash hoặc thoát sớm: {detail}"
            print(f"[{self.name}] {self.last_error}", file=sys.stderr, flush=True)
            return None

        try:
            parts = line.strip().split()
            if len(parts) != 4:
                raise ValueError(f"Đầu ra phải là 4 số 'x y nx ny', bot in ra: {line!r}")
            x, y, nx, ny = map(int, parts)
            return (x, y, nx, ny)
        except Exception as e:
            self.last_error = f"Lỗi định dạng nước đi: {e}"
            print(f"[{self.name}] {self.last_error}", file=sys.stderr, flush=True)
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


def _rules_from_state(s):
    return s.get("rules")


def _dist(x, y, g):
    return max(abs(x - g[0]), abs(y - g[1]))


def btc0(s):  # ngẫu nhiên
    b, me = _decode(s)
    return random.choice(legal_moves(b, me, _rules_from_state(s)))


def btc1(s):  # tham lam: thắng ngay > ăn quân > tiến về đích
    b, me = _decode(s)
    rules = _rules_from_state(s)
    lm, g = legal_moves(b, me, rules), GOAL[me]
    for m in lm:
        if (m[2], m[3]) == g:
            return m
    caps = [m for m in lm if (m[2], m[3]) in b]
    if caps:
        return random.choice(caps)
    return min(lm, key=lambda m: (_dist(m[2], m[3], g), random.random()))


def btc2(s):  # chấm điểm 1 nước: thắng ngay, ăn quân, tiến gần đích, tránh bị khắc ăn
    b, me = _decode(s)
    rules = _rules_from_state(s)
    g, best, bs = GOAL[me], None, -1e9
    for m in legal_moves(b, me, rules):
        nb = apply(b, m, rules)
        if check_win(nb, me, m, rules):
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


def _entry_btc(s, prioritize_progress=False, take_wins=False):
    b, me = _decode(s)
    rules = _rules_from_state(s)
    moves = legal_moves(b, me, rules)
    if take_wins:
        for move in moves:
            if check_win(apply(b, move, rules), me, move, rules):
                return move
    if prioritize_progress:
        x, y = GOAL[me]
        advancing = [
            move for move in moves
            if _dist(move[2], move[3], (x, y)) < _dist(move[0], move[1], (x, y))
        ]
        if advancing:
            return random.choice(advancing)
    return random.choice(moves)


def entry_btc0(s):
    return _entry_btc(s)


def entry_btc1(s):
    return _entry_btc(s, prioritize_progress=True)


def entry_btc2(s):
    return _entry_btc(s, take_wins=True)


ENTRY_BTC = [entry_btc0, entry_btc1, entry_btc2]


# ---------------- TRẬN BO2 ----------------
def make_bot(spec):
    if spec.startswith("entry:"):
        return FuncBot(ENTRY_BTC[int(spec[6:])])
    return FuncBot(BTC[int(spec[4:])]) if spec.startswith("btc:") else ProcBot(spec)


def _play_match(args, record, rules=None, on_move=None, delay=0.0):
    """args=(specA, specB), spec là đường dẫn file bot hoặc 'btc:k'. BO2, mỗi bên đi trước 1 ván.
    Trả tổng điểm của A; tùy chọn kèm dữ liệu nước đi từng ván."""
    a, b = args
    s = 0
    games = []
    for first in (0, 1):
        ba, bb = make_bot(a), make_bot(b)
        moves = [] if record else None

        def game_on_move(ply, p, m, captured, is_win):
            if on_move:
                on_move(first, ply, p, m, captured, is_win)

        try:
            raw = play(
                [ba, bb] if first == 0 else [bb, ba],
                moves=moves,
                rules=rules,
                on_move=game_on_move if on_move else None,
                delay=delay,
            )
            r = raw if first == 0 else -raw
        finally:
            ba.close(); bb.close()
        s += r
        if record:
            games.append({
                "players": ["a", "b"] if first == 0 else ["b", "a"],
                "result": r,
                "moves": moves,
            })
    return (s, games) if record else s


def play_match_recorded(args, rules=None, on_move=None, delay=0.0):
    return _play_match(args, True, rules=rules, on_move=on_move, delay=delay)


def play_match(args, rules=None, on_move=None, delay=0.0):
    return _play_match(args, False, rules=rules, on_move=on_move, delay=delay)




if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "test":
    for i in range(3):   # thí sinh tự test bot ở máy mình
        print(f"vs btc:{i}: {play_match((sys.argv[2], f'btc:{i}'))} / 2")

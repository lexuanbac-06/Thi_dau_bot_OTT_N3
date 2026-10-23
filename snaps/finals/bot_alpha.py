# Bot mẫu OTTv2. Mỗi lượt engine gửi 1 dòng JSON; bot in "x y nx ny".
# state gồm me, ply, goal, pieces và rules (nếu vòng dùng luật riêng).
# Teleport là nước riêng từ cổng hiện tại đến đầu cổng kia; không tự kích hoạt khi đi vào.
import sys, json, random

BEAT = {0: 2, 1: 0, 2: 1}

for line in sys.stdin:
    s = json.loads(line)
    me, (gx, gy) = s["me"], s["goal"]
    b = {(x, y): (o, t) for x, y, o, t in s["pieces"]}
    rules = s.get("rules", {}).get("board", {})
    walls = {tuple(cell) for cell in rules.get("walls", [])}
    protected_cells = {
        tuple(cell)
        for zone in rules.get("protection_zones", [])
        for cell in zone
    }
    teleporters = {}
    for teleporter in rules.get("teleporters", []):
        first, second = map(tuple, teleporter["ends"])
        teleporters[first] = second
        teleporters[second] = first
    moves = []

    def can_enter(piece_type, destination):
        if destination in walls:
            return False
        occupant = b.get(destination)
        return occupant is None or (
            occupant[0] != me
            and destination not in protected_cells
            and BEAT[piece_type] == occupant[1]
        )

    for (x, y), (o, t) in b.items():
        if o != me:
            continue
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                nx, ny = x + dx, y + dy
                if (dx or dy) and 0 <= nx < 9 and 0 <= ny < 9:
                    if can_enter(t, (nx, ny)):
                        moves.append((x, y, nx, ny))
        destination = teleporters.get((x, y))
        if destination is not None and can_enter(t, destination):
            move = (x, y, destination[0], destination[1])
            if move not in moves:
                moves.append(move)
    win = [m for m in moves if (m[2], m[3]) == (gx, gy)]
    cap = [m for m in moves if (m[2], m[3]) in b]
    print(*random.choice(win or cap or moves), flush=True)

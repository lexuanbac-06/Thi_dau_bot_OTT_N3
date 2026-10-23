# Bot mẫu OTTv2. Mỗi lượt engine gửi 1 dòng JSON vào stdin, bot in ra 1 dòng "x y nx ny".
# state có thêm trường "rules" khi thi đấu theo preset luật của vòng.
# loại: 0=Búa 1=Bao 2=Kéo ; Búa>Kéo, Kéo>Bao, Bao>Búa. Mỗi nước tối đa 1 giây.
import sys, json, random

BEAT = {0: 2, 1: 0, 2: 1}

for line in sys.stdin:
    s = json.loads(line)
    me, (gx, gy) = s["me"], s["goal"]
    b = {(x, y): (o, t) for x, y, o, t in s["pieces"]}
    rules = s.get("rules", {}).get("board", {})
    walls = {tuple(cell) for cell in rules.get("walls", [])}
    protected = {
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
    for (x, y), (o, t) in b.items():
        if o != me:
            continue
        destinations = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                nx, ny = x + dx, y + dy
                if (dx or dy) and 0 <= nx < 9 and 0 <= ny < 9:
                    destinations.append((nx, ny))
        if (x, y) in teleporters:
            destinations.append(teleporters[(x, y)])
        for nx, ny in destinations:
            destination = (nx, ny)
            if destination in walls:
                continue
            c = b.get(destination)
            if c is None or (
                c[0] != me and destination not in protected and BEAT[t] == c[1]
            ):
                moves.append((x, y, nx, ny))
    win = [m for m in moves if (m[2], m[3]) == (gx, gy)]
    cap = [m for m in moves if (m[2], m[3]) in b]
    print(*random.choice(win or cap or moves), flush=True)

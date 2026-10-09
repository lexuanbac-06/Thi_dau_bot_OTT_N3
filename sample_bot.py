# Bot mẫu OTTv2. Mỗi lượt engine gửi 1 dòng JSON vào stdin, bot in ra 1 dòng "x y nx ny".
# state = {"me": 0|1, "ply": số nước đã đi, "goal": [x,y], "pieces": [[x,y,chủ,loại], ...]}
# loại: 0=Búa 1=Bao 2=Kéo ; Búa>Kéo, Kéo>Bao, Bao>Búa. Mỗi nước tối đa 1 giây.
import sys, json, random

BEAT = {0: 2, 1: 0, 2: 1}

for line in sys.stdin:
    s = json.loads(line)
    me, (gx, gy) = s["me"], s["goal"]
    b = {(x, y): (o, t) for x, y, o, t in s["pieces"]}
    moves = []
    for (x, y), (o, t) in b.items():
        if o != me:
            continue
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                nx, ny = x + dx, y + dy
                if (dx or dy) and 0 <= nx < 9 and 0 <= ny < 9:
                    c = b.get((nx, ny))
                    if c is None or (c[0] != me and BEAT[t] == c[1]):
                        moves.append((x, y, nx, ny))
    win = [m for m in moves if (m[2], m[3]) == (gx, gy)]
    cap = [m for m in moves if (m[2], m[3]) in b]
    print(*random.choice(win or cap or moves), flush=True)

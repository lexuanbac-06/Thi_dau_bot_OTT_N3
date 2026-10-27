import json
import sys

BEAT = {0: 2, 1: 0, 2: 1}
DIRECTIONS = [(dx, dy) for dx in (-1, 0, 1)
              for dy in (-1, 0, 1) if dx or dy]


def choose_move(state):
    me = state["me"]
    goal = tuple(state["goal"])
    board = state["rules"]["board"]
    pieces = {(x, y): (owner, kind)
              for x, y, owner, kind in state["pieces"]}
    walls = {tuple(cell) for cell in board["walls"]}
    protected = {tuple(cell) for zone in board["protection_zones"]
                 for cell in zone}
    teleporters = {}
    for pair in board["teleporters"]:
        first, second = map(tuple, pair["ends"])
        teleporters[first] = second
        teleporters[second] = first
    changes = {tuple(item["position"]): item["type_changes"]
               for item in board["piece_changers"]}

    moves = []
    for (x, y), (owner, kind) in pieces.items():
        if owner != me:
            continue
        destinations = [(x + dx, y + dy) for dx, dy in DIRECTIONS]
        if (x, y) in teleporters:
            destinations.append(teleporters[(x, y)])
        for nx, ny in destinations:
            if not (0 <= nx < 9 and 0 <= ny < 9) or (nx, ny) in walls:
                continue
            target = pieces.get((nx, ny))
            if target is not None and (
                    target[0] == me or (nx, ny) in protected
                    or BEAT[kind] != target[1]):
                continue

            next_kind = int(changes.get((nx, ny), {}).get(str(kind), kind))
            next_pieces = dict(pieces)
            del next_pieces[(x, y)]
            next_pieces[(nx, ny)] = (me, next_kind)
            if ((nx, ny) == goal or
                    len({t for o, t in next_pieces.values() if o != me}) < 3):
                return (x, y, nx, ny)

            distance = max(abs(nx - goal[0]), abs(ny - goal[1]))
            danger = any(
                enemy_owner != me and BEAT[enemy_kind] == next_kind
                and max(abs(ex - nx), abs(ey - ny)) == 1
                for (ex, ey), (enemy_owner, enemy_kind) in next_pieces.items()
            )
            score = -distance * 2.0
            if target is not None:
                score += 12.0
            if danger:
                score -= 5.0
            score += (8 - abs(nx - goal[0]) - abs(ny - goal[1])) * 0.05
            moves.append((score, (x, y, nx, ny)))

    return max(moves, default=(0, (-1, -1, -1, -1)))[1]


if __name__ == "__main__":
    for line in sys.stdin:
        try:
            print(*choose_move(json.loads(line)), flush=True)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            print("-1 -1 -1 -1", flush=True)

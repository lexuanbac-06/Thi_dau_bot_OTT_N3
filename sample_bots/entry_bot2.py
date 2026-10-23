"""Qualification benchmark 2: take an immediate winning capture if available."""
import random

random.seed(2)
BEAT = {0: 2, 1: 0, 2: 1}
DIRS = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]


def choose_move(state):
    board = {(x, y): (owner, kind) for x, y, owner, kind in state["pieces"]}
    me = state["me"]
    opponent = {kind for owner, kind in board.values() if owner != me}
    moves = []
    for (x, y), (owner, kind) in board.items():
        if owner != me:
            continue
        for dx, dy in DIRS:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < 9 and 0 <= ny < 9):
                continue
            target = board.get((nx, ny))
            if target is None or (target[0] != me and BEAT[kind] == target[1]):
                moves.append((x, y, nx, ny))
                if target is not None and target[0] != me:
                    remaining = {other for pos, (player, other) in board.items() if player != me and pos != (nx, ny)}
                    if len(remaining) < len(opponent) and len(remaining) < 3:
                        return x, y, nx, ny
    return random.choice(moves) if moves else (-1, -1, -1, -1)

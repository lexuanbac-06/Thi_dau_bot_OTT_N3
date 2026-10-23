"""Rule-aware board operations shared with the generated Judge0 runner."""

N = 9
BEAT = {0: 2, 1: 0, 2: 1}
DIRS = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
GOAL = {0: (8, 8), 1: (0, 0)}


def normalize_rules(data):
    if not isinstance(data, dict) or set(data) != {"schema_version", "board"}:
        raise ValueError("Rule config must contain schema_version and board")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("Unsupported rule schema_version")

    board = data["board"]
    allowed = {
        "width", "height", "walls", "protection_zones",
        "teleporters", "piece_changers",
    }
    if not isinstance(board, dict) or set(board) - allowed:
        raise ValueError("Rule board contains unsupported fields")
    if (type(board.get("width", N)) is not int
            or type(board.get("height", N)) is not int
            or board.get("width", N) != N
            or board.get("height", N) != N):
        raise ValueError("Only 9x9 boards are supported")

    special_cells = set()

    def coordinate(value, field):
        if (not isinstance(value, list) or len(value) != 2
                or any(type(part) is not int or not 0 <= part < N for part in value)):
            raise ValueError(f"{field} must be a coordinate in range 0..{N - 1}")
        return tuple(value)

    def claim(cell):
        if cell in special_cells:
            raise ValueError(f"Overlapping special cell {list(cell)}")
        special_cells.add(cell)

    walls = []
    raw_walls = board.get("walls", [])
    if not isinstance(raw_walls, list):
        raise ValueError("board.walls must be a list")
    for index, item in enumerate(raw_walls):
        cell = coordinate(item, f"board.walls[{index}]")
        claim(cell)
        walls.append(list(cell))

    protection_zones = []
    raw_zones = board.get("protection_zones", [])
    if not isinstance(raw_zones, list) or (raw_zones and len(raw_zones) != 4):
        raise ValueError("protection_zones must be empty or contain four zones")
    for index, raw_zone in enumerate(raw_zones):
        if not isinstance(raw_zone, list) or len(raw_zone) != 2:
            raise ValueError(f"protection_zones[{index}] must contain two cells")
        cells = [
            coordinate(cell, f"protection_zones[{index}][{cell_index}]")
            for cell_index, cell in enumerate(raw_zone)
        ]
        if cells[0][1] != cells[1][1] or abs(cells[0][0] - cells[1][0]) != 1:
            raise ValueError("Protection zones must be horizontally adjacent")
        for cell in cells:
            claim(cell)
        protection_zones.append([list(cell) for cell in cells])
    zone_sets = {frozenset(map(tuple, zone)) for zone in protection_zones}
    rotated_zones = {
        frozenset((N - 1 - x, N - 1 - y) for x, y in zone)
        for zone in zone_sets
    }
    if zone_sets != rotated_zones:
        raise ValueError("Protection zones must be symmetric under 180-degree rotation")

    teleporters = []
    raw_teleporters = board.get("teleporters", [])
    if not isinstance(raw_teleporters, list):
        raise ValueError("board.teleporters must be a list")
    for index, item in enumerate(raw_teleporters):
        if not isinstance(item, dict) or set(item) != {
            "ends", "activation", "use", "occupied_destination"
        }:
            raise ValueError(f"teleporters[{index}] has an invalid structure")
        ends = item["ends"]
        if not isinstance(ends, list) or len(ends) != 2:
            raise ValueError(f"teleporters[{index}].ends must contain two cells")
        first = coordinate(ends[0], f"teleporters[{index}].ends[0]")
        second = coordinate(ends[1], f"teleporters[{index}].ends[1]")
        if first == second:
            raise ValueError("A teleporter cannot connect a cell to itself")
        if item["activation"] != "piece_starts_turn_on_endpoint":
            raise ValueError("Unsupported teleporter activation")
        if item["use"] != "optional":
            raise ValueError("Teleporter use must be optional")
        if item["occupied_destination"] != "capture_if_legal":
            raise ValueError("Unsupported occupied teleporter destination behavior")
        claim(first)
        claim(second)
        teleporters.append({
            "ends": [list(first), list(second)],
            "activation": item["activation"],
            "use": item["use"],
            "occupied_destination": item["occupied_destination"],
        })

    piece_changers = []
    raw_changers = board.get("piece_changers", [])
    if not isinstance(raw_changers, list) or len(raw_changers) > 1:
        raise ValueError("At most one piece changer is supported")
    for index, item in enumerate(raw_changers):
        if not isinstance(item, dict) or set(item) != {
            "position", "activation", "type_changes"
        }:
            raise ValueError(f"piece_changers[{index}] has an invalid structure")
        cell = coordinate(item["position"], f"piece_changers[{index}].position")
        if cell != (N // 2, N // 2):
            raise ValueError("The piece changer must be at the center of the board")
        if item["activation"] != "on_enter":
            raise ValueError("Piece changer activation must be on_enter")
        changes = item["type_changes"]
        if not isinstance(changes, dict) or changes != {"0": 2, "1": 0, "2": 1}:
            raise ValueError("Unsupported piece changer cycle")
        claim(cell)
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


def initial():
    board = {}
    for x in range(N):
        board[(x, 0)] = (0, x % 3)
        board[(x, N - 1)] = (1, x % 3)
    return board


def _can_enter(board, player, piece_type, destination, walls, protected_cells):
    if destination in walls:
        return False
    occupant = board.get(destination)
    if occupant is None:
        return True
    return (
        occupant[0] != player
        and destination not in protected_cells
        and BEAT[piece_type] == occupant[1]
    )


def _teleporter_destinations(rules):
    destinations = {}
    for teleporter in rules["board"]["teleporters"]:
        first, second = map(tuple, teleporter["ends"])
        destinations[first] = second
        destinations[second] = first
    return destinations


def legal_moves(board, player, rules):
    moves = []
    walls = {tuple(cell) for cell in rules["board"]["walls"]}
    protected_cells = {
        tuple(cell)
        for zone in rules["board"]["protection_zones"]
        for cell in zone
    }
    teleporters = _teleporter_destinations(rules)
    for (x, y), (owner, piece_type) in board.items():
        if owner != player:
            continue
        for dx, dy in DIRS:
            nx, ny = x + dx, y + dy
            if 0 <= nx < N and 0 <= ny < N:
                destination = (nx, ny)
                if _can_enter(board, player, piece_type, destination, walls, protected_cells):
                    moves.append((x, y, nx, ny))
        destination = teleporters.get((x, y))
        if destination is not None and _can_enter(
            board, player, piece_type, destination, walls, protected_cells
        ):
            move = (x, y, destination[0], destination[1])
            if move not in moves:
                moves.append(move)
    return moves


def apply_move(board, move, rules):
    x, y, nx, ny = move
    updated = dict(board)
    piece = updated.pop((x, y))
    changer_positions = {
        tuple(changer["position"]): changer["type_changes"]
        for changer in rules["board"]["piece_changers"]
    }
    changes = changer_positions.get((nx, ny))
    if changes:
        piece = (piece[0], changes[str(piece[1])])
    updated[(nx, ny)] = piece
    return updated


def encode_state(board, player, ply, rules):
    return {
        "me": player,
        "ply": ply,
        "goal": list(GOAL[player]),
        "pieces": [[x, y, owner, kind] for (x, y), (owner, kind) in board.items()],
        "rules": rules,
    }


def check_win(board, player, move, rules):
    if (move[2], move[3]) == GOAL[player]:
        return True
    return len({kind for (owner, kind) in board.values() if owner != player}) < 3

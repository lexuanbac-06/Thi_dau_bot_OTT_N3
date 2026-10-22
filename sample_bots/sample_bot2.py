# -*- coding: utf-8 -*-

import sys
import json
import math

BEAT = {
    0: 2,  # Hammer > Scissors
    1: 0,  # Paper  > Hammer
    2: 1,  # Scissors > Paper
}

DIRECTIONS = [
    (dx, dy)
    for dx in (-1, 0, 1)
    for dy in (-1, 0, 1)
    if dx != 0 or dy != 0
]

INF = 10**9


def chebyshev(x1, y1, x2, y2):
    return max(abs(x1 - x2), abs(y1 - y2))


def build_board(state):
    return {
        (x, y): (owner, typ)
        for x, y, owner, typ in state["pieces"]
    }


def legal_moves(board, me):
    moves = []

    for (x, y), (owner, typ) in board.items():
        if owner != me:
            continue

        for dx, dy in DIRECTIONS:
            nx = x + dx
            ny = y + dy

            if not (0 <= nx < 9 and 0 <= ny < 9):
                continue

            target = board.get((nx, ny))

            # Empty
            if target is None:
                moves.append((x, y, nx, ny))
                continue

            # Enemy and can capture
            if target[0] != me and BEAT[typ] == target[1]:
                moves.append((x, y, nx, ny))

    return moves


def apply_move(board, move):
    """
    Return board after move.
    """
    x, y, nx, ny = move

    new_board = board.copy()

    piece = new_board.pop((x, y))

    # Capture
    new_board.pop((nx, ny), None)

    new_board[(nx, ny)] = piece

    return new_board


def is_dangerous(board, pos, owner, typ):
    """
    Check whether piece at pos can be captured immediately.
    """
    x, y = pos

    for dx, dy in DIRECTIONS:
        px = x + dx
        py = y + dy

        if not (0 <= px < 9 and 0 <= py < 9):
            continue

        enemy = board.get((px, py))

        if enemy is None:
            continue

        enemy_owner, enemy_type = enemy

        if enemy_owner != owner:
            if BEAT[enemy_type] == typ:
                return True

    return False


def winning_move(board, move, me, goal):
    """
    Determine immediate winning moves.
    """
    x, y, nx, ny = move

    # Goal
    if (nx, ny) == tuple(goal):
        return True

    target = board.get((nx, ny))

    # Capture
    if target is not None and target[0] != me:
        opponent_types = {
            typ
            for (px, py), (owner, typ) in board.items()
            if owner != me
        }

        remaining_types = {
            typ
            for (px, py), (owner, typ) in board.items()
            if owner != me and (px, py) != (nx, ny)
        }

        # Same logic as sample bot:
        # if the captured piece removes the last representative
        # of some type.
        if len(remaining_types) < len(opponent_types):
            return True

    return False


def immediate_winning_moves(board, me, goal):
    result = []

    for move in legal_moves(board, me):
        if winning_move(board, move, me, goal):
            result.append(move)

    return result


def piece_count(board, owner):
    return sum(
        1 for (x, y), (o, typ) in board.items()
        if o == owner
    )


def type_count(board, owner):
    result = [0, 0, 0]

    for (x, y), (o, typ) in board.items():
        if o == owner:
            result[typ] += 1

    return result


def mobility(board, owner):
    return len(legal_moves(board, owner))


def evaluate(board, me, goal):
    """
    Evaluation from perspective of `me`.
    """

    opp = 1 - me

    my_pieces = [
        ((x, y), typ)
        for (x, y), (owner, typ) in board.items()
        if owner == me
    ]

    enemy_pieces = [
        ((x, y), typ)
        for (x, y), (owner, typ) in board.items()
        if owner == opp
    ]

    # ------------------------------------------------------------
    # Terminal
    # ------------------------------------------------------------

    if not my_pieces:
        return -100000

    if not enemy_pieces:
        return 100000

    # ------------------------------------------------------------
    # Piece count
    # ------------------------------------------------------------

    score = 0

    score += (len(my_pieces) - len(enemy_pieces)) * 35

    # ------------------------------------------------------------
    # Distance to goal
    # ------------------------------------------------------------

    my_distance = sum(
        chebyshev(x, y, goal[0], goal[1])
        for (x, y), typ in my_pieces
    )

    enemy_goal = (8 - goal[0], 8 - goal[1])

    enemy_distance = sum(
        chebyshev(x, y, enemy_goal[0], enemy_goal[1])
        for (x, y), typ in enemy_pieces
    )

    # Lower own distance is better
    score += (enemy_distance - my_distance) * 7

    # ------------------------------------------------------------
    # Dangerous pieces
    # ------------------------------------------------------------

    for (x, y), typ in my_pieces:
        if is_dangerous(board, (x, y), me, typ):
            score -= 18

    for (x, y), typ in enemy_pieces:
        if is_dangerous(board, (x, y), opp, typ):
            score += 18

    # ------------------------------------------------------------
    # Mobility
    # ------------------------------------------------------------

    my_mobility = mobility(board, me)
    enemy_mobility = mobility(board, opp)

    score += (my_mobility - enemy_mobility) * 2

    # ------------------------------------------------------------
    # Type advantage
    #
    # If enemy has a type and we possess its counter,
    # that is valuable.
    # ------------------------------------------------------------

    my_types = type_count(board, me)
    enemy_types = type_count(board, opp)

    for my_type in range(3):
        beaten_type = BEAT[my_type]

        if my_types[my_type] > 0 and enemy_types[beaten_type] > 0:
            score += 5

    # ------------------------------------------------------------
    # Threats
    #
    # Reward pieces that can capture enemy next turn.
    # ------------------------------------------------------------

    for (x, y), typ in my_pieces:
        for dx, dy in DIRECTIONS:
            tx = x + dx
            ty = y + dy

            enemy = board.get((tx, ty))

            if enemy and enemy[0] == opp:
                if BEAT[typ] == enemy[1]:
                    score += 12

    # ------------------------------------------------------------
    # Enemy threats
    # ------------------------------------------------------------

    for (x, y), typ in enemy_pieces:
        for dx, dy in DIRECTIONS:
            tx = x + dx
            ty = y + dy

            mine = board.get((tx, ty))

            if mine and mine[0] == me:
                if BEAT[typ] == mine[1]:
                    score -= 14

    return score


def move_order_score(board, move, me, goal):
    """
    Move ordering rất quan trọng cho alpha-beta.
    """

    x, y, nx, ny = move

    piece = board[(x, y)]
    typ = piece[1]

    target = board.get((nx, ny))

    score = 0

    # Immediate win
    if (nx, ny) == tuple(goal):
        score += 100000

    # Capture
    if target is not None and target[0] != me:
        score += 5000

        # Prefer removing a type completely
        enemy_type = target[1]

        remaining = any(
            owner != me
            and ptype == enemy_type
            and pos != (nx, ny)
            for pos, (owner, ptype) in board.items()
        )

        if not remaining:
            score += 3000

    # Distance improvement
    old_d = chebyshev(x, y, goal[0], goal[1])
    new_d = chebyshev(nx, ny, goal[0], goal[1])

    score += (old_d - new_d) * 100

    # Don't walk directly into death
    temp = apply_move(board, move)

    if is_dangerous(temp, (nx, ny), me, typ):
        score -= 300

    return score


def ordered_moves(board, me, goal):
    moves = legal_moves(board, me)

    moves.sort(
        key=lambda m: move_order_score(board, m, me, goal),
        reverse=True
    )

    return moves


def minimax(board, root_me, current_player, goal, depth, alpha, beta):
    """
    Negamax-style minimax.
    """

    opponent = 1 - current_player

    # Immediate terminal state
    if not any(owner == current_player for owner, typ in board.values()):
        if current_player == root_me:
            return -100000

    if not any(owner == opponent for owner, typ in board.values()):
        if opponent == root_me:
            return 100000

    moves = ordered_moves(board, current_player, goal)

    if not moves:
        return evaluate(board, root_me, goal)

    if depth == 0:
        return evaluate(board, root_me, goal)

    maximizing = current_player == root_me

    if maximizing:
        value = -INF

        for move in moves:
            new_board = apply_move(board, move)

            # Immediate goal
            if (move[2], move[3]) == tuple(goal):
                child = 100000
            else:
                child = minimax(
                    new_board,
                    root_me,
                    opponent,
                    goal,
                    depth - 1,
                    alpha,
                    beta
                )

            value = max(value, child)

            alpha = max(alpha, value)

            if alpha >= beta:
                break

        return value

    else:
        value = INF

        for move in moves:
            new_board = apply_move(board, move)

            enemy_goal = (8 - goal[0], 8 - goal[1])

            if (move[2], move[3]) == enemy_goal:
                child = -100000
            else:
                child = minimax(
                    new_board,
                    root_me,
                    opponent,
                    goal,
                    depth - 1,
                    alpha,
                    beta
                )

            value = min(value, child)

            beta = min(beta, value)

            if alpha >= beta:
                break

        return value


def choose_best_move(state):
    me = state["me"]
    goal = tuple(state["goal"])

    board = build_board(state)

    moves = ordered_moves(board, me, goal)

    if not moves:
        return None

    # ------------------------------------------------------------
    # ALWAYS take immediate winning move
    # ------------------------------------------------------------

    wins = immediate_winning_moves(board, me, goal)

    if wins:
        return wins[0]

    # ------------------------------------------------------------
    # Search
    #
    # Depth 3 = our move -> enemy move -> our move
    #
    # Depth 4 is stronger but more expensive.
    # ------------------------------------------------------------

    depth = 4

    best_move = moves[0]
    best_score = -INF

    for move in moves:
        new_board = apply_move(board, move)

        # If this move immediately reaches goal
        if (move[2], move[3]) == goal:
            return move

        score = minimax(
            new_board,
            me,
            1 - me,
            goal,
            depth - 1,
            -INF,
            INF
        )

        # Small deterministic tie breaker:
        # prefer getting closer to goal.
        x, y, nx, ny = move

        old_d = chebyshev(x, y, goal[0], goal[1])
        new_d = chebyshev(nx, ny, goal[0], goal[1])

        score += (old_d - new_d) * 0.1

        if score > best_score:
            best_score = score
            best_move = move

    return best_move


def main():
    for line in sys.stdin:
        line = line.strip()

        if not line:
            continue

        try:
            state = json.loads(line)

            move = choose_best_move(state)

            if move is not None:
                print(
                    f"{move[0]} {move[1]} "
                    f"{move[2]} {move[3]}",
                    flush=True
                )

        except Exception as e:
            # Không in lỗi ra stdout vì protocol yêu cầu
            # stdout chỉ chứa nước đi.
            pass


if __name__ == "__main__":
    main()
# -*- coding: utf-8 -*-
"""
BOT MẪU OTTv2 (BENCHMARK BOT) - GIẢI ĐẤU THI ĐẤU BOT OẰN TÙ TÌ
=============================================================
Giao thức:
- Mỗi lượt engine gửi 1 dòng JSON qua stdin:
    state = {
        "me": 0 | 1,          # 0 = đi trước (hàng 1, đích là i9=(8,8)), 1 = đi sau (hàng 9, đích là a1=(0,0))
        "ply": số_nước_đã_đi, # số thứ tự nước đi (bắt đầu từ 0)
        "goal": [gx, gy],     # toạ độ ô đích cần đưa quân đến
        "pieces": [           # danh sách quân cờ trên bàn
            [x, y, chủ, loại], ... # x, y: 0..8 (cột a..i, hàng 1..9)
        ]
    }
- Loại quân: 0 = Búa (Hammer), 1 = Bao (Paper), 2 = Kéo (Scissors)
  Quy tắc khắc chế: Búa > Kéo, Kéo > Bao, Bao > Búa.
- Nước đi hợp lệ: Di chuyển 1 ô theo 8 hướng vào ô trống hoặc ô quân địch bị mình khắc chế.
- Đầu ra stdout: In đúng 1 dòng dạng "x y nx ny" và flush dữ liệu.
"""
import sys
import json
import random

# Bảng quy tắc: BEAT[loại_mình] = loại quân địch bị mình ăn
BEAT = {
    0: 2,  # Búa (0) ăn Kéo (2)
    1: 0,  # Bao (1) ăn Búa (0)
    2: 1   # Kéo (2) ăn Bao (1)
}

# 8 hướng di chuyển xung quanh 1 ô (ngang, dọc, chéo)
DIRECTIONS = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]


def chebyshev_distance(x1, y1, x2, y2):
    """Khoảng cách số bước đi tối thiểu trên bàn cờ 8 hướng."""
    return max(abs(x1 - x2), abs(y1 - y2))


def get_legal_moves(board, me):
    """Tìm tất cả các nước đi hợp lệ của người chơi 'me'."""
    legal = []
    for (x, y), (owner, p_type) in board.items():
        if owner != me:
            continue
        for dx, dy in DIRECTIONS:
            nx, ny = x + dx, y + dy
            if 0 <= nx < 9 and 0 <= ny < 9:
                target = board.get((nx, ny))
                # Đi vào ô trống HOẶC ăn quân địch mà mình khắc chế
                if target is None or (target[0] != me and BEAT[p_type] == target[1]):
                    legal.append((x, y, nx, ny))
    return legal


def choose_best_move(state):
    """
    Thuật toán ra quyết định của bot mẫu:
    1. Ưu tiên 1: Nước đi thắng ngay (vào ô đích hoặc ăn quân cuối cùng của 1 loại quân đối phương).
    2. Ưu tiên 2: Ăn quân đối thủ và tránh rơi vào ô bị địch phản kích.
    3. Ưu tiên 3: Tiến dần về phía ô đích đối thủ an toàn.
    4. Ưu tiên 4: Chọn nước đi hợp lệ an toàn nhất.
    """
    me = state["me"]
    gx, gy = state["goal"]
    board = {(x, y): (owner, p_type) for x, y, owner, p_type in state["pieces"]}

    moves = get_legal_moves(board, me)
    if not moves:
        return None

    # Đếm số lượng từng loại quân còn lại của đối phương
    opponent_types = set(p_type for (x, y), (owner, p_type) in board.items() if owner != me)

    # 1. Tìm nước đi thắng ngay lập tức
    for m in moves:
        x, y, nx, ny = m
        # Thắng bằng cách chạm đích
        if (nx, ny) == (gx, gy):
            return m
        # Thắng bằng cách triệt hạ loại quân cuối cùng của đối thủ
        target = board.get((nx, ny))
        if target and target[0] != me:
            rem = set(p_type for (px, py), (owner, p_type) in board.items() if owner != me and (px, py) != (nx, ny))
            if len(rem) < len(opponent_types) and len(rem) < 3:
                return m

    # 2. Đánh giá điểm từng nước đi
    scored_moves = []
    for m in moves:
        x, y, nx, ny = m
        my_type = board[(x, y)][1]
        target = board.get((nx, ny))

        score = 0.0

        # Điểm ăn quân
        if target is not None and target[0] != me:
            score += 15.0

        # Điểm tiến về đích (càng gần đích càng được cộng điểm)
        curr_dist = chebyshev_distance(x, y, gx, gy)
        new_dist = chebyshev_distance(nx, ny, gx, gy)
        score += (curr_dist - new_dist) * 3.5

        # Kiểm tra an toàn: Nếu ô mới đến nằm trong tầm ngắm của quân địch khắc mình -> trừ điểm
        in_danger = False
        for dx, dy in DIRECTIONS:
            tx, ty = nx + dx, ny + dy
            if 0 <= tx < 9 and 0 <= ty < 9:
                threat = board.get((tx, ty))
                # Quân địch ở ô (tx, ty) có ăn được my_type không?
                if threat and threat[0] != me and (tx, ty) != (nx, ny):
                    if BEAT[threat[1]] == my_type:
                        in_danger = True
                        break

        if in_danger:
            score -= 10.0

        # Thêm chút yếu tố ngẫu nhiên để tránh bot bị lặp nước đi
        score += random.random() * 0.5
        scored_moves.append((score, m))

    # Chọn nước đi có điểm đánh giá cao nhất
    scored_moves.sort(key=lambda item: item[0], reverse=True)
    return scored_moves[0][1]


def main():
    """Vòng lặp nhận dữ liệu từ stdin và in nước đi ra stdout."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            state = json.loads(line)
            move = choose_best_move(state)
            if move:
                print(f"{move[0]} {move[1]} {move[2]} {move[3]}", flush=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()

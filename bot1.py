import random

FILES = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i']
RANKS = ['1', '2', '3', '4', '5', '6', '7', '8', '9']

DIRECTIONS = [
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),          (0, 1),
    (1, -1),  (1, 0),  (1, 1)
]

def is_valid_pos(r, c):
    return 0 <= r < 9 and 0 <= c < 9

def pos_to_str(r, c):
    return f"{FILES[c]}{RANKS[r]}"

def str_to_pos(pos_str):
    c = FILES.index(pos_str[0])
    r = RANKS.index(pos_str[1])
    return r, c

def get_next_move(game_state, player_side):
    """
    Hàm tính toán nước đi chính cho Bot 2
    """
    target_win_pos = 'i9' if player_side == 'B' else 'a1'
    enemy_win_pos = 'a1' if player_side == 'B' else 'i9'
    
    valid_moves = []

    # Quét tất cả quân cờ của phe mình
    for pos_str, piece in game_state.items():
        if piece.endswith(player_side):
            r, c = str_to_pos(pos_str)
            p_type = piece.split('_')[0]

            for dr, dc in DIRECTIONS:
                nr, nc = r + dr, c + dc
                if not is_valid_pos(nr, nc):
                    continue

                dest_str = pos_to_str(nr, nc)
                dest_piece = game_state.get(dest_str, None)

                # Quy tắc đứng chặn: Không thể đi vào ô có quân cùng phe hoặc quân cùng loại
                if dest_piece:
                    dest_type = dest_piece.split('_')[0]
                    dest_side = dest_piece.split('_')[-1]
                    if dest_side == player_side or dest_type == p_type:
                        continue

                # Chấm điểm nước đi
                score = 0

                # 1. Đi vào ô thắng
                if dest_str == target_win_pos:
                    score += 9999

                # 2. Ăn quân đối phương
                if dest_piece and dest_piece.split('_')[-1] != player_side:
                    score += 400

                # 3. Chặn đường vào ô thắng của đối phương
                er, ec = str_to_pos(enemy_win_pos)
                if abs(nr - er) <= 1 and abs(nc - ec) <= 1:
                    score += 50

                # 4. Giảm khoảng cách tới ô thắng của mình
                tr, tc = str_to_pos(target_win_pos)
                dist_after = abs(nr - tr) + abs(nc - tc)
                score -= dist_after  # Càng gần càng ít điểm trừ

                valid_moves.append(((pos_str, dest_str), score))

    if not valid_moves:
        return None

    # Sắp xếp các nước đi theo điểm số giảm dần và chọn nước đi tốt nhất
    valid_moves.sort(key=lambda x: x[1], reverse=True)
    return valid_moves[0][0]

if __name__ == "__main__":
    # Test giả định trạng thái
    sample_board = {
        'h8': 'SCISSORS_B',
        'g7': 'ROCK_A'
    }
    move = get_next_move(sample_board, 'B')
    print("Bot 2 chọn nước đi:", move)
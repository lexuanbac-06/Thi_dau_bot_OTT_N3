import random

# Định nghĩa bàn cờ 9x9 (Hàng từ 1-9, Cột từ a-i)
FILES = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i']
RANKS = ['1', '2', '3', '4', '5', '6', '7', '8', '9']

# 8 hướng di chuyển như quân Vua trong cờ vua
DIRECTIONS = [
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),          (0, 1),
    (1, -1),  (1, 0),  (1, 1)
]

def is_valid_pos(r, c):
    """Kiểm tra tọa độ có nằm trong bàn cờ 9x9 hay không"""
    return 0 <= r < 9 and 0 <= c < 9

def pos_to_str(r, c):
    """Chuyển tọa độ dòng/cột thành chuỗi dạng 'a1', 'i9'"""
    return f"{FILES[c]}{RANKS[r]}"

def str_to_pos(pos_str):
    """Chuyển chuỗi 'a1' thành tọa độ dòng/cột"""
    c = FILES.index(pos_str[0])
    r = RANKS.index(pos_str[1])
    return r, c

def get_next_move(game_state, player_side):
    """
    Hàm tính toán nước đi chính cho Bot 1
    game_state: Dict chứa trạng thái bàn cờ, ví dụ: {'a1': 'R_B', 'i9': 'R_A', ...}
    player_side: Side của người chơi ('A' hoặc 'B')
    """
    target_win_pos = 'a1' if player_side == 'A' else 'i9'
    my_prefix = f"R_{player_side}" if player_side == 'A' else f"R_{player_side}" # Hoặc ký hiệu quân của bên A/B
    
    my_pieces = []
    # Quét bàn cờ tìm các quân của mình
    for pos_str, piece in game_state.items():
        if piece.endswith(player_side):  # Quân thuộc sở hữu của phe mình
            r, c = str_to_pos(pos_str)
            piece_type = piece.split('_')[0] # Ví dụ: 'R' (Đấm/Rock), 'P' (Lá/Paper), 'S' (Kéo/Scissors)
            my_pieces.append((r, c, pos_str, piece_type))

    best_move = None
    best_score = -9999

    for r, c, pos_str, p_type in my_pieces:
        for dr, dc in DIRECTIONS:
            nr, nc = r + dr, c + dc
            if not is_valid_pos(nr, nc):
                continue
            
            dest_str = pos_to_str(nr, nc)
            dest_piece = game_state.get(dest_str, None)

            # 1. Kiểm tra nếu ô đích có quân cùng loại của mình hoặc địch -> Không thể đi vào/ăn (Đứng chặn đường)
            if dest_piece:
                dest_type = dest_piece.split('_')[0]
                dest_side = dest_piece.split('_')[-1]
                
                # Cùng phe -> Chặn đường, không đi được
                if dest_side == player_side:
                    continue
                # Cùng loại quân (ví dụ Đấm gặp Đấm) -> Không thể ăn nhau, đứng chặn đường
                if dest_type == p_type:
                    continue

            # Tính điểm ưu tiên cho nước đi
            score = 0
            
            # Ưu tiên 1: Đưa quân vào ô thắng
            if dest_str == target_win_pos:
                score += 10000

            # Ưu tiên 2: Ăn quân đối phương khác loại
            if dest_piece and dest_piece.split('_')[-1] != player_side:
                score += 500

            # Ưu tiên 3: Di chuyển lại gần ô thắng
            target_r, target_c = str_to_pos(target_win_pos)
            dist_before = abs(r - target_r) + abs(c - target_c)
            dist_after = abs(nr - target_r) + abs(nc - target_c)
            if dist_after < dist_before:
                score += 10

            if score > best_score:
                best_score = score
                best_move = (pos_str, dest_str)

    # Nếu không tìm thấy nước đi tối ưu, chọn ngẫu nhiên một nước đi hợp lệ
    if not best_move and my_pieces:
        r, c, pos_str, _ = random.choice(my_pieces)
        for dr, dc in DIRECTIONS:
            nr, nc = r + dr, c + dc
            if is_valid_pos(nr, nc):
                best_move = (pos_str, pos_to_str(nr, nc))
                break

    return best_move

if __name__ == "__main__":
    # Test giả định trạng thái
    sample_board = {
        'b2': 'ROCK_A',
        'c3': 'PAPER_B',
        'a2': 'ROCK_A'
    }
    move = get_next_move(sample_board, 'A')
    print("Bot 1 chọn nước đi:", move)
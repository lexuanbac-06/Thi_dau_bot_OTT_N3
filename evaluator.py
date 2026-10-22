# -*- coding: utf-8 -*-
"""
Module chấm điểm và đánh giá bot thí sinh khi thi đấu với bot mẫu (benchmark_bot).
"""
import os
import time
import engine


def chebyshev(x1, y1, x2, y2):
    return max(abs(x1 - x2), abs(y1 - y2))


def evaluate_bot_match(user_bot_path, sample_bot_path="sample_bot.py"):
    """
    Chạy trận BO2 giữa bot thí sinh và bot mẫu.
    Trả về cấu trúc chi tiết phục vụ hiển thị tiêu chí chấm và điểm cuối cùng.
    """
    if not os.path.isfile(user_bot_path):
        raise FileNotFoundError(f"Không tìm thấy file bot: {user_bot_path}")
    if not os.path.isfile(sample_bot_path):
        raise FileNotFoundError(f"Không tìm thấy bot mẫu: {sample_bot_path}")

    start_time = time.time()
    # Chạy trận đấu ghi hình 2 ván BO2
    # s là tổng điểm ván của A (thí sinh) qua 2 ván [-2, 2]
    s, games = engine.play_match_recorded((user_bot_path, sample_bot_path))
    duration = time.time() - start_time

    # Phân tích từng ván đấu
    game_details = []
    total_captures_by_user = 0
    total_losses_by_user = 0
    total_moves_by_user = 0
    min_dist_to_goal = 999

    for idx, g in enumerate(games):
        # g["players"]: ["a", "b"] nếu thí sinh đi trước, hoặc ["b", "a"] nếu bot mẫu đi trước
        # "a" là thí sinh, "b" là bot mẫu
        user_is_first = (g["players"][0] == "a")
        user_player_idx = 0 if user_is_first else 1
        user_goal = (8, 8) if user_player_idx == 0 else (0, 0)

        # Kết quả ván từ góc nhìn của thí sinh: +1 thắng, -1 thua, 0 hòa
        res = g["result"]
        res_str = "Thắng (+1)" if res > 0 else ("Thua (-1)" if res < 0 else "Hòa (0)")

        # Phân tích các nước đi để tính số quân ăn được và số quân mất
        board = engine.initial()
        v_captures = 0
        v_losses = 0
        v_user_moves = 0
        closest_goal_in_game = chebyshev(0, 0 if user_player_idx == 0 else 8, user_goal[0], user_goal[1])

        moves_data = g.get("moves") or []
        for p, m in moves_data:
            x, y, nx, ny = m
            is_user = (p == user_player_idx)
            target = board.get((nx, ny))

            if is_user:
                v_user_moves += 1
                dist = chebyshev(nx, ny, user_goal[0], user_goal[1])
                if dist < closest_goal_in_game:
                    closest_goal_in_game = dist
                if target is not None and target[0] != user_player_idx:
                    v_captures += 1
            else:
                if target is not None and target[0] == user_player_idx:
                    v_losses += 1

            board = engine.apply(board, m)

        total_captures_by_user += v_captures
        total_losses_by_user += v_losses
        total_moves_by_user += v_user_moves
        if closest_goal_in_game < min_dist_to_goal:
            min_dist_to_goal = closest_goal_in_game

        # Xác định nguyên nhân kết thúc ván
        if res > 0:
            if moves_data and (moves_data[-1][1][2], moves_data[-1][1][3]) == user_goal:
                reason = "Thí sinh đưa quân chạm đích đối thủ!"
            elif len(set(t for (o, t) in board.values() if o != user_player_idx)) < 3:
                reason = "Thí sinh ăn hết 1 loại quân của bot mẫu!"
            else:
                reason = "Bot mẫu hết nước đi hợp lệ hoặc phạm quy."
        elif res < 0:
            opp_goal = (0, 0) if user_player_idx == 0 else (8, 8)
            if moves_data and (moves_data[-1][1][2], moves_data[-1][1][3]) == opp_goal:
                reason = "Bot mẫu đưa quân chạm đích của thí sinh."
            elif len(set(t for (o, t) in board.values() if o == user_player_idx)) < 3:
                reason = "Bot mẫu đã ăn hết 1 loại quân của thí sinh."
            else:
                reason = "Thí sinh hết nước đi hợp lệ, timeout hoặc phạm quy."
        else:
            reason = "Hòa sau 200 nước đi cân não."

        game_details.append({
            "game_number": idx + 1,
            "role": "Đi trước (Bắt đầu ở hàng 1, đích i9)" if user_is_first else "Đi sau (Bắt đầu ở hàng 9, đích a1)",
            "result": res,
            "result_text": res_str,
            "total_plies": len(moves_data),
            "user_moves": v_user_moves,
            "user_captures": v_captures,
            "user_losses": v_losses,
            "closest_to_goal": closest_goal_in_game,
            "end_reason": reason,
        })
        print(f"  [VÁN {idx + 1}] {res_str} | Số nước: {len(moves_data)} | Ăn: {v_captures} - Mất: {v_losses} | Lý do: {reason}", flush=True)

    # Điểm trận BO2:
    match_pts = 1 if s > 0 else (-1 if s < 0 else 0)
    match_result_str = "THẮNG CHUNG CUỘC" if match_pts > 0 else ("THUA CHUNG CUỘC" if match_pts < 0 else "HÒA CHUNG CUỘC")

    # Đánh giá tiêu chuẩn đầu vào
    passed_entry = (s >= -1)
    status_text = "ĐẠT CHUẨN THI ĐẤU" if passed_entry else "CẦN TỐI ƯU THÊM"

    # Tính điểm quy đổi trên thang 100
    has_fault = any("Thí sinh hết nước đi" in g["end_reason"] or "timeout" in g["end_reason"] or "phạm quy" in g["end_reason"] for g in game_details)
    validity_pts = 15 if has_fault else 30
    offense_pts = min(30, max(0, total_captures_by_user * 6 + max(0, 8 - min_dist_to_goal) * 2))
    defense_pts = max(0, 25 - total_losses_by_user * 4)
    avg_ms = (duration / max(total_moves_by_user, 1)) * 1000
    speed_pts = 15 if avg_ms < 300 else (10 if avg_ms < 800 else 5)
    converted_score = max(10, min(100, validity_pts + offense_pts + defense_pts + speed_pts + (s * 5)))

    # Lời khuyên thuật toán
    tips = []
    if total_losses_by_user > total_captures_by_user:
        tips.append("Bot của bạn bị ăn nhiều quân hơn đối thủ. Hãy thêm kiểm tra 'in_danger' trước khi di chuyển để tránh đi vào tầm ngắm của quân khắc.")
    if min_dist_to_goal > 4:
        tips.append("Quân của bạn chưa tiến sâu về phía ô đích đối thủ. Hãy tăng trọng số điểm thưởng khi tiến gần đích.")
    if s < 0:
        tips.append("Hãy tham khảo bot mẫu để ưu tiên các nước đi thắng ngay khi có cơ hội chạm đích hoặc triệt hạ loại quân cuối cùng.")
    else:
        tips.append("Bot của bạn có phong độ rất tốt! Hãy tiếp tục tối ưu hóa thuật toán tìm kiếm nước đi sâu hơn (Minimax / Alpha-Beta).")

    print(f"[KẾT QUẢ CHẤM] {match_result_str} (Điểm ván: {s:+d} | Điểm trận: {match_pts:+d} | Điểm quy đổi: {converted_score}/100) - {status_text}", flush=True)

    return {
        "ok": True,
        "converted_score": converted_score, # Thang điểm 100
        "match_score": s,                   # Điểm ván: [-2, +2]
        "match_pts": match_pts,             # Điểm trận: +1 / 0 / -1
        "match_result": match_result_str,
        "passed": passed_entry,
        "status_badge": status_text,
        "duration_seconds": round(duration, 2),
        "criteria": {
            "validity": {
                "name": "Tính hợp lệ & Ổn định",
                "score": f"{validity_pts}/30",
                "status": "PASS" if not has_fault else "CẢNH BÁO",
                "desc": "Mọi nước đi đều tuân thủ luật cờ." if not has_fault else "Có ván kết thúc do timeout, lỗi runtime hoặc không còn nước đi.",
            },
            "offense": {
                "name": "Năng lực Tấn công",
                "score": f"{offense_pts}/30",
                "status": "Tốt" if total_captures_by_user >= 2 else "Trung bình",
                "desc": f"Ăn được {total_captures_by_user} quân địch qua 2 ván đấu, áp sát đích cự ly {min_dist_to_goal} ô.",
            },
            "defense": {
                "name": "Năng lực Phòng thủ",
                "score": f"{defense_pts}/25",
                "status": "Tốt" if total_losses_by_user <= 2 else "Cần chú ý",
                "desc": f"Để mất {total_losses_by_user} quân trước các đợt phản công của bot mẫu.",
            },
            "speed": {
                "name": "Tốc độ xử lý",
                "score": f"{speed_pts}/15 ({round(avg_ms, 1)} ms)",
                "status": "Cực nhanh (< 1.0s)" if avg_ms < 500 else "Đạt yêu cầu",
                "desc": f"Thời gian phản hồi trung bình: {round(avg_ms, 1)} ms/nước đi.",
            },
        },
        "games": game_details,
        "raw_games": games,                 # Phục vụ vẽ lại bàn cờ Replay trực tiếp
        "tips": tips,
    }

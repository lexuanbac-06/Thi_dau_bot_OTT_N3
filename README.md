# OTTv2 – Hệ thống thi đấu code Oẳn Tù Tì

## Cấu trúc
| File | Vai trò |
|---|---|
| `engine.py` | Luật chơi, sandbox chạy bot, 3 bot BTC (`btc0` ngẫu nhiên, `btc1` tham lam, `btc2` chấm điểm 1 nước), trận BO2. Thí sinh test local: `python engine.py test bot.py` |
| `tournament.py` | Đăng ký/nộp bài, thi đầu vào, chia bảng, chấm ngày (7 trận), vé vớt, lên vòng + CLI quản trị |
| `server.py` | API Flask cho thí sinh: `/register`, `/submit`, `/me`, `/leaderboard` |
| `sample_bot.py` | Bot mẫu + mô tả giao thức cho thí sinh |

## Giao thức bot
Bot là file `.py` đọc stdin / ghi stdout. Mỗi lượt nhận 1 dòng JSON
`{"me":0|1,"ply":n,"goal":[x,y],"pieces":[[x,y,chủ,loại],...]}` và in `x y nx ny` (toạ độ 0..8, x=cột a..i, y=hàng 1..9).
Loại: 0=Búa, 1=Bao, 2=Kéo. Giới hạn 1s/nước (3s nước đầu), 512MB RAM, không file/process/mạng.

## Quy trình vận hành
```bash
pip install flask
python server.py                    # mở cổng nhận bài (nên đặt sau nginx + HTTPS)

# Hết hạn thi đầu vào:
python tournament.py entry-close    # chấm vs bot BTC, loại điểm thấp, chia bảng

# Cron mỗi ngày:
0 0 * * *  cd /path/ott && python tournament.py close   # chốt hạn 12h đêm, snapshot bài
0 1 * * *  cd /path/ott && python tournament.py grade   # chấm 1h-5h, ngày 7 tự xét lên vòng
```
Ngày 7 của vòng, `grade` tự chọn người đi tiếp, tạo bảng vòng sau và đưa `day` về 1.
Vòng 5 (offline): chạy cùng bộ code trên máy tại điểm thi, BTC nhập bài bằng `python tournament.py add-bot TEN file.py`
rồi `close` / `grade` như bình thường (cần chuyển DB sang `member` vòng 5 trước, hoặc copy `ott.db`).

## Cách hiện thực các luật
- **Đầu vào**: mỗi thí sinh đấu BO2 với 3 bot BTC; `entry = 1·s0 + 2·s1 + 3·s2` (mỗi `s` thuộc [-2,2]). `entry < entry_cut` bị loại.
  Sau đó sắp theo điểm, cắt thành các nhóm `G` người (G = số bảng), mỗi nhóm rải ngẫu nhiên 1 người/bảng.
- **Mỗi ngày**: hạn nộp = lúc chạy `close` (snapshot bài) – nộp sau đó tính cho ngày kế tiếp; chấm bằng `grade`.
  Điểm reset về 0, thứ hạng ban đầu = trung bình thứ hạng các ngày trước (ngày 1: theo seed).
- **Trận BO2**: mỗi bên đi trước 1 ván; tổng 2 ván >0 thắng (+1), <0 thua (−1), =0 hòa (0). Không nộp bài → thua mọi trận (−1).
  Hạng cùng điểm xét: tổng điểm ván (`gs`), rồi thứ hạng ban đầu.
- **7 trận/ngày**: trận 1 nửa trên vs nửa dưới; trận 2–7 ghép người cùng điểm gần nhau nhất, tránh gặp lại. Bảng lẻ → hạng thấp nhất nhận bye (0 điểm).
- **Ngày 7**: chỉ người nộp ≥4/6 ngày đầu được đấu. Top `top` mỗi bảng đi tiếp + `wildcard` vé vớt cho người có thứ hạng (phần trăm) trung bình 6 ngày thường tốt nhất.
- Chỉnh số bảng / số người đi tiếp từng vòng trong `CFG["rounds"]` (`tournament.py`).

## Giả định tôi đã chọn (đề chưa nói rõ – sửa trong `engine.py` nếu khác ý bạn)
1. Xếp quân: mỗi bên 9 quân ở hàng cuối, loại = `x % 3` (3 Búa, 3 Bao, 3 Kéo).
2. Đích: bên đi trước (hàng 1) phải vào **i9**, bên sau phải vào **a1** (đích của đối phương, không phải góc nhà).
3. Đi vào ô quân địch khắc mình = nước không hợp lệ (không tự sát). Hết nước đi = thua. Quá 200 nước = hòa.
4. Đề ghi "1 ngày 7 trận" nhưng chỉ nêu trận 1 và trận 2–6; tôi cho trận 7 ghép theo điểm như trận 2–6.
5. Quy mô vòng 2–5 (số bảng/số người đi tiếp) là giá trị mẫu: 2000 → 440 → 144 → 56 → 20.

## Bảo mật & hiệu năng (đọc trước khi chạy thật)
- Sandbox trong `ProcBot` chỉ dùng rlimit. Vì chạy code lạ của 4000 người, **hãy chạy `grade`/`entry-close` trong container** (docker `--network none --read-only --cap-drop ALL`, user không đặc quyền), hoặc bọc bằng nsjail/bubblewrap.
- Không endpoint nào trả code bài nộp; chỉ `/leaderboard` công khai thứ hạng trong bảng của chính thí sinh.
- Tốc độ: đo thử ~0.15s/ván/lõi (chủ yếu khởi động Python). 2000 người ⇒ ~14.000 ván/ngày ⇒ cần máy ~16–32 lõi để chấm gọn trong khung 1h–5h; thiếu thì giảm `MATCHES` hoặc tăng worker.
- Đã test: luật, bot, entry, 7 ngày vòng 1 với 36 người (có người không nộp), xét lên vòng và chia bảng vòng 2. Chưa test tải 4000 người.

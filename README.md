# OTTv2 – Hệ thống thi đấu code Oẳn Tù Tì

## Cấu trúc
| File | Vai trò |
|---|---|
| `engine.py` | Luật chơi, sandbox chạy bot, 3 bot BTC (`btc0` ngẫu nhiên, `btc1` tham lam, `btc2` chấm điểm 1 nước), trận BO2. Thí sinh test local: `python engine.py test bot.py` |
| `tournament.py` | Đăng ký/nộp bài, thi đầu vào, chia bảng, chấm ngày (7 lượt ghép trận), vé vớt, lên vòng + CLI quản trị |
| `server.py` | API thí sinh và trang quản trị tại `/admin` |
| `sample_bot.py` | Bot mẫu + mô tả giao thức cho thí sinh |

## Quản trị qua website
- Mở `/admin` và đăng nhập bằng mật khẩu chung cấu hình trong biến môi trường `ADMIN_PASSWORD`.
- Đặt `ADMIN_PASSWORD` và `FLASK_SECRET_KEY` trong môi trường của máy chủ hoặc terminal chạy ứng dụng; không ghi các giá trị này vào GitHub.
- Nếu phục vụ website qua HTTPS, đặt `SESSION_COOKIE_SECURE=true`; để chạy local qua HTTP, không đặt biến này.
- Dùng trang quản trị để mở/đóng nhận bài, xem danh sách thí sinh, chấm đầu vào và chia bảng, chốt ngày, chấm ngày. Chấm ngày cuối tự xét lên vòng theo cấu hình hiện có.
- Thao tác chấm chạy nền và hiển thị lỗi/trạng thái trên trang. Dùng một Gunicorn worker (`gunicorn server:app --workers 1 --bind 0.0.0.0:$PORT`) để khóa thao tác quản trị trong bộ nhớ có hiệu lực.
- Nếu triển khai từ GitHub qua một dịch vụ hosting, đẩy thay đổi lên repository và chạy lại quy trình deploy của dịch vụ đó.

## Cách thí sinh tham gia
1. Mở trang chính, đăng ký tên thi đấu (3–20 ký tự, chỉ gồm chữ cái tiếng Anh, chữ số và `_`). Hệ thống cấp token; token là thông tin đăng nhập của thí sinh.
2. Viết bot theo giao thức bên dưới, chọn file `.py` rồi nộp bằng token. Hệ thống giới hạn file 64 KB và kiểm tra cú pháp Python trước khi nhận.
3. Dùng mục trạng thái để xem giai đoạn, vòng, ngày, bảng và điểm; mục bảng xếp hạng hiển thị kết quả bảng của tài khoản đó. Sau khi chấm ngày, mục “Xem lại trận đấu” cho phép phát lại các ván đã ghi hình của bảng; các trận đã chấm trước khi bật tính năng này không có dữ liệu phát lại.
4. Mỗi lần nộp thành công trong một ngày sẽ thay thế bài mới nhất. Khi ban tổ chức chốt ngày, hệ thống chụp bản bài hiện tại để chấm ngày đó; bài nộp sau thời điểm chốt được tính cho ngày kế tiếp.

## Giao thức bot
Bot là file `.py` đọc stdin / ghi stdout. Mỗi lượt nhận 1 dòng JSON
`{"me":0|1,"ply":n,"goal":[x,y],"pieces":[[x,y,chủ,loại],...]}` và in `x y nx ny` (toạ độ 0..8, x=cột a..i, y=hàng 1..9).
Loại: 0=Búa, 1=Bao, 2=Kéo. Giới hạn 1s/nước (3s nước đầu), 512MB RAM, không file/process/mạng.

## Luồng điều hành một giải
Ban tổ chức có thể thao tác trên trang `/admin` hoặc dùng các lệnh CLI trong `tournament.py`:

1. **Trước khi thi**: mở nhận bài, thí sinh đăng ký và nộp bot. Có thể đóng/mở nhận bài từ trang quản trị.
2. **Chốt đầu vào**: bấm “Chấm đầu vào và chia bảng” trên trang quản trị hoặc chạy `python tournament.py entry-close`. Hệ thống chấm bot dự thi với ba bot BTC, áp dụng ngưỡng đầu vào rồi chia người đạt yêu cầu vào các bảng.
3. **Mỗi ngày thi**: khi hết hạn nộp, bấm “Chốt bài ngày thi” hoặc chạy `python tournament.py close`. Hệ thống lưu snapshot bài nộp của ngày và chuyển sang ngày tiếp theo. Sau đó bấm “Chấm ngày / xét lên vòng” hoặc chạy `python tournament.py grade`.
4. **Lặp lại** bước chốt và chấm cho đến ngày cuối vòng. Không thể chốt ngày mới khi vẫn còn ngày trước đang chờ chấm.
5. **Cuối vòng**: khi chấm ngày cuối, hệ thống tự xét người đi tiếp, chia bảng vòng tiếp theo và đặt ngày về 1. Vòng cuối thì giải chuyển sang trạng thái kết thúc.

Không bắt buộc bật trang web để chạy phần chấm; các lệnh CLI có thể dùng độc lập. Nếu dùng lịch tự động, giờ chạy `close` là hạn nộp thực tế; cần đảm bảo `grade` chỉ chạy sau khi `close` hoàn tất.

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

## Cách tính điểm và xếp hạng
### Điểm đầu vào
Mỗi thí sinh có bài được đấu hai ván với từng bot BTC; hai bên đổi lượt đi trước. Với mỗi bot BTC, tính kết quả từ góc nhìn thí sinh: thắng một ván `+1`, hòa `0`, thua `−1`. Cộng hai ván thành `s0`, `s1`, `s2`, mỗi giá trị nằm trong `[-2, 2]`.

**entry = 1 × s0 + 2 × s1 + 3 × s2**

Ví dụ nếu kết quả tổng với ba bot lần lượt là `+2`, `0`, `−1`, thì `entry = 1×2 + 2×0 + 3×(−1) = −1`. Cấu hình giải thường là `entry_cut = 0`: thí sinh có `entry < 0` bị loại; bằng 0 vẫn đạt ngưỡng. Người không có bài để chấm không được vào vòng 1. Chế độ thử `OTT_TEST` và lệnh `demo` thay ngưỡng thành `−99`, nên không dùng ngưỡng đó để kết luận kết quả giải thật.

### Điểm trận trong một ngày
Một **trận** gồm hai ván, mỗi bên được đi trước một ván. Gọi `s` là tổng kết quả của bot A trong hai ván: thắng `+1`, hòa `0`, thua `−1` cho từng ván. Do đó `s` nằm trong `[-2, 2]`. Ví dụ: A thắng ván đầu và thua ván hai thì `s = +1 + (−1) = 0`.

- `s > 0`: A thắng trận; A nhận `pts +1`, B nhận `pts −1`.
- `s < 0`: A thua trận; A nhận `pts −1`, B nhận `pts +1`.
- `s = 0`: trận hòa; mỗi bên nhận `pts 0`.

`s` là **điểm ván của A**, không phải điểm trận. Giá trị `s` cũng được cộng vào `gs` của A; `gs` của B nhận giá trị đối dấu. Ví dụ `s = +2` nghĩa là A thắng cả hai ván, nhưng A chỉ được `+1 điểm trận`; `s = 0` nghĩa là trận hòa kể cả khi mỗi bên thắng một ván.

Nếu chỉ một bên không có bài trong snapshot ngày đó, bên đó thua trận (`pts −1`); nếu cả hai bên đều không có bài, trận được tính hòa. Người được bye không đấu trận và không nhận điểm cho lượt đó.

### Xếp hạng ngày và ghép trận
- Điểm `pts` và `gs` được tính lại từ 0 cho từng ngày.
- Xếp hạng theo `pts` giảm dần; nếu bằng nhau thì `gs` giảm dần; nếu vẫn bằng nhau thì theo thứ tự ban đầu của ngày.
- Ngày đầu thứ tự ban đầu lấy từ seed chia bảng. Ngày sau dùng thứ hạng trung bình của các ngày đã chấm để xếp thứ tự ban đầu.
- Mỗi bảng có 7 lượt ghép trận trong ngày. Lượt đầu ghép nửa trên thứ tự ban đầu với nửa dưới. Các lượt sau ghép theo thứ tự điểm hiện tại, đồng thời ưu tiên đối thủ chưa gặp lại. Nếu bảng lẻ người, hệ thống cho bye một người ở cuối thứ tự; ưu tiên người chưa từng được bye.

### Điều kiện và cách xét vé vớt
Ở ngày cuối (ngày 7 theo cấu hình hiện tại), chỉ thí sinh đã nộp bài ít nhất **4 trong 6 ngày đầu** mới được xếp trận ngày cuối và có thứ hạng ngày cuối. Top `top` người của mỗi bảng đi tiếp trực tiếp. Các suất `wildcard` còn lại được xét chung trong toàn vòng, từ những người đủ điều kiện nhưng chưa nằm trong top:

1. Với từng ngày trong 6 ngày đầu, tính chỉ số thứ hạng chuẩn hóa: **(hạng − 1) / số người được xếp hạng trong bảng ngày đó**.
2. Lấy trung bình 6 chỉ số; giá trị **càng thấp càng tốt**. Hạng nhất có chỉ số 0; cách chuẩn hóa giúp so sánh giữa các bảng có quy mô khác nhau.
3. Chọn số người có chỉ số thấp nhất theo số lượng `wildcard` của vòng.

Ví dụ trong bảng 10 người, hạng 2 tương ứng `(2−1)/10 = 0,1`; hạng 5 tương ứng `(5−1)/10 = 0,4`. Nếu thành tích 6 ngày giống nhau theo từng ví dụ, người hạng 2 có chỉ số tốt hơn và được ưu tiên vé vớt. Người không đủ điều kiện thi ngày cuối không được xét wildcard.

Quy mô hiện được đặt trong `CFG["rounds"]` của `tournament.py`:

| Vòng | Số bảng | Top mỗi bảng | Vé vớt toàn vòng | Tổng suất đi tiếp theo cấu hình |
|---|---:|---:|---:|---:|
| 1 | 40 | 10 | 40 | 440 |
| 2 | 16 | 8 | 16 | 144 |
| 3 | 8 | 6 | 8 | 56 |
| 4 | 4 | 4 | 4 | 20 |
| 5 | 1 | 1 | 0 | 1 |

Đây là cấu hình mẫu; số người thực tế đi tiếp có thể thấp hơn nếu không đủ thí sinh đủ điều kiện.

## Chạy thử demo
Trên Windows, `demo.bat` chạy `python -u tournament.py demo 40` để tạo giải mẫu rút gọn; có thể mất vài phút. Lệnh demo tạo/cập nhật dữ liệu trong `ott.db`, thư mục `bots` và `snaps`, vì vậy hãy chạy trên bản sao thư mục dự án hoặc sao lưu dữ liệu giải trước, không chạy đè dữ liệu giải thật. Khi demo xong, dùng `start_server.bat` để mở giao diện web và đăng nhập `/admin` để xem trạng thái/kết quả. Demo tạo tài khoản giả; nó không tự mở trình duyệt hoặc tạo sẵn token đăng nhập cho các tài khoản mẫu.

Các lệnh CLI hữu ích:
```bash
python tournament.py status        # xem giai đoạn, vòng, ngày, ngày chờ chấm
python tournament.py board         # in các bảng kết quả đã chấm
python engine.py test sample_bot.py # thử bot mẫu với ba bot BTC
```

## Giả định tôi đã chọn (đề chưa nói rõ – sửa trong `engine.py` nếu khác ý bạn)
1. Xếp quân: mỗi bên 9 quân ở hàng cuối, loại = `x % 3` (3 Búa, 3 Bao, 3 Kéo).
2. Đích: bên đi trước (hàng 1) phải vào **i9**, bên sau phải vào **a1** (đích của đối phương, không phải góc nhà).
3. Đi vào ô quân địch khắc mình = nước không hợp lệ (không tự sát). Hết nước đi = thua. Quá 200 nước = hòa.
4. Đề ghi "1 ngày 7 trận" nhưng chỉ nêu trận 1 và trận 2–6; tôi cho trận 7 ghép theo điểm như trận 2–6.
5. Quy mô các vòng (số bảng/số người đi tiếp) là giá trị mẫu: 2000 → 440 → 144 → 56 → 20 → 1.

## Bảo mật & hiệu năng (đọc trước khi chạy thật)
- Sandbox trong `ProcBot` chỉ dùng rlimit. Vì chạy code lạ của 4000 người, **hãy chạy `grade`/`entry-close` trong container** (docker `--network none --read-only --cap-drop ALL`, user không đặc quyền), hoặc bọc bằng nsjail/bubblewrap.
- Không endpoint nào trả code bài nộp; chỉ `/leaderboard` công khai thứ hạng trong bảng của chính thí sinh.
- Tốc độ: đo thử ~0.15s/ván/lõi (chủ yếu khởi động Python). 2000 người ⇒ ~14.000 ván/ngày ⇒ cần máy ~16–32 lõi để chấm gọn trong khung 1h–5h; thiếu thì giảm `MATCHES` hoặc tăng worker.
- Đã test: luật, bot, entry, 7 ngày vòng 1 với 36 người (có người không nộp), xét lên vòng và chia bảng vòng 2. Chưa test tải 4000 người.

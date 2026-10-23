# OTTv2 — giải đấu bot Oẳn Tù Tì

## Kiến trúc vận hành

- `frontend/`: ứng dụng Vite/React, đăng nhập và giao diện thí sinh/admin.
- `admin_cli_service/`: CLI tin cậy để tạo/import tài khoản admin bằng service-role key; không chạy như web API.
- `servers/scoring/`: module nhận bài, điều phối giải online, gọi Judge0, tải replay lên Supabase Storage.
- Supabase Postgres là nguồn dữ liệu chuẩn cho tài khoản, bài nộp, lịch đấu, điểm, ghép cặp và xét vòng. SQLite không thuộc luồng vận hành mới.
- `tournament.py status` chỉ đọc trạng thái Supabase. Các thao tác vận hành giải dùng `/admin` và scoring module.
- Mã/DB SQLite cũ được lưu tại `backup/legacy_sqlite/`; không chạy các lệnh cũ trong lúc giải mới hoạt động.

## Luật đã triển khai

- Tối đa 4.000 thí sinh; vòng đầu vào dùng ba bot chuẩn, trọng số `1,2,3`, ngưỡng `-2`, tối đa 20 lượt và giữ điểm tốt nhất.
- Người đạt ngưỡng được chia theo dải điểm vào 40 bảng.
- Mỗi vòng online kéo dài 7 ngày. Mỗi ngày có 7 lượt BO2; ngày 1 ghép nửa trên với nửa dưới, lượt 2–7 ghép theo điểm hiện tại và tránh đối thủ đã gặp.
- Mỗi lượt: thắng `+1`, thua `-1`, hòa `0`; vắng bài lúc chốt ngày `-1`; bye `0`.
- Ngày 7 yêu cầu đã nộp ít nhất 4/6 ngày đầu. Top và vé vớt: V1 `10+40`, V2 `8+16`, V3 `6+8`, V4 `4+4`.
- Bảng tạm và tiến độ đầy đủ chỉ dành cho admin. Thí sinh thấy đối thủ của mình; BXH công khai sau thời điểm công bố ngày hôm sau.
- Web giải chính kết thúc sau Vòng 4. Danh sách top/vé vớt Vòng 4 được xuất CSV rồi import vào ứng dụng chung kết offline; không có Vòng 5 trong cấu hình Supabase của giải online.
- Mỗi vòng online có preset luật bàn cờ riêng, BTC chọn trước khi vòng bắt đầu: Vòng 1 cơ bản; các preset kế tiếp lần lượt thêm tường, vùng bảo vệ, cổng dịch chuyển và ô đổi quân.

Chi tiết quy tắc và ngoại lệ: [docs/TOURNAMENT_OPERATIONS.md](docs/TOURNAMENT_OPERATIONS.md).

## Giao diện vòng chung kết độc lập

Giao diện quản lý và xem trực tiếp vòng chung kết dùng React/TypeScript, được Flask phục vụ từ `frontend/dist`. Chạy các lệnh sau trong PowerShell từ thư mục gốc dự án. Dùng `npm.cmd` để tránh lỗi Execution Policy chặn script `npm.ps1`:

```powershell
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
python -m finals.run_server
```

Mở `http://localhost:9000/` trên máy chủ hoặc `http://<LAN-IP>:9000/` từ các máy trong mạng thi. Chung kết là ứng dụng độc lập: roster, tài khoản cục bộ, trận đấu và kết quả lưu trong SQLite; xử lý trận dùng game engine/bot trên máy chủ. Chung kết không gọi Supabase, Internet, Judge0 hay scoring module.

## Triển khai schema Supabase

Chạy toàn bộ migration trong `data/supabase/migrations` theo thứ tự số, kết thúc bằng `0018_round_game_rules.sql`. Migration `0017` bỏ cấu hình vòng 5 khỏi giải online và mở RPC quản trị để xuất danh sách đủ điều kiện chung kết sau khi Vòng 4 hoàn tất. Migration `0018` lưu bộ luật theo vòng và mở lựa chọn preset trong admin. Hướng dẫn biến môi trường: [data/SUPABASE_SETUP.md](data/SUPABASE_SETUP.md).

### Chuẩn bị chung kết offline

1. Sau khi Vòng 4 hoàn tất, trên web giải chính dùng **Xuất CSV thí sinh chung kết**. Đây là bước cần Supabase; file roster không chứa mật khẩu.
2. Chuyển file roster tới máy chủ chung kết bằng phương thức an toàn. Trước khi chạy, đặt `FINALS_ADMIN_SECRET` trên host và chỉ cấp secret cho BTC; chạy `python -m finals.run_server`, đăng nhập tab BTC, chọn CSV và nhập danh sách. Không cần cấu hình Supabase trên máy chung kết.
3. Tải xuống `finalist-offline-credentials.csv` ngay sau khi import. Hệ thống cấp mật khẩu tạm riêng, ngẫu nhiên, chỉ lưu hash trong SQLite; phân phối từng mật khẩu cho đúng thí sinh qua kênh riêng và bảo vệ/xóa bản CSV mật khẩu sau khi phân phối.
4. Cho thí sinh truy cập `http://<LAN-IP>:9000/` trong mạng LAN và đăng nhập bằng username cùng mật khẩu tạm. Mở cổng 9000 chỉ trong LAN/firewall của điểm thi.
5. Trước ngày thi, dừng dịch vụ rồi sao lưu `finals/finals.db` và `snaps/finals/`; kiểm thử đăng nhập, tạo/chạy trận, feed trực tiếp và bảng xếp hạng khi đã ngắt WAN. Chỉ vòng online 1–4 và xuất CSV cần kết nối Supabase/Internet.

Import lại cùng roster sẽ cấp mật khẩu mới cho các tài khoản có trong file, vô hiệu hóa mật khẩu cũ. Chỉ thực hiện khi cần và phân phối lại credential CSV.

## Chạy dịch vụ local

1. Cấu hình Supabase/Judge0 trong `servers/scoring/config.local.env` (không commit secrets).
2. Khởi động Judge0 tại port `2358`.
3. Chạy scoring module tại port `8110`, rồi cấu hình public HTTPS Tunnel tới module.
4. Khởi động frontend và scoring module theo hướng dẫn local trong `servers/scoring/LOCAL_TEST.md`.
5. Đăng nhập `/admin`, kiểm tra URL máy chấm, đóng vòng đầu vào, mở/chốt từng ngày và dùng Resume nếu worker bị gián đoạn.

Module dùng song song tối đa `OTT_TOURNAMENT_MATCH_WORKERS` trận (mặc định 4), xử lý nền và phục hồi ngày đang mở/chấm khi khởi động lại. Bot và replay gốc vẫn được lưu trong Supabase/local scoring storage theo cấu hình.

## Tài liệu khôi phục

Snapshot các file SQLite cũ và lệnh khôi phục ở [backup/legacy_sqlite/README.md](backup/legacy_sqlite/README.md). Snapshot không chứa `ott.db`, dữ liệu thí sinh, source bot hay secrets; sao lưu các dữ liệu đó riêng trước khi dọn máy cũ.

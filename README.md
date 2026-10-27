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
- Vòng 5 offline không được triển khai; hệ thống vận hành V1–V4 online.

Chi tiết quy tắc và ngoại lệ: [docs/TOURNAMENT_OPERATIONS.md](docs/TOURNAMENT_OPERATIONS.md).

## Triển khai schema Supabase

Chạy SQL Editor theo thứ tự `0001` → `0002` → `0003` → `0004` → `0005` → `0006` → `0007`. Migration `0004` đã được áp dụng trước; `0005`–`0007` cần chạy để dùng giao diện admin, điều hành giải và lịch sử/replay mới. Hướng dẫn biến môi trường: [data/SUPABASE_SETUP.md](data/SUPABASE_SETUP.md).

## Chạy dịch vụ local

1. Cấu hình Supabase/Judge0 trong `servers/scoring/config.local.env` (không commit secrets).
2. Khởi động Judge0 tại port `2358`.
3. Chạy scoring module tại port `8110`, rồi cấu hình public HTTPS Tunnel tới module.
4. Khởi động frontend và scoring module theo hướng dẫn local trong `servers/scoring/LOCAL_TEST.md`.
5. Đăng nhập `/admin`, kiểm tra URL máy chấm, đóng vòng đầu vào, mở/chốt từng ngày và dùng Resume nếu worker bị gián đoạn.

Module dùng song song tối đa `OTT_TOURNAMENT_MATCH_WORKERS` trận (mặc định 4), xử lý nền và phục hồi ngày đang mở/chấm khi khởi động lại. Bot và replay gốc vẫn được lưu trong Supabase/local scoring storage theo cấu hình.

## Tài liệu khôi phục

Snapshot các file SQLite cũ và lệnh khôi phục ở [backup/legacy_sqlite/README.md](backup/legacy_sqlite/README.md). Snapshot không chứa `ott.db`, dữ liệu thí sinh, source bot hay secrets; sao lưu các dữ liệu đó riêng trước khi dọn máy cũ.

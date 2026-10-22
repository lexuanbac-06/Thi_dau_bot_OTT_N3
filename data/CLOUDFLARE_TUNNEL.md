# Máy local làm server file qua Cloudflare Tunnel

Máy local giữ replay trong `data/storage/` và chạy `data/storage_server.py`. Cloudflare Tunnel đưa nó ra
Internet qua HTTPS mà **không mở cổng, không cần IP tĩnh**.

```
Trình duyệt ──HTTPS──► files.<domain> (Cloudflare) ──tunnel──► cloudflared ──► 127.0.0.1:8100 (storage_server)
```

## Yêu cầu
- Tài khoản Cloudflare (miễn phí) có 1 domain đã trỏ nameserver về Cloudflare.
- Máy local bật liên tục trong thời gian thi (tắt sleep). Nên dùng UPS/mạng ổn định.

## 1. Chạy storage server
```bash
pip install flask waitress
# từ thư mục gốc dự án, đã có data/.env
.venv/bin/python -m waitress --listen=127.0.0.1:8100 data.storage_server:app
# kiểm tra
curl http://127.0.0.1:8100/healthz        # {"ok":true}
```
Chỉ bind `127.0.0.1` – chỉ cloudflared mới vào được.

## 2. Cài cloudflared
- macOS: `brew install cloudflared`
- Windows: `winget install --id Cloudflare.cloudflared`
- Linux: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/

## 3. Tạo tunnel
```bash
cloudflared tunnel login                                  # mở trình duyệt, chọn domain
cloudflared tunnel create ott-storage                     # in ra <TUNNEL_UUID>, tạo file credentials .json
cloudflared tunnel route dns ott-storage files.example.com
```
Tạo `~/.cloudflared/config.yml` từ mẫu [`cloudflared.config.example.yml`](cloudflared.config.example.yml)
(thay `<TUNNEL_UUID>`, hostname). Chạy thử:
```bash
cloudflared tunnel run ott-storage
curl https://files.example.com/healthz
```

### Thử nhanh không cần domain
```bash
cloudflared tunnel --url http://127.0.0.1:8100            # cấp URL https://xxxx.trycloudflare.com tạm thời
```
Chỉ để test, URL đổi mỗi lần chạy.

## 4. Chạy như dịch vụ (tự khởi động lại)
- macOS/Linux: `sudo cloudflared servicurl https://abc-xyz.trycloudflare.com/healthzce install` (dùng `~/.cloudflared/config.yml` hoặc `/etc/cloudflared/config.yml`).
- Windows (PowerShell admin): `cloudflared service install` rồi `sc start cloudflared`.
- Storage server tự khởi động: Windows dùng Task Scheduler (`At startup`) chạy
  `python -m waitress --listen=127.0.0.1:8100 data.storage_server:app` trong thư mục dự án;
  macOS dùng `launchd`; Linux dùng `systemd`.

## 5. Cấu hình CORS và frontend
Trong `data/.env`: `OTT_CORS_ORIGINS=https://ott.example.com` (domain web của thí sinh). Frontend lấy replay:
```js
const r = await fetch(`https://files.example.com/replays/${matchId}`,
                      { headers: { Authorization: `Bearer ${accessToken}` } });
const games = await r.json();     // trình duyệt tự giải nén gzip
```
`matchId` lấy từ RPC `get_group_matches` (cột `match_id`, `has_replay`).

## 6. Bảo mật & hiệu năng
- **Quyền truy cập**: do Supabase quyết định (RLS). Không đăng nhập / khác bảng / ngày chưa chấm → 401/404.
- Code bot (`bots/`, `snaps/`) **không** nằm trong `data/storage/` và storage server không có route trả code.
- Cloudflare dashboard → **Security → WAF → Rate limiting**: giới hạn ~60 request/phút/IP cho `files.<domain>/replays/*`.
- Replay đã nén gzip (~vài chục KB/trận). Bật cache Cloudflare **không** áp dụng được vì response là `private`; tải lớn
  thì giảm bằng cache phía trình duyệt (đã đặt `max-age=3600`).
- Không tunnel cổng SSH/DB; chỉ ingress tới 8100 (và 8000 nếu cần).
- Sao lưu `servers/scoring` source storage riêng nếu cần giữ các bot đã nộp trên máy module. SQLite không thuộc quy trình hiện tại.

## 7. Xử lý sự cố
| Triệu chứng | Cách xử lý |
|---|---|
| `502 Bad Gateway` ở Cloudflare | storage server chưa chạy / sai cổng trong `config.yml` |
| `401` dù đã đăng nhập | access token hết hạn → gọi `/auth/refresh` |
| `404 Replay chưa có trên máy chủ` | kiểm tra job/match có metadata `replay_objects` và object tương ứng trong private Supabase Storage |
| Lỗi CORS | thêm origin vào `OTT_CORS_ORIGINS`, khởi động lại storage server |

## 8. Scoring module và Judge0

Judge0 tiếp tục bind riêng trên `127.0.0.1:2358`; không expose port này qua Cloudflare. API điều phối chấm chạy ở
`127.0.0.1:8110`, dùng hostname `score.<domain>` trong `data/cloudflared.config.example.yml`.

1. Apply các migration theo thứ tự, gồm `0002_scoring_jobs.sql` và `0003_immediate_scoring_and_admin_phases.sql`, trong Supabase SQL Editor.
2. Khởi động Judge0 bằng Compose trong `servers/scoring/judge0-v1.13.0/`; copy các biến phù hợp từ
   `servers/scoring/.env.example` vào root `.env` hoặc `data/.env` (đây là các file được loader đọc). Module dùng Supabase service role, chỉ giữ key ở máy chấm. Trong file
   `judge0.conf` local (đang ignore vì có secrets), đặt `MAX_CPU_TIME_LIMIT=60`,
   `MAX_WALL_TIME_LIMIT=200`, `MAX_MEMORY_LIMIT=512000`; submission runner mặc định dùng 30s CPU,
   140s wall time và 262144 KB RAM. Sau khi đổi file, recreate cả `server` và `workers`, rồi xác nhận
   `GET http://127.0.0.1:2358/config_info` trả về các max trên. Runner kiểm tra `config_info` trước mỗi job
   và dừng với lỗi cấu hình dễ hiểu nếu Judge0 vẫn báo max 15/20. Giữ `judge0.conf` khỏi Git.
3. Chạy `servers/scoring/start_module.sh`; kiểm tra `http://127.0.0.1:8110/v1/health`.
4. Thêm `score.<domain> -> http://127.0.0.1:8110` vào tunnel config, rồi kiểm tra
   `https://score.<domain>/v1/health`.
5. Đặt `VITE_SCORING_MODULE_URL=https://score.<domain>` trong môi trường build Vercel và
   `OTT_SCORING_CORS_ORIGINS=https://<domain-web>` trên máy chấm.
6. Bật [Supabase Cron](https://supabase.com/docs/guides/cron) rồi schedule mỗi phút SQL
   `select public.timeout_scoring_jobs(now() - interval '3 minutes')`; kiểm tra job runs trên Dashboard.

Bot mới cần định nghĩa `choose_move(state)` theo [`../servers/scoring/BOT_PROTOCOL.md`](../servers/scoring/BOT_PROTOCOL.md).
Module cũng điều phối ghép/chấm các vòng online và thao tác admin qua Supabase RPC. Vòng offline không được triển khai. Các tệp SQLite cũ chỉ để trong backup, không khởi chạy song song với flow mới.
# Cập nhật replay (2026-10-21)

Replay mới được scoring module nén rồi upload trực tiếp lên private Supabase Storage; frontend tải qua signed URL ngắn hạn. Tunnel chỉ dùng để trình duyệt gọi scoring module. Replay cũ trong local storage chưa được tự động import.


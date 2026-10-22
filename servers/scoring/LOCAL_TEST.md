# Chạy thử scoring module trên máy local

Có thể quan sát luồng local mà chưa deploy và chưa cần Cloudflare Tunnel. Mở frontend bằng Vite trên `localhost`; trình duyệt gọi scoring module tại `http://127.0.0.1:8110`. Module gọi Judge0 tại `http://127.0.0.1:2358` và Supabase qua HTTPS.

## Trước khi chạy

1. Đảm bảo root `.env` hoặc `data/.env` có `SUPABASE_URL`, `SUPABASE_ANON_KEY` và `SUPABASE_SERVICE_ROLE_KEY`. Không đưa service role key vào frontend hay `config.local.env`.
2. Apply các migration theo thứ tự, gồm `0002_scoring_jobs.sql` rồi `0003_immediate_scoring_and_admin_phases.sql`, vào Supabase project. Migration không tự động được apply.
3. Khởi động Judge0 bằng Docker Compose trong `servers/scoring/judge0-v1.13.0`. `judge0.conf` cần có `MAX_CPU_TIME_LIMIT=60`, `MAX_WALL_TIME_LIMIT=200`, `MAX_MEMORY_LIMIT=512000`; giá trị CPU/wall này đã có trong file local hiện tại. Sau khi sửa config, recreate server và worker để chúng nạp config mới:

   ```sh
   cd servers/scoring/judge0-v1.13.0
   docker compose up -d --force-recreate server workers
   curl http://127.0.0.1:2358/config_info
   ```
   Kiểm tra response `config_info` có `max_cpu_time_limit >= 30`, `max_wall_time_limit >= 140`, `max_memory_limit >= 262144`.
   `OTT_JUDGE0_URL` phải là URL đầy đủ như `http://127.0.0.1:2358`; sau mọi thay đổi
   trong `config.local.env`, phải restart scoring module vì cấu hình được nạp lúc process khởi động.
   Để dùng durable queue, cần áp dụng thêm migration `0015_durable_scoring_queue.sql` và
   `0016_queue_claim_only_ready_jobs.sql`.
4. Cài dependencies scoring/frontend theo cấu hình hiện có của repo.

## Chạy

Terminal 1, từ thư mục repo:

```sh
sh servers/scoring/start_module.sh
```

Module bind loopback ở port `8110`. Có thể kiểm tra health tại `http://127.0.0.1:8110/health`.

Terminal 2, từ thư mục `frontend`:

```sh
VITE_SCORING_MODULE_URL=http://127.0.0.1:8110 npm run dev
```

Mở URL Vite được in ra terminal, đăng nhập bằng tài khoản Supabase, rồi submit bot. Dùng bot theo protocol `choose_move(state)` trong [BOT_PROTOCOL.md](BOT_PROTOCOL.md).

## Quan sát request và kết quả

- Terminal module: nhận job, cập nhật trạng thái Supabase, gọi Judge0 và ghi lỗi nếu có.
- Judge0: xem container/logs từ Docker Compose; module gửi một submission cho mỗi trận BO2.
- Frontend hiển thị runtime Python mặc định của Judge0 ở chế độ chỉ đọc; thí sinh không thể đổi. C++/Java chưa hỗ trợ vì bot protocol cần adapter `choose_move(state)` chạy trong tiến trình Python.
- Supabase Dashboard → Table Editor → `scoring_jobs`: theo dõi `dispatching` → `accepted` → `running` → trạng thái hoàn tất, cùng `result` hoặc mã lỗi.
- Browser DevTools → Network: thấy RPC tạo job và request multipart tới module chạy song song.
- Replay JSON vẫn nằm trên máy module; metadata/trạng thái job được lưu trên Supabase.

Nếu module chưa nhận job trong 10 giây, frontend đánh dấu dispatch thất bại. Chấm đang chạy mà không callback được Supabase có thể bị timeout theo migration. Offline không có hàng đợi chờ máy online.

## Giới hạn hiện tại

Đây là đường chạy local cho luồng Supabase và các vòng online. Trước khi thử điều hành, cần áp dụng migration `0005` và `0006`. Module scoring dùng Supabase làm nguồn dữ liệu, điều phối các lượt ghép và Judge0; vòng offline chưa được cài. Không mở port `8110` trực tiếp ra Internet. Trình duyệt Vercel cần HTTPS Tunnel tới module; Vite local có thể gọi địa chỉ local được CORS cho phép. Không còn FastAPI port `8000`; các thao tác admin account chạy bằng `admin_cli_service`.

# OTTv2 — nền tảng thi đấu bot Oẳn Tù Tì

OTTv2 là ứng dụng tổ chức giải bot chơi Oẳn Tù Tì trên bàn cờ 9×9. Thí sinh đăng nhập, viết bot Python, nộp để đấu với bot chuẩn hoặc đối thủ được ghép trong giải, rồi theo dõi điểm số và xem lại ván đấu. Ban tổ chức quản lý tài khoản, lịch thi, bảng đấu, kết quả và trạng thái hệ thống.

Các vòng 1–4 được tổ chức online trên hệ thống chính. Chung kết offline là ứng dụng riêng chạy tại điểm thi trên LAN, dùng SQLite cục bộ và bộ luật Vòng 5. Supabase là nguồn dữ liệu chuẩn cho giải online; SQLite của ứng dụng chung kết là ngoại lệ có chủ đích.

## Kiến trúc và luồng dữ liệu

```text
Trình duyệt (React)
  ├── Supabase Auth / Postgres RPC / Storage
  └── Cloudflare Worker + Durable Object
        ├── xác thực JWT Supabase
        ├── xếp hàng và giới hạn tốc độ
        ├── gọi OnlineCompiler để chạy Python
        └── ghi kết quả, replay và trạng thái vào Supabase
```

- **Frontend** gọi Supabase bằng public/anon key và JWT của người dùng. Các thao tác cần tính nguyên tử, như chốt ngày hoặc tạo cặp đấu, chạy qua Postgres RPC.
- **Cloudflare Worker** nhận bài chấm trực tiếp từ trình duyệt. Worker kiểm tra JWT với Supabase, sau đó Durable Object quản lý hàng đợi và gọi OnlineCompiler. Khóa OnlineCompiler và Supabase `service_role` chỉ nằm trong secrets của Worker.
- **Supabase Postgres** lưu hồ sơ, bài nộp, lịch đấu, kết quả, thứ hạng và trạng thái giải. RLS và RPC giới hạn dữ liệu mỗi thí sinh được đọc.
- **Supabase Storage** giữ replay đã nén trong bucket riêng `replays`; metadata và quyền đọc replay được quản lý qua `replay_objects`, policy và RPC.
- **Scoring module Python/Judge0** vẫn có trong repo để chạy local và phục vụ một số quy trình vận hành. Frontend hiện dùng Worker; không cần mở scoring module ra Internet để chấm bài từ trình duyệt.

## Cách tổ chức repo

| Thư mục / tệp | Vai trò |
|---|---|
| `frontend/` | Ứng dụng React/TypeScript: đăng nhập, Code Arena, lịch sử, bảng xếp hạng, replay và trang admin. |
| `servers/scoring/cloudflare_proxy/` | Worker, Durable Object queue, cấu hình Wrangler, kịch bản tải thử và báo cáo đo tải. |
| `servers/scoring/` | Scoring module Python, tích hợp Judge0, bot protocol và hướng dẫn chạy local. |
| `data/supabase/migrations/` | Schema, RLS, RPC và các thay đổi giải đấu/replay/proxy theo thứ tự migration. |
| `data/` | Supabase client, cấu hình, quản lý dữ liệu và tài liệu triển khai. |
| `admin_cli_service/` | Lệnh tin cậy để tạo/nhập tài khoản admin; cần service-role key ở máy quản trị. |
| `sample_bots/` | Bot mẫu và ba bot dùng để chấm vòng loại. |
| `docs/TOURNAMENT_OPERATIONS.md` | Thể thức và quy trình vận hành chi tiết. |
| `diagnostics/` | Kết quả kiểm tra/triển khai đã ghi nhận; gồm cả vấn đề do tiến trình local cũ. |
| `backup/` | Mã SQLite/backend cũ để tham khảo hoặc khôi phục; không thuộc luồng vận hành mới. |

## Cách chơi

### Viết và nộp bot

Thí sinh viết chương trình Python theo giao thức ở [`servers/scoring/BOT_PROTOCOL.md`](servers/scoring/BOT_PROTOCOL.md), rồi nộp file `.py` hoặc code trong Code Arena. Frontend kiểm tra định dạng và giới hạn kích thước 64 KiB. Bot nhận trạng thái bàn cờ và phải trả nước đi theo giao thức; nước đi sai hoặc chương trình lỗi được tính theo quy tắc chấm của engine.

Thí sinh có thể chọn bot mẫu để luyện tập. Lượt luyện tập được lưu vào lịch sử của chủ tài khoản, nhưng không ảnh hưởng bảng đấu chính thức.

### Vòng loại

Bot dự thi gặp ba bot chuẩn (`entry_bot0.py`–`entry_bot2.py`). Mỗi cặp bot chơi hai ván đổi bên đi trước; điểm từng cặp nằm trong khoảng `-2..+2`. Điểm vòng loại là:

```text
điểm = 1 × điểm(bot 0) + 2 × điểm(bot 1) + 3 × điểm(bot 2)
```

Ngưỡng đạt là `-2`. Mỗi thí sinh có tối đa 20 lượt và hệ thống dùng điểm cao nhất để xét đạt. Thí sinh vượt ngưỡng được xếp vào các bảng theo điểm đầu vào.

### Các vòng đấu online

- Hệ thống hiện triển khai vòng 1–4 online; mỗi vòng có 7 ngày, trong đó ngày thứ 7 là ngày quyết định.
- Mỗi cặp thi đấu theo BO2: mỗi bên nộp bot cho lượt của mình, mỗi lượt gồm hai ván đổi bên đi trước. Kết quả match gộp tối đa bốn ván từ hai lượt nộp.
- Thắng trận được `+1` điểm bảng, thua `-1`, hòa `0`. Người không nộp bot hợp lệ khi ngày được chốt nhận `-1`; bye nhận `0`.
- Ngày đầu ghép nửa trên với nửa dưới theo thứ tự seed. Các ngày tiếp theo ghép người cùng điểm, ưu tiên đối thủ chưa gặp.
- Muốn thi ngày thứ 7, thí sinh cần nộp hợp lệ ít nhất 4 trong 6 ngày thường.
- Cấu hình đi tiếp hiện tại: V1 `10 người/bảng + 40 vé vớt`; V2 `8 + 16`; V3 `6 + 8`; V4 `4 + 4`.
- Trong ngày, thí sinh thấy trận và đối thủ của mình. Bảng tạm dành cho admin; kết quả chính thức/replay được công bố theo `publish_after`.

Chi tiết luật, cách chốt ngày, bye và xét vé vớt xem [`docs/TOURNAMENT_OPERATIONS.md`](docs/TOURNAMENT_OPERATIONS.md).

### Chung kết offline

Chung kết là ứng dụng Flask độc lập trong `finals/`, không phải Vòng 5 được tạo trên web giải chính. Sau khi Vòng 4 kết thúc, BTC xuất roster finalist trên web chính, chuyển CSV sang máy chủ chung kết và import trước ngày thi. Ứng dụng tạo tài khoản cục bộ cùng mật khẩu tạm ngẫu nhiên; mật khẩu được trả về dưới dạng CSV riêng khi import. Import lại roster sẽ cấp mật khẩu mới cho các tài khoản trong roster, vì vậy hãy lưu và phân phối file thông tin đăng nhập an toàn.

Tại điểm thi, máy chủ chạy engine chung kết và SQLite cục bộ; thí sinh truy cập ứng dụng qua mạng LAN để đăng nhập, nộp bot và theo dõi trận đấu, replay cùng bảng xếp hạng. BTC quản lý tài khoản, chốt bot dự thi và điều phối các trận. Chung kết dùng bộ luật Vòng 5 (có ô đổi loại quân), không phụ thuộc Internet, Supabase, Judge0 hay scoring module. Chỉ việc xuất roster từ giải chính cần kết nối Supabase.

Để chạy máy chủ chung kết từ thư mục gốc repo:

```sh
python -m pip install -r requirements.txt
```

Sao chép `finals/.env.example` thành `finals/.env`, đặt `FINALS_ADMIN_SECRET` thành giá trị bí mật riêng, rồi khởi động:

```sh
python -m finals.run_server
```

Máy chủ mặc định lắng nghe cổng `9000`; thí sinh mở `http://<IP-máy-chủ-trong-LAN>:9000/finals`. Cấu hình cổng và đường dẫn SQLite có thể đặt lần lượt bằng `FINALS_PORT` và `FINALS_DB_PATH`. Không đưa máy chủ chung kết ra Internet. Trước ngày thi, hãy import roster, phân phối thông tin đăng nhập qua kênh an toàn, sao lưu SQLite và bot snapshots, rồi kiểm thử toàn bộ luồng khi đã ngắt WAN. Xem thêm [quy trình vận hành giải](docs/TOURNAMENT_OPERATIONS.md).

## Chấm bài và hàng đợi proxy

1. Frontend tạo scoring job trong Supabase cho lượt vòng loại/luyện tập; với trận chính thức, frontend gửi `match_id` để Worker chuẩn bị lượt nộp.
2. Trình duyệt gửi source và JWT tới `POST /v1/score`. Worker xác thực JWT với Supabase rồi đưa job vào Durable Object queue. API trả `202` cùng `job_id`; giao diện hỏi trạng thái qua `GET /v1/score/{job_id}`.
3. Durable Object chạy tối đa hai yêu cầu OnlineCompiler đồng thời và bắt đầu tối đa hai lượt mỗi 4,2 giây. Cấu hình này nhắm giữ tốc độ dưới giới hạn 30 lượt/phút của gói upstream được dùng khi đặt cấu hình.
4. Worker kiểm tra kết quả, cập nhật lượt chính thức qua RPC hoặc trả kết quả để frontend ghi scoring job. Replay được nén gzip, tải lên bucket riêng và đăng ký trong `replay_objects`.
5. Khi cả hai bên hoàn tất hoặc cửa sổ nộp 90 giây hết hạn, RPC chốt match. Khi hoàn tất vòng, Worker có thể lên lịch tạo vòng tiếp theo sau cooldown.

Hàng đợi có sức chứa tối đa 200 job; upstream request timeout là 120 giây. Các giá trị này là giới hạn cấu hình trong `worker.js`, không phải cam kết thời gian hoàn tất cho mỗi job. Lỗi upstream có retry giới hạn; job không hoàn tất sẽ được báo trạng thái lỗi/timeout.

## Tech stack

| Lớp | Công nghệ |
|---|---|
| Web client | React 19, TypeScript 5.9, Vite 7, Monaco Editor, Supabase JS v2 |
| Database / Auth / Storage | Supabase Postgres, Auth, PostgREST RPC, RLS, private Storage |
| Scoring ingress / queue | Cloudflare Workers, Durable Objects, Wrangler |
| Python execution hiện tại | OnlineCompiler API (`python-3.14`) từ Worker |
| Scoring local/dev | Python scoring module, Judge0 self-hosted, FastAPI/Uvicorn dependencies trong `requirements.txt` |
| Bot engine / dữ liệu cũ | Python; SQLite chỉ còn trong backup/legacy và không phải nguồn dữ liệu giải hiện hành |

## Hiệu năng đã đo

Repo có kết quả từ `queue_load_test.py` chạy qua proxy queue. Đây là các lần đo trên deployment/điều kiện tại thời điểm chạy, với bot mẫu; kết quả có thể thay đổi theo vùng mạng, tình trạng Worker và giới hạn của OnlineCompiler.

| Kịch bản | Thành công | Submit p95 | Chờ queue p95 | Hoàn tất p95 | Thông lượng hoàn tất |
|---|---:|---:|---:|---:|---:|
| 4 job, burst | 4/4, 0 lỗi/timeout | 279 ms | 4,12 s | 5,22 s | 0,583 job/s |
| 5 job, burst | 5/5, 0 lỗi/timeout | 259 ms | 7,92 s | 8,85 s | 0,444 job/s |
| 50 job, burst | 50/50, 0 lỗi/timeout | 789 ms | 96,08 s | 97,02 s | 0,485 job/s |
| 50 job, giãn cách 0,5 s | 50/50, 0 lỗi/timeout | 379 ms | 75,66 s | 76,64 s | 0,470 job/s |

`Submit` là thời gian nhận phản hồi tạo job; `queue wait` tính đến lúc job bắt đầu; `completion` tính từ khi gửi đến khi job báo hoàn tất. Vì vậy submit nhanh không có nghĩa job hoàn thành nhanh khi queue đông. Các số trên được chép từ [`queue-results-4.json`](servers/scoring/cloudflare_proxy/queue-results-4.json), [`queue-results-5.json`](servers/scoring/cloudflare_proxy/queue-results-5.json), [`queue-results-50-burst.json`](servers/scoring/cloudflare_proxy/queue-results-50-burst.json) và [`queue-results-50-staggered.json`](servers/scoring/cloudflare_proxy/queue-results-50-staggered.json). Đây là mẫu nhỏ và không chứng minh khả năng phục vụ 4.000 người nộp đồng thời; cần benchmark theo đúng quota/plan và cấu hình triển khai trước giải.

## Chạy local và triển khai

### Frontend

```sh
cd frontend
npm install
npm run dev
```

Đặt `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` (hoặc publishable key) và `VITE_SCORING_PROXY_URL` trong `frontend/.env`. `npm run build` tạo bản production trong `frontend/dist`.

### Cloudflare Worker

Đọc [`servers/scoring/cloudflare_proxy/README.md`](servers/scoring/cloudflare_proxy/README.md), đặt secrets `ONLINECOMPILER_API_KEY`, `SUPABASE_ANON_KEY` và `SUPABASE_SERVICE_ROLE_KEY`, sau đó chạy `npx wrangler dev` hoặc deploy bằng `npx wrangler deploy`. `SUPABASE_URL` được khai báo trong `wrangler.toml` và phải trỏ cùng project với frontend. Không đưa service-role hoặc OnlineCompiler key vào frontend, git, hay tài liệu công khai.

### Supabase và admin

Tạo project, cấu hình Auth và chạy đầy đủ migrations theo thứ tự trong [`data/SUPABASE_SETUP.md`](data/SUPABASE_SETUP.md). Không chỉ chạy đến `0007`: schema hiện tại bao gồm các migration tới `0031` và hai migration `0018` có tên riêng. Tình trạng SQL trong workspace không xác nhận được migration nào đã apply trên project Supabase thật.

Tạo admin từ máy tin cậy bằng `admin_cli_service`; không bật tự đăng ký công khai nếu đang vận hành giải. Hướng dẫn cấu hình chi tiết: [`data/SUPABASE_SETUP.md`](data/SUPABASE_SETUP.md).

### Scoring module và Judge0 local

Đây là đường chạy phát triển/kiểm tra cũ hơn, không phải proxy mà frontend production hiện gọi:

```sh
cd servers/scoring
./start_server.sh
```

Tham khảo [`servers/scoring/LOCAL_TEST.md`](servers/scoring/LOCAL_TEST.md) và [`servers/scoring/BOT_PROTOCOL.md`](servers/scoring/BOT_PROTOCOL.md) để cấu hình Judge0 và biến môi trường. Không dùng SQLite workflow trong `backup/legacy_sqlite/` để điều hành giải Supabase hiện hành.

## Lưu ý vận hành và bảo mật

- Migrations phải được chạy tuần tự; frontend và Worker cần cùng trỏ đến một Supabase project. Lỗi phiên bản SQL/Worker có thể làm RPC hoặc chấm bài thất bại.
- Bucket replay là private. Replay trận chính thức chỉ đọc được khi quyền thành viên và thời điểm công bố cho phép; replay vòng loại/luyện tập thuộc chủ tài khoản.
- Nếu kết quả đã thành công nhưng replay trong Storage chưa có, giao diện có thể dùng các ván đã lưu trong kết quả scoring job của chính người dùng làm phương án dự phòng.
- Tạo tài khoản, backup dữ liệu và kiểm tra quyền RLS trước khi mở đăng ký/thi. Không commit file `.env`, `config.local.env`, `.dev.vars` hoặc secrets.
- Mã SQLite và backend cũ nằm trong `backup/`; không dùng song song với Supabase làm hai nguồn dữ liệu.

# Dữ liệu và nguồn sự thật

## Luồng vận hành hiện tại

Supabase Postgres là nguồn dữ liệu chuẩn cho tài khoản, trạng thái giải, cấu hình vòng, bài nộp, ghép cặp, điểm trận, BXH, vé vớt và metadata replay. Các chuyển trạng thái quan trọng nằm trong RPC để thực hiện trong transaction.

Scoring module lưu tệp bot tạm trên máy chạy module, gọi Judge0 để chạy trận, rồi ghi kết quả và replay về Supabase. Tệp bot không được cung cấp cho thí sinh khác. Replay nén được tải lên bucket private trong Supabase Storage.

SQLite `ott.db` và các chương trình đồng bộ cũ không nằm trong luồng vận hành. Mã nguồn SQLite trước migration được giữ tại `backup/legacy_sqlite/` để khôi phục nếu cần.

## Bảng chính

| Bảng | Nội dung |
|---|---|
| `profiles` | Tên, vai trò, trạng thái, điểm đầu vào |
| `tournament_state`, `round_config`, `contest_days` | Trạng thái và lịch giải |
| `round_members`, `round_byes`, `matches` | Bảng đấu, lượt ghép và kết quả BO2 |
| `scoring_jobs`, `submissions` | Yêu cầu chấm, hash và bài nộp theo ngày |
| `daily_results`, `round_advancement` | BXH ngày và kết quả chuyển vòng |
| `replay_objects` | Metadata trỏ tới object nén trong Storage |

RLS giới hạn dữ liệu thí sinh; RPC người chơi chỉ trả đối thủ của mình và BXH đã tới giờ công bố. Admin dùng RPC có kiểm tra role để xem bảng tạm và tải CSV.

# Thể thức và quy trình vận hành giải đấu

Tài liệu này ghi lại thể thức BTC đã cung cấp làm yêu cầu chuẩn cho việc chuyển vận hành khỏi SQLite. Đây là đặc tả mục tiêu; các mục chưa có trong scoring module/Supabase được đánh dấu rõ, không được xem là đã vận hành chỉ vì đã có bảng dữ liệu.

## Quy mô và các giai đoạn

- Tối đa 4.000 thí sinh đăng ký đầu vào.
- Vòng loại đánh giá bot của thí sinh với các bot do BTC cung cấp. Thí sinh dưới ngưỡng bị loại trực tiếp.
- Những người đạt chuẩn được sắp theo điểm từ thấp đến cao, chia thành các dải điểm; từ mỗi dải phân bổ thí sinh rải đều qua 40 bảng để cân bằng sức mạnh. Ví dụ 2.000 người chia thành 50 dải, mỗi dải có khoảng 40 người và đóng góp người vào cả 40 bảng.
- Giải có 5 vòng trong 5 tuần. Tuần/vòng thứ năm thi offline tại địa điểm tổ chức, không có Internet.
- Cấu hình top và vé vớt được giữ theo luật cũ: vòng 1: top 10/bảng + 40 vé vớt; vòng 2: top 8/bảng + 16 vé vớt; vòng 3: top 6/bảng + 8 vé vớt; vòng 4: top 4/bảng + 4 vé vớt; vòng 5: top 1.

## Một tuần thi đấu

- Mỗi vòng kéo dài 7 ngày: 6 ngày thường và ngày thứ 7 là ngày quyết định.
- Thí sinh phải có bài hợp lệ ở ít nhất 4 trong 6 ngày thường để được tham gia ngày thứ 7.
- Chỉ bot nộp thành công trong ngày mới được dùng cho các trận của ngày đó; không nộp khi chốt ngày bị xử thua.
- Ghép cặp và chấm chỉ bắt đầu sau khi hai bên trong cặp đã sẵn sàng hoặc khi BTC chốt ngày và áp dụng xử thua cho người không có bài. Không cho thí sinh xem mã nguồn của nhau.
- Mỗi ngày tạo điểm ngày mới từ 0. Thứ tự ngày đầu dùng seed trong bảng; các ngày sau sắp theo trung bình thứ hạng của những ngày đã chấm trước đó.
- Các trận của ngày hiện tại và đối thủ của chính thí sinh được hiển thị cho thí sinh. BXH trực tiếp không hiển thị cho thí sinh.
- Trong ngày thi, BTC nhận được bảng/tiến độ tối đa mỗi 15 phút để tự cập nhật Google Sheet. Sau khi ngày kết thúc, BXH chính thức được công bố vào ngày hôm sau.
- Ngày thứ 7 chỉ xếp hạng người đủ điều kiện 4/6 ngày. Top theo cấu hình vòng đi tiếp. Các vé vớt chọn từ người đủ điều kiện chưa nằm trong top, theo trung bình chỉ số `(hạng - 1) / số người được xếp hạng trong bảng` của 6 ngày thường; số thấp hơn xếp tốt hơn.

## Ghép trận trong ngày

- Mỗi cặp đấu BO2; mỗi bên đi trước một ván. Tổng điểm ván của A nằm trong `[-2, 2]`.
- Kết quả trận: thắng `+1` điểm bảng, thua `-1`, hòa `0`. Không có bài hợp lệ khi BTC chốt ngày bị xử `-1` theo quy tắc vắng mặt.
- Có 7 lượt ghép mỗi ngày. Lượt 1 ghép nửa trên thứ tự ban đầu với nửa dưới. Các lượt 2–7 ghép người cùng điểm trận, ưu tiên đối thủ chưa gặp trong ngày và dùng thứ tự ban đầu để phá hòa.
- Khi chốt ngày, mỗi người không nộp bài hợp lệ nhận `-1` cho trận đó; nếu cả hai vắng mặt thì mỗi người nhận `-1`. Bye nhận `0` điểm; hệ thống ưu tiên người chưa từng nhận bye trong vòng, và chỉ lặp bye nếu không còn lựa chọn khác.

## Quy tắc đầu vào hiện có trong code cũ

Vòng đầu vào dùng ba bot chuẩn trong `sample_bots/entry_bot0.py`–`entry_bot2.py` với trọng số `[1, 2, 3]`. Mỗi bot đối đầu hai ván đổi lượt đi trước; tổng kết quả mỗi cặp nằm trong `[-2, 2]`. Điểm đầu vào là `1*s0 + 2*s1 + 3*s2`; `entry_cut=-2`, thấp hơn ngưỡng bị loại. Thí sinh có tối đa 20 lượt và dùng điểm cao nhất.

## Nguồn dữ liệu và phân quyền mục tiêu

- Supabase Postgres là nguồn dữ liệu chuẩn cho trạng thái giải, hồ sơ, điểm đầu vào, bảng đấu, bài nộp, ngày thi, cặp đấu, kết quả, thứ hạng, điều kiện/vé vớt và nhà vô địch.
- Supabase RPC thực hiện các chuyển trạng thái và thao tác cạnh tranh cần transaction: chốt ngày, tạo cặp, áp kết quả, chốt BXH và chuyển vòng. Scoring module chạy bot qua Judge0, gửi kết quả và replay lên Supabase.
- Thí sinh đọc hồ sơ, trạng thái của mình, đối thủ trong ngày và BXH đã công bố. RLS/RPC không cấp quyền đọc source bot hoặc BXH tạm trong ngày.
- BTC đọc tiến độ và BXH tạm qua quyền admin, có thể xuất CSV để cập nhật bảng Google Sheet thủ công.
- Không dùng SQLite trong quy trình vận hành giải đấu. SQLite/source cũ chỉ được giữ trong `backup/legacy_sqlite/` để rollback. Dữ liệu lịch sử và source/replay cần backup/migrate riêng trước khi xóa.
- Tuần offline chưa thuộc phạm vi cài đặt hiện tại; website sẽ không hoạt động khi địa điểm không có Internet. Chỉ cài đặt các vòng online.

## Trạng thái triển khai

Migration `0006_online_tournament_operations.sql` bổ sung sức chứa, luật vòng, ghép cặp/bye, xử vắng mặt, chốt bảng mỗi ngày, công bố trễ, điều kiện 4/6, vé vớt/chuyển vòng và bảng tạm admin. Scoring module gọi các RPC này, chạy trận BO2 trên Judge0, lưu kết quả/replay lên Supabase và giới hạn song song. `tournament.py` nay chỉ đọc trạng thái Supabase; mã SQLite cũ và `data/sync.py` đã được đưa vào vùng backup/loại khỏi đường vận hành.

**Cần áp dụng và kiểm chứng migration `0005` và `0006` trên project Supabase trước khi chạy giải.** Chưa thể xác nhận SQL đã chạy trên project thật từ workspace. Chỉ các vòng 1–4 online được tạo; vòng 5 offline dừng ngoài phạm vi.

## Điểm đã chốt

1. Số lượt là 7: Trận 1 và Trận 2–7.
2. Vắng mặt nhận `-1` (kể cả khi cả hai cùng vắng mặt); bye nhận `0`.
3. Mức top/vé vớt giữ cấu hình cũ: V1 `10+40`, V2 `8+16`, V3 `6+8`, V4 `4+4`, V5 `top 1`.
4. Không cài đặt vòng offline; website không hoạt động khi không có Internet. Phạm vi triển khai là các vòng online.

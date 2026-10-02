# Ghép ảnh theo transcript cho CapCut

Ứng dụng Windows tạo slideshow có audio từ transcript có timestamp. Mỗi ảnh bắt đầu tại timestamp tương ứng và được giữ đến mốc kế tiếp. Ảnh cuối hiển thị đến hết audio.

## Tính năng

- Kiểm tra số dòng timestamp và số ảnh trước khi xuất.
- Sắp xếp ảnh theo tên tự nhiên, ví dụ `001.png`, `002.png`, `010.png`.
- Xem trước thời gian bắt đầu, kết thúc và thời lượng của từng ảnh.
- Chọn xuất kèm audio hoặc không kèm audio. Khi bỏ audio, có thể đặt thời lượng hiển thị của ảnh cuối.
- Xuất video MP4 với lựa chọn độ phân giải và FPS.
- Hiển thị tiến độ, thời gian đã xử lý, tốc độ FFmpeg và cảnh báo khi lâu chưa có cập nhật.
- Có thể hủy lúc đang xuất; tool hỏi xác nhận và giữ file MP4 cũ nếu có.

## Yêu cầu

- Windows, Python 3.9 trở lên và Tkinter.
- FFmpeg có `ffmpeg` và `ffprobe` trong biến môi trường `PATH`.

## Khởi chạy

Nhấp đúp `run_timeline_maker.bat`.

## Cách dùng

1. Chọn transcript, thư mục ảnh, đường dẫn MP4 đầu ra; bật **Kèm audio** nếu muốn thêm âm thanh.
2. Transcript cần có một timestamp ở đầu mỗi dòng, ví dụ:

   ```text
   [0:00] Câu mở đầu
   [0:03] Câu tiếp theo
   [0:07] Câu sau nữa
   ```

3. Đặt tên ảnh theo thứ tự cần dùng, ví dụ `001.png`, `002.png`, `003.png`.
4. Bấm **Xem timeline**. Số ảnh phải bằng số dòng timestamp và timestamp phải tăng dần. Ảnh đầu luôn bắt đầu từ `00:00`, kể cả khi mốc đầu ghi dạng `[0:00.190]`.
5. Chọn độ phân giải và FPS, rồi bấm **Tạo video MP4**. Nếu bỏ audio, nhập thời lượng của ảnh cuối.
6. Khi xuất xong, chọn có mở CapCut hay không. Tool mở thư mục chứa MP4; nếu mở CapCut, hãy tạo/mở project, bấm **Import**, rồi chọn video vừa tạo.

## Ghi chú

Kết quả là một clip MP4 chứa chuỗi ảnh và audio. Đây không phải project CapCut gồm các clip ảnh riêng lẻ có thể chỉnh sửa độc lập. Ảnh sẽ được cắt để lấp đầy khung hình đã chọn.

# Ghép ảnh theo transcript cho CapCut

Ứng dụng Windows tạo slideshow có audio từ transcript có timestamp. Mỗi ảnh bắt đầu tại timestamp tương ứng và được giữ đến mốc kế tiếp. Ảnh cuối hiển thị đến hết audio.

## Tính năng

- Kiểm tra số dòng timestamp và số ảnh trước khi xuất.
- Sắp xếp ảnh theo tên tự nhiên, ví dụ `001.png`, `002.png`, `010.png`.
- Xem trước thời gian bắt đầu, kết thúc và thời lượng của từng ảnh.
- Xuất video MP4 có audio, với lựa chọn độ phân giải và FPS.
- Hiển thị tiến độ, thời gian đã xử lý, tốc độ FFmpeg và cảnh báo khi lâu chưa có cập nhật.

## Yêu cầu

- Windows, Python 3.9 trở lên và Tkinter.
- FFmpeg có `ffmpeg` và `ffprobe` trong biến môi trường `PATH`.

## Khởi chạy

Nhấp đúp `run_timeline_maker.bat`.

## Cách dùng

1. Chọn transcript, thư mục ảnh, file audio và đường dẫn MP4 đầu ra.
2. Transcript cần có một timestamp ở đầu mỗi dòng, ví dụ:

   ```text
   [0:00] Câu mở đầu
   [0:03] Câu tiếp theo
   [0:07] Câu sau nữa
   ```

3. Đặt tên ảnh theo thứ tự cần dùng, ví dụ `001.png`, `002.png`, `003.png`.
4. Bấm **Kiểm tra timeline**. Số ảnh phải bằng số dòng timestamp; timestamp phải tăng dần và bắt đầu từ `00:00`.
5. Chọn độ phân giải và FPS, rồi bấm **Tạo video để đưa vào CapCut**.
6. Khi xuất xong, import MP4 vào CapCut.

## Ghi chú

Kết quả là một clip MP4 chứa chuỗi ảnh và audio. Đây không phải project CapCut gồm các clip ảnh riêng lẻ có thể chỉnh sửa độc lập. Ảnh sẽ được cắt để lấp đầy khung hình đã chọn.

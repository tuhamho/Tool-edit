# Ghép ảnh theo transcript cho CapCut

Tool Windows tạo một video slideshow có audio, dựa trên timestamp trong transcript.

## Cách dùng

1. Cài Python 3 và FFmpeg. `ffmpeg` và `ffprobe` cần chạy được từ PowerShell (có trong `PATH`).
2. Chạy `run_timeline_maker.bat`.
3. Chọn transcript có mỗi dòng dạng `[0:03] nội dung`, thư mục ảnh, file audio và đường dẫn video đầu ra.
4. Bấm **Kiểm tra timeline** để xem ảnh nào chạy ở từng khoảng. Ảnh được xếp theo tên tự nhiên: `001.png`, `002.png`, …
5. Bấm **Tạo video để đưa vào CapCut**, sau đó import MP4 kết quả vào CapCut.

## Quy tắc thời gian

Mỗi ảnh chạy từ timestamp ở dòng tương ứng đến timestamp dòng kế tiếp. Ảnh cuối chạy đến hết audio. Timestamp phải tăng dần, bắt đầu từ 00:00; số ảnh phải bằng số dòng có timestamp.

MP4 kết quả là một clip video có audio, không phải 190 clip ảnh riêng biệt có thể kéo dài/chỉnh sửa độc lập trong CapCut. Video giữ đúng các lần đổi ảnh theo timestamp.

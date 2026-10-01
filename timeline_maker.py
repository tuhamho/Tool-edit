"""Create a timed image slideshow from a timestamped transcript and audio."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
STAMP = re.compile(r"^\s*\[(\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)\]")


@dataclass
class Cue:
    seconds: float
    text: str


def to_seconds(value: str) -> float:
    parts = value.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    raise ValueError(f"Timestamp không hợp lệ: {value}")


def parse_transcript(path: Path) -> list[Cue]:
    cues = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        match = STAMP.match(line)
        if not match:
            raise ValueError(f"Dòng {line_number} không có timestamp dạng [0:03]:\n{line[:100]}")
        cues.append(Cue(to_seconds(match.group(1)), line[match.end():].strip()))
    if not cues:
        raise ValueError("Không tìm thấy dòng timestamp nào trong transcript.")
    if cues[0].seconds != 0:
        raise ValueError("Timestamp đầu tiên cần bắt đầu tại 00:00 để ảnh đầu xuất hiện từ đầu video.")
    for previous, current in zip(cues, cues[1:]):
        if current.seconds <= previous.seconds:
            raise ValueError("Timestamp cần tăng dần và không được trùng nhau.")
    return cues


def natural_key(path: Path):
    return [int(part) if part.isdigit() else part.casefold()
            for part in re.split(r"(\d+)", path.name)]


def get_duration(audio: Path, ffprobe: str) -> float:
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(audio)],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def build_video(images: list[Path], starts: list[float], duration: float, audio: Path,
                output: Path, ffmpeg: str, width: int, height: int, fps: int, report=None):
    ends = starts[1:] + [duration]
    with tempfile.TemporaryDirectory(prefix="tlm_") as temp_name:
        temp_dir = Path(temp_name)
        short_images = []
        for index, image in enumerate(images):
            alias = temp_dir / f"{index:03d}{image.suffix.lower()}"
            try:
                os.link(image, alias)
            except OSError:
                shutil.copy2(image, alias)
            short_images.append(alias)

        args = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
        for image, start, end in zip(short_images, starts, ends):
            args += ["-loop", "1", "-framerate", str(fps), "-t", f"{end-start:.6f}", "-i", str(image)]
        args += ["-i", str(audio)]
        filters = []
        for index in range(len(images)):
            filters.append(
                f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},setsar=1,fps={fps},format=yuv420p,"
                f"trim=duration={ends[index]-starts[index]:.6f},setpts=PTS-STARTPTS[v{index}]"
            )
        concat_inputs = "".join(f"[v{i}]" for i in range(len(images)))
        filters.append(f"{concat_inputs}concat=n={len(images)}:v=1:a=0[vout]")
        filter_file = temp_dir / "filters.txt"
        filter_file.write_text(";".join(filters), encoding="utf-8")
        args += ["-/filter_complex", str(filter_file), "-progress", "pipe:1", "-stats_period", "0.5", "-nostats",
                 "-map", "[vout]", "-map", f"{len(images)}:a:0",
                 "-t", f"{duration:.6f}", "-r", str(fps), "-c:v", "libx264", "-preset", "medium",
                 "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                 "-movflags", "+faststart", str(output)]
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   encoding="utf-8", errors="replace", bufsize=1)
        progress_data = {}
        for line in process.stdout:
            if "=" not in line:
                continue
            key, value = line.strip().split("=", 1)
            progress_data[key] = value
            if key == "progress" and report:
                try:
                    current = max(0, int(progress_data.get("out_time_us", "0") or 0)) / 1_000_000
                except ValueError:
                    current = 0.0
                percent = min(99.0, max(0.0, current / duration * 100))
                elapsed = App._clock(min(current, duration))
                speed = progress_data.get("speed", "")
                detail = f"Đang dựng video… {percent:.0f}% • {elapsed}/{App._clock(duration)}"
                if speed and speed != "N/A":
                    detail += f" • tốc độ {speed}"
                report(percent, detail)
        error_text = process.stderr.read()
        return_code = process.wait()
        if return_code:
            raise RuntimeError(error_text.strip() or f"FFmpeg kết thúc với mã lỗi {return_code}.")
        if report:
            report(100.0, f"Đang hoàn tất video… {App._clock(duration)}/{App._clock(duration)}")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Ghép ảnh theo transcript — CapCut")
        self.geometry("800x610")
        self.minsize(700, 540)
        self.transcript = tk.StringVar()
        self.image_dir = tk.StringVar()
        self.audio = tk.StringVar()
        self.output = tk.StringVar()
        self.status = tk.StringVar(value="Chọn transcript, thư mục ảnh và audio để kiểm tra timeline.")
        self.progress_value = tk.DoubleVar(value=0)
        self.encoding = False
        self.last_progress_time = 0.0
        self.latest_progress_text = ""
        self._make_ui()

    def _make_ui(self):
        root = ttk.Frame(self, padding=16)
        root.pack(fill="both", expand=True)
        ttk.Label(root, text="Tạo slideshow theo mốc transcript", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(root, text="Mỗi ảnh chạy từ timestamp của dòng đó đến timestamp kế tiếp.").pack(anchor="w", pady=(3, 12))
        self._path_row(root, "Transcript", self.transcript, self._pick_transcript)
        self._path_row(root, "Thư mục ảnh", self.image_dir, self._pick_images)
        self._path_row(root, "File audio", self.audio, self._pick_audio)
        self._path_row(root, "Video xuất ra", self.output, self._pick_output)
        options = ttk.Frame(root)
        options.pack(fill="x", pady=(5, 8))
        self.resolution = tk.StringVar(value="1920x1080")
        ttk.Label(options, text="Kích thước:").pack(side="left")
        ttk.Combobox(options, textvariable=self.resolution, values=["1920x1080", "1080x1920", "1280x720"],
                     state="readonly", width=14).pack(side="left", padx=(6, 18))
        ttk.Label(options, text="FPS:").pack(side="left")
        self.fps = tk.StringVar(value="30")
        ttk.Combobox(options, textvariable=self.fps, values=["24", "25", "30", "60"],
                     state="readonly", width=6).pack(side="left", padx=6)
        actions = ttk.Frame(root)
        actions.pack(fill="x", pady=(2, 8))
        ttk.Button(actions, text="Kiểm tra timeline", command=self.preview).pack(side="left")
        self.create_button = ttk.Button(actions, text="Tạo video để đưa vào CapCut", command=self.create)
        self.create_button.pack(side="left", padx=8)
        self.table = ttk.Treeview(root, columns=("number", "image", "start", "end", "duration"), show="headings", height=12)
        for col, label, width in [("number", "#", 48), ("image", "Ảnh", 300), ("start", "Bắt đầu", 105),
                                  ("end", "Kết thúc", 105), ("duration", "Thời lượng", 100)]:
            self.table.heading(col, text=label)
            self.table.column(col, width=width, anchor="w" if col == "image" else "center")
        self.table.pack(fill="both", expand=True)
        self.progress = ttk.Progressbar(root, variable=self.progress_value, maximum=100, mode="determinate")
        self.progress.pack(fill="x", pady=(8, 0))
        ttk.Label(root, textvariable=self.status, wraplength=750).pack(anchor="w", pady=(9, 0))

    def _path_row(self, parent, label, variable, picker):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text=label, width=14).pack(side="left")
        ttk.Entry(row, textvariable=variable).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Chọn…", command=picker).pack(side="left", padx=(6, 0))

    def _pick_transcript(self):
        value = filedialog.askopenfilename(filetypes=[("Text", "*.txt"), ("All files", "*.*")])
        if value:
            self.transcript.set(value)
            self._default_output()

    def _pick_images(self):
        value = filedialog.askdirectory()
        if value:
            self.image_dir.set(value)

    def _pick_audio(self):
        value = filedialog.askopenfilename(filetypes=[("Audio", "*.mp3 *.wav *.m4a *.aac *.flac"), ("All files", "*.*")])
        if value:
            self.audio.set(value)
            self._default_output()

    def _pick_output(self):
        value = filedialog.asksaveasfilename(defaultextension=".mp4", filetypes=[("MP4 video", "*.mp4")])
        if value:
            self.output.set(value)

    def _default_output(self):
        source = self.audio.get() or self.transcript.get()
        if source and not self.output.get():
            self.output.set(str(Path(source).with_name("slideshow_timeline.mp4")))

    def _inputs(self):
        transcript, image_dir, audio = Path(self.transcript.get()), Path(self.image_dir.get()), Path(self.audio.get())
        if not transcript.is_file() or not image_dir.is_dir() or not audio.is_file():
            raise ValueError("Hãy chọn đúng transcript, thư mục ảnh và file audio.")
        cues = parse_transcript(transcript)
        images = sorted((p for p in image_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS), key=natural_key)
        if len(images) != len(cues):
            numbers = {}
            for image in images:
                match = re.match(r"^(\d+)", image.stem)
                if match:
                    numbers.setdefault(match.group(1), []).append(image.name)
            duplicates = [names for names in numbers.values() if len(names) > 1]
            detail = ""
            if duplicates:
                detail = "\nCó số thứ tự bị trùng: " + "; ".join(", ".join(names) for names in duplicates)
            raise ValueError(
                f"Có {len(cues)} dòng timestamp nhưng tìm thấy {len(images)} ảnh. Cần số lượng bằng nhau."
                f"{detail}\nHãy chuyển ảnh dư ra khỏi thư mục hoặc đổi tên cho đúng thứ tự rồi kiểm tra lại."
            )
        ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:
            raise ValueError("Không tìm thấy ffmpeg/ffprobe. Cài FFmpeg và thêm vào PATH rồi mở lại tool.")
        duration = get_duration(audio, ffprobe)
        if cues[-1].seconds >= duration:
            raise ValueError(f"Timestamp cuối ({cues[-1].seconds:.2f}s) nằm ngoài thời lượng audio ({duration:.2f}s).")
        output = Path(self.output.get()) if self.output.get() else audio.with_name("slideshow_timeline.mp4")
        self.output.set(str(output))
        return cues, images, audio, output, ffmpeg, duration

    def preview(self):
        try:
            cues, images, _, _, _, duration = self._inputs()
            for row in self.table.get_children():
                self.table.delete(row)
            ends = [cue.seconds for cue in cues[1:]] + [duration]
            for i, (cue, image, end) in enumerate(zip(cues, images, ends), 1):
                self.table.insert("", "end", values=(i, image.name, self._clock(cue.seconds), self._clock(end), f"{end-cue.seconds:.2f}s"))
            self.status.set(f"Khớp {len(cues)} ảnh với {len(cues)} mốc • audio {self._clock(duration)} • ảnh cuối đến hết audio.")
        except Exception as error:
            messagebox.showerror("Không thể kiểm tra", str(error))

    def create(self):
        try:
            cues, images, audio, output, ffmpeg, duration = self._inputs()
            if output.resolve() in [p.resolve() for p in images] or output.resolve() == audio.resolve():
                raise ValueError("File video đầu ra cần có đường dẫn riêng.")
        except Exception as error:
            messagebox.showerror("Không thể tạo video", str(error))
            return
        width, height = map(int, self.resolution.get().split("x"))
        self.create_button.configure(state="disabled")
        self.encoding = True
        self.progress_value.set(0)
        self.last_progress_time = time.monotonic()
        self.latest_progress_text = "Đang chuẩn bị ảnh và khởi động FFmpeg…"
        self.status.set(self.latest_progress_text)
        self.after(1000, self._check_progress_heartbeat)

        def report(percent, detail):
            self.after(0, lambda percent=percent, detail=detail: self._set_progress(percent, detail))

        def worker():
            try:
                build_video(images, [cue.seconds for cue in cues], duration, audio, output, ffmpeg,
                            width, height, int(self.fps.get()), report)
                self.after(0, lambda: self._done(output))
            except Exception as error:
                message = str(error)
                self.after(0, lambda message=message: self._failed(message))

        threading.Thread(target=worker, daemon=True).start()

    def _set_progress(self, percent, detail):
        self.progress_value.set(percent)
        self.last_progress_time = time.monotonic()
        self.latest_progress_text = detail
        self.status.set(detail)

    def _check_progress_heartbeat(self):
        if not self.encoding:
            return
        quiet_for = time.monotonic() - self.last_progress_time
        if quiet_for >= 30:
            self.status.set(f"Chưa có cập nhật {int(quiet_for)} giây. FFmpeg có thể đang xử lý; cửa sổ vẫn hoạt động. Tiến độ gần nhất: {self.latest_progress_text}")
        self.after(1000, self._check_progress_heartbeat)

    def _done(self, output):
        self.encoding = False
        self.progress_value.set(100)
        self.create_button.configure(state="normal")
        self.status.set(f"Đã tạo: {output}")
        messagebox.showinfo("Hoàn tất", f"Video đã sẵn sàng để import vào CapCut:\n{output}")

    def _failed(self, error):
        self.encoding = False
        self.create_button.configure(state="normal")
        self.status.set("Tạo video thất bại.")
        messagebox.showerror("Lỗi FFmpeg", error)

    @staticmethod
    def _clock(seconds):
        whole = int(seconds)
        return f"{whole//60:02d}:{whole%60:02d}" + (f".{round((seconds-whole)*100):02d}" if seconds % 1 else "")


if __name__ == "__main__":
    App().mainloop()

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
import uuid
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


class ExportCancelled(Exception):
    pass


def build_video(images: list[Path], starts: list[float], duration: float, audio: Path | None,
                output: Path, ffmpeg: str, width: int, height: int, fps: int, report=None,
                cancel_event: threading.Event | None = None):
    ends = starts[1:] + [duration]
    partial = output.with_name(f".{output.stem}.{uuid.uuid4().hex}.partial{output.suffix}")
    try:
        with tempfile.TemporaryDirectory(prefix="tlm_") as temp_name:
            temp_dir = Path(temp_name)
            short_images = []
            for index, image in enumerate(images):
                if cancel_event and cancel_event.is_set():
                    raise ExportCancelled()
                alias = temp_dir / f"{index:03d}{image.suffix.lower()}"
                try:
                    os.link(image, alias)
                except OSError:
                    shutil.copy2(image, alias)
                short_images.append(alias)

            args = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
            for image, start, end in zip(short_images, starts, ends):
                args += ["-loop", "1", "-framerate", str(fps), "-t", f"{end-start:.6f}", "-i", str(image)]
            if audio:
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
                     "-map", "[vout]"]
            if audio:
                args += ["-map", f"{len(images)}:a:0", "-c:a", "aac", "-b:a", "192k"]
            args += ["-t", f"{duration:.6f}", "-r", str(fps), "-c:v", "libx264", "-preset", "medium",
                     "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(partial)]
            process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                       encoding="utf-8", errors="replace", bufsize=1)

            if cancel_event:
                def stop_if_cancelled():
                    while process.poll() is None:
                        if cancel_event.wait(0.2):
                            if process.poll() is None:
                                process.terminate()
                            return
                threading.Thread(target=stop_if_cancelled, daemon=True).start()

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
            if cancel_event and cancel_event.is_set():
                raise ExportCancelled()
            if return_code:
                raise RuntimeError(error_text.strip() or f"FFmpeg kết thúc với mã lỗi {return_code}.")
            if report:
                report(100.0, f"Đang hoàn tất video… {App._clock(duration)}/{App._clock(duration)}")
        os.replace(partial, output)
    finally:
        partial.unlink(missing_ok=True)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Ghép ảnh theo transcript — CapCut")
        self.geometry("880x760")
        self.minsize(760, 650)
        self.transcript = tk.StringVar()
        self.image_dir = tk.StringVar()
        self.audio = tk.StringVar()
        self.output = tk.StringVar()
        self.use_audio = tk.BooleanVar(value=True)
        self.last_image_duration = tk.StringVar(value="3")
        self.status = tk.StringVar(value="Chọn transcript và thư mục ảnh để bắt đầu.")
        self.progress_value = tk.DoubleVar(value=0)
        self.encoding = False
        self.cancel_event = None
        self.last_progress_time = 0.0
        self.latest_progress_text = ""
        self._setup_style()
        self._make_ui()

    def _setup_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("App.TFrame", background="#f3f6fb")
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("App.TLabel", background="#f3f6fb", foreground="#203047", font=("Segoe UI", 10))
        style.configure("Card.TLabel", background="#ffffff", foreground="#243247", font=("Segoe UI", 9))
        style.configure("Title.TLabel", background="#f3f6fb", foreground="#13243a", font=("Segoe UI", 19, "bold"))
        style.configure("Subtitle.TLabel", background="#f3f6fb", foreground="#65758b", font=("Segoe UI", 10))
        style.configure("TLabelframe", background="#ffffff", bordercolor="#dce4ef", relief="solid")
        style.configure("TLabelframe.Label", background="#ffffff", foreground="#25466c", font=("Segoe UI", 10, "bold"))
        style.configure("TEntry", fieldbackground="#ffffff", bordercolor="#cbd5e1", padding=6)
        style.configure("TCombobox", fieldbackground="#ffffff", padding=5)
        style.configure("TButton", padding=(12, 7), font=("Segoe UI", 9))
        style.configure("Accent.TButton", background="#2463eb", foreground="#ffffff", bordercolor="#2463eb",
                        font=("Segoe UI", 9, "bold"))
        style.map("Accent.TButton", background=[("active", "#1d4ed8"), ("disabled", "#aab8d0")],
                  foreground=[("disabled", "#eef2f8")])
        style.configure("Cancel.TButton", background="#fff1f0", foreground="#b42318", bordercolor="#f5c2c0")
        style.map("Cancel.TButton", background=[("active", "#ffe2df"), ("disabled", "#f5f5f5")])
        style.configure("Treeview", background="#ffffff", fieldbackground="#ffffff", foreground="#243247",
                        rowheight=25, bordercolor="#dce4ef", font=("Segoe UI", 9))
        style.configure("Treeview.Heading", background="#eaf0f8", foreground="#32435a",
                        font=("Segoe UI", 9, "bold"), padding=7)
        style.map("Treeview", background=[("selected", "#dbeafe")], foreground=[("selected", "#173b72")])
        style.configure("Horizontal.TProgressbar", troughcolor="#e2e8f0", background="#2670e8", thickness=12)

    def _make_ui(self):
        root = ttk.Frame(self, padding=18, style="App.TFrame")
        root.pack(fill="both", expand=True)
        ttk.Label(root, text="Ghép ảnh theo thời gian", style="Title.TLabel").pack(anchor="w")
        ttk.Label(root, text="Tạo slideshow từ transcript, ảnh và audio — sẵn sàng nhập vào CapCut.",
                  style="Subtitle.TLabel").pack(anchor="w", pady=(3, 13))

        source_card = ttk.LabelFrame(root, text="  Nguồn media  ", padding=12)
        source_card.pack(fill="x", pady=(0, 10))
        self._path_row(source_card, "Transcript", self.transcript, self._pick_transcript)
        self._path_row(source_card, "Thư mục ảnh", self.image_dir, self._pick_images)
        audio_controls = ttk.Frame(source_card, style="Card.TFrame")
        audio_controls.pack(fill="x", pady=(4, 0))
        self.audio_check = ttk.Checkbutton(audio_controls, text="Kèm audio", variable=self.use_audio,
                                           command=self._toggle_audio)
        self.audio_check.pack(side="left", padx=(0, 8))
        audio_row = ttk.Frame(audio_controls, style="Card.TFrame")
        audio_row.pack(side="left", fill="x", expand=True)
        self.audio_entry, self.audio_button = self._path_row(audio_row, "File audio", self.audio, self._pick_audio)
        self.last_duration_row = ttk.Frame(audio_controls, style="Card.TFrame")
        ttk.Label(self.last_duration_row, text="Thời lượng ảnh cuối (giây)", style="Card.TLabel").pack(side="left")
        ttk.Entry(self.last_duration_row, textvariable=self.last_image_duration, width=8).pack(side="left", padx=8)
        ttk.Label(self.last_duration_row, text="Dùng khi bỏ audio.", style="Card.TLabel").pack(side="left")

        output_card = ttk.LabelFrame(root, text="  Video đầu ra  ", padding=12)
        output_card.pack(fill="x", pady=(0, 10))
        self._path_row(output_card, "Lưu video tại", self.output, self._pick_output)
        options = ttk.Frame(output_card, style="Card.TFrame")
        options.pack(fill="x", pady=(7, 0))
        self.resolution = tk.StringVar(value="1920x1080")
        ttk.Label(options, text="Độ phân giải", style="Card.TLabel").pack(side="left")
        ttk.Combobox(options, textvariable=self.resolution, values=["1920x1080", "1080x1920", "1280x720"],
                     state="readonly", width=14).pack(side="left", padx=(7, 22))
        ttk.Label(options, text="FPS", style="Card.TLabel").pack(side="left")
        self.fps = tk.StringVar(value="30")
        ttk.Combobox(options, textvariable=self.fps, values=["24", "25", "30", "60"],
                     state="readonly", width=6).pack(side="left", padx=6)
        actions = ttk.Frame(root)
        actions.pack(fill="x", pady=(0, 8))
        ttk.Button(actions, text="Xem timeline", command=self.preview).pack(side="left")
        self.create_button = ttk.Button(actions, text="Tạo video MP4", style="Accent.TButton", command=self.create)
        self.create_button.pack(side="left", padx=8)
        self.cancel_button = ttk.Button(actions, text="Hủy", style="Cancel.TButton", state="disabled",
                                        command=self.cancel_export)
        self.cancel_button.pack(side="left")
        ttk.Label(actions, text="Ảnh được xếp theo số trong tên file.", style="Subtitle.TLabel").pack(side="right")

        table_card = ttk.Frame(root, style="App.TFrame")
        table_card.pack(fill="both", expand=True)
        self.table = ttk.Treeview(table_card, columns=("number", "image", "start", "end", "duration"), show="headings", height=9)
        for col, label, width in [("number", "#", 48), ("image", "Ảnh", 300), ("start", "Bắt đầu", 105),
                                  ("end", "Kết thúc", 105), ("duration", "Thời lượng", 100)]:
            self.table.heading(col, text=label)
            self.table.column(col, width=width, anchor="w" if col == "image" else "center")
        self.table.pack(fill="both", expand=True)
        self.progress = ttk.Progressbar(root, variable=self.progress_value, maximum=100, mode="determinate")
        self.progress.pack(fill="x", pady=(10, 0))
        ttk.Label(root, textvariable=self.status, style="Subtitle.TLabel", wraplength=820).pack(anchor="w", pady=(7, 0))

    def _path_row(self, parent, label, variable, picker):
        row = ttk.Frame(parent, style="Card.TFrame")
        row.pack(fill="x", pady=4)
        ttk.Label(row, text=label, width=15, style="Card.TLabel").pack(side="left")
        entry = ttk.Entry(row, textvariable=variable)
        entry.pack(side="left", fill="x", expand=True)
        button = ttk.Button(row, text="Chọn…", command=picker)
        button.pack(side="left", padx=(7, 0))
        return entry, button

    def _toggle_audio(self):
        enabled = self.use_audio.get()
        self.audio_entry.configure(state="normal" if enabled else "disabled")
        self.audio_button.configure(state="normal" if enabled else "disabled")
        if enabled:
            self.last_duration_row.pack_forget()
        else:
            self.last_duration_row.pack(fill="x", pady=(7, 0))

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
        source = (self.audio.get() if self.use_audio.get() else "") or self.transcript.get()
        if source and not self.output.get():
            self.output.set(str(Path(source).with_name("slideshow_timeline.mp4")))

    def _inputs(self):
        transcript = Path(self.transcript.get())
        image_dir = Path(self.image_dir.get())
        if not transcript.is_file() or not image_dir.is_dir():
            raise ValueError("Hãy chọn đúng transcript và thư mục ảnh.")
        audio = Path(self.audio.get()) if self.use_audio.get() and self.audio.get().strip() else None
        if self.use_audio.get() and (audio is None or not audio.is_file()):
            raise ValueError("Đang bật Kèm audio. Hãy chọn file audio hoặc bỏ chọn Kèm audio.")
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
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        if not ffmpeg or (audio and not ffprobe):
            raise ValueError("Không tìm thấy ffmpeg/ffprobe. Cài FFmpeg và thêm vào PATH rồi mở lại tool.")
        if audio:
            duration = get_duration(audio, ffprobe)
        else:
            try:
                last_still = float(self.last_image_duration.get())
            except ValueError as error:
                raise ValueError("Thời lượng ảnh cuối cần là một số giây hợp lệ.") from error
            if last_still <= 0:
                raise ValueError("Thời lượng ảnh cuối cần lớn hơn 0 giây.")
            duration = cues[-1].seconds + last_still
        if cues[-1].seconds >= duration:
            raise ValueError(f"Timestamp cuối ({cues[-1].seconds:.2f}s) phải nằm trước thời điểm kết thúc video ({duration:.2f}s).")
        output = Path(self.output.get()) if self.output.get() else (audio or transcript).with_name("slideshow_timeline.mp4")
        self.output.set(str(output))
        return cues, images, audio, output, ffmpeg, duration

    def preview(self):
        try:
            cues, images, audio, _, _, duration = self._inputs()
            for row in self.table.get_children():
                self.table.delete(row)
            ends = [cue.seconds for cue in cues[1:]] + [duration]
            for i, (cue, image, end) in enumerate(zip(cues, images, ends), 1):
                self.table.insert("", "end", values=(i, image.name, self._clock(cue.seconds), self._clock(end), f"{end-cue.seconds:.2f}s"))
            end_note = f"audio {self._clock(duration)}" if audio else f"không audio • kết thúc {self._clock(duration)}"
            self.status.set(f"Khớp {len(cues)} ảnh với {len(cues)} mốc • {end_note}.")
        except Exception as error:
            messagebox.showerror("Không thể kiểm tra", str(error))

    def create(self):
        try:
            cues, images, audio, output, ffmpeg, duration = self._inputs()
            if (output.resolve() in [p.resolve() for p in images]
                    or output.resolve() == Path(self.transcript.get()).resolve()
                    or (audio and output.resolve() == audio.resolve())):
                raise ValueError("File video đầu ra cần có đường dẫn riêng.")
        except Exception as error:
            messagebox.showerror("Không thể tạo video", str(error))
            return
        width, height = map(int, self.resolution.get().split("x"))
        self.create_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.encoding = True
        self.cancel_event = threading.Event()
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
                            width, height, int(self.fps.get()), report, self.cancel_event)
                self.after(0, lambda: self._done(output))
            except ExportCancelled:
                self.after(0, self._cancelled)
            except Exception as error:
                message = str(error)
                self.after(0, lambda message=message: self._failed(message))

        threading.Thread(target=worker, daemon=True).start()

    def cancel_export(self):
        if not self.encoding or not self.cancel_event:
            return
        confirmed = messagebox.askyesno(
            "Xác nhận hủy",
            "Bạn muốn dừng xuất video?\n\nVideo đang làm dở sẽ bị xóa. Nếu đã có video cũ cùng tên, video cũ vẫn được giữ.",
            icon="warning",
        )
        if confirmed:
            self.cancel_button.configure(state="disabled")
            self.status.set("Đang dừng FFmpeg và xóa video xuất dở…")
            self.cancel_event.set()

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
        self.cancel_event = None
        self.progress_value.set(100)
        self.create_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.status.set(f"Đã tạo: {output}")
        messagebox.showinfo(
            "Xuất video xong",
            f"MP4 đã được lưu tại:\n{output}\n\n"
            "Sau khi bấm OK, thư mục chứa video sẽ mở. Trong CapCut, tạo/mở project rồi bấm Import để chọn file MP4."
        )
        try:
            os.startfile(str(output.parent))
        except OSError as error:
            messagebox.showerror("Không mở được thư mục", f"Video vẫn đã được tạo tại:\n{output}\n\n{error}")

    def _failed(self, error):
        self.encoding = False
        self.cancel_event = None
        self.create_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.status.set("Tạo video thất bại.")
        messagebox.showerror("Lỗi FFmpeg", error)

    def _cancelled(self):
        self.encoding = False
        self.cancel_event = None
        self.create_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.status.set("Đã hủy xuất video. File MP4 cũ được giữ nguyên.")
        messagebox.showinfo("Đã hủy", "Đã dừng xuất video và xóa file tạm. File MP4 cũ (nếu có) không bị thay đổi.")

    @staticmethod
    def _clock(seconds):
        whole = int(seconds)
        return f"{whole//60:02d}:{whole%60:02d}" + (f".{round((seconds-whole)*100):02d}" if seconds % 1 else "")


if __name__ == "__main__":
    App().mainloop()

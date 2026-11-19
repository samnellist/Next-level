"""Built-in screen recorder (Windows): FFmpeg gdigrab for the picture, WASAPI loopback for
"what you hear" (the stream's sound), saved in 20-minute chunks. Each finished chunk goes
straight to Process, so clips appear while it's still recording.
"""
from __future__ import annotations

import csv
import ctypes
import socket
import subprocess
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

from . import db
from .config import IS_WINDOWS, RECORD_DIR, load_settings, tool
from .media import popen, run
from .notify import notify

SR = 48000
CH = 2


def list_windows() -> list[str]:
    if not IS_WINDOWS:
        return []
    user32 = ctypes.windll.user32
    titles: list[str] = []
    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                t = buf.value.strip()
                if t and t not in ("Program Manager", "Settings") and t not in titles:
                    titles.append(t)
        return True
    user32.EnumWindows(EnumProc(cb), 0)
    return titles


def list_audio_devices() -> dict:
    out = {"dshow": [], "loopback": False}
    try:
        import soundcard  # noqa: F401
        out["loopback"] = True
        out["speakers"] = [s.name for s in soundcard.all_speakers()]
        out["mics"] = [m.name for m in soundcard.all_microphones(include_loopback=False)]
    except Exception as e:
        out["loopback_error"] = str(e)[:200]
    if IS_WINDOWS:
        r = run([tool("ffmpeg"), "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"])
        for line in r.stderr.decode(errors="ignore").splitlines():
            if "(audio)" in line and '"' in line:
                out["dshow"].append(line.split('"')[1])
    return out


def _keep_awake(on: bool) -> None:
    if not IS_WINDOWS:
        return
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x1, 0x2
    flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED if on else 0)
    ctypes.windll.kernel32.SetThreadExecutionState(flags)


def _pick_encoder() -> list[str]:
    """Use the laptop's hardware video encoder when it works (much less CPU), else x264 ultrafast."""
    for enc, extra in (("h264_qsv", ["-global_quality", "25"]), ("h264_mf", ["-b:v", "8M", "-hw_encoding", "1"])):
        if not IS_WINDOWS:
            break
        r = run([tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "testsrc=s=1280x720:d=0.2", "-c:v", enc] + extra +
                ["-f", "null", "-"], timeout=30)
        if r.returncode == 0:
            return ["-c:v", enc] + extra
    return ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-tune", "zerolatency"]


class Recorder:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.started = 0.0
        self.opts: dict = {}
        self.chunks_done: list[str] = []
        self.list_file: Path | None = None
        self.stop_flag = threading.Event()
        self.lock = threading.Lock()
        self.error = ""
        self.audio_thread: threading.Thread | None = None
        self.prefix = ""

    # ---------- status ----------
    def status(self) -> dict:
        on = self.proc is not None and self.proc.poll() is None
        el = time.time() - self.started if on else 0
        return {"recording": on, "elapsed": el, "chunks": self.chunks_done, "options": self.opts,
                "error": self.error, "auto_stop_minutes": self.opts.get("auto_stop_minutes", 0)}

    # ---------- start ----------
    def start(self, opts: dict) -> dict:
        with self.lock:
            if self.proc and self.proc.poll() is None:
                raise RuntimeError("Already recording")
            st = load_settings()["record"]
            o = dict(st, **(opts or {}))
            self.opts = o
            self.error = ""
            self.chunks_done = []
            self.stop_flag.clear()
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.prefix = f"rec_{stamp}"
            self.list_file = RECORD_DIR / f"{self.prefix}_chunks.csv"
            seg = int(float(o.get("chunk_minutes", 20)) * 60)
            fps = int(o.get("fps", 30))

            cmd = [tool("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error"]
            target = o.get("target", "screen")
            if target == "test" or not IS_WINDOWS:
                # used for testing on non-Windows machines
                cmd += ["-re", "-f", "lavfi", "-i", f"testsrc2=s=1280x720:r={fps}"]
            else:
                cmd += ["-thread_queue_size", "1024", "-f", "gdigrab", "-framerate", str(fps), "-draw_mouse", "0"]
                if target == "window" and o.get("window_title"):
                    cmd += ["-i", f"title={o['window_title']}"]
                else:
                    cmd += ["-i", "desktop"]
            audio_mode = o.get("audio", "system")
            port = None
            if target == "test" or not IS_WINDOWS:
                cmd += ["-f", "lavfi", "-i", "sine=f=440:r=48000"]
            elif audio_mode == "system":
                port = _free_port()
                cmd += ["-thread_queue_size", "4096", "-f", "f32le", "-ar", str(SR), "-ac", str(CH),
                        "-i", f"tcp://127.0.0.1:{port}?listen=1"]
            elif audio_mode == "device" and o.get("audio_device"):
                cmd += ["-thread_queue_size", "4096", "-f", "dshow", "-i", f"audio={o['audio_device']}"]
            else:
                cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
            if IS_WINDOWS and o.get("mic_device"):
                cmd += ["-thread_queue_size", "4096", "-f", "dshow", "-i", f"audio={o['mic_device']}"]
                cmd += ["-filter_complex", "[1:a][2:a]amix=inputs=2:duration=first:dropout_transition=0[a]",
                        "-map", "0:v", "-map", "[a]"]
            else:
                cmd += ["-map", "0:v", "-map", "1:a"]
            cmd += ["-vf", "scale='min(1920,iw)':-2,format=yuv420p"]
            cmd += _pick_encoder()
            cmd += ["-g", str(fps * 2), "-c:a", "aac", "-b:a", "160k",
                    "-f", "segment", "-segment_time", str(seg), "-reset_timestamps", "1",
                    "-segment_format", "matroska", "-segment_list", str(self.list_file), "-segment_list_type", "csv",
                    str(RECORD_DIR / f"{self.prefix}_%03d.mkv")]
            self.proc = popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
            self.started = time.time()
            if port:
                self.audio_thread = threading.Thread(target=self._loopback, args=(port,), daemon=True)
                self.audio_thread.start()
            threading.Thread(target=self._monitor, daemon=True).start()
            if o.get("keep_awake", True):
                threading.Thread(target=self._awake_loop, daemon=True).start()
            db.event("info", "Recording started")
            return self.status()

    # ---------- system audio ----------
    def _loopback(self, port: int) -> None:
        sock = None
        for _ in range(100):  # wait for ffmpeg to open the port
            try:
                sock = socket.create_connection(("127.0.0.1", port), timeout=2)
                break
            except OSError:
                time.sleep(0.1)
        if sock is None:
            self.error = "Couldn't connect system audio to the recorder"
            return
        written = 0
        wlock = threading.Lock()
        t0 = time.time()

        def pad() -> None:
            # when nothing is playing Windows sends no audio at all; fill the gap with silence
            nonlocal written
            while not self.stop_flag.is_set():
                time.sleep(0.1)
                expected = int((time.time() - t0) * SR)
                missing = expected - written
                if missing > SR // 4:
                    with wlock:
                        try:
                            sock.sendall(b"\x00" * (missing * CH * 4))
                        except OSError:
                            return
                        written += missing
        try:
            import soundcard as sc
            speaker = sc.default_speaker()
            mic = sc.get_microphone(str(speaker.name), include_loopback=True)
            threading.Thread(target=pad, daemon=True).start()
            with mic.recorder(samplerate=SR, channels=CH, blocksize=1024) as rec:
                while not self.stop_flag.is_set():
                    data = rec.record(numframes=2400)
                    with wlock:
                        sock.sendall(data.astype("float32").tobytes())
                        written += len(data)
        except Exception as e:
            self.error = f"System audio problem: {e}. Try Settings > Recorder > audio device."
            traceback.print_exc()
            # keep the stream alive with silence so the video still records
            while not self.stop_flag.is_set():
                time.sleep(0.1)
                expected = int((time.time() - t0) * SR)
                if expected > written:
                    try:
                        sock.sendall(b"\x00" * ((expected - written) * CH * 4))
                    except OSError:
                        break
                    written = expected
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def _awake_loop(self) -> None:
        while not self.stop_flag.is_set() and self.proc and self.proc.poll() is None:
            _keep_awake(True)
            self.stop_flag.wait(30)
        _keep_awake(False)

    # ---------- chunk hand-off + auto stop ----------
    def _monitor(self) -> None:
        from .pipeline import queue_video
        seen = set()
        while True:
            alive = self.proc is not None and self.proc.poll() is None
            if alive:
                lim = float(self.opts.get("auto_stop_minutes") or 0)
                if lim and time.time() - self.started >= lim * 60:
                    db.event("info", f"Auto-stop after {lim:.0f} minutes")
                    self.stop()
            if self.list_file and self.list_file.exists():
                try:
                    rows = list(csv.reader(self.list_file.open(encoding="utf-8", errors="ignore")))
                except Exception:
                    rows = []
                for row in rows:
                    if not row or row[0] in seen:
                        continue
                    seen.add(row[0])
                    f = RECORD_DIR / Path(row[0]).name
                    if f.exists() and f.stat().st_size > 50_000:
                        self.chunks_done.append(f.name)
                        if self.opts.get("auto_process", True):
                            o = {"preset": self.opts.get("preset", "gta6"), "campaign_id": self.opts.get("campaign_id"),
                                 "source": "recording", "scout": bool(self.opts.get("scout")),
                                 "speed": float(self.opts.get("speed", 1.0) or 1.0)}
                            queue_video(str(f), o)
                            db.event("info", f"Recording chunk {len(self.chunks_done)} sent to Process")
            if not alive:
                if self.proc is not None:
                    err = self.proc.stderr.read().decode(errors="ignore") if self.proc.stderr else ""
                    if self.proc.returncode not in (0, None) and not self.stop_flag.is_set():
                        self.error = "Recorder stopped: " + err[-300:]
                        notify("Recording stopped", "FFmpeg stopped unexpectedly", "error")
                self.stop_flag.set()
                _keep_awake(False)
                return
            time.sleep(2)

    def stop(self) -> dict:
        p = self.proc
        if not p or p.poll() is not None:
            return self.status()
        self.stop_flag.set()
        try:
            p.stdin.write(b"q")
            p.stdin.flush()
        except Exception:
            pass
        try:
            p.wait(timeout=20)
        except subprocess.TimeoutExpired:
            p.terminate()
        _keep_awake(False)
        db.event("info", f"Recording stopped after {int((time.time() - self.started) // 60)} min")
        # let the monitor pick up the last chunk
        time.sleep(2.5)
        return self.status()


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


recorder = Recorder()

"""FFmpeg helpers: probing, audio extraction, frame reading."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Iterator

import numpy as np

from .config import IS_WINDOWS, tool

CREATE_FLAGS = 0x08000000 if IS_WINDOWS else 0  # CREATE_NO_WINDOW: no black boxes popping up


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, creationflags=CREATE_FLAGS, **kw)


def popen(cmd: list[str], **kw) -> subprocess.Popen:
    return subprocess.Popen(cmd, creationflags=CREATE_FLAGS, **kw)


def probe(path: str | Path) -> dict:
    r = run([tool("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    if r.returncode != 0:
        raise RuntimeError(f"Could not read this video file: {r.stderr.decode(errors='ignore')[-300:]}")
    d = json.loads(r.stdout or b"{}")
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), None)
    dur = float(d.get("format", {}).get("duration") or 0)
    if not dur and v and v.get("duration"):
        dur = float(v["duration"])
    w = h = 0
    fps = 30.0
    rot = 0
    if v:
        w, h = int(v.get("width", 0)), int(v.get("height", 0))
        try:
            num, den = v.get("avg_frame_rate", "30/1").split("/")
            fps = float(num) / float(den) if float(den) else 30.0
        except Exception:
            fps = 30.0
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = int(sd["rotation"])
        rot = int(v.get("tags", {}).get("rotate", rot) or rot)
        if abs(rot) in (90, 270):  # iPhone portrait recordings
            w, h = h, w
    return {"duration": dur, "width": w, "height": h, "fps": fps or 30.0,
            "has_video": v is not None, "has_audio": a is not None}


def extract_audio(src: str | Path, dst: str | Path, speed: float = 1.0, start: float = 0, dur: float | None = None) -> Path:
    """16 kHz mono WAV. If the recording was sped up (scout mode) it is slowed back down,
    so Whisper and the loudness analysis hear normal speech and timestamps match the original."""
    af = []
    s = speed
    while s > 2.0:            # atempo only accepts 0.5..2 per step
        af.append("atempo=0.5"); s /= 2
    while s < 0.5:
        af.append("atempo=2.0"); s *= 2
    if abs(s - 1.0) > 1e-3:
        af.append(f"atempo={1.0 / s:.6f}")
    cmd = [tool("ffmpeg"), "-y", "-v", "error"]
    if start:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(src)]
    if dur:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-vn", "-ac", "1", "-ar", "16000"]
    if af:
        cmd += ["-af", ",".join(af)]
    cmd += ["-c:a", "pcm_s16le", str(dst)]
    r = run(cmd)
    if r.returncode != 0:
        raise RuntimeError("Could not extract audio: " + r.stderr.decode(errors="ignore")[-300:])
    return Path(dst)


def read_wav(path: str | Path) -> np.ndarray:
    import wave
    with wave.open(str(path), "rb") as w:
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def frames(src: str | Path, fps: float, width: int, height: int, start: float = 0, dur: float | None = None,
           gray: bool = False) -> Iterator[np.ndarray]:
    """Decode frames at a fixed rate, scaled to width x height (letterboxing is not used: stretch is fine for analysis)."""
    pix = "gray" if gray else "bgr24"
    ch = 1 if gray else 3
    cmd = [tool("ffmpeg"), "-v", "error"]
    if start:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(src)]
    if dur:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-an", "-vf", f"fps={fps},scale={width}:{height}:flags=area", "-f", "rawvideo", "-pix_fmt", pix, "-"]
    p = popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10 ** 7)
    size = width * height * ch
    try:
        while True:
            buf = p.stdout.read(size)
            if not buf or len(buf) < size:
                break
            a = np.frombuffer(buf, dtype=np.uint8)
            yield a.reshape((height, width)) if gray else a.reshape((height, width, 3))
    finally:
        p.stdout.close()
        p.kill()
        p.wait()


def grab_frame(src: str | Path, t: float, width: int = 0) -> np.ndarray | None:
    info_w = width
    cmd = [tool("ffmpeg"), "-v", "error", "-ss", f"{max(t, 0):.3f}", "-i", str(src), "-frames:v", "1"]
    if info_w:
        cmd += ["-vf", f"scale={info_w}:-2"]
    cmd += ["-f", "image2pipe", "-vcodec", "png", "-"]
    r = run(cmd)
    if r.returncode != 0 or not r.stdout:
        return None
    import cv2
    return cv2.imdecode(np.frombuffer(r.stdout, np.uint8), cv2.IMREAD_COLOR)

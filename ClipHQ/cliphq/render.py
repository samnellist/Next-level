"""Make the final vertical clip: 1080x1920, H.264, 30 fps, audio at -14 LUFS, captions burned in."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from . import framing
from .captions import build_ass
from .config import FONTS_DIR, ROOT, WORK_DIR, tool
from .media import grab_frame, popen, probe, run

OW, OH = 1080, 1920
FPS = 30
STACK_TOP = 0.40   # facecam takes the top 40%
FRAME_CENTER_Y = 900  # where the 16:9 picture sits in wide / blur layouts (captions go just below it)


def _blur_regions(img: np.ndarray, regions: list[list[float]]) -> None:
    h, w = img.shape[:2]
    for r in regions or []:
        x0, y0 = int(r[0] * w), int(r[1] * h)
        x1, y1 = int((r[0] + r[2]) * w), int((r[1] + r[3]) * h)
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        patch = img[y0:y1, x0:x1]
        small = cv2.resize(patch, (max(2, (x1 - x0) // 12), max(2, (y1 - y0) // 12)), interpolation=cv2.INTER_AREA)
        small = cv2.GaussianBlur(small, (0, 0), 2)
        img[y0:y1, x0:x1] = cv2.resize(small, (x1 - x0, y1 - y0), interpolation=cv2.INTER_LINEAR)


def _cover(img: np.ndarray, w: int, h: int, cx: float = 0.5, cy: float = 0.5) -> np.ndarray:
    """Scale + crop img to exactly w x h, keeping (cx, cy) as centred as possible."""
    ih, iw = img.shape[:2]
    s = max(w / iw, h / ih)
    cw, ch = min(iw, w / s), min(ih, h / s)
    x0 = int(np.clip(cx * iw - cw / 2, 0, iw - cw))
    y0 = int(np.clip(cy * ih - ch / 2, 0, ih - ch))
    crop = img[y0:y0 + int(round(ch)), x0:x0 + int(round(cw))]
    return cv2.resize(crop, (w, h), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)


def _fit_width(img: np.ndarray, w: int) -> np.ndarray:
    ih, iw = img.shape[:2]
    h = int(round(ih * w / iw / 2)) * 2
    return cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA if w < iw else cv2.INTER_CUBIC)


def _measure_loudness(src: str, start: float, dur: float) -> dict | None:
    r = run([tool("ffmpeg"), "-hide_banner", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", src, "-vn",
             "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"])
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr.decode(errors="ignore"), re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        if d.get("input_i") in ("-inf", None) or float(d["input_i"]) < -70:
            return None
        return d
    except Exception:
        return None


def render_clip(src: str, out: str | Path, start: float, end: float, layout: str, words: list[dict], hook: str,
                style: str, facecam: list[float] | None = None, extra_texts: list[dict] | None = None,
                blur_regions: list[list[float]] | None = None, hook_seconds: float = 3.5,
                preset: str = "veryfast", captions_on: bool = True, hook_style: int = 0,
                caption_y: float | None = None, progress: Callable[[float], None] | None = None) -> dict:
    info = probe(src)
    sw, sh = info["width"], info["height"]
    if not sw or not sh:
        raise RuntimeError("This file has no video picture.")
    # work resolution: max 1920 wide / 1080 tall (keeps it fast on a laptop)
    scale = min(1.0, 1920 / max(sw, sh) if sw >= sh else 1920 / sh)
    ww, wh = int(sw * scale) // 2 * 2, int(sh * scale) // 2 * 2
    dur = max(1.0, end - start)
    n_frames = int(round(dur * FPS))
    portrait = wh > ww

    if layout == "stacked" and not facecam:
        layout = "action"
    # --- camera paths ---
    times = np.arange(n_frames) / FPS
    path_x = np.full(n_frames, 0.5)
    path_y = np.full(n_frames, 0.5)
    crop_frac = min(1.0, (wh * 9 / 16) / ww)  # width of a full-height 9:16 crop, as a fraction
    if layout == "face" and not portrait:
        fp = framing.face_path(src, start, end, sw, sh, crop_frac)
        if fp["x"]:
            path_x = framing.smooth_path(np.array(fp["t"]), np.array(fp["x"]), times, dead=0.035, speed=0.5)
        # mostly 2+ people that don't fit? Use the wide shot instead of cutting someone in half.
        if fp["multi_ratio"] > 0.5 and _people_dont_fit(fp, crop_frac):
            layout = "wide"
    elif layout in ("action", "stacked") and not portrait:
        excl = [facecam] if facecam else []
        excl += blur_regions or []
        ap = framing.action_path(src, start, end, sw, sh, excl)
        if ap["x"]:
            path_x = framing.smooth_path(np.array(ap["t"]), np.array(ap["x"]), times, dead=0.06, speed=0.35)
    if progress:
        progress(0.1)

    cap_y = caption_y if caption_y is not None else (0.58 if layout == "stacked" else 0.66 if layout in ("face", "action") else 0.70)
    ass = build_ass(words, start, end, style, hook, extra_texts, hook_seconds, cap_y, hook_style, captions_on)
    out = Path(out)
    ass_path = WORK_DIR / (out.stem + ".ass")
    ass_path.write_text(ass, "utf-8")

    loud = _measure_loudness(src, start, dur) if info["has_audio"] else None
    if loud:
        af = (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={loud['input_i']}:measured_TP={loud['input_tp']}:"
              f"measured_LRA={loud['input_lra']}:measured_thresh={loud['input_thresh']}:offset={loud['target_offset']}:linear=true")
    else:
        af = "loudnorm=I=-14:TP=-1.5:LRA=11"
    af += f",aresample=48000,afade=t=in:d=0.04,afade=t=out:st={max(0, dur - 0.15):.3f}:d=0.15"

    rel_ass = ass_path.relative_to(ROOT).as_posix()
    rel_fonts = FONTS_DIR.relative_to(ROOT).as_posix()
    vf = f"ass={rel_ass}:fontsdir={rel_fonts},format=yuv420p"
    tmp_out = out.with_suffix(".part.mp4")
    cmd = [tool("ffmpeg"), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{OW}x{OH}", "-r", str(FPS), "-i", "-"]
    if info["has_audio"]:
        cmd += ["-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", src, "-map", "0:v", "-map", "1:a:0", "-af", af]
    else:
        cmd += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v", "-map", "1:a"]
    cmd += ["-vf", vf, "-c:v", "libx264", "-preset", preset, "-crf", "20", "-profile:v", "high", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", "-shortest", "-f", "mp4", str(tmp_out)]
    enc = popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(ROOT))

    dec_cmd = [tool("ffmpeg"), "-v", "error", "-ss", f"{start:.3f}", "-i", src, "-t", f"{dur:.3f}", "-an",
               "-vf", f"fps={FPS},scale={ww}:{wh}:flags=bicubic", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    dec = popen(dec_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10 ** 7)
    fsize = ww * wh * 3
    bg_dark = np.zeros((OH, OW, 3), np.uint8)
    # dark gradient background for the wide layout
    for y in range(OH):
        v = int(14 + 10 * (1 - abs(y - OH / 2) / (OH / 2)))
        bg_dark[y, :] = (v + 4, v, v)
    i = 0
    last = None
    try:
        while i < n_frames:
            buf = dec.stdout.read(fsize)
            if not buf or len(buf) < fsize:
                if last is None:
                    break
                frame = last  # pad the end with the last frame if the decoder ended early
            else:
                frame = np.frombuffer(buf, np.uint8).reshape((wh, ww, 3)).copy()
                if blur_regions:
                    _blur_regions(frame, blur_regions)
                last = frame
            canvas = _compose(frame, layout, path_x[i], path_y[i], facecam, bg_dark, portrait)
            try:
                enc.stdin.write(canvas.tobytes())
            except (BrokenPipeError, OSError):
                break
            i += 1
            if progress and i % 15 == 0:
                progress(0.1 + 0.88 * i / n_frames)
    finally:
        dec.kill(); dec.wait()
        try:
            enc.stdin.close()
        except Exception:
            pass
        err = enc.stderr.read().decode(errors="ignore")
        enc.wait()
    if enc.returncode != 0 or not tmp_out.exists():
        raise RuntimeError("Video export failed: " + err[-400:])
    tmp_out.replace(out)
    thumb = out.with_suffix(".jpg")
    img = grab_frame(str(out), min(1.2, dur / 2), width=540)
    if img is not None:
        cv2.imwrite(str(thumb), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if progress:
        progress(1.0)
    return {"file": str(out), "thumb": str(thumb), "layout": layout}


def _people_dont_fit(fp: dict, crop_frac: float) -> bool:
    xs = fp["x"]
    return bool(xs) and (max(xs) - min(xs)) > crop_frac * 0.9


def _compose(frame: np.ndarray, layout: str, px: float, py: float, facecam: list[float] | None,
             bg_dark: np.ndarray, portrait: bool) -> np.ndarray:
    h, w = frame.shape[:2]
    if portrait and layout in ("face", "action", "stacked"):
        return _cover(frame, OW, OH, 0.5, 0.5)
    if layout in ("face", "action"):
        return _cover(frame, OW, OH, float(px), 0.5)
    if layout == "stacked" and facecam:
        top_h = int(OH * STACK_TOP) // 2 * 2
        # trim 3% inside the box so facecam borders / frames don't show
        ix, iy = facecam[2] * 0.03, facecam[3] * 0.03
        x0, y0 = int((facecam[0] + ix) * w), int((facecam[1] + iy) * h)
        x1, y1 = int((facecam[0] + facecam[2] - ix) * w), int((facecam[1] + facecam[3] - iy) * h)
        cam = frame[max(0, y0):min(h, y1), max(0, x0):min(w, x1)]
        top = _cover(cam, OW, top_h, 0.5, 0.45) if cam.size else np.zeros((top_h, OW, 3), np.uint8)
        bottom = _cover(frame, OW, OH - top_h, float(px), 0.5)
        canvas = np.vstack([top, bottom])
        canvas[top_h - 3:top_h + 3, :] = (0, 0, 0)  # thin divider
        return canvas
    if layout == "blur":
        small = cv2.resize(frame, (w // 8, h // 8), interpolation=cv2.INTER_AREA)
        bg = _cover(cv2.GaussianBlur(small, (0, 0), 6), OW, OH)
        bg = (bg.astype(np.float32) * 0.5).astype(np.uint8)
        fg = _fit_width(frame, OW)
        canvas = bg
    else:  # wide
        canvas = bg_dark.copy()
        fg = _fit_width(frame, OW - 0)
    fh = fg.shape[0]
    y0 = int(np.clip(FRAME_CENTER_Y - fh / 2, 0, OH - fh))
    canvas[y0:y0 + fh] = fg
    return canvas

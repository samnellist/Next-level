"""Where to point the 9:16 'camera'.

- Faces: OpenCV YuNet (accurate, small model) with the built-in Haar detector as a backup.
- Facecam box: finds a face that stays in the same spot across the video, then finds the
  box edges around it (facecam borders don't move while the game behind them does).
- Tracking paths: smooth, slow camera moves with a dead-zone so it never jitters.
"""
from __future__ import annotations

import threading

import cv2
import numpy as np

from .config import MODELS_DIR

_det_lock = threading.Lock()


class FaceDetector:
    def __init__(self) -> None:
        self.yunet = None
        p = MODELS_DIR / "face_detection_yunet_2023mar.onnx"
        if p.exists() and p.stat().st_size > 10000 and hasattr(cv2, "FaceDetectorYN"):
            try:
                self.yunet = cv2.FaceDetectorYN.create(str(p), "", (320, 320), 0.7, 0.3, 5000)
            except Exception:
                self.yunet = None
        self.haar = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        self.haar_p = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_profileface.xml")

    def detect(self, img: np.ndarray) -> list[tuple[float, float, float, float, float]]:
        """Returns faces as (x, y, w, h, score) in pixels of img."""
        h, w = img.shape[:2]
        with _det_lock:
            if self.yunet is not None:
                self.yunet.setInputSize((w, h))
                _, faces = self.yunet.detect(img)
                if faces is None:
                    return []
                return [(float(f[0]), float(f[1]), float(f[2]), float(f[3]), float(f[-1])) for f in faces]
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        g = cv2.equalizeHist(g)
        mins = max(24, w // 40)
        out = []
        for c in (self.haar, self.haar_p):
            for (x, y, fw, fh) in c.detectMultiScale(g, 1.1, 6, minSize=(mins, mins)):
                out.append((float(x), float(y), float(fw), float(fh), 0.8))
        # merge duplicates
        merged = []
        for f in sorted(out, key=lambda f: -f[2]):
            if all(_iou(f, m) < 0.3 for m in merged):
                merged.append(f)
        return merged


def _iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a[0], a[1], a[0] + a[2], a[1] + a[3]
    bx1, by1, bx2, by2 = b[0], b[1], b[0] + b[2], b[1] + b[3]
    iw = max(0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    return inter / (a[2] * a[3] + b[2] * b[3] - inter + 1e-6)


_detector: FaceDetector | None = None


def detector() -> FaceDetector:
    global _detector
    if _detector is None:
        _detector = FaceDetector()
    return _detector


def analyse_faces(src: str, times: list[float]) -> dict:
    """Look at a handful of frames: how many faces, how big, and is there a facecam box?"""
    from .media import grab_frame
    det = detector()
    samples = []
    imgs = []
    for t in times:
        img = grab_frame(src, t, width=960)
        if img is None:
            continue
        imgs.append(img)
        H, W = img.shape[:2]
        fs = [(x / W, y / H, w / W, h / H, s) for (x, y, w, h, s) in det.detect(img)]
        samples.append(fs)
    if not samples:
        return {"faces_avg": 0, "big_face": False, "facecam": None, "multi": False}
    counts = [len(s) for s in samples]
    faces_avg = float(np.mean(counts))
    big = [f for s in samples for f in s if f[2] > 0.10]
    small = [f for s in samples for f in s if f[2] <= 0.16]
    facecam = _find_facecam(samples, imgs)
    multi = float(np.mean([c >= 2 for c in counts])) > 0.5
    return {"faces_avg": faces_avg, "big_face": len(big) >= max(1, len(samples) * 0.4) and facecam is None,
            "facecam": facecam, "multi": multi, "n": len(samples), "small_faces": len(small)}


def _find_facecam(samples: list[list], imgs: list[np.ndarray]) -> list[float] | None:
    pts = [f for s in samples for f in s]
    if not pts:
        return None
    # cluster face centres
    best = None
    for f in pts:
        cx, cy = f[0] + f[2] / 2, f[1] + f[3] / 2
        members = [g for g in pts if abs(g[0] + g[2] / 2 - cx) < 0.06 and abs(g[1] + g[3] / 2 - cy) < 0.08]
        frames_with = sum(1 for s in samples if any(abs(g[0] + g[2] / 2 - cx) < 0.06 and abs(g[1] + g[3] / 2 - cy) < 0.08 for g in s))
        if best is None or frames_with > best[0]:
            best = (frames_with, members)
    frames_with, members = best
    if frames_with < max(2, 0.4 * len(samples)):
        return None
    fx = float(np.median([m[0] for m in members])); fy = float(np.median([m[1] for m in members]))
    fw = float(np.median([m[2] for m in members])); fh = float(np.median([m[3] for m in members]))
    cx, cy = fx + fw / 2, fy + fh / 2
    # A facecam is a small face, not in the middle of the screen
    if fw > 0.2:
        return None
    if 0.3 < cx < 0.7 and 0.3 < cy < 0.7:
        return None
    # default guess: a 4:3-ish box around the face
    bw, bh = fw * 3.4, fh * 3.0
    x0, y0 = cx - bw / 2, cy - bh / 2 + fh * 0.15
    box = [x0, y0, x0 + bw, y0 + bh]
    # refine with edges that stay still across frames (the facecam border)
    try:
        box = _refine_box(imgs, box, (fx, fy, fw, fh))
    except Exception:
        pass
    x0, y0, x1, y1 = max(0, box[0]), max(0, box[1]), min(1, box[2]), min(1, box[3])
    # snap to the frame edge when close (most facecams sit in a corner)
    if x0 < 0.03: x0 = 0.0
    if y0 < 0.03: y0 = 0.0
    if x1 > 0.97: x1 = 1.0
    if y1 > 0.97: y1 = 1.0
    if x1 - x0 < fw * 1.5 or y1 - y0 < fh * 1.5:
        return None
    return [round(x0, 4), round(y0, 4), round(x1 - x0, 4), round(y1 - y0, 4)]


def _refine_box(imgs: list[np.ndarray], box: list[float], face: tuple) -> list[float]:
    H, W = imgs[0].shape[:2]
    grays = [cv2.cvtColor(i, cv2.COLOR_BGR2GRAY).astype(np.float32) for i in imgs if i.shape[:2] == (H, W)]
    gx = np.median([np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)) for g in grays], axis=0)
    gy = np.median([np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)) for g in grays], axis=0)
    fx, fy, fw, fh = face[0] * W, face[1] * H, face[2] * W, face[3] * H
    y_a, y_b = int(max(0, fy - fh)), int(min(H, fy + 2 * fh))
    x_a, x_b = int(max(0, fx - fw)), int(min(W, fx + 2 * fw))
    col = gx[y_a:y_b].mean(axis=0)
    row = gy[:, x_a:x_b].mean(axis=1)
    thr_c = col.mean() * 3
    thr_r = row.mean() * 3
    out = list(box)

    def best_in(arr, lo, hi, thr):
        lo, hi = int(max(0, lo)), int(min(len(arr), hi))
        if hi - lo < 2:
            return None
        i = lo + int(np.argmax(arr[lo:hi]))
        return i if arr[i] > thr else None

    l = best_in(col, fx - 2.2 * fw, fx - 0.4 * fw, thr_c)
    r = best_in(col, fx + 1.4 * fw, fx + 3.2 * fw, thr_c)
    t = best_in(row, fy - 1.8 * fh, fy - 0.3 * fh, thr_r)
    b = best_in(row, fy + 1.4 * fh, fy + 3.0 * fh, thr_r)
    if l is not None: out[0] = l / W
    if r is not None: out[2] = r / W
    if t is not None: out[1] = t / H
    if b is not None: out[3] = b / H
    return out


def choose_layout(face_info: dict, preset: str, gta: bool) -> str:
    if face_info.get("facecam") and (gta or preset in ("gta6", "gaming")):
        return "stacked"
    if face_info.get("multi"):
        return "wide"
    if face_info.get("big_face"):
        return "face"
    if face_info.get("facecam"):
        return "stacked"
    if gta or preset == "gaming":
        return "action"
    return "blur" if face_info.get("faces_avg", 0) < 0.3 else "face"


def smooth_path(times: np.ndarray, values: np.ndarray, out_times: np.ndarray, dead: float = 0.04,
                speed: float = 0.6) -> np.ndarray:
    """Turn noisy targets into a calm camera move: ignore small changes (dead-zone),
    then ease toward the target like a camera operator would."""
    if len(values) == 0:
        return np.full(len(out_times), 0.5)
    tgt = np.interp(out_times, times, values)
    out = np.empty_like(tgt)
    pos = tgt[0]
    vel = 0.0
    dt = (out_times[1] - out_times[0]) if len(out_times) > 1 else 1 / 30
    for i, t in enumerate(tgt):
        err = t - pos
        if abs(err) < dead:
            err = 0.0
        else:
            err -= np.sign(err) * dead
        # critically damped spring
        k = speed * 12
        acc = k * k * err - 2 * k * vel
        vel += acc * dt
        pos += vel * dt
        out[i] = pos
    return out


def face_path(src: str, start: float, end: float, src_w: int, src_h: int, crop_w_frac: float,
              sample_fps: float = 4) -> dict:
    """Per-frame horizontal centre (0..1) for a face-tracked crop, plus whether the shot should go wide."""
    from .media import frames
    det = detector()
    W = 640
    H = int(round(src_h * W / src_w / 2)) * 2
    ts, xs, multi_n, n = [], [], 0, 0
    for i, f in enumerate(frames(src, sample_fps, W, H, start=start, dur=end - start)):
        faces = det.detect(f)
        n += 1
        t = i / sample_fps
        if not faces:
            continue
        faces = sorted(faces, key=lambda f: -f[2] * f[3])
        main = faces[0]
        big_others = [g for g in faces[1:] if g[2] * g[3] > 0.35 * main[2] * main[3]]
        if big_others:
            multi_n += 1
            xs_all = [g[0] for g in [main] + big_others] + [g[0] + g[2] for g in [main] + big_others]
            span = (max(xs_all) - min(xs_all)) / W
            cx = (max(xs_all) + min(xs_all)) / 2 / W
            if span > crop_w_frac * 0.95:
                cx = (main[0] + main[2] / 2) / W
        else:
            cx = (main[0] + main[2] / 2) / W
        ts.append(t); xs.append(cx)
    return {"t": ts, "x": xs, "multi_ratio": multi_n / max(1, n), "found": len(xs) / max(1, n)}


def action_path(src: str, start: float, end: float, src_w: int, src_h: int, exclude: list[list[float]],
                sample_fps: float = 6) -> dict:
    """Follow the movement: where in the frame is the action (car, character, explosion)?"""
    from .media import frames
    W, H = 256, 144
    mask_ex = np.ones((H, W), np.float32)
    for r in exclude or []:
        x0, y0 = int(r[0] * W), int(r[1] * H)
        mask_ex[y0:int((r[1] + r[3]) * H), x0:int((r[0] + r[2]) * W)] = 0
    # also ignore the very edges (HUD and letterbox) a bit
    mask_ex[:, :8] *= 0.3; mask_ex[:, -8:] *= 0.3
    prev = None
    ts, xs, ys = [], [], []
    for i, f in enumerate(frames(src, sample_fps, W, H, start=start, dur=end - start, gray=True)):
        g = cv2.GaussianBlur(f, (5, 5), 0).astype(np.float32)
        if prev is not None:
            # remove global camera motion first so we track the thing moving, not the whole screen
            (dx, dy), _ = cv2.phaseCorrelate(prev, g)
            Mt = np.float32([[1, 0, dx], [0, 1, dy]])
            prev_al = cv2.warpAffine(prev, Mt, (W, H), borderMode=cv2.BORDER_REPLICATE)
            d = np.abs(g - prev_al) * mask_ex
            d[d < 12] = 0
            tot = d.sum()
            if tot > W * H * 0.4:
                col = d.sum(axis=0)
                cx = float((col * np.arange(W)).sum() / tot) / W
                row = d.sum(axis=1)
                cy = float((row * np.arange(H)).sum() / tot) / H
                ts.append(i / sample_fps); xs.append(cx); ys.append(cy)
        prev = g
    # in GTA the player character / car is usually near the centre: pull gently toward it
    xs = [0.65 * x + 0.35 * 0.5 for x in xs]
    return {"t": ts, "x": xs, "y": ys}

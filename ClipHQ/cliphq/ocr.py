"""Free on-screen text reading for the GTA HUD.

Uses RapidOCR (pip, works offline, fast on CPU). If you installed Tesseract instead,
set 'OCR engine' to tesseract in Settings. OCR is slow, so it only looks at the
moments that already look interesting, plus a light sweep every few seconds.
"""
from __future__ import annotations

import re
import shutil
import threading

import numpy as np

_engine = None
_name = None
_lock = threading.Lock()


def engine(pref: str = "auto"):
    global _engine, _name
    with _lock:
        if _engine is not None and (pref in ("auto", _name)):
            return _name, _engine
        if pref in ("auto", "rapidocr"):
            try:
                from rapidocr_onnxruntime import RapidOCR
                _engine, _name = RapidOCR(), "rapidocr"
                return _name, _engine
            except Exception:
                if pref == "rapidocr":
                    return None, None
        if pref in ("auto", "tesseract"):
            try:
                import pytesseract
                exe = shutil.which("tesseract") or r"C:\Program Files\Tesseract-OCR\tesseract.exe"
                pytesseract.pytesseract.tesseract_cmd = exe
                pytesseract.get_tesseract_version()
                _engine, _name = pytesseract, "tesseract"
                return _name, _engine
            except Exception:
                pass
        return None, None


def read_text(img: np.ndarray, pref: str = "auto") -> str:
    name, eng = engine(pref)
    if eng is None or img is None or img.size == 0:
        return ""
    try:
        if name == "rapidocr":
            res, _ = eng(img)
            return " ".join(str(r[1]) for r in (res or []) if r and float(r[2]) > 0.5)
        return eng.image_to_string(img)
    except Exception:
        return ""


def crop(img: np.ndarray, region: list[float]) -> np.ndarray:
    h, w = img.shape[:2]
    x0, y0 = int(region[0] * w), int(region[1] * h)
    x1, y1 = int((region[0] + region[2]) * w), int((region[1] + region[3]) * h)
    return img[max(0, y0):min(h, y1), max(0, x0):min(w, x1)]


def match_phrases(text: str, phrases: dict[str, list[str]]) -> list[str]:
    t = " " + re.sub(r"[^a-z0-9+ ]", " ", text.lower()) + " "
    t = re.sub(r"\s+", " ", t)
    hits = []
    for label, words in phrases.items():
        for p in words:
            p2 = " " + p.lower().strip() + " " if len(p.strip()) <= 5 else p.lower().strip()
            if p2 and p2 in t:
                hits.append(label)
                break
    return hits


def scan(src: str, times: list[float], regions: dict[str, list[float]], phrases: dict[str, list[str]],
         pref: str = "auto", speed: float = 1.0, progress=None) -> dict[float, dict]:
    """OCR the given ORIGINAL-video times. Returns {t: {"text":..., "hits":[...]}}"""
    from .media import grab_frame
    out: dict[float, dict] = {}
    name, eng = engine(pref)
    if eng is None:
        return out
    for i, t in enumerate(times):
        img = grab_frame(src, t / speed, width=1280)
        if img is None:
            continue
        texts = []
        for rname, reg in regions.items():
            texts.append(read_text(crop(img, reg), pref))
        txt = " ".join(x for x in texts if x)
        hits = match_phrases(txt, phrases)
        # wanted stars: count star characters in the top-right HUD area
        stars = 0
        if "top_right" in regions:
            tr = texts[list(regions).index("top_right")]
            stars = min(6, tr.count("*") + tr.count("\u2605") + tr.count("\u2606"))
        out[t] = {"text": txt, "hits": hits, "stars": stars}
        if progress:
            progress((i + 1) / max(1, len(times)))
    # wanted level going up = an event
    prev = 0
    for t in sorted(out):
        st = out[t].get("stars", 0)
        if st > prev and "wanted" not in out[t]["hits"]:
            out[t]["hits"].append("wanted")
        prev = st
    return out

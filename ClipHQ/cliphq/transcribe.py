"""Speech to text with faster-whisper, word-level timestamps, in chunks."""
from __future__ import annotations

import os
import threading
from typing import Callable

import numpy as np

from .config import MODELS_DIR, pick_whisper_model

_models: dict = {}
_mlock = threading.Lock()
_force_cpu = False


def has_gpu() -> bool:
    if _force_cpu:
        return False
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def get_model(name: str, threads: int = 0):
    from faster_whisper import WhisperModel
    with _mlock:
        if name not in _models:
            _models.clear()  # keep only one model in memory (16 GB laptop)
            model = None
            if has_gpu():  # e.g. Google Colab's free graphics card: much faster
                try:
                    model = WhisperModel(name, device="cuda", compute_type="float16", download_root=str(MODELS_DIR))
                except Exception:
                    model = None
            if model is None:
                model = WhisperModel(name, device="cpu", compute_type="int8",
                                     cpu_threads=threads or (os.cpu_count() or 4),
                                     download_root=str(MODELS_DIR))
            _models[name] = model
        return _models[name]


def transcribe(audio: np.ndarray, *args, **kwargs) -> dict:
    """Transcribe, falling back to the normal processor if the graphics card fails."""
    global _force_cpu
    try:
        return _transcribe(audio, *args, **kwargs)
    except Exception as e:
        msg = str(e).lower()
        if has_gpu() and any(k in msg for k in ("cuda", "cudnn", "cublas", "gpu")):
            _force_cpu = True
            with _mlock:
                _models.clear()
            return _transcribe(audio, *args, **kwargs)
        raise


def _transcribe(audio: np.ndarray, sr: int = 16000, model_name: str = "auto", chunk_minutes: int = 10,
               keep: list[tuple[float, float]] | None = None, threads: int = 0,
               progress: Callable[[float], None] | None = None, duration_hint: float = 0) -> dict:
    """Returns {"words": [{"w","s","e","p"}], "segments": [{"s","e","text"}], "model": name}.

    keep: optional list of (start, end) ranges to transcribe. Everything else is skipped
    (used by the fast GTA skim to skip long stretches of quiet driving).
    """
    name = pick_whisper_model(model_name)
    if model_name == "auto" and has_gpu():
        name = "small.en"  # a graphics card makes the more accurate model fast too
    elif model_name == "auto" and duration_hint > 90 * 60 and name == "small.en":
        name = "base.en"  # very long streams: favour speed
    model = get_model(name, threads)
    total = len(audio) / sr
    ranges = keep if keep else [(0.0, total)]
    # split ranges into chunks
    chunks: list[tuple[float, float]] = []
    step = chunk_minutes * 60
    for a, b in ranges:
        t = a
        while t < b - 0.5:
            chunks.append((t, min(b, t + step)))
            t += step
    todo = sum(b - a for a, b in chunks) or 1
    done = 0.0
    words: list[dict] = []
    segments: list[dict] = []
    for a, b in chunks:
        # small overlap so words at the boundary are not lost
        pa = max(0.0, a - 1.0)
        piece = audio[int(pa * sr): int(b * sr)]
        segs, _ = model.transcribe(piece, language="en", word_timestamps=True, vad_filter=True,
                                   vad_parameters={"min_silence_duration_ms": 400},
                                   beam_size=1, condition_on_previous_text=False)
        for s in segs:
            s_start, s_end = s.start + pa, s.end + pa
            if s_end <= a:  # belongs to previous chunk
                continue
            ws = []
            for w in s.words or []:
                ws_ = w.start + pa
                if ws_ < a - 0.05 and a > 0:
                    continue
                ws.append({"w": w.word.strip(), "s": round(ws_, 3), "e": round(w.end + pa, 3),
                           "p": round(float(w.probability), 3)})
            ws = [x for x in ws if x["w"]]
            if not ws:
                continue
            words.extend(ws)
            segments.append({"s": round(ws[0]["s"], 3), "e": round(ws[-1]["e"], 3),
                             "text": " ".join(x["w"] for x in ws)})
            if progress:
                progress(min(0.999, (done + min(s_end - a, b - a)) / todo))
        done += b - a
        if progress:
            progress(min(1.0, done / todo))
    words.sort(key=lambda x: x["s"])
    # remove duplicates created by the chunk overlap
    clean: list[dict] = []
    for w in words:
        if clean and abs(w["s"] - clean[-1]["s"]) < 0.05 and w["w"].lower() == clean[-1]["w"].lower():
            continue
        clean.append(w)
    return {"words": clean, "segments": segments, "model": name}

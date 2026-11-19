"""Audio and video signals, one value per second of the ORIGINAL video.

Audio (all numpy, no heavy libraries):
  loud        loudness in dB (max over the second)
  loud_spike  how much louder than the last minute (screams, hype, laughter)
  onset       sharp new sounds
  impact      explosions / crashes: big sudden jump with lots of bass
  gunfire     several sharp bangs in a row
  siren       a strong single tone sweeping up and down (police sirens)
  music_change  the music / sound mood changing suddenly
Video:
  motion      how much the picture is changing
  scene_cut   hard cuts / big jumps
  shake       camera shake (picture jolting back and forth)
  hud_change  the wanted-level area of the HUD changing
"""
from __future__ import annotations

from typing import Callable

import numpy as np

SR = 16000
HOP = 1600          # 0.1 s
WIN = 2048


def _rolling_median(x: np.ndarray, w: int) -> np.ndarray:
    if len(x) == 0:
        return x
    # cheap rolling median using block medians (fast enough for 10k+ seconds)
    out = np.empty_like(x)
    half = w // 2
    step = max(1, w // 6)
    centers = np.arange(0, len(x), step)
    meds = np.array([np.median(x[max(0, c - half): c + half + 1]) for c in centers])
    out[:] = np.interp(np.arange(len(x)), centers, meds)
    return out


def _rolling_pct(x: np.ndarray, w: int, pct: float) -> np.ndarray:
    if len(x) == 0:
        return x
    half = w // 2
    step = max(1, w // 6)
    centers = np.arange(0, len(x), step)
    vals = np.array([np.percentile(x[max(0, c - w): c + 1], pct) for c in centers])
    return np.interp(np.arange(len(x)), centers, vals).astype(np.float32)


def audio_features(audio: np.ndarray, progress: Callable[[float], None] | None = None) -> dict:
    n_frames = max(0, (len(audio) - WIN) // HOP + 1)
    secs = int(np.ceil(len(audio) / SR))
    freqs = np.fft.rfftfreq(WIN, 1 / SR)
    low = (freqs >= 20) & (freqs < 250)
    mid = (freqs >= 250) & (freqs < 2000)
    high = (freqs >= 2000) & (freqs < 7500)
    siren_band = (freqs >= 450) & (freqs < 1900)
    window = np.hanning(WIN).astype(np.float32)

    db = np.full(n_frames, -90.0, np.float32)
    flux = np.zeros(n_frames, np.float32)
    lowr = np.zeros(n_frames, np.float32)
    highr = np.zeros(n_frames, np.float32)
    peaky = np.zeros(n_frames, np.float32)
    peakf = np.zeros(n_frames, np.float32)
    centroid = np.zeros(n_frames, np.float32)
    lowdb = np.full(n_frames, -90.0, np.float32)
    flat = np.zeros(n_frames, np.float32)
    flat_band = (freqs >= 250) & (freqs < 4000)
    bands12 = np.zeros((n_frames, 12), np.float32)
    edges = np.geomspace(60, 7500, 13)
    band_idx = [(freqs >= edges[i]) & (freqs < edges[i + 1]) for i in range(12)]

    prev = None
    block = 4000
    for b0 in range(0, n_frames, block):
        b1 = min(n_frames, b0 + block)
        idx = np.arange(b0, b1)[:, None] * HOP + np.arange(WIN)[None, :]
        fr = audio[idx] * window
        rms = np.sqrt(np.mean(fr ** 2, axis=1) + 1e-12)
        db[b0:b1] = 20 * np.log10(rms + 1e-9)
        mag = np.abs(np.fft.rfft(fr, axis=1)).astype(np.float32)
        tot = mag.sum(axis=1) + 1e-9
        lowr[b0:b1] = mag[:, low].sum(axis=1) / tot
        highr[b0:b1] = mag[:, high].sum(axis=1) / tot
        centroid[b0:b1] = (mag * freqs).sum(axis=1) / tot
        lowdb[b0:b1] = 20 * np.log10(mag[:, low].sum(axis=1) / WIN + 1e-9)
        fb = mag[:, flat_band] + 1e-9
        flat[b0:b1] = np.exp(np.mean(np.log(fb), axis=1)) / np.mean(fb, axis=1)
        sb = mag[:, siren_band]
        peaky[b0:b1] = sb.max(axis=1) / (sb.mean(axis=1) + 1e-9)
        peakf[b0:b1] = freqs[siren_band][sb.argmax(axis=1)]
        for i, m in enumerate(band_idx):
            bands12[b0:b1, i] = np.log1p(mag[:, m].mean(axis=1))
        lm = np.log1p(mag)
        d = np.empty(b1 - b0, np.float32)
        p = prev if prev is not None else lm[0]
        d[0] = np.maximum(lm[0] - p, 0).mean()
        d[1:] = np.maximum(lm[1:] - lm[:-1], 0).mean(axis=1)
        flux[b0:b1] = d
        prev = lm[-1]
        if progress:
            progress(b1 / max(1, n_frames))

    def per_sec(x, fn=np.max):
        out = np.zeros(secs, np.float32)
        for s in range(secs):
            seg = x[s * 10:(s + 1) * 10]
            if len(seg):
                out[s] = fn(seg)
        return out

    loud = per_sec(db)
    loud[loud < -80] = -80
    # "Spike" = louder than this person's normal talking level over the last minute.
    # The baseline is the 70th percentile of the loud parts, so silence doesn't make
    # every sentence look like a scream.
    floor = float(np.percentile(loud, 40)) if secs else -60
    base = np.maximum(_rolling_pct(loud, 60, 70), floor)
    # the first minute has no history: compare with the whole first minute instead
    if secs > 5:
        base[:30] = np.maximum(base[:30], np.percentile(loud[:60], 70))
    loud_spike = np.clip(loud - base, 0, 20)

    flux_n = flux / (np.median(flux) + 1e-6)
    onset = per_sec(flux_n)

    # impact (explosion / crash): a sudden jump in loudness AND in bass, noisy (not a voice),
    # and it STAYS loud for half a second (a word starting jumps too, but is tonal and short)
    def jump_of(x):
        j = np.zeros(n_frames, np.float32)
        if n_frames > 3:
            j[3:] = x[3:] - np.minimum(np.minimum(x[:-3], x[1:-2]), x[2:-1])
        return j
    jump = jump_of(db)
    ljump = jump_of(lowdb)
    sustain = np.zeros(n_frames, np.float32)
    for k in range(1, 6):
        sh = np.full(n_frames, -90.0, np.float32)
        sh[:-k] = db[k:]
        sustain += (sh > db - 9).astype(np.float32)
    sustain /= 5
    flat_med = float(np.median(flat)) + 1e-6
    noisy = np.clip(flat / flat_med - 1.0, 0, 2)
    imp_f = (np.clip((jump - 6) / 10, 0, 1.5) * np.clip((ljump - 6) / 10, 0, 1.5)
             * np.clip(sustain - 0.3, 0, 1) * (0.3 + noisy))
    impact = per_sec(imp_f)

    # gunfire: several sharp, bright bangs per second (local peaks in the onset curve)
    is_peak = np.zeros(n_frames, bool)
    if n_frames > 2:
        is_peak[1:-1] = (flux_n[1:-1] > flux_n[:-2]) & (flux_n[1:-1] >= flux_n[2:]) & (flux_n[1:-1] > 3)
    bright = highr > np.median(highr)
    gun_count = per_sec((is_peak & bright).astype(np.float32), np.sum)
    gun2 = np.convolve(gun_count, [1, 1], mode="same")  # bangs across 2 s
    gunfire = np.clip((gun2 - 3) / 4, 0, 1)

    # siren: tonal (peaky) and the tone keeps sweeping up and down over ~2 s
    tonal = peaky > 9
    siren = np.zeros(secs, np.float32)
    for s in range(secs):
        a, b = max(0, s * 10 - 10), min(n_frames, s * 10 + 10)
        if b - a < 8:
            continue
        t = tonal[a:b]
        if t.mean() < 0.6:
            continue
        pf = peakf[a:b][t]
        if len(pf) < 6:
            continue
        span = pf.max() - pf.min()
        direction_changes = np.sum(np.diff(np.sign(np.diff(pf))) != 0)
        if span > 150 and direction_changes <= len(pf) * 0.5:
            siren[s] = min(1.0, span / 600) * t.mean()

    # music / mood change: compare the sound "colour" of the 6 s before and after
    music_change = np.zeros(secs, np.float32)
    b12 = np.array([bands12[s * 10:(s + 1) * 10].mean(axis=0) if s * 10 < n_frames else np.zeros(12) for s in range(secs)])
    for s in range(6, secs - 6):
        a = b12[s - 6:s].mean(axis=0)
        b = b12[s:s + 6].mean(axis=0)
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        if na > 0 and nb > 0:
            music_change[s] = 1 - float(a @ b / (na * nb))
    if secs:
        music_change = np.clip(music_change / (np.percentile(music_change, 98) + 1e-6), 0, 1.5)

    return {"loud": loud, "loud_spike": loud_spike, "onset": onset, "impact": impact,
            "gunfire": gunfire, "siren": siren, "music_change": music_change,
            "centroid": per_sec(centroid, np.mean)}


def video_features(src: str, duration: float, speed: float = 1.0, fps: float = 3.0,
                   wanted_region: list | None = None,
                   progress: Callable[[float], None] | None = None) -> dict:
    """Motion, cuts, shake. Times are in the ORIGINAL video (multiplied by speed for scout mode)."""
    import cv2
    from .media import frames
    W, H = 160, 90
    secs = int(np.ceil(duration * speed)) + 1
    motion = np.zeros(secs, np.float32)
    cut = np.zeros(secs, np.float32)
    shake = np.zeros(secs, np.float32)
    hud = np.zeros(secs, np.float32)
    shifts: list[tuple[float, float, float]] = []
    prev = None
    prev_hist = None
    wr = wanted_region
    total = max(1, int(duration * fps))
    for i, f in enumerate(frames(src, fps, W, H, gray=True)):
        t = i / fps * speed
        s = min(secs - 1, int(t))
        g = f.astype(np.float32)
        hist = cv2.calcHist([f], [0], None, [32], [0, 256])
        cv2.normalize(hist, hist)
        if prev is not None:
            d = float(np.mean(np.abs(g - prev)))
            motion[s] = max(motion[s], d)
            corr = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
            if corr < 0.55 and d > 25:
                cut[s] = max(cut[s], 1.0)
            (dx, dy), resp = cv2.phaseCorrelate(prev, g)
            shifts.append((t, dx, dy))
            if wr:
                x0, y0 = int(wr[0] * W), int(wr[1] * H)
                x1, y1 = max(x0 + 2, int((wr[0] + wr[2]) * W)), max(y0 + 2, int((wr[1] + wr[3]) * H))
                hud[s] = max(hud[s], float(np.mean(np.abs(g[y0:y1, x0:x1] - prev[y0:y1, x0:x1]))))
        prev = g
        prev_hist = hist
        if progress and i % 30 == 0:
            progress(min(1.0, i / total))
    # shake = quick back-and-forth shifts (direction flips) within a second
    if shifts:
        arr = np.array(shifts)
        for s in range(secs):
            m = (arr[:, 0] >= s - 0.5) & (arr[:, 0] < s + 1.5)
            if m.sum() < 3:
                continue
            dx, dy = arr[m, 1], arr[m, 2]
            mag = np.hypot(dx, dy)
            flips = np.sum(np.diff(np.sign(dx)) != 0) + np.sum(np.diff(np.sign(dy)) != 0)
            shake[s] = float(np.clip(np.mean(mag) / 4, 0, 1) * np.clip(flips / 4, 0, 1))
    if progress:
        progress(1.0)
    return {"motion": motion, "scene_cut": cut, "shake": shake, "hud_change": hud}

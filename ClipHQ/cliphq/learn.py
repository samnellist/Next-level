"""Learning from your examples.

Mark a few great moments (or just approve clips) and Clip HQ looks at what those
moments had in common: which signals were high (sirens? explosions? screaming?) and
which on-screen words appeared. It then boosts those signals and adds those words to
the OCR phrase list for future videos.
"""
from __future__ import annotations

import json
import re
import time
from collections import Counter

import numpy as np

from . import db
from .config import load_settings, set_value

SIGNALS = ["loud_spike", "onset", "impact", "gunfire", "siren", "music_change", "motion", "scene_cut", "shake", "hud_change"]


def _features_at(cache: dict, t: float) -> dict:
    out = {}
    for grp in ("audio", "video"):
        for k, arr in (cache.get(grp) or {}).items():
            if k not in SIGNALS:
                continue
            arr = np.asarray(arr, np.float32)
            if len(arr) == 0:
                continue
            a, b = max(0, int(t) - 3), min(len(arr), int(t) + 4)
            hi = float(np.percentile(arr, 95)) or 1.0
            out[k] = float(arr[a:b].max() / hi) if b > a else 0.0
    return out


def add_example(video_id: int, t: float, label: str = "good") -> int:
    from .pipeline import load_cache
    from . import ocr, media
    cache = load_cache(video_id)
    feats = _features_at(cache, t) if cache else {}
    text = ""
    v = db.one("SELECT path, options FROM videos WHERE id=?", (video_id,))
    if v:
        opts = db.loads(v["options"], {})
        speed = float(opts.get("speed", 2.0 if opts.get("scout") else 1.0) or 1.0)
        try:
            for dt in (0, 1.5):
                img = media.grab_frame(v["path"], (t + dt) / speed, width=1280)
                if img is not None:
                    text += " " + ocr.read_text(img, load_settings()["gta"].get("ocr_engine", "auto"))
        except Exception:
            pass
    eid = db.run("INSERT INTO examples(video_id,t,label,features,ocr,created) VALUES (?,?,?,?,?,?)",
                 (video_id, t, label, json.dumps(feats), text.strip()[:500], time.time()))
    relearn()
    return eid


def relearn() -> dict:
    ex = db.q("SELECT * FROM examples ORDER BY id DESC LIMIT 200")
    if not ex:
        return {}
    acc: dict[str, list[float]] = {}
    for e in ex:
        for k, v in db.loads(e["features"], {}).items():
            acc.setdefault(k, []).append(v)
    weights = {}
    for k, vals in acc.items():
        if len(vals) < 2:
            continue
        m = float(np.mean(vals))  # ~1.0 means "as high as this signal's top 5%"
        weights[k] = round(float(np.clip(0.6 + 0.8 * m, 0.6, 2.2)), 3)
    set_value(["gta", "weights"], weights)
    return weights


def learned_phrases() -> list[str]:
    ex = db.q("SELECT ocr FROM examples WHERE ocr != ''")
    if len(ex) < 2:
        return []
    cnt: Counter = Counter()
    for e in ex:
        toks = set(t for t in re.findall(r"[a-z]{4,}", e["ocr"].lower()))
        cnt.update(toks)
    return [w for w, n in cnt.most_common(15) if n >= 2]

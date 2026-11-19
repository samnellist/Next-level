"""The full job: video in -> scored moments -> rendered clips. One job at a time (it's CPU heavy)."""
from __future__ import annotations

import json
import random
import shutil
import threading
import time
import traceback
from pathlib import Path

import numpy as np

from . import campaigns, captions, db, framing, learn, media, moments, ocr, signals, smart, transcribe
from .config import APPROVED_DIR, CLIPS_DIR, PRESETS, WORK_DIR, load_settings
from .notify import notify


class Cancelled(Exception):
    pass


STAGES = [  # name, share of the progress bar
    ("Reading audio", 0.03), ("Listening for loud moments", 0.04), ("Watching for action", 0.12),
    ("Transcribing", 0.45), ("Reading on-screen text", 0.10), ("Finding moments", 0.04),
    ("Choosing layout", 0.04), ("Making clips", 0.18),
]


class Progress:
    def __init__(self, vid: int) -> None:
        self.vid = vid
        self.done = 0.0
        self.cur = None
        self.last_write = 0.0

    def stage(self, name: str) -> None:
        if self.cur:
            self.done += dict(STAGES)[self.cur]
        self.cur = name
        self.set(0.0, force=True)

    def set(self, frac: float, force: bool = False) -> None:
        v = db.one("SELECT status FROM videos WHERE id=?", (self.vid,))
        if v and v["status"] == "cancelled":
            raise Cancelled()
        now = time.time()
        if not force and now - self.last_write < 0.7:
            return
        self.last_write = now
        share = dict(STAGES).get(self.cur, 0)
        total = min(0.999, self.done + share * max(0.0, min(1.0, frac)))
        label = f"{self.cur} {int(frac * 100)}%" if frac > 0 else f"{self.cur}..."
        db.update("videos", self.vid, stage=label, progress=round(total, 4))


def _cache_path(vid: int) -> Path:
    return WORK_DIR / f"video_{vid}.json"


def save_cache(vid: int, data: dict) -> None:
    def conv(o):
        if isinstance(o, np.ndarray):
            return [round(float(x), 4) for x in o]
        if isinstance(o, (np.floating,)):
            return float(o)
        raise TypeError(type(o))
    _cache_path(vid).write_text(json.dumps(data, default=conv), "utf-8")


def load_cache(vid: int) -> dict:
    p = _cache_path(vid)
    if not p.exists():
        return {}
    d = json.loads(p.read_text("utf-8"))
    for grp in ("audio", "video"):
        if d.get(grp):
            d[grp] = {k: np.array(v, np.float32) for k, v in d[grp].items()}
    return d


def process_video(vid: int) -> None:
    v = db.one("SELECT * FROM videos WHERE id=?", (vid,))
    if not v:
        return
    opts = db.loads(v["options"], {})
    st = load_settings()
    src = v["path"]
    preset = opts.get("preset", "gta6")
    gta = PRESETS.get(preset, {}).get("gta", False)
    scout = bool(opts.get("scout"))
    speed = float(opts.get("speed", 2.0 if scout else 1.0) or 1.0)
    min_len = float(opts.get("min_clip", st["min_clip"]))
    max_len = float(opts.get("max_clip", st["max_clip"]))
    max_clips = int(opts.get("max_clips", st["max_clips"]))
    gs = st["gta"]
    pr = Progress(vid)
    db.update("videos", vid, status="working", error="", progress=0)

    if not Path(src).exists():
        raise RuntimeError(f"File not found: {src}")
    info = media.probe(src)
    if not info["has_audio"] and not info["has_video"]:
        raise RuntimeError("This file has no audio or video.")
    duration = info["duration"] * speed  # in ORIGINAL time
    db.update("videos", vid, info=dict(info, original_duration=duration))

    pr.stage("Reading audio")
    wav = WORK_DIR / f"video_{vid}.wav"
    if info["has_audio"]:
        media.extract_audio(src, wav, speed=speed)
        audio = media.read_wav(wav)
    else:
        audio = np.zeros(int(duration * 16000), np.float32)
    pr.set(1)

    pr.stage("Listening for loud moments")
    af = signals.audio_features(audio, progress=pr.set)

    pr.stage("Watching for action")
    vf = None
    if info["has_video"]:
        fps = 2.0 if duration > 3600 else 3.0
        vf = signals.video_features(src, info["duration"], speed=speed, fps=fps,
                                    wanted_region=gs["wanted_region"] if gta else None, progress=pr.set)

    pr.stage("Transcribing")
    keep = moments.keep_ranges(duration, af, vf) if (gta and gs.get("skip_quiet", True)) else None
    if keep:
        skipped = duration - sum(b - a for a, b in keep)
        db.event("info", f"Skipping {int(skipped // 60)} min of quiet driving in {v['name']}")
    tx = transcribe.transcribe(audio, model_name=st["whisper_model"], chunk_minutes=int(st["chunk_minutes"]),
                               keep=keep, threads=int(st["whisper_threads"]), progress=pr.set, duration_hint=duration)
    words = tx["words"]
    del audio

    pr.stage("Reading on-screen text")
    ocr_hits: dict = {}
    if gta and info["has_video"] and gs.get("ocr_engine", "auto") != "off":
        prelim, _ = moments.find_moments(duration, af, vf, words, None, gta, min_len, max_len, max_clips * 2)
        times = set()
        for m in prelim:
            for dt in (-2, 0, 2, 4):
                times.add(round(max(0, min(duration - 0.5, m.peak + dt))))
        sweep = 10 if duration < 3600 else 20
        times.update(range(0, int(duration), sweep))
        times = sorted(times)[:900]
        phrases = dict(gs["ocr_phrases"])
        learned_p = learn.learned_phrases()
        if learned_p:
            phrases["learned"] = learned_p
        ocr_hits = ocr.scan(src, [float(t) for t in times], gs["ocr_regions"], phrases, gs.get("ocr_engine", "auto"),
                            speed=speed, progress=pr.set)
        if not ocr.engine(gs.get("ocr_engine", "auto"))[1]:
            db.event("warn", "On-screen text reading (OCR) is not available - skipped")

    pr.stage("Finding moments")
    learned = gs.get("weights") or {}
    found, total_curve = moments.find_moments(duration, af, vf, words, ocr_hits, gta, min_len, max_len,
                                              max_clips + 4 if st.get("claude_api_key") else max_clips,
                                              learned=learned, seed=vid)
    found = [m for m in found if m.score >= 12] or found[:3]
    campaign = campaigns.get(opts.get("campaign_id"))
    ai_titles: dict = {}
    if st.get("claude_api_key") and st.get("use_claude", True):
        found, extra = smart.rerank(found, st["claude_api_key"], st.get("claude_model"), gta, campaign, k=max_clips)
        ai_titles = extra.get("titles", {})
        if extra.get("error"):
            db.event("warn", f"Smart mode (Claude) failed, using built-in picks: {extra['error']}")
    found = found[:max_clips]
    save_cache(vid, {"audio": af, "video": vf, "words": words, "ocr": {str(k): v for k, v in ocr_hits.items()},
                     "duration": duration, "gta": gta, "total": total_curve})

    if scout:
        scout_list = [{"start": m.start, "end": m.end, "from": moments.fmt_time(m.start), "to": moments.fmt_time(m.end),
                       "score": m.score, "kind": m.kind, "reason": m.reason, "hook": m.hook,
                       "text": " ".join(w["w"] for w in m.words)[:200]} for m in sorted(found, key=lambda m: m.start)]
        db.update("videos", vid, scout=scout_list, status="done", stage="Scout list ready", progress=1.0, finished=time.time())
        notify("Scout list ready", f"{len(scout_list)} moments found in {v['name']}", "clips")
        return

    pr.stage("Choosing layout")
    face_info = {"facecam": None}
    layout = opts.get("layout", "auto")
    facecam = opts.get("facecam")
    if info["has_video"]:
        sample_t = [info["duration"] * f for f in (0.08, 0.2, 0.33, 0.45, 0.57, 0.7, 0.82, 0.94)]
        face_info = framing.analyse_faces(src, sample_t)
        if not facecam:
            facecam = face_info.get("facecam")
        if layout == "auto" or (layout == "stacked" and not facecam):
            layout = framing.choose_layout(dict(face_info, facecam=facecam), preset, gta)
    pr.set(1)
    db.update("videos", vid, info=dict(info, original_duration=duration, face=face_info, facecam=facecam, layout=layout))

    rng = random.Random(vid * 7919)
    blur = list(st.get("clutter_regions") or []) if st.get("hide_clutter") == "blur" else []
    if gta and gs.get("hide_hud"):
        blur += gs["hud_regions"]
    clip_ids = []
    for m in found:
        style = st["caption_style"]
        if style == "random" or st.get("randomise_style"):
            style = captions.random_style(st["caption_styles_enabled"], rng)
        text = " ".join(w["w"] for w in m.words)
        title = campaigns.make_title(m.hook, m.kind, campaign, ai_titles.get(id(m), ""))
        desc = campaigns.make_description(m.hook, text, campaign, gta)
        near = [w for w in words if m.start - 15 <= w["s"] <= m.end + 15]
        edits = {"facecam": facecam, "blur": blur, "hook_style": rng.randrange(len(captions.HOOK_STYLES)),
                 "captions_on": True, "extra_texts": [], "checklist": campaigns.checklist(campaign),
                 "checked": [], "campaign_id": opts.get("campaign_id"), "peak": m.peak, "gta": gta}
        cid = db.run("""INSERT INTO clips(video_id,start,"end",score,reason,kind,hook,title,description,layout,style,edits,words,status,created)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (vid, m.start, m.end, m.score, m.reason, m.kind, m.hook, title, desc, layout, style,
                      json.dumps(edits), json.dumps(near), "new", time.time()))
        clip_ids.append(cid)

    pr.stage("Making clips")
    for i, cid in enumerate(clip_ids):
        render_one(cid, sub=lambda f, i=i: pr.set((i + f) / max(1, len(clip_ids))))
    db.update("videos", vid, status="done", stage=f"Done - {len(clip_ids)} clips", progress=1.0, finished=time.time())
    best = max((m.score for m in found), default=0)
    if clip_ids:
        notify("New clips ready", f"{len(clip_ids)} clips from {v['name']} (best score {best})", "clips")
    else:
        db.event("info", f"No strong moments in {v['name']}")


def render_one(cid: int, sub=None) -> None:
    from .render import render_clip
    c = db.one("SELECT * FROM clips WHERE id=?", (cid,))
    if not c or c["status"] == "deleted":
        return
    v = db.one("SELECT * FROM videos WHERE id=?", (c["video_id"],))
    ed = db.loads(c["edits"], {})
    st = load_settings()
    db.update("clips", cid, status="rendering", render_error="")
    out = CLIPS_DIR / f"clip_{cid:05d}_v{int(time.time()) % 100000}.mp4"
    try:
        res = render_clip(v["path"], out, float(c["start"]), float(c["end"]), c["layout"], db.loads(c["words"], []),
                          c["hook"] or "", c["style"], facecam=ed.get("facecam"), extra_texts=ed.get("extra_texts"),
                          blur_regions=ed.get("blur"), hook_seconds=float(st.get("hook_seconds", 3.5)),
                          preset=st.get("render_preset", "veryfast"), captions_on=ed.get("captions_on", True),
                          hook_style=int(ed.get("hook_style", 0)), caption_y=ed.get("caption_y"), progress=sub)
        old = c.get("file")
        db.update("clips", cid, file=Path(res["file"]).name, thumb=Path(res["thumb"]).name, status="ready",
                  layout=res["layout"])
        for o in (old, (old or "").replace(".mp4", ".jpg")):
            if o and o != Path(res["file"]).name and (CLIPS_DIR / o).exists():
                try:
                    (CLIPS_DIR / o).unlink()
                except OSError:
                    pass
    except Exception as e:
        traceback.print_exc()
        db.update("clips", cid, status="error", render_error=str(e)[:500])


def approve(cid: int) -> dict:
    c = db.one("SELECT * FROM clips WHERE id=?", (cid,))
    if not c or not c["file"]:
        raise RuntimeError("Clip is not rendered yet")
    safe = "".join(ch for ch in (c["hook"] or "clip") if ch.isalnum() or ch in " -_").strip()[:40] or "clip"
    base = f"{cid:05d} - {safe}"
    shutil.copy2(CLIPS_DIR / c["file"], APPROVED_DIR / f"{base}.mp4")
    ed = db.loads(c["edits"], {})
    (APPROVED_DIR / f"{base}.txt").write_text(
        f"TITLE:\n{c['title']}\n\nDESCRIPTION:\n{c['description']}\n\nCHECKLIST:\n" +
        "\n".join(f"[ ] {x}" for x in ed.get("checklist", [])) + "\n", "utf-8")
    ed["approved_file"] = f"{base}.mp4"
    db.update("clips", cid, status="approved", edits=ed)
    try:
        learn.add_example(c["video_id"], float(ed.get("peak", (c["start"] + c["end"]) / 2)), "approved")
    except Exception:
        pass
    return {"file": f"{base}.mp4"}


# ---------------- worker ----------------

class Worker(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True, name="clip-worker")
        self.wake = threading.Event()
        self.current: dict | None = None

    def run(self) -> None:
        while True:
            try:
                did = self.step()
            except Exception:
                traceback.print_exc()
                did = False
            if not did:
                self.wake.wait(2)
                self.wake.clear()

    def step(self) -> bool:
        # 1) re-renders you asked for in Review come first (they're quick)
        c = db.one("SELECT id FROM clips WHERE status='queued' ORDER BY id LIMIT 1")
        if c:
            self.current = {"type": "render", "id": c["id"]}
            render_one(c["id"])
            self.current = None
            return True
        v = db.one("SELECT id, name FROM videos WHERE status='queued' ORDER BY id LIMIT 1")
        if not v:
            return False
        self.current = {"type": "video", "id": v["id"]}
        try:
            process_video(v["id"])
        except Cancelled:
            db.update("videos", v["id"], stage="Cancelled", status="cancelled")
        except Exception as e:
            traceback.print_exc()
            db.update("videos", v["id"], status="error", error=str(e)[:800], stage="Error")
            notify("Processing failed", f"{v['name']}: {str(e)[:120]}", "error")
        finally:
            self.current = None
        return True


worker = Worker()


def queue_video(path: str, options: dict) -> int:
    p = Path(path)
    vid = db.run("INSERT INTO videos(path,name,status,options,created) VALUES (?,?,?,?,?)",
                 (str(p), p.name, "queued", json.dumps(options), time.time()))
    worker.wake.set()
    return vid

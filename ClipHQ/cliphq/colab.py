"""Clip HQ for Google Colab: same clip engine, driven from notebook forms, files in Google Drive.

Drive layout (made for you):
  MyDrive/ClipHQ/input     put your videos here (from the iPhone Google Drive app or drive.google.com)
  MyDrive/ClipHQ/clips     finished clips, one folder per video, each with a .txt (title, description, checklist)
  MyDrive/ClipHQ/approved  clips you approve
  MyDrive/ClipHQ/state     Clip HQ's memory (settings, campaigns, what it has learned) - leave this alone
"""
from __future__ import annotations

import base64
import html
import json
import re
import shutil
import sqlite3
import threading
import time
from pathlib import Path

DRIVE: Path | None = None
LOCAL_IN = Path("/content/cliphq_videos")


def _drive(sub: str) -> Path:
    p = DRIVE / sub
    p.mkdir(parents=True, exist_ok=True)
    return p


def setup(drive_root: str = "/content/drive/MyDrive/ClipHQ") -> None:
    """Create the Drive folders and load Clip HQ's memory from Drive."""
    global DRIVE
    DRIVE = Path(drive_root)
    for sub in ("input", "clips", "approved", "state"):
        _drive(sub)
    from .config import DATA_DIR, SETTINGS_FILE, DB_FILE
    LOCAL_IN.mkdir(parents=True, exist_ok=True)
    st = DRIVE / "state"
    if (st / "cliphq.db").exists() and not DB_FILE.exists():
        shutil.copy2(st / "cliphq.db", DB_FILE)
    if (st / "settings.json").exists() and not SETTINGS_FILE.exists():
        shutil.copy2(st / "settings.json", SETTINGS_FILE)
    cache = st / "cache"
    if cache.is_dir():
        from .config import WORK_DIR
        for f in cache.glob("video_*.json"):
            if not (WORK_DIR / f.name).exists():
                shutil.copy2(f, WORK_DIR / f.name)
    from . import db
    db.init()
    from .transcribe import has_gpu
    print("Google Drive folders ready:", DRIVE)
    print("Graphics card (fast speech-to-text):", "YES" if has_gpu() else
          "no - it still works, just slower. (Runtime > Change runtime type > T4 GPU to get one)")
    vids = _video_files()
    print(f"Videos in your input folder: {len(vids)}" + (" -> " + ", ".join(v.name for v in vids[:8]) if vids else
          "  (put videos in MyDrive/ClipHQ/input)"))


def save_state() -> None:
    from . import db
    from .config import DB_FILE, SETTINGS_FILE
    try:
        db.conn().execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        pass
    st = _drive("state")
    tmp = st / "cliphq.db.tmp"
    src = sqlite3.connect(DB_FILE)
    dst = sqlite3.connect(tmp)
    src.backup(dst)
    dst.close(); src.close()
    tmp.replace(st / "cliphq.db")
    if SETTINGS_FILE.exists():
        shutil.copy2(SETTINGS_FILE, st / "settings.json")
    # each video's analysis (used for trimming and for learning from your examples)
    from .config import WORK_DIR
    cache = st / "cache"
    cache.mkdir(exist_ok=True)
    for f in WORK_DIR.glob("video_*.json"):
        dst = cache / f.name
        if not dst.exists() or dst.stat().st_mtime < f.stat().st_mtime:
            shutil.copy2(f, dst)


VIDEO_EXT = {".mp4", ".mkv", ".mov", ".m4v", ".avi", ".webm", ".flv", ".ts", ".wmv", ".mpg", ".mpeg", ".3gp"}


def _video_files() -> list[Path]:
    return sorted([p for p in _drive("input").rglob("*") if p.is_file() and p.suffix.lower() in VIDEO_EXT],
                  key=lambda p: p.stat().st_mtime)


def _local_copy(drive_path: Path) -> Path:
    """Work on a copy on Colab's fast disk (reading straight from Drive is slow)."""
    dst = LOCAL_IN / drive_path.name
    if not dst.exists() or dst.stat().st_size != drive_path.stat().st_size:
        print(f"Copying {drive_path.name} from Drive ({drive_path.stat().st_size / 1e6:.0f} MB)...")
        shutil.copy2(drive_path, dst)
    return dst


def _ensure_source(video_id: int) -> str:
    from . import db
    v = db.one("SELECT path, options FROM videos WHERE id=?", (video_id,))
    p = Path(v["path"])
    if p.exists():
        return str(p)
    drive_src = db.loads(v["options"], {}).get("drive_path")
    if drive_src and Path(drive_src).exists():
        return str(_local_copy(Path(drive_src)))
    raise RuntimeError(f"The original video for this clip isn't in your Drive input folder any more: {p.name}")


def _safe(s: str, n: int = 50) -> str:
    s = re.sub(r"[^\w\- ]+", "", s or "").strip()
    return (s[:n] or "clip").strip()


def _campaign_id(name: str):
    from . import db
    if not name or not name.strip():
        return None
    r = db.one("SELECT id FROM campaigns WHERE lower(name)=lower(?)", (name.strip(),))
    if not r:
        print(f"(No campaign called '{name}' - making clips without one. Add it in the Campaigns step first.)")
        return None
    return r["id"]


def _run_with_progress(vid: int) -> None:
    from . import db, pipeline
    err: list = []

    def work():
        try:
            pipeline.process_video(vid)
        except Exception as e:  # noqa: BLE001
            err.append(e)
            db.update("videos", vid, status="error", error=str(e)[:800], stage="Error")
    t = threading.Thread(target=work, daemon=True)
    t.start()
    last = ""
    t0 = time.time()
    while t.is_alive():
        v = db.one("SELECT stage, progress FROM videos WHERE id=?", (vid,))
        line = f"  [{int((v['progress'] or 0) * 100):3d}%] {v['stage']}"
        if line != last:
            print(f"{line}   ({int(time.time() - t0)}s)")
            last = line
        t.join(3)
    if err:
        raise err[0]


def make_clips(video: str = "all new", preset: str = "gta6", campaign: str = "", layout: str = "auto",
               scout: bool = False, speed: float = 2.0, min_len: int = 10, max_len: int = 30, how_many: int = 12,
               claude_api_key: str = "") -> None:
    from . import db
    from .config import save_settings
    if claude_api_key.strip():
        save_settings({"claude_api_key": claude_api_key.strip()})
    files = _video_files()
    if not files:
        print("No videos found. Put a video in MyDrive/ClipHQ/input first.")
        return
    if video.strip().lower() in ("", "all new", "all"):
        done = {db.loads(r["options"], {}).get("drive_path") for r in db.q("SELECT options FROM videos WHERE status='done'")}
        todo = [f for f in files if str(f) not in done]
        if not todo:
            print("No new videos - everything in the input folder has already been done. "
                  "Type a video's name in the 'video' box to do it again.")
            return
    else:
        want = video.strip().lower()
        todo = [f for f in files if f.name.lower() == want] or [f for f in files if want in f.name.lower()]
        if not todo:
            print(f"Couldn't find '{video}'. Videos in your input folder:\n  " + "\n  ".join(f.name for f in files))
            return
        todo = todo[:1]
    from .pipeline import queue_video
    for f in todo:
        print(f"\n=== {f.name} ===")
        local = _local_copy(f)
        opts = {"preset": preset, "layout": layout, "scout": bool(scout), "speed": float(speed) if scout else 1.0,
                "min_clip": int(min_len), "max_clip": int(max_len), "max_clips": int(how_many),
                "campaign_id": _campaign_id(campaign), "drive_path": str(f), "source": "colab"}
        vid = db.run("INSERT INTO videos(path,name,status,options,created) VALUES (?,?,?,?,?)",
                     (str(local), f.name, "working", json.dumps(opts), time.time()))
        try:
            _run_with_progress(vid)
        except Exception as e:  # noqa: BLE001
            print(f"PROBLEM with {f.name}: {e}")
            save_state()
            continue
        v = db.one("SELECT * FROM videos WHERE id=?", (vid,))
        if v["status"] != "done":
            print(f"PROBLEM with {f.name}: {v['error'] or v['stage']}")
            continue
        if scout:
            _export_scout(vid)
        else:
            export_video(vid)
            show(vid)
        save_state()
    print("\nAll done. Your clips are in Google Drive: MyDrive/ClipHQ/clips")


def _export_scout(vid: int) -> None:
    from . import db
    v = db.one("SELECT * FROM videos WHERE id=?", (vid,))
    items = db.loads(v["scout"], [])
    lines = [f"Scout timestamps for {v['name']} (times in the ORIGINAL, normal-speed video)", ""]
    for m in items:
        lines.append(f"{m['from']} - {m['to']}   score {m['score']}   {m['kind']}: {m['reason']}")
        lines.append(f"      \"{m['text']}\"")
    txt = "\n".join(lines)
    out = _drive("clips") / f"{_safe(Path(v['name']).stem)} - scout timestamps.txt"
    out.write_text(txt, "utf-8")
    print("\n" + txt + f"\n\nSaved to Drive: {out}")


def _clip_name(c: dict, rank: int) -> str:
    return f"{rank:02d} - score {c['score']} - {_safe(c['hook'], 40)} (clip {c['id']})"


def _write_txt(c: dict, path: Path) -> None:
    from . import db
    ed = db.loads(c["edits"], {})
    path.write_text(f"TITLE:\n{c['title']}\n\nDESCRIPTION:\n{c['description']}\n\nWHY IT WAS PICKED:\n{c['reason']}\n\n"
                    f"CHECKLIST:\n" + "\n".join(f"[ ] {x}" for x in ed.get("checklist", [])) + "\n", "utf-8")


def export_video(vid: int) -> None:
    """Copy every finished clip of a video to Drive, named best-first, each with its text file."""
    from . import db
    from .config import CLIPS_DIR
    v = db.one("SELECT * FROM videos WHERE id=?", (vid,))
    folder = _drive("clips") / _safe(Path(v["name"]).stem, 60)
    folder.mkdir(parents=True, exist_ok=True)
    clips = db.q("SELECT * FROM clips WHERE video_id=? AND status IN ('ready','approved') ORDER BY score DESC", (vid,))
    for old in folder.glob("*"):
        if "(clip " in old.name:
            old.unlink()
    for rank, c in enumerate(clips, 1):
        if not c["file"]:
            continue
        name = _clip_name(c, rank)
        shutil.copy2(CLIPS_DIR / c["file"], folder / f"{name}.mp4")
        _write_txt(c, folder / f"{name}.txt")
    print(f"\nSaved {len(clips)} clips to Drive: {folder}")


def show(vid: int | None = None) -> None:
    """A table of the clips (best first) with a picture, score and reason."""
    from . import db
    from .config import CLIPS_DIR
    from .moments import fmt_time
    if vid is None:
        r = db.one("SELECT id FROM videos WHERE status='done' ORDER BY id DESC LIMIT 1")
        if not r:
            print("No clips yet.")
            return
        vid = r["id"]
    clips = db.q("SELECT * FROM clips WHERE video_id=? AND status != 'deleted' ORDER BY score DESC", (vid,))
    rows = []
    for c in clips:
        img = ""
        if c["thumb"] and (CLIPS_DIR / c["thumb"]).exists():
            b = base64.b64encode((CLIPS_DIR / c["thumb"]).read_bytes()).decode()
            img = f'<img src="data:image/jpeg;base64,{b}" style="width:110px;border-radius:8px">'
        status = "APPROVED" if c["status"] == "approved" else c["status"]
        rows.append(f"<tr><td>{img}</td><td style='font-size:22px;font-weight:800'>{c['score']}</td>"
                    f"<td><b>Clip {c['id']}</b> &middot; {fmt_time(c['start'])}&ndash;{fmt_time(c['end'])} "
                    f"({int(c['end'] - c['start'])}s) &middot; {html.escape(c['layout'])} &middot; {status}<br>"
                    f"<b>{html.escape(c['hook'] or '')}</b><br><span style='color:#888'>{html.escape(c['reason'] or '')}</span>"
                    f"<br><span style='color:#888'>Title: {html.escape(c['title'] or '')}</span></td></tr>")
    table = ("<table style='border-collapse:collapse'>" + "".join(rows) + "</table>"
             "<p>Watch them in Google Drive: MyDrive/ClipHQ/clips. Use the <b>clip number</b> in the Edit / Approve steps.</p>")
    try:
        from IPython.display import HTML, display
        display(HTML(table))
    except Exception:
        for c in clips:
            print(c["id"], c["score"], c["hook"], "|", c["reason"])


def preview(clip_number: int) -> None:
    """Play a clip right here in the notebook."""
    from . import db
    from .config import CLIPS_DIR
    c = db.one("SELECT file FROM clips WHERE id=?", (int(clip_number),))
    if not c or not c["file"]:
        print("That clip isn't ready.")
        return
    from IPython.display import HTML, display
    b = base64.b64encode((CLIPS_DIR / c["file"]).read_bytes()).decode()
    display(HTML(f'<video controls playsinline style="height:640px;border-radius:12px" '
                 f'src="data:video/mp4;base64,{b}"></video>'))


def edit_clip(clip_number: int, hook: str = "", start: float | None = None, end: float | None = None,
              layout: str = "keep", caption_style: str = "keep", extra_text: str = "", extra_text_at: float = 0,
              new_random_style: bool = False) -> None:
    """Change a clip and re-make it. Leave a box empty to keep it the same."""
    import random
    from . import campaigns, captions, db, pipeline
    c = db.one("SELECT * FROM clips WHERE id=?", (int(clip_number),))
    if not c:
        print(f"There's no clip {clip_number}.")
        return
    ed = db.loads(c["edits"], {})
    f: dict = {}
    if hook.strip():
        f["hook"] = hook.strip().upper()
        camp = campaigns.get(ed.get("campaign_id"))
        f["title"] = campaigns.make_title(f["hook"], c["kind"], camp)
        words = db.loads(c["words"], [])
        text = " ".join(w["w"] for w in words if c["start"] <= w["s"] <= c["end"])
        f["description"] = campaigns.make_description(f["hook"], text, camp, ed.get("gta", True))
    if start is not None or end is not None:
        s = float(start) if start is not None else c["start"]
        e = float(end) if end is not None else c["end"]
        if e - s < 3:
            print("A clip must be at least 3 seconds.")
            return
        f["start"], f["end"] = round(s, 2), round(e, 2)
        from .pipeline import load_cache
        cache = load_cache(c["video_id"])
        if cache.get("words"):
            f["words"] = [w for w in cache["words"] if s - 15 <= w["s"] <= e + 15]
    if layout and layout != "keep":
        f["layout"] = layout
    if new_random_style:
        f["style"] = random.choice([k for k in captions.STYLES if k != c["style"]])
        ed["hook_style"] = random.randrange(len(captions.HOOK_STYLES))
    elif caption_style and caption_style != "keep":
        f["style"] = caption_style
    if extra_text.strip():
        ed.setdefault("extra_texts", []).append({"text": extra_text.strip().upper(), "start": float(extra_text_at),
                                                 "end": float(extra_text_at) + 3})
    f["edits"] = ed
    db.update("clips", c["id"], **f)
    _ensure_source(c["video_id"])
    v = db.one("SELECT path FROM videos WHERE id=?", (c["video_id"],))
    if not Path(v["path"]).exists():
        db.run("UPDATE videos SET path=? WHERE id=?", (_ensure_source(c["video_id"]), c["video_id"]))
    print(f"Re-making clip {c['id']}...")
    pipeline.render_one(c["id"])
    c2 = db.one("SELECT * FROM clips WHERE id=?", (c["id"],))
    if c2["status"] != "ready" and c2["status"] != "approved":
        print("PROBLEM:", c2["render_error"])
        return
    export_video(c["video_id"])
    save_state()
    print(f"Done. Hook: {c2['hook']} | {c2['start']:.1f}s-{c2['end']:.1f}s | layout {c2['layout']} | style {c2['style']}")


def approve(clip_number: int) -> None:
    from . import db, pipeline
    from .config import APPROVED_DIR
    try:
        r = pipeline.approve(int(clip_number))
    except Exception as e:  # noqa: BLE001
        print("PROBLEM:", e)
        return
    for ext in (".mp4", ".txt"):
        src = APPROVED_DIR / r["file"].replace(".mp4", ext)
        if src.exists():
            shutil.copy2(src, _drive("approved") / src.name)
    c = db.one("SELECT title FROM clips WHERE id=?", (int(clip_number),))
    save_state()
    print(f"Approved! Saved to Drive: MyDrive/ClipHQ/approved/{r['file']}\nTitle: {c['title']}")


def add_campaign(name: str, hashtags: str = "", tags: str = "", pay_rate: str = "", rules: str = "",
                 main_focus: str = "") -> None:
    from . import db
    if not name.strip():
        print("Give the campaign a name.")
        return
    rules = rules.replace(" | ", "\n").replace(";", "\n")
    r = db.one("SELECT id FROM campaigns WHERE lower(name)=lower(?)", (name.strip(),))
    vals = (name.strip(), hashtags, tags, pay_rate, rules, main_focus)
    if r:
        db.run("UPDATE campaigns SET name=?,hashtags=?,tags=?,pay_rate=?,rules=?,focus=? WHERE id=?", (*vals, r["id"]))
        print(f"Updated campaign '{name}'.")
    else:
        db.run("INSERT INTO campaigns(name,hashtags,tags,pay_rate,rules,focus,created) VALUES (?,?,?,?,?,?,?)",
               (*vals, time.time()))
        print(f"Saved campaign '{name}'.")
    save_state()
    for c in db.q("SELECT * FROM campaigns ORDER BY name"):
        print(f"  - {c['name']}: {c['hashtags']}  {c['pay_rate']}")


def teach(video: str, at_time: str, label: str = "good") -> None:
    """Mark a great moment (e.g. 12:40) in a video you've processed, so it learns what to look for."""
    from . import db, learn
    rows = db.q("SELECT id, name FROM videos WHERE status='done' ORDER BY id DESC")
    want = video.strip().lower()
    v = next((r for r in rows if r["name"].lower() == want), None) or next((r for r in rows if want in r["name"].lower()), None)
    if not v:
        print("Couldn't find that video among the ones you've processed:\n  " + "\n  ".join(r["name"] for r in rows))
        return
    try:
        parts = [float(x) for x in at_time.strip().split(":")]
    except ValueError:
        print("Type the time like 12:40 or 1:02:15")
        return
    t = 0.0
    for x in parts:
        t = t * 60 + x
    _ensure_source(v["id"])
    learn.add_example(v["id"], t, label)
    from .config import load_settings
    save_state()
    print(f"Learned from {at_time} in {v['name']}.")
    print("Signal boosts now:", load_settings()["gta"].get("weights", {}))
    lp = learn.learned_phrases()
    if lp:
        print("On-screen words it has learned:", ", ".join(lp))


def channels(add: str = "", check: bool = True) -> None:
    from . import db, watcher
    if add.strip():
        try:
            r = watcher.add_channel(add.strip())
            print(f"Now watching {r['name']}.")
        except Exception as e:  # noqa: BLE001
            print("PROBLEM:", e)
    if check:
        n = watcher.check_all()
        print(f"Checked. {n} new upload(s) since last time.\n")
    ups = db.q("SELECT u.*, c.name channel FROM uploads u LEFT JOIN channels c ON c.channel_id=u.channel_id "
               "ORDER BY u.published DESC LIMIT 15")
    rows = []
    for u in ups:
        new = "<b style='color:#ff3d5a'>NEW</b> " if u["is_new"] else ""
        rows.append(f"<tr><td><img src='{html.escape(u['thumb'])}' style='width:140px;border-radius:6px'></td>"
                    f"<td>{new}<a href='{html.escape(u['link'])}' target='_blank'>{html.escape(u['title'])}</a><br>"
                    f"<span style='color:#888'>{html.escape(u['channel'] or '')} &middot; {html.escape(u['published'][:16].replace('T', ' '))}</span></td></tr>")
    db.run("UPDATE uploads SET is_new=0")
    save_state()
    chans = db.q("SELECT name FROM channels ORDER BY name")
    print("Watching:", ", ".join(c["name"] for c in chans) or "nobody yet")
    try:
        from IPython.display import HTML, display
        display(HTML("<table>" + "".join(rows) + "</table>"))
    except Exception:
        for u in ups:
            print(u["title"], u["link"])

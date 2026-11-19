"""The local web app (FastAPI). Open http://localhost:8000 on the laptop,
or the Wi-Fi address shown at start-up on your phone."""
from __future__ import annotations

import json
import os
import random
import shutil
import string
import time
from pathlib import Path

import cv2
from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import campaigns, captions, certs, db, learn, media, pipeline, smart, watcher
from .config import (APPROVED_DIR, CLIPS_DIR, DATA_DIR, INPUT_DIR, LAYOUTS, PRESETS, STATIC_DIR, load_settings,
                     save_settings)
from .recorder import list_audio_devices, list_windows, recorder

app = FastAPI(title="Clip HQ")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/files/clips", StaticFiles(directory=CLIPS_DIR), name="clips")
app.mount("/files/approved", StaticFiles(directory=APPROVED_DIR), name="approved")
UPLOAD_DIR = INPUT_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _no_cache(path: Path) -> HTMLResponse:
    return HTMLResponse(path.read_text("utf-8"), headers={"Cache-Control": "no-store"})


@app.get("/")
def index(request: Request):
    ua = request.headers.get("user-agent", "").lower()
    if any(k in ua for k in ("iphone", "android", "ipod")) and request.query_params.get("desktop") != "1":
        return _no_cache(STATIC_DIR / "phone.html")
    return _no_cache(STATIC_DIR / "index.html")


@app.get("/m")
def phone():
    return _no_cache(STATIC_DIR / "phone.html")


@app.get("/cliphq-ca.crt")
def ca_cert():
    certs.ensure_certs()
    return FileResponse(certs.CA_CERT, media_type="application/x-x509-ca-cert", filename="ClipHQ-CA.crt")


# ---------------- status ----------------

@app.get("/api/status")
def status(since: int = 0):
    st = load_settings()
    ips = certs.local_ips()
    videos = db.q("SELECT id,name,status,stage,progress,error,created,options FROM videos "
                  "WHERE status IN ('queued','working') OR created > ? ORDER BY id DESC LIMIT 30",
                  (time.time() - 86400 * 3,))
    for v in videos:
        v["options"] = db.loads(v["options"], {})
    events = db.q("SELECT * FROM events WHERE id > ? ORDER BY id DESC LIMIT 50", (since,))
    counts = {r["status"]: r["n"] for r in db.q("SELECT status, COUNT(*) n FROM clips GROUP BY status")}
    return {
        "videos": videos, "events": events, "counts": counts, "recorder": recorder.status(),
        "worker": pipeline.worker.current,
        "urls": {"phone": [f"https://{ip}:{st['https_port']}/m" for ip in ips[:2]],
                 "phone_http": [f"http://{ip}:{st['port']}/m" for ip in ips[:2]]},
        "new_uploads": db.one("SELECT COUNT(*) n FROM uploads WHERE is_new=1")["n"],
        "last_event": db.one("SELECT MAX(id) m FROM events")["m"] or 0,
    }


@app.get("/api/meta")
def meta():
    return {"presets": PRESETS, "layouts": LAYOUTS, "styles": {k: v["label"] for k, v in captions.STYLES.items()},
            "hook_styles": captions.HOOK_STYLES, "campaigns": campaigns.list_campaigns()}


# ---------------- process ----------------

@app.get("/api/browse")
def browse(path: str = ""):
    """A simple file picker (a web page can't see your file paths on its own)."""
    if not path:
        roots = [str(INPUT_DIR), str(Path.home() / "Videos"), str(Path.home() / "Downloads"), str(Path.home() / "Desktop")]
        if os.name == "nt":
            roots += [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
        return {"path": "", "parent": "", "dirs": [r for r in roots if os.path.isdir(r)], "files": []}
    p = Path(path)
    if not p.is_dir():
        raise HTTPException(400, "Not a folder")
    dirs, files = [], []
    try:
        for c in sorted(p.iterdir(), key=lambda x: x.name.lower()):
            if c.name.startswith("."):
                continue
            if c.is_dir():
                dirs.append(str(c))
            elif c.suffix.lower() in watcher.VIDEO_EXT:
                files.append({"path": str(c), "name": c.name, "size": c.stat().st_size})
    except PermissionError:
        pass
    return {"path": str(p), "parent": str(p.parent) if p.parent != p else "", "dirs": dirs, "files": files}


@app.post("/api/process")
def process(body: dict = Body(...)):
    paths = body.get("paths") or ([body["path"]] if body.get("path") else [])
    if body.get("folder"):
        folder = Path(body["folder"])
        if not folder.is_dir():
            raise HTTPException(400, "Folder not found")
        paths += [str(p) for p in sorted(folder.iterdir()) if p.suffix.lower() in watcher.VIDEO_EXT]
    if not paths:
        raise HTTPException(400, "Pick a video file or folder first")
    opts = {k: body.get(k) for k in ("preset", "campaign_id", "layout", "scout", "speed", "min_clip", "max_clip", "max_clips")
            if body.get(k) not in (None, "")}
    ids = []
    for p in paths:
        if not Path(p).is_file():
            raise HTTPException(400, f"File not found: {p}")
        ids.append(pipeline.queue_video(p, opts))
    if body.get("remember_for_drop"):
        save_settings({"drop_options": opts})
    return {"queued": ids}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...), auto: str = Form("1"), preset: str = Form("gta6"),
                 campaign_id: str = Form(""), scout: str = Form("0")):
    name = Path(file.filename or "upload.mov").name
    safe = "".join(c for c in name if c.isalnum() or c in "._- ") or "upload.mov"
    dest = UPLOAD_DIR / f"{time.strftime('%Y%m%d_%H%M%S')}_{safe}"
    with dest.open("wb") as f:
        while True:
            chunk = await file.read(4 * 1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
    vid = None
    if auto == "1":
        opts = {"preset": preset, "source": "phone"}
        if campaign_id:
            opts["campaign_id"] = int(campaign_id)
        if scout == "1":
            opts.update(scout=True, speed=2.0)
        vid = pipeline.queue_video(str(dest), opts)
    db.event("info", f"Uploaded from phone: {name}")
    return {"saved": dest.name, "video_id": vid}


@app.get("/api/videos")
def videos():
    rows = db.q("SELECT * FROM videos ORDER BY id DESC LIMIT 200")
    for r in rows:
        r["options"] = db.loads(r["options"], {})
        r["info"] = db.loads(r["info"], {})
        r["scout"] = db.loads(r["scout"], [])
    return rows


@app.post("/api/videos/{vid}/cancel")
def cancel(vid: int):
    db.update("videos", vid, status="cancelled", stage="Cancelled")
    return {"ok": True}


@app.post("/api/videos/{vid}/retry")
def retry(vid: int):
    db.update("videos", vid, status="queued", stage="", error="", progress=0)
    pipeline.worker.wake.set()
    return {"ok": True}


@app.delete("/api/videos/{vid}")
def delete_video(vid: int):
    v = db.one("SELECT status FROM videos WHERE id=?", (vid,))
    if v and v["status"] == "working":
        db.update("videos", vid, status="cancelled")
    db.run("DELETE FROM videos WHERE id=?", (vid,))
    return {"ok": True}


@app.get("/api/videos/{vid}/frame")
def frame(vid: int, t: float = 30):
    v = db.one("SELECT path FROM videos WHERE id=?", (vid,))
    if not v:
        raise HTTPException(404)
    img = media.grab_frame(v["path"], t, width=960)
    if img is None:
        raise HTTPException(404, "Couldn't read a frame")
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return Response(buf.tobytes(), media_type="image/jpeg")


@app.post("/api/videos/{vid}/examples")
def add_example(vid: int, body: dict = Body(...)):
    eid = learn.add_example(vid, float(body["t"]), body.get("label", "good"))
    return {"id": eid, "weights": load_settings()["gta"].get("weights", {}), "phrases": learn.learned_phrases()}


# ---------------- clips / review ----------------

def _clip_out(c: dict) -> dict:
    c["edits"] = db.loads(c["edits"], {})
    c.pop("words", None)
    c["url"] = f"/files/clips/{c['file']}" if c.get("file") else ""
    c["thumb_url"] = f"/files/clips/{c['thumb']}" if c.get("thumb") else ""
    af = c["edits"].get("approved_file")
    c["approved_url"] = f"/files/approved/{af}" if af else ""
    return c


@app.get("/api/clips")
def clips(status: str = "", video_id: int = 0):
    sql = "SELECT c.*, v.name video_name FROM clips c LEFT JOIN videos v ON v.id=c.video_id WHERE c.status != 'deleted'"
    args: list = []
    if status:
        sql += " AND c.status IN (%s)" % ",".join("?" * len(status.split(",")))
        args += status.split(",")
    if video_id:
        sql += " AND c.video_id=?"
        args.append(video_id)
    sql += " ORDER BY c.video_id DESC, c.score DESC LIMIT 500"
    return [_clip_out(c) for c in db.q(sql, tuple(args))]


@app.get("/api/clips/{cid}")
def clip(cid: int):
    c = db.one("SELECT c.*, v.name video_name, v.path video_path FROM clips c LEFT JOIN videos v ON v.id=c.video_id WHERE c.id=?", (cid,))
    if not c:
        raise HTTPException(404)
    words = db.loads(c["words"], [])
    out = _clip_out(c)
    out["transcript"] = " ".join(w["w"] for w in words if c["start"] - 0.05 <= w["s"] <= c["end"])
    return out


@app.patch("/api/clips/{cid}")
def edit_clip(cid: int, body: dict = Body(...)):
    c = db.one("SELECT * FROM clips WHERE id=?", (cid,))
    if not c:
        raise HTTPException(404)
    ed = db.loads(c["edits"], {})
    fields = {}
    for k in ("hook", "title", "description", "layout", "style"):
        if k in body:
            fields[k] = body[k]
    if "start" in body or "end" in body:
        v = db.one("SELECT info FROM videos WHERE id=?", (c["video_id"],))
        dur = db.loads(v["info"], {}).get("duration", 10 ** 6) if v else 10 ** 6
        s = max(0.0, float(body.get("start", c["start"])))
        e = min(float(dur), float(body.get("end", c["end"])))
        if e - s < 3:
            raise HTTPException(400, "Clip must be at least 3 seconds")
        fields["start"], fields["end"] = round(s, 2), round(e, 2)
        # make sure we have the words for the new range
        cache = pipeline.load_cache(c["video_id"])
        if cache.get("words"):
            fields["words"] = [w for w in cache["words"] if s - 15 <= w["s"] <= e + 15]
    for k in ("extra_texts", "captions_on", "hook_style", "caption_y", "facecam", "blur", "checked"):
        if k in body:
            ed[k] = body[k]
    if "hook" in body and body["hook"] != c["hook"] and "title" not in body:
        camp = campaigns.get(ed.get("campaign_id"))
        fields["title"] = campaigns.make_title(body["hook"], c["kind"], camp)
        words = fields.get("words") or db.loads(c["words"], [])
        s0, e0 = fields.get("start", c["start"]), fields.get("end", c["end"])
        text = " ".join(w["w"] for w in words if s0 <= w["s"] <= e0)
        fields["description"] = campaigns.make_description(body["hook"], text, camp, ed.get("gta", True))
    fields["edits"] = ed
    rerender = any(k in body for k in ("hook", "layout", "style", "start", "end", "extra_texts", "captions_on",
                                       "hook_style", "caption_y", "facecam", "blur"))
    if rerender and body.get("render", True):
        fields["status"] = "queued"
        if c["status"] == "approved":
            ed.pop("approved_file", None)
    db.update("clips", cid, **fields)
    pipeline.worker.wake.set()
    return clip(cid)


@app.post("/api/clips/{cid}/shuffle")
def shuffle(cid: int):
    st = load_settings()
    c = db.one("SELECT style, edits FROM clips WHERE id=?", (cid,))
    opts = [s for s in st["caption_styles_enabled"] if s != c["style"]] or list(captions.STYLES)
    ed = db.loads(c["edits"], {})
    return edit_clip(cid, {"style": random.choice(opts), "hook_style": random.randrange(len(captions.HOOK_STYLES))})


@app.post("/api/clips/{cid}/approve")
def approve(cid: int):
    try:
        return pipeline.approve(cid)
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@app.post("/api/clips/{cid}/delete")
def delete_clip(cid: int):
    c = db.one("SELECT file FROM clips WHERE id=?", (cid,))
    if c and c["file"]:
        for f in (CLIPS_DIR / c["file"], CLIPS_DIR / c["file"].replace(".mp4", ".jpg")):
            try:
                f.unlink()
            except OSError:
                pass
    db.update("clips", cid, status="deleted", file="")
    return {"ok": True}


@app.post("/api/clips/{cid}/rerender")
def rerender(cid: int):
    db.update("clips", cid, status="queued")
    pipeline.worker.wake.set()
    return {"ok": True}


@app.get("/api/download/{cid}")
def download(cid: int):
    c = db.one("SELECT * FROM clips WHERE id=?", (cid,))
    if not c or not c["file"]:
        raise HTTPException(404)
    ed = db.loads(c["edits"], {})
    f = APPROVED_DIR / ed["approved_file"] if ed.get("approved_file") else CLIPS_DIR / c["file"]
    return FileResponse(f, media_type="video/mp4", filename=f.name)


# ---------------- campaigns ----------------

@app.get("/api/campaigns")
def list_c():
    return campaigns.list_campaigns()


@app.post("/api/campaigns")
def save_c(body: dict = Body(...)):
    f = [body.get(k, "") for k in ("name", "hashtags", "tags", "pay_rate", "rules", "focus")]
    if not f[0]:
        raise HTTPException(400, "Give the campaign a name")
    if body.get("id"):
        db.run("UPDATE campaigns SET name=?,hashtags=?,tags=?,pay_rate=?,rules=?,focus=? WHERE id=?", (*f, int(body["id"])))
        return {"id": body["id"]}
    return {"id": db.run("INSERT INTO campaigns(name,hashtags,tags,pay_rate,rules,focus,created) VALUES (?,?,?,?,?,?,?)",
                         (*f, time.time()))}


@app.delete("/api/campaigns/{cid}")
def del_c(cid: int):
    db.run("DELETE FROM campaigns WHERE id=?", (cid,))
    return {"ok": True}


@app.post("/api/clips/{cid}/apply_campaign")
def apply_campaign(cid: int, body: dict = Body(...)):
    c = db.one("SELECT * FROM clips WHERE id=?", (cid,))
    camp = campaigns.get(body.get("campaign_id"))
    ed = db.loads(c["edits"], {})
    words = db.loads(c["words"], [])
    text = " ".join(w["w"] for w in words if c["start"] <= w["s"] <= c["end"])
    ed["campaign_id"] = body.get("campaign_id")
    ed["checklist"] = campaigns.checklist(camp)
    ed["checked"] = []
    db.update("clips", cid, title=campaigns.make_title(c["hook"], c["kind"], camp),
              description=campaigns.make_description(c["hook"], text, camp, ed.get("gta", True)), edits=ed)
    return clip(cid)


# ---------------- channels ----------------

@app.get("/api/channels")
def channels():
    return {"channels": db.q("SELECT * FROM channels ORDER BY name"),
            "uploads": db.q("SELECT u.*, c.name channel_name FROM uploads u LEFT JOIN channels c ON c.channel_id=u.channel_id "
                            "ORDER BY u.published DESC LIMIT 100")}


@app.post("/api/channels")
def add_channel(body: dict = Body(...)):
    try:
        return watcher.add_channel(body.get("text", ""))
    except Exception as e:
        raise HTTPException(400, f"Couldn't add channel: {e}")


@app.delete("/api/channels/{cid}")
def del_channel(cid: int):
    db.run("DELETE FROM channels WHERE id=?", (cid,))
    return {"ok": True}


@app.post("/api/channels/check")
def check_now():
    return {"new": watcher.check_all()}


@app.post("/api/uploads/seen")
def mark_seen(body: dict = Body(default={})):
    if body.get("video_id"):
        db.run("UPDATE uploads SET is_new=0 WHERE video_id=?", (body["video_id"],))
    else:
        db.run("UPDATE uploads SET is_new=0")
    return {"ok": True}


# ---------------- recorder ----------------

@app.get("/api/recorder")
def rec_status():
    return recorder.status()


@app.get("/api/recorder/sources")
def rec_sources():
    return {"windows": list_windows(), "audio": list_audio_devices()}


@app.post("/api/recorder/start")
def rec_start(body: dict = Body(default={})):
    try:
        return recorder.start(body)
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/recorder/stop")
def rec_stop():
    return recorder.stop()


# ---------------- settings ----------------

@app.get("/api/settings")
def get_settings():
    st = load_settings()
    st["claude_api_key_set"] = bool(st.get("claude_api_key"))
    st["claude_api_key"] = ("•" * 8 + st["claude_api_key"][-4:]) if st.get("claude_api_key") else ""
    st["learned_phrases"] = learn.learned_phrases()
    st["examples"] = db.one("SELECT COUNT(*) n FROM examples")["n"]
    return st


@app.put("/api/settings")
def put_settings(body: dict = Body(...)):
    body.pop("claude_api_key_set", None)
    body.pop("learned_phrases", None)
    body.pop("examples", None)
    if str(body.get("claude_api_key", "")).startswith("•"):
        body.pop("claude_api_key")
    return save_settings(body) and get_settings()


@app.post("/api/settings/test_claude")
def test_claude():
    st = load_settings()
    if not st.get("claude_api_key"):
        return {"result": "No key saved yet"}
    return {"result": smart.test_key(st["claude_api_key"], st.get("claude_model"))}


@app.post("/api/settings/reset_learning")
def reset_learning():
    db.run("DELETE FROM examples")
    from .config import set_value
    set_value(["gta", "weights"], {})
    return {"ok": True}


@app.exception_handler(Exception)
async def err(request: Request, exc: Exception):
    return JSONResponse({"detail": str(exc)[:500]}, status_code=500)

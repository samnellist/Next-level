"""Channel watcher (YouTube public RSS feeds, no API key) and the drop-folder watcher.

Nothing here downloads videos. It only reads the public feed that lists a channel's
latest uploads, so you get an alert and a link.
"""
from __future__ import annotations

import re
import threading
import time
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

from . import db
from .config import load_settings
from .notify import notify

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept-Language": "en-GB,en;q=0.9"}
COOKIES = {"CONSENT": "YES+cb", "SOCS": "CAI"}  # skip the EU/UK cookie consent page
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
      "media": "http://search.yahoo.com/mrss/"}
CHECK_EVERY = 600  # 10 minutes


def resolve_channel(text: str) -> tuple[str, str]:
    """Accepts a channel URL, @handle, or UC... id. Returns (channel_id, url)."""
    t = text.strip()
    m = re.search(r"(UC[\w-]{22})", t)
    if m and ("/channel/" in t or re.fullmatch(r"UC[\w-]{22}", t)):
        return m.group(1), f"https://www.youtube.com/channel/{m.group(1)}"
    if t.startswith("@"):
        url = f"https://www.youtube.com/{t}"
    elif t.startswith("http"):
        url = t
    elif "youtube.com" in t:
        url = "https://" + t
    else:
        url = f"https://www.youtube.com/@{t}"
    r = httpx.get(url, headers=UA, cookies=COOKIES, follow_redirects=True, timeout=20)
    r.raise_for_status()
    html = r.text
    for pat in (r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"',
                r'<meta itemprop="identifier" content="(UC[\w-]{22})"',
                r'"externalId":"(UC[\w-]{22})"', r'"channelId":"(UC[\w-]{22})"',
                r'"browseId":"(UC[\w-]{22})"'):
        m = re.search(pat, html)
        if m:
            return m.group(1), url
    raise RuntimeError("Couldn't find that channel. Paste the full channel link (e.g. https://www.youtube.com/@name).")


def fetch_feed(channel_id: str) -> tuple[str, list[dict]]:
    r = httpx.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}", headers=UA, timeout=20,
                  follow_redirects=True)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    name = root.findtext("a:title", default="", namespaces=NS)
    items = []
    for e in root.findall("a:entry", NS):
        vid = e.findtext("yt:videoId", default="", namespaces=NS)
        link_el = e.find("a:link", NS)
        thumb_el = e.find("media:group/media:thumbnail", NS)
        items.append({
            "video_id": vid,
            "title": e.findtext("a:title", default="", namespaces=NS),
            "link": link_el.get("href") if link_el is not None else f"https://www.youtube.com/watch?v={vid}",
            "published": e.findtext("a:published", default="", namespaces=NS),
            "thumb": thumb_el.get("url") if thumb_el is not None else f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
        })
    return name, items


def add_channel(text: str) -> dict:
    cid, url = resolve_channel(text)
    name, items = fetch_feed(cid)
    db.run("INSERT OR IGNORE INTO channels(channel_id,name,url,added,last_checked) VALUES (?,?,?,?,?)",
           (cid, name, url, time.time(), time.time()))
    # existing videos are history: don't alert about them
    for it in items:
        db.run("""INSERT OR IGNORE INTO uploads(video_id,channel_id,title,link,thumb,published,seen,is_new,notified)
                  VALUES (?,?,?,?,?,?,?,0,1)""",
               (it["video_id"], cid, it["title"], it["link"], it["thumb"], it["published"], time.time()))
    return {"channel_id": cid, "name": name, "videos": len(items)}


def check_all() -> int:
    new_count = 0
    for ch in db.q("SELECT * FROM channels"):
        try:
            name, items = fetch_feed(ch["channel_id"])
            for it in items:
                if db.one("SELECT 1 FROM uploads WHERE video_id=?", (it["video_id"],)):
                    continue
                db.run("""INSERT INTO uploads(video_id,channel_id,title,link,thumb,published,seen,is_new,notified)
                          VALUES (?,?,?,?,?,?,?,1,1)""",
                       (it["video_id"], ch["channel_id"], it["title"], it["link"], it["thumb"], it["published"], time.time()))
                new_count += 1
                notify(f"New upload: {name or ch['name']}", it["title"], "upload")
            db.run("UPDATE channels SET last_checked=?, last_error='', name=? WHERE id=?",
                   (time.time(), name or ch["name"], ch["id"]))
        except Exception as e:
            db.run("UPDATE channels SET last_checked=?, last_error=? WHERE id=?", (time.time(), str(e)[:200], ch["id"]))
    return new_count


VIDEO_EXT = {".mp4", ".mkv", ".mov", ".m4v", ".avi", ".webm", ".flv", ".ts", ".wmv", ".mpg", ".mpeg", ".3gp"}


def scan_drop_folder() -> int:
    from .pipeline import queue_video
    st = load_settings()
    if not st.get("watch_drop_folder"):
        return 0
    folder = Path(st.get("drop_folder") or "")
    if not folder.is_dir():
        return 0
    added = 0
    for p in sorted(folder.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in VIDEO_EXT or p.name.endswith(".part.mp4"):
            continue
        try:
            size, mtime = p.stat().st_size, p.stat().st_mtime
        except OSError:
            continue
        row = db.one("SELECT * FROM seen_files WHERE path=?", (str(p),))
        if row and row["added"]:
            continue
        # wait until the file stops growing (still copying / downloading)
        if not row or row["size"] != size or time.time() - mtime < 8:
            db.run("INSERT OR REPLACE INTO seen_files(path,size,mtime,added) VALUES (?,?,?,0)", (str(p), size, mtime))
            continue
        db.run("UPDATE seen_files SET added=? WHERE path=?", (time.time(), str(p)))
        opts = dict(st.get("drop_options") or {"preset": "gta6"})
        queue_video(str(p), opts)
        db.event("info", f"Drop folder: queued {p.name}")
        added += 1
    return added


class Watchers(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True, name="watchers")
        self.next_feed = 0.0

    def run(self) -> None:
        while True:
            try:
                scan_drop_folder()
            except Exception:
                traceback.print_exc()
            if time.time() >= self.next_feed:
                self.next_feed = time.time() + CHECK_EVERY
                try:
                    check_all()
                except Exception:
                    traceback.print_exc()
            time.sleep(10)


watchers = Watchers()

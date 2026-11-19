"""Small SQLite database. JSON columns hold the flexible bits."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any

from .config import DB_FILE

_local = threading.local()
_write_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  path TEXT NOT NULL,
  name TEXT,
  status TEXT DEFAULT 'queued',      -- queued, working, done, error, cancelled
  stage TEXT DEFAULT '',
  progress REAL DEFAULT 0,
  options TEXT DEFAULT '{}',
  info TEXT DEFAULT '{}',
  error TEXT DEFAULT '',
  scout TEXT DEFAULT '[]',
  created REAL,
  finished REAL
);
CREATE TABLE IF NOT EXISTS clips (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  video_id INTEGER,
  start REAL, "end" REAL,
  score INTEGER, reason TEXT, kind TEXT,
  hook TEXT, title TEXT, description TEXT,
  layout TEXT, style TEXT,
  edits TEXT DEFAULT '{}',
  words TEXT DEFAULT '[]',
  file TEXT DEFAULT '',
  thumb TEXT DEFAULT '',
  status TEXT DEFAULT 'new',         -- new, rendering, ready, approved, deleted, error
  render_error TEXT DEFAULT '',
  created REAL,
  notified INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS channels (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  channel_id TEXT UNIQUE, name TEXT, url TEXT, added REAL, last_checked REAL, last_error TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS uploads (
  video_id TEXT PRIMARY KEY, channel_id TEXT, title TEXT, link TEXT, thumb TEXT,
  published TEXT, seen REAL, is_new INTEGER DEFAULT 1, notified INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS campaigns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT, hashtags TEXT, tags TEXT, pay_rate TEXT, rules TEXT, focus TEXT DEFAULT '', created REAL
);
CREATE TABLE IF NOT EXISTS examples (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  video_id INTEGER, t REAL, label TEXT, features TEXT, ocr TEXT, created REAL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, message TEXT, created REAL
);
CREATE TABLE IF NOT EXISTS seen_files (path TEXT PRIMARY KEY, size INTEGER, mtime REAL, added REAL);
"""


def conn() -> sqlite3.Connection:
    c = getattr(_local, "c", None)
    if c is None:
        c = sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        _local.c = c
    return c


def init() -> None:
    with _write_lock:
        conn().executescript(SCHEMA)
        conn().commit()
        # Anything left "working" from a crash goes back in the queue.
        conn().execute("UPDATE videos SET status='queued', stage='' WHERE status='working'")
        conn().execute("UPDATE clips SET status='new' WHERE status='rendering'")
        conn().commit()


def q(sql: str, args: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn().execute(sql, args).fetchall()]


def one(sql: str, args: tuple = ()) -> dict | None:
    r = conn().execute(sql, args).fetchone()
    return dict(r) if r else None


def run(sql: str, args: tuple = ()) -> int:
    with _write_lock:
        cur = conn().execute(sql, args)
        conn().commit()
        return cur.lastrowid


def update(table: str, row_id: int, **fields: Any) -> None:
    if not fields:
        return
    cols = []
    vals = []
    for k, v in fields.items():
        if isinstance(v, (dict, list)):
            v = json.dumps(v)
        cols.append(f'"{k}"=?')
        vals.append(v)
    vals.append(row_id)
    run(f"UPDATE {table} SET {', '.join(cols)} WHERE id=?", tuple(vals))


def event(kind: str, message: str) -> None:
    run("INSERT INTO events(kind, message, created) VALUES (?,?,?)", (kind, message, time.time()))


def loads(s: str | None, default: Any) -> Any:
    try:
        return json.loads(s) if s else default
    except Exception:
        return default

#!/usr/bin/env python3
"""
HQ status board. Every agent calls this so its robot lights up on hq.html.

  python3 tools/hq.py set <agent> <idle|working|done|error> "what I'm doing"
  python3 tools/hq.py reset            # everyone back to idle (start of a new run)
  python3 tools/hq.py subs 1234        # update your subscriber count
  python3 tools/hq.py refresh          # rebuild hq_data.js from tracker.csv

Agents: chief, scout, transcript, picker, cutter, hooks, voice, captions, publisher

Writes status.json (the real data) and hq_data.js (the same data wrapped so a
double-clicked hq.html can read it: browsers block reading .json files from
disk, but they do allow loading a .js file).
"""
import csv
import datetime as dt
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATUS = os.path.join(ROOT, "status.json")
DATA_JS = os.path.join(ROOT, "hq_data.js")
TRACKER = os.path.join(ROOT, "tracker.csv")

AGENTS = {
    "chief": "Chief of Staff", "scout": "Trend Scout", "transcript": "Transcript Reader",
    "picker": "Moment Picker", "cutter": "Cutter", "hooks": "Hook Writer",
    "voice": "Voice Check", "captions": "Caption Maker", "publisher": "Publisher",
}
STATES = ("idle", "working", "done", "error")


def now():
    return dt.datetime.now().isoformat(timespec="seconds")


def _write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)                           # atomic: the dashboard never sees half a file


def load():
    try:
        with open(STATUS, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data.setdefault("agents", {})
    data.setdefault("log", [])
    data.setdefault("channel", {"subscribers": 0, "goal": 10000})
    for k in AGENTS:
        data["agents"].setdefault(k, {"state": "idle", "msg": "", "updated": ""})
    return data


def tracker_summary():
    today = dt.date.today().isoformat()
    s = {"today": 0, "approved": 0, "posted": 0, "views": 0, "top": None}
    try:
        with open(TRACKER, encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    except OSError:
        return s
    best = -1
    for r in rows:
        s["approved"] += 1
        if r.get("date_approved") == today:
            s["today"] += 1
        if (r.get("posted_date") or "").strip():
            s["posted"] += 1
        try:
            v = int(float(r.get("views") or 0))
        except ValueError:
            v = 0
        s["views"] += v
        if v > best and v > 0:
            best, s["top"] = v, {"hook": r.get("hook", ""), "views": v}
    return s


def save(data):
    data["updated"] = now()
    _write(STATUS, json.dumps(data, indent=2))
    payload = dict(data, tracker=tracker_summary(), names=AGENTS)
    _write(DATA_JS, "window.HQ_DATA = " + json.dumps(payload) + ";\n")


def set_status(agent, state, msg=""):
    if agent not in AGENTS:
        raise SystemExit(f"Unknown agent '{agent}'. Use one of: {', '.join(AGENTS)}")
    if state not in STATES:
        raise SystemExit(f"State must be one of: {', '.join(STATES)}")
    data = load()
    data["agents"][agent] = {"state": state, "msg": msg[:120], "updated": now()}
    if state != "idle":
        data["log"] = ([{"t": now(), "agent": agent, "state": state, "msg": msg[:120]}]
                       + data["log"])[:25]
    save(data)


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return
    cmd = argv[0]
    if cmd == "set" and len(argv) >= 3:
        set_status(argv[1], argv[2], " ".join(argv[3:]))
    elif cmd == "reset":
        data = load()
        for k in AGENTS:
            data["agents"][k] = {"state": "idle", "msg": "", "updated": now()}
        save(data)
    elif cmd == "subs" and len(argv) == 2:
        data = load()
        data["channel"]["subscribers"] = int(argv[1].replace(",", ""))
        save(data)
        print(f"Subscribers set to {data['channel']['subscribers']}")
    elif cmd == "refresh":
        save(load())
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])

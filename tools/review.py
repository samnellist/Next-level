#!/usr/bin/env python3
"""
The approval gate. Nothing is "ready" until you approve it here.

  python3 tools/review.py list                          # every video with clips waiting
  python3 tools/review.py list <name>                   # clips for one video + hook/reason/score
  python3 tools/review.py approve <name> clip_01 clip_04
  python3 tools/review.py bin <name> clip_02 clip_03

approve -> moves the clip to out/<name>/approved/ and adds it to tracker.csv
bin     -> moves the clip to out/<name>/binned/ (and takes it off tracker.csv if it was approved)
"""
import csv
import datetime as dt
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hq  # noqa: E402

ROOT = hq.ROOT
OUT = os.path.join(ROOT, "out")
TRACKER = hq.TRACKER
FIELDS = ["id", "date_approved", "video", "clip", "hook", "moment_type", "reason", "score",
          "posted_date", "views", "likes", "subs_gained", "last_updated"]


def clip_info(name):
    path = os.path.join(OUT, name, "clips.csv")
    if not os.path.exists(path):
        sys.exit(f"No clips found for '{name}' (looked for {path})")
    with open(path, encoding="utf-8", newline="") as f:
        return {r["clip"].replace(".mp4", ""): r for r in csv.DictReader(f)}


def where(name, clip):
    for state in ("approved", "binned"):
        if os.path.exists(os.path.join(OUT, name, state, clip + ".mp4")):
            return state
    if os.path.exists(os.path.join(OUT, name, clip + ".mp4")):
        return "waiting"
    return "missing"


def read_tracker():
    if not os.path.exists(TRACKER):
        return []
    with open(TRACKER, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_tracker(rows):
    with open(TRACKER, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def cmd_list(name=None):
    if not name:
        names = sorted(d for d in os.listdir(OUT)
                       if os.path.exists(os.path.join(OUT, d, "clips.csv"))) if os.path.isdir(OUT) else []
        if not names:
            print("No finished clips yet. Run /clip first.")
        for n in names:
            states = [where(n, c) for c in clip_info(n)]
            print(f"{n}: {states.count('waiting')} waiting, {states.count('approved')} approved, "
                  f"{states.count('binned')} binned")
        return
    for clip, r in clip_info(name).items():
        state = where(name, clip)
        folder = f"out/{name}/" + ("" if state in ("waiting", "missing") else state + "/")
        print(f"{clip}  [{state.upper()}]  score {r.get('score', '')}  "
              f"type {r.get('type', '') or '-'}  {r.get('start', '')}-{r.get('end', '')}")
        print(f"   hook:   {r.get('hook', '') or '(none)'}")
        print(f"   reason: {r.get('reason', '') or '(auto-picked loud moment)'}")
        print(f"   file:   {folder}{clip}.mp4")


def move(name, clips, state):
    info = clip_info(name)
    rows = read_tracker()
    today = dt.date.today().isoformat()
    for clip in clips:
        clip = clip.replace(".mp4", "")
        if clip.isdigit():
            clip = f"clip_{int(clip):02d}"
        if clip not in info:
            print(f"  ? {clip}: not one of this video's clips, skipped")
            continue
        now_at = where(name, clip)
        if now_at == "missing":
            print(f"  ? {clip}: file not found, skipped")
            continue
        src = (os.path.join(OUT, name, clip + ".mp4") if now_at == "waiting"
               else os.path.join(OUT, name, now_at, clip + ".mp4"))
        dst_dir = os.path.join(OUT, name, state)
        os.makedirs(dst_dir, exist_ok=True)
        if now_at != state:
            shutil.move(src, os.path.join(dst_dir, clip + ".mp4"))
        cid = f"{name}/{clip}"
        rows = [r for r in rows if r["id"] != cid] if state == "binned" else rows
        if state == "approved" and not any(r["id"] == cid for r in rows):
            r = info[clip]
            rows.append({"id": cid, "date_approved": today, "video": name, "clip": clip,
                         "hook": r.get("hook", ""), "moment_type": r.get("type", ""),
                         "reason": r.get("reason", ""), "score": r.get("score", ""),
                         "posted_date": "", "views": "", "likes": "", "subs_gained": "",
                         "last_updated": today})
        print(f"  {'✓' if state == 'approved' else '✗'} {clip} -> out/{name}/{state}/")
    write_tracker(rows)
    hq.set_status("chief", "done", f"Review: {len(clips)} clip(s) {state}")


def main(argv):
    if not argv or argv[0] not in ("list", "approve", "bin"):
        sys.exit(__doc__)
    if argv[0] == "list":
        cmd_list(argv[1] if len(argv) > 1 else None)
    elif len(argv) >= 3:
        move(argv[1], argv[2:], "approved" if argv[0] == "approve" else "binned")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])

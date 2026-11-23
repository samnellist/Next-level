#!/usr/bin/env python3
"""
Performance tracker. Every approved clip is a row in tracker.csv.

  python3 tools/stats.py list                                    # every tracked clip + its id
  python3 tools/stats.py set <id> views=12000 likes=800 subs=15 posted=2026-11-24
  python3 tools/stats.py subs 1234                               # channel subscriber count
  python3 tools/stats.py report                                  # what's working

<id> looks like  my_stream/clip_03  (see 'list').
"""
import csv
import datetime as dt
import os
import re
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hq  # noqa: E402
from review import FIELDS, read_tracker, write_tracker  # noqa: E402

KEYS = {"views": "views", "likes": "likes", "subs": "subs_gained", "posted": "posted_date"}


def num(v):
    """'12,400' / '12.4k' / '1.2M' -> int (None if blank or not a number)."""
    s = str(v).strip().lower().replace(",", "")
    mult = {"k": 1000, "m": 1000000}.get(s[-1:], 1) if s else 1
    try:
        return int(round(float(s.rstrip("km")) * mult))
    except ValueError:
        return None


def cmd_list(rows):
    if not rows:
        print("tracker.csv is empty. Approve clips in /review first.")
    for r in rows:
        print(f"{r['id']:<32} views {r['views'] or '-':>8}  posted {r['posted_date'] or '-':<10}  "
              f"[{r['moment_type'] or '-'}] {r['hook']}")


def cmd_set(rows, cid, pairs):
    match = [r for r in rows if r["id"] == cid] or [r for r in rows if r["id"].endswith(cid)]
    if len(match) != 1:
        sys.exit(f"Couldn't find exactly one clip matching '{cid}'. Run: python3 tools/stats.py list")
    r = match[0]
    for p in pairs:
        k, _, v = p.partition("=")
        if k not in KEYS:
            sys.exit(f"Unknown field '{k}'. Use: {', '.join(KEYS)}")
        if k != "posted" and num(v) is None:
            sys.exit(f"'{v}' isn't a number")
        r[KEYS[k]] = v if k == "posted" else str(num(v))
    r["last_updated"] = dt.date.today().isoformat()
    write_tracker(rows)
    hq.save(hq.load())
    print(f"Updated {r['id']}: views {r['views'] or '-'}, likes {r['likes'] or '-'}, "
          f"subs {r['subs_gained'] or '-'}")


def hook_style(h):
    h = h.strip()
    words = len(h.split())
    tags = [f"{words} words" if words <= 8 else "9+ words (breaks rule)"]
    if h.endswith("?"):
        tags.append("question")
    if re.search(r"\b(he|she|they|this|that)\b", h.lower()):
        tags.append("mystery 'this/he/they'")
    if re.search(r"\d", h):
        tags.append("has a number")
    if re.search(r"\b(never|nobody|no one|first|only)\b", h.lower()):
        tags.append("superlative")
    return tags


def cmd_report(rows):
    rows = [r for r in rows if num(r["views"]) is not None]
    if not rows:
        print("No view counts yet. Use /stats and paste your numbers.")
        return
    allv = [num(r["views"]) for r in rows]
    print(f"{len(rows)} clips with views. Total {sum(allv):,}. Median {int(st.median(allv)):,}. "
          f"Best {max(allv):,}.\n")

    def group(label, keyfn):
        g = {}
        for r in rows:
            for k in keyfn(r):
                g.setdefault(k, []).append(num(r["views"]))
        print(label)
        for k, v in sorted(g.items(), key=lambda kv: -st.median(kv[1])):
            print(f"  {k:<28} median {int(st.median(v)):>9,}   ({len(v)} clip{'s' if len(v) > 1 else ''})")
        print()

    group("By moment type:", lambda r: [r["moment_type"] or "unknown"])
    group("By hook style:", lambda r: hook_style(r["hook"]))
    top = sorted(rows, key=lambda r: -num(r["views"]))
    print("Top hooks:")
    for r in top[:5]:
        print(f"  {num(r['views']):>9,}  [{r['moment_type'] or '-'}] {r['hook']}")
    if len(top) <= 5:
        return
    print("\nBottom hooks:")
    for r in top[-3:][::-1]:
        print(f"  {num(r['views']):>9,}  [{r['moment_type'] or '-'}] {r['hook']}")


def main(argv):
    rows = read_tracker()
    if not argv:
        sys.exit(__doc__)
    if argv[0] == "list":
        cmd_list(rows)
    elif argv[0] == "set" and len(argv) >= 3:
        cmd_set(rows, argv[1], argv[2:])
    elif argv[0] == "subs" and len(argv) == 2:
        hq.main(["subs", argv[1]])
    elif argv[0] == "report":
        cmd_report(rows)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])

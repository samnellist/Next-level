#!/usr/bin/env python3
"""
Merge loud spikes + hype lines from the transcript into one shortlist.

  python3 tools/candidates.py work/<name>

Reads  work/<name>/spikes.csv      (from: clipper.py VIDEO --analyze work/<name>/spikes.csv --clips 30)
       work/<name>/transcript.json (from: tools/transcribe.py)
Writes work/<name>/candidates.md   ~up to 40 candidate moments, each with what was said around it

The Moment Picker agent reads candidates.md and chooses the final 10.
"""
import csv
import json
import os
import re
import sys

HYPE = [  # phrase -> points
    ("clip that", 6), ("clip it", 6), ("no way", 4), ("oh my god", 4), ("omg", 3),
    ("are you kidding", 4), ("what the", 3), ("let's go", 3), ("lets go", 3),
    ("i can't believe", 3), ("i cannot believe", 3), ("no no no", 4), ("oh no", 3),
    ("bro", 1), ("chat", 1), ("insane", 2), ("crazy", 2), ("funniest", 3), ("dude", 1),
    ("run", 1), ("go go", 3), ("wait wait", 3), ("help", 2), ("why", 1), ("yo", 1),
    ("haha", 2), ("laugh", 2), ("scream", 2), ("dead", 1), ("cops", 1), ("police", 1),
    ("glitch", 2), ("bug", 1), ("first time", 2), ("never seen", 3), ("hold on", 2),
]
WINDOW = 30          # seconds of transcript shown per candidate
MAX_CANDIDATES = 40


def fmt(t):
    t = int(max(0, t))
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}"


def text_score(text):
    t = " " + text.lower() + " "
    score = sum(pts * len(re.findall(r"(?<![a-z])" + re.escape(p) + r"(?![a-z])", t))
                for p, pts in HYPE)
    score += text.count("!") * 2
    score += 2 * len(re.findall(r"\b(\w+)[,!.]? \1\b", t))   # "no no", "wait wait"
    return score


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    work = sys.argv[1]
    with open(os.path.join(work, "transcript.json"), encoding="utf-8") as f:
        tr = json.load(f)
    words = [w for s in tr["segments"] for w in s["words"]]   # [word, start, end]
    duration = tr.get("duration") or (words[-1][2] if words else 0)

    spikes = []
    sp_path = os.path.join(work, "spikes.csv")
    if os.path.exists(sp_path):
        with open(sp_path, encoding="utf-8") as f:
            spikes = [(float(r["peak"]), float(r["loud_score"])) for r in csv.DictReader(f)]

    # hype scan: slide a 10s window over the words, keep the best non-overlapping spots
    hype = []
    for i, (_, t0, _) in enumerate(words):
        chunk = " ".join(w[0] for w in words[i:] if w[1] < t0 + 10)
        sc = text_score(chunk)
        if sc >= 4:
            hype.append((t0 + 3, sc))
    hype.sort(key=lambda x: -x[1])

    cands = []   # [peak, loud, hype]
    for t, loud in spikes:
        cands.append([t, loud, 0])
    for t, sc in hype:
        near = [c for c in cands if abs(c[0] - t) < 20]
        if near:
            near[0][2] = max(near[0][2], sc)
        else:
            cands.append([t, 0, sc])
    for c in cands:   # give spikes credit for hype said around them
        if c[2] == 0:
            c[2] = text_score(" ".join(w[0] for w in words if c[0] - 15 <= w[1] <= c[0] + 10))
    cands.sort(key=lambda c: -(c[1] + c[2] * 3))
    cands = sorted(cands[:MAX_CANDIDATES], key=lambda c: c[0])

    out = [f"# Candidate moments: {os.path.basename(os.path.normpath(work))}",
           "",
           f"Stream length {fmt(duration)}. {len(cands)} candidates, in time order.",
           "loud = how much louder than normal (0 = not a spike). hype = hype words/lines said.",
           "Transcript shown from 20s before to 10s after each moment.",
           ""]
    for n, (t, loud, hy) in enumerate(cands, 1):
        lines, cur, cur_t = [], [], None
        for w, s, _ in words:
            if t - 20 <= s <= t + 10:
                if cur_t is None or s - cur_t > 5:
                    if cur:
                        lines.append(cur)
                    cur, cur_t = [f"[{fmt(s)}]"], s
                cur.append(w)
        if cur:
            lines.append(cur)
        said = "\n".join("    " + " ".join(l) for l in lines) or "    (nobody talking)"
        out += [f"## C{n:02d}  moment {fmt(t)} ({t:.1f}s)  loud {loud:.1f}  hype {hy}",
                said, ""]
    path = os.path.join(work, "candidates.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"Wrote {len(cands)} candidates to {path}")


if __name__ == "__main__":
    main()

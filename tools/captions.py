#!/usr/bin/env python3
"""
Word-by-word captions for each clip, made from the transcript (no re-transcribing).

  python3 tools/captions.py draft work/<name>   # transcript + moments.csv -> captions.json + captions.txt
  python3 tools/captions.py build work/<name>   # captions.json -> captions/clip_01.ass ...

Step 1 (draft) writes:
  captions.json  every word of every clip with its timing (relative to the clip start).
                 Voice Check may fix the WORD TEXT (spelling, mask swears) but keeps the timings.
  captions.txt   the same, one line per clip, easy to read.
Step 2 (build) makes the styled caption files clipper.py burns in with --subs-dir:
  big bold white, thick black outline, centred in the lower third, up to 3 words on
  screen with the word being spoken popping bigger.
"""
import csv
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hq  # noqa: E402

WORDS_PER_GROUP = 3
FONT_SIZE = 92
MARGIN_V = 470            # pixels up from the bottom of a 1920-tall frame (= lower third)

ASS_HEAD = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Arial,{FONT_SIZE},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,1,0,1,7,3,2,60,60,{MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def parse_time(s):
    secs = 0.0
    for part in str(s).strip().split(":"):
        secs = secs * 60 + float(part)
    return secs


def ass_time(t):
    cs = int(round(max(0.0, t) * 100))
    return f"{cs // 360000}:{cs % 360000 // 6000:02d}:{cs % 6000 // 100:02d}.{cs % 100:02d}"


def clean(word):
    word = re.sub(r"[{}\\]", "", word).upper()
    return word.strip(" ,.;:")  # keep ! and ? (they add energy), drop trailing commas/full stops


def draft(work):
    with open(os.path.join(work, "transcript.json"), encoding="utf-8") as f:
        words = [w for s in json.load(f)["segments"] for w in s["words"]]
    with open(os.path.join(work, "moments.csv"), encoding="utf-8-sig", newline="") as f:
        moments = [r for r in csv.DictReader(f) if (r.get("start") or "").strip()]
    caps, lines = {}, []
    for n, m in enumerate(moments, 1):
        start, end = parse_time(m["start"]), parse_time(m["end"])
        clip = [[w, round(s - start, 2), round(e - start, 2)]
                for w, s, e in words if start - 0.1 <= s < end - 0.2]
        caps[f"clip_{n:02d}"] = {"start": start, "end": end, "words": clip}
        lines.append(f"clip_{n:02d}: " + (" ".join(w[0] for w in clip) or "(no speech)"))
    with open(os.path.join(work, "captions.json"), "w", encoding="utf-8") as f:
        json.dump(caps, f, indent=1)
    with open(os.path.join(work, "captions.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Drafted captions for {len(caps)} clips -> {work}/captions.json")


def build(work):
    with open(os.path.join(work, "captions.json"), encoding="utf-8") as f:
        caps = json.load(f)
    out_dir = os.path.join(work, "captions")
    os.makedirs(out_dir, exist_ok=True)
    for name, c in caps.items():
        hq.set_status("captions", "working", f"Styling captions for {name}")
        words = [[clean(w), max(0.0, s), e] for w, s, e in c["words"] if clean(w)]
        # group into chunks of up to 3 words, breaking on pauses and sentence ends
        groups, cur = [], []
        for i, w in enumerate(words):
            if cur and (len(cur) >= WORDS_PER_GROUP or w[1] - cur[-1][2] > 0.6):
                groups.append(cur)
                cur = []
            cur.append(w)
            if w[0].endswith(("!", "?")):
                groups.append(cur)
                cur = []
        if cur:
            groups.append(cur)
        events = []
        for g, grp in enumerate(groups):
            nxt = groups[g + 1][0][1] if g + 1 < len(groups) else None
            g_end = grp[-1][2] + 0.25
            if nxt is not None and nxt - g_end < 0.3:
                g_end = nxt                          # no flicker between close groups
            for j, (w, s, e) in enumerate(grp):
                t0 = s
                t1 = grp[j + 1][1] if j + 1 < len(grp) else g_end
                text = " ".join(
                    (r"{\fscx118\fscy118}" + ww + r"{\fscx100\fscy100}") if k == j else ww
                    for k, (ww, _, _) in enumerate(grp))
                if t1 > t0:
                    events.append(f"Dialogue: 0,{ass_time(t0)},{ass_time(t1)},Cap,,0,0,0,,{text}")
        with open(os.path.join(out_dir, f"{name}.ass"), "w", encoding="utf-8") as f:
            f.write(ASS_HEAD + "\n".join(events) + "\n")
    print(f"Built {len(caps)} caption files in {out_dir}/")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("draft", "build"):
        sys.exit(__doc__)
    (draft if sys.argv[1] == "draft" else build)(sys.argv[2])

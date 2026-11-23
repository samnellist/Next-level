#!/usr/bin/env python3
"""
Moments Daily Clipper (v2) - the "Edit Bay".

One stream recording in, up to N vertical Shorts out.

How it picks moments (auto mode): it listens to the audio and finds the spots
where the stream suddenly gets much louder than normal (shouting, laughing,
crashes, explosions). That is usually where the best reactions are. Each clip
starts a little BEFORE the spike so viewers see what caused it.

v2 adds (used by the AI team, all optional):
  --analyze FILE   only find loud spikes and save them to a CSV (no cutting)
  --times FILE     cut the exact start/end times in a moments.csv instead of auto-picking
  --check          with --times: just check the times make sense, cut nothing
  --subs-dir DIR   burn in ready-made captions (clip_01.ass / clip_01.srt ...)
  --preview        fast half-size rough cuts (for checking, not posting)
  --thumbs         save a still frame (clip_01.jpg) at each loud moment
  --status AGENT   report progress to the HQ dashboard

Needs: Python 3.9+, numpy, and ffmpeg on your PATH.
Optional: faster-whisper (pip install faster-whisper) for auto captions.

Examples:
  python3 clipper.py stream.mp4
  python3 clipper.py stream.mp4 --clips 10 --length 30
  python3 clipper.py stream.mp4 --hooks hooks.txt --captions
  python3 clipper.py stream.mp4 --mode crop      # fill screen instead of blur bars
  python3 clipper.py stream.mp4 --analyze spikes.csv --clips 30
  python3 clipper.py stream.mp4 --times moments.csv --hooks hooks.txt --subs-dir captions/
"""
import argparse
import csv
import os
import shutil
import subprocess
import sys
import textwrap

import numpy as np

SR = 16000          # audio sample rate used for analysis
WIN = 0.5           # seconds per loudness window
W, H = 1080, 1920   # Shorts resolution

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))
try:
    import hq                                       # HQ dashboard status (optional)
except ImportError:
    hq = None


# ---------------------------------------------------------------- helpers
def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def fmt(t):
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}"


def parse_time(s):
    """'95', '95.5', '1:35', '0:01:35' or '0:01:35.5' -> seconds."""
    s = str(s).strip()
    if not s:
        raise ValueError("empty time")
    secs = 0.0
    for part in s.split(":"):
        secs = secs * 60 + float(part)
    return secs


def find_font(user_font):
    if user_font:
        return user_font
    for p in [
        "C:/Windows/Fonts/arialbd.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]:
        if os.path.exists(p):
            return p
    return None


def esc(path):
    """Escape a path for use inside an ffmpeg filter argument."""
    return path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def status(agent, state, msg):
    if agent and hq:
        try:
            hq.set_status(agent, state, msg)
        except Exception:
            pass                                    # never let the dashboard break a cut


# ---------------------------------------------------------------- analysis
def loudness_curve(path):
    """Return loudness in dB for every WIN-second window of the audio."""
    print("Listening to the audio...")
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(SR),
         "-f", "s16le", "-"],
        capture_output=True, check=True).stdout
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    n = int(SR * WIN)
    frames = len(audio) // n
    if frames == 0:
        sys.exit("No audio found in that video.")
    audio = audio[: frames * n].reshape(frames, n)
    rms = np.sqrt((audio ** 2).mean(axis=1)) + 1e-6
    return 20 * np.log10(rms)


def excitement(db):
    """How much louder each moment is than the stream's normal level nearby."""
    k = max(1, int(60 / WIN))                       # 60s local baseline
    pad = np.pad(db, (k // 2, k // 2), mode="edge")
    idx = np.arange(len(db))[:, None] + np.arange(0, k, max(1, k // 30))[None, :]
    baseline = np.median(pad[np.clip(idx, 0, len(pad) - 1)], axis=1)
    jump = db - baseline
    s = max(1, int(2 / WIN))                        # smooth over ~2s
    return np.convolve(jump, np.ones(s) / s, mode="same")


def pick_moments(score, total, n_clips, length, pre):
    """Choose the top spikes, spaced so clips never overlap."""
    order = np.argsort(score)[::-1]
    picks = []
    for i in order:
        peak = i * WIN
        start = min(max(0.0, peak - pre), max(0.0, total - length))
        if all(abs(start - p[0]) >= length for p in picks):
            picks.append((start, peak, float(score[i])))
        if len(picks) >= n_clips:
            break
    return picks


def read_times(path, total):
    """Read a moments.csv (start,end + optional peak,type,score,reason)."""
    moments, problems = [], []
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if any((v or "").strip() for v in r.values())]
    for n, r in enumerate(rows, 1):
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
        try:
            start, end = parse_time(r["start"]), parse_time(r["end"])
        except (KeyError, ValueError):
            problems.append(f"row {n}: needs 'start' and 'end' times")
            continue
        if end > total:
            problems.append(f"row {n}: ends at {fmt(end)} but the video is only {fmt(total)} (trimmed)")
            end = total
        if end - start < 1:
            problems.append(f"row {n}: start must be before end")
            continue
        try:
            peak = parse_time(r["peak"]) if r.get("peak") else start + (end - start) * 0.65
        except ValueError:
            peak = start + (end - start) * 0.65
        try:
            sc = float(r.get("score") or 0)
        except ValueError:
            sc = 0.0
        length = end - start
        if not 25 <= length <= 40:
            problems.append(f"row {n}: {length:.0f}s long (Brand Brain wants 25-40s)")
        moments.append({"start": start, "end": end, "peak": peak, "score": sc,
                        "type": r.get("type", ""), "reason": r.get("reason", "")})
    for i, a in enumerate(moments):
        for b in moments[i + 1:]:
            if a["start"] < b["end"] and b["start"] < a["end"]:
                problems.append(f"clips at {fmt(a['start'])} and {fmt(b['start'])} overlap")
    return moments, problems


# ---------------------------------------------------------------- captions
def make_srt(src, start, length, srt_path, model):
    raw = subprocess.run(                           # decode just this clip's audio with ffmpeg
        ["ffmpeg", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{length:.2f}", "-i", src,
         "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
        capture_output=True, check=True).stdout
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    segments, _ = model.transcribe(audio, word_timestamps=True, vad_filter=True)
    words = [w for seg in segments for w in (seg.words or []) if w.start < length]
    if not words:
        return False

    def ts(t):
        t = max(0.0, t)
        ms = int(round(t * 1000))
        return f"{ms // 3600000:02d}:{ms % 3600000 // 60000:02d}:{ms % 60000 // 1000:02d},{ms % 1000:03d}"

    with open(srt_path, "w", encoding="utf-8") as f:
        for i in range(0, len(words), 3):           # 3 words per caption
            chunk = words[i:i + 3]
            text = " ".join(w.word.strip() for w in chunk).upper()
            f.write(f"{i // 3 + 1}\n{ts(chunk[0].start)} --> {ts(chunk[-1].end)}\n{text}\n\n")
    return True


# ---------------------------------------------------------------- render
def render(src, start, length, out_path, mode, hook, font, srt_name, workdir, preview=False):
    s = 0.5 if preview else 1.0                     # preview = half size, much faster
    w, h = int(W * s), int(H * s)
    if mode == "crop":
        chain = f"[0:v]scale=-2:{h},crop={w}:{h}[base]"
    else:  # blurred background + full frame in the middle
        chain = (f"[0:v]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,"
                 f"gblur=sigma=8,scale={w}:{h},eq=brightness=-0.15[bg];"
                 f"[0:v]scale={w}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[base]")
    last = "base"

    hook_files = []
    if hook and font:
        clean = "".join(c for c in hook if ord(c) <= 0xFFFF).strip()  # fonts can't draw emoji
        for j, line in enumerate(textwrap.wrap(clean, 22)[:3]):        # max 3 lines, each centred
            name = f"{os.path.basename(out_path)}.hook{j}.txt"         # ffmpeg runs inside workdir
            with open(os.path.join(workdir, name), "w", encoding="utf-8") as f:
                f.write(line)
            hook_files.append(name)
            chain += (f";[{last}]drawtext=fontfile='{esc(font)}':textfile='{name}':"
                      f"fontsize={int(68 * s)}:fontcolor=black:box=1:boxcolor=white@0.95:"
                      f"boxborderw={int(18 * s)}:"
                      f"x=(w-text_w)/2:y={int((230 + j * 104) * s)}[h{j}]")
            last = f"h{j}"

    if srt_name:
        if srt_name.lower().endswith(".ass"):       # styled word-by-word captions keep their own look
            chain += f";[{last}]subtitles={srt_name}[cap]"
        else:
            style = ("FontName=Arial,FontSize=16,Bold=1,PrimaryColour=&H00FFFFFF,"
                     "OutlineColour=&H00000000,BorderStyle=1,Outline=3,Shadow=0,"
                     "Alignment=2,MarginV=70")
            chain += f";[{last}]subtitles={srt_name}:force_style='{style}'[cap]"
        last = "cap"

    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.2f}", "-t", f"{length:.2f}",
         "-i", os.path.abspath(src), "-filter_complex", chain, "-map", f"[{last}]",
         "-map", "0:a?", "-c:v", "libx264", "-preset", "ultrafast" if preview else "veryfast",
         "-crf", "28" if preview else "21",
         "-r", "30", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
         os.path.abspath(out_path)], cwd=workdir)
    for name in hook_files:
        os.remove(os.path.join(workdir, name))


def thumb(src, t, out_path):
    """Save one still frame so the AI team can 'see' the moment."""
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, t):.2f}", "-i", os.path.abspath(src),
         "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "4", os.path.abspath(out_path)])


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="One stream in, vertical Shorts out.")
    ap.add_argument("video", help="stream recording (mp4, mkv, mov...)")
    ap.add_argument("--clips", type=int, default=10, help="how many clips (default 10)")
    ap.add_argument("--length", type=float, default=30, help="seconds per clip (default 30)")
    ap.add_argument("--pre", type=float, default=None,
                    help="seconds before the loud moment to start (default 65%% of length)")
    ap.add_argument("--mode", choices=["fit", "crop"], default="fit",
                    help="fit = full frame with blurred bars (default), crop = fill screen")
    ap.add_argument("--hooks", help="text file, one hook per line (line 1 = clip 1...)")
    ap.add_argument("--captions", action="store_true",
                    help="auto captions (needs: pip install faster-whisper)")
    ap.add_argument("--font", help="path to a bold .ttf font for hooks")
    ap.add_argument("--out", default="clips_out", help="output folder")
    # v2
    ap.add_argument("--analyze", metavar="CSV",
                    help="only find loud spikes and save them to this CSV (no cutting)")
    ap.add_argument("--times", metavar="CSV",
                    help="cut the start/end times in this moments.csv instead of auto-picking")
    ap.add_argument("--check", action="store_true",
                    help="with --times: only check the times, cut nothing")
    ap.add_argument("--subs-dir", help="folder of ready-made captions (clip_01.ass or .srt)")
    ap.add_argument("--preview", action="store_true", help="fast half-size rough cuts")
    ap.add_argument("--thumbs", action="store_true", help="save a still at each loud moment")
    ap.add_argument("--status", metavar="AGENT", help="report progress to the HQ dashboard")
    a = ap.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg isn't installed or isn't on your PATH.")
    if not os.path.exists(a.video):
        sys.exit(f"Can't find {a.video}")

    total = duration(a.video)
    length = min(a.length, total)
    pre = a.pre if a.pre is not None else length * 0.65

    # ---- analyze only: save the loud spikes for the Moment Picker
    if a.analyze:
        status(a.status, "working", "Listening for loud spikes")
        score = excitement(loudness_curve(a.video))
        moments = sorted(pick_moments(score, total, a.clips, length, pre), key=lambda m: -m[2])
        os.makedirs(os.path.dirname(os.path.abspath(a.analyze)), exist_ok=True)
        with open(a.analyze, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["rank", "peak", "peak_time", "loud_score", "start", "end"])
            for n, (start, peak, sc) in enumerate(moments, 1):
                w.writerow([n, round(peak, 1), fmt(peak), round(sc, 1),
                            round(start, 1), round(min(start + length, total), 1)])
        print(f"Saved {len(moments)} loud spikes from {fmt(total)} of footage to {a.analyze}")
        return

    # ---- pick moments: from a moments.csv, or automatically
    if a.times:
        chosen, problems = read_times(a.times, total)
        for p in problems:
            print("  ! " + p)
        if not chosen:
            sys.exit("No usable times in " + a.times)
        if a.check:
            print(f"{len(chosen)} clips OK to cut" + (" (see notes above)." if problems else "."))
            return
    else:
        score = excitement(loudness_curve(a.video))
        picks = pick_moments(score, total, a.clips, length, pre)
        picks.sort(key=lambda m: -m[2])             # best first
        chosen = [{"start": s, "end": s + length, "peak": p, "score": sc, "type": "", "reason": ""}
                  for s, p, sc in picks]

    os.makedirs(a.out, exist_ok=True)

    hooks = []
    if a.hooks:
        with open(a.hooks, encoding="utf-8") as f:
            hooks = [l.strip() for l in f if l.strip()]
    font = find_font(a.font) if hooks else None
    if hooks and not font:
        print("No font found, so hooks are skipped. Use --font path/to/font.ttf")

    model = None
    if a.captions and not a.subs_dir:
        try:
            from faster_whisper import WhisperModel
            print("Loading caption model (first run downloads it)...")
            model = WhisperModel("small", device="auto", compute_type="int8")
        except ImportError:
            print("Captions skipped: run  pip install faster-whisper  to turn them on.")

    print(f"Cutting {len(chosen)} clips from {fmt(total)} of footage.\n")

    rows = []
    for n, m in enumerate(chosen, 1):
        start, peak, sc = m["start"], m["peak"], m["score"]
        clip_len = m["end"] - start
        name = f"clip_{n:02d}.mp4"
        status(a.status, "working", f"Cutting clip {n} of {len(chosen)}")
        hook = hooks[n - 1] if n - 1 < len(hooks) else None
        srt, temp_sub = None, None
        if a.subs_dir:
            for ext in (".ass", ".srt"):
                cand = os.path.join(a.subs_dir, f"clip_{n:02d}{ext}")
                if os.path.exists(cand):
                    srt = f"clip_{n:02d}.captions{ext}"   # copied next to the output for ffmpeg
                    temp_sub = os.path.join(a.out, srt)
                    shutil.copyfile(cand, temp_sub)
                    break
        elif model:
            srt_path = os.path.join(a.out, f"clip_{n:02d}.srt")
            if make_srt(a.video, start, clip_len, srt_path, model):
                srt = os.path.basename(srt_path)
        print(f"  {name}: {fmt(start)} to {fmt(start + clip_len)}  "
              f"(moment at {fmt(peak)}, score {sc:.1f})")
        render(a.video, start, clip_len, os.path.join(a.out, name),
               a.mode, hook, font, srt, a.out, a.preview)
        if temp_sub:
            os.remove(temp_sub)
        if a.thumbs:
            thumb(a.video, peak, os.path.join(a.out, f"clip_{n:02d}.jpg"))
        rows.append([name, fmt(start), fmt(start + clip_len), fmt(peak), round(sc, 1),
                     hook or "", m["type"], m["reason"]])

    with open(os.path.join(a.out, "clips.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["clip", "start", "end", "loud_moment", "score", "hook", "type", "reason"])
        w.writerows(rows)
    status(a.status, "done", f"Cut {len(rows)} clips")
    print(f"\nDone. {len(rows)} clips are in the '{a.out}' folder (list in clips.csv).")


if __name__ == "__main__":
    main()

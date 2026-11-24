#!/usr/bin/env python3
"""
Transcribe a recording with faster-whisper (word timestamps), runs on your own computer.

  python3 tools/transcribe.py inbox/stream.mp4 work/stream
  python3 tools/transcribe.py inbox/stream.mp4 work/stream --model base   # faster, less accurate

Writes:
  work/<name>/transcript.json  every segment + every word with its start/end time
  work/<name>/transcript.txt   easy-to-read version: [0:12:34] what was said
"""
import argparse
import json
import os
import subprocess
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hq  # noqa: E402


def fmt(t):
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("workdir")
    ap.add_argument("--model", default="small", help="tiny / base / small (default) / medium")
    ap.add_argument("--lang", default="en", help="language code, default en")
    a = ap.parse_args()

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        hq.set_status("transcript", "error", "faster-whisper not installed")
        sys.exit("faster-whisper isn't installed. Run:  python3 -m pip install faster-whisper")

    os.makedirs(a.workdir, exist_ok=True)
    hq.set_status("transcript", "working", "Pulling the audio out")
    # decode with ffmpeg ourselves (avoids PyAV version problems)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", a.video, "-vn", "-ac", "1",
                          "-ar", "16000", "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

    hq.set_status("transcript", "working", f"Loading the '{a.model}' speech model")
    print(f"Loading the '{a.model}' model (first run downloads it)...")
    model = WhisperModel(a.model, device="auto", compute_type="int8")
    segments, info = model.transcribe(audio, language=a.lang, word_timestamps=True,
                                      vad_filter=True)
    total = info.duration or 1
    out, last_pct, t0 = [], -1, time.time()
    for seg in segments:
        words = [[w.word.strip(), round(w.start, 2), round(w.end, 2)]
                 for w in (seg.words or []) if w.word.strip()]
        out.append({"start": round(seg.start, 2), "end": round(seg.end, 2),
                    "text": seg.text.strip(), "words": words})
        pct = int(seg.end / total * 100)
        if pct >= last_pct + 5:
            last_pct = pct
            msg = f"Transcribing... {pct}% ({fmt(seg.end)} of {fmt(total)})"
            print(msg)
            hq.set_status("transcript", "working", msg)

    with open(os.path.join(a.workdir, "transcript.json"), "w", encoding="utf-8") as f:
        json.dump({"source": a.video, "model": a.model, "language": info.language,
                   "duration": round(total, 2), "segments": out}, f)
    with open(os.path.join(a.workdir, "transcript.txt"), "w", encoding="utf-8") as f:
        # one line per burst of speech, stamped with its FIRST WORD's time
        # (Whisper segments can hide long pauses, which made times look early)
        line, last = [], None
        for w, st, en in (w for s in out for w in s["words"]):
            if line and st - last > 1.5:
                f.write(f"[{fmt(line[0][1])}] {' '.join(x[0] for x in line)}\n")
                line = []
            line.append((w, st))
            last = en
        if line:
            f.write(f"[{fmt(line[0][1])}] {' '.join(x[0] for x in line)}\n")
    n_words = sum(len(s["words"]) for s in out)
    mins = (time.time() - t0) / 60
    hq.set_status("transcript", "done", f"{n_words} words transcribed in {mins:.0f} min")
    print(f"Done: {n_words} words, {len(out)} lines -> {a.workdir}/transcript.json")


if __name__ == "__main__":
    main()

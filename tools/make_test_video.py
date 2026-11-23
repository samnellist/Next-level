#!/usr/bin/env python3
"""
Make a fake 4-minute "stream" to test the whole pipeline without a real recording.

  python3 tools/make_test_video.py            # -> inbox/test_stream.mp4

Coloured test pattern + quiet background + a computer voice saying stream-ish
lines, with a few LOUD moments (reactions + bangs) the clipper should find.
The voice comes from ffmpeg's 'flite' voice if it has one, otherwise the Mac's
built-in 'say' command, otherwise beeps (then captions/transcript can't be tested).
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "inbox", "test_stream.mp4")
LENGTH = 240

# (seconds, volume, line)
LINES = [
    (4, 1.0, "okay chat, welcome back to the stream. we are in vice city today"),
    (14, 1.0, "the plan is simple. we drive to the bank and we keep it quiet"),
    (26, 1.0, "nice and slow, nobody panic, just a normal drive"),
    (38, 4.0, "no way! no way bro! did you see that? oh my god, clip that!"),
    (52, 1.0, "okay okay, that was insane. let's keep going"),
    (75, 1.0, "chat is telling me to take the boat. fine, we take the boat"),
    (90, 1.0, "this boat is way faster than i thought"),
    (104, 4.0, "wait wait wait! the cops are right behind us! go go go!"),
    (118, 1.0, "i think we lost them. i actually think we lost them"),
    (140, 1.0, "right, quick break, drink some water chat"),
    (160, 1.0, "back on the road. lets find something fun to do"),
    (178, 4.0, "what was that? are you kidding me? that is the funniest thing ever!"),
    (194, 1.0, "i can not stop laughing. somebody clip that please"),
    (215, 1.0, "okay that is it for the test stream. thanks for watching"),
]
BANGS = [41, 107, 181]                              # loud crashes right after the reactions


def has_flite():
    out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    return " flite " in out


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    voice = "flite" if has_flite() else ("say" if shutil.which("say") else None)
    with tempfile.TemporaryDirectory() as tmp:
        inputs, mixes = [], []
        for i, (t, vol, text) in enumerate(LINES):
            wav = os.path.join(tmp, f"l{i}.wav")
            if voice == "say":
                aiff = os.path.join(tmp, f"l{i}.aiff")
                subprocess.run(["say", "-o", aiff, text], check=True)
                src_args = ["-i", aiff]
            elif voice == "flite":
                txt = os.path.join(tmp, f"l{i}.txt")
                with open(txt, "w") as f:
                    f.write(text)
                src_args = ["-f", "lavfi", "-i", f"flite=textfile='{txt}':voice=slt"]
            else:
                src_args = ["-f", "lavfi", "-i", "sine=frequency=440:duration=3"]
            subprocess.run(["ffmpeg", "-v", "error", "-y"] + src_args +
                           ["-ar", "16000", "-ac", "1", wav], check=True)
            inputs += ["-i", wav]
            mixes.append((t, vol))
        for t in BANGS:
            inputs += ["-f", "lavfi", "-i", "anoisesrc=color=brown:amplitude=0.9:duration=1.5"]
            mixes.append((t, 3.0))

        parts, labels = [], []
        for i, (t, vol) in enumerate(mixes, start=1):
            parts.append(f"[{i}:a]aresample=44100,volume={vol},adelay={int(t * 1000)}:all=1[a{i}]")
            labels.append(f"[a{i}]")
        parts.append("[0:a]volume=0.05[bed]")
        parts.append("[bed]" + "".join(labels) +
                     f"amix=inputs={len(labels) + 1}:normalize=0:duration=first[aout]")
        cmd = (["ffmpeg", "-v", "error", "-y",
                "-f", "lavfi", "-i", f"anoisesrc=color=pink:amplitude=0.3:duration={LENGTH}:sample_rate=44100"]
               + inputs +
               ["-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate=30:duration={LENGTH}",
                "-filter_complex", ";".join(parts),
                "-map", f"{len(mixes) + 1}:v", "-map", "[aout]",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
                "-c:a", "aac", "-shortest", OUT])
        subprocess.run(cmd, check=True)
    print(f"Made {OUT} ({LENGTH}s{'' if voice else ', beeps instead of a voice'})")


if __name__ == "__main__":
    sys.exit(main())

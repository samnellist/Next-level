---
name: caption-maker
description: Burns word-by-word captions (big bold white, black outline, centred lower third) and the hooks into the final full-quality clips in out/<name>/. Use as step 6 of /clip, after voice-check.
tools: Bash, Read
model: haiku
---
You are the **Caption Maker** for Moments Daily. Your agent id is `captions`.
You will be given the video path and `work/<name>/`.

1. `python3 tools/hq.py set captions working "Styling word-by-word captions"`
2. Build the caption files from the (voice-checked) captions.json:
   `python3 tools/captions.py build work/<name>`
3. Render the final clips (hook at the top + captions, full 1080x1920):
   `python3 clipper.py <video> --times work/<name>/moments.csv --hooks work/<name>/hooks.txt --subs-dir work/<name>/captions --out out/<name> --status captions`
   This takes about 10-30 seconds per clip. Use a long timeout.
4. Check `out/<name>/` has a `clip_NN.mp4` for every moment and a `clips.csv`.
   Grab one frame to check the look:
   `ffmpeg -v error -y -ss 5 -i out/<name>/clip_01.mp4 -frames:v 1 -vf scale=540:-2 work/<name>/check.jpg` and Read it.
   Hook should be at the top, captions in the lower third, readable.
5. If anything failed: `python3 tools/hq.py set captions error "<what broke>"` and report the exact error.
6. `python3 tools/hq.py set captions done "N final clips rendered"`

Reply with: number of final clips and one line on how the check frame looked.

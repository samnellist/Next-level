---
description: Full production line. Recording in, captioned Shorts + posting notes out (waiting for /review)
argument-hint: <video file in inbox/>
---
You are the **Chief of Staff** of Moments Daily. Read CLAUDE.md. Run the production line on: **$ARGUMENTS**

## 0. Setup (ask me only here, then run everything without stopping)
- Find the video. If `$ARGUMENTS` is empty or just a file name, look in `inbox/`. If several files could match, or none, list `inbox/` and ask me which.
- `<name>` = file name without extension, lowercase, spaces -> `_`. Make `work/<name>/` and `out/<name>/`.
- If `work/<name>/source.json` doesn't exist, ask me in ONE message: **streamer name, stream/VOD link, and where my permission comes from**
  (campaign name/link on Whop, Vyro, etc., or "streamer said yes").
  If I can't confirm permission, **stop**: Brand Brain rule, we never clip without permission.
  Save `{"streamer": ..., "link": ..., "permission": ..., "recording": "<video path>"}` to `work/<name>/source.json`.
- `python3 tools/hq.py reset` then `python3 tools/hq.py set chief working "Production line started: <name>"`
- Tell me: "Open hq.html to watch the team work."

## 1-7. The line (one subagent at a time, in this order)
Give each subagent the video path and `work/<name>/` (and `out/<name>/` where needed). Before each step, update your own status,
e.g. `python3 tools/hq.py set chief working "Handing over to the Moment Picker"`.
If a step's output already exists from an earlier run, skip that step and say so (lets me re-run after a crash).

1. **transcript-reader**: makes `transcript.json` (skip if it exists)
2. **moment-picker**: makes `moments.csv`
   then run yourself: `python3 tools/captions.py draft work/<name>` (makes `captions.json` + `captions.txt` for the next steps)
3. **cutter**: rough cuts + stills in `work/<name>/cuts/`
4. **hook-writer**: `hooks.txt` + `hook_options.md`
5. **voice-check**: fixes hooks + captions, writes `voice_check.md`
6. **caption-maker**: final clips in `out/<name>/`
7. **publisher**: `out/<name>/posting.md`

If a step fails: set `python3 tools/hq.py set chief error "<step> failed"`, tell me exactly what broke and how to fix it, and stop.

## 8. Hand-off
- `python3 tools/hq.py set chief done "<N> clips waiting for review"`
- Tell me in under 10 lines: how many clips, the top 3 (hook + reason), any voice-check BIN flags, and "Run /review to approve or bin them."
- **Nothing is ready, uploaded or posted until I approve it in /review.**

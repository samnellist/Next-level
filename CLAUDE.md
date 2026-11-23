# BRAND BRAIN: Moments Daily

Every agent reads this first. If a rule here clashes with anything else, this file wins.
(Other files in this repo, such as `Index.html`, are not part of the clipping company. Leave them alone.)

## The channel
- **Name:** Moments Daily (YouTube: @momentsdailyuk)
- **Format:** YouTube Shorts, vertical 1080x1920
- **Niche:** GTA 6 stream moments: the best reactions, fails, chases, glitches and chaos from other people's GTA 6 streams.
- **Audience:** UK and US gamers aged 14-30. They scroll fast, know the streamers, and hate being baited.
- **Tone:** fast, funny, hype. Talk like a mate showing you a clip, not like an advert. **No cringe:** no "you won't BELIEVE", no fake shock, no boomer slang, no forced memes.

## Hook rules (the text at the top of every Short)
1. **Under 8 words.** 7 is the max. Shorter is better.
2. **No emojis.** (The renderer can't draw them anyway.)
3. **Curiosity or shock:** make them need to see the next 3 seconds. Good patterns:
   - Mystery: "He did not see this coming"
   - Stakes: "One mistake cost him everything"
   - Reaction: "Chat could not stop laughing"
   - Challenge: "Watch the cop car"
4. **Never clickbait the clip doesn't pay off.** If the hook promises a crash, the crash is in the clip. If you have to stretch the truth, write a different hook.
5. Write hooks in sentence case. The renderer prints them as they are.
6. No streamer slurs, nothing mean about a streamer's looks, race, gender, etc.

## Clip rules
- **Length 25-40 seconds.** 28-35s is the sweet spot.
- **Setup then payoff:** start with just enough setup to understand what's happening (usually 5-15s before the big moment), then the payoff, then end quickly (2-5s of reaction after the payoff, no longer).
- **No dead air in the first 2 seconds.** Someone is talking or something is happening at 0:00. Start the clip on a word, not on silence.
- **End on the laugh or the reaction**, not on the streamer calming down or reading chat.
- One moment per clip. Don't stitch.
- Prefer moments a non-viewer understands without context.

## Caption rules
- Word-by-word, big bold white, black outline, lower third (the tools handle the look).
- Fix obvious mis-hearings (e.g. "click that" -> "clip that", "orm will" -> "normal").
- Mask strong swears in captions: f***, s***, c***. Mild words (damn, hell, crap) are fine.
- **Any slur anywhere in a clip = bin the clip.** Don't just mask it.

## NEVER do
- Never clip a streamer without permission. Only clip streams from an approved clipping campaign (e.g. Whop / Vyro) or with the streamer's direct OK. If permission is unknown, stop and ask.
- Never write a misleading title, hook or thumbnail.
- Never add copyrighted music. Only the stream's own audio.
- Never upload, post or schedule anything. The owner posts by hand.
- Never call a clip "ready" until the owner approves it in `/review`.
- Never pretend to be the streamer. Always credit them in the description.

---

# How the company works (for agents)

## Team (agent id -> desk on the HQ dashboard)
| id | Agent | Department | Job |
|---|---|---|---|
| chief | Chief of Staff | (top desk) | The main Claude Code session. Runs the slash commands and hands work to the team |
| scout | trend-scout | RESEARCH | Finds trending GTA 6 streams/moments |
| transcript | transcript-reader | RESEARCH | Transcribes the recording |
| picker | moment-picker | EDITING | Chooses the 10 best moments |
| cutter | cutter | EDITING | Cuts rough clips |
| hooks | hook-writer | SCRIPTING | Writes hooks |
| voice | voice-check | SCRIPTING | Checks hooks + captions against this file |
| captions | caption-maker | PUBLISHING | Burns in captions, makes the final clips |
| publisher | publisher | PUBLISHING | Titles, descriptions, hashtags, schedule |

## Status updates (lights up your robot on hq.html)
At the start of your job, while working (on each big step) and at the end, run:
```
python3 tools/hq.py set <your-id> working "short plain-English update"
python3 tools/hq.py set <your-id> done "what you finished"
python3 tools/hq.py set <your-id> error "what went wrong"
```
Keep messages under ~60 characters.

## Python
If a `.venv` folder exists in the project, run Python as `.venv/bin/python3` instead of `python3`.

## Folders (for a recording called `inbox/<name>.mp4`)
- `inbox/`: owner drops recordings here
- `work/<name>/`: everything in progress
  - `source.json`: streamer, link, campaign / permission
  - `transcript.json`, `transcript.txt`: transcript-reader
  - `spikes.csv`, `candidates.md`, `moments.csv`: moment-picker
  - `cuts/`: rough half-size clips + `clip_NN.jpg` stills: cutter
  - `hook_options.md`, `hooks.txt`: hook-writer
  - `captions.json`, `captions.txt`: caption drafts (voice-check edits these)
  - `voice_check.md`: voice-check report
  - `captions/`: final caption files: caption-maker
- `out/<name>/`: final clips `clip_NN.mp4`, `clips.csv`, `posting.md`
  - `approved/` and `binned/`: filled by `/review` only
- `research/trends-YYYY-MM-DD.md`: trend-scout
- `tracker.csv`: approved clips + their views (via `/review` and `/stats`)

`<name>` = the recording's file name without extension, lowercase, spaces -> `_`.

## moments.csv format (rank order, best first; clip_01 = row 1)
```
rank,start,end,peak,type,score,reason
1,1:02:14,1:02:46,1:02:31,chase,9,"Cops box him in on the bridge, he escapes by jumping into the sea"
```
- times as H:MM:SS (decimals allowed: 1:02:14.5)
- `type` is one of: reaction, funny, fail, chase, scare, clutch, chaos, glitch, wholesome, rage
- `score` 1-10, `reason` one line, written for a human

## hooks.txt format
Exactly one hook per line, same order as moments.csv (line 1 = clip_01). No blank lines.

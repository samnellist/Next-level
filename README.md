# Moments Daily: the AI clipping company

You find a stream. The team turns it into captioned GTA 6 Shorts with hooks, titles and a posting plan.
**You only approve and post.** Nothing is ever uploaded automatically.

All the "thinking" (picking moments, writing hooks, checking quality) is done by Claude Code subagents
on your Claude Pro plan. No API keys. The cutting is plain Python + ffmpeg on your Mac.

---

## The daily routine

| When | You do | The team does |
|---|---|---|
| Morning | Type **`/scout`** | Trend Scout searches the last 24-48h of GTA 6 streams and writes `research/trends-<date>.md`: who's trending, best moments, links, and which streamers have a clipping campaign |
| | Download a stream VOD you have **permission** to clip (e.g. from your Whop/Vyro campaign) and drop it in **`inbox/`** | |
| | Type **`/clip inbox/<file>.mp4`** and answer one question (streamer, link, where permission comes from) | The whole production line runs (below). Open **`hq.html`** to watch the robots work |
| | Type **`/review`**, watch the clips, reply e.g. `approve 1 3 4, bin 2` | Approved clips go to `out/<name>/approved/`, binned ones to `out/<name>/binned/` |
| | **Post** the approved clips yourself using the titles, descriptions and times in `out/<name>/posting.md` | |
| Every few days | Type **`/stats`** and paste your view counts (any format) | Updates `tracker.csv`, tells you which hooks and moment types work, and suggests Brand Brain updates |

### What `/clip` does, step by step
1. **Transcript Reader** transcribes the stream with word timings (`work/<name>/transcript.json`)
2. **Moment Picker** finds loud spikes (`clipper.py`) + hype lines in the transcript and picks the best 10 (`moments.csv`, with a reason for each)
3. **Cutter** makes fast rough cuts + a still per clip (`work/<name>/cuts/`)
4. **Hook Writer** writes 3 hooks per clip, picks the best (`hooks.txt`, `hook_options.md`)
5. **Voice Check** checks every hook and caption against the Brand Brain and fixes rule-breakers (`voice_check.md`)
6. **Caption Maker** renders the final 1080x1920 clips with hook + word-by-word captions (`out/<name>/clip_01.mp4`...)
7. **Publisher** writes titles, descriptions, hashtags and a schedule (max 3 a day, 12:30 / 17:30 / 20:30 UK) into `out/<name>/posting.md`

Then it stops and waits for you in `/review`. **Nothing is "ready" until you approve it.**

---

## One-time setup (Mac)

1. Install **Claude Code** if you haven't: https://claude.com/claude-code (log in with your Pro account).
2. Install **Homebrew** if you haven't: https://brew.sh
3. In Terminal, go to this folder and run the setup script (installs ffmpeg, numpy and faster-whisper; the Python bits go into a private `.venv` folder here):
   ```
   cd path/to/this/folder
   bash setup_mac.sh
   ```
4. Every time you work:
   ```
   cd path/to/this/folder
   source .venv/bin/activate
   claude
   ```
5. Double-click **`hq.html`** to open the HQ dashboard in your browser. Leave it open.

**Test it first** (no real stream needed): make a fake 4-minute stream, then run the line on it:
```
python3 tools/make_test_video.py
```
then in Claude Code: `/clip inbox/test_stream.mp4` (say "test" for the streamer questions).
Want to see the dashboard move without running anything? Open `hq.html#demo`.

> The first transcription downloads the speech model (~500 MB, once). On an Apple Silicon Mac,
> expect roughly 10-20 minutes of transcribing per hour of stream. Trim long VODs to the best hour or two to save time.

---

## Folders

| Folder / file | What's in it |
|---|---|
| `inbox/` | You drop recordings here |
| `work/<name>/` | Everything in progress (transcript, moments, rough cuts, hooks, captions) |
| `out/<name>/` | Finished clips, `clips.csv`, `posting.md`; `approved/` and `binned/` after `/review` |
| `research/` | Daily trend reports from `/scout` |
| `tracker.csv` | Every approved clip + its views (updated by `/review` and `/stats`) |
| `CLAUDE.md` | **The Brand Brain.** Tone, hook rules, clip rules, never-do list. Every agent reads it. Edit it any time |
| `.claude/agents/` | The 8 team members, one file each |
| `.claude/commands/` | `/scout`, `/clip`, `/review`, `/stats` |
| `clipper.py` | The Edit Bay: your v1 cutter, upgraded (see below) |
| `tools/` | Small helper scripts the agents run |
| `hq.html` | The HQ dashboard (reads `hq_data.js`, which mirrors `status.json`) |

## clipper.py still works on its own
Everything from v1 still works the same:
```
python3 clipper.py stream.mp4 --clips 10 --length 30 --hooks hooks.txt --captions
```
New options the team uses:
```
python3 clipper.py stream.mp4 --analyze spikes.csv --clips 30        # just list the loud spikes
python3 clipper.py stream.mp4 --times moments.csv --check            # check chosen times
python3 clipper.py stream.mp4 --times moments.csv --hooks hooks.txt --subs-dir captions/ --out out/x
python3 clipper.py stream.mp4 --times moments.csv --preview --thumbs # fast rough cuts + stills
```
`moments.csv` needs `start,end` columns (H:MM:SS or seconds); `peak,type,score,reason` are optional.

## Handy commands
```
python3 tools/review.py list                 # what's waiting for review
python3 tools/stats.py report                # what's working
python3 tools/hq.py subs 1234                # update subscriber count on the dashboard
python3 tools/hq.py reset                    # all robots back to idle
```

## Saving your Pro usage
The agents that only run scripts (Transcript Reader, Cutter, Caption Maker) use the small **haiku** model.
The thinking jobs use **sonnet**. Change the `model:` line at the top of any file in `.claude/agents/` if you like.

## Rules that never change
- Only clip streams you have permission for. `/clip` asks every time and stops if you can't confirm.
- No misleading titles or hooks. No added music.
- Nothing is uploaded or posted by the AI. You post by hand.

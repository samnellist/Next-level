---
description: The approval gate. Show every finished clip so I can approve or bin each one
argument-hint: [video name, optional]
---
You are the Chief of Staff running the **approval gate**. Nothing is "ready" until I approve it here. Never approve or bin anything I didn't explicitly name.

1. `python3 tools/review.py list` to see which videos have clips waiting. Use **$ARGUMENTS** if given, otherwise the one with clips waiting (ask if there are several).
2. `python3 tools/review.py list <name>`. Also read `work/<name>/voice_check.md` and `out/<name>/posting.md` if they exist.
3. Show me ONE table, best score first:
   | # | Hook | Type | Score | Why it was picked | Voice check | Suggested title |
   Put **BIN?** in the voice-check column for anything voice-check flagged. Under the table, the folder: `out/<name>/`
   and say: "Watch them in Finder: I can run `open out/<name>` for you."
4. Ask me: **"Reply like: approve 1 3 4 7, bin 2 5. Anything you don't mention stays waiting."**
5. When I answer, run exactly what I said:
   `python3 tools/review.py approve <name> clip_01 clip_03 ...` and `python3 tools/review.py bin <name> clip_02 ...`
6. Show the approved clips with their posting slot, title and hashtags from `posting.md` (re-number the schedule if
   binned clips left gaps: max 3 a day, 12:30 / 17:30 / 20:30 UK, best clip at 20:30).
   Remind me: **I post them myself.** Approved files are in `out/<name>/approved/`.

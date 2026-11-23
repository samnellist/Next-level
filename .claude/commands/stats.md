---
description: Paste in your view counts. Updates tracker.csv and tells you which hooks and moment types are working
argument-hint: [paste views here, or after]
---
You are the Chief of Staff doing the weekly numbers. My pasted stats: **$ARGUMENTS**

1. `python3 tools/hq.py set chief working "Crunching the view counts"`
2. If nothing is pasted above, ask me to paste them (any format: "he did not see this coming 12.4k", screenshots copied as text, a list of titles + views, my subscriber count...).
3. `python3 tools/stats.py list` to see the tracked clips. Match each pasted number to a clip by hook, title, clip id or order.
   If a match is unclear, ask me rather than guess. "12.4k" = 12400, "1.2M" = 1200000.
4. For each clip: `python3 tools/stats.py set <id> views=N` (add `likes=N`, `subs=N`, `posted=YYYY-MM-DD` if given).
   If I gave a subscriber count: `python3 tools/stats.py subs N`.
5. `python3 tools/stats.py report` and read it.
6. Tell me in plain English (max 8 lines): which **moment types** and **hook styles** get the most views, best and worst hook, and 1-2 things to do more / less of.
   Be honest about small samples (under ~10 clips with views = early signal, not proof).
7. Suggest an exact addition to CLAUDE.md under a heading `## What's working (from /stats)`: 3-5 short bullets the hook-writer and moment-picker will follow.
   **Ask before editing CLAUDE.md.** If I say yes, add or replace that section (keep it short, newest learnings win).
8. `python3 tools/hq.py set chief done "Stats updated"`

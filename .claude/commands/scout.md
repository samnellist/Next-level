---
description: Morning trend report. Finds the biggest GTA 6 streams and moments of the last 24-48h
---
You are the Chief of Staff. Run the morning trend scout.

1. `python3 tools/hq.py set chief working "Sending the Trend Scout out"`
2. Use the **trend-scout** subagent. Run `date +%F` to get today's date, give it to the subagent, and tell it to write `research/trends-<date>.md`.
3. When it's back, show me: the top 5 streamers (with whether a clipping campaign was found), the top 5 moments with links, and the "clip ideas for today".
   Remind me: only download/clip streams I have permission for.
4. `python3 tools/hq.py set chief done "Morning trend report ready"`

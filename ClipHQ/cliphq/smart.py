"""Optional smart mode: if you add your own Claude API key in Settings, the transcript of the
candidate moments (text only, never the video) is sent to Claude to re-rank them and write hooks.
If anything goes wrong the app just keeps its own picks."""
from __future__ import annotations

import json
import re

import httpx

from .moments import Moment, fmt_time

API = "https://api.anthropic.com/v1/messages"

PROMPT = """You pick the most viral moments from a livestream for YouTube Shorts.
{context}
Below are candidate moments found by audio/video analysis. Each has an id, a time range, detected signals and the transcript.
Pick the best {k} (fewest is fine if few are good). For each, return:
- id
- score: 1-100 for how likely it is to do well as a Short
- hook: 2-7 word ALL CAPS on-screen hook that creates curiosity WITHOUT giving away the payoff
- reason: one short line on why it works
- title: a YouTube title under 60 characters (no hashtags)
- trim_start / trim_end: optional seconds to move the start later / end earlier so it starts on the most interesting moment and ends right after the payoff (0 if fine)

Reply with JSON only: {{"clips": [{{"id": 0, "score": 90, "hook": "...", "reason": "...", "title": "...", "trim_start": 0, "trim_end": 0}}]}}

Candidates:
{cands}
"""


def rerank(moments: list[Moment], api_key: str, model: str, gta: bool, campaign: dict | None = None,
           k: int = 10) -> tuple[list[Moment], dict]:
    if not api_key or not moments:
        return moments, {}
    ctx = "The streamer is playing GTA 6. Favour chases, crashes, fails, funny physics and big reactions." if gta else ""
    if campaign:
        ctx += f" Campaign: {campaign.get('name','')}. Rules: {campaign.get('rules','')}. Focus: {campaign.get('focus','')}."
    lines = []
    for i, m in enumerate(moments):
        text = " ".join(w["w"] for w in m.words)[:900]
        lines.append(f"[{i}] {fmt_time(m.start)}-{fmt_time(m.end)} ({m.end - m.start:.0f}s) kind={m.kind} "
                     f"signals: {m.reason}\n    \"{text}\"")
    body = {
        "model": model or "claude-sonnet-5-5",
        "max_tokens": 3000,
        "messages": [{"role": "user", "content": PROMPT.format(context=ctx, k=k, cands="\n".join(lines))}],
    }
    try:
        r = httpx.post(API, json=body, timeout=120, headers={
            "x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        r.raise_for_status()
        txt = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
        m = re.search(r"\{.*\}", txt, re.S)
        data = json.loads(m.group(0)) if m else {}
    except Exception as e:  # network, bad key, rate limit...
        return moments, {"error": str(e)[:200]}
    out: list[Moment] = []
    titles: dict = {}
    for c in data.get("clips", []):
        try:
            mo = moments[int(c["id"])]
        except Exception:
            continue
        ts, te = float(c.get("trim_start") or 0), float(c.get("trim_end") or 0)
        length = mo.end - mo.start
        if 0 < ts < length - 8:
            mo.start += ts
        if 0 < te < (mo.end - mo.start) - 8:
            mo.end -= te
        # blend Claude's score with ours so a bad answer can't ruin a great moment
        mo.score = int(round(0.6 * float(c.get("score", mo.score)) + 0.4 * mo.score))
        if c.get("hook"):
            mo.hook = str(c["hook"]).upper()[:60]
        if c.get("reason"):
            mo.reason = ("AI: " + str(c["reason"]))[:140]
        titles[id(mo)] = str(c.get("title", ""))[:70]
        out.append(mo)
    if not out:
        return moments, {"error": "Claude returned nothing usable"}
    out.sort(key=lambda m: -m.score)
    return out, {"titles": titles}


def test_key(api_key: str, model: str) -> str:
    try:
        r = httpx.post(API, timeout=30, json={"model": model, "max_tokens": 10,
                                              "messages": [{"role": "user", "content": "Say OK"}]},
                       headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"})
        if r.status_code == 200:
            return "ok"
        return f"error {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return f"error: {e}"

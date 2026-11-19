"""Titles, descriptions and rule checklists for campaign profiles."""
from __future__ import annotations

import re

from . import db
from .moments import EMOJI


def list_campaigns() -> list[dict]:
    return db.q("SELECT * FROM campaigns ORDER BY name")


def get(cid) -> dict | None:
    if not cid:
        return None
    return db.one("SELECT * FROM campaigns WHERE id=?", (int(cid),))


def _tags(s: str) -> list[str]:
    out = []
    for t in re.split(r"[,\s]+", s or ""):
        t = t.strip()
        if not t:
            continue
        out.append(t if t.startswith("#") else "#" + t)
    return out


def _title_case(hook: str) -> str:
    small = {"a", "an", "the", "of", "in", "on", "to", "and", "or", "for", "at"}
    words = hook.strip().rstrip(".").split()
    out = []
    for i, w in enumerate(words):
        lw = w.lower()
        out.append(lw if (i and lw in small) else lw[:1].upper() + lw[1:])
    return " ".join(out)


def make_title(hook: str, kind: str, campaign: dict | None, ai_title: str = "") -> str:
    tags = _tags(campaign.get("hashtags", "")) if campaign else []
    if not tags:
        tags = ["#shorts"]
    emoji = EMOJI.get(kind, "🔥")
    base = ai_title.strip() if ai_title else _title_case(hook or "Wait for it")
    tag_str = " ".join(tags)
    room = 69 - len(tag_str) - 3  # space + emoji + space
    if len(base) > room:
        base = base[:max(10, room - 1)].rsplit(" ", 1)[0] + "…"
    title = f"{base} {emoji} {tag_str}".strip()
    return title[:69]


def make_description(hook: str, transcript: str, campaign: dict | None, gta: bool) -> str:
    tags = _tags(campaign.get("hashtags", "")) if campaign else []
    extra = ["#shorts", "#gta6", "#gta", "#gaming"] if gta else ["#shorts", "#viral"]
    all_tags = tags + [t for t in extra if t.lower() not in {x.lower() for x in tags}]
    quote = transcript.strip()
    if len(quote) > 140:
        quote = quote[:140].rsplit(" ", 1)[0] + "…"
    lines = [_title_case(hook) + (" 😳" if gta else ""), ""]
    if quote:
        lines += [f"\"{quote}\"", ""]
    if campaign and campaign.get("name"):
        lines.append(f"Credit: {campaign['name']}")
    lines.append("Follow @momentsdailyuk for daily moments")
    lines += ["", " ".join(all_tags)]
    if campaign and campaign.get("tags"):
        lines += ["", "Tags: " + ", ".join(t.strip() for t in campaign["tags"].split(",") if t.strip())]
    return "\n".join(lines)


def checklist(campaign: dict | None) -> list[str]:
    items: list[str] = []
    rules: list[str] = []
    if campaign:
        rules = [r.strip(" .-•") for r in re.split(r"[\n;]+", campaign.get("rules", "") or "") if r.strip(" .-•")]
        rl = " ".join(rules).lower()
        for h in _tags(campaign.get("hashtags", "")):
            if h.lower() not in rl:
                items.append(f"{h} is in the title / caption")
        items += rules
        focus = (campaign.get("focus") or "").strip()
        if focus and not any(focus.lower() in r.lower() and "focus" in r.lower() for r in rules):
            items.append(f"{focus} is the main focus of the clip")
    rl = " ".join(items).lower()
    if "logo" not in rl and "watermark" not in rl:
        items.append("No logos or watermarks on the video")
    items += ["Captions are readable and above YouTube's buttons", "Clip starts straight into the action (no slow intro)"]
    seen, out = set(), []
    for i in items:
        if i.lower() not in seen:
            seen.add(i.lower()); out.append(i)
    return out

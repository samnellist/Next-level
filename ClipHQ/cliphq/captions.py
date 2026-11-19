"""Animated word-by-word captions and hook text, written as an .ass subtitle file and burned in by FFmpeg."""
from __future__ import annotations

import random
import re

W, H = 1080, 1920
SAFE_BOTTOM = int(H * 0.75)  # nothing below here: YouTube's buttons and description sit there

# Colours are normal hex (#RRGGBB); converted to ASS (&HBBGGRR&) below.
STYLES = {
    "bold_yellow": {"label": "Bold yellow (classic)", "font": "Anton", "size": 132, "color": "#FFFFFF",
                    "hi": "#FFE81A", "outline": "#000000", "ow": 7, "shadow": 3, "upper": True, "words": 3, "pop": True},
    "clean_white": {"label": "Clean white", "font": "Poppins Black", "size": 112, "color": "#FFFFFF",
                    "hi": "#38E1FF", "outline": "#000000", "ow": 6, "shadow": 2, "upper": False, "words": 3, "pop": True},
    "neon_green": {"label": "Neon green", "font": "Luckiest Guy", "size": 126, "color": "#FFFFFF",
                   "hi": "#39FF14", "outline": "#000000", "ow": 7, "shadow": 4, "upper": True, "words": 2, "pop": True},
    "boxed": {"label": "Purple outline highlight", "font": "Poppins Black", "size": 110, "color": "#FFFFFF",
              "hi": "#FFFFFF", "hibox": "#7B2CFF", "outline": "#000000", "ow": 5, "shadow": 0, "upper": True, "words": 3, "pop": False},
    "red_pop": {"label": "Red pop", "font": "Bebas Neue", "size": 160, "color": "#FFFFFF",
                "hi": "#FF2E2E", "outline": "#000000", "ow": 7, "shadow": 3, "upper": True, "words": 3, "pop": True},
    "purple_glow": {"label": "Purple glow", "font": "Anton", "size": 130, "color": "#FFFFFF",
                    "hi": "#D16BFF", "outline": "#2A0040", "ow": 8, "shadow": 5, "upper": True, "words": 2, "pop": True},
}

HOOK_STYLES = [
    {"bg": "#FFFFFF", "fg": "#000000"}, {"bg": "#000000", "fg": "#FFFFFF"}, {"bg": "#FFE81A", "fg": "#000000"},
    {"bg": "#FF2E2E", "fg": "#FFFFFF"}, {"bg": "#7B2CFF", "fg": "#FFFFFF"},
]


def ass_color(hex_: str, alpha: int = 0) -> str:
    h = hex_.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _esc(t: str) -> str:
    return t.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def _ts(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def random_style(enabled: list[str], rng: random.Random | None = None) -> str:
    rng = rng or random.Random()
    opts = [s for s in enabled if s in STYLES] or list(STYLES)
    return rng.choice(opts)


def chunk_words(words: list[dict], max_words: int) -> list[list[dict]]:
    chunks, cur = [], []
    for i, w in enumerate(words):
        if cur and (len(cur) >= max_words or w["s"] - cur[-1]["e"] > 0.5):
            chunks.append(cur); cur = []
        cur.append(w)
        if re.search(r"[.?!,]$", w["w"]):
            chunks.append(cur); cur = []
    if cur:
        chunks.append(cur)
    return chunks


def build_ass(words: list[dict], clip_start: float, clip_end: float, style_name: str, hook: str,
              extra_texts: list[dict] | None = None, hook_seconds: float = 3.5, caption_y: float = 0.66,
              hook_style: int = 0, captions_on: bool = True) -> str:
    st = STYLES.get(style_name) or STYLES["bold_yellow"]
    hs = HOOK_STYLES[hook_style % len(HOOK_STYLES)]
    dur = clip_end - clip_start
    cy = int(min(caption_y * H, SAFE_BOTTOM - st["size"] * 1.3))
    hook_size = 104 if len(hook or "") <= 22 else 92 if len(hook or "") <= 34 else 80
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{st['font']},{st['size']},{ass_color(st['color'])},{ass_color(st['hi'])},{ass_color(st['outline'])},{ass_color('#000000', 0x60)},-1,0,0,0,100,100,2,0,1,{st['ow']},{st['shadow']},5,50,50,0,1
Style: Hook,{st['font']},{hook_size},{ass_color(hs['fg'])},{ass_color(hs['fg'])},{ass_color(hs['bg'])},{ass_color(hs['bg'])},-1,0,0,0,100,100,1,0,3,22,0,8,70,70,210,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    # hook title at the top
    if hook and hook.strip():
        ev.append(f"Dialogue: 2,{_ts(0)},{_ts(min(hook_seconds, dur))},Hook,,0,0,0,,"
                  f"{{\\fad(120,200)\\t(0,180,\\fscx106\\fscy106)\\t(180,320,\\fscx100\\fscy100)}}{_esc(hook.strip())}")
    for x in extra_texts or []:
        try:
            a, b = float(x.get("start", 0)), float(x.get("end", dur))
        except Exception:
            continue
        if x.get("text") and b > a:
            ev.append(f"Dialogue: 2,{_ts(a)},{_ts(min(b, dur))},Hook,,0,0,0,,{{\\fad(100,150)}}{_esc(x['text'])}")
    if captions_on:
        rel = [dict(w, s=w["s"] - clip_start, e=w["e"] - clip_start) for w in words
               if w["e"] > clip_start and w["s"] < clip_end]
        hi = ass_color(st["hi"])
        base = ass_color(st["color"])
        caps = []  # (start, end, text)
        for ch in chunk_words(rel, st["words"]):
            texts = [(_esc(w["w"]).upper() if st["upper"] else _esc(w["w"])) for w in ch]
            for i, w in enumerate(ch):
                a = max(0.0, w["s"])
                b = ch[i + 1]["s"] if i + 1 < len(ch) else min(max(w["e"], w["s"]) + 0.4, dur)
                parts = []
                for j, t in enumerate(texts):
                    if j == i:
                        if st.get("hibox"):
                            parts.append(f"{{\\3c{ass_color(st['hibox'])}\\bord14\\c{hi}}}{t}{{\\3c{ass_color(st['outline'])}\\bord{st['ow']}\\c{base}}}")
                        elif st.get("pop"):
                            parts.append(f"{{\\c{hi}\\fscx106\\fscy106}}{t}{{\\c{base}\\fscx100\\fscy100}}")
                        else:
                            parts.append(f"{{\\c{hi}}}{t}{{\\c{base}}}")
                    else:
                        parts.append(t)
                intro = "\\t(0,90,\\fscx104\\fscy104)\\t(90,160,\\fscx100\\fscy100)" if i == 0 and st.get("pop") else ""
                caps.append([a, b, f"{{\\an5\\pos({W // 2},{cy}){intro}}}" + " ".join(parts)])
        caps.sort(key=lambda c: c[0])
        # never show two caption lines at once
        for k in range(len(caps) - 1):
            caps[k][1] = min(caps[k][1], caps[k + 1][0])
        for a, b, text in caps:
            if b - a < 0.04:
                b = a + 0.04
            ev.append(f"Dialogue: 1,{_ts(a)},{_ts(b)},Cap,,0,0,0,,{text}")
    return head + "\n".join(ev) + "\n"

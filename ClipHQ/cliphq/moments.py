"""Find the best moments.

1. Turn every signal into a 0..1 "how unusual is this second" curve.
2. Add them up with weights (GTA mode adds game signals and a big bonus when the
   streamer reacts at the same time as something happens in the game).
3. Pick the strongest peaks, then build a clip around each one:
   - start right before the action (2-4 s before a crash/fail, or at the start of the
     sentence that leads into a reaction), skipping "um", silence and dead air
   - end after the payoff, at the end of a sentence, at a quiet point that loops well
   - 10-30 s, never overlapping
4. Score each clip out of 100 and explain why in one line.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

import numpy as np

FILLER = {"um", "uh", "erm", "er", "ah", "hmm", "mm", "like", "so", "okay", "ok", "yeah", "right", "and", "but",
          "anyway", "basically", "well", "you", "know", "i", "mean"}
FILLER_START_PHRASES = [("you", "know"), ("i", "mean")]

# phrase -> (weight, tag)
LEXICON = {
    "no way": (1.0, "reaction"), "oh my god": (1.0, "reaction"), "oh my gosh": (0.8, "reaction"), "omg": (0.8, "reaction"),
    "let's go": (1.0, "hype"), "lets go": (1.0, "hype"), "let's goo": (1.0, "hype"), "what the": (0.9, "reaction"),
    "what the hell": (1.0, "reaction"), "are you kidding": (0.9, "reaction"), "are you serious": (0.9, "reaction"),
    "bro": (0.4, "reaction"), "bruh": (0.6, "reaction"), "dude": (0.4, "reaction"), "holy": (0.8, "reaction"),
    "insane": (0.7, "hype"), "crazy": (0.6, "hype"), "unbelievable": (0.8, "reaction"), "wow": (0.6, "reaction"),
    "yo": (0.4, "reaction"), "oh no": (0.9, "fail"), "no no no": (1.0, "fail"), "nooo": (1.0, "fail"),
    "i'm dead": (0.8, "funny"), "im dead": (0.8, "funny"), "i'm crying": (0.8, "funny"), "dying": (0.5, "funny"),
    "haha": (0.8, "funny"), "hahaha": (1.0, "funny"), "lol": (0.5, "funny"), "lmao": (0.7, "funny"),
    "wait": (0.5, "setup"), "watch this": (0.9, "setup"), "watch": (0.4, "setup"), "hold on": (0.5, "setup"),
    "look at this": (0.7, "setup"), "check this out": (0.7, "setup"), "here we go": (0.6, "setup"),
    "how": (0.3, "glitch"), "what is happening": (0.9, "glitch"), "glitch": (0.9, "glitch"), "physics": (0.8, "glitch"),
    "did that just": (0.9, "glitch"), "how did": (0.7, "glitch"), "what just happened": (1.0, "glitch"),
    "i died": (0.9, "fail"), "i'm done": (0.6, "fail"), "why": (0.3, "fail"), "nah": (0.4, "reaction"),
    "police": (0.5, "chase"), "cops": (0.6, "chase"), "run": (0.4, "chase"), "go go go": (0.9, "chase"),
    "drive": (0.3, "chase"), "chase": (0.7, "chase"), "lost them": (0.8, "chase"), "get away": (0.6, "chase"),
    "crash": (0.7, "crash"), "crashed": (0.8, "crash"), "explode": (0.7, "crash"), "blew up": (0.8, "crash"),
    "and then": (0.4, "story"), "turns out": (0.7, "story"), "so basically": (0.4, "story"),
    "you won't believe": (0.9, "story"), "true story": (0.7, "story"), "the craziest": (0.7, "story"),
    "fuck": (0.4, "reaction"), "shit": (0.3, "reaction"), "damn": (0.4, "reaction"),
}

GTA_HOOKS = {
    "chase": ["POLICE DIDN'T EXPECT THIS", "THE COPS HAD NO CHANCE", "HE REALLY TRIED TO ESCAPE", "THIS CHASE GOT OUT OF HAND",
              "WORST GETAWAY EVER?", "5 STARS IN 30 SECONDS"],
    "crash": ["WAIT FOR THE CRASH", "HE DID NOT SEE THIS COMING", "THIS DIDN'T GO TO PLAN", "WORST DRIVER IN VICE CITY?",
              "WATCH THE CAR"],
    "fail": ["HE WAS SO CLOSE", "THIS WENT WRONG FAST", "WAIT FOR IT...", "NOBODY SAW THIS COMING", "ONE JOB."],
    "glitch": ["GTA 6 PHYSICS ARE BROKEN", "HOW IS THIS EVEN POSSIBLE", "WAIT, WHAT JUST HAPPENED?", "THIS SHOULDN'T BE POSSIBLE"],
    "shootout": ["THIS GOT OUT OF HAND", "HE PICKED THE WRONG FIGHT", "WAIT FOR IT...", "IT ESCALATED FAST"],
    "wait_for_it": ["WAIT FOR IT...", "WATCH UNTIL THE END", "KEEP WATCHING...", "IT GETS WORSE"],
    "funny": ["HE COULDN'T STOP LAUGHING", "THIS IS WHY I LOVE GTA 6", "I CAN'T BREATHE", "WHAT DID I JUST WATCH"],
    "reaction": ["HIS REACTION THOUGH", "HE COULDN'T BELIEVE IT", "WAIT FOR HIS REACTION", "NOBODY WAS READY"],
    "hype": ["THE CLEANEST PLAY IN GTA 6?", "HE ACTUALLY DID IT", "THIS WAS INSANE", "NO WAY HE PULLED THIS OFF"],
    "mission": ["HE ACTUALLY DID IT", "FIRST TRY?!", "THE ENDING THOUGH"],
    "talk": ["HE HAS A POINT", "CHAT WAS SPLIT ON THIS", "HOT TAKE INCOMING", "WAIT FOR THE ENDING"],
    "question": [], "story": ["STORY TIME", "WAIT FOR THE ENDING"],
}
GENERAL_HOOKS = {
    "funny": ["I CAN'T STOP LAUGHING", "HE REALLY SAID THIS", "WAIT FOR IT...", "THIS WENT LEFT"],
    "story": ["YOU WON'T BELIEVE THIS STORY", "WAIT FOR THE ENDING", "THE ENDING THOUGH...", "STORY TIME"],
    "reaction": ["HIS REACTION THOUGH", "NOBODY WAS READY FOR THIS", "WAIT FOR IT...", "HE WASN'T READY"],
    "hype": ["THIS WAS INSANE", "HE ACTUALLY DID IT", "THE ROOM WENT CRAZY"],
    "question": [],
    "fail": ["THIS WENT WRONG FAST", "WAIT FOR IT...", "HE WAS SO CLOSE"],
    "talk": ["HE HAS A POINT", "HOT TAKE INCOMING", "WAIT FOR THE ENDING", "THIS IS SO TRUE"],
}

EMOJI = {"chase": "🚔", "crash": "💥", "fail": "💀", "glitch": "🤯", "shootout": "🔫", "wait_for_it": "👀",
         "funny": "😂", "talk": "💬", "reaction": "😱", "hype": "🔥", "story": "🎙️", "question": "🤔", "mission": "🏆"}


@dataclass
class Moment:
    start: float
    end: float
    peak: float
    score: int = 0
    raw: float = 0.0
    kind: str = "reaction"
    reason: str = ""
    hook: str = ""
    tags: list = field(default_factory=list)
    words: list = field(default_factory=list)


def _norm(x: np.ndarray, n: int) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    if len(x) < n:
        x = np.pad(x, (0, n - len(x)))
    x = x[:n]
    hi = np.percentile(x, 99) if len(x) else 0
    if hi <= 1e-6:
        hi = x.max() if len(x) and x.max() > 0 else 1
    return np.clip(x / hi, 0, 1.5)


def _smooth(x: np.ndarray, w: int = 3) -> np.ndarray:
    if w <= 1 or len(x) == 0:
        return x
    k = np.ones(w) / w
    return np.convolve(x, k, mode="same")


def _clean(w: str) -> str:
    return re.sub(r"[^a-z0-9' ]", "", w.lower()).strip()


def transcript_signals(words: list[dict], n: int) -> dict:
    wps = np.zeros(n, np.float32)
    react = np.zeros(n, np.float32)
    question = np.zeros(n, np.float32)
    tags = [set() for _ in range(n)]
    hits = [[] for _ in range(n)]
    toks = [_clean(w["w"]) for w in words]
    for w in words:
        s = int(w["s"])
        if 0 <= s < n:
            wps[s] += 1
    for i, w in enumerate(words):
        s = int(w["s"])
        if not 0 <= s < n:
            continue
        for L in (4, 3, 2, 1):
            if i + L > len(toks):
                continue
            ph = " ".join(toks[i:i + L])
            if ph in LEXICON:
                wt, tag = LEXICON[ph]
                react[s] += wt
                tags[s].add(tag)
                hits[s].append(ph)
                break
        # laughter written out ("hahaha")
        if re.fullmatch(r"(ha){2,}h?|(he){3,}|a?ha+ha+", toks[i] or ""):
            react[s] += 0.8; tags[s].add("funny"); hits[s].append("haha")
        # shouted / repeated words ("NO NO NO")
        if i >= 2 and toks[i] and toks[i] == toks[i - 1] == toks[i - 2] and len(toks[i]) <= 6:
            react[s] += 0.6; tags[s].add("reaction")
        # question followed by an answer within 4 s
        if w["w"].endswith("?") and i + 1 < len(words) and words[i + 1]["s"] - w["e"] < 4:
            a = int(words[i + 1]["s"])
            if 0 <= a < n:
                question[a] += 0.7; tags[a].add("question")
    wps_s = _smooth(wps, 3)
    med = np.median(wps_s[wps_s > 0]) if np.any(wps_s > 0) else 1
    pace = np.clip(np.abs(wps_s - med) / (med + 1e-6), 0, 2)
    pace_change = np.zeros(n, np.float32)
    pace_change[3:] = np.clip(np.abs(wps_s[3:] - wps_s[:-3]) / (med + 1e-6), 0, 2)
    return {"words_raw": words, "wps": wps_s, "react": react, "question": question, "pace": pace, "pace_change": pace_change,
            "tags": tags, "hits": hits}


BASE_WEIGHTS = {
    "loud_spike": 1.2, "onset": 0.3, "react": 1.4, "question": 0.5, "pace_change": 0.4, "pace": 0.2,
    "motion": 0.4, "scene_cut": 0.2, "shake": 0.3, "music_change": 0.2,
    # gaming / GTA extras
    "impact": 0.0, "gunfire": 0.0, "siren": 0.0, "hud_change": 0.0, "ocr": 0.0,
}
GTA_WEIGHTS = {"impact": 1.2, "gunfire": 0.7, "siren": 0.6, "hud_change": 0.4, "ocr": 1.5, "motion": 0.7,
               "shake": 0.7, "music_change": 0.4, "scene_cut": 0.3}


def build_curves(duration: float, audio: dict, video: dict | None, tx: dict, ocr_hits: dict | None,
                 gta: bool, learned: dict | None = None) -> tuple[np.ndarray, dict, dict]:
    n = int(np.ceil(duration)) + 1
    w = dict(BASE_WEIGHTS)
    if gta:
        w.update(GTA_WEIGHTS)
    for k, m in (learned or {}).items():
        if k in w:
            w[k] *= float(np.clip(m, 0.4, 2.5))
    curves = {}
    audio = dict(audio)
    # A voice starting after a pause looks like a "bang" to the audio detector.
    # Whisper tells us exactly when speech starts, so discount those seconds.
    imp = np.array(audio.get("impact", np.zeros(n)), np.float32).copy()
    prev_e = -10.0
    for wd in tx.get("words_raw", []):
        if wd["s"] - prev_e > 0.4:
            for sec in (int(wd["s"] - 0.2), int(wd["s"]), int(wd["s"] + 0.2)):
                if 0 <= sec < len(imp):
                    imp[sec] *= 0.2
        prev_e = wd["e"]
    audio["impact"] = imp
    for k in ("loud_spike", "onset", "impact", "gunfire", "siren", "music_change"):
        curves[k] = _norm(audio.get(k, np.zeros(n)), n)
    for k in ("react", "question", "pace_change", "pace"):
        curves[k] = _norm(tx[k], n) if np.any(tx[k]) else np.zeros(n, np.float32)
    for k in ("motion", "scene_cut", "shake", "hud_change"):
        curves[k] = _norm(video[k], n) if video and k in video else np.zeros(n, np.float32)
    # motion spikes matter more than constant motion (driving is always "moving")
    if video and "motion" in video:
        m = _norm(video["motion"], n)
        from .signals import _rolling_median
        curves["motion"] = np.clip(m - _rolling_median(m, 30), 0, 1) * 1.5
    ocr = np.zeros(n, np.float32)
    for t, d in (ocr_hits or {}).items():
        if d.get("hits"):
            i = int(t)
            if 0 <= i < n:
                ocr[i] = 1.0
    curves["ocr"] = ocr
    total = np.zeros(n, np.float32)
    for k, c in curves.items():
        total += w.get(k, 0) * c
    # loud audio with no speech and no motion (music, ads) should not dominate
    if gta:
        game = np.maximum.reduce([curves["impact"], curves["gunfire"], curves["siren"], curves["motion"],
                                  curves["shake"], curves["ocr"]])
        streamer = np.maximum(curves["loud_spike"], curves["react"])
        # streamer reacting within 3 s after a game event = the best GTA moments
        g_recent = np.array([game[max(0, i - 3): i + 1].max() for i in range(n)])
        total += 1.2 * np.minimum(g_recent, streamer)
    total = _smooth(total, 3)
    return total, curves, w


def keep_ranges(duration: float, audio: dict, video: dict | None, pad: float = 25) -> list[tuple[float, float]] | None:
    """Fast GTA skim: find the stretches worth transcribing. Returns None = transcribe everything."""
    n = int(np.ceil(duration)) + 1
    act = _norm(audio["loud_spike"], n) + 0.5 * _norm(audio["onset"], n) + _norm(audio.get("impact", np.zeros(n)), n)
    if video:
        act += _norm(video["motion"], n) * 0.5 + _norm(video.get("shake", np.zeros(n)), n) * 0.5
    thr = np.percentile(act, 65)
    hot = act > max(thr, 0.25)
    if hot.mean() > 0.8 or duration < 8 * 60:
        return None
    keep = np.zeros(n, bool)
    for i in np.where(hot)[0]:
        keep[max(0, int(i - pad)): int(i + pad)] = True
    ranges = []
    i = 0
    while i < n:
        if keep[i]:
            j = i
            while j < n and keep[j]:
                j += 1
            ranges.append((float(i), float(min(j, duration))))
            i = j
        else:
            i += 1
    if sum(b - a for a, b in ranges) > 0.85 * duration:
        return None
    return ranges


# ---------- boundaries ----------

def _sentence_starts(words: list[dict]) -> list[int]:
    idx = []
    for i, w in enumerate(words):
        if i == 0:
            idx.append(i); continue
        prev = words[i - 1]
        if prev["w"][-1:] in ".?!" or w["s"] - prev["e"] > 0.6:
            idx.append(i)
    return idx


def _sentence_ends(words: list[dict]) -> list[int]:
    idx = []
    for i, w in enumerate(words):
        nxt = words[i + 1] if i + 1 < len(words) else None
        if w["w"][-1:] in ".?!" or nxt is None or nxt["s"] - w["e"] > 0.6:
            idx.append(i)
    return idx


def _words_in(words: list[dict], a: float, b: float) -> list[dict]:
    return [w for w in words if w["s"] >= a - 0.01 and w["e"] <= b + 0.3]


def _skip_filler_start(words: list[dict], start: float, limit: float) -> float:
    """Move the start past um/uh/so/okay and silence."""
    ws = [w for w in words if w["s"] >= start - 0.05 and w["s"] < limit]
    i = 0
    while i < len(ws):
        t = _clean(ws[i]["w"])
        if i + 1 < len(ws) and (t, _clean(ws[i + 1]["w"])) in FILLER_START_PHRASES:
            i += 2; continue
        if t in {"um", "uh", "erm", "er", "ah", "hmm", "mm", "so", "okay", "ok", "anyway", "basically", "well", "like"}:
            i += 1; continue
        break
    if i < len(ws):
        return max(start, ws[i]["s"] - 0.12)
    return start


def _quietest(loud: np.ndarray, a: float, b: float) -> float:
    a_i, b_i = int(max(0, a)), int(min(len(loud) - 1, b))
    if b_i <= a_i:
        return b
    seg = loud[a_i:b_i + 1]
    return float(a_i + int(np.argmin(seg)) + 0.5)


def _classify(tagset: set, curves: dict, a: int, b: int, ocr_labels: set, gta: bool) -> str:
    def m(k):
        c = curves.get(k)
        return float(c[a:b].max()) if c is not None and b > a else 0.0
    if gta:
        if ocr_labels & {"death", "arrest", "mission_fail"}:
            return "fail"
        if "mission_pass" in ocr_labels:
            return "mission"
        if "glitch" in tagset:
            return "glitch"
        if m("siren") > 0.5 or "wanted" in ocr_labels or "chase" in tagset:
            return "chase"
        if m("impact") > 0.6 or "crash" in tagset:
            return "crash"
        if m("gunfire") > 0.6:
            return "shootout"
        if "fail" in tagset:
            return "fail"
    for k in ("funny", "fail", "glitch", "story", "question", "hype", "reaction"):
        if k in tagset:
            return k
    if gta and (m("motion") > 0.6 or m("impact") > 0.4):
        return "wait_for_it"
    return "talk"


def _reason(kind: str, curves: dict, w: dict, a: int, b: int, hits: list[str], ocr_text: list[str], gta: bool) -> str:
    names = {
        "loud_spike": "a big volume spike", "react": "a strong reaction", "impact": "an explosion / crash sound",
        "gunfire": "gunfire", "siren": "police sirens", "motion": "sudden on-screen action", "shake": "camera shake",
        "scene_cut": "quick cuts", "ocr": "an on-screen event", "music_change": "the music changing",
        "question": "a question with a payoff", "pace_change": "the pace suddenly changing", "hud_change": "the wanted level changing",
    }
    contrib = []
    for k, label in names.items():
        c = curves.get(k)
        if c is None or b <= a:
            continue
        contrib.append((w.get(k, 0) * float(c[a:b].max()), label))
    contrib.sort(reverse=True)
    top = [l for v, l in contrib[:2] if v > 0.25]
    parts = " + ".join(top) if top else "steady energy"
    quote = ""
    if hits:
        quote = f' ("{hits[0]}")'
    if ocr_text:
        quote += f" [screen: {ocr_text[0]}]"
    pretty = kind.replace("_", " ")
    return f"{pretty.capitalize()}: {parts}{quote}"[:140]


def make_hook(kind: str, words: list[dict], gta: bool, rng: random.Random) -> str:
    pool = (GTA_HOOKS if gta else GENERAL_HOOKS).get(kind) or (GTA_HOOKS if gta else GENERAL_HOOKS)["reaction"]
    # Use the clip's own opening question if it has one (it's a setup, never the payoff)
    # only questions from the opening few seconds (the setup), never the reaction/payoff
    t0 = words[0]["s"] if words else 0
    text = " ".join(w["w"] for w in words if w["s"] < t0 + 5)
    m = re.search(r"([^.?!]{8,70}\?)", text)
    if m and kind in ("question", "talk", "story"):
        q = m.group(1).strip().upper()
        q = re.sub(r"^(ANYWAY|SO|OKAY|OK|CHAT|AND|BUT|ALRIGHT)[, ]+", "", q)
        q = re.sub(r"^(CHAT)[, ]+", "", q)
        if 3 <= len(q.split()) <= 10:
            return q
    if not pool:
        pool = GENERAL_HOOKS["reaction"]
    return rng.choice(pool)


def find_moments(duration: float, audio: dict, video: dict | None, words: list[dict], ocr_hits: dict | None,
                 gta: bool, min_len: float = 10, max_len: float = 30, max_clips: int = 12,
                 learned: dict | None = None, seed: int | None = None) -> tuple[list[Moment], np.ndarray]:
    rng = random.Random(seed)
    n = int(np.ceil(duration)) + 1
    tx = transcript_signals(words, n)
    total, curves, w = build_curves(duration, audio, video, tx, ocr_hits, gta, learned)
    loud = np.asarray(audio["loud"], np.float32)
    if len(loud) < n:
        loud = np.pad(loud, (0, n - len(loud)), constant_values=-80)
    starts_i = _sentence_starts(words)
    ends_i = _sentence_ends(words)
    s_starts = [words[i]["s"] for i in starts_i]
    s_ends = [words[i]["e"] for i in ends_i]
    min_len = max(5.0, float(min_len))
    max_len = max(min_len + 2, float(max_len))

    # ---- peak picking ----
    order = np.argsort(-total)
    taken = np.zeros(n, bool)
    peaks: list[int] = []
    for i in order:
        if len(peaks) >= max_clips * 3:
            break
        if total[i] <= 0 or taken[i]:
            continue
        if i < 2 or i > duration - 2:
            continue
        peaks.append(int(i))
        taken[max(0, int(i - min_len)): int(i + min_len)] = True

    med = float(np.median(total)) if n else 0
    mad = float(np.median(np.abs(total - med))) + 1e-6
    moments: list[Moment] = []
    for p in peaks:
        win_a, win_b = max(0, p - 6), min(n, p + 6)
        tagset = set().union(*tx["tags"][win_a:win_b]) if win_b > win_a else set()
        ocr_labels, ocr_text = set(), []
        for t, d in (ocr_hits or {}).items():
            if win_a - 4 <= t <= win_b + 2 and d.get("hits"):
                ocr_labels.update(d["hits"])
                words_only = re.sub(r"[^A-Za-z ]", "", d["text"]).strip()
                if words_only:
                    ocr_text.append(words_only[:30])
                elif "wanted" in d["hits"]:
                    ocr_text.append(f"wanted level {d.get('stars', '')}".strip())
        ocr_text.sort(key=lambda x: x.startswith("wanted"))
        kind = _classify(tagset, curves, win_a, win_b, ocr_labels, gta)

        # where exactly is the action?
        if gta and kind in ("crash", "fail", "shootout", "chase", "glitch", "wait_for_it", "mission"):
            if kind == "shootout":
                ev = curves["gunfire"]
            else:
                ev = np.maximum.reduce([curves["impact"], curves["motion"], 0.8 * curves["ocr"], curves["shake"]])
            a, b = max(0, p - 5), min(n, p + 3)
            impact_t = a + int(np.argmax(ev[a:b])) if b > a else p
            lead = 3.0 if kind in ("crash", "fail", "glitch") else 4.0
            if kind == "wait_for_it":
                lead = min(max_len - 6, 9.0)
            start = max(0.0, impact_t - lead)
            # don't start mid-word: back up to the start of a word if we are inside one
            for wd in words:
                if wd["s"] < start < wd["e"]:
                    start = wd["s"] - 0.05
                    break
            keep_lead = True
            # if the streamer starts talking during the lead-in, start on their first word
            first = next((wd for wd in words if wd["s"] >= start - 0.05), None)
            if first and 0.4 < first["s"] - start and first["s"] < impact_t:
                start = first["s"] - 0.12
            # build-up talk right before the action ("watch this") is worth keeping
            setup = [s0 for s0 in s_starts if impact_t - 9 <= s0 < start]
            if setup and any(tx["tags"][int(x)] & {"setup"} for x in setup if int(x) < n):
                start = _skip_filler_start(words, setup[0], impact_t)
        else:
            # start at the sentence that leads into the reaction (setup -> payoff)
            cands = [s for s in s_starts if p - (max_len - min_len / 2) <= s <= p - 1.5]
            if cands:
                # prefer the closest setup that still gives ~4-8 s of build-up
                good = [s for s in cands if p - s <= 9]
                start = (good[0] if good else cands[-1])
            else:
                start = max(0.0, p - 4.0)
            keep_lead = False
        if not keep_lead:
            start = _skip_filler_start(words, start, p)
            # dead air at the start? jump to the first word / sound
            first = next((wd for wd in words if wd["s"] >= start - 0.05), None)
            if first and first["s"] - start > 0.4 and first["s"] < p:
                start = first["s"] - 0.12
        start = max(0.0, start)

        # ---- end: after the payoff, at the end of a sentence, at a quiet point ----
        target_min = start + min_len
        target_max = min(duration, start + max_len)
        # the reaction "dies down" when the curve falls under 45% of the peak
        settle = p + 2
        while settle < min(n - 1, target_max) and total[int(settle)] > 0.45 * total[p]:
            settle += 1
        lo = max(target_min, settle)
        end_c = [e for e in s_ends if lo <= e <= target_max]
        if end_c:
            # pick the sentence end with the most silence after it (cleanest loop)
            def gap_after(e):
                nxt = next((wd["s"] for wd in words if wd["s"] > e + 0.01), e + 2)
                return nxt - e
            scored = sorted(end_c[:6], key=lambda e: (-min(gap_after(e), 1.5), e))
            end = scored[0] + 0.25
            nxt = next((wd["s"] for wd in words if wd["s"] > scored[0] + 0.01), None)
            if nxt is not None:
                end = min(end, nxt - 0.05)
        else:
            # no clean sentence end: if someone is talking at the min length, wait for a gap
            in_speech = [wd for wd in words if wd["s"] < target_max and wd["e"] > lo]
            if in_speech:
                end = None
                for i2 in range(len(in_speech) - 1):
                    if in_speech[i2 + 1]["s"] - in_speech[i2]["e"] > 0.3 and in_speech[i2]["e"] >= lo:
                        end = in_speech[i2]["e"] + 0.2
                        break
                if end is None:
                    end = _quietest(loud, lo, target_max)
            else:
                end = _quietest(loud, lo, min(target_max, lo + 6))
        end = float(min(max(end, start + min_len), start + max_len, duration))
        if end - start < min_len * 0.8:
            continue

        a_i, b_i = int(start), int(np.ceil(end))
        seg_words = _words_in(words, start, end)
        hits = [h for hs in tx["hits"][a_i:b_i] for h in hs]
        peak_val = float(total[p])
        mean_val = float(total[a_i:b_i].mean()) if b_i > a_i else 0
        raw = 0.65 * peak_val + 0.35 * mean_val
        # completeness bonuses
        if seg_words and seg_words[-1]["w"][-1:] in ".?!":
            raw *= 1.05
        if not seg_words and not gta:
            raw *= 0.7  # nobody talking in a talking video: weaker
        strength = float(np.clip((peak_val - med) / (6 * mad), 0, 1))
        m = Moment(start=round(start, 2), end=round(end, 2), peak=float(p), raw=raw, kind=kind, words=seg_words)
        m.reason = _reason(kind, curves, w, max(0, p - 4), min(n, p + 4), hits, ocr_text, gta)
        m.hook = make_hook(kind, seg_words, gta, rng)
        m.tags = sorted(tagset)
        m._strength = strength  # type: ignore[attr-defined]
        moments.append(m)

    # ---- choose the best, no overlaps ----
    moments.sort(key=lambda m: -m.raw)
    chosen: list[Moment] = []
    for m in moments:
        if any(not (m.end <= c.start or m.start >= c.end) for c in chosen):
            continue
        chosen.append(m)
        if len(chosen) >= max_clips:
            break
    if chosen:
        top = max(c.raw for c in chosen)
        for c in chosen:
            rel = c.raw / (top + 1e-6)
            c.score = int(round(np.clip(100 * (0.55 * rel + 0.45 * c._strength) * 0.98 + 2, 1, 99)))  # type: ignore
    chosen.sort(key=lambda m: -m.score)
    return chosen, total


def fmt_time(t: float) -> str:
    t = int(round(t))
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

"""Folders and settings for Clip HQ.

Everything lives next to the app so it is easy to find:
  input/     videos waiting to be processed (and the drop folder)
  clips/     every clip the app makes (for review)
  approved/  clips you approved, with their title + description
  data/      the app's database, settings and recordings
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import threading
from pathlib import Path

ROOT = Path(os.environ.get("CLIPHQ_HOME", Path(__file__).resolve().parent.parent))
INPUT_DIR = ROOT / "input"
DROP_DIR = INPUT_DIR / "drop"
CLIPS_DIR = ROOT / "clips"
APPROVED_DIR = ROOT / "approved"
DATA_DIR = ROOT / "data"
WORK_DIR = DATA_DIR / "work"
RECORD_DIR = INPUT_DIR / "recordings"
MODELS_DIR = ROOT / "models"
FONTS_DIR = ROOT / "fonts"
BIN_DIR = ROOT / "bin"
STATIC_DIR = ROOT / "static"
SETTINGS_FILE = DATA_DIR / "settings.json"
DB_FILE = DATA_DIR / "cliphq.db"

for _d in (INPUT_DIR, DROP_DIR, CLIPS_DIR, APPROVED_DIR, DATA_DIR, WORK_DIR, RECORD_DIR, MODELS_DIR, FONTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

IS_WINDOWS = sys.platform.startswith("win")

# Areas of the screen are stored as fractions of the frame: [x, y, width, height], 0..1.
DEFAULTS: dict = {
    "port": 8000,
    "https_port": 8443,
    "whisper_model": "auto",          # auto, tiny.en, base.en, small.en, medium.en
    "whisper_threads": 0,              # 0 = use all cores
    "chunk_minutes": 10,               # transcribe long videos 10 minutes at a time
    "min_clip": 10,
    "max_clip": 30,
    "max_clips": 12,
    "claude_api_key": "",
    "claude_model": "claude-sonnet-5-5",
    "use_claude": True,                # only used when a key is set
    "drop_folder": str(DROP_DIR),
    "watch_drop_folder": True,
    "auto_render": True,
    "render_preset": "veryfast",       # x264 speed: faster = quicker exports, slightly larger files
    "caption_style": "random",
    "caption_styles_enabled": ["bold_yellow", "clean_white", "neon_green", "boxed", "red_pop", "purple_glow"],
    "randomise_style": True,
    "hook_seconds": 3.5,
    "record": {
        "chunk_minutes": 20,
        "auto_stop_minutes": 0,
        "fps": 30,
        "audio": "system",             # system (what you hear), device, none
        "audio_device": "",
        "mic_device": "",
        "target": "screen",            # screen or window
        "window_title": "",
        "keep_awake": True,
        "auto_process": True,
        "preset": "gta6",
        "campaign_id": None,
    },
    "gta": {
        "ocr_engine": "auto",           # auto, rapidocr, tesseract, off
        "ocr_phrases": {
            "death": ["wasted", "you died", "dead", "killed"],
            "arrest": ["busted", "arrested"],
            "mission_pass": ["mission passed", "passed", "respect +", "complete"],
            "mission_fail": ["mission failed", "failed", "fail"],
            "wanted": ["wanted", "police", "cops"],
        },
        "ocr_regions": {
            "center": [0.2, 0.3, 0.6, 0.4],
            "top_right": [0.7, 0.0, 0.3, 0.2],
            "bottom_center": [0.25, 0.75, 0.5, 0.2],
        },
        "wanted_region": [0.75, 0.02, 0.23, 0.12],
        "hud_regions": [[0.0, 0.72, 0.22, 0.28], [0.72, 0.0, 0.28, 0.18]],
        "hide_hud": False,
        "skip_quiet": True,
        "weights": {},
    },
    "clutter_regions": [],            # chat boxes / pop-ups to blur, e.g. [[0.78,0.3,0.22,0.7]]
    "hide_clutter": "blur",            # blur or off
    "notify_desktop": True,
}

PRESETS = {
    "general": {"label": "General (talking / IRL / podcasts)", "layout": "auto", "gta": False},
    "gta6": {"label": "GTA 6 streamer", "layout": "stacked", "gta": True},
    "gaming": {"label": "Other gaming stream", "layout": "auto", "gta": False, "gaming": True},
}

LAYOUTS = {
    "auto": "Auto (pick for me)",
    "face": "Full screen, follows the face",
    "stacked": "Stacked: facecam on top, gameplay below",
    "wide": "Wide shot on dark background",
    "blur": "Blurred background (full 16:9 in middle)",
    "action": "Follow the action (no facecam)",
}

_lock = threading.Lock()


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_settings() -> dict:
    with _lock:
        data = {}
        if SETTINGS_FILE.exists():
            try:
                data = json.loads(SETTINGS_FILE.read_text("utf-8"))
            except Exception:
                data = {}
        return _merge(DEFAULTS, data)


def save_settings(new: dict) -> dict:
    merged = _merge(load_settings(), new)
    with _lock:
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(merged, indent=2), "utf-8")
        os.replace(tmp, SETTINGS_FILE)
    return merged


def tool(name: str) -> str:
    """Find ffmpeg / ffprobe: the copy in ClipHQ/bin first, then the system one."""
    exe = name + (".exe" if IS_WINDOWS else "")
    local = BIN_DIR / exe
    if local.exists():
        return str(local)
    found = shutil.which(name)
    if found:
        return found
    raise RuntimeError(f"{name} was not found. Run 'Install Clip HQ.bat' again to download it.")


def pick_whisper_model(setting: str) -> str:
    if setting and setting != "auto":
        return setting
    cores = os.cpu_count() or 4
    # small.en is much more accurate on shouty gaming audio; base.en is the fast fallback.
    return "small.en" if cores >= 8 else "base.en"


def set_value(keys: list[str], value) -> dict:
    """Replace one nested setting outright (no merging), e.g. set_value(["gta", "weights"], {})."""
    st = load_settings()
    d = st
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value
    with _lock:
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, indent=2), "utf-8")
        os.replace(tmp, SETTINGS_FILE)
    return st

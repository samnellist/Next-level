"""Downloads the free models and fonts Clip HQ needs (run once by the installer)."""
from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

FONTS = {
    "Anton-Regular.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/anton/Anton-Regular.ttf",
    "BebasNeue-Regular.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/bebasneue/BebasNeue-Regular.ttf",
    "Poppins-Black.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-Black.ttf",
    "LuckiestGuy-Regular.ttf": "https://raw.githubusercontent.com/google/fonts/main/apache/luckiestguy/LuckiestGuy-Regular.ttf",
}
YUNET = ("face_detection_yunet_2023mar.onnx",
         "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx")


def fetch(url: str, dest: Path, min_size: int) -> None:
    if dest.exists() and dest.stat().st_size >= min_size:
        print(f"  ok      {dest.name}")
        return
    print(f"  getting {dest.name} ...")
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    urllib.request.urlretrieve(url, tmp)
    if tmp.stat().st_size < min_size:
        tmp.unlink()
        raise RuntimeError(f"{dest.name} download looks wrong")
    tmp.replace(dest)


def main() -> int:
    ok = True
    (ROOT / "fonts").mkdir(exist_ok=True)
    (ROOT / "models").mkdir(exist_ok=True)
    print("Fonts for captions:")
    for name, url in FONTS.items():
        try:
            fetch(url, ROOT / "fonts" / name, 20000)
        except Exception as e:
            ok = False
            print(f"  could not download {name}: {e}")
    print("Face detector:")
    try:
        fetch(YUNET[1], ROOT / "models" / YUNET[0], 100000)
    except Exception as e:
        print(f"  could not download face model ({e}) - the built-in backup detector will be used")
    print("Speech recognition models (this is the big one, ~200-500 MB):")
    from faster_whisper import WhisperModel
    for m in ("base.en", "small.en"):
        try:
            WhisperModel(m, device="cpu", compute_type="int8", download_root=str(ROOT / "models"))
            print(f"  ok      {m}")
        except Exception as e:
            ok = False
            print(f"  could not download {m}: {e}")
    print("On-screen text reader:")
    try:
        from rapidocr_onnxruntime import RapidOCR
        RapidOCR()
        print("  ok      RapidOCR")
    except Exception as e:
        print(f"  RapidOCR not working ({e}) - GTA on-screen text detection will be skipped")
    print("Done." if ok else "Finished with some problems (see above).")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

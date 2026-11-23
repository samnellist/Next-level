#!/bin/bash
# One-time setup for Moments Daily on a Mac. Run it yourself in Terminal:
#   cd path/to/this/folder && bash setup_mac.sh
# It installs: ffmpeg (via Homebrew), and numpy + faster-whisper into a private
# .venv folder inside this project (doesn't touch the rest of your Mac's Python).
set -e
cd "$(dirname "$0")"

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew isn't installed. Install it from https://brew.sh (one command), then run this again."
  exit 1
fi
command -v ffmpeg >/dev/null 2>&1 || brew install ffmpeg
command -v python3 >/dev/null 2>&1 || brew install python

python3 -m venv .venv
.venv/bin/python3 -m pip install --upgrade pip
.venv/bin/python3 -m pip install numpy faster-whisper

mkdir -p inbox work out research
.venv/bin/python3 tools/hq.py reset
echo
echo "All set. Every time you work:  cd \"$(pwd)\" && source .venv/bin/activate && claude"
echo "Then open hq.html (double-click it) to watch the office."

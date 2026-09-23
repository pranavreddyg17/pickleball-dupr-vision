#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -x /opt/homebrew/bin/python3.11 ]; then
  PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.11}"
else
  PYTHON_BIN="${PYTHON_BIN:-python3.11}"
fi
command -v "$PYTHON_BIN" >/dev/null || { echo "Python 3.11 is required (set PYTHON_BIN to its path)."; exit 1; }
command -v ffmpeg >/dev/null || { echo "FFmpeg is required: brew install ffmpeg"; exit 1; }
command -v ffprobe >/dev/null || { echo "ffprobe is required: brew install ffmpeg"; exit 1; }
if [ ! -d .venv ]; then "$PYTHON_BIN" -m venv .venv; fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
if [ ! -f .env ]; then cp .env.example .env; fi
.venv/bin/python -c "from duprvision.core import init_db; init_db()"
.venv/bin/python -c "from ultralytics import YOLO; YOLO('yolo26n-pose.pt')"
echo "Ready. Local analysis needs no API key. Run ./scripts/start.sh"

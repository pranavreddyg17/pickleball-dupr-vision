#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then echo "Run ./scripts/bootstrap.sh first"; exit 1; fi
.venv/bin/python -m duprvision.worker &
WORKER_PID=$!
cleanup() { kill "$WORKER_PID" 2>/dev/null || true; wait "$WORKER_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
echo "DUPRVision: http://127.0.0.1:3000"
.venv/bin/python -m uvicorn duprvision.app:app --host 127.0.0.1 --port 3000 --proxy-headers --forwarded-allow-ips 127.0.0.1


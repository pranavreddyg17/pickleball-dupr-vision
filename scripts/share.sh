#!/usr/bin/env bash
set -euo pipefail
command -v cloudflared >/dev/null || { echo "Install Cloudflare Tunnel first: brew install cloudflared"; exit 1; }
curl -fsS http://127.0.0.1:3000/api/health >/dev/null || { echo "Start DUPRVision with ./scripts/start.sh first"; exit 1; }
HEALTH=$(curl -fsS http://127.0.0.1:3000/api/health)
if ! printf '%s' "$HEALTH" | grep -q '"worker_running":true'; then
  echo "The analysis worker is not running. Restart the app before sharing publicly."
  exit 1
fi
echo "Starting a temporary public URL. Keep this terminal and your Mac running."
cloudflared tunnel --url http://127.0.0.1:3000

# DUPRVision

Video review and daily progress tracking for pickleball players.

[Watch the demo](docs/demo.mp4)

The demo uses a 27-second gameplay clip and the report saved by DUPRVision for that clip: Vision score 97/100, nine assessed shots, and one rally. AI observations are fallible; the clip and score are an example, not a validated skill rating.

## What it does

- Accepts MP4 and MOV gameplay clips up to 3 minutes and 100 MB, including clips shorter than a minute.
- Lets the uploader identify the player and consent to analysis.
- Produces a concise shot and rally review. With Gemini enabled, it scores observed shot control, balance, and recovery on a 0-100 Vision scale.
- Tracks scored days in an activity calendar and shows a daily average. Players can opt into discovery and follow each other.
- Deletes footage after a completed report while retaining the report and daily activity.

The profile also displays a **DUPR-scale equivalent**: `2.0 + 3.0 * Vision average / 100`, rounded to one decimal. This is an uncalibrated display conversion, not an official DUPR rating or a prediction of match results. DUPRVision is independent of DUPR.

## Run locally

Requires Python 3.11, FFmpeg/FFprobe, and at least 5 GB free disk space. On macOS, install FFmpeg with `brew install ffmpeg`.

```sh
./scripts/bootstrap.sh
./scripts/start.sh
```

Open <http://127.0.0.1:3000>. Bootstrap creates `.venv`, `.env`, the local database, and downloads the YOLO26 pose weights. Accounts and reports are stored in `data/duprvision.sqlite3`; temporary uploads live under `data/uploads/`. Both `.env` and `data` are excluded from Git.

### Analysis modes

The default `ANALYSIS_ENGINE=local` uses YOLO26 pose tracking without a paid API. It records possible stroke motions but cannot reliably identify ball contacts, shot types, outcomes, or a skill score. It leaves the Vision score empty when that evidence is unavailable.

For shot and rally review, set these values in `.env` and restart the app:

```dotenv
ANALYSIS_ENGINE=gemini
GEMINI_API_KEY=your-key
GEMINI_MODEL=gemini-3.5-flash-lite
```

Each uploader must consent before the clip and player-selection frame are sent to Google. The worker normalizes video to a silent 5-fps copy and caps the provider payload at 12 MiB. The default worker handles three concurrent jobs; local video processing is serialized. Provider failures can still delay or prevent a report. The daily provider-attempt limit is configurable with `MAX_DAILY_VIDEO_REVIEWS` (default 20).

The Vision score is a clip-performance heuristic: 50% shot control, 25% balance, and 25% recovery. Unclear events are excluded, and too little evidence produces no score. It is not a calibrated skill model.

## Sharing

`./scripts/share.sh` opens a temporary Cloudflare Tunnel to the running local server. Your computer must remain awake and online. Registration is open; this small-group app has no email verification, account recovery, or moderation. Share the URL only with trusted testers.

The optional `cloudflare/worker.mjs` keeps a stable Workers address in front of a changing tunnel. Copy `cloudflare/wrangler.example.jsonc` to `cloudflare/wrangler.jsonc`, configure your Cloudflare account and origin, and deploy with Wrangler. The example config is safe to commit; your account-specific config is ignored. A server that stays online is needed for uptime when your laptop is off.

## Tests

```sh
.venv/bin/python -m pytest -q
node --check static/app.js
node --test cloudflare/worker.test.mjs
```

The YOLO26 weights are subject to Ultralytics' licensing. Review its terms before redistribution or commercial use.

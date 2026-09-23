# DUPRVision

Video review and daily progress tracking for pickleball players.

[Watch the demo](docs/demo.mp4)

The demo records the full app workflow with `1.mp4`: create an account, upload the clip, select a player, consent to analysis, wait for the worker, inspect the report, and review the daily calendar and player directory. This captured run scored 83/100 from nine assessed shots and one rally. The score can vary on another run; AI observations are fallible and are not a validated skill rating.

## What it does

- Accepts MP4 and MOV gameplay clips up to 3 minutes and 100 MB, including clips shorter than a minute.
- Lets the uploader identify the player and consent to analysis.
- Produces a concise shot and rally review. With Gemini enabled, it scores observed shot control, balance, and recovery on a 0-100 Vision scale.
- Tracks scored days in an activity calendar and shows a daily average. Players can opt into discovery and follow each other.
- Deletes the full upload after a completed report while retaining the report and daily activity.
- Replays shot and rally timestamps from the original file in your browser, with 0.25x-1x playback. Reopening a file does not upload it or trigger another analysis.
- Presents your average and a practice takeaway without extra dashboard counters or sparse charts.
- Opens followers and following in an in-place Connections panel with a distinct-player count.
- Saves private session notes and timestamped report corrections without changing the score.
- Can retain up to three private six-second replays and annotated player frames when selected before analysis; the original upload still expires.

The profile also displays a **DUPR-scale equivalent**: `2.0 + 3.0 * Vision average / 100`, rounded to one decimal. This is an uncalibrated display conversion, not an official DUPR rating or a prediction of match results. DUPRVision is independent of DUPR.

### Review and practice

The report opens retained moments directly, with a moving selected-player overlay, Tracked/Original switching, slow motion, frame stepping, looping, and shot filters. Tracking disappears across detection gaps instead of guessing the player's location. Older reports with snapshots open enlarged annotated frames.

Use **Open full video** to review the complete original in your browser without uploading it again. Shot timestamps and rally links seek to an available replay or the attached original. SHA-256 verifies reattached files for uploads made since fingerprinting was introduced. Older reports label the match unverified. Only one browser file reference is retained at a time; it is released on replacement, sign-out, or page reload. Browser codec support is required.

The overview keeps the average score, latest practice takeaway, calendar, and recent sessions. Shot control, balance, and recovery remain in individual reports. **Connections** counts distinct discoverable players you follow or who follow you; mutual follows count once. Its panel opens without leaving Overview and supports filtering, following, and unfollowing. Private profiles are excluded.

**My notes** autosave and are visible only to the account owner. Use **Report an issue** to flag a wrong player, shot assessment, or missed moment. Feedback does not rerun analysis or alter scores. Optional **Key moments** show the locally tracked player, not ball contact or proof of a shot label. Frames and silent replays are owner-only and deleted with the report. New replay retention requires consent before analysis; expired uploads cannot be reconstructed.

## Run locally

Requires Python 3.11, FFmpeg/FFprobe, and at least 5 GB free disk space. On macOS, install FFmpeg with `brew install ffmpeg`.

```sh
./scripts/bootstrap.sh
./scripts/start.sh
```

Open <http://127.0.0.1:3000>. Bootstrap creates `.venv`, `.env`, the local database, and downloads the YOLO26 weights. Accounts and reports are stored in `data/duprvision.sqlite3`; temporary uploads live under `data/uploads/`, and opted-in frames and replays under `data/evidence/`. Both `.env` and `data` are excluded from Git.

### Analysis modes

The default `ANALYSIS_ENGINE=local` uses YOLO26 pose tracking without a paid API. It records possible stroke motions but cannot reliably identify ball contacts, shot types, outcomes, or a skill score. It leaves the Vision score empty when that evidence is unavailable.

For shot and rally review, set these values in `.env` and restart the app:

```dotenv
ANALYSIS_ENGINE=gemini
GEMINI_API_KEY=your-key
GEMINI_MODEL=gemini-3.5-flash-lite
```

Each uploader must consent before the clip and player-selection frame are sent to Google. The worker normalizes video to a silent 5-fps copy and caps the provider payload at 12 MiB. The default worker handles three concurrent jobs; local video processing is serialized. Gemini requests have a separate concurrency limit of one (`PROVIDER_CONCURRENCY`). Provider failures can still delay or prevent a report. The daily provider-attempt limit is configurable with `MAX_DAILY_VIDEO_REVIEWS` (default 20).

The Vision score is a clip-performance heuristic: 50% shot control, 25% balance, and 25% recovery. Unclear events are excluded, and too little evidence produces no score. It is not a calibrated skill model.

### Recovery and reuse

- Each worker invocation sends one request. Transient failures schedule up to two automatic retries in SQLite, with backoff and a shared provider cooldown. Waiting does not occupy a worker thread, and the schedule survives restarts.
- Malformed or incomplete reports receive at most one automatic retry. Configuration errors, blocked content, and unclear player selection stop immediately. Failed clips can be retried or have their player selected again without reuploading.
- Retries keep the original model. The default read-inactivity timeout is 60 seconds (`GEMINI_READ_TIMEOUT`, constrained to 10-120); this is not an end-to-end deadline. Provider `Retry-After` delays longer than ten minutes pause automatic recovery. Each clip has a six-request lifetime cap, including manual retries.
- Identical uploads reuse a completed report only within the same account, with the exact player selection, model, prompt, schema, and scoring implementation. No video is retained for this cache. Deleted source reports are excluded; older uploads without fingerprints are not reused across uploads. Concurrent duplicates can still incur separate requests when provider concurrency exceeds one.
- The full upload expires immediately after successful analysis; opted-in report frames and replays remain until report deletion. Abandoned, failed, or waiting uploads expire after 24 hours without updates. A delayed job can be canceled and deleted.

### Analysis diagnostics

Run locally as the owner; this command is read-only and prints aggregate request outcomes, failure codes, latency, and cooldowns without user details or keys:

```sh
.venv/bin/python -m duprvision.diagnostics
```

Compare saved JSON reports for **the same clip and player**, optionally against human-reviewed shot labels:

```sh
.venv/bin/python -m duprvision.evaluate run-1.json run-2.json --labels labels.json
```

The label format is `{"shots":[{"timestamp":12.5,"shot_type":"drive"}]}`. Use a complete manually checked shot list, not model-generated labels. The evaluator reports score spread, request latency, one-to-one event precision/recall within one second, and shot-type agreement on matched events. It makes no API calls. Successful report files omit failed-attempt latency; use diagnostics for operational failures. Cached reports are useful for reuse tests, not for measuring model repeatability. No labeled accuracy benchmark is bundled yet.

## Sharing

`./scripts/share.sh` opens a temporary Cloudflare Tunnel to the running local server. Your computer must remain awake and online. Registration is open; this small-group app has no email verification, account recovery, or moderation. Share the URL only with trusted testers.

The optional `cloudflare/worker.mjs` keeps a stable Workers address in front of a changing tunnel. Copy `cloudflare/wrangler.example.jsonc` to `cloudflare/wrangler.jsonc`, configure your Cloudflare account and origin, and deploy with Wrangler. The example config is safe to commit; your account-specific config is ignored. A server that stays online is needed for uptime when your laptop is off.

## Tests

```sh
.venv/bin/python -m pytest -q
node --check static/app.js
node --test cloudflare/worker.test.mjs
```

The optional `tests/practice_ui.mjs` browser test expects Playwright, Chrome, a disposable server seeded with `tests/ui_fixture.py`, and `DUPRVISION_REPLAY_FIXTURE` pointing to a playable short MP4. It checks file matching, timestamp seeking, slow motion, note persistence, no replay uploads, cleanup, and 320/390/1440px layouts. Never seed UI fixtures in the normal app database.

The YOLO26 weights are subject to Ultralytics' licensing. Review its terms before redistribution or commercial use.

# Testing and demo recording

## Tools

Runtime dependencies live in `requirements.txt`. Install tests and lint tooling
with `requirements-dev.txt`; `npm ci` installs the pinned Playwright development
dependency from `package-lock.json`. The app itself does not need a Node build.

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
npm ci
.venv/bin/python -m pytest -q
.venv/bin/ruff check duprvision scripts tests
npm run test:edge
```

Backend tests use temporary databases and deterministic provider responses. The
YOLO smoke test is opt-in: set `DUPRVISION_POSE_SMOKE=1` and
`DUPRVISION_POSE_IMAGE=/path/to/consented-player.jpg` to run it.
Tests do not establish real-world shot-classification accuracy.

## Browser checks

Use a dedicated disposable data directory. Never seed the real application database.

```sh
PYTHONPATH=. DUPRVISION_DATA_DIR=/tmp/duprvision-ui .venv/bin/python tests/ui_fixture.py
DUPRVISION_DATA_DIR=/tmp/duprvision-ui .venv/bin/python -m uvicorn duprvision.app:app --port 3017
```

In another terminal:

```sh
node tests/navigation_ui.mjs
node tests/analyze_flow_ui.mjs
node tests/analysis_ui.mjs
node tests/connections_ui.mjs
node tests/schedule_ui.mjs
node tests/places_ui.mjs
node tests/competition_ui.mjs
```

Set `CHROME_PATH` to an installed browser executable if it is not at the default
macOS Google Chrome path. Tests accept `DUPRVISION_UI_URL` for another localhost
port. They reject non-local hosts. Reseed or use a fresh data directory for repeatable
independent runs: event/social tests intentionally mutate their fixture accounts.

Replay checks require real playable footage:

```sh
PYTHONPATH=. DUPRVISION_DATA_DIR=/tmp/duprvision-ui \
  DUPRVISION_REPLAY_FIXTURE=/path/to/clip.mp4 .venv/bin/python tests/tracked_fixture.py
DUPRVISION_REPLAY_FIXTURE=/path/to/clip.mp4 node tests/tracked_ui.mjs
DUPRVISION_REPLAY_FIXTURE=/path/to/clip.mp4 node tests/practice_ui.mjs
```

`DUPRVISION_PREVIEW_FIXTURE` can supply a JPEG for the selection-flow test. These
fixtures are test data, not demo analyses. Public map requests are intercepted.

## Record a real demo

Use a separate data directory and port, not the live app. Configure a review engine
and credentials in your private environment. The recorder submits two real analyses;
Gemini mode incurs provider calls and sends the supplied footage with consent.

Start the API and worker in separate terminals:

```sh
DUPRVISION_DATA_DIR=/tmp/duprvision-demo ANALYSIS_ENGINE=gemini \
  .venv/bin/python -m uvicorn duprvision.app:app --host 127.0.0.1 --port 3018
```

```sh
DUPRVISION_DATA_DIR=/tmp/duprvision-demo ANALYSIS_ENGINE=gemini \
  .venv/bin/python -m duprvision.worker
```

Then record:

```sh
node scripts/record_demo.mjs /path/to/1.mp4 /path/to/2.mp4 docs/demo.mp4
```

The recorder follows the real UI, saves raw captures/screenshots to a temporary
directory, and creates an H.264 MP4 with FFmpeg. It shortens idle analysis waits,
never injects scores, and fails if the review reaches a terminal failure. Player
selection coordinates are tailored to the two supplied clips; inspect and adjust
them before using unrelated footage. Review the finished video before publishing.

The current demo resumed its second report after a provider retry. The optional
`DEMO_RESUME_CAPTURE` setting accepts the original capture JSON to resume that exact
two-clip workflow and splice the recorded upload section with the completed report.
It does not create another analysis. Raw metadata stays outside the repository.

The final demo includes gameplay. Confirm publication rights separately from analysis
permission. Stop the disposable worker and API when recording is complete.

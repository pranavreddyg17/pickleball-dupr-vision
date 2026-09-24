# Analysis configuration

The API accepts uploads and selections; the worker prepares footage, runs the
configured reviewer, validates observations, computes scores, and expires media.
Reports store their scoring version. New settings do not rescore old reports.

## Configuration

Copy `.env.example` through bootstrap and change only the values you need.
Environment variables take precedence over `.env`. Restart both processes after
changing configuration.

| Variable | Default | Purpose |
| --- | --- | --- |
| `ANALYSIS_ENGINE` | `local` | `local`, `gemini`, or `self_hosted` |
| `YOLO_MODEL` | `yolo26n.pt` | Selected-player tracking weights |
| `YOLO_POSE_MODEL` | `yolo26n-pose.pt` | Local pose-review weights |
| `ANALYSIS_CONCURRENCY` | `3` | Worker job slots; local inference is serialized |
| `PROVIDER_CONCURRENCY` | `1` | Concurrent video-model jobs |
| `MAX_DAILY_VIDEO_REVIEWS` | `20` | Daily Gemini request budget, including attempts |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Cost-limited model supported by the provider adapter |
| `GEMINI_READ_TIMEOUT` | `60` | Read-inactivity seconds, constrained to 10-120 |
| `SELF_HOSTED_VLM_URL` | empty | Compatible server base URL ending in `/v1` |
| `SELF_HOSTED_VLM_MODEL` | empty | Model identifier known to that server |
| `SELF_HOSTED_VLM_REVISION` | `1` | Cache identity; change after weights/settings change |
| `SELF_HOSTED_VLM_TOKEN` | empty | Bearer token for a protected endpoint |
| `SELF_HOSTED_VLM_TIMEOUT` | `180` | Self-hosted response timeout |
| `APP_TIMEZONE` | `America/Chicago` | Reporting day and quota boundaries, not event display time |

Keep `GEMINI_API_KEY` and endpoint tokens private. Self-hosting removes a Gemini
dependency, not hardware cost, model validation, or access-control requirements.

## Footage and evidence

There is no minimum resolution gate. Portrait and landscape recordings preserve
their orientation and are not upscaled. Larger recordings are bounded to
720x1280 or 1280x720. Review copies are silent, sampled at 5 fps, and limited to
12 MiB. Local outlines identify the selected player without bridging tracking
gaps. Visible-player checks do not prove a ball contact or correct shot label.

New scores use the [V2 rubric](scoring.md). Pose-only mode deliberately abstains
from scoring shots. A compatible self-hosted model must support reference images,
base64 MP4 `video_url`, and structured JSON-schema responses. See
[vLLM's video-input documentation](https://docs.vllm.ai/en/latest/features/multimodal_inputs/)
for the protocol family; model compatibility and quality must be tested separately.

## Retry and reuse behavior

- One provider request per worker invocation. Retry waiting is persisted in SQLite
  and does not occupy an analysis thread.
- Transient failures have bounded automatic retries, backoff, and a shared
  cooldown. Invalid/incomplete responses receive at most one automatic retry.
- Invalid configuration, blocked content, and unclear selection stop immediately.
- A clip has a six-request lifetime cap, including manual retries. Manual retry
  does not change its selected model or bypass that limit.
- Provider `Retry-After` delays longer than ten minutes pause automatic recovery.
  A read timeout is not an end-to-end latency promise.
- Matching completed reviews are reused only within one account and with the same
  file fingerprint, player selection, model revision, prompt, and scoring contract.
  Deleted source reports are excluded. Recognized duplicates do not inflate progress.
- Concurrency above one can allow simultaneous identical jobs to make separate
  requests. Reuse is not a distributed exactly-once guarantee.

Failed clips can be retried or reselected while their media is available. Original
uploads expire after successful review; failed, abandoned, and waiting media expire
after 24 hours without updates. Saved private moments remain until report deletion.

## Diagnostics

Aggregate provider outcomes, latency, and cooldowns without listing keys or users:

```sh
.venv/bin/python -m duprvision.diagnostics
```

Compare saved reports for the same clip and player against human-reviewed labels:

```sh
.venv/bin/python -m duprvision.evaluate run-1.json run-2.json --labels labels.json
```

Labels use `{"shots":[{"timestamp":12.5,"shot_type":"drive"}]}`. The evaluator
matches events one-to-one within one second and reports agreement and score spread.
Cached runs are reuse tests, not evidence of independent model repeatability.

For one isolated provider request using your own footage:

```sh
PYTHONPATH=. .venv/bin/python scripts/probe_analysis.py /path/to/clip.mp4 \
  --engine self_hosted --x .35 --y .35 --output /tmp/review.json
```

For Gemini, choose `--engine gemini --external-consent`. This probe uses a temporary
database and does not automatically retry. Keep private reports outside Git.

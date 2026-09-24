# Operations

## Current deployment boundary

This is a single-host application with SQLite and local media files. Run one API
process and one worker process; the worker manages its own bounded job concurrency.
Do not point multiple machines at a shared SQLite file. POSIX process locks and
the supplied shell scripts require macOS/Linux or a compatible environment.

The codebase has tested account ownership checks, same-origin mutation checks,
upload limits, bounded provider retries, and transactional event commands. These
are useful safeguards, not a completed security audit or a public-launch guarantee.

## Always-on hosting

1. Provision an always-on host, Python 3.11, FFmpeg/FFprobe, and persistent disk.
2. Bootstrap the app and configure `.env` or a private environment file.
3. Set `DUPRVISION_DATA_DIR` to persistent storage owned by the service account.
4. Supervise the API and worker. Run only one `scripts/start.sh` instance, or manage
   its two commands separately using your service manager.
5. Terminate HTTPS at a trusted reverse proxy. Trust forwarded headers only from
   that proxy; do not expose the local origin directly to untrusted networks.
6. Set `SESSION_SECURE=true` when all user-facing requests are HTTPS.
7. Monitor health, job backlog, provider failures, disk usage, and backups.

`GET /api/health` exposes `ok`, `worker_running`, `analysis_engine`, and
`analysis_configured`. A healthy API with `worker_running=false` cannot process
uploads. Configured credentials do not guarantee that the external service is up.

The optional Cloudflare Worker is an HTTP proxy. It does not host Python, model
weights, SQLite, or video analysis. A laptop tunnel stops working when its origin
sleeps or disconnects. Use `cloudflare/wrangler.example.jsonc` as a template; keep
your account-specific configuration private. `scripts/public.py` is a local tunnel
supervisor, not an alternative to hosted infrastructure.

## Backups and retention

Back up SQLite through its online backup API or while services are stopped. Do not
copy only the main database file during active WAL writes. For a consistent restore
of reports and opted-in replays, stop both services, back up the database and
`evidence/`, then restart. Store backups encrypted with restricted access. Restore
them to an isolated data directory and test account access, reports, and events.

The repository deliberately does not commit `.env`, model weights, user data, local
service definitions, or deployment account configuration. Original uploads expire;
backups must follow a deliberate retention policy too. Never promise deletion from
old backups unless your backup policy actually implements it.

## Maps

Venue search uses Photon with a bounded one-day cache, one outbound lookup per
second per app process, and no automatic retries. The default public endpoint has
no availability guarantee. Set `PLACE_SEARCH_URL` to an appropriate hosted/private
Photon instance, or leave it empty to disable search. Manual venue entry remains.

Leaflet uses attributed OpenStreetMap tiles without offline downloads. Review
[the tile service policy](https://operations.osmfoundation.org/policies/tiles/)
and provide appropriate search/tile capacity before increasing traffic. Browser
tests intercept map tiles and search responses rather than load-test public services.

## Before public launch

- Account verification, recovery, and an account-deletion workflow.
- Abuse controls for registration, uploads, invitations, and provider spending.
- Monitoring and alerts, job-age targets, disk thresholds, and tested restore procedures.
- A security review of authentication, media processing, dependencies, and deployment.
- An explicit privacy policy and retention policy matching actual storage and providers.
- A labeled pickleball evaluation set and repeatability measurements for scored reviews.
- Load tests on the intended hardware. PostgreSQL, object storage, and a durable queue
  before multi-host scaling; see [architecture](architecture.md).

These items are not automatically satisfied by removing unused code.

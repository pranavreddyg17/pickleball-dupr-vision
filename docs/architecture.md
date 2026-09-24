# Deployment architecture

## What is implemented

The current web UI can be installed on a phone's home screen. Reports are stored as versioned structured data. The worker has three analysis modes: local pose observation, Gemini review, and owner-operated `self_hosted` review. The latter uses an OpenAI-compatible endpoint with a reference frame and bounded MP4 payload, then runs the existing evidence checks and V2 scoring locally. The worker schedules retries in SQLite and limits concurrent video-model requests. The default deployment still uses its current `.env` mode; changing the setting requires an available model server. No open-weight video model has yet been validated to match the current reviewer on pickleball footage.

## Service boundaries for a larger deployment

1. **Clients:** keep the current responsive UI as a shared product specification. Build signed iOS and Android clients around the same authenticated API, upload state, report schema, and video review controls. Home-screen installation is available now; native store packages, accessibility checks, and store review are separate deliverables.
2. **API and accounts:** move to stateless API instances behind HTTPS. Migrate users, sessions, follows, plans, and report metadata from SQLite to PostgreSQL. Preserve account IDs and report versions. Introduce standard mobile authentication and account recovery before public rollout.
3. **Media:** upload directly to private object storage through short-lived, per-user upload grants. A durable job references the object key, never video bytes in the message. Keep the current expiration rule with an independent cleanup process and measured failure recovery. Generate small selected-player frames and replays only when requested.
4. **Jobs:** use a durable managed queue. Make normalized uploads, analysis results, media deletion, and score history idempotent by video ID and model revision. Bound queue size and per-account uploads. Separate preprocessing CPU workers from GPU inference workers; use independent concurrency budgets.
5. **Inference:** run vision-capable open-weight models in a private, autoscaled serving pool. Pin model weights and preprocessing for each job. Benchmark quality, GPU memory, video length, latency, and cost before selecting capacity. A model service must emit the same structured assessment contract; clients never talk to it directly.
6. **Reports:** persist event evidence, confidence, model and rubric versions, and any user corrections. Generate short text from validated facts. Scores remain separate from official DUPR. Monitor event accuracy, abstention, retries, queue age, and end-to-end latency.

The current 100 MB limit and three-minute maximum can imply substantial temporary storage and decode work at scale. Provisioning must follow measured traffic, not registered-user count alone. At one analysis per month for one million users, average arrival rate is about 0.39 videos per second; peaks, clip lengths, and GPU service time determine the actual worker count. The existing five-uploads-per-user-per-day and global Gemini attempt budget are product and provider controls, not capacity estimates for a hosted system.

## Research and release gates

Train and evaluate a pickleball-specific contact and shot pipeline on consented recordings. Keep entire players, venues, and matches out of the training split used for final evaluation. Measure contact precision/recall, shot family accuracy, player attribution, outcome agreement, score repeatability, time per clip, and memory on the intended hardware. Compare the self-hosted model with the present reviewer and human annotations. Preserve an explicit unknown result when evidence is incomplete.

The repository uses AGPL-3.0. Audit any additional model weights, mobile SDKs, and footage before distributing them: their terms can differ from the application source. Ultralytics YOLO26 uses AGPL-3.0 unless separately licensed.

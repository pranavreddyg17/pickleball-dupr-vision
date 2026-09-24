# Local analysis: evidence before replacement

This records the local-model feasibility probes and the earlier V1 resolution fix. Current production scoring is described in [Scoring and assessment](scoring.md); the V1 score examples below are historical, not the current rubric.

## Decision

Remove the pixel-dimension scoring gate. Keep local player tracking and deterministic scoring. Preserve small-video detail, and provide the remote reviewer with the selected player's moving outline. Do not deploy a small general-purpose vision model as an automatic fallback that returns less reliable scores during a provider outage.

Allow a labeled short-sample score once there are three assessable contacts spanning five seconds, with three observations for each component. This aligns contact eligibility with component coverage instead of imposing a separate four-contact cutoff. The 50/25/25 arithmetic is unchanged. These are product eligibility rules, not validated confidence bounds; one or two contacts still do not receive a score. New reports record `contacts_v2`; old scores and averages are not rewritten.

Player visibility, ball visibility, shot classification, and outcome assessment are different tasks. A person detector cannot establish a drop shot's landing point or whether an attack was effective. Being able to track someone is a reason to attempt a review, not sufficient evidence for a skill score.

## Recording bug

The supplied 26.4-second portrait recording is 480x854. The previous landscape-shaped 1280x720 normalization shrank it below the 480-pixel cutoff. The app then rejected its own downscaled copy. Normalization and retained replays now respect orientation, with no minimum-resolution scoring gate or artificial upscaling. Encoding uses CRF 23 and an adaptive bitrate ceiling, retaining the 12 MiB provider-video cap.

## Measurements

These are small feasibility probes on an Apple M1 with 8 GB RAM, not an accuracy benchmark. The supplied footage is private and is not committed. The selected subject is the near-side left player in blue, selected at 40% of the recording.

| Candidate | Actual observation | Decision |
| --- | --- | --- |
| Qwen3.5 2B, Ollama Q4_K_M | About 1.9 GB download; 33.7 seconds for twelve images over a six-second window. Returned six unknown shots at regular timestamps and no usable score. | Keep out of the production scoring path. One configuration is not a judgment about every Qwen model. |
| sportcv-ballnet ONNX | About 7.3 MB; an evenly spaced 12-frame CPU probe averaged 56 ms per triplet, excluding decoding. Another visual spot check found several correct early ball peaks, but later peaks were unreliable. | Useful research candidate, not a validated tracker or shot classifier. No production integration. |
| Gemini default video detail, corrected dimensions | First run completed in 22.0 seconds end to end, including 5.6 seconds at the provider. One assessed shot remained after the local visibility check; no session score. | Dimension handling is fixed, but that alone does not establish sufficient shot evidence. |
| Gemini high video detail | The single probe reached the 60-second read timeout. No automatic test retries were run. | Do not enable globally or raise the timeout to hide this result. |
| Gemini with moving selected-player outline | Final captured run completed in 51.2 seconds, including 26.8 seconds at the provider, before the annotation decoder was optimized from random seeks to sequential reads. It returned three assessed contacts, all aligned with local player visibility. | Those saved observations calculate to 92/100 under the revised short-sample policy. This is not a verified accuracy result or a promised repeat score. |

Across the default-detail cloud probes, the model returned one, two, or three assessable contacts. Shot labels also varied. There is no basis to claim the outline alone improves accuracy from these few uncontrolled runs. It makes the selected subject explicit and is tested not to bridge local tracking gaps. No additional API calls were made just to force a higher score. The final recorded observations were passed through the new scoring function locally to check eligibility and arithmetic.

The [Qwen model card](https://huggingface.co/Qwen/Qwen3.5-2B) licenses the model under Apache 2.0 and describes prototyping and task-specific fine-tuning as intended uses at this scale. General vision benchmarks do not validate pickleball contacts or outcomes.

The [sportcv-ballnet model card](https://huggingface.co/CondadosAI/sportcv-ballnet) identifies Apache 2.0 weights and explicitly warns that it was trained on 396 annotated frames from one camera and match. Its published accuracy is not an estimate for this app. The linked code repository was unavailable during evaluation. The ONNX artifact takes nine channels; the probe uses consecutive BGR frames scaled by 1/255, with bottom/right padding to a multiple of 32. This preprocessing worked on some inspected moments but has not been verified against upstream source. Peaks are not automatically labeled as correct in the evaluation output.

Google's [media-resolution documentation](https://ai.google.dev/gemini-api/docs/generate-content/media-resolution?authuser=4) distinguishes default Gemini 3 video detail (roughly 70 tokens per frame) from high detail (280). Sending more pixels alone does not ensure the model uses them. Higher detail increases token usage; the measured timeout makes it inappropriate as the default here.

## Reproducible probes

Run from the repository root. Output files contain private frames and observations: keep them outside the repository. No probe writes accounts, scores, or reports into the app database.

One real app analysis, with explicit permission for one cloud request and no automatic retry loop:

```sh
PYTHONPATH=. .venv/bin/python scripts/probe_analysis.py /path/to/clip.mp4 \
  --x .35 --y .35 --external-consent --output /tmp/clip-review.json
```

The retired Ollama and ball-model probe scripts are no longer shipped. Their
measurements above are historical research notes, not supported app features.
The maintained `probe_analysis.py` exercises the actual Gemini/self-hosted path.

## Path to a dependable local pipeline

1. Build a consented, manually labeled set across portrait/landscape, indoor/outdoor courts, moving cameras, blur, overlays, and occlusions. Hold out whole venues and recordings, not adjacent frames from the same rally.
2. Evaluate a temporal ball detector with visible-ball precision/recall and pixel error. Measure false positives when the ball is absent, latency, and memory. The [WASB paper](https://arxiv.org/abs/2311.05237) is a relevant temporal heatmap baseline, not proof of pickleball accuracy.
3. Combine reliable ball tracks with player/paddle proximity to propose contacts. Reject camera cuts and tracking gaps. Manually label contacts and shot types; a trajectory alone is not an outcome label.
4. Train a small temporal classifier for pickleball-specific events. Court calibration is needed before assigning kitchen/landing zones or physical speeds. Evaluate drives versus drops and dinks on held-out footage.
5. Only after measuring quality, let local evidence supply shot counts and assessments. Generate short report text from those structured observations; make cloud coaching optional rather than the source of basic evidence.

Free weights remove per-request fees, not compute cost, labeling work, or validation requirements. No evaluated candidate currently establishes equivalent shot-review quality as a drop-in replacement, and the current remote reviewer also remains unvalidated against human ground truth.

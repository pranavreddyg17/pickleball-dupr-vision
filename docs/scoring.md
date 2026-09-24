# Scoring and assessment

## Research findings

[MyDUPRCoach's definitions](https://www.duprcoach.com/definitions) describe certified coaches assessing 18 skills and four game areas, including on-paddle and off-paddle play. Its [published skills guide](https://info.duprcoach.com/assets/files/skills-level-9d8371013349da20a58b55c5fedb91d5.pdf) emphasizes skills repeated in real games under pressure, with positioning and decisions informing the assessment. [DUPR's description of the service](https://www.dupr.com/my-dupr-coach) describes a coach-assigned initial rating after an in-person or video assessment.

Those public materials do not establish a complete reproducible point-to-rating formula for this app. DUPRVision does not implement or claim that proprietary rating system. A short automated video review cannot reproduce a credentialed coach's broader assessment without measuring agreement on independently labeled footage.

## Why the old score inflated

The earlier formula gave half its weight to binary balance and recovery checks. Three apparently clean contacts could approach 100, with no distinction between an easy ball and an effective pressured response. Mapping that number linearly to a DUPR scale added unsupported precision. The old scores are retained as historical records, not retroactively corrected.

## Vision V2

The new index remains a **clip-performance heuristic**, not an opponent-adjusted skill rating. It is intentionally separated from earlier scores. These coefficients and sample rules are product choices requiring future calibration, not industry-standard thresholds.

An event is eligible only when the ball is visible, the selected player and shot type are identified, the event lies within an observed rally, confidence is medium/high, and a nonempty visible observation is supplied. Local selected-player tracking can exclude unsupported timestamps when its coverage is adequate. Model-written evidence is inspectable but is not independent proof of correctness.

Weights:

- Shot control: 70%.
- Balance: 15%.
- Recovery: 15%.

Control credit:

| Observation | Credit |
| --- | ---: |
| Purposeful placement or effective reset under visible pressure | 1.00 |
| Purposeful routine execution | 0.75 |
| Neutral play, or claimed control with unknown pressure | 0.50 |
| Visible error | 0.00 |
| Unknown outcome | Excluded |

Balance and recovery use 1 for a positive observation, 0 for a negative observation, and exclude unclear observations. The provider is instructed not to treat merely keeping a ball in play as purposeful control.

For each component, high-confidence observations have weight 1; medium-confidence observations have weight 0.5. Its displayed value is:

```text
100 * (sum(observation_credit * observation_weight) + 6 * 0.5)
    / (sum(observation_weight) + 6)
```

The overall score is the weighted mean of displayed components, rounded to a whole number. Six neutral-weight observations reduce extreme scores from tiny samples in both directions. They are not six actual shots and do not count toward coverage or eligibility. This stabilization does not correct mislabeled shots and is not a statistical confidence interval.

Illustrative synthetic test cases, not measured player ratings:

- Three routine, purposeful shots with stable balance and recovery: 61.
- The same three executions under visible pressure: 67.
- One routine shot changed to a visible error shifts the short-sample score by six points, rather than producing a large swing.

The score needs at least three real observations for every component across five seconds. Otherwise the report provides observations without an overall score. An extended sample requires at least 12 eligible contacts, three observed rallies, and 30 seconds between first and last eligible contact. Other samples are explicitly labeled limited. Missing shot families are never treated as skill failures.

## Report structure

The short summary is accompanied by weighted components, shot outcomes by type, observed game coverage, and timestamped per-shot evidence. A local rule selects one practice focus from visible errors, late recovery, or off-balance contacts and links to up to two supporting moments. It makes no extra cloud call. If none of those issues appears, no corrective drill is invented.

Game coverage groups serve/return, groundstrokes, soft-game shots, and net exchanges. These are labels for observed shot families, not measurements of court zones, all 18 coaching skills, physical speed, spin, or partner chemistry.

## Versioning and efficiency

New reports store `performance.version = vision_score_v2`. Cached requests include the schema, prompt, scoring implementation, weights, and version. One completed response can be reused within the same account and player selection. Identical cached evidence is not counted twice in the average or trends.

Once an account has a V2 report, earlier results remain in its history but do not enter the new average. Earlier-only accounts show their earlier average explicitly labeled. No old footage is reuploaded, no existing score is overwritten, and there is no automatic paid rescore. The uncalibrated DUPR conversion is no longer shown.

The provider request still uses the existing compact model, five-frame-per-second silent video, bounded output, per-provider concurrency limit, persistent retry queue, and 12 MiB video cap. This revision adds no model service and no second opinion or retry ensemble. More restrictive evidence can result in an unscored short report; the worker does not retry a valid report simply because it lacks a score.

## Remaining validation

Sports-grade accuracy requires a held-out set of complete games reviewed independently by qualified pickleball coaches. Separate venues, players, and camera conditions between development and evaluation. Measure contact recall, shot-type agreement, outcome agreement, repeated-run variation, and agreement with coach assessments. Calibrate weights and stabilization only against that evidence. Until then, do not describe V2 as an official DUPR, a MyDUPRCoach clone, or a validated replacement for coaching.

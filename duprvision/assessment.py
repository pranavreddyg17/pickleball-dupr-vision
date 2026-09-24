"""Evidence-weighted clip assessment. This index is not a calibrated skill rating."""
from collections import Counter
from typing import Literal

from pydantic import Field

from .performance import CompactReview, Event, PROMPT as BASE_PROMPT, validate_performance

VERSION = 'vision_score_v2'
PRIOR_WEIGHT = 6
WEIGHTS = (.70, .15, .15)
AREAS = (
    ('Serve & return', ('serve', 'return')),
    ('Groundstrokes', ('drive', 'lob')),
    ('Soft game', ('drop', 'dink')),
    ('Net exchanges', ('volley', 'overhead')),
)


class AssessedEvent(Event):
    pressure: Literal['routine', 'pressured', 'unknown']
    evidence: str = Field(max_length=110)


class Assessment(CompactReview):
    shots: list[AssessedEvent] = Field(max_length=40)


PROMPT = BASE_PROMPT + """
For each shot, give one short visible observation in evidence (under 110 characters).
Describe the ball's placement or outcome and relevant footwork, not a rating or praise.
If you cannot see supporting evidence, leave evidence empty and use unknown/null values.
pressure: routine = player has time and a stable contact zone; pressured = visibly rushed,
stretched or defending a fast incoming attack; unknown = incoming context not visible.
A routine shot kept in play is neutral, not automatically controlled. Controlled requires
visible purposeful placement, pressure created, or a reset that actually neutralizes attack.
Do not infer pressure from a shot name, reputation, camera speed, or general appearance.
Balance and readiness are supporting observations, not evidence of advanced skill.
Missing shot families are unobserved, not weaknesses. Evaluate repeatability, not highlights.
The practice priority must address a visible issue supported by a listed shot's evidence.
Leave priority empty if no specific correction is supported; do not invent one.
"""


def validate_assessment(raw, duration):
    review = Assessment.model_validate(raw)
    base = review.model_dump()
    base['shots'] = [{key: value for key, value in shot.items() if key not in ('pressure', 'evidence')}
                     for shot in base['shots']]
    # Keep the established timestamp, rally and player validation for archived compatibility.
    result = validate_performance(base, duration)
    shots = sorted(review.shots, key=lambda shot: shot.timestamp)
    reliable = [shot for shot in shots if review.ball_visible and shot.confidence != 'low'
                and shot.shot_type != 'unknown' and len(shot.evidence.strip()) >= 12
                and any(r.start <= shot.timestamp <= r.end for r in review.rallies)]
    values = [[], [], []]
    for shot in reliable:
        weight = 1.0 if shot.confidence == 'high' else .5
        control = {'neutral':.5, 'error':0}.get(shot.control)
        if shot.control == 'controlled':
            control = {'routine':.75, 'pressured':1, 'unknown':.5}[shot.pressure]
        for bucket, value in zip(values, (control, shot.balanced, shot.recovered)):
            if value is not None:
                bucket.append((float(value), weight))
    components = []
    for name, samples, weight in zip(('Shot control', 'Balance', 'Recovery'), values, WEIGHTS):
        mass = sum(w for _, w in samples)
        earned = sum(value * w for value, w in samples)
        components.append({'name':name, 'value':round(100 * (earned + PRIOR_WEIGHT / 2) /
                           (mass + PRIOR_WEIGHT), 1) if samples else None,
                           'observed_value':round(100 * earned / mass, 1) if mass else None,
                           'observations':len(samples), 'effective_observations':mass, 'weight':weight})
    span = reliable[-1].timestamp - reliable[0].timestamp if reliable else 0
    sufficient = span >= 5 and all(c['observations'] >= 3 for c in components)
    score = round(sum(c['value'] * c['weight'] for c in components)) if sufficient else None
    observed_rallies = sum(any(r.start <= shot.timestamp <= r.end for shot in reliable)
                           for r in review.rallies)
    broad_sample = len(reliable) >= 12 and observed_rallies >= 3 and span >= 30
    sample = 'extended' if broad_sample else 'short'
    note = 'Extended sample' if broad_sample else 'Limited sample'
    if score is None:
        note = 'A score needs three evidenced observations per component across five seconds of play.'
    by_type = {}
    for shot in reliable:
        if shot.control != 'unknown':
            by_type.setdefault(shot.shot_type, Counter())[shot.control] += 1
    practice = None
    patterns = [
        ('Shot margin', [s for s in reliable if s.control == 'error'],
         'Visible shot errors', 'Repeat the affected shot at controlled pace with a larger target before adding speed.'),
        ('Recovery', [s for s in reliable if s.recovered is False],
         'Late recovery', 'Return to a ready position after each contact before your practice partner feeds the next ball.'),
        ('Contact balance', [s for s in reliable if s.balanced is False],
         'Off-balance contact', 'Use short adjustment steps to establish a stable base; increase pace only while that base holds.'),
    ]
    title, moments, observation, exercise = max(patterns, key=lambda item: len(item[1]))
    if moments:
        practice = {'title':title, 'observation':f'{observation} observed at {len(moments)} ' +
                    ('contacts.' if len(moments) != 1 else 'contact.'),
                    'exercise':exercise, 'timestamps':[s.timestamp for s in moments[:2]]}
    saved_shots = []
    for shot in shots:
        saved = shot.model_dump()
        saved['scored'] = shot in reliable
        if not review.ball_visible:
            saved.update(shot_type='unknown', confidence='low', control='unknown',
                         balanced=None, recovered=None, pressure='unknown', evidence='')
        saved_shots.append(saved)
    result.update(shots=saved_shots,
                  shot_counts=dict(Counter(shot.shot_type for shot in reliable)),
                  uncertain_shots=len(shots) - len(reliable),
                  shot_breakdown=[{'type':name, 'assessed':sum(counts.values()),
                                   'controlled':counts['controlled'], 'neutral':counts['neutral'],
                                   'errors':counts['error']} for name, counts in sorted(by_type.items())],
                  game_areas=[{'name':name, 'observations':sum(s.shot_type in types for s in reliable)}
                              for name, types in AREAS],
                  practice=practice,
                  performance={'version':VERSION, 'score':score, 'components':components,
                               'sample_scope':sample, 'observed_shots':len(reliable), 'note':note,
                               'prior_weight':PRIOR_WEIGHT,
                               'evidence':{'reported':len(shots), 'assessed':len(reliable),
                                           'rallies':observed_rallies, 'span_seconds':round(span, 1),
                                           'high_confidence':sum(s.confidence == 'high' for s in reliable)}})
    return result

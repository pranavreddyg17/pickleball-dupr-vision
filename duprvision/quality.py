"""Cheap recording and selected-player evidence checks."""
import bisect
import math

from .performance import validate_performance


def capture_quality(path):
    import cv2

    capture = cv2.VideoCapture(str(path))
    try:
        width = round(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = capture.get(cv2.CAP_PROP_FPS)
    finally:
        capture.release()
    if not width or not height:
        return None
    return {'width': width, 'height': height, 'fps': round(fps, 1)}


def reconcile_track(report, tracked, duration):
    """Use a visible selected player as a necessary, never sufficient, shot check."""
    if report.get('kind') != 'video_review_v2' or not tracked:
        return report
    expected = max(1, math.ceil(duration * 5))
    times = [sample[0] for sample in tracked]
    coverage = min(1.0, len(times) / expected)
    alignments = []
    for shot in report.get('shots', []):
        t = float(shot['timestamp'])
        index = bisect.bisect_left(times, t)
        distance = min((abs(times[i] - t) for i in (index-1, index) if 0 <= i < len(times)), default=float('inf'))
        aligned = distance <= .3
        shot['player_visible'] = aligned
        alignments.append(aligned)
    status = 'checked' if coverage >= .6 else 'limited'
    report['tracking_check'] = {'version': 1, 'status': status,
                                'coverage': round(coverage, 2),
                                'aligned_shots': sum(alignments), 'reported_shots': len(alignments)}
    if status != 'checked' or all(alignments) or 'ball_visible' not in report:
        return report
    raw = {field: report[field] for field in
           ('subject_identified', 'ball_visible', 'summary', 'priority', 'recording_note', 'rallies')}
    raw['shots'] = [{key:value for key,value in shot.items() if key not in ('player_visible', 'scored')}
                    for shot in report['shots']]
    for shot, aligned in zip(raw['shots'], alignments):
        if not aligned:
            shot.update(shot_type='unknown', confidence='low', control='unknown', balanced=None, recovered=None)
    had_score = report.get('performance', {}).get('score') is not None
    if report.get('performance', {}).get('version') == 'vision_score_v2':
        from .assessment import validate_assessment
        revised = validate_assessment(raw, duration)
        report['game_areas'] = revised['game_areas']
        report['practice'] = revised['practice']
    else:
        revised = validate_performance(raw, duration)
    for name in ('shot_counts', 'shot_breakdown', 'uncertain_shots', 'performance'):
        report[name] = revised[name]
    for original, assessed in zip(report['shots'], revised['shots']):
        if not original['player_visible']:
            original.update(assessed)
    if had_score and report['performance']['score'] is None:
        report['performance']['note'] = 'Selected-player tracking did not support enough reported contacts for a score.'
    return report

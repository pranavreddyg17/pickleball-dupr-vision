"""Descriptive daily trends from saved reports, with no additional model calls."""
import json
import math
from datetime import datetime
from zoneinfo import ZoneInfo
import os


def progress_history(db, user_id):
    rows = db.execute("""SELECT v.created_at,a.result_json,k.cache_key FROM videos v
        JOIN analyses a ON a.video_id=v.id LEFT JOIN review_cache_keys k ON k.video_id=v.id
        WHERE v.user_id=? AND v.status='COMPLETED' ORDER BY v.created_at,v.id""", (user_id,)).fetchall()
    days, seen = {}, set()
    names = ('Shot control', 'Balance', 'Recovery')
    for row in rows:
        report = json.loads(row['result_json'])
        performance = report.get('performance', {})
        score = performance.get('score')
        if report.get('kind') != 'video_review_v2' or performance.get('version') != 'vision_score_v1':
            continue
        if not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 100:
            continue
        # Reuploads of the same analyzed evidence are not new progress observations.
        key = row['cache_key']
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        date = report.get('score_date') or datetime.fromisoformat(row['created_at']).astimezone(
            ZoneInfo(os.getenv('APP_TIMEZONE', 'America/Chicago'))).date().isoformat()
        day = days.setdefault(date, {'scores': [], 'components': {name: [] for name in names}})
        day['scores'].append(score)
        for component in performance.get('components', []):
            name, value, count = component.get('name'), component.get('value'), component.get('observations', 0)
            if name in names and isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value <= 100 and count > 0:
                day['components'][name].append((value, count))
    series = []
    for date, day in sorted(days.items()):
        components = {}
        for name, values in day['components'].items():
            count = sum(n for _, n in values)
            components[name] = sum(v*n for v, n in values)/count if count else None
        series.append({'date': date, 'score': round(sum(day['scores'])/len(day['scores']), 1), 'components': components})
    recent, previous = series[-5:], series[-10:-5]

    def metric(name):
        def values(window):
            return [d['score'] if name == 'Vision score' else d['components'][name] for d in window
                    if name == 'Vision score' or d['components'][name] is not None]
        current, prior = values(recent), values(previous)
        mean = lambda data: sum(data)/len(data) if data else None
        delta = round(mean(current)-mean(prior), 1) if len(current) >= 3 and len(prior) >= 3 else None
        return {'name': name, 'value': round(mean(current), 1) if current else None, 'delta': delta,
                'recent_days': len(current), 'previous_days': len(prior)}

    return {'days': [{'date': d['date'], 'score': d['score']} for d in series[-10:]],
            'recent_days': len(recent), 'previous_days': len(previous),
            'metrics': [metric(name) for name in ('Vision score', *names)]}

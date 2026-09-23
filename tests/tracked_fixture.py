"""Add locally tracked sample footage to the disposable browser fixture, without API calls."""
import hashlib
import json
import os
from pathlib import Path

import cv2

from duprvision import core
from duprvision.evidence import build_evidence, serialize_track, track_player

if not os.environ.get('DUPRVISION_DATA_DIR') or core.DATA.resolve() == (core.ROOT / 'data').resolve():
    raise SystemExit('Use a disposable DUPRVISION_DATA_DIR')
source = Path(os.environ['DUPRVISION_REPLAY_FIXTURE'])
capture = cv2.VideoCapture(str(source))
duration = capture.get(cv2.CAP_PROP_FRAME_COUNT) / capture.get(cv2.CAP_PROP_FPS)
capture.release()
row = {'id': 'qa-local-0', 'normalized_path': str(source), 'duration_seconds': duration}
selection = {'timestamp_seconds': duration * .4, 'x': .43, 'y': .51}
with core.connect() as db:
    report = json.loads(db.execute('SELECT result_json FROM analyses WHERE video_id=?', (row['id'],)).fetchone()[0])
report['shots'] = [
    {'timestamp': 12, 'shot_type': 'drive', 'confidence': 'medium', 'control': 'neutral', 'balanced': True, 'recovered': True},
    {'timestamp': 17, 'shot_type': 'drop', 'confidence': 'medium', 'control': 'error', 'balanced': False, 'recovered': False},
]
tracked = track_player(row, selection)
report['player_track'] = serialize_track(row, tracked)
report['evidence'] = build_evidence(row, report, tracked, keep_clips=True)
assert report['evidence'] and all(m.get('clip') for m in report['evidence'])
with core.connect() as db:
    db.execute('UPDATE analyses SET result_json=? WHERE video_id=?', (json.dumps(report), row['id']))
    db.execute('UPDATE videos SET duration_seconds=? WHERE id=?', (duration, row['id']))
    db.execute('INSERT OR REPLACE INTO video_fingerprints VALUES (?,?)', (row['id'], hashlib.sha256(source.read_bytes()).hexdigest()))
print(json.dumps({'tracked_frames':len(tracked), 'moments':report['evidence']}))

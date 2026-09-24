import json
import subprocess

import cv2

from duprvision import core
from duprvision.evidence import build_evidence, serialize_track, review_track_video
from test_flow import add_result


def test_provider_overlay_preserves_timeline_and_leaves_gaps(tmp_path):
    source = tmp_path / 'sample.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=gray:s=160x240:r=30:d=2',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(source)], check=True)
    row = {'normalized_path':str(source), 'duration_seconds':2.05}
    output = tmp_path / 'tracked.mp4'
    tracked = [(i / 5, [40, 30, 100, 190]) for i in range(5)]
    assert review_track_video(row, tracked, output)
    capture = cv2.VideoCapture(str(output))
    try:
        assert capture.get(cv2.CAP_PROP_FPS) == 5
        assert capture.get(cv2.CAP_PROP_FRAME_COUNT) == 10
        capture.set(cv2.CAP_PROP_POS_MSEC, 400)
        ok, marked = capture.read()
        assert ok
        capture.set(cv2.CAP_PROP_POS_MSEC, 1400)
        ok, gap = capture.read()
        assert ok
        def green_pixels(frame):
            b, g, r = cv2.split(frame.astype('int16'))
            return ((g > r + 30) & (g > b + 30)).sum()
        assert green_pixels(marked) > 100
        assert green_pixels(gap) == 0
    finally:
        capture.release()
    assert not review_track_video(row, [], tmp_path / 'empty.mp4')


def test_saved_replays_are_bounded_and_optional(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DATA', tmp_path)
    source = tmp_path / 'sample.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=gray:s=320x180:r=30:d=8',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(source)], check=True)
    row = {'id':'sample', 'normalized_path':str(source), 'duration_seconds':8}
    tracked = [(i / 5, [60, 30, 100, 120]) for i in range(40)]
    report = {'shots':[{'timestamp':t,'shot_type':'drive','confidence':'high'} for t in (1,3,6)]}
    stills = build_evidence(row, report, tracked)
    assert len(stills) == 3 and all('clip' not in m for m in stills)
    assert not list(core.evidence_dir('sample').glob('*.mp4'))
    moments = build_evidence(row, report, tracked, keep_clips=True)
    assert len(moments) == 3
    for moment in moments:
        assert 0 <= moment['clip']['start'] < moment['clip']['end'] <= 8
        video = cv2.VideoCapture(str(core.evidence_dir('sample') / f"{moment['number']}.mp4"))
        assert video.isOpened()
        assert video.get(cv2.CAP_PROP_FRAME_COUNT) / video.get(cv2.CAP_PROP_FPS) <= 6.1
        assert video.get(cv2.CAP_PROP_FRAME_WIDTH) == 320
        video.release()
    manifest = serialize_track(row, tracked)
    assert all(len(s) == 5 and all(0 <= n <= 1 for n in s[1:]) for s in manifest['samples'])


def test_replay_requires_manifest_and_owner_and_supports_seeking(clients):
    a, b = clients
    add_result(a.get('/api/me').json()['id'], 'replay', 70, core.iso())
    folder = core.evidence_dir('replay')
    folder.mkdir(parents=True)
    (folder / '1.mp4').write_bytes(b'0123456789')
    url = '/api/videos/replay/evidence/1/clip'
    assert a.get(url).status_code == 404
    with core.connect() as db:
        db.execute('UPDATE analyses SET result_json=? WHERE video_id=?',
                   (json.dumps({'evidence':[{'number':1,'clip':{'start':0,'end':6}}]}), 'replay'))
    assert b.get(url).status_code == 404
    response = a.get(url, headers={'Range':'bytes=2-5'})
    assert response.status_code == 206 and response.content == b'2345'
    assert response.headers['cache-control'] == 'private, no-store'
    core.expire_media('replay')
    assert a.get(url).status_code == 200
    assert a.delete('/api/videos/replay').status_code == 200
    assert not folder.exists() and a.get(url).status_code == 404

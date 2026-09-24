import subprocess
import pytest

from duprvision import core, review, worker
from duprvision.evidence import save_replay
from duprvision.performance import validate_performance
from duprvision.quality import capture_quality, reconcile_track
from test_flow import compact_review, make_video


def test_tracking_gap_changes_only_unsupported_observation():
    original = validate_performance(compact_review(), 60)
    samples = [(round(i / 5, 1), (10, 10, 100, 180)) for i in range(300)
               if not 1.6 <= i / 5 <= 2.4]
    result = reconcile_track(original, samples, 60)
    assert result['tracking_check'] == {'version':1, 'status':'checked', 'coverage':.98,
                                         'aligned_shots':7, 'reported_shots':8}
    assert result['shots'][0]['player_visible'] is False
    assert result['shots'][0]['shot_type'] == 'unknown'
    assert result['shots'][0]['control'] == 'unknown'
    assert result['shots'][1]['shot_type'] == 'dink'
    assert result['performance']['observed_shots'] == 7
    assert result['performance']['score'] != 63
    assert result['shot_counts'] == {'dink':7}
    assert result['shot_breakdown'][0]['assessed'] == 7
    assert result['uncertain_shots'] == 1


def test_weak_tracking_does_not_rewrite_model_report():
    original = validate_performance(compact_review(), 60)
    result = reconcile_track(original, [(4.0, (10, 10, 100, 180))], 60)
    assert result['tracking_check']['status'] == 'limited'
    assert result['performance']['score'] == 63
    assert result['shots'][0]['shot_type'] == 'dink'


def test_short_sample_explains_missing_score_without_blaming_resolution():
    raw = compact_review()
    raw['shots'] = raw['shots'][:2]
    result = validate_performance(raw, 60)
    assert result['performance']['score'] is None
    assert result['performance']['note'] == '2 assessed contacts. At least 3 are needed for a session score.'
    result = reconcile_track(result, [(i / 5, (10,10,100,180)) for i in range(300)
                                      if not 1.6 <= i / 5 <= 2.4], 60)
    assert result['performance']['note'] == '1 assessed contact. At least 3 are needed for a session score.'


def test_short_sample_needs_three_complete_assessments_over_five_seconds():
    raw = compact_review()
    raw['shots'] = raw['shots'][:3]
    result = validate_performance(raw, 60)
    assert result['performance']['score'] is not None
    assert result['performance']['sample_scope'] == 'short'
    assert result['performance']['eligibility_version'] == 'contacts_v2'
    assert result['performance']['note'] == 'Short sample: 3 assessed shots.'
    raw['shots'][0]['recovered'] = None
    assert validate_performance(raw, 60)['performance']['score'] is None
    raw['shots'][0]['recovered'] = True
    raw['shots'][2]['timestamp'] = 5
    assert validate_performance(raw, 60)['performance']['score'] is None


def test_small_clip_receives_full_review_with_consent(clients, tmp_path, monkeypatch):
    client, _ = clients
    monkeypatch.setenv('ANALYSIS_ENGINE', 'gemini')
    monkeypatch.setenv('GEMINI_API_KEY', 'test-not-real')
    source = tmp_path/'tiny.mp4'
    make_video(source, seconds=60, dimensions='144x256')
    response = client.post('/api/videos', content=source.read_bytes(), headers={'X-Filename':'tiny.mp4'})
    assert response.status_code == 200
    video_id = response.json()['id']
    with core.connect() as db:
        row = dict(db.execute('SELECT * FROM videos WHERE id=?', (video_id,)).fetchone())
    worker.process(row)
    selection = {'timestamp_seconds':24, 'x':.5, 'y':.5, 'consent':True, 'save_evidence':False}
    assert client.post(f'/api/videos/{video_id}/select', json=selection).status_code == 400
    response = client.post(f'/api/videos/{video_id}/select', json={**selection, 'external_consent':True})
    assert response.status_code == 200, response.text
    with core.connect() as db:
        assert db.execute('SELECT engine FROM analysis_options WHERE video_id=?', (video_id,)).fetchone()[0] == 'gemini'
    monkeypatch.setattr(worker, 'track_player', lambda *args: [])
    monkeypatch.setattr(worker, 'marked_reference', lambda *args: None)
    calls = []
    def review(*args):
        calls.append(args)
        return validate_performance(compact_review(), 60)
    monkeypatch.setattr(worker, 'gemini_review', review)
    row = worker.claim_next()
    assert row['id'] == video_id
    worker.process(row)
    report = client.get(f'/api/videos/{video_id}').json()
    assert report['status'] == 'COMPLETED'
    assert report['result']['performance']['score'] == 63
    assert report['result']['capture_quality'] == {'width':144,'height':256,'fps':30.0}
    assert len(calls) == 1 and calls[0][2] is True


@pytest.mark.parametrize('dimensions,expected', [('144x256',(144,256)),('480x854',(480,854)),
                                                ('854x480',(854,480)),('1080x1920',(720,1280))])
def test_normalization_preserves_portrait_and_small_clips(tmp_path, monkeypatch, dimensions, expected):
    monkeypatch.setattr(core, 'DATA', tmp_path)
    monkeypatch.setattr(core, 'DB', tmp_path/'duprvision.sqlite3')
    monkeypatch.setattr(worker, 'update', lambda *args, **kwargs: None)
    folder = core.video_dir('small')
    folder.mkdir(parents=True)
    raw = folder/'original.mp4'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i',
                    f'color=c=green:s={dimensions}:r=30:d=2','-c:v','libx264',str(raw)],check=True)
    worker.normalize({'id':'small','raw_path':str(raw),'duration_seconds':2})
    quality = capture_quality(folder/'normalized.mp4')
    assert (quality['width'], quality['height']) == expected
    assert quality['fps'] == 30.0
    assert not raw.exists()


def test_legacy_local_only_job_requires_fresh_choice(clients, monkeypatch):
    from test_flow import add_result
    client, _ = clients
    add_result(client.get('/api/me').json()['id'], 'old-limited', None, core.iso())
    with core.connect() as db:
        db.execute("UPDATE videos SET status='QUEUED' WHERE id='old-limited'")
        db.execute("INSERT INTO selections VALUES ('old-limited',12,.5,.5)")
        db.execute("INSERT INTO analysis_options VALUES ('old-limited','limited',0)")
    monkeypatch.setattr(worker, 'gemini_review', lambda *args: (_ for _ in ()).throw(AssertionError('no consent')))
    worker.process(worker.claim_next())
    assert client.get('/api/videos/old-limited').json()['status'] == 'WAITING_FOR_PLAYER'


def test_portrait_provider_copy_and_replay_retain_detail(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DATA', tmp_path)
    source = tmp_path / 'portrait.mp4'
    make_video(source, seconds=7, dimensions='480x854')
    row = {'id':'portrait', 'normalized_path':str(source), 'duration_seconds':7}
    output = tmp_path / 'review.mp4'
    review.encode_review(row, output)
    assert capture_quality(output) == {'width':480, 'height':854, 'fps':5.0}
    assert output.stat().st_size <= 12 * 1024 * 1024
    core.evidence_dir('portrait').mkdir(parents=True)
    assert save_replay(row, 3, 1) == {'start':1, 'end':7, 'fps':30}
    assert capture_quality(core.evidence_dir('portrait') / '1.mp4') == {
        'width':480, 'height':854, 'fps':30.0}


def test_provider_encoding_rejects_oversize_output(tmp_path, monkeypatch):
    output = tmp_path / 'oversize.mp4'
    def encode(*args, **kwargs):
        with output.open('wb') as file:
            file.truncate(12 * 1024 * 1024 + 1)
    monkeypatch.setattr(review.subprocess, 'run', encode)
    with pytest.raises(RuntimeError, match='size limit'):
        review.encode_review({'normalized_path':'fixture', 'duration_seconds':180}, output)


def test_annotation_failure_falls_back_without_another_request(tmp_path, monkeypatch):
    from duprvision import evidence
    output = tmp_path / 'review.mp4'
    def broken(*args):
        raise OSError('codec unavailable')
    monkeypatch.setattr(evidence, 'review_track_video', broken)
    sources = []
    monkeypatch.setattr(review, '_encode_review', lambda row, output, source: sources.append(source))
    assert review.encode_review({'normalized_path':'original.mp4'}, output, [(0,[0,0,10,10])]) is False
    assert sources == ['original.mp4']
    assert not output.with_name('review-tracked-source.mp4').exists()

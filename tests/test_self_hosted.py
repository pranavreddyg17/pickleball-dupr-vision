import json
from datetime import timedelta

import httpx
import pytest

from duprvision import core, review, worker
from test_flow import add_result, compact_assessment


def setup_review(clients, monkeypatch, responses):
    client, _ = clients
    uid = client.get('/api/me').json()['id']
    add_result(uid, 'self-hosted-clip', None, core.iso())
    folder = core.video_dir('self-hosted-clip')
    folder.mkdir()
    (folder / 'preview-1.jpg').write_bytes(b'frame')
    monkeypatch.setenv('ANALYSIS_ENGINE', 'self_hosted')
    monkeypatch.setenv('SELF_HOSTED_VLM_URL', 'http://127.0.0.1:8000/v1')
    monkeypatch.setenv('SELF_HOSTED_VLM_MODEL', 'test-video-model')
    monkeypatch.setenv('SELF_HOSTED_VLM_REVISION', '1')
    monkeypatch.delenv('SELF_HOSTED_VLM_TOKEN', raising=False)
    def encode(row, path, track):
        path.write_bytes(b'video')
        return False
    monkeypatch.setattr(review, 'encode_review', encode)
    calls = []

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, **kwargs):
            calls.append((url, kwargs))
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

    monkeypatch.setattr(review.httpx, 'Client', Client)
    row = {'id':'self-hosted-clip', 'duration_seconds':60, 'normalized_path':'unused.mp4'}
    selection = {'timestamp_seconds':6, 'x':.5, 'y':.5}
    return row, selection, calls


def completion():
    return httpx.Response(200, json={'choices':[{'finish_reason':'stop',
        'message':{'content':json.dumps(compact_assessment())}}], 'usage':{'total_tokens':75}})


def test_keyless_self_hosted_review_uses_existing_report_contract(clients, monkeypatch):
    row, selection, calls = setup_review(clients, monkeypatch, [completion()])
    result = review.self_hosted_review(row, selection)
    assert result['kind'] == 'video_review_v2'
    assert result['performance']['version'] == 'vision_score_v2'
    assert result['performance']['score'] == 54
    assert result['model'] == 'self_hosted:test-video-model:1'
    assert calls[0][0] == 'http://127.0.0.1:8000/v1/chat/completions'
    payload = calls[0][1]['json']
    assert payload['model'] == 'test-video-model'
    assert payload['messages'][0]['content'][2]['type'] == 'video_url'
    assert payload['response_format']['type'] == 'json_schema'
    assert calls[0][1]['headers'] == {}
    assert review.self_hosted_review(row, selection)['performance']['score'] == 54
    assert len(calls) == 1


def test_self_hosted_service_retry_is_bounded(clients, monkeypatch):
    row, selection, calls = setup_review(clients, monkeypatch, [httpx.Response(503), completion()])
    with pytest.raises(review.RetryableReviewError):
        review.self_hosted_review(row, selection)
    assert review.self_hosted_review(row, selection)['performance']['score'] == 54
    with core.connect() as db:
        assert [r[0] for r in db.execute('SELECT status FROM provider_requests ORDER BY id')] == ['retryable','succeeded']
    assert len(calls) == 2


def test_self_hosted_config_and_admission(clients, monkeypatch):
    client, _ = clients
    monkeypatch.setenv('ANALYSIS_ENGINE', 'self_hosted')
    monkeypatch.delenv('SELF_HOSTED_VLM_URL', raising=False)
    monkeypatch.delenv('SELF_HOSTED_VLM_MODEL', raising=False)
    assert client.get('/api/health').json()['analysis_configured'] is False
    monkeypatch.setenv('SELF_HOSTED_VLM_URL', 'http://127.0.0.1:8000/v1')
    monkeypatch.setenv('SELF_HOSTED_VLM_MODEL', 'test-video-model')
    assert client.get('/api/health').json()['analysis_configured'] is True
    assert client.get('/manifest.webmanifest').json()['display'] == 'standalone'
    assert client.get('/app-icon-192.png').headers['content-type'] == 'image/png'
    uid = client.get('/api/me').json()['id']
    add_result(uid, 'queued-self', None, core.iso())
    with core.connect() as db:
        db.execute("UPDATE videos SET status='QUEUED' WHERE id='queued-self'")
        db.execute("INSERT INTO analysis_options VALUES ('queued-self','self_hosted',0)")
        db.execute("INSERT INTO analysis_jobs(video_id,model) VALUES ('queued-self','test-video-model')")
        db.execute("INSERT INTO provider_health VALUES ('self_hosted',?)", (core.iso(core.now() + timedelta(minutes=5)),))
    assert worker.claim_next() is None
    with core.connect() as db:
        db.execute("DELETE FROM provider_health WHERE name='self_hosted'")
    assert worker.claim_next()['id'] == 'queued-self'


def test_self_hosted_queue_respects_inference_capacity(clients, monkeypatch):
    client, _ = clients
    monkeypatch.setenv('PROVIDER_CONCURRENCY', '1')
    uid = client.get('/api/me').json()['id']
    for video_id, status in (('already-running', 'ANALYZING'), ('needs-review', 'QUEUED')):
        add_result(uid, video_id, None, core.iso())
        with core.connect() as db:
            db.execute('UPDATE videos SET status=? WHERE id=?', (status, video_id))
            db.execute('INSERT INTO analysis_options VALUES (?,?,0)', (video_id, 'self_hosted'))
    assert worker.claim_next() is None
    with core.connect() as db:
        db.execute("UPDATE videos SET status='COMPLETED' WHERE id='already-running'")
    assert worker.claim_next()['id'] == 'needs-review'

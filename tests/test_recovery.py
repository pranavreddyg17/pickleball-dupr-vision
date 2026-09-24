import json
from datetime import timedelta

import httpx
import pytest

from duprvision import core, review, worker
from duprvision.evaluate import compare_events, summarize
from test_flow import add_result
from test_reliability import prepare_provider, success


def queue_provider(row, selection):
    with core.connect() as db:
        db.execute("DELETE FROM analyses WHERE video_id=?", (row['id'],))
        db.execute("UPDATE videos SET status='QUEUED',normalized_path=? WHERE id=?", (row['normalized_path'], row['id']))
        db.execute("INSERT INTO selections VALUES (?,?,?,?)", (row['id'], *selection.values()))
        db.execute("INSERT INTO analysis_options VALUES (?,'gemini',1)", (row['id'],))


def make_due():
    with core.connect() as db:
        db.execute("UPDATE analysis_jobs SET next_attempt_at=?", (core.iso(core.now()-timedelta(seconds=1)),))
        db.execute("DELETE FROM provider_health")


def test_scheduled_recovery_survives_restart(clients, monkeypatch):
    row, selection, calls = prepare_provider(clients, monkeypatch, [httpx.Response(503), success()])
    queue_provider(row, selection)
    worker.process(worker.claim_next())
    assert len(calls) == 1
    assert clients[0].get('/api/videos/outage').json()['status'] == 'RETRY_WAIT'
    assert worker.claim_next() is None
    core.init_db()
    worker.recover_interrupted()
    assert worker.claim_next() is None
    make_due()
    worker.process(worker.claim_next())
    assert clients[0].get('/api/videos/outage').json()['status'] == 'COMPLETED'
    assert len(calls) == 2
    assert not core.video_dir('outage').exists()


@pytest.mark.parametrize('failure,attempts', [(httpx.Response(503), 3), (httpx.Response(200, json={}), 2)])
def test_retries_are_bounded(clients, monkeypatch, failure, attempts):
    row, selection, calls = prepare_provider(clients, monkeypatch, [failure] * attempts)
    queue_provider(row, selection)
    for _ in range(attempts):
        make_due()
        worker.process(worker.claim_next())
    assert len(calls) == attempts
    assert clients[0].get('/api/videos/outage').json()['status'] == 'FAILED'
    assert worker.claim_next() is None


def test_cooldown_does_not_block_video_preparation(clients, monkeypatch):
    row, selection, _ = prepare_provider(clients, monkeypatch, [httpx.Response(429)])
    queue_provider(row, selection)
    worker.process(worker.claim_next())
    add_result(clients[0].get('/api/me').json()['id'], 'prepare', None, core.iso())
    with core.connect() as db:
        db.execute("UPDATE videos SET status='PROCESSING' WHERE id='prepare'")
    assert worker.claim_next()['id'] == 'prepare'


def test_provider_concurrency_is_separate(clients, monkeypatch):
    monkeypatch.setenv('PROVIDER_CONCURRENCY', '1')
    uid = clients[0].get('/api/me').json()['id']
    for name in ('first', 'second'):
        add_result(uid, name, None, core.iso())
        with core.connect() as db:
            db.execute("UPDATE videos SET status='QUEUED' WHERE id=?", (name,))
            db.execute("INSERT INTO analysis_options VALUES (?,'gemini',1)", (name,))
    assert worker.claim_next() is not None
    assert worker.claim_next() is None


def test_duplicate_cache_is_account_player_and_model_scoped(clients, monkeypatch):
    row, selection, calls = prepare_provider(clients, monkeypatch, [success()])
    uid = clients[0].get('/api/me').json()['id']
    with core.connect() as db:
        db.execute("INSERT INTO video_fingerprints VALUES ('outage','same-file')")
    result = review.gemini_review(row, selection, True)
    with core.connect() as db:
        db.execute("UPDATE analyses SET result_json=? WHERE video_id='outage'", (json.dumps(result),))
    add_result(uid, 'duplicate', None, core.iso())
    other_uid = clients[1].get('/api/me').json()['id']
    add_result(other_uid, 'other-account', None, core.iso())
    with core.connect() as db:
        for name in ('duplicate', 'other-account'):
            db.execute("INSERT INTO video_fingerprints VALUES (?,'same-file')", (name,))
        original = review.cache_key(db, 'outage', selection, 'gemini-3.1-flash-lite')
        assert original == review.cache_key(db, 'duplicate', selection, 'gemini-3.1-flash-lite')
        assert original != review.cache_key(db, 'other-account', selection, 'gemini-3.1-flash-lite')
        assert original != review.cache_key(db, 'duplicate', {**selection, 'x': .4}, 'gemini-3.1-flash-lite')
        assert original != review.cache_key(db, 'duplicate', selection, 'gemini-3.5-flash-lite')
        assert original != review.cache_key(db, 'duplicate', selection, 'gemini-3.1-flash-lite', marked=True)
    cached = review.gemini_review({**row, 'id': 'duplicate'}, selection, True)
    assert cached['cache_hit'] and cached['performance'] == result['performance']
    assert len(calls) == 1


def test_deleted_report_not_reused(clients, monkeypatch):
    row, selection, calls = prepare_provider(clients, monkeypatch, [success(), success()])
    with core.connect() as db:
        db.execute("INSERT INTO video_fingerprints VALUES ('outage','same-file')")
    result = review.gemini_review(row, selection, True)
    with core.connect() as db:
        db.execute("UPDATE analyses SET result_json=? WHERE video_id='outage'", (json.dumps(result),))
    assert clients[0].delete('/api/videos/outage').status_code == 200
    add_result(clients[0].get('/api/me').json()['id'], 'new-upload', None, core.iso())
    folder = core.video_dir('new-upload')
    folder.mkdir()
    (folder/'preview-1.jpg').write_bytes(b'preview')
    monkeypatch.setattr(review.subprocess, 'run', lambda *a, **kw: (folder/'review.mp4').write_bytes(b'video'))
    with core.connect() as db:
        db.execute("INSERT INTO video_fingerprints VALUES ('new-upload','same-file')")
    review.gemini_review({**row, 'id': 'new-upload'}, selection, True)
    assert len(calls) == 2


def test_can_cancel_waiting_retry(clients, monkeypatch):
    row, selection, _ = prepare_provider(clients, monkeypatch, [httpx.Response(503)])
    queue_provider(row, selection)
    worker.process(worker.claim_next())
    assert clients[1].delete('/api/videos/outage').status_code == 404
    assert clients[0].delete('/api/videos/outage').status_code == 200
    make_due()
    assert worker.claim_next() is None


def test_reselect_is_owned_and_only_for_failed_jobs(clients, monkeypatch):
    row, selection, _ = prepare_provider(clients, monkeypatch, [httpx.Response(403)])
    path = core.video_dir('outage')/'normalized.mp4'
    path.write_bytes(b'video')
    row['normalized_path'] = str(path)
    queue_provider(row, selection)
    assert clients[0].post('/api/videos/outage/reselect').status_code == 409
    worker.process(worker.claim_next())
    assert clients[1].post('/api/videos/outage/reselect').status_code == 404
    assert clients[0].post('/api/videos/outage/reselect').status_code == 200
    assert clients[0].get('/api/videos/outage').json()['status'] == 'WAITING_FOR_PLAYER'


def test_interrupted_request_is_not_immediately_resent(clients, monkeypatch):
    row, selection, _ = prepare_provider(clients, monkeypatch, [])
    queue_provider(row, selection)
    worker.claim_next()
    with core.connect() as db:
        db.execute("INSERT INTO analysis_jobs(video_id,model) VALUES ('outage','gemini-3.1-flash-lite')")
    review.reserve_request('outage', 'gemini-3.1-flash-lite')
    worker.recover_interrupted()
    assert worker.claim_next() is None
    make_due()
    assert worker.claim_next()['id'] == 'outage'


def test_event_matching_and_repeatability():
    labels = [{'timestamp': 1, 'shot_type': 'drive'}, {'timestamp': 2, 'shot_type': 'drop'}]
    predicted = [{'timestamp': 1.5, 'shot_type': 'drive'}, {'timestamp': .2, 'shot_type': 'drive'}]
    metrics = compare_events(predicted, labels)
    assert metrics['matched'] == 2 and metrics['shot_type_accuracy'] == .5
    assert compare_events(predicted, labels[:1])['matched'] == 1
    assert summarize([])['score_min'] is None
    stats = summarize([{'performance': {'score': s}} for s in (70, 83)])
    assert stats['score_stddev'] == 6.5


def test_additive_migration_preserves_reports(clients):
    uid = clients[0].get('/api/me').json()['id']
    add_result(uid, 'before-migration', 75, core.iso())
    with core.connect() as db:
        db.execute('ALTER TABLE provider_requests DROP COLUMN failure_code')
        db.execute('ALTER TABLE provider_requests DROP COLUMN elapsed_seconds')
        for table in ('analysis_jobs', 'provider_health', 'video_fingerprints', 'review_cache_keys'):
            db.execute(f'DROP TABLE {table}')
    core.init_db()
    core.init_db()
    assert clients[0].get('/api/scores').json()['average'] == 75
    with core.connect() as db:
        columns = {row[1] for row in db.execute('PRAGMA table_info(provider_requests)')}
        assert {'failure_code', 'elapsed_seconds'} <= columns


def test_blocked_content_is_not_retried(clients, monkeypatch):
    response = httpx.Response(200, json={'promptFeedback': {'blockReason': 'SAFETY'}})
    row, selection, calls = prepare_provider(clients, monkeypatch, [response])
    queue_provider(row, selection)
    worker.process(worker.claim_next())
    clip = clients[0].get('/api/videos/outage').json()
    assert clip['status'] == 'FAILED'
    assert clip['recovery']['failure_code'] == 'CONTENT_BLOCKED'
    assert len(calls) == 1

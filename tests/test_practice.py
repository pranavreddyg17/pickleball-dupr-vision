import json
from datetime import timedelta

from duprvision import core, worker
from test_flow import clients, add_result


def scored_day(uid, name, days_ago, score, key=None):
    stamp = core.iso(core.now()-timedelta(days=days_ago))
    add_result(uid, name, score, stamp)
    result = {'kind': 'video_review_v2', 'performance': {'version': 'vision_score_v1', 'score': score,
        'components': [{'name': 'Shot control', 'value': score, 'observations': 5},
                       {'name': 'Balance', 'value': None, 'observations': 0},
                       {'name': 'Recovery', 'value': 100, 'observations': 5}]}}
    with core.connect() as db:
        db.execute('UPDATE analyses SET result_json=? WHERE video_id=?', (json.dumps(result), name))
        if key:
            db.execute('INSERT INTO review_cache_keys VALUES (?,?)', (name, key))


def test_notes_private_validated_and_deleted(clients):
    a, b = clients
    uid = a.get('/api/me').json()['id']
    add_result(uid, 'notes', 80, core.iso())
    assert b.put('/api/videos/notes/notes', json={'note': 'stolen'}).status_code == 404
    assert a.put('/api/videos/notes/notes', json={'note': 'x'*1001}).status_code == 422
    assert a.put('/api/videos/notes/notes', json={'feedback': 'bad-enum'}).status_code == 422
    assert a.put('/api/videos/notes/notes', json={'note': 'blocked'}, headers={'Origin': 'https://evil.test'}).status_code == 403
    payload = {'note': '  Practice resets  ', 'feedback': 'inaccurate'}
    assert a.put('/api/videos/notes/notes', json=payload).status_code == 200
    expected = {'note': 'Practice resets', 'feedback': 'inaccurate'}
    assert a.get('/api/videos/notes').json()['notes'] == expected
    assert a.get('/api/videos').json()[0]['notes'] == expected
    assert a.get('/api/scores').json()['average'] == 80
    a.put('/api/me', json={'display_name': 'Visible Player', 'discoverable': True})
    assert 'Practice resets' not in b.get('/api/players/'+uid).text
    assert a.put('/api/videos/notes/notes', json={'note': '', 'feedback': None}).status_code == 200
    assert a.get('/api/videos/notes').json()['notes']['feedback'] is None
    a.delete('/api/videos/notes')
    assert a.put('/api/videos/notes/notes', json={'note': 'resurrect'}).status_code == 404
    with core.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM session_notes').fetchone()[0] == 0


def test_unfinished_report_rejects_notes(clients):
    a, _ = clients
    add_result(a.get('/api/me').json()['id'], 'unfinished', None, core.iso())
    with core.connect() as db:
        db.execute("UPDATE videos SET status='RETRY_WAIT' WHERE id='unfinished'")
    assert a.put('/api/videos/unfinished/notes', json={'note': 'no'}).status_code == 409


def test_report_issues_and_evidence_are_private_and_deleted(clients):
    a, b = clients
    uid = a.get('/api/me').json()['id']
    add_result(uid, 'evidence', 75, core.iso())
    with core.connect() as db:
        db.execute('UPDATE analyses SET result_json=? WHERE video_id=?',
                   (json.dumps({'kind':'video_review_v2','evidence':[{'number':1,'timestamp':12,'label':'drive'}]}), 'evidence'))
    path = core.evidence_dir('evidence') / '1.jpg'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'private-frame')
    assert b.get('/api/videos/evidence/evidence/1').status_code == 404
    assert b.put('/api/videos/evidence/issue', json={'reason': 'player'}).status_code == 404
    assert a.get('/api/videos/evidence/evidence/1').content == b'private-frame'
    assert a.get('/api/videos/evidence/evidence/4').status_code == 404
    assert a.put('/api/videos/evidence/issue', json={'reason': 'wrong'}).status_code == 422
    assert a.put('/api/videos/evidence/issue', json={'reason': 'shot', 'timestamp_seconds': 61}).status_code == 400
    issue = {'reason': 'shot', 'detail': '  Drive at 12 seconds  ', 'timestamp_seconds': 12}
    assert a.put('/api/videos/evidence/issue', json=issue).status_code == 200
    assert a.get('/api/videos/evidence').json()['issue']['detail'] == 'Drive at 12 seconds'
    assert 'Drive at 12 seconds' not in b.get('/api/players/'+uid).text
    assert a.delete('/api/videos/evidence').status_code == 200
    assert not path.exists()
    with core.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM report_issues').fetchone()[0] == 0


def test_tracking_failure_does_not_discard_completed_review(clients, monkeypatch):
    a, _ = clients
    uid = a.get('/api/me').json()['id']
    add_result(uid, 'snapshot-failure', None, core.iso())
    with core.connect() as db:
        db.execute("UPDATE videos SET status='QUEUED' WHERE id='snapshot-failure'")
        db.execute("INSERT INTO selections VALUES ('snapshot-failure',12,.5,.5)")
        db.execute("INSERT INTO analysis_options VALUES ('snapshot-failure','gemini',1)")
        db.execute("INSERT INTO evidence_preferences(video_id,enabled) VALUES ('snapshot-failure',1)")
    monkeypatch.setattr(worker, 'track_player', lambda *args: (_ for _ in ()).throw(RuntimeError('tracker unavailable')))
    monkeypatch.setattr(worker, 'gemini_review', lambda *args: {
        'kind':'video_review_v2','summary':'Review completed','shots':[],
        'performance':{'version':'vision_score_v1','score':None}})
    worker.process(worker.claim_next())
    report = a.get('/api/videos/snapshot-failure').json()
    assert report['status'] == 'COMPLETED'
    assert report['result']['evidence'] == []
    assert not core.video_dir('snapshot-failure').exists()


def test_progress_daily_comparison_and_account_scope(clients):
    a, b = clients
    uid = a.get('/api/me').json()['id']
    for day in range(10):
        scored_day(uid, f'day-{day}', day, 80 if day < 5 else 60)
    progress = a.get('/api/progress').json()
    assert progress['recent_days'] == progress['previous_days'] == 5
    score, control, balance, recovery = progress['metrics']
    assert score['value'] == 80 and score['delta'] == 20
    assert control['delta'] == 20
    assert balance['value'] is None and balance['delta'] is None
    assert recovery['delta'] == 0
    assert b.get('/api/progress').json()['days'] == []


def test_progress_duplicates_versions_and_small_samples(clients):
    a, _ = clients
    uid = a.get('/api/me').json()['id']
    scored_day(uid, 'original', 2, 70, 'same-evidence')
    scored_day(uid, 'duplicate', 0, 70, 'same-evidence')
    scored_day(uid, 'other-session', 2, 90)
    scored_day(uid, 'future-rubric', 1, 100)
    with core.connect() as db:
        row = db.execute("SELECT result_json FROM analyses WHERE video_id='future-rubric'").fetchone()
        result = json.loads(row[0]); result['performance']['version'] = 'different-rubric'
        db.execute("UPDATE analyses SET result_json=? WHERE video_id='future-rubric'", (json.dumps(result),))
    progress = a.get('/api/progress').json()
    assert len(progress['days']) == 1
    assert progress['metrics'][0]['value'] == 80
    assert progress['metrics'][0]['delta'] is None
    a.delete('/api/videos/original')
    assert len(a.get('/api/progress').json()['days']) == 2


def test_original_fingerprint_is_owner_only(clients):
    a, b = clients
    add_result(a.get('/api/me').json()['id'], 'fingerprint', 75, core.iso())
    with core.connect() as db:
        db.execute("INSERT INTO video_fingerprints VALUES ('fingerprint','private-sha')")
    assert a.get('/api/videos/fingerprint').json()['sha256'] == 'private-sha'
    assert b.get('/api/videos/fingerprint').status_code == 404
    assert b.get('/api/videos').json() == []


def test_connections_union_count_and_privacy(clients):
    a,b=clients
    aid,bid=a.get('/api/me').json()['id'],b.get('/api/me').json()['id']
    for client,name in ((a,'Alice'),(b,'Bob')):
        client.put('/api/me',json={'display_name':name,'discoverable':True})
    assert a.get('/api/players/'+aid).json()['connections']==0
    a.post('/api/players/'+bid+'/follow')
    b.post('/api/players/'+aid+'/follow')
    assert a.get('/api/players/'+aid).json()['connections']==1
    assert [p['id'] for p in a.get('/api/players?view=connections').json()['players']]==[bid]
    assert 'connections' not in a.get('/api/players/'+bid).json()
    a.delete('/api/players/'+bid+'/follow')
    assert a.get('/api/players/'+aid).json()['connections']==1
    assert len(a.get('/api/players?view=connections').json()['players'])==1
    b.put('/api/me',json={'display_name':'Bob','discoverable':False})
    assert a.get('/api/players/'+aid).json()['connections']==0
    assert a.get('/api/players?view=connections').json()['players']==[]

import json
import threading
from concurrent.futures import ThreadPoolExecutor, wait

import httpx
import pytest

from duprvision import core, review, worker
from duprvision.performance import validate_performance
from test_flow import clients, add_result, compact_review


def test_deterministic_score_and_missing_evidence():
    raw = compact_review()
    result = validate_performance(raw,60)
    assert result["performance"]["score"] == 63
    assert result == validate_performance(raw,60)
    raw["ball_visible"] = False
    assert validate_performance(raw,60)["performance"]["score"] is None
    raw = compact_review()
    for s in raw["shots"]:
        s["balanced"] = None
    assert validate_performance(raw,60)["performance"]["score"] is None
    raw = compact_review()
    raw["shots"][0]["timestamp"] = 500
    with pytest.raises(ValueError):
        validate_performance(raw,60)


def prepare_provider(clients, monkeypatch, responses):
    a,_ = clients
    add_result(a.get('/api/me').json()['id'],'outage',None,core.iso())
    folder = core.video_dir('outage')
    folder.mkdir()
    (folder/'preview-1.jpg').write_bytes(b'reference')
    monkeypatch.setenv('ANALYSIS_ENGINE','gemini')
    monkeypatch.setenv('GEMINI_API_KEY','test-not-real')
    monkeypatch.setenv('GEMINI_MODEL','gemini-3.1-flash-lite')
    monkeypatch.setattr(review.subprocess,'run',lambda *a,**kw:(folder/'review.mp4').write_bytes(b'video'))
    monkeypatch.setattr(review.time,'sleep',lambda _:None)
    calls=[]
    class Client:
        def __init__(self,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def post(self,*a,**kw):
            calls.append(kw)
            response=responses.pop(0)
            if isinstance(response,Exception):raise response
            return response
    monkeypatch.setattr(review.httpx,'Client',Client)
    return {'id':'outage','duration_seconds':60,'normalized_path':'test.mp4'}, {'timestamp_seconds':6,'x':.5,'y':.5}, calls


def success():
    return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(compact_review())}]}}]})


@pytest.mark.parametrize('failure',[httpx.Response(503),httpx.Response(429),httpx.ReadTimeout('timeout'),httpx.Response(200,json={})])
def test_transient_failure_recovers(clients,monkeypatch,failure):
    row, selection, calls = prepare_provider(clients,monkeypatch,[failure,success()])
    assert review.gemini_review(row,selection,True)['performance']['score']==63
    assert len(calls)==2
    with core.connect() as db:
        assert [r[0] for r in db.execute('SELECT status FROM provider_requests ORDER BY id')]==['retryable','succeeded']
        assert [r[0] for r in db.execute('SELECT model FROM provider_requests ORDER BY id')]==['gemini-3.1-flash-lite','gemini-3.5-flash-lite']


def test_long_retry_after_does_not_hold_worker(clients,monkeypatch):
    row, selection, calls = prepare_provider(clients,monkeypatch,[httpx.Response(429,headers={'Retry-After':'120'})])
    with pytest.raises(RuntimeError,match='clip is saved'):
        review.gemini_review(row,selection,True)
    assert len(calls)==1


def test_outage_is_bounded_and_manual_retry_works(clients,monkeypatch):
    responses=[httpx.Response(503) for _ in range(3)]+[success()]
    row, selection, calls = prepare_provider(clients,monkeypatch,responses)
    with pytest.raises(RuntimeError,match='clip is saved'):
        review.gemini_review(row,selection,True)
    assert len(calls)==3
    assert review.gemini_review(row,selection,True)['performance']['score']==63
    assert len(calls)==4


def test_budget_counts_retries_and_permanent_failures_do_not_retry(clients,monkeypatch):
    row, selection, calls = prepare_provider(clients,monkeypatch,[httpx.Response(403)])
    with pytest.raises(RuntimeError,match='configuration'):
        review.gemini_review(row,selection,True)
    assert len(calls)==1
    monkeypatch.setenv('MAX_DAILY_VIDEO_REVIEWS','1')
    with pytest.raises(RuntimeError,match='budget'):
        review.gemini_review(row,selection,True)
    assert len(calls)==1


def test_request_reservation_is_atomic(clients):
    a,_=clients
    add_result(a.get('/api/me').json()['id'],'atomic',None,core.iso())
    def reserve(_):
        try:return review.reserve_request('atomic','test')
        except RuntimeError:return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        results=list(pool.map(reserve,range(8)))
    assert sum(r is not None for r in results)==1


def test_three_jobs_overlap_without_duplicate_claims(clients,monkeypatch):
    a,_=clients
    uid=a.get('/api/me').json()['id']
    for i in range(5):add_result(uid,f'concurrent-{i}',None,core.iso())
    with core.connect() as db:db.execute("UPDATE videos SET status='QUEUED'")
    barrier=threading.Barrier(3)
    seen=[]
    def process(row):
        seen.append(row['id'])
        if len(seen)<=3:barrier.wait(timeout=3)
        worker.update(row['id'],status='COMPLETED')
    monkeypatch.setattr(worker,'process',process)
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures=set()
        worker.dispatch(pool,futures,3)
        wait(futures,timeout=5)
        assert len(seen)==3
        with core.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM videos WHERE status='QUEUED'").fetchone()[0]==2
        worker.dispatch(pool,futures,3)
        wait(futures,timeout=5)
    assert len(seen)==len(set(seen))==5


def test_retry_preserves_selection_consent_and_quota(clients):
    a,_=clients
    uid=a.get('/api/me').json()['id']
    add_result(uid,'retry-selected',None,core.iso())
    folder=core.video_dir('retry-selected');folder.mkdir()
    path=folder/'normalized.mp4';path.write_bytes(b'test')
    with core.connect() as db:
        db.execute("UPDATE videos SET status='FAILED',normalized_path=?",(str(path),))
        db.execute("INSERT INTO selections VALUES ('retry-selected',6,.5,.5)")
        db.execute("INSERT INTO analysis_options VALUES ('retry-selected','gemini',1)")
    remaining=a.get('/api/me').json()['remaining']
    assert a.post('/api/videos/retry-selected/retry').status_code==200
    assert a.get('/api/videos/retry-selected').json()['status']=='QUEUED'
    assert a.post('/api/videos/retry-selected/retry').status_code==409
    assert a.get('/api/me').json()['remaining']==remaining


def test_legacy_rating_never_mixed_with_performance(clients):
    a,_=clients
    uid=a.get('/api/me').json()['id']
    add_result(uid,'old',4,core.iso(),kind='video_review_v1')
    add_result(uid,'new',70,core.iso())
    history=a.get('/api/scores').json()
    assert history['average']==70
    assert history['clips']==2 and history['rated_clips']==1
    assert history['dupr_equivalent']==4.1


def test_dupr_equivalent_is_bounded_and_missing_stays_missing():
    assert core.dupr_scale_equivalent(None) is None
    assert core.dupr_scale_equivalent(0)==2.0
    assert core.dupr_scale_equivalent(50)==3.5
    assert core.dupr_scale_equivalent(100)==5.0
    assert core.dupr_scale_equivalent(120)==5.0

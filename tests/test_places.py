
import httpx
import pytest

from duprvision import core, places
from test_schedule import plan, events


@pytest.fixture(autouse=True)
def reset_search(monkeypatch):
    monkeypatch.setenv('PLACE_SEARCH_URL', 'https://photon.komoot.io/api/')
    places._cache.clear()
    monkeypatch.setattr(places, '_last_request', 0)


def test_search_requires_auth_origin_and_caches_results(clients, monkeypatch):
    owner, other = clients
    calls = []
    def lookup(url, **kwargs):
        calls.append(kwargs)
        return httpx.Response(200,request=httpx.Request('GET',url),json={'features':[
            {'properties':{'name':'Court <name>','housenumber':'100','street':'Main Street','city':'Dallas','state':'Texas'},
             'geometry':{'coordinates':[-96.8,32.8]}},
            {'properties':{'name':'Invalid'},'geometry':{'coordinates':[0,100]}},
        ]})
    monkeypatch.setattr(places.httpx, 'get', lookup)
    assert owner.post('/api/places/search',json={'query':'co'}).status_code == 422
    assert owner.post('/api/places/search',json={'query':'courts'},headers={'Origin':'https://evil.test'}).status_code == 403
    response = owner.post('/api/places/search',json={'query':'  Courts   Dallas '})
    assert response.status_code == 200
    result = response.json()['places']
    assert len(result) == 1 and result[0]['latitude'] == 32.8
    assert result[0]['address'] == '100 Main Street, Dallas, Texas'
    assert other.post('/api/places/search',json={'query':'courts dallas'}).json()['places'] == result
    assert len(calls) == 1
    assert calls[0]['params']['q'] == 'Courts Dallas'
    assert calls[0]['headers']['User-Agent'].startswith('DUPRVision/')
    assert owner.post('/api/places/search',json={'query':'different'}).status_code == 429
    owner.post('/api/logout')
    assert owner.post('/api/places/search',json={'query':'courts'}).status_code == 401


def test_search_failure_has_manual_fallback(clients, monkeypatch):
    owner, _ = clients
    monkeypatch.setattr(places.httpx, 'get', lambda *a,**k: (_ for _ in ()).throw(httpx.ReadTimeout('down')))
    response=owner.post('/api/places/search',json={'query':'courts'})
    assert response.status_code == 503
    assert 'enter the location yourself' in response.json()['detail']


def test_coordinates_persist_remain_private_and_clear_on_manual_edit(clients):
    owner, other = clients
    uid = owner.get('/api/me').json()['id']
    owner.put('/api/me',json={'display_name':'Alice','discoverable':True})
    payload = plan(latitude=32.8,longitude=-96.8)
    created=owner.post('/api/schedule',json=payload)
    assert created.status_code == 200
    event_id=created.json()['id']
    result=events(owner).json()['events'][0]
    assert result['latitude'] == 32.8 and '32.8%2C-96.8' in result['maps_url']
    assert other.get('/api/places/recent').json()['places'] == []
    assert events(other).json()['events'] == []
    other.post('/api/players/'+uid+'/follow')
    assert events(other).json()['events'][0]['longitude'] == -96.8
    assert other.get('/api/places/recent').json()['places'] == []
    assert owner.get('/api/places/recent').json()['places'][0]['latitude'] == 32.8
    assert owner.post('/api/schedule',json=plan(latitude=32.8)).status_code == 400
    assert owner.post('/api/schedule',json=plan(latitude=91,longitude=0)).status_code == 422
    assert other.put('/api/schedule/'+event_id,json=plan(latitude=0,longitude=0)).status_code == 404
    assert owner.put('/api/schedule/'+event_id,json=plan()).status_code == 200
    assert events(owner).json()['events'][0]['latitude'] is None
    assert owner.put('/api/schedule/'+event_id,json=payload).status_code == 200
    owner.delete('/api/schedule/'+event_id)
    with core.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM playing_event_places').fetchone()[0] == 0
    assert owner.get('/api/places/recent').json()['places'] == []

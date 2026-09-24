from datetime import timedelta

from duprvision import core


def plan(**changes):
    start = core.now() + timedelta(days=2)
    return {'kind': 'open_play', 'location': 'The Picklr Lewisville', 'address': 'Lewisville, TX',
            'starts_at': core.iso(start), 'ends_at': core.iso(start + timedelta(minutes=90)),
            'timezone': 'America/Chicago', 'visibility': 'followers', 'note': 'Court 4', **changes}


def events(client, **params):
    return client.get('/api/schedule', params={'start': core.iso(core.now()),
        'end': core.iso(core.now()+timedelta(days=30)), **params})


def test_schedule_access_and_visibility(clients):
    owner, follower = clients
    uid = owner.get('/api/me').json()['id']
    owner.put('/api/me', json={'display_name': 'Alice', 'discoverable': True})
    shared = owner.post('/api/schedule', json=plan()).json()['id']
    owner.post('/api/schedule', json=plan(visibility='private', location='Private court'))
    assert len(events(owner).json()['events']) == 2
    assert events(follower).json()['events'] == []
    assert follower.get('/api/players/'+uid).json()['playing'] == []
    follower.post('/api/players/'+uid+'/follow')
    visible = events(follower).json()['events']
    assert [event['id'] for event in visible] == [shared]
    assert visible[0]['is_owner'] is False
    assert visible[0]['maps_url'].startswith('https://www.google.com/maps/search/?api=1&query=')
    assert len(follower.get('/api/players/'+uid).json()['playing']) == 1
    assert len(events(follower, view='following').json()['events']) == 1
    assert events(follower, view='mine').json()['events'] == []
    assert follower.put('/api/schedule/'+shared, json=plan()).status_code == 404
    assert follower.delete('/api/schedule/'+shared).status_code == 404
    owner.put('/api/me', json={'display_name': 'Alice', 'discoverable': False})
    assert events(follower).json()['events'] == []
    owner.put('/api/me', json={'display_name': 'Alice', 'discoverable': True})
    follower.delete('/api/players/'+uid+'/follow')
    assert events(follower).json()['events'] == []
    follower.post('/api/players/'+uid+'/follow')
    assert owner.put('/api/schedule/'+shared, json=plan(visibility='private')).status_code == 200
    assert events(follower).json()['events'] == []
    assert owner.delete('/api/schedule/'+shared).status_code == 200
    assert owner.delete('/api/schedule/'+shared).status_code == 404
    assert events(owner).headers['cache-control'] == 'private, no-store'
    owner.post('/api/logout')
    assert events(owner).status_code == 401


def test_schedule_validation_origin_and_time_ranges(clients):
    owner, _ = clients
    assert owner.post('/api/schedule', json=plan(), headers={'Origin':'https://evil.test'}).status_code == 403
    for changes in ({'location':' '}, {'timezone':'Fake/Zone'}, {'ends_at':core.iso()},
                    {'ends_at':core.iso(core.now()+timedelta(days=5))}):
        assert owner.post('/api/schedule', json=plan(**changes)).status_code == 400
    for changes in ({'starts_at':'2026-09-25T18:00:00'}, {'kind':'invalid'}, {'visibility':'public'},
                    {'note':'x'*301}):
        assert owner.post('/api/schedule', json=plan(**changes)).status_code == 422
    assert events(owner, view='invalid').status_code == 400
    assert events(owner, start='2026-09-23T00:00:00').status_code == 400
    assert events(owner, end=core.iso(core.now()+timedelta(days=100))).status_code == 400
    event = owner.post('/api/schedule', json=plan()).json()['id']
    assert owner.delete('/api/schedule/'+event, headers={'Origin':'https://evil.test'}).status_code == 403


def test_utc_order_and_overnight_overlap(clients):
    owner, _ = clients
    # Different offsets around daylight saving must represent elapsed time correctly.
    start = (core.now()+timedelta(days=3)).replace(hour=23, minute=30, second=0, microsecond=0)
    end = start+timedelta(hours=2)
    result = owner.post('/api/schedule', json=plan(starts_at=start.isoformat(), ends_at=end.isoformat()))
    assert result.status_code == 200
    response = events(owner, start=core.iso(start+timedelta(minutes=30)), end=core.iso(end+timedelta(days=1)))
    assert len(response.json()['events']) == 1
    assert events(owner, start=core.iso(end), end=core.iso(end+timedelta(days=1))).json()['events'] == []
    assert owner.put('/api/schedule/'+result.json()['id'],json=plan(location='Updated court')).status_code == 200
    assert events(owner).json()['events'][0]['location'] == 'Updated court'

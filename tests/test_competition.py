import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from duprvision import app as web
from fastapi.testclient import TestClient
from duprvision.round_robin import schedule
from test_schedule import plan, events


def create(client, **rules):
    result = client.post('/api/competitions', json={'title': 'Friday doubles', 'plan': plan(),
                        'rules': {'courts': ['7', '8'], **rules}, 'playing': False})
    assert result.status_code == 200, result.text
    return result.json()


def command(client, event, action, status=200, **kwargs):
    result = client.post(f"/api/competitions/{event['id']}/commands", json={
        'version': event['version'], 'request_id': str(uuid.uuid4()), 'action': action, **kwargs})
    assert result.status_code == status, result.text
    return result.json() if status == 200 else event


def roster(client, event, count=8):
    for i in range(count):
        event = command(client, event, 'add_player', name=f'Player {i}')
        player = event['players'][-1]
        event = command(client, event, 'attendance', player_id=player['id'])
        if event['rules']['format'] == 'fixed':
            event = command(client, event, 'team', player_id=player['id'], team=f'Team {i//2+1}')
    return event


def test_host_only_round_lifecycle_and_idempotency(clients):
    owner, _ = clients
    event = roster(owner, create(owner), 9)
    assert len(event['players']) == 9
    body = {'version': event['version'], 'request_id': str(uuid.uuid4()), 'action': 'generate'}
    path = f"/api/competitions/{event['id']}/commands"
    first = owner.post(path, json=body)
    assert first.status_code == 200
    assert owner.post(path, json=body).json()['version'] == first.json()['version']
    event = first.json()
    assert len(event['matches']) == 2
    assert len({p for m in event['matches'] for p in m['a'] + m['b']}) == 8
    command(owner, event, 'add_player', name='Late', status=400)
    event = command(owner, event, 'start')
    command(owner, event, 'generate', status=400)
    for match in event['matches']:
        event = command(owner, event, 'score', match_id=match['id'], score_a=11, score_b=6)
    assert event['rounds'][0]['status'] == 'completed'
    event = command(owner, event, 'generate')
    assert len(event['rounds']) == 2
    assert owner.delete('/api/schedule/'+event['id']).status_code == 400
    event = command(owner, event, 'discard')
    event = command(owner, event, 'finish')
    command(owner, event, 'generate', status=400)
    assert len(event['audit']) > 0


def test_membership_privacy_and_score_confirmation(clients):
    owner, other = clients
    event = create(owner)
    assert other.get('/api/competitions/'+event['id']).status_code == 404
    joined = other.post('/api/competitions/join', json={'token': event['invite']})
    assert joined.status_code == 200
    assert joined.json()['invite'] is None
    assert event['id'] in [e['id'] for e in events(other).json()['events']]
    assert event['id'] in [e['id'] for e in events(other, view='mine').json()['events']]
    event = owner.get('/api/competitions/'+event['id']).json()
    event = command(owner, event, 'attendance', player_id=event['players'][0]['id'])
    event = roster(owner, event, 3)
    command(other, event, 'generate', status=403)
    event = command(owner, event, 'generate')
    event = command(owner, event, 'start')
    match = event['matches'][0]
    command(other, event, 'score', match_id=match['id'], score_a=11, score_b=10, status=400)
    event = command(other, event, 'score', match_id=match['id'], score_a=11, score_b=8)
    assert event['matches'][0]['status'] == 'submitted'
    command(other, event, 'confirm', match_id=match['id'], status=400)
    event = command(owner, event, 'confirm', match_id=match['id'])
    assert event['matches'][0]['status'] == 'confirmed'


def test_stale_edits_forfeits_and_fixed_completion(clients):
    owner, _ = clients
    event = roster(owner, create(owner, format='fixed'), 8)
    stale = dict(event)
    event = command(owner, event, 'generate')
    command(owner, stale, 'generate', status=409)
    for number in range(3):
        if number:
            event = command(owner, event, 'generate')
        event = command(owner, event, 'start')
        for match in event['matches']:
            if match['status'] == 'live':
                event = command(owner, event, 'forfeit', match_id=match['id'], winner=1, reason='Injury')
    assert len(event['matches']) == 6
    assert event['fixed_complete'] is True
    assert all(r['games'] == 3 for r in event['standings'])
    assert all(m['score_a'] is None for m in event['matches'])
    command(owner, event, 'generate', status=400)


def test_scheduler_balances_rests_and_never_double_books():
    players = [dict(id=str(i), availability='ready', last_round=0, team='') for i in range(13)]
    matches = []
    counts = Counter()
    for round_number in range(1, 14):
        games = schedule(players, matches, 3)
        ids = [pid for a,b in games for pid in a+b]
        assert len(ids) == len(set(ids)) == 12
        counts.update(ids)
        for p in players:
            if p['id'] in ids:
                p['last_round'] = round_number
        matches.extend(dict(a=a,b=b,status='confirmed') for a,b in games)
    assert set(counts.values()) == {12}


def test_invite_rotation_pause_timed_draw_and_origin(clients):
    owner, other = clients
    event = roster(owner, create(owner, minutes=10), 4)
    old = event['invite']
    event = command(owner, event, 'rotate_invite')
    assert other.post('/api/competitions/join', json={'token': old}).status_code == 404
    event = command(owner, event, 'pause')
    command(owner, event, 'generate', status=400)
    event = command(owner, event, 'resume')
    event = command(owner, event, 'generate')
    event = command(owner, event, 'start')
    event = command(owner, event, 'score', match_id=event['matches'][0]['id'], score_a=8, score_b=8)
    assert all(r['draws'] == 1 and r['percentage'] == 50 for r in event['standings'])
    assert owner.post('/api/competitions', json={}, headers={'Origin':'https://evil.test'}).status_code in (403,422)


def test_concurrent_generation_and_cohost_without_playing(clients):
    owner, other = clients
    event = roster(owner, create(owner), 8)
    other_id = other.get('/api/me').json()['id']
    event = command(owner, event, 'host', user_id=other_id)
    assert len(event['players']) == 8
    assert other.get('/api/competitions/'+event['id']).json()['is_host'] is True
    bodies = [dict(action='generate', version=event['version'], request_id=str(uuid.uuid4())) for _ in range(2)]
    def generate(item):
        client, body = item
        return client.post('/api/competitions/'+event['id']+'/commands', json=body).status_code
    with ThreadPoolExecutor(2) as executor:
        assert sorted(executor.map(generate, zip((owner, other), bodies))) == [200,409]
    event = owner.get('/api/competitions/'+event['id']).json()
    assert len(event['rounds']) == 1
    event = command(owner, event, 'remove_host', user_id=other_id)
    assert other.get('/api/competitions/'+event['id']).status_code == 404


def test_conflicting_scores_preserve_audit_and_require_organizer(clients):
    owner, first = clients
    second = TestClient(web.app)
    assert second.post('/api/register', json={'email':'third@example.test','password':'long-password',
                      'display_name':'Third'}).status_code == 200
    event = create(owner)
    for client in (first, second):
        assert client.post('/api/competitions/join', json={'token':event['invite']}).status_code == 200
    event = owner.get('/api/competitions/'+event['id']).json()
    for p in event['players']:
        event = command(owner, event, 'attendance', player_id=p['id'])
    event = roster(owner, event, 2)
    event = command(owner, event, 'generate')
    a,b = event['players'][:2]
    match = event['matches'][0]
    if (a['id'] in match['a']) == (b['id'] in match['a']):
        opposite = match['b'] if a['id'] in match['a'] else match['a']
        event = command(owner, event, 'swap', player_id=b['id'], other_id=opposite[0])
    event = command(owner, event, 'start')
    event = command(first, event, 'score', match_id=match['id'], score_a=11, score_b=7)
    event = command(second, event, 'score', match_id=match['id'], score_a=7, score_b=11)
    assert event['matches'][0]['status'] == 'disputed'
    command(owner, event, 'generate', status=400)
    event = command(owner, event, 'score', match_id=match['id'], score_a=11, score_b=7)
    assert event['matches'][0]['status'] == 'confirmed'
    assert sum(a['action']=='score' for a in event['audit']) == 3


def test_settings_lock_and_win_by_one_validation(clients):
    owner, _ = clients
    event = create(owner)
    event = command(owner, event, 'settings', title='Updated event', plan=plan(location='North courts'),
                    rules={'courts':['1'], 'win_by':1})
    assert event['title'] == 'Updated event' and event['plan']['location'] == 'North courts'
    event = roster(owner, event, 4)
    event = command(owner, event, 'generate')
    command(owner, event, 'settings', title='Too late', plan=plan(), rules={}, status=400)
    event = command(owner, event, 'start')
    command(owner, event, 'score', match_id=event['matches'][0]['id'], score_a=12, score_b=11, status=400)
    event = command(owner, event, 'score', match_id=event['matches'][0]['id'], score_a=11, score_b=10)
    assert event['matches'][0]['status'] == 'confirmed'

"""Event membership, synchronized doubles rounds, and auditable results."""
import hashlib
import json
import secrets
import uuid
from itertools import combinations
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .core import connect, iso
from .round_robin import schedule
from .schedule import PlayingEvent, save_place


SCHEMA = """
CREATE TABLE IF NOT EXISTS competitions (
 event_id TEXT PRIMARY KEY REFERENCES playing_events(id) ON DELETE CASCADE,
 title TEXT NOT NULL, settings TEXT NOT NULL, phase TEXT NOT NULL DEFAULT 'registration',
 version INTEGER NOT NULL DEFAULT 0, invite TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS competition_hosts (
 event_id TEXT NOT NULL REFERENCES competitions(event_id) ON DELETE CASCADE,
 user_id TEXT NOT NULL REFERENCES users(id), PRIMARY KEY(event_id,user_id)
);
CREATE TABLE IF NOT EXISTS competition_players (
 id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES competitions(event_id) ON DELETE CASCADE,
 user_id TEXT REFERENCES users(id), name TEXT NOT NULL, team TEXT NOT NULL DEFAULT '',
 availability TEXT NOT NULL DEFAULT 'expected', last_round INTEGER NOT NULL DEFAULT 0,
 UNIQUE(event_id,user_id)
);
CREATE INDEX IF NOT EXISTS competition_players_event ON competition_players(event_id);
CREATE TABLE IF NOT EXISTS competition_rounds (
 id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES competitions(event_id) ON DELETE CASCADE,
 number INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'draft', started_at TEXT,
 UNIQUE(event_id,number)
);
CREATE TABLE IF NOT EXISTS competition_matches (
 id TEXT PRIMARY KEY, round_id TEXT NOT NULL REFERENCES competition_rounds(id) ON DELETE CASCADE,
 court TEXT NOT NULL, a TEXT NOT NULL, b TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'scheduled', score_a INTEGER, score_b INTEGER,
 submitted_by TEXT REFERENCES users(id), winner INTEGER, reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS competition_matches_round ON competition_matches(round_id);
CREATE TABLE IF NOT EXISTS competition_audit (
 id INTEGER PRIMARY KEY, event_id TEXT NOT NULL REFERENCES competitions(event_id) ON DELETE CASCADE,
 actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS competition_commands (
 event_id TEXT NOT NULL REFERENCES competitions(event_id) ON DELETE CASCADE,
 actor TEXT NOT NULL, request_id TEXT NOT NULL, digest TEXT NOT NULL,
 PRIMARY KEY(event_id,actor,request_id)
);
"""


class Rules(BaseModel):
    format: Literal['rotating', 'fixed'] = 'rotating'
    courts: list[str] = Field(default=[''], min_length=1, max_length=8)
    target: Literal[11, 15, 21] = 11
    win_by: Literal[1, 2] = 2
    scoring: Literal['side_out', 'rally'] = 'side_out'
    minutes: int = Field(default=0, ge=0, le=30)
    minimum_games: int = Field(default=3, ge=1, le=20)


class CreateCompetition(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    plan: PlayingEvent
    rules: Rules
    playing: bool = False


class JoinCompetition(BaseModel):
    token: str = Field(min_length=20, max_length=100)


class Command(BaseModel):
    version: int = Field(ge=0)
    request_id: uuid.UUID
    action: Literal['add_player', 'attendance', 'team', 'host', 'remove_host', 'generate', 'discard',
                    'swap', 'start', 'score', 'confirm', 'dispute', 'void', 'forfeit',
                    'pause', 'resume', 'finish', 'courts', 'rotate_invite', 'settings']
    player_id: str = ''
    other_id: str = ''
    user_id: str | None = None
    name: str = Field(default='', max_length=80)
    team: str = Field(default='', max_length=40)
    availability: Literal['expected', 'ready', 'resting', 'withdrawn'] = 'ready'
    match_id: str = ''
    score_a: int = Field(default=0, ge=0, le=99)
    score_b: int = Field(default=0, ge=0, le=99)
    winner: Literal[1, 2] = 1
    reason: str = Field(default='', max_length=300)
    courts: list[str] = Field(default=[], max_length=8)
    title: str = Field(default='', max_length=100)
    rules: Rules | None = None
    plan: PlayingEvent | None = None


def fail(message, status=400):
    raise HTTPException(status, message)


def courts_valid(courts):
    if not courts or any(len(c.strip()) > 40 for c in courts):
        fail('Choose one to eight courts, with labels up to 40 characters.')
    names = [c.strip().casefold() for c in courts if c.strip()]
    if len(names) != len(set(names)):
        fail('Court names must be unique.')


def access(db, event_id, uid, host=False):
    event = db.execute('SELECT c.*, e.user_id AS owner FROM competitions c JOIN playing_events e '
                       'ON e.id=c.event_id WHERE c.event_id=?', (event_id,)).fetchone()
    is_host = db.execute('SELECT 1 FROM competition_hosts WHERE event_id=? AND user_id=?', (event_id, uid)).fetchone()
    member = db.execute('SELECT 1 FROM competition_players WHERE event_id=? AND user_id=?', (event_id, uid)).fetchone()
    if not event or not (is_host or member):
        fail('Event not found.', 404)
    if host and not is_host:
        fail('Only an organizer can do this.', 403)
    return dict(event), bool(is_host)


def matches_for(db, event_id):
    rows = db.execute('SELECT m.*, r.number, r.started_at FROM competition_matches m '
                      'JOIN competition_rounds r ON r.id=m.round_id WHERE r.event_id=? '
                      'ORDER BY r.number,m.court,m.id', (event_id,)).fetchall()
    return [{**dict(row), 'a': json.loads(row['a']), 'b': json.loads(row['b'])} for row in rows]


def standings(players, matches, rules):
    names = {p['id']: p for p in players}
    records = {}
    for p in players:
        key = p['team'] if rules['format'] == 'fixed' else p['id']
        if not key:
            continue
        records.setdefault(key, dict(id=key, name=p['team'] if rules['format'] == 'fixed' else p['name'],
                                    games=0, wins=0, draws=0, losses=0, differential=0, scored_games=0))
    for match in matches:
        if match['status'] not in ('confirmed', 'forfeit'):
            continue
        for side, ids in enumerate((match['a'], match['b']), 1):
            keys = {names[pid]['team'] if rules['format'] == 'fixed' else pid for pid in ids}
            for key in keys:
                record = records[key]
                record['games'] += 1
                record['wins' if match['winner'] == side else 'draws' if match['winner'] == 0 else 'losses'] += 1
                if match['status'] == 'confirmed':
                    difference = match['score_a'] - match['score_b']
                    record['differential'] += difference if side == 1 else -difference
                    record['scored_games'] += 1
    for record in records.values():
        record['percentage'] = round(100 * (record['wins'] + record['draws'] / 2) / record['games'], 1) if record['games'] else 0
        record['average_differential'] = round(record['differential'] / record['scored_games'], 2) if record['scored_games'] else 0
        record['eligible'] = record['games'] >= rules['minimum_games']
    def rank_key(record):
        primary = record['wins'] + record['draws'] / 2 if rules['format'] == 'fixed' else record['percentage']
        return (record['eligible'], primary, record['average_differential'])
    ordered = sorted(records.values(), key=rank_key, reverse=True)
    previous, rank = None, 0
    for index, record in enumerate(ordered, 1):
        key = rank_key(record)
        if key != previous:
            rank = index
        record['rank'] = rank if record['eligible'] else None
        previous = key
    return ordered


def snapshot(db, event_id, uid):
    event, host = access(db, event_id, uid)
    plan = dict(db.execute('SELECT e.*,p.latitude,p.longitude FROM playing_events e LEFT JOIN '
                          'playing_event_places p ON p.event_id=e.id WHERE e.id=?', (event_id,)).fetchone())
    players = [dict(p) for p in db.execute('SELECT * FROM competition_players WHERE event_id=? ORDER BY rowid', (event_id,))]
    rounds = [dict(r) for r in db.execute('SELECT * FROM competition_rounds WHERE event_id=? ORDER BY number', (event_id,))]
    matches = matches_for(db, event_id)
    rules = json.loads(event['settings'])
    team_by_player = {p['id']: p['team'] for p in players}
    teams = {p['team'] for p in players if p['team']}
    completed_pairs = {tuple(sorted((team_by_player[m['a'][0]], team_by_player[m['b'][0]])))
                       for m in matches if m['status'] in ('confirmed', 'forfeit')}
    fixed_complete = rules['format'] == 'fixed' and len(teams) >= 2 and all(
        tuple(sorted(pair)) in completed_pairs for pair in combinations(teams, 2))
    hosts = [r['user_id'] for r in db.execute('SELECT user_id FROM competition_hosts WHERE event_id=?', (event_id,))]
    organizers = [dict(r) for r in db.execute('SELECT u.id,u.display_name FROM competition_hosts h JOIN users u '
                 'ON u.id=h.user_id WHERE h.event_id=?', (event_id,))]
    for player in players:
        player['is_me'] = player['user_id'] == uid
        player['is_host'] = player['user_id'] in hosts
    audit = [dict(r) for r in db.execute('SELECT actor,action,detail,created_at FROM competition_audit '
              'WHERE event_id=? ORDER BY id DESC LIMIT 50', (event_id,))] if host else []
    return dict(id=event_id, title=event['title'], phase=event['phase'], version=event['version'],
                rules=rules, plan=plan, is_host=host, is_owner=event['owner'] == uid, fixed_complete=fixed_complete,
                invite=event['invite'] if host else None, players=players, rounds=rounds,
                matches=matches, organizers=organizers, standings=standings(players, matches, rules), audit=audit)


def add_player(db, event_id, uid, name):
    if db.execute('SELECT COUNT(*) FROM competition_players WHERE event_id=?', (event_id,)).fetchone()[0] >= 32:
        fail('This event supports up to 32 players.')
    if uid:
        if db.execute('SELECT 1 FROM competition_players WHERE event_id=? AND user_id=?', (event_id, uid)).fetchone():
            fail('This player is already on the roster.')
        user = db.execute('SELECT display_name FROM users WHERE id=?', (uid,)).fetchone()
        if not user:
            fail('Player not found.', 404)
        name = user['display_name']
    if not name.strip():
        fail('Enter a player name.')
    db.execute('INSERT INTO competition_players(id,event_id,user_id,name) VALUES (?,?,?,?)',
               (str(uuid.uuid4()), event_id, uid, name.strip()))


def apply_command(db, event, uid, host, body):
    event_id = event['event_id']
    rules = json.loads(event['settings'])
    if body.action not in ('score', 'confirm', 'dispute') and not host:
        fail('Only an organizer can do this.', 403)
    if event['phase'] == 'finished':
        fail('This event is finished. Results are locked.')
    rounds = list(db.execute('SELECT * FROM competition_rounds WHERE event_id=? ORDER BY number', (event_id,)))
    current = rounds[-1] if rounds else None
    players = [dict(p) for p in db.execute('SELECT * FROM competition_players WHERE event_id=?', (event_id,))]
    player = next((p for p in players if p['id'] == body.player_id), None)
    draft = current and current['status'] == 'draft'
    if body.action in ('attendance', 'team', 'add_player', 'courts') and draft:
        fail('Discard the round preview before changing the roster or courts.')
    if body.action in ('team', 'add_player') and rounds and rules['format'] == 'fixed':
        fail('Fixed teams are locked once the first round is generated.')
    if body.action == 'settings':
        if rounds:
            fail('Event rules lock once rounds exist. Discard an unstarted first preview to edit.')
        if not body.rules or not body.plan or not body.title.strip():
            fail('Complete the event details.')
        courts_valid(body.rules.courts)
        values = body.plan.values()
        db.execute('UPDATE competitions SET title=?,settings=? WHERE event_id=?',
                   (body.title.strip(), body.rules.model_dump_json(), event_id))
        db.execute('UPDATE playing_events SET kind=?,location=?,address=?,starts_at=?,ends_at=?,timezone=?,visibility=?,note=?,updated_at=? WHERE id=?',
                   (*values, iso(), event_id))
        save_place(db, event_id, body.plan)
    elif body.action == 'add_player':
        add_player(db, event_id, body.user_id, body.name)
    elif body.action in ('host', 'remove_host'):
        if event['owner'] != uid:
            fail('Only the event owner can manage organizers.', 403)
        target = body.user_id or (player['user_id'] if player else None)
        if not target or not db.execute('SELECT 1 FROM users WHERE id=?', (target,)).fetchone():
            fail('A co-organizer needs an account.')
        if body.action == 'remove_host':
            if target == event['owner']:
                fail('The event owner must remain an organizer.')
            db.execute('DELETE FROM competition_hosts WHERE event_id=? AND user_id=?', (event_id, target))
        else:
            db.execute('INSERT OR IGNORE INTO competition_hosts VALUES (?,?)', (event_id, target))
    elif body.action in ('attendance', 'team'):
        if not player:
            fail('Player not found.', 404)
        field, value = ('availability', body.availability) if body.action == 'attendance' else ('team', body.team.strip())
        db.execute(f'UPDATE competition_players SET {field}=? WHERE id=?', (value, player['id']))
    elif body.action == 'courts':
        courts_valid(body.courts)
        rules['courts'] = [c.strip() for c in body.courts]
        db.execute('UPDATE competitions SET settings=? WHERE event_id=?', (json.dumps(rules), event_id))
    elif body.action == 'generate':
        if event['phase'] == 'paused':
            fail('Resume the event before generating games.')
        if current and current['status'] != 'completed':
            fail('Resolve every match in the current round first.')
        if len(rounds) >= 50:
            fail('An event supports up to 50 rounds.')
        history = matches_for(db, event_id)
        try:
            pairings = schedule(players, history, len(rules['courts']), rules['format'] == 'fixed')
        except ValueError as error:
            fail(str(error))
        rid, number = str(uuid.uuid4()), len(rounds) + 1
        db.execute('INSERT INTO competition_rounds(id,event_id,number) VALUES (?,?,?)', (rid, event_id, number))
        for i, (a, b) in enumerate(pairings):
            label = rules['courts'][i].strip()
            court = f'Court {label}' if label.isdigit() else label or f'Match {i + 1}'
            db.execute('INSERT INTO competition_matches(id,round_id,court,a,b) VALUES (?,?,?,?,?)',
                       (str(uuid.uuid4()), rid, court, json.dumps(a), json.dumps(b)))
    elif body.action == 'discard':
        if not draft:
            fail('Only an unstarted preview can be discarded.')
        db.execute('DELETE FROM competition_rounds WHERE id=?', (current['id'],))
    elif body.action == 'swap':
        if not draft or rules['format'] != 'rotating':
            fail('Player swaps are available in rotating-partner previews.')
        other = next((p for p in players if p['id'] == body.other_id), None)
        if not player or not other or player['availability'] != 'ready' or other['availability'] != 'ready':
            fail('Choose two available players.')
        for match in matches_for(db, event_id):
            if match['round_id'] != current['id']:
                continue
            teams = [[body.other_id if pid == body.player_id else body.player_id if pid == body.other_id else pid
                      for pid in match[side]] for side in ('a', 'b')]
            db.execute('UPDATE competition_matches SET a=?,b=? WHERE id=?', (json.dumps(teams[0]), json.dumps(teams[1]), match['id']))
    elif body.action == 'start':
        if not draft or event['phase'] == 'paused':
            fail('Generate a preview and resume the event before starting.')
        db.execute("UPDATE competition_rounds SET status='live',started_at=? WHERE id=?", (iso(), current['id']))
        db.execute("UPDATE competition_matches SET status='live' WHERE round_id=?", (current['id'],))
        db.execute("UPDATE competitions SET phase='live' WHERE event_id=?", (event_id,))
        for match in matches_for(db, event_id):
            if match['round_id'] == current['id']:
                db.executemany('UPDATE competition_players SET last_round=? WHERE id=?',
                               [(current['number'], pid) for pid in match['a'] + match['b']])
    elif body.action in ('score', 'confirm', 'dispute', 'void', 'forfeit'):
        match = next((m for m in matches_for(db, event_id) if m['id'] == body.match_id), None)
        if not match or match['status'] == 'scheduled':
            fail('Start the match before recording its result.')
        me = next((p['id'] for p in players if p['user_id'] == uid), None)
        my_side = 1 if me in match['a'] else 2 if me in match['b'] else 0
        if not host and (not my_side or match['status'] in ('confirmed', 'forfeit', 'void')):
            fail('You cannot change this result.', 403)
        submitter = next((p['id'] for p in players if p['user_id'] == match['submitted_by']), None)
        submitted_side = 1 if submitter in match['a'] else 2 if submitter in match['b'] else 0
        if body.action == 'score':
            a, b = body.score_a, body.score_b
            if not rules['minutes']:
                high, low = max(a, b), min(a, b)
                if high < rules['target'] or high - low < rules['win_by'] or (high > rules['target'] and
                        (rules['win_by'] == 1 or high - low != rules['win_by'])):
                    fail(f"Enter a final score to {rules['target']}, win by {rules['win_by']}.")
            if host:
                status = 'confirmed'
            elif match['status'] in ('submitted', 'disputed'):
                if match['status'] == 'submitted' and uid == match['submitted_by']:
                    status = 'submitted'
                else:
                    if my_side == submitted_side:
                        fail('An opponent or organizer must confirm this score.')
                    status = 'confirmed' if match['status'] == 'submitted' and (a, b) == (match['score_a'], match['score_b']) else 'disputed'
                if status == 'disputed':
                    db.execute("UPDATE competition_matches SET status='disputed' WHERE id=?", (match['id'],))
                    return
            else:
                status = 'submitted'
            db.execute('UPDATE competition_matches SET status=?,score_a=?,score_b=?,submitted_by=?,winner=?,reason=? WHERE id=?',
                       (status, a, b, uid, 1 if a > b else 2 if b > a else 0, body.reason, match['id']))
        elif body.action in ('confirm', 'dispute'):
            if match['status'] != 'submitted' or (not host and my_side == submitted_side):
                fail('This score needs confirmation from the opposing team or organizer.')
            db.execute('UPDATE competition_matches SET status=? WHERE id=?',
                       ('confirmed' if body.action == 'confirm' else 'disputed', match['id']))
        else:
            if not body.reason.strip():
                fail('Add a reason for this result.')
            db.execute('UPDATE competition_matches SET status=?,score_a=NULL,score_b=NULL,winner=?,reason=? WHERE id=?',
                       ('void' if body.action == 'void' else 'forfeit', None if body.action == 'void' else body.winner,
                        body.reason.strip(), match['id']))
        remaining = db.execute("SELECT 1 FROM competition_matches WHERE round_id=? AND status NOT IN ('confirmed','void','forfeit')",
                               (match['round_id'],)).fetchone()
        db.execute('UPDATE competition_rounds SET status=? WHERE id=?', ('live' if remaining else 'completed', match['round_id']))
    elif body.action in ('pause', 'resume'):
        db.execute('UPDATE competitions SET phase=? WHERE event_id=?', ('paused' if body.action == 'pause' else 'live', event_id))
    elif body.action == 'finish':
        if current and current['status'] != 'completed':
            fail('Resolve the current round or discard its preview before finishing.')
        db.execute("UPDATE competitions SET phase='finished' WHERE event_id=?", (event_id,))
    elif body.action == 'rotate_invite':
        db.execute('UPDATE competitions SET invite=? WHERE event_id=?', (secrets.token_urlsafe(24), event_id))


def router(require_user, check_origin):
    routes = APIRouter(prefix='/api/competitions')

    @routes.get('')
    def listing(request: Request, response: Response):
        uid = require_user(request)['id']
        response.headers['Cache-Control'] = 'private, no-store'
        with connect() as db:
            return [dict(r) for r in db.execute('''SELECT c.event_id AS id,c.title,c.phase,e.starts_at,e.location
                FROM competitions c JOIN playing_events e ON e.id=c.event_id WHERE
                EXISTS(SELECT 1 FROM competition_hosts h WHERE h.event_id=c.event_id AND h.user_id=?) OR
                EXISTS(SELECT 1 FROM competition_players p WHERE p.event_id=c.event_id AND p.user_id=?)
                ORDER BY e.starts_at DESC LIMIT 100''', (uid, uid))]

    @routes.post('')
    def create(body: CreateCompetition, request: Request):
        check_origin(request)
        user = require_user(request)
        values = body.plan.values()
        courts_valid(body.rules.courts)
        if not body.title.strip():
            fail('Enter an event name.')
        event_id = str(uuid.uuid4())
        with connect(immediate=True) as db:
            count = db.execute('SELECT COUNT(*) FROM playing_events WHERE user_id=? AND ends_at>?', (user['id'], iso())).fetchone()[0]
            if count >= 100:
                fail('You can keep up to 100 upcoming events.')
            db.execute('INSERT INTO playing_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', (event_id, user['id'], *values, iso(), iso()))
            save_place(db, event_id, body.plan)
            db.execute('INSERT INTO competitions(event_id,title,settings,invite) VALUES (?,?,?,?)',
                       (event_id, body.title.strip(), body.rules.model_dump_json(), secrets.token_urlsafe(24)))
            db.execute('INSERT INTO competition_hosts VALUES (?,?)', (event_id, user['id']))
            if body.playing:
                add_player(db, event_id, user['id'], user['display_name'])
            return snapshot(db, event_id, user['id'])

    @routes.post('/join')
    def join(body: JoinCompetition, request: Request):
        check_origin(request)
        user = require_user(request)
        with connect(immediate=True) as db:
            event = db.execute('SELECT * FROM competitions WHERE invite=?', (body.token,)).fetchone()
            if not event:
                fail('This invitation is no longer available.', 404)
            existing = db.execute('SELECT 1 FROM competition_players WHERE event_id=? AND user_id=?', (event['event_id'], user['id'])).fetchone()
            if not existing:
                if event['phase'] == 'finished':
                    fail('This event is finished.')
                current = db.execute('SELECT status FROM competition_rounds WHERE event_id=? ORDER BY number DESC LIMIT 1', (event['event_id'],)).fetchone()
                if current and (current['status'] == 'draft' or json.loads(event['settings'])['format'] == 'fixed'):
                    fail('The roster is locked. Contact the organizer.')
                add_player(db, event['event_id'], user['id'], user['display_name'])
                db.execute('UPDATE competitions SET version=version+1 WHERE event_id=?', (event['event_id'],))
                db.execute('INSERT INTO competition_audit(event_id,actor,action,detail,created_at) VALUES (?,?,?,?,?)',
                           (event['event_id'], user['id'], 'joined', json.dumps({'name': user['display_name']}), iso()))
            return snapshot(db, event['event_id'], user['id'])

    @routes.get('/{event_id}')
    def get(event_id: str, request: Request, response: Response):
        uid = require_user(request)['id']
        response.headers['Cache-Control'] = 'private, no-store'
        with connect() as db:
            return snapshot(db, event_id, uid)

    @routes.post('/{event_id}/commands')
    def command(event_id: str, body: Command, request: Request):
        check_origin(request)
        uid = require_user(request)['id']
        digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
        with connect(immediate=True) as db:
            event, host = access(db, event_id, uid)
            receipt = db.execute('SELECT digest FROM competition_commands WHERE event_id=? AND actor=? AND request_id=?',
                                 (event_id, uid, str(body.request_id))).fetchone()
            if receipt:
                if receipt['digest'] != digest:
                    fail('This request was already used for a different change.', 409)
                return snapshot(db, event_id, uid)
            if event['version'] != body.version:
                fail('This event changed. Review the latest state and try again.', 409)
            apply_command(db, event, uid, host, body)
            db.execute('UPDATE competitions SET version=version+1 WHERE event_id=?', (event_id,))
            db.execute('INSERT INTO competition_commands VALUES (?,?,?,?)', (event_id, uid, str(body.request_id), digest))
            db.execute('INSERT INTO competition_audit(event_id,actor,action,detail,created_at) VALUES (?,?,?,?,?)',
                       (event_id, uid, body.action, body.model_dump_json(), iso()))
            return snapshot(db, event_id, uid)

    return routes

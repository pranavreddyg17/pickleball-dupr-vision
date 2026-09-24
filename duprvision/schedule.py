"""Player-entered plans, shared only with current followers of visible profiles."""
from datetime import timedelta, timezone
from typing import Literal
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from pydantic import AwareDatetime, BaseModel, Field

from .core import iso, now


class PlayingEvent(BaseModel):
    kind: Literal['open_play', 'dupr_match', 'practice', 'lesson', 'league', 'tournament', 'other']
    location: str = Field(min_length=1, max_length=120)
    address: str = Field(default='', max_length=200)
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    timezone: str = Field(max_length=80)
    visibility: Literal['followers', 'private'] = 'followers'
    note: str = Field(default='', max_length=300)
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)

    def values(self):
        if (self.latitude is None) != (self.longitude is None):
            raise HTTPException(400, 'Select a complete map location')
        start, end = self.starts_at.astimezone(timezone.utc), self.ends_at.astimezone(timezone.utc)
        if not self.location.strip():
            raise HTTPException(400, 'Enter a court or venue name')
        if end <= start or end - start > timedelta(hours=24):
            raise HTTPException(400, 'End time must be after the start, within 24 hours')
        if end <= now() or start > now() + timedelta(days=366):
            raise HTTPException(400, 'Choose an upcoming time within the next year')
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise HTTPException(400, 'Choose a valid time zone')
        return (self.kind, self.location.strip(), self.address.strip(), iso(start), iso(end),
                self.timezone, self.visibility, self.note.strip())


def save_place(db, event_id, body):
    if body.latitude is None:
        db.execute('DELETE FROM playing_event_places WHERE event_id=?', (event_id,))
    else:
        db.execute('INSERT OR REPLACE INTO playing_event_places VALUES (?,?,?)',
                   (event_id, body.latitude, body.longitude))


def visible_events(db, viewer, start, end, view='all', player_id=None):
    if start.tzinfo is None or end.tzinfo is None or end <= start or end-start > timedelta(days=93):
        raise HTTPException(400, 'Choose a calendar range of up to three months with a time zone')
    if view not in ('all', 'mine', 'following'):
        raise HTTPException(400, 'Invalid calendar view')
    # Privacy is evaluated on every read, including after unfollowing or hiding a profile.
    query = """SELECT e.*, u.display_name, loc.latitude, loc.longitude, c.title AS competition_title,
        c.phase AS competition_phase,
        (EXISTS(SELECT 1 FROM competition_hosts h WHERE h.event_id=e.id AND h.user_id=?) OR
         EXISTS(SELECT 1 FROM competition_players cp WHERE cp.event_id=e.id AND cp.user_id=?)) AS competition_access
        FROM playing_events e JOIN users u ON u.id=e.user_id
        LEFT JOIN playing_event_places loc ON loc.event_id=e.id
        LEFT JOIN competitions c ON c.event_id=e.id
        WHERE e.starts_at < ? AND e.ends_at > ? AND (e.user_id=? OR
          EXISTS(SELECT 1 FROM competition_hosts h WHERE h.event_id=e.id AND h.user_id=?) OR
          EXISTS(SELECT 1 FROM competition_players cp WHERE cp.event_id=e.id AND cp.user_id=?) OR
          (e.visibility='followers' AND EXISTS(SELECT 1 FROM profile_settings p
            WHERE p.user_id=e.user_id AND p.discoverable=1) AND EXISTS(SELECT 1 FROM follows f
            WHERE f.follower_id=? AND f.followed_id=e.user_id)))"""
    args = [viewer, viewer, iso(end.astimezone(timezone.utc)), iso(start.astimezone(timezone.utc)), viewer, viewer, viewer, viewer]
    if view == 'mine':
        query += ''' AND (e.user_id=? OR
            EXISTS(SELECT 1 FROM competition_hosts h WHERE h.event_id=e.id AND h.user_id=?) OR
            EXISTS(SELECT 1 FROM competition_players cp WHERE cp.event_id=e.id AND cp.user_id=?))'''
        args.extend([viewer, viewer, viewer])
    elif view == 'following':
        query += ' AND e.user_id!=? AND EXISTS(SELECT 1 FROM follows f WHERE f.follower_id=? AND f.followed_id=e.user_id)'
        args.extend([viewer, viewer])
    if player_id:
        query += ' AND e.user_id=?'
        args.append(player_id)
    rows = db.execute(query + ' ORDER BY e.starts_at, e.id LIMIT 501', args).fetchall()
    events = []
    for row in rows[:500]:
        event = dict(row)
        event['is_owner'] = event['user_id'] == viewer
        query = (f"{event['latitude']},{event['longitude']}" if event['latitude'] is not None
                 else ', '.join(filter(None, [event['location'], event['address']])))
        event['maps_url'] = 'https://www.google.com/maps/search/?' + urlencode({'api': 1, 'query': query})
        events.append(event)
    return {'events': events, 'has_more': len(rows) > 500}

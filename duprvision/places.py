"""Small, cached place searches against a configurable Photon service."""
import math
import os
import threading
import time
from collections import OrderedDict

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field


class PlaceSearch(BaseModel):
    query: str = Field(min_length=3, max_length=160)


_lock = threading.Lock()
_cache = OrderedDict()
_last_request = 0.0


def search_places(body):
    global _last_request
    query = ' '.join(body.query.split())
    if len(query) < 3:
        raise HTTPException(400, 'Enter at least three characters')
    url = os.getenv('PLACE_SEARCH_URL', 'https://photon.komoot.io/api/').strip()
    if not url:
        raise HTTPException(503, 'Place search is unavailable. Choose on the map or enter the location yourself.')
    key = (url, query.casefold())
    with _lock:
        stamp = time.monotonic()
        cached = _cache.get(key)
        if cached and stamp - cached[0] < 86400:
            _cache.move_to_end(key)
            return cached[1]
        # One outbound lookup per second across the app, with no automatic retries.
        if stamp - _last_request < 1:
            raise HTTPException(429, 'Place search is busy. Try again in a moment.', headers={'Retry-After': '1'})
        _last_request = stamp
    try:
        response = httpx.get(url, params={'q': query, 'limit': 6, 'lang': 'en'}, timeout=8,
                             headers={'User-Agent': 'DUPRVision/1.0 (+https://pickle.duprvision.workers.dev)'})
        response.raise_for_status()
        features = response.json()['features']
        if not isinstance(features, list):
            raise ValueError('Invalid places response')
        results = []
        for feature in features[:6]:
            try:
                props = feature['properties']
                lon, lat = map(float, feature['geometry']['coordinates'])
                if not math.isfinite(lat) or not math.isfinite(lon) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    continue
                name = str(props.get('name') or props.get('street') or props.get('city') or '').strip()[:120]
                street = ' '.join(str(props[k]) for k in ('housenumber', 'street') if props.get(k))
                parts = [street, props.get('city') or props.get('town') or props.get('district'),
                         props.get('state'), props.get('postcode'), props.get('country')]
                address = ', '.join(dict.fromkeys(str(p) for p in parts if p))[:200]
                if name:
                    results.append({'location': name, 'address': address, 'latitude': lat, 'longitude': lon})
            except (KeyError, TypeError, ValueError):
                continue
        result = {'places': results}
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(503, 'Place search is unavailable. Choose on the map or enter the location yourself.') from exc
    with _lock:
        _cache[key] = (time.monotonic(), result)
        _cache.move_to_end(key)
        while len(_cache) > 256:
            _cache.popitem(last=False)
    return result

"""Keep the served asset inventory and active review contract in sync."""
import json
import re

import pytest

from duprvision import core
from duprvision.assessment import Assessment
from duprvision.review import provider_schema, valid_coaching_note


def test_every_first_party_asset_is_referenced_and_served(clients):
    client, _ = clients
    static = core.ROOT / 'static'
    index = (static / 'index.html').read_text()
    urls = set(re.findall(r'(?:src|href)="(/[^"?]+)', index))
    manifest = json.loads((static / 'manifest.webmanifest').read_text())
    urls.update(icon['src'] for icon in manifest['icons'])
    assert {p.name for p in static.iterdir() if p.is_file()} == {'index.html', *(url[1:] for url in urls if '/' not in url[1:])}
    for url in urls:
        assert client.get(url).status_code == 200, url
    source = '\n'.join(p.read_text() for p in static.glob('*.js'))
    for stylesheet in static.glob('*.css'):
        css = stylesheet.read_text()
        assert css.count('/*') == css.count('*/'), stylesheet.name
    icons = set(re.findall(r"icon\('([^']+)'\)", source))
    assert icons == {p.stem for p in (static / 'icons').glob('*.svg')}
    for name in icons:
        assert client.get(f'/icons/{name}.svg').status_code == 200
    for path in ('/overview.css', '/icons/house.svg', '/.env', '/api/estimate', '/api/progress'):
        assert client.get(path).status_code == 404


def test_current_schema_keeps_local_validation_bounds():
    schema = provider_schema(Assessment)
    assert 'maxItems' not in schema['properties']['shots']
    assert 'rating' not in schema['properties']
    from test_flow import compact_assessment
    raw = compact_assessment()
    raw['shots'] *= 20
    with pytest.raises(ValueError):
        Assessment.model_validate(raw)


@pytest.mark.parametrize('note,valid', [
    ('Try an attack at 12:00.', False),
    ('Aim your dinks just inside the baseline.', False),
    ('Keep the paddle prepared.', True),
])
def test_coaching_note_validation_remains_active(note, valid):
    assert valid_coaching_note(note, 60) is valid

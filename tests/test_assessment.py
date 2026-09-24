import copy
import json

import pytest

from duprvision import core
from duprvision.assessment import validate_assessment
from duprvision.quality import reconcile_track
from test_flow import add_result, compact_assessment


def sample(count=3, pressure='routine', confidence='high', control='controlled'):
    raw = compact_assessment()
    template = raw['shots'][0]
    raw['shots'] = [{**template, 'timestamp':2 + i * 3, 'control':control,
                     'balanced':True, 'recovered':True, 'pressure':pressure,
                     'confidence':confidence} for i in range(count)]
    raw['rallies'] = [{'start':0, 'end':max(12, count * 3 + 3)}]
    return raw


def test_small_easy_sample_cannot_produce_elite_looking_score():
    result = validate_assessment(sample(), 60)
    assert result['performance']['score'] == 61
    assert result['performance']['version'] == 'vision_score_v2'
    assert result['performance']['sample_scope'] == 'short'
    assert validate_assessment(sample(pressure='pressured'), 60)['performance']['score'] == 67
    assert validate_assessment(sample(pressure='unknown'), 60)['performance']['score'] == 55
    assert validate_assessment(sample(confidence='medium'), 60)['performance']['score'] < 61
    assert validate_assessment(sample(), 60) == result


def test_repetition_reduces_shrinkage_but_does_not_invent_other_skills():
    result = validate_assessment(sample(12), 60)
    assert 61 < result['performance']['score'] < 85
    assert result['game_areas'] == [
        {'name':'Serve & return','observations':0}, {'name':'Groundstrokes','observations':0},
        {'name':'Soft game','observations':12}, {'name':'Net exchanges','observations':0}]
    assert result['performance']['sample_scope'] == 'short'  # Only one rally.


@pytest.mark.parametrize('field,value', [('evidence',''),('confidence','low'),('control','unknown'),
                                        ('balanced',None),('recovered',None)])
def test_missing_evidence_cannot_fill_a_score(field, value):
    raw = sample()
    raw['shots'][0][field] = value
    assert validate_assessment(raw, 60)['performance']['score'] is None


def test_invisible_ball_redacts_shot_claims():
    raw = sample()
    raw['ball_visible'] = False
    result = validate_assessment(raw, 60)
    assert result['performance']['score'] is None
    assert all(s['shot_type'] == 'unknown' and not s['scored'] for s in result['shots'])
    assert result['shot_counts'] == {}


def test_tracking_reconciliation_uses_current_rubric_and_coverage():
    result = validate_assessment(sample(), 60)
    track = [(i / 5, (10,10,100,180)) for i in range(300) if not 1.6 <= i / 5 <= 2.4]
    revised = reconcile_track(result, track, 60)
    assert revised['performance']['version'] == 'vision_score_v2'
    assert revised['performance']['score'] is None
    assert not revised['shots'][0]['scored']
    assert revised['game_areas'][2]['observations'] == 2


def test_single_outcome_change_has_bounded_effect_on_short_sample():
    raw = sample()
    original = validate_assessment(raw, 60)['performance']['score']
    raw['shots'][0]['control'] = 'error'
    assert 0 < original - validate_assessment(raw, 60)['performance']['score'] <= 7


def test_versions_never_mix_and_identical_evidence_is_not_new_progress(clients):
    a, _ = clients
    uid = a.get('/api/me').json()['id']
    add_result(uid, 'old', 99, core.iso())
    for name in ('new','duplicate'):
        add_result(uid, name, None, core.iso())
        report = validate_assessment(sample(), 60)
        with core.connect() as db:
            db.execute('UPDATE analyses SET result_json=? WHERE video_id=?', (json.dumps(report), name))
            db.execute('INSERT INTO review_cache_keys VALUES (?,?)', (name, 'shared-evidence'))
    history = a.get('/api/scores').json()
    assert history['average'] == 61 and history['kind'] == 'vision_score_v2'
    assert history['earlier_reports'] == 1 and history['rated_clips'] == 1
    assert history['clips'] == 3 and 'dupr_equivalent' not in history
    assert history['scored_days'] == 1
    assert a.get('/api/videos/old').json()['result']['performance']['score'] == 99


def test_schema_rejects_missing_pressure_or_evidence():
    raw = sample()
    for key in ('pressure','evidence'):
        broken = copy.deepcopy(raw)
        del broken['shots'][0][key]
        with pytest.raises(ValueError):
            validate_assessment(broken, 60)


def test_analysis_assets_are_served_without_exposing_files(clients):
    a, _ = clients
    for asset in ('analyze.js','analyze.css'):
        assert a.get('/'+asset).status_code == 200
    assert a.get('/court.png').status_code == 404
    assert a.get('/assessment.py').status_code == 404

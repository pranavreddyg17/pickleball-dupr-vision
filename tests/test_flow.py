import json
import subprocess

import pytest

from fastapi.testclient import TestClient

from duprvision import app as web
from duprvision import core, worker


def make_video(path, seconds=60, dimensions="160x160"):
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
        f"color=c=green:s={dimensions}:r=1:d={seconds}", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)
    ], check=True)


def test_auth_upload_quota_worker_and_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DATA", tmp_path)
    monkeypatch.setattr(core, "DB", tmp_path / "duprvision.sqlite3")
    monkeypatch.setattr(web, "DATA", tmp_path)
    monkeypatch.setattr(web, "DB", tmp_path / "duprvision.sqlite3")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("INVITE_CODE", "")
    monkeypatch.setenv("ANALYSIS_ENGINE", "local")
    source = tmp_path / "valid.mp4"
    make_video(source)
    with TestClient(web.app) as client:
        response = client.post("/api/register", json={"email": "player@example.com", "password": "long-password", "display_name": "Player"})
        assert response.status_code == 200
        assert client.get("/api/me").json()["remaining"] == 5
        assert client.post("/api/login", json={"email": "player@example.com", "password": "wrong-password"}).status_code == 401

        rejected = client.post("/api/videos", content=b"not a video", headers={"X-Filename": "bad.mp4"})
        assert rejected.status_code == 400
        assert client.get("/api/me").json()["remaining"] == 5

        first = client.post("/api/videos", content=source.read_bytes(), headers={"X-Filename": "match.mp4"})
        assert first.status_code == 200, first.text
        video_id = first.json()["id"]
        assert client.get("/api/me").json()["remaining"] == 4
        with core.connect() as db:
            row = dict(db.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone())
        worker.process(row)
        assert client.get(f"/api/videos/{video_id}").json()["status"] == "WAITING_FOR_PLAYER"
        assert client.get(f"/api/videos/{video_id}/preview/1").status_code == 200
        assert client.post(f"/api/videos/{video_id}/select", json={"timestamp_seconds": 6, "x": .5, "y": .5, "consent": False}).status_code == 400
        assert client.post(f"/api/videos/{video_id}/select", json={"timestamp_seconds": 6, "x": .5, "y": .5, "consent": True}).status_code == 200

        monkeypatch.setattr(worker, "track_and_analyze", lambda row, selection: {
            "kind": "pose_review_v1", "rating": None, "subject_visibility": .9,
            "score_date": "2026-09-22", "limitations": []})
        with core.connect() as db:
            row = dict(db.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone())
        worker.process(row)
        assert client.get(f"/api/videos/{video_id}").json()["result"]["rating"] is None
        assert client.get("/api/scores").json()["average"] is None
        assert client.get("/api/scores").json()["clips"] == 1
        assert not core.video_dir(video_id).exists()
        assert client.get(f"/api/videos/{video_id}/preview/1").status_code == 410
        assert client.get("/api/estimate").json()["profile"] is None

        for _ in range(4):
            assert client.post("/api/videos", content=source.read_bytes(), headers={"X-Filename": "match.mp4"}).status_code == 200
        assert client.post("/api/videos", content=source.read_bytes(), headers={"X-Filename": "match.mp4"}).status_code == 429
        assert client.delete(f"/api/videos/{video_id}").status_code == 200
        assert client.get("/api/estimate").json()["profile"] is None
        assert client.get("/api/scores").json()["average"] is None
        assert client.get(f"/api/videos/{video_id}/preview/1").status_code == 404
        assert client.get("/api/me").json()["remaining"] == 0


def test_aggregate_resists_one_outlier():
    results = [{"best_estimate": value, "duration_seconds": 60} for value in (3.7, 3.6, 4.8, 3.7, 3.8)]
    profile = core.aggregate(results)
    assert profile["estimate"] == 3.7
    assert profile["sessions"] == 5
    assert profile["observed_seconds"] == 300


def test_login_is_limited(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DATA", tmp_path)
    monkeypatch.setattr(core, "DB", tmp_path / "duprvision.sqlite3")
    with TestClient(web.app) as client:
        for _ in range(10):
            assert client.post("/api/login", json={"email": "nobody@example.com", "password": "wrong"}).status_code == 401
        assert client.post("/api/login", json={"email": "nobody@example.com", "password": "wrong"}).status_code == 429


def test_registration_does_not_require_invite_code(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DATA", tmp_path)
    monkeypatch.setattr(core, "DB", tmp_path / "duprvision.sqlite3")
    monkeypatch.setenv("INVITE_CODE", "old-code")
    with TestClient(web.app) as client:
        response = client.post("/api/register", json={
            "email": "new@example.com", "password": "long-password", "display_name": "New Player"
        })
        assert response.status_code == 200
        assert client.get("/api/me").json()["display_name"] == "New Player"


@pytest.mark.parametrize("speed,expected", [(0, 0), (.05, 0), (.4, 100)])
def test_motion_score_is_activity_not_skill(speed, expected):
    samples = [{"t": i / 5, "x": 100 + speed * 100 * i / 5, "y": 300, "h": 100} for i in range(300)]
    result = worker.measure_motion(samples, 300)
    assert result["movement_score"] == expected
    assert result["subject_visibility"] == 1
    assert "best_estimate" not in result


def test_motion_rejects_missing_and_fragmented_tracks():
    samples = [{"t": i / 5, "x": 100, "y": 300, "h": 100} for i in range(300)]
    with pytest.raises(RuntimeError, match="coverage"):
        worker.measure_motion(samples[:100], 300)
    with pytest.raises(RuntimeError, match="continuous"):
        worker.measure_motion(samples[::2], 300)


@pytest.fixture
def clients(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DATA", tmp_path)
    monkeypatch.setattr(core, "DB", tmp_path / "duprvision.sqlite3")
    monkeypatch.setattr(web, "DATA", tmp_path)
    monkeypatch.setenv("INVITE_CODE", "")
    monkeypatch.setenv("APP_TIMEZONE", "America/Chicago")
    monkeypatch.setenv("ANALYSIS_ENGINE", "local")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with TestClient(web.app) as a, TestClient(web.app) as b:
        for client, name in ((a,"Alice"),(b,"Bob")):
            assert client.post("/api/register", json={"email": f"{name}@example.com", "password": "a-long-password", "display_name": name}).status_code == 200
        yield a, b


def add_result(user_id, video_id, score, created_at, kind="video_review_v2", score_date=None):
    result = {"kind":kind,"rating":{"estimate":score} if score is not None else None}
    if kind == "video_review_v2":
        result["performance"] = {"score":score}
    if score_date:
        result["score_date"] = score_date
    with core.connect() as db:
        db.execute("INSERT INTO videos VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
            video_id,user_id,"test.mp4",100,60,None,None,"COMPLETED","Complete",None,created_at,created_at))
        db.execute("INSERT INTO analyses VALUES (?,?,?)", (video_id,json.dumps(result),created_at))


@pytest.mark.parametrize("seconds", [1, 26])
def test_short_low_resolution_uploads(clients, tmp_path, seconds):
    client, _ = clients
    source = tmp_path / "short.mp4"
    make_video(source, seconds=seconds, dimensions="144x256")
    response = client.post("/api/videos", content=source.read_bytes(), headers={"X-Filename":"short.mp4"})
    assert response.status_code == 200, response.text
    video = client.get(f"/api/videos/{response.json()['id']}").json()
    assert video["duration_seconds"] == seconds


def test_upload_size_limit_is_100_mb(clients, monkeypatch):
    client, _ = clients
    assert core.MAX_SIZE == web.MAX_SIZE == 100_000_000
    monkeypatch.setattr(web, "MAX_SIZE", 8)
    response = client.post("/api/videos", content=b"123456789", headers={"X-Filename":"oversize.mp4"})
    assert response.status_code == 413
    assert response.json()["detail"] == "Video exceeds the 100 MB limit"
    assert client.get("/api/me").json()["remaining"] == 5
    assert not list((core.DATA / "tmp").iterdir())


def test_daily_calendar_timezone_averages_and_deletion(clients):
    a,_ = clients
    uid=a.get("/api/me").json()["id"]
    add_result(uid,"one",2,"2026-09-22T00:10:00+00:00")
    add_result(uid,"two",6,"2026-09-22T01:10:00+00:00")
    add_result(uid,"three",8,"2026-09-23T01:10:00+00:00")
    add_result(uid,"legacy",99,"2026-09-20T01:10:00+00:00",kind="legacy")
    history=a.get("/api/scores").json()
    assert history["days"] == [{"date":"2026-09-21","score":4.0,"clips":2,"rated_clips":2},{"date":"2026-09-22","score":8.0,"clips":1,"rated_clips":1}]
    assert history["average"] == 6
    assert history["clips"] == 3
    assert a.delete("/api/videos/two").status_code == 200
    assert a.get("/api/scores").json()["average"] == 5


def test_saved_score_date_does_not_shift(clients, monkeypatch):
    a,_=clients
    uid=a.get("/api/me").json()["id"]
    add_result(uid,"saved",4.5,"2026-09-22T01:10:00+00:00",score_date="2026-09-21")
    monkeypatch.setenv("APP_TIMEZONE","Asia/Tokyo")
    assert a.get("/api/scores").json()["days"][0]["date"] == "2026-09-21"


def test_follow_privacy_idempotence_and_isolation(clients):
    a,b=clients
    aid=a.get("/api/me").json()["id"]
    bid=b.get("/api/me").json()["id"]
    assert a.get("/api/players").json()["players"] == []
    assert a.post(f"/api/players/{bid}/follow").status_code == 404
    assert b.put("/api/me",json={"display_name":"Bob","discoverable":True}).status_code == 200
    for _ in range(2):
        assert a.post(f"/api/players/{bid}/follow").status_code == 200
    player=a.get(f"/api/players/{bid}").json()
    assert player["followers"] == 1 and player["is_following"]
    assert "email" not in player and "videos" not in player
    assert len(a.get("/api/players?view=following").json()["players"]) == 1
    assert a.post(f"/api/players/{aid}/follow").status_code == 400
    add_result(bid,"private-media",70,"2026-09-22T12:00:00+00:00")
    assert a.get("/api/videos/private-media").status_code == 404
    assert a.get("/api/videos/private-media/tracking/1").status_code == 404
    assert a.delete("/api/videos/private-media").status_code == 404
    b.put("/api/me",json={"display_name":"Bob","discoverable":False})
    assert a.get(f"/api/players/{bid}").status_code == 404
    assert a.get("/api/players?view=following").json()["players"] == []
    assert a.delete(f"/api/players/{bid}/follow").status_code == 200
    assert b.get(f"/api/players/{bid}").json()["followers"] == 0


def test_health_needs_no_api_key_and_rejects_cross_origin(clients):
    a,_=clients
    assert a.get("/api/health").json()["analysis_engine"] == "local"
    assert a.get("/api/health").json()["analysis_configured"]
    assert a.get("/icons/trash-2.svg").status_code == 200
    assert a.put("/api/me",json={"display_name":"Oops","discoverable":True},headers={"Origin":"https://evil.example"}).status_code == 403


def test_retry_reselects_without_new_quota(clients):
    a,_=clients
    uid=a.get("/api/me").json()["id"]
    add_result(uid,"retry",25,core.iso())
    folder=core.video_dir("retry")
    folder.mkdir()
    normalized=folder / "normalized.mp4"
    normalized.touch()
    with core.connect() as db:
        db.execute("UPDATE videos SET normalized_path=?, status='FAILED' WHERE id='retry'",(str(normalized),))
    before=a.get("/api/me").json()["remaining"]
    assert a.post("/api/videos/retry/retry").status_code == 200
    assert a.get("/api/videos/retry").json()["status"] == "WAITING_FOR_PLAYER"
    assert a.get("/api/scores").json()["average"] is None
    assert a.get("/api/me").json()["remaining"] == before


def test_unrated_reports_missing_days_and_streak(clients, monkeypatch):
    from datetime import datetime, timezone
    a,_=clients
    monkeypatch.setattr(core,"now",lambda:datetime(2026,9,22,12,tzinfo=timezone.utc))
    uid=a.get("/api/me").json()["id"]
    add_result(uid,"unrated",None,"2026-09-21T12:00:00+00:00",kind="pose_review_v1")
    add_result(uid,"prior",4,"2026-09-20T12:00:00+00:00")
    history=a.get("/api/scores").json()
    assert history["average"] == 4
    assert history["streak"] == 2
    assert len(history["days"]) == 2
    assert history["days"][-1]["score"] is None


def test_followers_search_and_unfollow(clients):
    a,b=clients
    aid=a.get("/api/me").json()["id"]
    bid=b.get("/api/me").json()["id"]
    for client,name in ((a,"Alice"),(b,"Bob")):
        client.put("/api/me",json={"display_name":name,"discoverable":True})
    assert a.get("/api/players?q=bo").json()["players"][0]["id"] == bid
    assert a.get("/api/players?q=nobody").json()["players"] == []
    a.post(f"/api/players/{bid}/follow")
    assert b.get("/api/players?view=followers").json()["players"][0]["id"] == aid
    a.delete(f"/api/players/{bid}/follow")
    assert b.get("/api/players?view=followers").json()["players"] == []


def test_mutating_active_job_is_rejected(clients):
    a,_=clients
    uid=a.get("/api/me").json()["id"]
    add_result(uid,"active",50,core.iso())
    with core.connect() as db:
        db.execute("UPDATE videos SET status='ANALYZING' WHERE id='active'")
    assert a.delete("/api/videos/active").status_code == 409
    assert a.post("/api/videos/active/retry").status_code == 409


def test_media_expiry_retains_report_and_history(clients):
    a,_=clients
    uid=a.get("/api/me").json()["id"]
    add_result(uid,"expiry",3.5,core.iso())
    folder=core.video_dir("expiry")
    folder.mkdir()
    for name in ("source.upload","normalized.mp4","preview-1.jpg","tracking-1.jpg"):
        (folder/name).write_bytes(b"test media")
    with core.connect() as db:
        db.execute("UPDATE videos SET normalized_path=? WHERE id='expiry'",(str(folder/"normalized.mp4"),))
    core.cleanup_media()
    assert not folder.exists()
    assert a.get("/api/scores").json()["average"] == 3.5
    assert a.get("/api/videos/expiry").json()["result"]["rating"]["estimate"] == 3.5
    assert a.get("/api/videos/expiry/preview/1").status_code == 410
    assert a.get("/api/videos/expiry/tracking/1").status_code == 410
    assert a.post("/api/videos/expiry/retry").status_code == 409


def test_abandoned_media_expires_but_active_job_does_not(clients):
    from datetime import timedelta
    a,_=clients
    uid=a.get("/api/me").json()["id"]
    for vid,status in (("abandoned","WAITING_FOR_PLAYER"),("running","ANALYZING")):
        add_result(uid,vid,None,core.iso(core.now()-timedelta(days=2)))
        folder=core.video_dir(vid)
        folder.mkdir()
        (folder/"normalized.mp4").touch()
        with core.connect() as db:
            db.execute("UPDATE videos SET status=?,normalized_path=? WHERE id=?",(status,str(folder/"normalized.mp4"),vid))
    core.cleanup_media()
    assert a.get("/api/videos/abandoned").json()["status"] == "EXPIRED"
    assert not core.video_dir("abandoned").exists()
    assert core.video_dir("running").exists()


def valid_review():
    return {"subject_identified":True,"ball_visible":True,
            "summary":"The selected player used measured returns and several soft shots. Test fixture, not a real coaching assessment.",
            "shots":[{"timestamp":t,"shot_type":"drive" if i%2 else "drop","confidence":"high","observation":"Test-only shot observation"} for i,t in enumerate((2,4,8,17,19,22,33,36))],
            "rallies":[{"start":s,"end":e,"observation":"Test-only rally"} for s,e in ((0,12),(15,25),(30,45))],
            "strengths":[],"priorities":[],"limitations":["Test fixture"],
            "rating":{"estimate":3.5,"low":3.0,"high":4.0,"rationale":"Test-only supported rating range, not a real assessment."}}


def compact_review():
    return {"subject_identified":True,"ball_visible":True,
            "summary":"Controlled kitchen play with stable contact. Recover earlier after wide shots.",
            "priority":"Keep the paddle ready after contact.","recording_note":"",
            "shots":[{"timestamp":t,"shot_type":"dink","confidence":"high","control":"neutral",
                      "balanced":True,"recovered":i%2==0} for i,t in enumerate((2,4,8,17,19,22,33,36))],
            "rallies":[{"start":0,"end":40}]}


def test_review_evidence_gates_and_timestamps():
    from duprvision.review import validate_review
    raw=valid_review()
    assert validate_review(raw,60)["rating"]["estimate"] == 3.5
    raw["ball_visible"]=False
    r=validate_review(raw,60)
    assert r["rating"] is None and r["shot_counts"] is None
    assert all(s["shot_type"]=="unknown" for s in r["shots"])
    raw=valid_review()
    raw["shots"]=raw["shots"][:3]
    assert validate_review(raw,60)["rating"] is None
    raw=valid_review()
    raw["shots"][0]["timestamp"]=90
    with pytest.raises(RuntimeError,match="timestamps"):
        validate_review(raw,60)
    raw=valid_review()
    raw["rallies"][1]["start"]=10
    with pytest.raises(RuntimeError,match="overlapping"):
        validate_review(raw,60)


def test_gemini_requires_owner_opt_in_and_uploader_consent(monkeypatch):
    from duprvision.review import gemini_review
    monkeypatch.setenv("ANALYSIS_ENGINE","local")
    with pytest.raises(RuntimeError,match="authorized"):
        gemini_review({}, {}, True)
    monkeypatch.setenv("ANALYSIS_ENGINE","gemini")
    with pytest.raises(RuntimeError,match="authorized"):
        gemini_review({}, {}, False)


@pytest.mark.parametrize("model", ["gemini-2.5-flash", "gemini-3.6-flash", "gemini-3.1-flash-lite", "gemini-3.5-flash-lite"])
def test_provider_payload_limits_and_no_automatic_duplicate(clients,monkeypatch,model):
    from duprvision import review
    import httpx
    a,_=clients
    uid=a.get("/api/me").json()["id"]
    add_result(uid,"provider",None,core.iso())
    folder=core.video_dir("provider")
    folder.mkdir()
    (folder/"preview-1.jpg").write_bytes(b"test reference")
    monkeypatch.setenv("ANALYSIS_ENGINE","gemini")
    monkeypatch.setenv("GEMINI_API_KEY","test-key-not-real")
    monkeypatch.setenv("GEMINI_MODEL",model)
    monkeypatch.setattr(review.subprocess,"run",lambda *a,**kw:(folder/"review.mp4").write_bytes(b"test video"))
    calls=[]
    class Client:
        def __init__(self,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,**kwargs):
            calls.append(kwargs)
            return httpx.Response(200,json={"candidates":[{"finishReason":"STOP","content":{"parts":[{"text":json.dumps(compact_review())}]}}]})
    monkeypatch.setattr(review.httpx,"Client",Client)
    row={"id":"provider","duration_seconds":60,"normalized_path":str(folder/"normalized.mp4")}
    selection={"timestamp_seconds":6,"x":.5,"y":.5}
    assert review.gemini_review(row,selection,True)["performance"]["score"]==63
    assert len(calls)==1
    payload=calls[0]["json"]
    assert payload["generationConfig"]["maxOutputTokens"]==4096
    assert "maxItems" not in payload["generationConfig"]["responseJsonSchema"]["properties"]["shots"]
    assert payload["generationConfig"]["thinkingConfig"] == ({"thinkingLevel":"minimal" if "flash-lite" in model else "low"} if model.startswith("gemini-3") else {"thinkingBudget":0})
    assert payload["contents"][0]["parts"][2]["videoMetadata"]["fps"]==5
    assert not (folder/"review.mp4").exists()
    assert review.gemini_review(row,selection,True)["performance"]["score"]==63
    assert len(calls)==1
    assert not (folder/"review.mp4").exists()


def test_pose_candidates_are_not_shot_labels_or_ratings():
    from duprvision.pose_review import build_pose_review,swing_candidates,rally_candidates
    def person(wrist_x):
        points=[[0,0,.99] for _ in range(17)]
        points[5]=[100,100,.99]
        points[9]=[wrist_x,120,.99]
        return {"height":100,"points":points}
    events=swing_candidates([(0,{1:person(100)}),(.2,{1:person(150)})])
    assert len(events)==1 and events[0]["form"]=="full swing"
    assert rally_candidates([{"timestamp":t,"track_id":i%2} for i,t in enumerate((0,1,2,3))])
    r=build_pose_review({"subject_visibility":1,"measured_seconds":59,"active_seconds":0,"median_speed":0},[],1)
    assert r["rating"] is None and r["shot_counts"] is None
    assert "drive/drop" in r["summary"]


def test_single_rally_requires_sustained_shot_evidence_and_broad_range():
    from duprvision.review import validate_review
    raw = valid_review()
    raw["rallies"] = [{"start":0,"end":40,"observation":"Test sustained rally"}]
    raw["rating"].update(low=3.25,high=3.75)
    result = validate_review(raw,45)
    assert result["sample_scope"] == "short"
    assert result["rating"]["high"] - result["rating"]["low"] >= 1
    raw["rallies"][0]["end"] = 10
    assert validate_review(raw,45)["rating"] is None


def test_uncertain_shots_do_not_inflate_counts_or_rating():
    from duprvision.review import validate_review
    raw = valid_review()
    for shot in raw["shots"][:4]:
        shot["confidence"] = "low"
    result = validate_review(raw,60)
    assert sum(result["shot_counts"].values()) == 4
    assert result["uncertain_shots"] == 4
    assert result["rating"] is None


def test_invalid_coaching_timecodes_are_not_displayed():
    from duprvision.review import validate_review
    raw = valid_review()
    raw["priorities"] = ["Try an attack at 12:00.", "Aim your dinks just inside the baseline.", "Keep the paddle prepared."]
    result = validate_review(raw,60)
    assert result["priorities"] == ["Keep the paddle prepared."]


def test_recording_notes_alias_and_strict_local_bounds():
    from duprvision.review import Review, provider_schema
    raw = valid_review()
    raw["recording_notes"] = raw.pop("limitations")
    assert Review.model_validate(raw).limitations == ["Test fixture"]
    assert "recording_notes" in provider_schema()["properties"]
    raw["shots"] *= 20
    with pytest.raises(ValueError):
        Review.model_validate(raw)


@pytest.mark.parametrize("estimate,low,high", [(2,2,2.5),(8,7.5,8)])
def test_short_sample_range_respects_scale_boundaries(estimate,low,high):
    from duprvision.review import validate_review
    raw = valid_review()
    raw["rating"].update(estimate=estimate,low=low,high=high)
    result = validate_review(raw,50)
    assert result["rating"]["high"] - result["rating"]["low"] >= 1
    assert 2 <= result["rating"]["low"] <= result["rating"]["high"] <= 8

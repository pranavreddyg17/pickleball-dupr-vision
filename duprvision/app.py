import asyncio
import fcntl
import json
import os
import shutil
import subprocess
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from argon2.exceptions import VerifyMismatchError
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from .review import configured_engine

from .core import (
    COOKIE, DATA, DB, MAX_DURATION, MAX_SIZE, MAX_UPLOADS,
    PASSWORD_HASHER, ROOT, aggregate, cleanup_media, cleanup_tmp, connect, create_session,
    hash_token, init_db, iso, now, public_video, quota, score_history, user_for_token, video_dir,
)


@asynccontextmanager
async def lifespan(_app):
    init_db()
    cleanup_tmp()
    cleanup_media()
    yield


app = FastAPI(title="DUPRVision", docs_url=None, redoc_url=None, lifespan=lifespan)
STATIC = ROOT / "static"
UPLOAD_SLOTS = asyncio.Semaphore(2)


class Credentials(BaseModel):
    email: str
    password: str
    display_name: str = ""


class Selection(BaseModel):
    timestamp_seconds: float = Field(ge=0)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    consent: bool
    external_consent: bool = False


class ProfileSettings(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    discoverable: bool


def require_user(request):
    user = user_for_token(request.cookies.get(COOKIE))
    if not user:
        raise HTTPException(401, "Sign in to continue")
    return user


def check_origin(request):
    origin = request.headers.get("origin")
    if origin:
        from urllib.parse import urlparse
        parsed = urlparse(origin)
        if parsed.netloc != request.headers.get("host") or parsed.scheme not in ("http", "https"):
            raise HTTPException(403, "Invalid request origin")


def set_cookie(response, request, token):
    secure_setting = os.getenv("SESSION_SECURE", "auto").lower()
    secure = secure_setting == "true" or (secure_setting == "auto" and (
        request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    ))
    response.set_cookie(COOKIE, token, httponly=True, secure=secure, samesite="lax", max_age=7 * 86400)


@app.post("/api/register")
def register(body: Credentials, request: Request, response: Response):
    check_origin(request)
    email = body.email.strip().lower()
    if len(email) > 254 or "@" not in email or len(body.password) < 10 or len(body.password) > 256:
        raise HTTPException(400, "Enter a valid email and a password of at least 10 characters")
    user_id = str(uuid.uuid4())
    try:
        with connect() as db:
            db.execute("INSERT INTO users VALUES (?,?,?,?,?,?)", (
                user_id, email, (body.display_name.strip() or email.split("@")[0])[:80],
                PASSWORD_HASHER.hash(body.password), None, iso()
            ))
            token = create_session(db, user_id)
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            raise HTTPException(409, "An account with that email already exists") from exc
        raise
    set_cookie(response, request, token)
    return {"ok": True}


@app.post("/api/login")
def login(body: Credentials, request: Request, response: Response):
    check_origin(request)
    email = body.email.strip().lower()
    cutoff = iso(now() - timedelta(minutes=15))
    with connect() as db:
        attempts = db.execute("SELECT COUNT(*) FROM login_attempts WHERE email=? AND attempted_at>=?", (email, cutoff)).fetchone()[0]
        if attempts >= 10:
            raise HTTPException(429, "Too many sign-in attempts. Try again later")
        row = db.execute("SELECT id, password_hash FROM users WHERE email=?", (email,)).fetchone()
        try:
            if not row:
                raise VerifyMismatchError()
            PASSWORD_HASHER.verify(row["password_hash"], body.password)
        except VerifyMismatchError:
            failed = True
        else:
            failed = False
            db.execute("DELETE FROM login_attempts WHERE email=?", (email,))
            token = create_session(db, row["id"])
        if failed:
            db.execute("INSERT INTO login_attempts VALUES (?,?)", (email, iso()))
            db.execute("DELETE FROM login_attempts WHERE attempted_at<?", (iso(now() - timedelta(days=1)),))
    if failed:
        raise HTTPException(401, "Invalid email or password")
    set_cookie(response, request, token)
    return {"ok": True}


@app.post("/api/logout")
def logout(request: Request, response: Response):
    check_origin(request)
    token = request.cookies.get(COOKIE)
    if token:
        with connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (hash_token(token),))
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/me")
def me(request: Request):
    user = require_user(request)
    with connect() as db:
        used = quota(db, user["id"])
        settings = db.execute("SELECT discoverable FROM profile_settings WHERE user_id=?", (user["id"],)).fetchone()
    return {"id": user["id"], "email": user["email"], "display_name": user["display_name"],
            "remaining": max(0, MAX_UPLOADS - used), "consent_at": user["consent_at"],
            "discoverable": bool(settings and settings[0])}


@app.put("/api/me")
def update_profile(body: ProfileSettings, request: Request):
    check_origin(request)
    user = require_user(request)
    name = body.display_name.strip()
    if not name:
        raise HTTPException(400, "Name is required")
    with connect(immediate=True) as db:
        db.execute("UPDATE users SET display_name=? WHERE id=?", (name, user["id"]))
        db.execute("INSERT OR REPLACE INTO profile_settings VALUES (?,?)", (user["id"], int(body.discoverable)))
    return {"ok": True}


@app.get("/api/scores")
def scores(request: Request):
    user = require_user(request)
    with connect() as db:
        return score_history(db, user["id"])


def player_summary(db, target_id, viewer_id, include_history=False):
    row = db.execute("""SELECT users.id, users.display_name FROM users
      LEFT JOIN profile_settings ON profile_settings.user_id=users.id
      WHERE users.id=? AND (profile_settings.discoverable=1 OR users.id=?)""", (target_id, viewer_id)).fetchone()
    if not row:
        raise HTTPException(404, "Player not found")
    history = score_history(db, target_id)
    result = {**dict(row), "average": history["average"], "clips": history["clips"],
              "latest": history["days"][-1] if history["days"] else None,
              "is_following": bool(db.execute("SELECT 1 FROM follows WHERE follower_id=? AND followed_id=?", (viewer_id, target_id)).fetchone()),
              "followers": db.execute("SELECT COUNT(*) FROM follows WHERE followed_id=?", (target_id,)).fetchone()[0],
              "following": db.execute("SELECT COUNT(*) FROM follows WHERE follower_id=?", (target_id,)).fetchone()[0]}
    if include_history:
        result["history"] = history
    return result


@app.get("/api/players")
def players(request: Request, q: str = "", view: str = "discover", offset: int = 0):
    user = require_user(request)
    if view not in ("discover", "following", "followers") or len(q) > 80 or offset < 0:
        raise HTTPException(400, "Invalid player search")
    relation = ""
    params = [user["id"], f"%{q.strip()}%"]
    if view != "discover":
        relation = (" AND EXISTS(SELECT 1 FROM follows f WHERE f.follower_id=? AND f.followed_id=u.id)" if view == "following"
                    else " AND EXISTS(SELECT 1 FROM follows f WHERE f.followed_id=? AND f.follower_id=u.id)")
        params.append(user["id"])
    with connect() as db:
        rows = db.execute("""SELECT u.id FROM users u JOIN profile_settings p ON p.user_id=u.id
          WHERE p.discoverable=1 AND u.id!=? AND u.display_name LIKE ?""" + relation +
          " ORDER BY u.display_name COLLATE NOCASE, u.id LIMIT 31 OFFSET ?", (*params, offset)).fetchall()
        return {"players": [player_summary(db, row[0], user["id"]) for row in rows[:30]], "has_more": len(rows) > 30}


@app.get("/api/players/{player_id}")
def player(request: Request, player_id: str):
    user = require_user(request)
    with connect() as db:
        return player_summary(db, player_id, user["id"], include_history=True)


@app.post("/api/players/{player_id}/follow")
def follow(request: Request, player_id: str):
    check_origin(request)
    user = require_user(request)
    if player_id == user["id"]:
        raise HTTPException(400, "You cannot follow yourself")
    with connect(immediate=True) as db:
        player_summary(db, player_id, user["id"])
        db.execute("INSERT OR IGNORE INTO follows VALUES (?,?,?)", (user["id"], player_id, iso()))
    return {"ok": True}


@app.delete("/api/players/{player_id}/follow")
def unfollow(request: Request, player_id: str):
    check_origin(request)
    user = require_user(request)
    with connect() as db:
        db.execute("DELETE FROM follows WHERE follower_id=? AND followed_id=?", (user["id"], player_id))
    return {"ok": True}


@app.post("/api/videos")
async def upload(request: Request):
    check_origin(request)
    user = require_user(request)
    with connect() as db:
        if quota(db, user["id"]) >= MAX_UPLOADS:
            raise HTTPException(429, "Daily limit reached: five accepted videos")
    if shutil.disk_usage(DATA).free < 5 * 1024**3:
        raise HTTPException(503, "Uploads are paused because this computer is low on storage")
    from urllib.parse import unquote
    filename = unquote(request.headers.get("x-filename", "video"))[:200]
    temp_path = DATA / "tmp" / f"{uuid.uuid4()}.upload"
    size = 0
    try:
        async with UPLOAD_SLOTS:
            with temp_path.open("wb") as target:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_SIZE:
                        raise HTTPException(413, "Video exceeds the 100 MB limit")
                    target.write(chunk)
        if size == 0:
            raise HTTPException(400, "Choose a video file")
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
             "-of", "json", str(temp_path)], capture_output=True, text=True, timeout=30
        )
        if probe.returncode:
            raise HTTPException(400, "This video could not be read")
        info = json.loads(probe.stdout)
        streams = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
        duration = float(info.get("format", {}).get("duration", 0))
        if not streams or not (0 < duration <= MAX_DURATION):
            raise HTTPException(400, "Video must contain readable footage and be no longer than 3 minutes")
        if not (64 <= streams[0].get("width", 0) <= 7680 and 64 <= streams[0].get("height", 0) <= 4320):
            raise HTTPException(400, "Video dimensions are unsupported")
        video_id = str(uuid.uuid4())
        folder = video_dir(video_id)
        folder.mkdir(parents=True)
        raw_path = folder / "source.upload"
        try:
            with connect(immediate=True) as db:
                if quota(db, user["id"]) >= MAX_UPLOADS:
                    raise HTTPException(429, "Daily limit reached: five accepted videos")
                temp_path.replace(raw_path)
                db.execute("INSERT INTO videos VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
                    video_id, user["id"], filename, size, duration, str(raw_path), None,
                    "PROCESSING", "Preparing video", None, iso(), iso()
                ))
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        return {"id": video_id, "status": "PROCESSING"}
    finally:
        temp_path.unlink(missing_ok=True)


def owned_video(request, video_id):
    user = require_user(request)
    with connect() as db:
        row = db.execute("SELECT * FROM videos WHERE id=? AND user_id=?", (video_id, user["id"])).fetchone()
        if not row or row["status"] == "DELETED":
            raise HTTPException(404, "Video not found")
        return dict(row)


@app.get("/api/videos")
def videos(request: Request):
    user = require_user(request)
    with connect() as db:
        rows = db.execute("SELECT * FROM videos WHERE user_id=? AND status!='DELETED' ORDER BY created_at DESC", (user["id"],)).fetchall()
        output = []
        for row in rows:
            item = public_video(row)
            result = db.execute("SELECT result_json FROM analyses WHERE video_id=?", (row["id"],)).fetchone()
            item["result"] = json.loads(result[0]) if result else None
            output.append(item)
    return output


@app.get("/api/videos/{video_id}")
def video(request: Request, video_id: str):
    row = owned_video(request, video_id)
    item = public_video(row)
    with connect() as db:
        result = db.execute("SELECT result_json FROM analyses WHERE video_id=?", (video_id,)).fetchone()
        item["result"] = json.loads(result[0]) if result else None
    return item


@app.get("/api/videos/{video_id}/preview/{number}")
def preview(request: Request, video_id: str, number: int):
    row = owned_video(request, video_id)
    if row["status"] in ("COMPLETED", "EXPIRED"):
        raise HTTPException(410, "Media expired after analysis; the report is retained")
    if number not in (1, 2, 3):
        raise HTTPException(404)
    path = video_dir(video_id) / f"preview-{number}.jpg"
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})


@app.post("/api/videos/{video_id}/select")
def select(request: Request, video_id: str, body: Selection):
    check_origin(request)
    row = owned_video(request, video_id)
    if row["status"] != "WAITING_FOR_PLAYER":
        raise HTTPException(409, "Video is not ready for player selection")
    if not body.consent:
        raise HTTPException(400, "Consent is required before analysis")
    engine = configured_engine()
    if engine == "gemini":
        if not os.getenv("GEMINI_API_KEY"):
            raise HTTPException(503, "Video review is unavailable until the owner completes provider setup")
        if not body.external_consent:
            raise HTTPException(400, "Consent to send this clip to Google for video review is required")
    if body.timestamp_seconds > row["duration_seconds"]:
        raise HTTPException(400, "Selection is outside this video")
    with connect(immediate=True) as db:
        current = db.execute("SELECT status FROM videos WHERE id=?", (video_id,)).fetchone()
        if current["status"] != "WAITING_FOR_PLAYER":
            raise HTTPException(409, "Analysis was already started")
        db.execute("INSERT OR REPLACE INTO selections VALUES (?,?,?,?)", (
            video_id, body.timestamp_seconds, body.x, body.y
        ))
        db.execute("INSERT OR REPLACE INTO analysis_options VALUES (?,?,?)", (video_id, engine, int(body.external_consent)))
        db.execute("UPDATE users SET consent_at=COALESCE(consent_at,?) WHERE id=?", (iso(), row["user_id"]))
        db.execute("UPDATE videos SET status='QUEUED', stage='Waiting for analysis', updated_at=? WHERE id=?", (iso(), video_id))
    return {"ok": True}


@app.delete("/api/videos/{video_id}")
def delete_video(request: Request, video_id: str):
    check_origin(request)
    row = owned_video(request, video_id)
    with connect(immediate=True) as db:
        current = db.execute("SELECT status FROM videos WHERE id=?", (video_id,)).fetchone()
        if current[0] in ("PROCESSING", "PREPARING", "QUEUED", "ANALYZING"):
            raise HTTPException(409, "Wait for this job to finish before deleting it")
        db.execute("DELETE FROM analyses WHERE video_id=?", (video_id,))
        db.execute("DELETE FROM provider_results WHERE video_id=?", (video_id,))
        db.execute("UPDATE videos SET status='DELETED', stage='Deleted', updated_at=? WHERE id=?", (iso(), video_id))
    shutil.rmtree(video_dir(video_id), ignore_errors=True)
    return {"ok": True}


@app.post("/api/videos/{video_id}/retry")
def retry_video(request: Request, video_id: str):
    check_origin(request)
    row = owned_video(request, video_id)
    with connect(immediate=True) as db:
        current = db.execute("SELECT status FROM videos WHERE id=?", (video_id,)).fetchone()
        if current[0] != "FAILED":
            raise HTTPException(409, "This clip is not ready to retry")
        prepared = row["normalized_path"] and Path(row["normalized_path"]).exists()
        if not prepared and not (row["raw_path"] and Path(row["raw_path"]).exists()):
            raise HTTPException(409, "Original media is unavailable. Upload a new clip")
        selected = db.execute("SELECT 1 FROM selections JOIN analysis_options USING(video_id) WHERE video_id=?", (video_id,)).fetchone()
        queued = prepared and selected
        db.execute("UPDATE videos SET status=?, stage=?, error=NULL, updated_at=? WHERE id=?", (
            "QUEUED" if queued else "WAITING_FOR_PLAYER" if prepared else "PROCESSING",
            "Waiting for analysis" if queued else "Choose your player" if prepared else "Preparing video", iso(), video_id))
    return {"ok": True}


@app.get("/api/videos/{video_id}/tracking/{number}")
def tracking_frame(request: Request, video_id: str, number: int):
    row = owned_video(request, video_id)
    if row["status"] in ("COMPLETED", "EXPIRED"):
        raise HTTPException(410, "Media expired after analysis; the report is retained")
    if number not in (1, 2, 3):
        raise HTTPException(404)
    path = video_dir(video_id) / f"tracking-{number}.jpg"
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})


@app.get("/api/estimate")
def estimate(request: Request):
    user = require_user(request)
    with connect() as db:
        rows = db.execute("""SELECT analyses.result_json, videos.duration_seconds FROM analyses
          JOIN videos ON videos.id=analyses.video_id WHERE videos.user_id=? AND videos.status='COMPLETED'
          ORDER BY videos.created_at DESC""", (user["id"],)).fetchall()
    results = [{**json.loads(row["result_json"]), "duration_seconds": row["duration_seconds"]} for row in rows]
    return {"profile": aggregate(results)}


@app.get("/api/health")
def health():
    lock_path = DATA / "worker.lock"
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            worker_running = True
        else:
            worker_running = False
            fcntl.flock(lock, fcntl.LOCK_UN)
    engine = configured_engine()
    return {"ok": True, "analysis_configured": engine == "local" or bool(os.getenv("GEMINI_API_KEY")),
            "analysis_engine": engine, "worker_running": worker_running}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/{asset}")
def asset(asset: str):
    if asset not in ("app.js", "style.css", "court.png"):
        raise HTTPException(404)
    return FileResponse(STATIC / asset, headers={"Cache-Control": "no-cache"})


@app.get("/icons/{name}.svg")
def icon(name: str):
    if name not in ("house", "circle-plus", "history", "user-round", "users-round", "search", "upload", "arrow-left", "trash-2"):
        raise HTTPException(404)
    return FileResponse(STATIC / "icons" / f"{name}.svg", media_type="image/svg+xml")

import hashlib
import json
import math
import os
import secrets
import shutil
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from argon2 import PasswordHasher


ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("DUPRVISION_DATA_DIR", str(ROOT / "data")))
DB = DATA / "duprvision.sqlite3"
MAX_SIZE = 100_000_000
MAX_UPLOADS = 5
MAX_DURATION = 180
COOKIE = os.environ.get("DUPRVISION_COOKIE", "duprvision_session")
PASSWORD_HASHER = PasswordHasher()


def load_env():
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if line and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


load_env()


def now():
    return datetime.now(timezone.utc)


def iso(value=None):
    return (value or now()).isoformat()


def day_bounds():
    local = now().astimezone(ZoneInfo(os.getenv("APP_TIMEZONE", "America/Chicago")))
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat()


@contextmanager
def connect(immediate=False):
    DATA.mkdir(exist_ok=True)
    db = sqlite3.connect(DB, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=30000")
    try:
        if immediate:
            db.execute("BEGIN IMMEDIATE")
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    (DATA / "tmp").mkdir(parents=True, exist_ok=True)
    (DATA / "uploads").mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL,
          password_hash TEXT NOT NULL, consent_at TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
          token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          expires_at TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS login_attempts (
          email TEXT NOT NULL, attempted_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS login_attempts_email_time ON login_attempts(email, attempted_at);
        CREATE TABLE IF NOT EXISTS videos (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          original_filename TEXT NOT NULL, raw_size_bytes INTEGER NOT NULL,
          duration_seconds REAL NOT NULL, raw_path TEXT, normalized_path TEXT,
          status TEXT NOT NULL, stage TEXT NOT NULL, error TEXT,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS videos_user_created ON videos(user_id, created_at);
        CREATE INDEX IF NOT EXISTS videos_status_created ON videos(status, created_at);
        CREATE TABLE IF NOT EXISTS selections (
          video_id TEXT PRIMARY KEY REFERENCES videos(id) ON DELETE CASCADE,
          timestamp_seconds REAL NOT NULL, x REAL NOT NULL, y REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS analyses (
          video_id TEXT PRIMARY KEY REFERENCES videos(id) ON DELETE CASCADE,
          result_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS profile_settings (
          user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
          discoverable INTEGER NOT NULL DEFAULT 0 CHECK(discoverable IN (0,1))
        );
        CREATE TABLE IF NOT EXISTS follows (
          follower_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          followed_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          created_at TEXT NOT NULL,
          PRIMARY KEY(follower_id, followed_id), CHECK(follower_id != followed_id)
        );
        CREATE INDEX IF NOT EXISTS follows_target ON follows(followed_id);
        CREATE TABLE IF NOT EXISTS analysis_options (
          video_id TEXT PRIMARY KEY REFERENCES videos(id) ON DELETE CASCADE,
          engine TEXT NOT NULL, external_consent INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS provider_attempts (
          video_id TEXT PRIMARY KEY REFERENCES videos(id) ON DELETE CASCADE,
          model TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS provider_requests (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
          model TEXT NOT NULL, created_at TEXT NOT NULL, status TEXT NOT NULL, failure_code TEXT
        );
        CREATE INDEX IF NOT EXISTS provider_requests_video ON provider_requests(video_id);
        CREATE UNIQUE INDEX IF NOT EXISTS provider_one_active ON provider_requests(video_id) WHERE status='inflight';
        CREATE TABLE IF NOT EXISTS provider_results (
          video_id TEXT PRIMARY KEY REFERENCES videos(id) ON DELETE CASCADE,
          result_json TEXT NOT NULL
        );
        INSERT INTO provider_requests(video_id,model,created_at,status)
          SELECT video_id,model,created_at,'legacy' FROM provider_attempts old
          WHERE NOT EXISTS (SELECT 1 FROM provider_requests new WHERE new.video_id=old.video_id);
        """)
        db.execute("BEGIN IMMEDIATE")
        columns = {row[1] for row in db.execute("PRAGMA table_info(provider_requests)")}
        if "failure_code" not in columns:
            db.execute("ALTER TABLE provider_requests ADD COLUMN failure_code TEXT")


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db, user_id):
    token = secrets.token_urlsafe(40)
    db.execute("INSERT INTO sessions VALUES (?,?,?,?)", (
        hash_token(token), user_id, iso(now() + timedelta(days=7)), iso()
    ))
    return token


def user_for_token(token):
    if not token:
        return None
    with connect() as db:
        row = db.execute("""SELECT users.* FROM sessions JOIN users ON users.id=sessions.user_id
          WHERE sessions.token_hash=? AND sessions.expires_at>?""", (hash_token(token), iso())).fetchone()
        return dict(row) if row else None


def quota(db, user_id):
    start, end = day_bounds()
    return db.execute("SELECT COUNT(*) FROM videos WHERE user_id=? AND created_at>=? AND created_at<?", (user_id, start, end)).fetchone()[0]


def dupr_scale_equivalent(vision_average):
    """A display-only 2.0-5.0 mapping, with no match-rating calibration."""
    if not isinstance(vision_average, (int, float)) or not math.isfinite(vision_average):
        return None
    return round(2 + 3 * min(100, max(0, vision_average)) / 100, 1)


def aggregate(results):
    results = [item for item in results if isinstance(item.get("best_estimate"), (int, float))]
    if not results:
        return None
    values = sorted(item["best_estimate"] for item in results)
    middle = len(values) // 2
    estimate = values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2
    estimate = round(estimate, 1)
    deviations = sorted(abs(value - estimate) for value in values)
    deviation = deviations[middle] if len(values) % 2 else (deviations[middle - 1] + deviations[middle]) / 2
    base_width = 0.5 if len(values) == 1 else 0.4 if len(values) == 2 else 0.3 if len(values) < 5 else 0.2
    # A descriptive band; it is not a statistical confidence interval.
    half_width = round(max(base_width, base_width + 1.5 * deviation), 1)
    return {
        "estimate": estimate,
        "low": round(max(2.0, estimate - half_width), 1),
        "high": round(min(6.0, estimate + half_width), 1),
        "sessions": len(values),
        "evidence": "Early" if len(values) < 3 else "Growing" if len(values) < 5 else "Stronger",
        "observed_seconds": round(sum(item["duration_seconds"] for item in results)),
    }


def public_video(row):
    item = dict(row)
    return {**{key: item[key] for key in ("id", "original_filename", "duration_seconds", "status", "stage", "error", "created_at")},
            "media_available": bool(item["raw_path"] or item["normalized_path"])}


def score_history(db, user_id):
    zone = ZoneInfo(os.getenv("APP_TIMEZONE", "America/Chicago"))
    rows = db.execute("""SELECT videos.created_at, analyses.result_json FROM analyses
      JOIN videos ON videos.id=analyses.video_id
      WHERE videos.user_id=? AND videos.status='COMPLETED' ORDER BY videos.created_at""", (user_id,)).fetchall()
    days = {}
    for row in rows:
        result = json.loads(row["result_json"])
        if result.get("kind") not in ("pose_review_v1", "video_review_v1", "video_review_v2"):
            continue
        # Persist the upload's local day in each result so timezone changes cannot move old entries.
        day = result.get("score_date") or datetime.fromisoformat(row["created_at"]).astimezone(zone).date().isoformat()
        # Never mix the former 2-8 estimate with the new 0-100 performance metric.
        days.setdefault(day, []).append(result.get("performance", {}).get("score"))
    daily = []
    for day, scores in sorted(days.items()):
        rated = [score for score in scores if score is not None]
        daily.append({"date":day,"score":round(sum(rated)/len(rated),2) if rated else None,
                      "clips":len(scores),"rated_clips":len(rated)})
    today = now().astimezone(zone).date()
    cursor = today if today.isoformat() in days else today - timedelta(days=1)
    streak = 0
    while cursor.isoformat() in days:
        streak += 1
        cursor -= timedelta(days=1)
    rated_days = [d["score"] for d in daily if d["score"] is not None]
    average = round(sum(rated_days)/len(rated_days),2) if rated_days else None
    return {"days": daily, "average": average,
            "dupr_equivalent": dupr_scale_equivalent(average),
            "clips": sum(d["clips"] for d in daily), "streak": streak,
            "rated_clips":sum(d["rated_clips"] for d in daily),
            "today": today.isoformat(), "timezone": str(zone), "kind": "vision_score_v1"}


def video_dir(video_id):
    return DATA / "uploads" / video_id


def expire_media(video_id):
    folder = video_dir(video_id)
    if folder.exists():
        shutil.rmtree(folder)
    with connect() as db:
        db.execute("UPDATE videos SET raw_path=NULL, normalized_path=NULL WHERE id=?", (video_id,))


def cleanup_media():
    cutoff = iso(now() - timedelta(hours=24))
    with connect(immediate=True) as db:
        db.execute("""UPDATE videos SET status='EXPIRED', stage='Clip expired',
          error='The upload expired before analysis. Upload a new clip.', updated_at=?
          WHERE status IN ('WAITING_FOR_PLAYER','FAILED') AND updated_at<?""", (iso(), cutoff))
        ids = [row[0] for row in db.execute("SELECT id FROM videos WHERE status IN ('COMPLETED','DELETED','EXPIRED')")]
    for video_id in ids:
        expire_media(video_id)


def cleanup_tmp():
    cutoff = time.time() - 86400
    for path in (DATA / "tmp").glob("*"):
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink()

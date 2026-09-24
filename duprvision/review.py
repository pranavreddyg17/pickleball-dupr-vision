"""Structured video review. External processing is opt-in, never a fallback."""
import base64
import hashlib
import json
import os
import re
import random
import subprocess
import time
from urllib.parse import urlparse
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

import httpx

from .core import connect, day_bounds, iso, video_dir


def provider_schema(schema_model):
    """Keep the generation grammar small; enforce bounds with local validation."""
    local_only = {"title", "minLength", "maxLength", "exclusiveMinimum", "minItems", "maxItems", "minimum", "maximum"}

    def simplify(value):
        if isinstance(value, list):
            return [simplify(item) for item in value]
        if isinstance(value, dict):
            return {key:simplify(item) for key,item in value.items() if key not in local_only}
        return value

    return simplify(schema_model.model_json_schema())


def configured_engine():
    engine = os.getenv("ANALYSIS_ENGINE", "local").lower()
    return engine if engine in ("gemini", "self_hosted") else "local"


def valid_coaching_note(note, duration):
    if any(int(m)*60+float(s) > duration for m,s in re.findall(r"\b(\d{1,3}):([0-5]\d(?:\.\d+)?)\b", note)):
        return False
    # Reject this contradictory instruction instead of displaying a wrong court target.
    return not (re.search(r"\bdinks?\b", note, re.I) and re.search(r"\bbaseline\b", note, re.I))


class ReviewError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class RetryableReviewError(ReviewError):
    def __init__(self, code, delay=30):
        super().__init__(code, "The video service is busy. Your clip is saved for another attempt.")
        self.delay = delay


def cache_key(db, video_id, selection, model, marked=False, tracked=False, backend="gemini"):
    from .assessment import PROMPT, Assessment, validate_assessment, PRIOR_WEIGHT, WEIGHTS, VERSION
    import inspect
    source = db.execute("SELECT user_id,sha256 FROM videos JOIN video_fingerprints ON id=video_id WHERE id=?", (video_id,)).fetchone()
    if not source:
        return None
    # The account, exact player selection, prompt, schema, and rubric define reuse.
    material = [*source, dict(selection), backend, model, "silent-video-5fps-adaptive-crf23-tracked-v5", bool(marked), bool(tracked),
                "yolo26n-detect-bytetrack-5hz-v1" if marked else "", PROMPT,
                Assessment.model_json_schema(), inspect.getsource(validate_assessment), PRIOR_WEIGHT, WEIGHTS, VERSION]
    material[2].pop("video_id", None)
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def gemini_review(row, selection, external_consent, marked_reference=None, tracked=None):
    if not external_consent:
        raise RuntimeError("External video processing has not been authorized")
    if configured_engine() != "gemini":
        with connect() as db:
            saved_option = db.execute("SELECT engine,external_consent FROM analysis_options WHERE video_id=?",
                                      (row.get("id"),)).fetchone()
        if not saved_option or saved_option["engine"] != "gemini" or not saved_option["external_consent"]:
            raise RuntimeError("External video processing has not been authorized")
    with connect() as db:
        cached = db.execute("SELECT result_json FROM provider_results WHERE video_id=?", (row["id"],)).fetchone()
    if cached:
        return json.loads(cached[0])
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        raise ReviewError("CONFIGURATION", "Video review is not configured by the owner")
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    with connect(immediate=True) as db:
        db.execute("INSERT OR IGNORE INTO analysis_jobs(video_id,model) VALUES (?,?)", (row["id"], model))
        model = db.execute("SELECT model FROM analysis_jobs WHERE video_id=?", (row["id"],)).fetchone()[0]
        fingerprint = cache_key(db, row["id"], selection, model, marked_reference is not None, bool(tracked))
        if fingerprint:
            cached = db.execute("SELECT a.result_json FROM review_cache_keys k JOIN videos v ON v.id=k.video_id JOIN analyses a ON a.video_id=v.id WHERE k.cache_key=? AND v.status='COMPLETED' LIMIT 1", (fingerprint,)).fetchone()
            db.execute("INSERT OR REPLACE INTO review_cache_keys VALUES (?,?)", (row["id"], fingerprint))
            if cached:
                result = json.loads(cached[0])
                result.update(cache_hit=True, analysis_seconds=0, usage={})
                db.execute("INSERT OR REPLACE INTO provider_results VALUES (?,?)", (row["id"], json.dumps(result)))
                return result
    if model not in ("gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.6-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite"):
        raise ReviewError("CONFIGURATION", "Select a supported cost-limited video review model")
    output = video_dir(row["id"]) / "review.mp4"
    try:
        return _request_review(row, selection, key, model, output, marked_reference, tracked)
    finally:
        output.unlink(missing_ok=True)


def self_hosted_review(row, selection, marked_reference=None, tracked=None):
    """Review with an owner-operated OpenAI-compatible video model server."""
    base_url = os.getenv("SELF_HOSTED_VLM_URL", "").rstrip("/")
    parsed = urlparse(base_url)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or
            parsed.password or parsed.query or parsed.fragment or not parsed.path.endswith("/v1")):
        raise ReviewError("CONFIGURATION", "The self-hosted video service is not configured")
    model = os.getenv("SELF_HOSTED_VLM_MODEL", "").strip()
    if not model:
        raise ReviewError("CONFIGURATION", "A self-hosted video model is required")
    revision = os.getenv("SELF_HOSTED_VLM_REVISION", "1").strip()
    if not revision:
        raise ReviewError("CONFIGURATION", "A model revision is required")
    with connect() as db:
        saved = db.execute("SELECT result_json FROM provider_results WHERE video_id=?", (row["id"],)).fetchone()
    if saved:
        return json.loads(saved[0])
    identity = f"self_hosted:{model}:{revision}"
    with connect(immediate=True) as db:
        db.execute("INSERT OR IGNORE INTO analysis_jobs(video_id,model) VALUES (?,?)", (row["id"], identity))
        if db.execute("SELECT model FROM analysis_jobs WHERE video_id=?", (row["id"],)).fetchone()[0] != identity:
            raise ReviewError("CONFIGURATION", "This job was created for a different video model")
        fingerprint = cache_key(db, row["id"], selection, identity, marked_reference is not None,
                                bool(tracked), backend="self_hosted")
        if fingerprint:
            cached = db.execute("SELECT a.result_json FROM review_cache_keys k JOIN videos v ON v.id=k.video_id "
                                "JOIN analyses a ON a.video_id=v.id WHERE k.cache_key=? AND v.status='COMPLETED' "
                                "LIMIT 1", (fingerprint,)).fetchone()
            db.execute("INSERT OR REPLACE INTO review_cache_keys VALUES (?,?)", (row["id"], fingerprint))
            if cached:
                result = json.loads(cached[0])
                result.update(cache_hit=True, analysis_seconds=0, usage={})
                db.execute("INSERT OR REPLACE INTO provider_results VALUES (?,?)", (row["id"], json.dumps(result)))
                return result
    output = video_dir(row["id"]) / "review.mp4"
    try:
        return _request_self_hosted_review(row, selection, model, identity, base_url, output,
                                           marked_reference, tracked)
    finally:
        output.unlink(missing_ok=True)


def _request_self_hosted_review(row, selection, model, identity, base_url, output,
                                marked_reference=None, tracked=None):
    from .assessment import Assessment, PROMPT, validate_assessment

    marked_video = encode_review(row, output, tracked)
    previews = (.1, .4, .7)
    number = min(range(3), key=lambda i: abs(row["duration_seconds"] * previews[i] - selection["timestamp_seconds"])) + 1
    reference = marked_reference or video_dir(row["id"]) / f"preview-{number}.jpg"
    prompt = (PROMPT + f"\nDuration: {row['duration_seconds']:.1f}s. Reference timestamp: "
              f"{selection['timestamp_seconds']:.1f}s. Player point: x={selection['x']:.3f}, "
              f"y={selection['y']:.3f} (0-1 from top-left). Return only JSON matching the schema.")
    if marked_reference is not None or marked_video:
        prompt += "\nGreen outlines mark the selected player when tracked. Gaps are not ball-contact evidence."
    payload = {"model": model, "messages": [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," +
            base64.b64encode(reference.read_bytes()).decode()}},
        {"type": "video_url", "video_url": {"url": "data:video/mp4;base64," +
            base64.b64encode(output.read_bytes()).decode()}}]}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "assessment",
                            "schema": provider_schema(Assessment)}},
        "temperature": .1, "max_tokens": 4096}
    started = time.monotonic()
    request_id = reserve_request(row["id"], identity, enforce_daily_limit=False)
    try:
        timeout = max(30, min(600, float(os.getenv("SELF_HOSTED_VLM_TIMEOUT", "180"))))
        token = os.getenv("SELF_HOSTED_VLM_TOKEN", "")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=8, write=30, pool=5),
                          follow_redirects=False) as client:
            response = client.post(base_url + "/chat/completions", headers=headers, json=payload)
        if response.status_code != 200:
            code = f"HTTP_{response.status_code}"
            if response.status_code in (408, 429, 500, 502, 503, 504):
                raise RetryableReviewError(code, retry_delay(response))
            raise ReviewError(code, "The self-hosted video service rejected this review")
        body = response.json()
        choice = body["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise RetryableReviewError("INCOMPLETE_RESPONSE")
        raw = json.loads(choice["message"]["content"])
        try:
            result = validate_assessment(raw, row["duration_seconds"])
        except RuntimeError as exc:
            raise ReviewError("PLAYER_UNCLEAR", str(exc)) from exc
        result.update(model=identity, usage=body.get("usage", {}),
                      analysis_seconds=round(time.monotonic() - started, 1),
                      review_input={"fps": 5, "detail": "default", "player_marked": marked_video})
        with connect() as db:
            db.execute("INSERT OR REPLACE INTO provider_results VALUES (?,?)", (row["id"], json.dumps(result)))
            db.execute("UPDATE provider_requests SET status='succeeded' WHERE id=?", (request_id,))
        return result
    except RetryableReviewError as exc:
        finish_request(request_id, "retryable", exc.code)
        raise
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
        code = type(exc).__name__ if isinstance(exc, httpx.HTTPError) else "INVALID_RESPONSE"
        finish_request(request_id, "retryable", code)
        raise RetryableReviewError(code) from exc
    except ReviewError as exc:
        finish_request(request_id, "permanent", exc.code)
        raise
    finally:
        with connect() as db:
            db.execute("UPDATE provider_requests SET elapsed_seconds=? WHERE id=?", (time.monotonic()-started, request_id))


def encode_review(row, output, tracked=None):
    import cv2
    from .evidence import review_track_video
    intermediate = output.with_name('review-tracked-source.mp4')
    marked = False
    try:
        try:
            marked = review_track_video(row, tracked, intermediate)
        except (cv2.error, OSError) as exc:
            print(f'Review annotation unavailable: {type(exc).__name__}', flush=True)
        _encode_review(row, output, str(intermediate) if marked else row['normalized_path'])
    finally:
        intermediate.unlink(missing_ok=True)
    return marked


def _encode_review(row, output, source):
    # Short clips can retain more ball detail within the same upload budget.
    max_rate = max(128, min(1200, int(12 * 1024 * 1024 * 8 * .85 / max(1, row['duration_seconds']) / 1000)))
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", source,
                    "-vf", "fps=5", "-an", "-c:v", "libx264", "-threads", "1", "-preset", "veryfast", "-crf", "23",
                    "-maxrate", f"{max_rate}k", "-bufsize", f"{max_rate * 2}k", "-movflags", "+faststart", str(output)],
                   check=True, capture_output=True, timeout=300)
    if output.stat().st_size > 12 * 1024 * 1024:
        raise RuntimeError("Review video exceeded the processing size limit")


def _request_review(row, selection, key, model, output, marked_reference=None, tracked=None):
    from .assessment import Assessment, PROMPT as compact_prompt, validate_assessment
    marked_video = encode_review(row, output, tracked)
    previews = (.1, .4, .7)
    number = min(range(3), key=lambda i: abs(row["duration_seconds"] * previews[i] - selection["timestamp_seconds"])) + 1
    reference = marked_reference or video_dir(row["id"]) / f"preview-{number}.jpg"
    prompt = compact_prompt + f"\nDuration: {row['duration_seconds']:.1f}s. Reference timestamp: {selection['timestamp_seconds']:.1f}s. Player point: x={selection['x']:.3f}, y={selection['y']:.3f} (0-1 from top-left)."
    if marked_reference is not None:
        prompt += "\nThe green outline in the reference frame marks the locally tracked selected player. Use the video, not the outline, to judge shots and outcomes."
    if marked_video:
        prompt += "\nGreen outlines in the video identify the same selected player when locally tracked. An absent outline is a tracking gap, not proof the player is absent. Inspect the whole clip for that player's visible contacts; do not report teammates' shots."
    payload = {"contents":[{"role":"user","parts":[{"text":prompt},
        {"inlineData":{"mimeType":"image/jpeg","data":base64.b64encode(reference.read_bytes()).decode()}},
        {"inlineData":{"mimeType":"video/mp4","data":base64.b64encode(output.read_bytes()).decode()}, "videoMetadata":{"fps":5}}]}],
        "generationConfig":{"temperature":1 if model.startswith("gemini-3") else .1,"maxOutputTokens":4096,"responseMimeType":"application/json",
                            "responseJsonSchema":provider_schema(Assessment),"thinkingConfig":{"thinkingLevel":"minimal" if "flash-lite" in model else "low"} if model.startswith("gemini-3") else {"thinkingBudget":0}}}
    started = time.monotonic()
    # A worker invocation makes exactly one paid request. SQLite schedules recovery.
    request_id = reserve_request(row["id"], model)
    response = None
    try:
        timeout = max(10, min(120, float(os.getenv("GEMINI_READ_TIMEOUT", "60"))))
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=8, write=15, pool=5), follow_redirects=False) as client:
            response = client.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                   headers={"x-goog-api-key":key}, json=payload)
        if response.status_code != 200:
            code = f"HTTP_{response.status_code}"
            if response.status_code not in (408, 429, 500, 502, 503, 504):
                raise ReviewError(code, "Video provider configuration needs attention. Contact the owner.")
            raise RetryableReviewError(code, retry_delay(response))
        body = response.json()
        candidate = body.get("candidates", [{}])[0]
        finish = candidate.get("finishReason")
        if body.get("promptFeedback", {}).get("blockReason") or finish in ("SAFETY", "RECITATION", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII"):
            raise ReviewError("CONTENT_BLOCKED", "The provider could not review this recording. Try a different gameplay clip.")
        if finish != "STOP":
            raise RetryableReviewError("INCOMPLETE_RESPONSE")
        raw = json.loads("".join(p.get("text", "") for p in candidate.get("content", {}).get("parts", []) if not p.get("thought")))
        try:
            result = validate_assessment(raw, row["duration_seconds"])
        except RuntimeError as exc:
            raise ReviewError("PLAYER_UNCLEAR", str(exc)) from exc
        result.update(model=model, usage=body.get("usageMetadata", {}), analysis_seconds=round(time.monotonic()-started, 1),
                      review_input={'fps':5, 'detail':'default', 'player_marked':marked_video})
        with connect() as db:
            db.execute("INSERT OR REPLACE INTO provider_results VALUES (?,?)", (row["id"], json.dumps(result)))
            db.execute("UPDATE provider_requests SET status='succeeded' WHERE id=?", (request_id,))
        return result
    except RetryableReviewError as exc:
        finish_request(request_id, "retryable", exc.code)
        raise
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
        code = type(exc).__name__ if isinstance(exc, httpx.HTTPError) else "INVALID_RESPONSE"
        finish_request(request_id, "retryable", code)
        raise RetryableReviewError(code) from exc
    except ReviewError as exc:
        finish_request(request_id, "permanent", exc.code)
        raise
    finally:
        with connect() as db:
            db.execute("UPDATE provider_requests SET elapsed_seconds=? WHERE id=?", (time.monotonic()-started, request_id))


def retry_delay(response):
    delay = 30 + random.uniform(0, 5)
    value = response.headers.get("retry-after", "0")
    try:
        delay = max(delay, float(value))
    except ValueError:
        try:
            delay = max(delay, (parsedate_to_datetime(value)-datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            pass
    return min(delay, 86400)


def reserve_request(video_id, model, enforce_daily_limit=True):
    start, end = day_bounds()
    with connect(immediate=True) as db:
        if db.execute("SELECT 1 FROM provider_requests WHERE video_id=? AND status IN ('inflight','succeeded')", (video_id,)).fetchone():
            raise RuntimeError("This clip already has an active or completed review")
        if db.execute("SELECT COUNT(*) FROM provider_requests WHERE video_id=?", (video_id,)).fetchone()[0] >= 6:
            raise ReviewError("ATTEMPT_LIMIT", "This clip reached its retry limit. Contact the owner.")
        count = db.execute("SELECT COUNT(*) FROM provider_requests WHERE created_at>=? AND created_at<?", (start,end)).fetchone()[0]
        if enforce_daily_limit and count >= int(os.getenv("MAX_DAILY_VIDEO_REVIEWS", "20")):
            raise ReviewError("DAILY_BUDGET", "Today's video-review budget is exhausted. Try again tomorrow.")
        return db.execute("INSERT INTO provider_requests(video_id,model,created_at,status) VALUES (?,?,?,'inflight')",
                          (video_id,model,iso())).lastrowid


def finish_request(request_id, status, failure_code=None):
    with connect() as db:
        db.execute("UPDATE provider_requests SET status=?,failure_code=COALESCE(?,failure_code) WHERE id=?", (status,failure_code,request_id))

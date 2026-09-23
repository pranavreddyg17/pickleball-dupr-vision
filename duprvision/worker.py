import fcntl
import json
import math
import os
import statistics
import subprocess
import time
import signal
import threading
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .core import DATA, ROOT, cleanup_media, connect, expire_media, init_db, iso, video_dir
from .pose_review import build_pose_review
from .review import gemini_review

SAMPLE_HZ = 5
TRACK_HZ = 15
MOVEMENT_THRESHOLD = 0.20
SCORE_KIND = "local_motion_v1"
LOCAL_MODEL_LOCK = threading.Lock()
NORMALIZE_LOCK = threading.Lock()


def update(video_id, **fields):
    fields["updated_at"] = iso()
    assignments = ", ".join(f"{key}=?" for key in fields)
    with connect() as db:
        db.execute(f"UPDATE videos SET {assignments} WHERE id=?", (*fields.values(), video_id))


def normalize(row):
    folder = video_dir(row["id"])
    output = folder / "normalized.mp4"
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", row["raw_path"],
               "-map", "0:v:0", "-vf", "scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2,fps=30",
               "-an", "-c:v", "libx264", "-threads", "1", "-preset", "veryfast", "-crf", "27", "-movflags", "+faststart", str(output)]
    process = subprocess.run(command, capture_output=True, text=True, timeout=600)
    if process.returncode or not output.exists():
        raise RuntimeError("This video could not be converted. Try an MP4 or MOV file.")
    import cv2
    capture = cv2.VideoCapture(str(output))
    try:
        for number, fraction in enumerate((0.1, 0.4, 0.7), 1):
            capture.set(cv2.CAP_PROP_POS_MSEC, row["duration_seconds"] * fraction * 1000)
            ok, frame = capture.read()
            if not ok or not cv2.imwrite(str(folder / f"preview-{number}.jpg"), frame):
                raise RuntimeError("Could not generate video previews")
    finally:
        capture.release()
    update(row["id"], normalized_path=str(output), raw_path=None,
           status="WAITING_FOR_PLAYER", stage="Choose your player")
    Path(row["raw_path"]).unlink(missing_ok=True)


def measure_motion(samples, total_samples):
    """Measure image-space activity, not sporting skill or physical court distance."""
    visibility = len(samples) / max(1, total_samples)
    if visibility < 0.5 or len(samples) < 25:
        raise RuntimeError("Too little tracking coverage. Select another preview or use a steady, wider recording.")
    samples = sorted(samples, key=lambda p: p["t"])
    smooth = []
    # A short median filter reduces detector-box jitter without interpolating occlusions.
    for index, point in enumerate(samples):
        nearby = [p for p in samples[max(0, index - 1):index + 2] if abs(p["t"] - point["t"]) < .25]
        smooth.append({"t": point["t"], **{k: statistics.median(p[k] for p in nearby) for k in ("x", "y", "h")}})
    active_seconds = measured_seconds = displacement = 0.0
    speeds = []
    for index, point in enumerate(smooth):
        # Non-overlapping one-second windows; never bridge a lost track.
        if index < SAMPLE_HZ or index % SAMPLE_HZ:
            continue
        window = smooth[index - SAMPLE_HZ:index + 1]
        if any(b["t"] - a["t"] > .3 for a, b in zip(window, window[1:])):
            continue
        start = window[0]
        dt = point["t"] - start["t"]
        height = statistics.median(p["h"] for p in window)
        if dt <= 0 or height <= 0:
            continue
        distance = math.hypot(point["x"] - start["x"], point["y"] - start["y"]) / height
        speed = distance / dt
        if speed > 3:
            continue
        measured_seconds += dt
        displacement += distance
        active_seconds += dt if speed >= MOVEMENT_THRESHOLD else 0
        speeds.append(speed)
    if measured_seconds < 10:
        raise RuntimeError("Not enough continuous tracking to score this clip. Try a clearer player selection.")
    return {"kind": SCORE_KIND, "movement_score": round(100 * active_seconds / measured_seconds, 1),
            "subject_visibility": round(visibility, 3), "measured_seconds": round(measured_seconds, 1),
            "active_seconds": round(active_seconds, 1), "median_speed": round(statistics.median(speeds), 2),
            "displacement_body_heights": round(displacement, 1), "sample_hz": SAMPLE_HZ,
            "movement_threshold": MOVEMENT_THRESHOLD,
            "limitations": ["Activity measurement only; no skill rating is inferred from movement.",
                            "Camera motion, perspective, occlusion and identity switches can distort results.",
                            "Walking between rallies counts. A higher score does not mean better play.",
                            "No ball, shot quality, rally or tactical analysis is performed."]}


def track_and_analyze(row, selection):
    import cv2
    import torch
    from ultralytics import YOLO

    model_path = Path(os.getenv("YOLO_POSE_MODEL", "yolo26n-pose.pt"))
    if not model_path.is_absolute():
        model_path = ROOT / model_path
    if not model_path.exists():
        raise RuntimeError("Local YOLO weights are missing. Run scripts/bootstrap.sh to install them.")
    model = YOLO(str(model_path))
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    capture = cv2.VideoCapture(row["normalized_path"])
    if not capture.isOpened():
        raise RuntimeError("Video could not be opened for tracking")
    duration = row["duration_seconds"]
    tracked = []
    pose_frames = []
    selected_id = None
    selected_distance = float("inf")
    sample_index = 0
    width = height = 0
    try:
        while sample_index / TRACK_HZ < duration - .1:
            current = sample_index / TRACK_HZ
            capture.set(cv2.CAP_PROP_POS_MSEC, current * 1000)
            ok, frame = capture.read()
            if not ok:
                break
            height, width = frame.shape[:2]
            # Preserve low-score detections for ByteTrack's second association stage.
            result = model.track(frame, persist=True, tracker="bytetrack.yaml", classes=[0],
                                 verbose=False, conf=.1, imgsz=640, device=device)[0]
            keep_sample = sample_index % (TRACK_HZ // SAMPLE_HZ) == 0
            boxes = {}
            if result.boxes is not None and result.boxes.id is not None:
                boxes = dict(zip(result.boxes.id.int().cpu().tolist(), result.boxes.xyxy.cpu().tolist()))
                if keep_sample and result.keypoints is not None:
                    poses = result.keypoints.data.cpu().tolist()
                    pose_frames.append((current, {track_id:{"points":points,"height":box[3]-box[1]}
                        for (track_id,box),points in zip(boxes.items(),poses)}))
            distance = abs(current - selection["timestamp_seconds"])
            if distance < .25 and distance < selected_distance:
                cx, cy = selection["x"] * width, selection["y"] * height
                candidates = [(track_id, box) for track_id, box in boxes.items() if box[0] <= cx <= box[2] and box[1] <= cy <= box[3]]
                if len(candidates) == 1:
                    selected_id, selected_distance = candidates[0][0], distance
            if keep_sample:
                tracked.append((current, boxes))
            sample_index += 1
            if sample_index % 50 == 0:
                update(row["id"], stage=f"Tracking player: {min(99, round(current / duration * 100))}%")
    finally:
        capture.release()
    if selected_id is None:
        raise RuntimeError("No unambiguous player at that point. Select the center of your body in another preview.")
    samples = []
    for timestamp, boxes in tracked:
        if selected_id in boxes:
            x1, y1, x2, y2 = boxes[selected_id]
            samples.append({"t": timestamp, "x": (x1 + x2) / 2, "y": y2, "h": y2 - y1})
    result = measure_motion(samples, math.ceil((duration - .1) * SAMPLE_HZ))
    return build_pose_review(result, pose_frames, selected_id)


def process(row):
    try:
        if row["status"] == "PROCESSING":
            with NORMALIZE_LOCK:
                normalize(row)
        else:
            update(row["id"], stage="Tracking selected player", error=None)
            with connect() as db:
                selection = db.execute("SELECT * FROM selections WHERE video_id=?", (row["id"],)).fetchone()
                options = db.execute("SELECT * FROM analysis_options WHERE video_id=?", (row["id"],)).fetchone()
            if not selection:
                raise RuntimeError("Player selection is missing")
            if options and options["engine"] == "gemini":
                update(row["id"], stage="Reviewing shots and rallies")
                result = gemini_review(row, selection, bool(options["external_consent"]))
            else:
                with LOCAL_MODEL_LOCK:
                    result = track_and_analyze(row, selection)
            result["score_date"] = datetime.fromisoformat(row["created_at"]).astimezone(ZoneInfo(os.getenv("APP_TIMEZONE", "America/Chicago"))).date().isoformat()
            with connect() as db:
                db.execute("INSERT OR REPLACE INTO analyses VALUES (?,?,?)", (row["id"], json.dumps(result), iso()))
                db.execute("UPDATE videos SET status='COMPLETED', stage='Complete', error=NULL, updated_at=? WHERE id=?", (iso(), row["id"]))
    except Exception as exc:
        update(row["id"], status="FAILED", stage="Analysis failed", error=str(exc)[:250])
        return
    if row["status"] != "PROCESSING":
        try:
            expire_media(row["id"])
        except OSError as exc:
            print(f"Media cleanup will retry: {type(exc).__name__}", flush=True)


def claim_next():
    with connect(immediate=True) as db:
        row = db.execute("SELECT * FROM videos WHERE status IN ('PROCESSING','QUEUED') ORDER BY created_at LIMIT 1").fetchone()
        if row:
            db.execute("UPDATE videos SET status=?, updated_at=? WHERE id=?", (
                "PREPARING" if row["status"] == "PROCESSING" else "ANALYZING", iso(), row["id"]
            ))
        return dict(row) if row else None


def dispatch(pool, futures, capacity):
    """Only claim as many jobs as can start; excess work remains durably queued."""
    for future in list(futures):
        if future.done():
            future.result()
            futures.remove(future)
    while len(futures) < capacity:
        row = claim_next()
        if not row:
            break
        futures.add(pool.submit(process, row))


def main():
    init_db()
    with (DATA / "worker.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another DUPRVision worker is already running")
        with connect() as db:
            db.execute("UPDATE videos SET status='PROCESSING' WHERE status='PREPARING'")
            db.execute("UPDATE videos SET status='QUEUED' WHERE status='ANALYZING'")
            db.execute("UPDATE provider_requests SET status='interrupted' WHERE status='inflight'")
        last_cleanup = 0
        stopped = threading.Event()
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: stopped.set())
        capacity = max(1, min(4, int(os.getenv("ANALYSIS_CONCURRENCY", "3"))))
        with ThreadPoolExecutor(max_workers=capacity) as pool:
            futures = set()
            while not stopped.is_set():
                if time.monotonic() - last_cleanup > 60:
                    try:
                        cleanup_media()
                    except OSError as exc:
                        print(f"Media cleanup will retry: {type(exc).__name__}", flush=True)
                    last_cleanup = time.monotonic()
                dispatch(pool, futures, capacity)
                if futures:
                    wait(futures, timeout=.5, return_when=FIRST_COMPLETED)
                else:
                    stopped.wait(.5)


if __name__ == "__main__":
    main()

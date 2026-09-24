"""Private report frames and replays from a local, sequential player track."""

import math
import bisect
import os
import subprocess
from pathlib import Path

from .core import ROOT, evidence_dir, video_dir


def track_player(row, selection):
    import cv2
    import torch
    from ultralytics import YOLO

    model_path = Path(os.getenv('YOLO_DETECT_MODEL', 'yolo26n.pt'))
    if not model_path.is_absolute():
        model_path = ROOT / model_path
    if not model_path.is_file():
        return []
    capture = cv2.VideoCapture(row['normalized_path'])
    if not capture.isOpened():
        return []
    fps = capture.get(cv2.CAP_PROP_FPS) or 30
    stride = max(1, round(fps / 5))
    device = 'mps' if torch.backends.mps.is_available() else 'cpu'
    model = YOLO(str(model_path))
    frames = []
    selected_id = None
    selected_distance = float('inf')
    index = 0
    try:
        while capture.grab():
            if index % stride:
                index += 1
                continue
            ok, frame = capture.retrieve()
            if not ok:
                break
            timestamp = index / fps
            detected = model.track(frame, persist=True, tracker='bytetrack.yaml', classes=[0],
                                   conf=.1, imgsz=640, device=device, verbose=False)[0]
            boxes = {}
            if detected.boxes is not None and detected.boxes.id is not None:
                boxes = dict(zip(detected.boxes.id.int().cpu().tolist(), detected.boxes.xyxy.cpu().tolist()))
            distance = abs(timestamp - selection['timestamp_seconds'])
            if distance <= stride / fps + .05 and distance < selected_distance:
                height, width = frame.shape[:2]
                x, y = selection['x'] * width, selection['y'] * height
                matches = [track_id for track_id, box in boxes.items()
                           if box[0] <= x <= box[2] and box[1] <= y <= box[3]]
                if len(matches) == 1:
                    selected_id, selected_distance = matches[0], distance
            frames.append((timestamp, boxes))
            index += 1
    finally:
        capture.release()
    if selected_id is None:
        return []

    anchor = min((i for i, (t, boxes) in enumerate(frames) if selected_id in boxes),
                 key=lambda i: abs(frames[i][0] - selection['timestamp_seconds']))
    accepted = {anchor}
    for indices in (range(anchor + 1, len(frames)), range(anchor - 1, -1, -1)):
        previous_time, previous_box = frames[anchor][0], frames[anchor][1][selected_id]
        for i in indices:
            timestamp, boxes = frames[i]
            if timestamp == previous_time or abs(timestamp - previous_time) > 1.2:
                break
            box = boxes.get(selected_id)
            if box is None:
                continue
            previous_center = ((previous_box[0] + previous_box[2]) / 2, (previous_box[1] + previous_box[3]) / 2)
            center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
            height = max(1, previous_box[3] - previous_box[1])
            if math.dist(previous_center, center) > 2.5 * height:
                break
            accepted.add(i)
            previous_time, previous_box = timestamp, box
    tracked = [(frames[i][0], frames[i][1][selected_id]) for i in sorted(accepted)]
    return tracked


def marked_reference(row, selection, tracked):
    import cv2

    if not tracked:
        return None
    timestamp, box = min(tracked, key=lambda item: abs(item[0] - selection['timestamp_seconds']))
    if abs(timestamp - selection['timestamp_seconds']) > .35:
        return None
    capture = cv2.VideoCapture(row['normalized_path'])
    try:
        capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
        ok, frame = capture.read()
    finally:
        capture.release()
    if not ok:
        return None
    marked = draw_box(frame, box)
    path = video_dir(row['id']) / 'selected-player.jpg'
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), marked, [cv2.IMWRITE_JPEG_QUALITY, 82]):
        return None
    return path


def draw_box(frame, box):
    import cv2

    height, width = frame.shape[:2]
    x1, y1, x2, y2 = (max(0, round(box[0])), max(0, round(box[1])),
                      min(width - 1, round(box[2])), min(height - 1, round(box[3])))
    canvas = frame.copy()
    if x2 > x1 and y2 > y1:
        cv2.rectangle(canvas, (x1, y1), (x2, y2), (75, 190, 125), max(2, math.ceil(width / 500)))
    return canvas


def review_track_video(row, tracked, path):
    """Mark the tracked subject at review cadence, without bridging tracking gaps."""
    import cv2

    if not tracked:
        return False
    capture = cv2.VideoCapture(row['normalized_path'])
    width = round(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = capture.get(cv2.CAP_PROP_FPS)
    frames = capture.get(cv2.CAP_PROP_FRAME_COUNT)
    if not capture.isOpened() or not width or not height or not fps or not frames:
        capture.release()
        return False
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), 5, (width, height))
    times = [sample[0] for sample in tracked]
    complete = False
    try:
        if not writer.isOpened():
            return False
        # Container duration may include a partial final frame beyond decoded video.
        duration = min(float(row['duration_seconds']), frames / fps)
        frame_index = -1
        for index in range(math.ceil(duration * 5 - 1e-8)):
            timestamp = index / 5
            target = min(int(frames) - 1, round(timestamp * fps))
            while frame_index < target:
                if not capture.grab():
                    return False
                frame_index += 1
            ok, frame = capture.retrieve()
            if not ok:
                return False
            at = bisect.bisect_left(times, timestamp)
            nearest = min((i for i in (at - 1, at) if 0 <= i < len(times)),
                          key=lambda i: abs(times[i] - timestamp))
            if abs(times[nearest] - timestamp) <= .15:
                frame = draw_box(frame, tracked[nearest][1])
            writer.write(frame)
        complete = True
    finally:
        capture.release()
        writer.release()
        if not complete:
            path.unlink(missing_ok=True)
    return complete and path.is_file() and path.stat().st_size > 0


def serialize_track(row, tracked):
    import cv2

    capture = cv2.VideoCapture(row['normalized_path'])
    try:
        width, height = capture.get(cv2.CAP_PROP_FRAME_WIDTH), capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
    finally:
        capture.release()
    if not width or not height or not tracked:
        return None
    return {'version': 1, 'sample_hz': 5, 'max_gap': .3, 'samples': [
        [round(t, 3), *[round(max(0, min(1, value / size)), 5)
                       for value, size in zip(box, (width, height, width, height))]]
        for t, box in tracked]}


def save_replay(row, timestamp, number):
    directory = evidence_dir(row['id'])
    start = max(0, timestamp - 2)
    end = min(float(row['duration_seconds']), start + 6)
    temporary = directory / f'{number}.part.mp4'
    path = directory / f'{number}.mp4'
    try:
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                        '-ss', str(start), '-i', row['normalized_path'], '-t', str(end - start),
                        '-map', '0:v:0', '-vf', "scale=w='if(gte(iw,ih),min(iw,960),min(iw,540))':h='if(gte(iw,ih),min(ih,540),min(ih,960))':force_original_aspect_ratio=decrease:force_divisible_by=2,fps=30",
                        '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-threads', '1',
                        '-preset', 'veryfast', '-crf', '25', '-movflags', '+faststart', str(temporary)],
                       check=True, capture_output=True, timeout=45)
        if not temporary.is_file() or temporary.stat().st_size > 4 * 1024 * 1024:
            return None
        temporary.replace(path)
        return {'start': round(start, 3), 'end': round(end, 3), 'fps': 30}
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        temporary.unlink(missing_ok=True)


def build_evidence(row, report, tracked, keep_clips=False):
    import cv2

    if not tracked:
        return []
    shots = [shot for shot in report.get('shots', [])
             if shot.get('confidence') != 'low' and shot.get('shot_type') != 'unknown']
    # Favor a correction opportunity, then spread the remaining review moments through play.
    shots.sort(key=lambda shot: (shot.get('control') != 'error', shot.get('recovered') is not False,
                                shot.get('balanced') is not False, shot['timestamp']))
    candidates = [(float(shot['timestamp']), shot['shot_type']) for shot in shots]
    if not candidates:
        candidates = [(tracked[len(tracked) * i // 4][0], 'Player track') for i in (1, 2, 3)]
    selected = []
    for moment, label in candidates:
        if len(selected) == 3:
            break
        nearest = min(tracked, key=lambda item: abs(item[0] - moment))
        if abs(nearest[0] - moment) > .35 or any(abs(nearest[0] - item[0]) < 2 for item, _ in selected):
            continue
        selected.append((nearest, label))
    if not selected:
        for i in (1, 2, 3):
            sample = tracked[len(tracked) * i // 4]
            if not any(abs(sample[0] - item[0]) < 2 for item, _ in selected):
                selected.append((sample, 'Player track'))
    selected.sort(key=lambda item: item[0][0])
    directory = evidence_dir(row['id'])
    directory.mkdir(parents=True, exist_ok=True)
    output = []
    for number, ((timestamp, box), label) in enumerate(selected, 1):
        capture = cv2.VideoCapture(row['normalized_path'])
        try:
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            ok, frame = capture.read()
        finally:
            capture.release()
        if not ok:
            continue
        canvas = draw_box(frame, box)
        path = directory / f'{number}.jpg'
        temporary = directory / f'{number}.tmp.jpg'
        if cv2.imwrite(str(temporary), canvas, [cv2.IMWRITE_JPEG_QUALITY, 82]):
            temporary.replace(path)
            moment = {'number': number, 'timestamp': round(timestamp, 2), 'label': label}
            if keep_clips:
                clip = save_replay(row, timestamp, number)
                if clip:
                    moment['clip'] = clip
            output.append(moment)
    return output

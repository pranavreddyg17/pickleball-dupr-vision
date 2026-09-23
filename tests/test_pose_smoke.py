"""Opt-in real model smoke test. A still image is not skill-validation footage."""
import os
import subprocess

import pytest
from fastapi.testclient import TestClient

from duprvision import app as web, core, worker


@pytest.mark.skipif(os.getenv("DUPRVISION_POSE_SMOKE") != "1", reason="Opt-in model inference")
def test_real_pose_pipeline_expires_media(tmp_path, monkeypatch):
    import cv2
    from ultralytics import YOLO

    monkeypatch.setattr(core, "DATA", tmp_path)
    monkeypatch.setattr(core, "DB", tmp_path / "duprvision.sqlite3")
    monkeypatch.setattr(web, "DATA", tmp_path)
    monkeypatch.setenv("INVITE_CODE", "")
    monkeypatch.setenv("ANALYSIS_ENGINE", "local")
    source = tmp_path / "still.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-loop", "1",
                    "-i", str(core.ROOT / "static/court.png"), "-t", "60", "-vf",
                    "scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2,fps=30",
                    "-an", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(source)], check=True)
    with TestClient(web.app) as client:
        assert client.post("/api/register", json={"email":"pose@example.test", "password":"local-smoke-test-only", "display_name":"Pose Test"}).status_code == 200
        response = client.post("/api/videos", content=source.read_bytes(), headers={"X-Filename":"still.mp4"})
        assert response.status_code == 200, response.text
        video_id = response.json()["id"]
        worker.process(worker.claim_next())
        frame = cv2.imread(str(core.video_dir(video_id) / "preview-1.jpg"))
        boxes = YOLO(str(core.ROOT / "yolo26n-pose.pt"))(frame, verbose=False, conf=.25)[0].boxes.xyxy.tolist()
        assert boxes
        x1,y1,x2,y2 = max(boxes, key=lambda b:(b[2]-b[0])*(b[3]-b[1]))
        response = client.post(f"/api/videos/{video_id}/select", json={"timestamp_seconds":6,
            "x":(x1+x2)/2/frame.shape[1], "y":(y1+y2)/2/frame.shape[0], "consent":True})
        assert response.status_code == 200, response.text
        worker.process(worker.claim_next())
        result = client.get(f"/api/videos/{video_id}").json()
        assert result["status"] == "COMPLETED", result
        assert result["result"]["kind"] == "pose_review_v1"
        assert result["result"]["rating"] is None
        assert result["result"]["shot_counts"] is None
        assert not core.video_dir(video_id).exists()
        assert client.get(f"/api/videos/{video_id}/preview/1").status_code == 410
        assert client.get("/api/scores").json()["clips"] == 1

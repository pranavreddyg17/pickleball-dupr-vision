"""Disposable UI fixture; never seed the normal application database."""
import json
import os
from datetime import timedelta

from duprvision import core

if not os.environ.get("DUPRVISION_DATA_DIR") or core.DATA.resolve() == (core.ROOT / "data").resolve():
    raise SystemExit("Set DUPRVISION_DATA_DIR to a disposable directory")
core.init_db()
with core.connect() as db:
    for user_id, name, visible in (("qa-local", "Jordan Ellis", 0), ("qa-follow", "Alex Morgan", 1)):
        db.execute("INSERT OR IGNORE INTO users VALUES (?,?,?,?,?,?)", (
            user_id, f"{user_id}@example.test", name, core.PASSWORD_HASHER.hash("local-ui-test-2026"), None, core.iso()))
        db.execute("INSERT OR REPLACE INTO profile_settings VALUES (?,?)", (user_id,visible))
        for index in range(36):
            day=core.now()-timedelta(days=index*3)
            video_id=f"{user_id}-{index}"
            score=60+(index*13)%35
            result={"kind":"video_review_v2","score_date":day.date().isoformat(),
                    "summary":"UI fixture only, not a real assessment. This report checks that compact observations fit on small screens.",
                    "priority":"Test-only practice priority for checking mobile line wrapping.","recording_note":"UI fixture only.",
                    "performance":{"version":"vision_score_v1","score":score,"observed_shots":8,"note":"Test fixture, not a real player score.",
                      "components":[{"name":n,"value":score,"observations":8,"weight":w} for n,w in (("Shot control",.5),("Balance",.25),("Recovery",.25))]},
                    "shot_counts":{"drive":4,"drop":3,"serve":1},
                    "shots":[{"timestamp":12,"shot_type":"drive","confidence":"medium","control":"neutral","balanced":True,"recovered":None}],
                    "rallies":[{"start":8,"end":20}],
                    "evidence":[{"number":1,"timestamp":12,"label":"drive"}] if user_id == "qa-local" and index == 0 else []}
            db.execute("INSERT OR IGNORE INTO videos VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
                video_id,user_id,f"Practice {index+1}.mp4",100,60,None,None,"COMPLETED","Complete",None,core.iso(day),core.iso(day)))
            db.execute("INSERT OR REPLACE INTO analyses VALUES (?,?,?)", (video_id,json.dumps(result),core.iso()))
            if result["evidence"]:
                import cv2
                import numpy as np
                folder = core.evidence_dir(video_id)
                folder.mkdir(parents=True, exist_ok=True)
                canvas = np.full((180, 320, 3), 230, dtype=np.uint8)
                cv2.rectangle(canvas, (120, 30), (185, 150), (75, 190, 125), 3)
                cv2.imwrite(str(folder / "1.jpg"), canvas)
print("Disposable UI fixtures ready")

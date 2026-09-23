"""Low-cost pose observations. Swing motion is not proof of ball contact."""
import math
from collections import Counter


def swing_candidates(frames):
    previous = {}
    peaks = {}
    for timestamp, people in frames:
        for track_id, person in people.items():
            points = person["points"]
            height = person["height"]
            if height <= 0 or len(points) < 11:
                continue
            for shoulder, wrist in ((5, 9), (6, 10)):
                if min(points[shoulder][2], points[wrist][2]) < .55:
                    continue
                relative = ((points[wrist][0]-points[shoulder][0])/height,
                            (points[wrist][1]-points[shoulder][1])/height)
                key = (track_id, wrist)
                old = previous.get(key)
                previous[key] = (timestamp, relative)
                if not old or not .1 <= timestamp-old[0] <= .3:
                    continue
                dt = timestamp-old[0]
                excursion = math.dist(relative, old[1])
                speed = excursion / dt
                if not 1.2 <= speed <= 6 or excursion < .22:
                    continue
                form = "overhead motion" if relative[1] < -.15 else "full swing" if excursion >= .4 else "compact swing"
                candidate = {"timestamp":round(timestamp,1),"track_id":track_id,"form":form,"strength":round(speed,2)}
                events = peaks.setdefault(track_id, [])
                if events and timestamp-events[-1]["timestamp"] < .8:
                    if speed > events[-1]["strength"]:
                        events[-1] = candidate
                else:
                    events.append(candidate)
    return sorted((event for events in peaks.values() for event in events),key=lambda e:e["timestamp"])


def rally_candidates(events):
    groups = []
    for event in events:
        if not groups or event["timestamp"]-groups[-1][-1]["timestamp"] > 4:
            groups.append([])
        groups[-1].append(event)
    return [{"start":g[0]["timestamp"],"end":g[-1]["timestamp"],"motions":len(g),
             "observation":"Possible exchange inferred from multiple players' swing motions; ball contacts unconfirmed."}
            for g in groups if len(g)>=4 and len({e["track_id"] for e in g})>=2 and g[-1]["timestamp"]-g[0]["timestamp"]>=2]


def build_pose_review(movement, frames, selected_id):
    events = swing_candidates(frames)
    selected = [{k:v for k,v in e.items() if k not in ("track_id","strength")} for e in events if e["track_id"]==selected_id]
    rallies = rally_candidates(events)
    counts = dict(Counter(e["form"] for e in selected))
    summary = (f"The selected player was tracked in {movement['subject_visibility']:.0%} of sampled frames. "
               f"Pose analysis found {len(selected)} possible stroke motions and {len(rallies)} possible rally sequences involving multiple players. "
               "These are motion candidates, not confirmed ball contacts; drive/drop labels, shot success and a DUPR estimate cannot be established by this pose-only analysis.")
    return {"kind":"pose_review_v1", "source":"YOLO26 pose analysis", "summary":summary,
            "rating":None, "rating_status":"Shot quality not established", "shot_counts":None,
            "shots":[], "rallies":[], "swing_candidates":selected, "swing_counts":counts,
            "rally_candidates":rallies, "strengths":[], "priorities":[],
            "metrics":{k:movement[k] for k in ("subject_visibility","measured_seconds","active_seconds","median_speed")},
            "limitations":["Pose motion does not establish drive, drop, dink or ball contact.",
                           "Occlusion, camera motion and tracker identity switches can affect motion counts.",
                           "No rating is derived from motion counts."]}

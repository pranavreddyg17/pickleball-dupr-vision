"""Offline report evaluation. Never contacts a provider or changes application data."""
import argparse
import json
import statistics
from pathlib import Path


def compare_events(predicted, expected, tolerance=1.0):
    """Maximum one-to-one timestamp matching, independent of predicted shot type."""
    assigned = {}

    def assign(index, visited):
        candidates = sorted(range(len(expected)), key=lambda j: abs(predicted[index]["timestamp"] - expected[j]["timestamp"]))
        for j in candidates:
            if j in visited or abs(predicted[index]["timestamp"] - expected[j]["timestamp"]) > tolerance:
                continue
            visited.add(j)
            if j not in assigned or assign(assigned[j], visited):
                assigned[j] = index
                return True
        return False

    for i in range(len(predicted)):
        assign(i, set())
    correct = sum(predicted[i]["shot_type"] == expected[j]["shot_type"] for j, i in assigned.items())
    return {"matched": len(assigned), "predicted": len(predicted), "labeled": len(expected),
            "precision": len(assigned) / len(predicted) if predicted else None,
            "recall": len(assigned) / len(expected) if expected else None,
            "shot_type_accuracy": correct / len(assigned) if assigned else None}


def summarize(reports, labels=None):
    scores = [r["performance"]["score"] for r in reports if r.get("performance", {}).get("score") is not None]
    latency = sorted(r["analysis_seconds"] for r in reports if "analysis_seconds" in r and not r.get("cache_hit"))
    return {"runs": len(reports), "scored_runs": len(scores),
            "score_min": min(scores) if scores else None, "score_max": max(scores) if scores else None,
            "score_stddev": round(statistics.pstdev(scores), 2) if scores else None,
            "median_request_seconds": statistics.median(latency) if latency else None,
            "events": [compare_events(r.get("shots", []), labels["shots"]) for r in reports] if labels is not None else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path, help="JSON reports for the same clip and player")
    parser.add_argument("--labels", type=Path, help='Human-reviewed JSON: {"shots":[{"timestamp":1.0,"shot_type":"drive"}]}')
    args = parser.parse_args()
    reports = [json.loads(p.read_text()) for p in args.reports]
    labels = json.loads(args.labels.read_text()) if args.labels else None
    print(json.dumps(summarize(reports, labels), indent=2))


if __name__ == "__main__":
    main()

"""Owner-only local diagnostics. Prints aggregate counts, never keys or user data."""
import json
import sqlite3
import statistics

from .core import DB


def main():
    with sqlite3.connect(f"{DB.as_uri()}?mode=ro", uri=True) as db:
        statuses = dict(db.execute("SELECT status,COUNT(*) FROM videos GROUP BY status"))
        failures = dict(db.execute("SELECT COALESCE(failure_code,'none'),COUNT(*) FROM provider_requests GROUP BY failure_code"))
        timings = sorted(r[0] for r in db.execute("SELECT elapsed_seconds FROM provider_requests WHERE elapsed_seconds IS NOT NULL"))
        output = {"jobs": statuses, "request_outcomes": dict(db.execute("SELECT status,COUNT(*) FROM provider_requests GROUP BY status")),
                  "failure_codes": failures, "timed_requests": len(timings),
                  "median_request_seconds": round(statistics.median(timings), 2) if timings else None,
                  "provider_cooldowns": dict(db.execute("SELECT name,cooldown_until FROM provider_health"))}
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()

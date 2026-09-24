"""Run one real analysis in a disposable database, without changing player accounts."""
import argparse
import json
import os
import tempfile
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--x', type=float, required=True)
    parser.add_argument('--y', type=float, required=True)
    parser.add_argument('--engine', choices=('gemini', 'self_hosted'), default='gemini')
    parser.add_argument('--external-consent', action='store_true',
                        help='Authorize one Gemini request; not needed for a self-hosted model')
    args = parser.parse_args()
    if not args.video.is_file() or not 0 <= args.x <= 1 or not 0 <= args.y <= 1:
        parser.error('Supply an existing clip and normalized player coordinates')
    if args.engine == 'gemini' and not args.external_consent:
        parser.error('Gemini review requires --external-consent')
    with tempfile.TemporaryDirectory(prefix='duprvision-analysis-probe-') as directory:
        # Set these before importing modules that resolve storage at import time.
        os.environ['DUPRVISION_DATA_DIR'] = directory
        os.environ['ANALYSIS_ENGINE'] = args.engine
        from fastapi.testclient import TestClient
        from duprvision import core, worker
        from duprvision.app import app

        started = time.monotonic()
        with TestClient(app) as client:
            response = client.post('/api/register', json={
                'email': 'probe@example.test', 'password': 'temporary-probe-account',
                'display_name': 'Analysis probe'})
            response.raise_for_status()
            response = client.post('/api/videos', content=args.video.read_bytes(),
                                   headers={'X-Filename': args.video.name})
            response.raise_for_status()
            video_id = response.json()['id']
            worker.process(worker.claim_next())
            video = client.get(f'/api/videos/{video_id}').json()
            response = client.post(f'/api/videos/{video_id}/select', json={
                'timestamp_seconds': video['duration_seconds'] * .4,
                'x': args.x, 'y': args.y, 'consent': True,
                'external_consent': args.engine == 'gemini' and args.external_consent,
                'save_evidence': False})
            response.raise_for_status()
            # Do not run a worker loop: provider retries must not make extra paid calls.
            worker.process(worker.claim_next())
            video = client.get(f'/api/videos/{video_id}').json()
            with core.connect() as db:
                requests = [dict(row) for row in db.execute(
                    'SELECT model,status,failure_code,elapsed_seconds FROM provider_requests')]
            record = {'filename': args.video.name, 'engine': args.engine,
                      'selection': {'x': args.x, 'y': args.y},
                      'status': video['status'], 'error': video.get('error'),
                      'elapsed_seconds': round(time.monotonic() - started, 2),
                      'requests': requests, 'result': video.get('result')}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(record, indent=2) + '\n')
            print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()

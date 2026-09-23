"""Keep the local app, temporary tunnel, and stable Worker route in sync."""
import json
import fcntl
import os
import queue
import re
import signal
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "")
LOG = ROOT / "data" / "public.log"
PUBLIC_URL = "https://pickle.duprvision.workers.dev"
LOCAL_HEALTH = "http://127.0.0.1:3000/api/health"
TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
stopping = threading.Event()


def log(message):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n"
    with LOG.open("a") as stream:
        stream.write(line)


def healthy(url):
    try:
        with urllib.request.urlopen(url, timeout=6) as response:
            body = json.load(response)
        return body.get("ok") is True and body.get("worker_running") is True
    except (OSError, ValueError, TimeoutError):
        return False


def terminate(process):
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=120)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def start_app():
    with LOG.open("a") as output:
        return subprocess.Popen(["./scripts/start.sh"], cwd=ROOT, stdout=output,
                                stderr=subprocess.STDOUT, start_new_session=True)


def start_tunnel():
    process = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", "http://127.0.0.1:3000", "--no-autoupdate"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, start_new_session=True,
    )
    discovered = queue.Queue()

    def read_output():
        for line in process.stdout:
            with LOG.open("a") as output:
                output.write(line)
            match = TUNNEL_URL.search(line)
            if match:
                discovered.put(match.group())
            elif 'Unauthorized: Tunnel not found' in line:
                discovered.put(None)

    threading.Thread(target=read_output, daemon=True).start()
    return process, discovered


def deploy(origin):
    # --var replaces only this binding; API keys stay in the local .env file.
    result = subprocess.run(
        ["npx", "--yes", "wrangler", "deploy", "--config", "cloudflare/wrangler.jsonc",
         "--var", f"ORIGIN_URL:{origin}"],
        cwd=ROOT, capture_output=True, text=True, timeout=90,
    )
    with LOG.open("a") as output:
        output.write(result.stdout)
        output.write(result.stderr)
    return result.returncode == 0


def main():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    lock = (LOG.parent / "public.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("DUPRVision public supervisor is already running")
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopping.set())
    app = tunnel = None
    origin = deployed = None
    urls = None
    failures = 0
    last_check = 0
    try:
        while not stopping.is_set():
            if app is None or app.poll() is not None:
                if app is not None:
                    log("App exited; restarting")
                app = start_app()
                origin = None
                time.sleep(2)
            if not healthy(LOCAL_HEALTH):
                stopping.wait(2)
                continue
            if tunnel is None or tunnel.poll() is not None:
                tunnel, urls = start_tunnel()
                origin = None
                failures = 0
            try:
                new_origin = urls.get(timeout=2)
                if new_origin is None:
                    log("Tunnel authorization expired; reconnecting")
                    terminate(tunnel)
                    tunnel = None
                    origin = None
                    stopping.wait(5)
                    continue
                if new_origin != origin:
                    origin = new_origin
                    log(f"Tunnel available: {origin}")
            except queue.Empty:
                pass
            if origin and deployed != origin:
                if deploy(origin):
                    deployed = origin
                    log(f"Worker routed to tunnel: {origin}")
                else:
                    log("Worker deployment failed; retrying")
                    stopping.wait(10)
            if origin and time.monotonic() - last_check >= 30:
                failures = 0 if tunnel.poll() is None else failures + 1
                last_check = time.monotonic()
                if failures >= 2:
                    log("Tunnel unreachable; reconnecting")
                    terminate(tunnel)
                    tunnel = None
                    origin = None
                    failures = 0
            stopping.wait(1)
    finally:
        terminate(tunnel)
        terminate(app)


if __name__ == "__main__":
    main()

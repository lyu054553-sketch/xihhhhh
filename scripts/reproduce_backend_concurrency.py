"""Reproduce backend read concurrency on a new temporary demo database.

No reset or write HTTP route is called. The parent owns this backend process and
stops it through stdin so SQLite is closed before removing the temporary folder.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
PATHS = ("/proposals", "/execution-tasks", "/work-items")


def run_backend():
    import uvicorn
    sys.path.insert(0, str(ROOT))
    from backend import api
    config = uvicorn.Config(api.app, host="127.0.0.1", port=0, log_level="error", lifespan="off")
    server = uvicorn.Server(config)
    bound = config.bind_socket()

    def stop_on_input():
        sys.stdin.readline()
        server.should_exit = True

    threading.Thread(target=stop_on_input, daemon=True).start()
    Path(os.environ["CONCURRENCY_READY_FILE"]).write_text(str(bound.getsockname()[1]), encoding="ascii")
    try:
        server.run(sockets=[bound])
    finally:
        api.store.close()
        bound.close()


def summarize(results):
    return {"requests": len(results), "failed": sum(status != 200 for _, status in results),
            "responses": dict(Counter(f"{path} HTTP {status}" for path, status in results))}


def reproduce(workers, rounds):
    with tempfile.TemporaryDirectory(prefix="inventory-concurrency-") as directory:
        root = Path(directory)
        ready, log = root / "ready.txt", root / "backend.log"
        environment = dict(os.environ, INVENTORY_AGENT_DB=str(root / "isolated.db"), INVENTORY_AGENT_MODE="demo",
                           CONCURRENCY_READY_FILE=str(ready), PYTHONIOENCODING="utf-8")
        with log.open("w", encoding="utf-8") as stream:
            child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve"], cwd=ROOT,
                                     env=environment, stdin=subprocess.PIPE, stdout=stream, stderr=subprocess.STDOUT,
                                     text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                deadline = time.monotonic() + 15
                while not ready.exists():
                    if child.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError("Temporary backend could not start: " + log.read_text(encoding="utf-8"))
                    time.sleep(.05)
                base = f"http://127.0.0.1:{ready.read_text(encoding='ascii')}"
                while True:
                    try:
                        with urlopen(base + "/openapi.json", timeout=2) as response:
                            version = json.load(response)["info"]["version"]
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise
                        time.sleep(.05)

                expected = {}

                def read(path):
                    try:
                        with urlopen(base + "/api/v1" + path, timeout=10) as response:
                            payload = json.load(response)
                            if path not in expected:
                                expected[path] = payload
                            if payload != expected[path]:
                                return path, "inconsistent-payload"
                            return path, response.status
                    except HTTPError as error:
                        error.close()
                        return path, error.code
                    except (ValueError, OSError):
                        return path, "transport-or-json-error"

                sequential = [read(path) for path in PATHS * 15]
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    concurrent = list(pool.map(read, PATHS * rounds))
            finally:
                if child.poll() is None:
                    try:
                        child.stdin.write("stop\n")
                        child.stdin.flush()
                        child.wait(timeout=5)
                    except (OSError, subprocess.TimeoutExpired):
                        child.terminate()
                        try:
                            child.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            child.kill()
                            child.wait(timeout=5)
                child.stdin.close()
        errors = log.read_text(encoding="utf-8")
        return {"api_version": version, "python": sys.version.split()[0], "sqlite": sqlite3.sqlite_version,
                "database": "fresh temporary demo database", "reset_requests": 0, "write_requests": 0,
                "workers": workers, "payload_check": "each response equals its serial baseline", "sequential": summarize(sequential), "concurrent": summarize(concurrent),
                "error_examples": sorted({line for line in errors.splitlines()
                                          if line.startswith(("TypeError:", "sqlite3.", "KeyError:"))})}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=9)
    parser.add_argument("--rounds", type=int, default=50, help="Concurrent requests per read route")
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.serve:
        run_backend()
        return 0
    if not 1 <= args.workers <= 32 or not 1 <= args.rounds <= 100:
        parser.error("workers must be 1..32 and rounds must be 1..100")
    result = reproduce(args.workers, args.rounds)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(bool(result["sequential"]["failed"] or result["concurrent"]["failed"]))


if __name__ == "__main__":
    raise SystemExit(main())

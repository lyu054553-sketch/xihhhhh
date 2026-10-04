"""Verify versioned HTTP writes on an owned process and temporary database.

Run with the project's Python environment. No persistent project database,
demo reset, external service or model credential is used.
"""
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
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
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
WORKERS = 32


def verify():
    with tempfile.TemporaryDirectory(prefix="backend-delivery-") as directory:
        folder = Path(directory)
        ready, database = folder / "ready", folder / "test.db"
        environment = dict(os.environ, INVENTORY_AGENT_DB=str(database), INVENTORY_AGENT_MODE="demo",
                           CONCURRENCY_READY_FILE=str(ready))
        with (folder / "server.log").open("w") as log:
            child = subprocess.Popen([sys.executable, str(ROOT / "scripts/reproduce_backend_concurrency.py"), "--serve"],
                                     cwd=ROOT, env=environment, stdin=subprocess.PIPE, stdout=log, stderr=log, text=True)
            try:
                deadline = time.monotonic()+15
                while not ready.exists():
                    if child.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("Temporary server failed to start")
                    time.sleep(.05)
                base = "http://127.0.0.1:" + ready.read_text()

                def request(path, body=None, headers=None):
                    req = Request(base+"/api/v1"+path, data=json.dumps(body).encode() if body is not None else None,
                                  headers={"Content-Type": "application/json", **(headers or {})})
                    try:
                        with urlopen(req, timeout=15) as response:
                            return response.status, json.load(response)
                    except HTTPError as exc:
                        return exc.code, json.load(exc)

                while True:
                    try:
                        request("/health")
                        break
                    except OSError:
                        if time.monotonic() > deadline:
                            raise
                        time.sleep(.05)

                def together(path, body, key=None):
                    barrier = threading.Barrier(WORKERS)
                    def send(_):
                        barrier.wait(timeout=10)
                        return request(path, body, {"Idempotency-Key": key} if key else {})
                    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                        return list(pool.map(send, range(WORKERS)))

                calculated = together("/workbenches/transfer/calculate", {"expected_version": 0, "input": {"risk_id": 1, "quantity": 40}})
                assert Counter(status for status, _ in calculated) == {200: 1, 409: 31}, calculated
                assert all(result["detail"]["code"] == "version_conflict" for status, result in calculated if status == 409)
                status, saved = request("/workbenches/transfer/save", {"expected_version": 1, "expected_proposal_version": 1, "input": {"risk_id": 1, "quantity": 40}})
                assert status == 200, saved
                proposal = saved["proposal"]
                path = "/proposals/" + proposal["id"]
                version = {"expected_version": proposal["current_version"]}
                assert request(path+"/submit", version)[0] == 200
                approvals = together(path+"/approve", version, "approve-network")
                executions = together(path+"/execute", version, "execute-network")
                for group in (approvals, executions):
                    assert all(status == 200 for status, _ in group), group
                    assert len({row["id"] for _, row in group}) == 1
                task = executions[0][1]
                receipt = request("/execution-tasks/"+task["id"]+"/status", {"expected_version": 1, "status": "completed", "receipt_ref": "manual-http", "actual_cash": 1400})
                assert receipt[0] == 200 and receipt[1]["metadata"]["actual_cash"] == 1400, receipt
                assert not receipt[1]["metadata"]["external_write"]
                with sqlite3.connect(database) as conn:
                    counts = {table: conn.execute("SELECT COUNT(*) FROM "+table).fetchone()[0] for table in ("approvals", "execution_tasks")}
                assert counts == {"approvals": 1, "execution_tasks": 1}, counts
                return {"workers": WORKERS, "database": "fresh temporary database", "calculate": {"HTTP 200": 1, "HTTP 409 version_conflict": 31},
                        "approval": {"requests": WORKERS, "HTTP 200": WORKERS, "distinct_records": 1},
                        "execute": {"requests": WORKERS, "HTTP 200": WORKERS, "distinct_records": 1},
                        "receipt": {"actual_cash": 1400, "confirmation_method": "manual", "external_write": False}, "database_counts": counts}
            finally:
                if child.poll() is None:
                    child.stdin.write("stop\n")
                    child.stdin.flush()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=5)
                child.stdin.close()


if __name__ == "__main__":
    print(json.dumps(verify(), ensure_ascii=False, indent=2))

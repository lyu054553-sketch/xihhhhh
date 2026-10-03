"""Run every acceptance check and retain failures in output/acceptance.

Use the Python interpreter containing requirements-dev.txt. No test filters or
retries are applied: a failed check stays failed even when later checks pass.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Step:
    name: str
    command: tuple[str, ...]


def acceptance_steps(root: Path) -> list[Step]:
    """Expand file arguments here so Windows does not depend on shell globbing."""
    backend_files = sorted(path.relative_to(root).as_posix() for path in (root / "backend").rglob("*.py"))
    node_tests = sorted(path.relative_to(root).as_posix() for path in (root / "tests").glob("*.mjs"))
    if not backend_files or not node_tests or not list((root / "tests").glob("test*.py")):
        raise ValueError("Acceptance sources are missing; refusing an empty test run")
    python = sys.executable
    return [
        Step("backend-syntax", (python, "-m", "py_compile", *backend_files)),
        Step("frontend-syntax", ("node", "--check", "app.js")),
        Step("node-tests", ("node", "--test", *node_tests)),
        Step("sample-data", (python, "sample-data/generate.py", "--check")),
        Step("python-tests", (python, "-m", "unittest", "discover", "-s", "tests", "-v")),
        Step("backend-concurrency", (python, "scripts/reproduce_backend_concurrency.py")),
    ]


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_summary(directory: Path, report: dict) -> None:
    # Readers see a complete JSON document, including when a later check fails.
    temporary = directory / "summary.json.tmp"
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(directory / "summary.json")


def run_steps(steps: list[Step], root: Path, output: Path) -> tuple[int, Path]:
    if not steps:
        raise ValueError("Acceptance requires at least one check")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + f"-{os.getpid()}"
    directory = output / run_id
    directory.mkdir(parents=True, exist_ok=False)
    report = {
        "schema_version": 1, "status": "running", "exit_code": None,
        "started_at": timestamp(), "finished_at": None,
        "root": str(root), "python": sys.version, "platform": platform.platform(),
        "steps": [{"name": step.name, "command": list(step.command), "status": "not_run",
                   "return_code": None, "duration_seconds": None, "log": f"{index:02d}-{step.name}.log"}
                  for index, step in enumerate(steps, 1)],
    }
    environment = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1",
                       FRONTEND_TEST_ARTIFACTS=str(directory / "browser"))
    write_summary(directory, report)
    interrupted = False
    for result, step in zip(report["steps"], steps):
        print(f"Running {step.name}; log: {directory / result['log']}", flush=True)
        result["status"] = "running"
        write_summary(directory, report)
        started = time.monotonic()
        with (directory / result["log"]).open("w", encoding="utf-8") as stream:
            try:
                child = subprocess.run(step.command, cwd=root, env=environment,
                                       stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
                result["return_code"] = child.returncode
                result["status"] = "passed" if child.returncode == 0 else "failed"
            except OSError as error:
                result["status"] = "error"
                result["error"] = str(error)
                stream.write(f"Could not run check: {error}\n")
            except KeyboardInterrupt:
                result["status"] = "interrupted"
                stream.write("Acceptance interrupted; remaining checks were not run.\n")
                interrupted = True
        result["duration_seconds"] = round(time.monotonic() - started, 3)
        write_summary(directory, report)
        print(f"{step.name}: {result['status']} (exit {result['return_code']})", flush=True)
        if interrupted:
            break
    code = 130 if interrupted else int(any(result["status"] != "passed" for result in report["steps"]))
    report.update(status="interrupted" if interrupted else "failed" if code else "passed",
                  exit_code=code, finished_at=timestamp())
    write_summary(directory, report)
    print(f"Acceptance {report['status']}; summary: {directory / 'summary.json'}", flush=True)
    return code, directory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("output/acceptance"),
                        help="Parent of per-run reports, relative to the repository (default: output/acceptance)")
    args = parser.parse_args(argv)
    output = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    try:
        code, _ = run_steps(acceptance_steps(ROOT), ROOT, output.resolve())
    except (OSError, ValueError) as error:
        print(f"Acceptance could not start or record results: {error}", file=sys.stderr)
        return 2
    return code


if __name__ == "__main__":
    raise SystemExit(main())

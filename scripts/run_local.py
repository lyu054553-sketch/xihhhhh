"""Start the v1.2 backend and the public frontend as one local application."""

from __future__ import annotations

import argparse
import http.client
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

from serve_frontend import ROOT, serve, validate_api_base


def default_database() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share")
    return base / "huobuyaqian" / "retail-demo-v1.2.db"


def configuration(args):
    """Validate without importing the backend, creating files, or binding ports."""
    if sys.version_info < (3, 10):
        raise ValueError("Python 3.10 or newer is required")
    if not 1 <= args.port <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    if not args.host or any(char.isspace() for char in args.host):
        raise ValueError("Listen host must be a hostname or IP address")
    api_base = validate_api_base(args.api_base)
    database = Path(args.database).expanduser().resolve()
    if not api_base:
        missing = [name for name in ("fastapi", "uvicorn", "pydantic", "openpyxl")
                   if importlib.util.find_spec(name) is None]
        if missing:
            raise ValueError("Missing backend dependencies: " + ", ".join(missing)
                             + ". Install them with: python -m pip install -r requirements.txt")
        if not (ROOT / "backend" / "api.py").is_file():
            raise ValueError("The local v1.2 backend is missing")
        if database.is_relative_to(ROOT):
            raise ValueError("Keep the database outside the repository; use --database with an external path")
        if database.exists() and not database.is_file():
            raise ValueError("The database path must name a file")
    if not (ROOT / "index.html").is_file():
        raise ValueError("The frontend index.html is missing")
    return api_base, database


def backend_child(ready_file: Path):
    """Private worker: a bound ephemeral socket avoids port-selection races."""
    import uvicorn

    sys.path.insert(0, str(ROOT))
    config = uvicorn.Config("backend.api:app", host="127.0.0.1", port=0,
                            log_level="warning", access_log=False)
    listener = config.bind_socket()
    worker = uvicorn.Server(config)

    def stop_on_parent_exit():
        # The parent owns this pipe. A byte or EOF requests graceful shutdown.
        os.read(sys.stdin.fileno(), 1)
        worker.should_exit = True

    threading.Thread(target=stop_on_parent_exit, daemon=True).start()
    try:
        ready_file.write_text(str(listener.getsockname()[1]), encoding="ascii")
        worker.run(sockets=[listener])
    finally:
        listener.close()


def wait_for_backend(process, ready_file: Path, timeout=30.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Local backend exited during startup (code {process.returncode})")
        try:
            port = int(ready_file.read_text(encoding="ascii"))
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=0.5)
            try:
                connection.request("GET", "/api/v1/health")
                response = connection.getresponse()
                payload = json.loads(response.read())
                if response.status == 200 and payload.get("status") == "ok":
                    return f"http://127.0.0.1:{port}/api/v1"
            finally:
                connection.close()
        except (OSError, ValueError, http.client.HTTPException):
            pass
        time.sleep(0.1)
    raise RuntimeError("Local backend did not become healthy within 30 seconds")


def stop_backend(process):
    if process is None:
        return
    if process.stdin:
        try:
            if process.poll() is None:
                process.stdin.write(b"\n")
                process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def run(args, api_base, database):
    process = None
    stopped = threading.Event()
    backend_failed = threading.Event()
    server = None
    with tempfile.TemporaryDirectory(prefix="huobuyaqian-launch-") as temporary:
        with tempfile.TemporaryFile(mode="w+b") as backend_log:
            try:
                if not api_base:
                    database.parent.mkdir(parents=True, exist_ok=True)
                    environment = os.environ.copy()
                    environment["INVENTORY_AGENT_DB"] = str(database)
                    environment.setdefault("INVENTORY_AGENT_MODE", "demo")
                    environment["PYTHONUNBUFFERED"] = "1"
                    ready_file = Path(temporary) / "backend-port.txt"
                    process = subprocess.Popen(
                        [sys.executable, str(Path(__file__).resolve()), "--backend-child", "--ready-file", str(ready_file)],
                        cwd=ROOT, env=environment, stdin=subprocess.PIPE,
                        stdout=backend_log, stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    )
                    api_base = wait_for_backend(process, ready_file)
                    print(f"Local v1.2 backend: {api_base}", flush=True)
                    print(f"Database: {database}", flush=True)
                else:
                    print(f"External v1.2 API: {api_base}", flush=True)

                server = serve(ROOT, api_base, args.host, args.port)

                def monitor_backend():
                    while not stopped.wait(0.5):
                        if process.poll() is not None:
                            backend_failed.set()
                            server.shutdown()
                            return

                if process is not None:
                    threading.Thread(target=monitor_backend, daemon=True).start()
                print(f"Open http://{args.host}:{server.server_port}", flush=True)
                print("Press Ctrl+C to stop this application and its own backend.", flush=True)
                try:
                    server.serve_forever(poll_interval=0.2)
                except KeyboardInterrupt:
                    print("\nStopping local application...", flush=True)
                if backend_failed.is_set():
                    raise RuntimeError(f"Local backend stopped unexpectedly (code {process.poll()})")
                return 0
            except KeyboardInterrupt:
                print("\nStartup cancelled.", flush=True)
                return 0
            except (OSError, RuntimeError, ValueError) as error:
                print(f"Startup failed: {error}", file=sys.stderr, flush=True)
                if process is not None:
                    backend_log.flush()
                    backend_log.seek(0, os.SEEK_END)
                    backend_log.seek(max(0, backend_log.tell() - 8000))
                    diagnostics = backend_log.read().decode("utf-8", errors="replace").strip()
                    if diagnostics:
                        print(diagnostics, file=sys.stderr, flush=True)
                return 1
            finally:
                stopped.set()
                if server is not None:
                    server.server_close()
                stop_backend(process)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--api-base", default=os.environ.get("AGENT_API_BASE"),
                        help="Use an external /api/v1 URL instead of starting the local backend")
    parser.add_argument("--database", default=os.environ.get("INVENTORY_AGENT_DB") or str(default_database()))
    parser.add_argument("--check", action="store_true", help="Check configuration without creating a DB or starting services")
    parser.add_argument("--backend-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--ready-file", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.backend_child:
        if args.ready_file is None:
            parser.error("Internal backend worker requires --ready-file")
        backend_child(args.ready_file)
        return 0
    try:
        api_base, database = configuration(args)
    except ValueError as error:
        parser.error(str(error))
    if args.check:
        print(f"Configuration OK: http://{args.host}:{args.port}")
        print(f"API: {api_base or 'local v1.2 backend on a private dynamic port'}")
        if not api_base:
            print(f"Database: {database}")
        print("No database was created and no service was started.")
        return 0
    return run(args, api_base, database)


if __name__ == "__main__":
    raise SystemExit(main())

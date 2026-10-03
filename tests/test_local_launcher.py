"""Exercise launcher ownership with real, isolated backend subprocesses."""

from contextlib import closing, contextmanager, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

from scripts import run_local


ROOT = Path(__file__).resolve().parents[1]


class LocalLauncherTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="launcher-test-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.daily = self.directory / "daily.db"
        with closing(sqlite3.connect(self.daily)) as database:
            database.execute("CREATE TABLE sentinel (value TEXT)")
            database.execute("INSERT INTO sentinel VALUES ('daily data must survive')")
            database.commit()
        self.original_daily = self.daily.read_bytes()
        self.original_mtime = self.daily.stat().st_mtime_ns
        self.environment = {
            "INVENTORY_AGENT_DB": str(self.daily),
            "INVENTORY_AGENT_MODE": "real",
            "AGENT_API_BASE": "",
            "LOCALAPPDATA": str(self.directory / "user-data"),
        }
        self.env_patch = patch.dict(os.environ, self.environment)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def options(self, **changes):
        values = dict(host="127.0.0.1", port=8000, api_base=None,
                      database=None, demo_session=True)
        values.update(changes)
        return SimpleNamespace(**values)

    def request(self, base, path, body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(base + path, data=data, headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=10) as response:
            return json.load(response)

    @contextmanager
    def running(self, args=None):
        """Run the real lifecycle; capture its server to request graceful shutdown."""
        args = args or self.options()
        api_base, database = run_local.configuration(args)
        args.port = 0  # Let the operating system allocate the test frontend port.
        servers, processes, result = [], [], []
        output = io.StringIO()
        actual_serve, actual_popen = run_local.serve, subprocess.Popen

        def serve(*arguments):
            server = actual_serve(*arguments)
            servers.append(server)
            return server

        def popen(*arguments, **keywords):
            process = actual_popen(*arguments, **keywords)
            processes.append((process, keywords))
            return process

        with patch.object(run_local, "serve", side_effect=serve), \
                patch.object(run_local.subprocess, "Popen", side_effect=popen), \
                redirect_stdout(output), redirect_stderr(output):
            thread = threading.Thread(target=lambda: result.append(run_local.run(args, api_base, database)), daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 35
                while not servers and thread.is_alive() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(servers, output.getvalue())
                base = f"http://127.0.0.1:{servers[0].server_port}/api/v1"
                yield SimpleNamespace(base=base, processes=processes, output=output)
            finally:
                if servers:
                    servers[0].shutdown()
                thread.join(timeout=12)
                self.assertFalse(thread.is_alive(), output.getvalue())
                for process, _ in processes:
                    self.assertIsNotNone(process.poll(), "Owned backend survived launcher shutdown")
                self.assertEqual(result, [0], output.getvalue())

    def assert_daily_untouched(self):
        self.assertEqual(self.daily.read_bytes(), self.original_daily)
        self.assertEqual(self.daily.stat().st_mtime_ns, self.original_mtime)
        self.assertEqual(os.environ["INVENTORY_AGENT_DB"], str(self.daily))
        self.assertEqual(os.environ["INVENTORY_AGENT_MODE"], "real")

    def test_fresh_demo_sessions_restore_seed_and_never_open_parent_daily_database(self):
        paths = []
        for iteration in range(2):
            with self.running() as session:
                process, options = session.processes[0]
                path = Path(options["env"]["INVENTORY_AGENT_DB"])
                paths.append(path)
                self.assertTrue(path.is_file())
                self.assertNotEqual(path, self.daily)
                self.assertEqual(options["env"]["INVENTORY_AGENT_MODE"], "demo")
                self.assertEqual(options["creationflags"], subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                risks = self.request(session.base, "/risks")["items"]
                self.assertTrue(risks, "Actual backend must seed the synthetic session")
                proposal = self.request(session.base, "/proposals")["items"][0]
                self.assertEqual(proposal["status"], "pending_approval")
                if iteration == 0:
                    approved = self.request(session.base, f'/proposals/{proposal["id"]}/approve', {})
                    self.assertEqual(approved["status"], "approved")
                    changed = self.request(session.base, "/proposals")["items"][0]
                    self.assertEqual(changed["status"], "approved")
                self.assert_daily_untouched()
            self.assertFalse(path.parent.exists(), "Session directory and SQLite side files must be removed")
            self.assertIsNotNone(process.poll())
        self.assertNotEqual(paths[0], paths[1])
        self.assert_daily_untouched()

    def test_normal_real_start_preserves_daily_database_across_sessions(self):
        for _ in range(2):
            with self.running(self.options(demo_session=False)) as session:
                _, options = session.processes[0]
                self.assertEqual(Path(options["env"]["INVENTORY_AGENT_DB"]), self.daily)
                self.assertEqual(options["env"]["INVENTORY_AGENT_MODE"], "real")
                self.assertEqual(self.request(session.base, "/risks")["items"], [])
            self.assertTrue(self.daily.is_file())
            with closing(sqlite3.connect(self.daily)) as database:
                self.assertEqual(database.execute("SELECT value FROM sentinel").fetchone()[0], "daily data must survive")

    def test_external_mode_starts_no_local_backend_or_database(self):
        # The outer live demo is an actual external API for the inner frontend.
        with self.running() as upstream:
            ready = upstream.processes[0][0].args[-1]
            backend_port = Path(ready).read_text(encoding="ascii")
            base = f"http://127.0.0.1:{backend_port}/api/v1"
            with self.running(self.options(demo_session=False, api_base=base)) as frontend:
                self.assertEqual(frontend.processes, [])
                self.assertTrue(self.request(frontend.base, "/risks")["items"])
            self.assertIsNone(upstream.processes[0][0].poll(), "External backend must not be stopped by frontend")
        self.assert_daily_untouched()

    def test_demo_rejects_database_and_external_api_without_side_effects(self):
        for changes, message in [
            ({"database": str(self.directory / "never-created" / "custom.db")}, "--database"),
            ({"api_base": "http://127.0.0.1:1234/api/v1"}, "AGENT_API_BASE"),
        ]:
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, message):
                run_local.configuration(self.options(**changes))
        self.assertFalse((self.directory / "never-created").exists())
        self.assert_daily_untouched()

    def check_command(self, *arguments, env=None):
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "run_local.py"), "--check", *arguments],
                              cwd=ROOT, env=env, capture_output=True, text=True, timeout=15,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)

    def test_check_has_no_filesystem_or_database_side_effects(self):
        before = sorted(str(p.relative_to(self.directory)) for p in self.directory.rglob("*"))
        absent = self.directory / "not-created" / "daily.db"
        for arguments in [("--demo-session",), ("--database", str(absent))]:
            with self.subTest(arguments=arguments):
                result = self.check_command(*arguments)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("No database was created", result.stdout)
        self.assertEqual(before, sorted(str(p.relative_to(self.directory)) for p in self.directory.rglob("*")))
        self.assert_daily_untouched()

    def test_demo_check_rejects_external_api_inherited_from_environment(self):
        environment = dict(os.environ, AGENT_API_BASE="http://127.0.0.1:1234/api/v1")
        result = self.check_command("--demo-session", env=environment)
        self.assertEqual(result.returncode, 2)
        self.assertIn("AGENT_API_BASE", result.stderr)
        self.assert_daily_untouched()

    def test_port_conflict_stops_owned_backend_and_cleans_demo_session(self):
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            args = self.options(port=occupied.getsockname()[1])
            api_base, database = run_local.configuration(args)
            processes = []
            actual_popen = subprocess.Popen

            def popen(*arguments, **keywords):
                process = actual_popen(*arguments, **keywords)
                processes.append((process, Path(keywords["env"]["INVENTORY_AGENT_DB"])))
                return process

            output = io.StringIO()
            with patch.object(run_local.subprocess, "Popen", side_effect=popen), redirect_stdout(output), redirect_stderr(output):
                self.assertEqual(run_local.run(args, api_base, database), 1)
            self.assertIn("Startup failed", output.getvalue())
            self.assertEqual(len(processes), 1)
            process, path = processes[0]
            self.assertIsNotNone(process.poll())
            self.assertFalse(path.parent.exists())
            self.assertNotEqual(occupied.fileno(), -1, "An existing listener is not owned by the launcher")
        self.assert_daily_untouched()

    def test_backend_startup_failure_cleans_its_session(self):
        args = self.options()
        api_base, database = run_local.configuration(args)
        processes = []
        actual_popen = subprocess.Popen

        def popen(*arguments, **keywords):
            process = actual_popen(*arguments, **keywords)
            processes.append((process, Path(keywords["env"]["INVENTORY_AGENT_DB"])))
            return process

        with patch.object(run_local.subprocess, "Popen", side_effect=popen), \
                patch.object(run_local, "wait_for_backend", side_effect=RuntimeError("injected health failure")), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(run_local.run(args, api_base, database), 1)
        self.assertEqual(len(processes), 1)
        self.assertIsNotNone(processes[0][0].poll())
        self.assertFalse(processes[0][1].parent.exists())
        self.assert_daily_untouched()

    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "Windows PowerShell entry point")
    def test_powershell_demo_check_distinguishes_parent_database_from_explicit_database(self):
        command = [shutil.which("powershell"), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                   str(ROOT / "start.ps1"), "-DemoSession", "-Check"]
        for arguments, expected in [(command, 0), (command + ["-Database", str(self.daily)], 1)]:
            with self.subTest(explicit=arguments is not command):
                # PowerShell diagnostics use the Windows locale, independently of Python's UTF-8 mode.
                result = subprocess.run(arguments, cwd=ROOT, capture_output=True, timeout=20,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
                self.assertEqual(result.returncode, expected, {"stdout": result.stdout, "stderr": result.stderr})
        self.assert_daily_untouched()


if __name__ == "__main__":
    unittest.main()

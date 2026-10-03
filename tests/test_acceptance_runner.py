"""Exercise process failures and report retention without running the whole suite."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import run_acceptance as acceptance


class AcceptanceRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="acceptance space ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / "output with spaces"

    def python_step(self, name, code):
        return acceptance.Step(name, (sys.executable, "-c", code))

    def run_checks(self, steps):
        with redirect_stdout(io.StringIO()):
            code, directory = acceptance.run_steps(steps, self.root, self.output)
        return code, directory, json.loads((directory / "summary.json").read_text(encoding="utf-8"))

    def test_failure_is_retained_and_later_check_runs(self):
        code, directory, report = self.run_checks([
            self.python_step("failure", "import sys; print('diagnostic', file=sys.stderr); sys.exit(7)"),
            self.python_step("after-failure", "from pathlib import Path; Path('finished.txt').write_text('done')"),
        ])
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "failed")
        self.assertEqual([step["return_code"] for step in report["steps"]], [7, 0])
        self.assertEqual((self.root / "finished.txt").read_text(), "done")
        self.assertIn("diagnostic", (directory / report["steps"][0]["log"]).read_text(encoding="utf-8"))

    def test_missing_executable_does_not_hide_later_results(self):
        code, _, report = self.run_checks([
            acceptance.Step("missing", (str(self.root / "absent executable"),)),
            self.python_step("next", "print('completed')"),
        ])
        self.assertEqual(code, 1)
        self.assertEqual([step["status"] for step in report["steps"]], ["error", "passed"])
        self.assertIsNone(report["steps"][0]["return_code"])
        self.assertIn("error", report["steps"][0])

    def test_script_and_argument_spaces_unicode_and_shell_characters_are_literal(self):
        script = self.root / "check argument.py"
        script.write_text("import sys\nprint(sys.argv[1])\n", encoding="utf-8")
        argument = "门店 空格 & echo not-a-command"
        code, directory, report = self.run_checks([
            acceptance.Step("literal-argument", (sys.executable, str(script), argument)),
        ])
        self.assertEqual(code, 0)
        self.assertEqual((directory / report["steps"][0]["log"]).read_text(encoding="utf-8").strip(), argument)

    def test_separate_runs_keep_previous_evidence(self):
        steps = [self.python_step("ok", "print('evidence')")]
        _, first, original = self.run_checks(steps)
        code, second, report = self.run_checks(steps)
        self.assertEqual(code, 0)
        self.assertNotEqual(first, second)
        self.assertEqual(json.loads((first / "summary.json").read_text(encoding="utf-8")), original)
        self.assertEqual(report["exit_code"], 0)
        self.assertIsNotNone(report["finished_at"])

    def test_interruption_is_incomplete_and_never_success(self):
        steps = [self.python_step("interrupted", ""), self.python_step("not-started", "")]
        with patch.object(acceptance.subprocess, "run", side_effect=KeyboardInterrupt):
            code, _, report = self.run_checks(steps)
        self.assertEqual(code, 130)
        self.assertEqual(report["status"], "interrupted")
        self.assertEqual([step["status"] for step in report["steps"]], ["interrupted", "not_run"])

    def test_empty_run_is_rejected(self):
        with self.assertRaises(ValueError):
            self.run_checks([])

    def test_main_propagates_failure_with_repository_relative_output(self):
        steps = [self.python_step("failure", "raise SystemExit(3)")]
        with patch.object(acceptance, "ROOT", self.root), patch.object(acceptance, "acceptance_steps", return_value=steps):
            with redirect_stdout(io.StringIO()):
                code = acceptance.main(["--output-dir", "output with spaces"])
        self.assertEqual(code, 1)
        self.assertEqual(len(list(self.output.glob("*/summary.json"))), 1)

    def test_sources_expand_without_shell_and_include_all_existing_checks(self):
        (self.root / "backend" / "nested").mkdir(parents=True)
        (self.root / "backend" / "nested" / "module.py").write_text("")
        (self.root / "tests").mkdir()
        for name in ("one.mjs", "two with spaces.mjs", "test_case.py"):
            (self.root / "tests" / name).write_text("")
        steps = {step.name: step.command for step in acceptance.acceptance_steps(self.root)}
        self.assertIn("backend/nested/module.py", steps["backend-syntax"])
        self.assertEqual(steps["node-tests"], ("node", "--test", "tests/one.mjs", "tests/two with spaces.mjs"))
        self.assertEqual(steps["python-tests"][1:], ("-m", "unittest", "discover", "-s", "tests", "-v"))
        self.assertIn("scripts/reproduce_backend_concurrency.py", steps["backend-concurrency"])
        self.assertIn("--check", steps["sample-data"])
        self.assertEqual(steps["frontend-syntax"], ("node", "--check", "app.js"))

    def test_missing_test_sources_cannot_pass(self):
        with self.assertRaises(ValueError):
            acceptance.acceptance_steps(self.root)


if __name__ == "__main__":
    unittest.main()

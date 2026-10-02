"""Browser acceptance against an isolated demo database; never opens the user's DB.

Run: .venv/Scripts/python -m unittest tests.test_frontend_browser -v
Install browser once: .venv/Scripts/python -m playwright install chromium
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import URLError
from urllib.request import Request, urlopen

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]


class FrontendBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch(headless=True)
        cls.addClassCleanup(cls.browser.close)

    def _start_server(self):
        self.temp = tempfile.TemporaryDirectory(prefix="inventory-browser-tests-")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.server_log = open(Path(self.temp.name) / "server.log", "w+", encoding="utf-8")
        environment = dict(os.environ, INVENTORY_AGENT_DB=str(Path(self.temp.name) / "test.db"), INVENTORY_AGENT_MODE="demo")
        self.server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.api:app", "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=ROOT, env=environment, stdout=self.server_log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.addCleanup(self._stop_server)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.server.poll() is not None:
                self.server_log.seek(0)
                raise RuntimeError(self.server_log.read())
            try:
                health = self.api("/health")
                if Path(health["database"]).resolve() != (Path(self.temp.name) / "test.db").resolve():
                    raise RuntimeError("test server opened an unexpected database")
                break
            except (URLError, TimeoutError):
                time.sleep(0.1)
        else:
            raise RuntimeError("isolated test API did not start")

    def _stop_server(self):
        if os.name == "nt" and self.server.poll() is None:
            # Windows venv python.exe can launch another Python process. Stop
            # only the test-owned process tree so no child keeps DB/log handles.
            subprocess.run(["taskkill", "/PID", str(self.server.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=True)
        elif self.server.poll() is None:
            self.server.terminate()
        try:
            self.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.server.kill()
            self.server.wait(timeout=5)
        self.server_log.close()
        self.temp.cleanup()

    def api(self, path, body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(self.base_url + "/api/v1" + path, data=data, headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=5) as response:
            return json.load(response)

    def setUp(self):
        # A closed page may leave an already-running server request behind.
        # Fresh API processes prevent that request from crossing test boundaries.
        self._start_server()
        artifacts = os.environ.get("FRONTEND_TEST_ARTIFACTS")
        self.artifact_dir = Path(artifacts).resolve() if artifacts and self._testMethodName == "test_transfer_approval_creates_execution_draft_without_external_completion" else None
        options = {"viewport": {"width": 1440, "height": 1000}}
        if self.artifact_dir:
            self.artifact_dir.mkdir(parents=True, exist_ok=True)
            options.update(record_video_dir=str(self.artifact_dir), record_video_size={"width": 1440, "height": 1000})
        self.context = self.browser.new_context(**options)
        self.context.route("https://fonts.googleapis.com/**", lambda route: route.abort())
        self.context.route("https://fonts.gstatic.com/**", lambda route: route.abort())
        self.page = self.context.new_page()
        self.page_errors = []
        self.page.on("pageerror", lambda error: self.page_errors.append(str(error)))
        self.addCleanup(self._close_context)

    def _close_context(self):
        video = self.page.video
        try:
            if self.artifact_dir and not self.page.is_closed():
                self.page.evaluate("window.scrollTo(0, 0)")
                self.page.screenshot(path=str(self.artifact_dir / "demo-flow.png"))
        finally:
            self.context.close()
        if self.artifact_dir and video:
            original = Path(video.path())
            video.save_as(str(self.artifact_dir / "demo-flow.webm"))
            original.unlink(missing_ok=True)

    def demo_frame(self):
        if self.artifact_dir:
            self.page.evaluate("window.scrollTo(0, 0)")
            self.page.wait_for_timeout(900)

    def open(self, route="overview"):
        self.page.goto(self.base_url + "/#" + route)
        self.page.wait_for_load_state("networkidle")

    def navigate(self, route):
        self.page.evaluate("route => { location.hash = route; }", route)
        expect(self.page.locator(f'[data-view="{route}"]')).to_be_visible()
        self.page.wait_for_load_state("networkidle")

    def assert_no_script_errors(self):
        self.assertEqual(self.page_errors, [])

    def test_all_api_failure_shows_error_without_sample_fallback(self):
        self.page.route("**/api/v1/**", lambda route: route.abort())
        self.open("risks")
        content = self.page.locator(".workspace").inner_text()
        self.assertRegex(content, r"失败|不可用|无法|连接")
        self.assertNotIn("钙维生素D软胶囊", content)
        self.assert_no_script_errors()

    def test_empty_risks_remain_empty(self):
        self.page.route("**/api/v1/risks", lambda route: route.fulfill(json={"items": [], "total": 0}))
        self.open("slow-diagnosis")
        content = self.page.locator("#slow-list").inner_text()
        self.assertRegex(content, r"暂无|没有|0 条|空")
        self.assertNotIn("钙维生素D软胶囊", content)
        self.assert_no_script_errors()

    def test_data_templates_and_multiple_imports_report_validation_without_replacing_snapshot(self):
        snapshot = self.api("/data-center")["snapshot_id"]
        self.open("data")
        self.page.locator("#import-kind").select_option("inventory")
        with self.page.expect_download() as downloaded:
            self.page.locator("#import-template").click()
        self.assertTrue(downloaded.value.suggested_filename.endswith(".csv"))
        self.assertIn("inventory_qty", Path(downloaded.value.path()).read_text(encoding="utf-8-sig"))
        self.page.locator("#import-file").set_input_files([
            {"name": "inventory.csv", "mimeType": "text/csv", "buffer": (ROOT / "sample-data/generated/inventory.csv").read_bytes()},
            {"name": "missing-columns.csv", "mimeType": "text/csv", "buffer": b"sku,store\nTEST-SKU,TEST-STORE\n"},
        ])
        expect(self.page.locator("#selected-file-count")).to_have_text("2")
        self.page.locator('#data-import-form button[type="submit"]').click()
        expect(self.page.locator("#import-history")).to_contain_text("inventory.csv")
        expect(self.page.locator("#import-history")).to_contain_text("missing-columns.csv")
        expect(self.page.locator("#import-history")).to_contain_text("仅字段校验通过")
        expect(self.page.locator("#import-history")).to_contain_text("缺少字段")
        data = self.api("/data-center")
        self.assertEqual(data["snapshot_id"], snapshot)
        self.assertEqual({item["filename"]: item["status"] for item in data["imports"]}, {
            "inventory.csv": "validated", "missing-columns.csv": "failed",
        })
        self.assert_no_script_errors()

    def test_rule_mode_and_five_agent_entries_are_available(self):
        self.open()
        self.assertRegex(self.page.locator("body").inner_text(), r"规则模式|规则计算|规则测算")
        for route in ("slow-diagnosis", "transfer", "expiry-rescue", "procurement-brake", "simulation"):
            self.navigate(route)
            self.assertGreater(len(self.page.locator(f'[data-view="{route}"]').inner_text()), 20)
        self.assert_no_script_errors()

    def test_late_detail_response_cannot_replace_current_selection(self):
        self.open("risks")
        old_response = self.api("/risks/1")
        held = []
        self.page.route("**/api/v1/risks/1", lambda route: route.continue_() if held else held.append(route))
        with self.page.expect_request("**/api/v1/risks/1"):
            self.page.locator('[data-risk-id="1"]').click()
        self.page.locator('[data-risk-id="2"]').click()
        expect(self.page.locator("#case-title")).to_contain_text("阿胶块")
        self.assertEqual(len(held), 1)
        held[0].fulfill(json=old_response)
        self.page.wait_for_load_state("networkidle")
        expect(self.page.locator("#case-title")).to_contain_text("阿胶块")
        self.assert_no_script_errors()

    def test_input_invalidates_actions_before_draft_is_saved_and_calculation_waits(self):
        self.open("transfer")
        form = self.page.locator('[data-workbench-form="transfer"]')
        expect(form).to_be_visible()
        self.page.locator('[data-workbench-save="transfer"]').click()
        expect(self.page.locator('[data-workbench-submit="transfer"]')).to_be_enabled()
        held = []
        calculation_requests = []
        self.page.route("**/api/v1/workbenches/transfer/draft", lambda route: held.append(route))
        self.page.on("request", lambda request: calculation_requests.append(request) if request.url.endswith("/transfer/calculate") else None)
        with self.page.expect_request("**/api/v1/workbenches/transfer/draft"):
            form.locator('[name="quantity"]').fill("31")
            form.locator('[name="quantity"]').press("Tab")
        expect(self.page.locator('[data-workbench-save="transfer"]')).to_be_disabled()
        expect(self.page.locator('[data-workbench-submit="transfer"]')).to_be_disabled()
        form.evaluate("form => form.requestSubmit()")
        self.page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        self.assertEqual(calculation_requests, [], "calculation must follow the outstanding draft write")
        self.assertEqual(len(held), 1)
        with self.page.expect_response("**/api/v1/workbenches/transfer/calculate"):
            held[0].continue_()
        expect(self.page.locator('[data-workbench-save="transfer"]')).to_be_enabled()
        result = self.api("/workbenches/transfer")
        self.assertEqual(int(result["input"]["quantity"]), 31)
        self.assertEqual(result["calculation"]["allocation"]["quantity"], 31)
        self.assert_no_script_errors()

    def test_reloaded_dirty_draft_cannot_submit_a_previous_proposal(self):
        self.api("/workbenches/transfer/save", {"input": {}})
        self.api("/workbenches/transfer/draft", {"input": {"quantity": 31}})
        self.open("transfer")
        expect(self.page.locator('[data-workbench-form="transfer"] [name="quantity"]')).to_have_value("31")
        expect(self.page.locator('[data-workbench-save="transfer"]')).to_be_disabled()
        expect(self.page.locator('[data-workbench-submit="transfer"]')).to_be_disabled()
        self.assert_no_script_errors()

    def test_calculation_failure_can_recover_with_the_users_latest_input(self):
        self.open("transfer")
        form = self.page.locator('[data-workbench-form="transfer"]')
        form.locator('[name="quantity"]').fill("31")
        form.locator('[name="quantity"]').press("Tab")
        self.page.wait_for_load_state("networkidle")
        self.page.route("**/api/v1/workbenches/transfer/calculate", lambda route: route.fulfill(status=503, json={"detail": "计算服务暂不可用"}))
        with self.page.expect_response("**/api/v1/workbenches/transfer/calculate"):
            form.locator('button[type="submit"]').click()
        expect(self.page.locator('[data-agent-runtime="transfer"]')).to_contain_text("计算服务暂不可用")
        self.page.unroute("**/api/v1/workbenches/transfer/calculate")
        expect(form).to_be_visible()
        expect(form.locator('[name="quantity"]')).to_have_value("31")
        with self.page.expect_response("**/api/v1/workbenches/transfer/calculate") as response:
            form.locator('button[type="submit"]').click()
        self.assertEqual(response.value.json()["calculation"]["allocation"]["quantity"], 31)
        self.assert_no_script_errors()

    def test_transfer_approval_creates_execution_draft_without_external_completion(self):
        self.open("transfer")
        self.demo_frame()
        self.page.locator('[data-workbench-form="transfer"] button[type="submit"]').click()
        expect(self.page.locator('[data-workbench-save="transfer"]')).to_be_enabled()
        with self.page.expect_response("**/api/v1/workbenches/transfer/save") as saved:
            self.page.locator('[data-workbench-save="transfer"]').click()
        proposal_id = saved.value.json()["proposal"]["id"]
        expect(self.page.locator('[data-workbench-submit="transfer"]')).to_be_enabled()
        self.demo_frame()
        with self.page.expect_response(f"**/api/v1/proposals/{proposal_id}/submit") as submitted:
            self.page.locator('[data-workbench-submit="transfer"]').click()
        self.assertEqual(submitted.value.status, 200)
        self.assertEqual(submitted.value.json()["status"], "pending_approval")
        self.page.wait_for_load_state("networkidle")
        self.navigate("approvals")
        self.demo_frame()
        self.page.locator(f'[data-approve-proposal="{proposal_id}"]').click()
        expect(self.page.locator(f'[data-execute-proposal="{proposal_id}"]')).to_be_visible()
        self.demo_frame()
        self.page.locator(f'[data-execute-proposal="{proposal_id}"]').click()
        self.page.wait_for_load_state("networkidle")
        self.navigate("execution")
        expect(self.page.locator("[data-execution-form]")).to_have_count(1)
        self.demo_frame()
        tasks = self.api("/execution-tasks")["items"]
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["status"], "draft_pending_external_execution")
        self.assertIs(tasks[0]["metadata"]["external_write"], False)
        self.assert_no_script_errors()

    def test_feedback_requires_review_before_invalidating_old_approval(self):
        self.open("risks")
        self.page.locator('[data-risk-id="1"]').click()
        expect(self.page.locator("#case-title")).to_contain_text("钙维生素D软胶囊")
        if not self.page.locator("#create-investigation").is_visible():
            self.page.locator("#agent-toggle").click()
        self.page.locator("#create-investigation").click()
        original = "门店已重新上架，具体滞销原因仍待核查。"
        self.page.locator("#feedback-text").fill(original)
        self.page.locator("#submit-feedback").click()
        expect(self.page.locator("#feedback-draft")).to_be_visible()
        expect(self.page.locator("#feedback-draft")).to_contain_text(original)
        expect(self.page.locator("#confirm-feedback")).to_be_disabled()
        self.assertEqual(self.api("/risks/1")["risk"]["current_fact_version"], 1)
        self.page.locator("#feedback-reviewed").check()
        expect(self.page.locator("#confirm-feedback")).to_be_enabled()
        with self.page.expect_response(re.compile(r"/api/v1/feedback/[^/]+/confirm$")):
            self.page.locator("#confirm-feedback").click()
        risk = self.api("/risks/1")["risk"]
        self.assertEqual(risk["current_fact_version"], 2)
        self.assertEqual(risk["proposal_status"], "needs_replan")
        self.assert_no_script_errors()

    def test_late_feedback_response_cannot_attach_to_another_case(self):
        self.open("risks")
        self.page.locator('[data-risk-id="1"]').click()
        self.page.locator("#create-investigation").click()
        self.page.locator("#feedback-text").fill("第一案件独有反馈，不能串到第二案件。")
        held = []
        self.page.route("**/api/v1/investigations/*/feedback", lambda route: held.append(route))
        with self.page.expect_request("**/api/v1/investigations/*/feedback"):
            self.page.locator("#submit-feedback").click()
        self.page.locator("#modal-close").click()
        self.page.locator('[data-risk-id="2"]').click()
        expect(self.page.locator("#case-title")).to_contain_text("阿胶块")
        self.page.locator("#create-investigation").click()
        expect(self.page.locator("#investigation-title")).to_contain_text("阿胶块")
        self.assertEqual(len(held), 1)
        held[0].continue_()
        self.page.wait_for_load_state("networkidle")
        expect(self.page.locator("#feedback-draft")).to_be_hidden()
        expect(self.page.locator("#confirm-feedback")).to_be_disabled()
        self.assertEqual(self.api("/risks/1")["risk"]["current_fact_version"], 1)
        self.assertEqual(self.api("/risks/2")["risk"]["current_fact_version"], 1)
        self.assert_no_script_errors()

    def test_expiry_and_procurement_use_server_results_then_cash_simulation(self):
        self.open("expiry-rescue")
        for route in ("expiry-rescue", "procurement-brake"):
            self.navigate(route)
            form = self.page.locator(f'[data-workbench-form="{route}"]')
            if route == "expiry-rescue":
                price = form.locator('[name="promo_price"]')
                price.fill("12.50")
                price.press("Tab")
                self.page.wait_for_load_state("networkidle")
                self.assertTrue(price.evaluate("input => input.checkValidity()"))
            with self.page.expect_response(f"**/api/v1/workbenches/{route}/calculate") as response:
                form.locator('button[type="submit"]').click()
            result = response.value.json()
            self.assertTrue(result["calculation"]["valid"])
            expect(self.page.locator(f'[data-workbench-save="{route}"]')).to_be_enabled()
            self.page.locator(f'[data-workbench-save="{route}"]').click()
            expect(self.page.locator(f'[data-workbench-submit="{route}"]')).to_be_enabled()
        self.navigate("simulation")
        self.page.locator("#simulation-target").fill("1")
        with self.page.expect_response("**/api/v1/scenarios/simulate") as response:
            self.page.locator('#simulation-form button[type="submit"]').click()
        result = response.value.json()
        self.assertIn("gap", result)
        self.assertIn("bundle_validation", result)
        expect(self.page.locator("#simulation-output")).not_to_have_text(re.compile(r"^输入目标后"))
        self.assert_no_script_errors()

    def test_simulation_cannot_keep_results_after_target_or_region_changes(self):
        self.api("/workbenches/procurement-brake/calculate", {"input": {}})
        self.open("simulation")
        for change in (lambda: self.page.locator("#simulation-target").fill("2"),
                       lambda: self.page.locator("#region-select").select_option("west-lake")):
            with self.page.expect_response("**/api/v1/scenarios/simulate"):
                self.page.locator('#simulation-form button[type="submit"]').click()
            expect(self.page.locator("#simulation-status")).not_to_have_text("待重新计算")
            change()
            expect(self.page.locator("#simulation-status")).to_have_text("待重新计算")
            expect(self.page.locator("#simulation-output")).to_contain_text("重新")
        self.assert_no_script_errors()

    def test_demo_reset_requires_confirmation_and_rebuilds_server_state(self):
        self.api("/risks/1/investigations", {})
        self.open("data")
        reset = self.page.locator("#demo-reset")
        expect(reset).to_be_enabled()
        held = []
        self.page.route("**/api/v1/risks/1", lambda route: route.continue_() if held else held.append(route))
        with self.page.expect_request("**/api/v1/risks/1"):
            self.page.locator("#refresh-data").click()
        # Data-center has already loaded; the outstanding detail read must still
        # prevent reset from deleting rows while the server is reading them.
        expect(reset).to_be_disabled()
        self.assertEqual(len(held), 1)
        held[0].continue_()
        self.page.unroute("**/api/v1/risks/1")
        self.page.wait_for_load_state("networkidle")
        expect(reset).to_be_enabled()
        self.page.once("dialog", lambda dialog: dialog.dismiss())
        reset.click()
        self.assertEqual(self.api("/risks/1")["risk"]["investigation_status"], "pending")
        self.page.once("dialog", lambda dialog: dialog.accept())
        with self.page.expect_response("**/api/v1/demo/reset"):
            reset.click()
        self.page.wait_for_load_state("networkidle")
        self.assertNotEqual(self.api("/risks/1")["risk"]["investigation_status"], "pending")
        self.assert_no_script_errors()

    def test_real_mode_does_not_offer_demo_reset(self):
        data_center = self.api("/data-center")
        data_center["mode"] = "real_inventory_snapshot"
        self.page.route("**/api/v1/health", lambda route: route.fulfill(json={"status": "ok", "sample_data": False}))
        self.page.route("**/api/v1/data-center", lambda route: route.fulfill(json=data_center))
        self.open("data")
        reset = self.page.locator("#demo-reset")
        self.assertTrue(reset.count() == 0 or not reset.is_visible() or reset.is_disabled())
        self.assert_no_script_errors()

    def test_real_mode_without_imported_snapshot_cannot_reset(self):
        # The current API returns sample_replay from data-center until a real
        # snapshot exists. The health mode must still prohibit destructive reset.
        self.page.route("**/api/v1/health", lambda route: route.fulfill(json={"status": "ok", "sample_data": False}))
        self.open("data")
        reset = self.page.locator("#demo-reset")
        self.assertTrue(reset.count() == 0 or not reset.is_visible() or reset.is_disabled())
        self.assert_no_script_errors()

    def test_mobile_views_do_not_overflow_document(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.open()
        for route in ("overview", "slow-diagnosis", "transfer", "expiry-rescue", "procurement-brake", "simulation", "data"):
            self.navigate(route)
            sizes = self.page.evaluate("({width: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth})")
            self.assertLessEqual(sizes["scroll"], sizes["width"] + 1, route)
        self.assert_no_script_errors()


if __name__ == "__main__":
    unittest.main()

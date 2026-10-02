"""Browser acceptance with v0.3 fixtures, never a live Agent/model or legacy DB."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import threading
import unittest
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright
from scripts.serve_frontend import serve

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "v03"
AGENTS = ["slow_moving", "store_transfer", "near_expiry", "procurement_brake", "cashflow_simulation"]
FIXTURE_BY_AGENT = dict(zip(AGENTS, ["succeeded", "store_transfer", "near_expiry", "procurement_brake", "awaiting_confirmation"]))


class FrontendBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = serve(ROOT, port=0)
        cls.server.RequestHandlerClass.log_message = lambda handler, *args: None
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.addClassCleanup(cls._stop_server)
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch(headless=True)
        cls.addClassCleanup(cls.browser.close)

    @classmethod
    def _stop_server(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=5)

    def setUp(self):
        self.calls, self.pending, self.page_errors, self.requests_seen = [], [], [], []
        self.transport = None
        self.run_response = self.response_for
        self.decision_response = self.decision_for
        artifacts = os.environ.get("FRONTEND_TEST_ARTIFACTS")
        self.artifact_dir = Path(artifacts).resolve() if artifacts and self._testMethodName == "test_contract_preview_and_simulation_decision_flow" else None
        options = {"viewport": {"width": 1440, "height": 1000}}
        if self.artifact_dir:
            self.artifact_dir.mkdir(parents=True, exist_ok=True)
            options.update(record_video_dir=str(self.artifact_dir), record_video_size={"width": 1440, "height": 1000})
        self.context = self.browser.new_context(**options)
        self.context.add_init_script("""document.addEventListener('DOMContentLoaded', () => {
          const banner = document.createElement('div');
          banner.dataset.testFixtureBanner = '';
          banner.textContent = '契约夹具演示 · 非真实后端 / 非模型调用';
          banner.style.cssText = 'position:fixed;bottom:0;left:0;right:0;padding:6px 12px;background:#152b25;color:white;font:12px sans-serif;text-align:center;z-index:9999;pointer-events:none';
          document.body.append(banner);
        });""")
        self.page = self.context.new_page()
        self.page.set_default_timeout(5000)
        self.page.on("pageerror", lambda error: self.page_errors.append(str(error)))
        self.page.on("request", lambda request: self.requests_seen.append(request.url))
        self.page.route("**/api/v1/**", self.route_api)
        self.addCleanup(self.close_context)

    def close_context(self):
        video = self.page.video
        try:
            for route, _call in self.pending:
                route.abort()
            self.pending.clear()
            if self.artifact_dir and not self.page.is_closed():
                self.page.evaluate("document.activeElement?.blur(); window.scrollTo(0, 0)")
                self.page.screenshot(path=str(self.artifact_dir / "contract-flow.png"), full_page=True)
        finally:
            self.context.close()
        if self.artifact_dir and video:
            original = Path(video.path())
            video.save_as(str(self.artifact_dir / "contract-flow.webm"))
            original.unlink(missing_ok=True)

    def tearDown(self):
        self.assertEqual(self.page_errors, [], "unhandled browser errors")
        for call in self.calls:
            self.assertEqual(call["method"], "POST")
            self.assertRegex(call["path"], r"^/api/v1/agent-runs(?:/[^/]+/decisions)?$")
        self.assertFalse(any(re.search(r"/(?:reference|fixtures)/|expected[_-]results", url) for url in self.requests_seen))

    def fixture(self, name):
        return json.loads((FIXTURES / f"response-{name}.json").read_text(encoding="utf-8"))

    def response_for(self, request, name=None):
        if name is None:
            name = "partial" if request["agent_type"] == "cashflow_simulation" and request["params"].get("operation") == "simulate" else FIXTURE_BY_AGENT[request["agent_type"]]
        response = self.fixture(name)
        response.update(request_id=request["request_id"], agent_type=request["agent_type"], session_id=request.get("session_id"),
                        data_version=request["data_version"], policy_version=request.get("policy_version", "snack-policy-v1"),
                        run_id=f"run-{request['agent_type']}-{len(self.calls)}")
        return response

    @staticmethod
    def decision_for(call):
        return {**call["body"], "run_id": call["path"].split("/")[-2], "decision_status": "recorded", "execution_mode": "simulation"}

    def route_api(self, route):
        request = route.request
        call = {"method": request.method, "path": urlparse(request.url).path, "body": request.post_data_json}
        self.calls.append(call)
        if self.transport:
            self.transport(route, call)
            return
        if call["path"] == "/api/v1/agent-runs":
            response = self.run_response(call["body"])
        elif re.fullmatch(r"/api/v1/agent-runs/[^/]+/decisions", call["path"]):
            response = self.decision_response(call)
        else:
            route.fulfill(status=404, json={"detail": "unexpected endpoint"})
            return
        if response is None:
            self.pending.append((route, call))
        else:
            route.fulfill(json=response)

    def release(self, index=0):
        route, call = self.pending.pop(index)
        response = self.response_for(call["body"]) if call["path"].endswith("agent-runs") else self.decision_for(call)
        route.fulfill(json=response)

    def open(self, agent="slow_moving"):
        self.page.goto(f"{self.base_url}/#{agent}")
        expect(self.page.locator("#agent-form button[type=submit]")).to_be_visible()

    def navigate(self, agent):
        self.page.evaluate("route => { location.hash = route; }", agent)
        expect(self.page.locator(f'#app-nav [data-agent="{agent}"]')).to_have_attribute("aria-current", "page")

    def submit(self):
        user_input = self.page.locator('#agent-form [name="user_input"]')
        if user_input.get_attribute("required") is not None and not user_input.input_value():
            self.page.locator('[data-action="example"]').click()
        self.page.locator("#agent-form button[type=submit]").click()

    def frame(self):
        if self.artifact_dir:
            self.page.wait_for_timeout(800)

    def test_five_agents_use_one_contract_and_integer_fen(self):
        self.open()
        for agent in AGENTS:
            with self.subTest(agent=agent):
                self.navigate(agent)
                self.submit()
                if agent == "cashflow_simulation":
                    expect(self.page.locator(".scenario-card")).to_be_visible()
                    expect(self.page.locator(".metric")).to_have_count(0)
                else:
                    expect(self.page.locator(".result-card")).to_have_count(1)
                request = self.calls[-1]["body"]
                self.assertEqual(request["agent_type"], agent)
                self.assertRegex(request["request_id"], r"^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$")
                self.assertEqual(request["scope"]["as_of"], "2026-10-02")
                if agent == "procurement_brake":
                    self.assertEqual(request["params"]["horizon_days"], 14)
        self.navigate("slow_moving")
        expect(self.page.locator(".metric-grid")).to_contain_text("¥220.00")
        self.assertEqual(len(self.calls), 5)

    def test_six_business_states_render_without_invented_success(self):
        states = {"succeeded": "分析完成", "partial": "部分结果", "no_data": "当前范围没有数据",
                  "needs_input": "需要补充或确认", "failed": "本次运行失败", "awaiting_confirmation": "情景待确认"}
        for status, label in states.items():
            with self.subTest(status=status):
                self.run_response = lambda request, name=status: self.response_for(request, name)
                self.open("cashflow_simulation" if status == "awaiting_confirmation" else "slow_moving")
                self.submit()
                expect(self.page.locator("#run-status")).to_contain_text(label)
                if status in {"no_data", "needs_input", "failed", "awaiting_confirmation"}:
                    expect(self.page.locator(".metric")).to_have_count(0)
                if status == "needs_input":
                    expect(self.page.locator("#run-output")).to_contain_text("请补充或确认")
                if status == "failed":
                    expect(self.page.locator("#run-status")).to_contain_text("AI_TIMEOUT")

    def test_unconfigured_preview_server_reports_service_unavailable(self):
        self.page.unroute("**/api/v1/**", self.route_api)
        self.open()
        self.submit()
        expect(self.page.locator("#run-status")).to_contain_text("请求未取得可用结果")
        expect(self.page.locator(".result-card")).to_have_count(0)
        self.assertEqual(len([url for url in self.requests_seen if "/api/v1/" in url]), 1)

    def test_missing_endpoint_does_not_fall_back_to_legacy_or_sample_results(self):
        self.transport = lambda route, call: route.fulfill(status=404, json={"detail": "Not Found"})
        self.open()
        self.submit()
        expect(self.page.locator("#run-status")).to_contain_text("Not Found")
        expect(self.page.locator(".metric")).to_have_count(0)
        self.assertEqual(len(self.calls), 1)

    def test_network_failure_does_not_generate_analysis(self):
        self.transport = lambda route, call: route.abort("internetdisconnected")
        self.open()
        self.submit()
        expect(self.page.locator("#run-status")).to_contain_text("无法连接服务")
        expect(self.page.locator("#run-status")).to_contain_text("服务端可能仍在处理")
        expect(self.page.locator(".metric")).to_have_count(0)
        self.assertEqual(len(self.calls), 1)

    def test_ai_http_errors_and_invalid_json_are_visible(self):
        for transport, expected in [
            (lambda route, call: route.fulfill(status=503, json={"error": {"code": "AI_UNAVAILABLE", "message": "模型服务暂不可用", "retryable": True, "field_errors": []}}), "AI_UNAVAILABLE"),
            (lambda route, call: route.fulfill(status=200, body="<html>gateway</html>", content_type="text/html"), "invalid_json"),
        ]:
            with self.subTest(expected=expected):
                self.transport = transport
                self.open()
                self.submit()
                expect(self.page.locator("#run-status")).to_contain_text(expected)
                expect(self.page.locator(".metric")).to_have_count(0)

    def test_invalid_money_and_foreign_response_are_rejected(self):
        for field in ["money", "identity"]:
            with self.subTest(field=field):
                def response(request):
                    value = self.response_for(request)
                    if field == "money": value["items"][0]["metrics"][0]["value"] = 22000.5
                    else: value["request_id"] = "foreign-request"
                    return value
                self.run_response = response
                self.open()
                self.submit()
                expect(self.page.locator("#run-status")).to_contain_text("CONTRACT_INVALID")
                expect(self.page.locator(".metric")).to_have_count(0)

    def test_contract_preview_and_simulation_decision_flow(self):
        self.open("cashflow_simulation")
        self.submit()
        expect(self.page.locator(".scenario-card")).to_be_visible()
        expect(self.page.locator(".metric")).to_have_count(0)
        expect(self.page.locator("[data-decision]")).to_have_count(0)
        first = self.calls[0]["body"]
        preview = self.fixture("awaiting_confirmation")["scenario_preview"]
        self.assertEqual(first["params"]["operation"], "preview")
        self.assertNotIn("confirmed", first["params"])
        self.frame()
        self.page.locator('[data-action="simulate"]').click()
        expect(self.page.locator(".result-card")).to_have_count(1)
        expect(self.page.locator("#run-output")).to_contain_text("¥52.80")
        self.assertEqual(len(self.calls), 2, "simulation does not record a decision")
        simulation = self.calls[1]["body"]
        self.assertEqual(simulation["session_id"], first["session_id"])
        self.assertEqual(simulation["params"]["scenario_id"], preview["scenario_id"])
        self.assertEqual(simulation["params"]["adjustments"], preview["adjustments"])
        self.assertIs(simulation["params"]["confirmed"], True)
        self.frame()
        self.page.locator("[data-decision-note]").fill("契约夹具演示：核对后模拟确认")
        self.page.locator('[data-decision="approve"]').click()
        expect(self.page.locator(".decision-status")).to_contain_text("已记录：模拟确认")
        expect(self.page.locator(".decision-status")).to_contain_text("未修改库存")
        self.assertEqual(len(self.calls), 3)
        self.assertTrue(self.calls[2]["path"].endswith("/decisions"))
        self.frame()

    def test_preview_changes_invalidate_confirmation_and_version_changes_reset_session(self):
        self.open("cashflow_simulation")
        self.submit()
        expect(self.page.locator(".scenario-card")).to_be_visible()
        first_session = self.calls[-1]["body"]["session_id"]
        self.page.locator('[name="user_input"]').fill("改为减少 7 袋，请重新整理")
        expect(self.page.locator('[data-action="simulate"]')).to_have_count(0)
        expect(self.page.locator("#run-status")).to_contain_text("输入已改变")
        self.page.locator('[name="as_of"]').fill("2026-10-03")
        self.submit()
        expect(self.page.locator(".scenario-card")).to_be_visible()
        self.assertNotEqual(self.calls[-1]["body"]["session_id"], first_session)
        self.assertTrue(all(call["body"]["params"]["operation"] == "preview" for call in self.calls))

    def test_revise_scenario_returns_to_input_without_computing(self):
        self.open("cashflow_simulation")
        self.submit()
        expect(self.page.locator(".scenario-card")).to_be_visible()
        self.page.locator('[data-action="revise"]').click()
        expect(self.page.locator(".scenario-card")).to_have_count(0)
        expect(self.page.locator('[name="user_input"]')).to_be_focused()
        self.assertEqual(len(self.calls), 1)

    def test_approve_and_reject_are_recorded_once_even_on_double_click(self):
        self.decision_response = lambda call: None
        for decision in ["approve", "reject"]:
            with self.subTest(decision=decision):
                self.open()
                self.submit()
                expect(self.page.locator(".result-card")).to_have_count(1)
                before = len(self.calls)
                self.page.evaluate("decision => { const button = document.querySelector(`[data-decision=${decision}]`); button.click(); button.click(); }", decision)
                expect(self.page.locator(".decision-status")).to_contain_text("正在记录")
                expect(self.page.locator('[data-decision="approve"]')).to_be_disabled()
                expect(self.page.locator('[data-decision="reject"]')).to_be_disabled()
                self.assertEqual(len(self.calls), before + 1)
                self.release()
                expect(self.page.locator(".decision-status")).to_contain_text("已记录")
                expect(self.page.locator('[data-decision="approve"]')).to_be_disabled()

    def test_decision_with_real_execution_mode_is_never_presented_as_confirmed(self):
        self.decision_response = lambda call: {**self.decision_for(call), "execution_mode": "real"}
        self.open()
        self.submit()
        expect(self.page.locator(".result-card")).to_have_count(1)
        self.page.locator('[data-decision="approve"]').click()
        expect(self.page.locator(".decision-status")).to_contain_text("CONTRACT_INVALID")
        expect(self.page.locator(".decision-status")).not_to_contain_text("已记录")

    def test_unknown_decision_outcome_requires_acknowledgement_before_resubmission(self):
        def uncertain_transport(route, call):
            if call["path"].endswith("/decisions"):
                route.abort("internetdisconnected")
                self.transport = None
            else:
                route.fulfill(json=self.response_for(call["body"]))
        self.transport = uncertain_transport
        self.open()
        self.submit()
        expect(self.page.locator(".result-card")).to_have_count(1)
        self.page.locator('[data-decision="approve"]').click()
        expect(self.page.locator(".decision-status")).to_contain_text("服务端可能仍在处理")
        count = len(self.calls)
        self.page.once("dialog", lambda dialog: dialog.dismiss())
        self.page.locator('[data-decision="approve"]').click()
        self.assertEqual(len(self.calls), count)
        self.page.once("dialog", lambda dialog: dialog.accept())
        self.page.locator('[data-decision="approve"]').click()
        expect(self.page.locator(".decision-status")).to_contain_text("已记录：模拟确认")
        self.assertEqual(len(self.calls), count + 1)

    def test_late_response_stays_with_its_agent_after_navigation(self):
        self.run_response = lambda request: None if request["agent_type"] == "slow_moving" else self.response_for(request)
        self.open()
        self.submit()
        expect(self.page.locator("#run-status")).to_contain_text("请求处理中")
        expect(self.page.locator('[name="as_of"]')).to_be_disabled()
        self.navigate("near_expiry")
        self.submit()
        expect(self.page.locator(".result-card")).to_have_count(1)
        before = self.page.locator("#run-output").inner_text()
        self.release()
        expect(self.page.locator("#page-title")).to_have_text("近效期分析")
        expect(self.page.locator("#run-output")).to_have_text(before, use_inner_text=True)
        self.navigate("slow_moving")
        expect(self.page.locator(".metric-grid")).to_contain_text("¥220.00")

    def test_late_decision_response_cannot_replace_another_agent_output(self):
        self.decision_response = lambda call: None
        self.open()
        self.submit()
        expect(self.page.locator(".result-card")).to_have_count(1)
        self.page.locator('[data-decision="approve"]').click()
        expect(self.page.locator(".decision-status")).to_contain_text("正在记录")
        self.navigate("near_expiry")
        self.submit()
        expect(self.page.locator(".result-card")).to_have_count(1)
        before = self.page.locator("#run-output").inner_text()
        self.release()
        expect(self.page.locator("#run-output")).to_have_text(before, use_inner_text=True)
        self.navigate("slow_moving")
        expect(self.page.locator(".decision-status")).to_contain_text("已记录：模拟确认")

    def test_cancel_waiting_reports_unknown_outcome_without_retry(self):
        self.run_response = lambda request: None
        self.open()
        self.submit()
        expect(self.page.locator('[data-action="cancel"]')).to_be_visible()
        self.page.locator('[data-action="cancel"]').click()
        expect(self.page.locator("#run-status")).to_contain_text("请求已取消")
        expect(self.page.locator("#run-status")).to_contain_text("服务端可能仍在处理")
        expect(self.page.locator("#agent-form button[type=submit]")).to_be_enabled()
        expect(self.page.locator(".metric")).to_have_count(0)
        self.assertEqual(len(self.calls), 1)

    def test_timeout_reports_unknown_outcome_without_automatic_retry(self):
        self.run_response = lambda request: None
        self.open()
        self.page.clock.install()
        self.submit()
        expect(self.page.locator("#run-status")).to_contain_text("请求处理中")
        self.page.clock.fast_forward(60001)
        expect(self.page.locator("#run-status")).to_contain_text("请求超时")
        expect(self.page.locator("#run-status")).to_contain_text("服务端可能仍在处理")
        self.assertEqual(len(self.calls), 1)

    def test_mobile_navigation_long_evidence_and_series_do_not_overflow(self):
        def long_response(request):
            value = self.response_for(request)
            value["warnings"].append({"code": "FIXTURE_ONLY", "message": "长文本验证：" + "LONG_RECORD_ID_" * 30})
            for item in value["items"]:
                item["entity"]["sku_name"] = "很长的合成商品标识" * 20
                old_id = item["evidence"][0]["record_id"]
                new_id = "RECORD_" * 45
                item["evidence"][0]["record_id"] = new_id
                for recommendation in item["recommendations"]:
                    recommendation["evidence_ids"] = [new_id if record == old_id else record for record in recommendation["evidence_ids"]]
                item["details"]["inventory_capital_series"] = [{"date": "2026-10-02", "baseline_capital_fen": 22000, "scenario_capital_fen": 22000}]
            return value
        self.run_response = long_response
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.open()
        for agent in AGENTS:
            with self.subTest(agent=agent):
                self.page.locator("#nav-toggle").click()
                self.page.locator(f'#app-nav [data-agent="{agent}"]').click()
                expect(self.page.locator(f'#app-nav [data-agent="{agent}"]')).to_have_attribute("aria-current", "page")
                self.submit()
                if agent == "cashflow_simulation": expect(self.page.locator(".scenario-card")).to_be_visible()
                else: expect(self.page.locator(".result-card")).to_have_count(1)
                for details in self.page.locator("#run-output details").all():
                    details.evaluate("node => { node.open = true; }")
                widths = self.page.evaluate("({viewport:innerWidth,document:document.documentElement.scrollWidth})")
                self.assertLessEqual(widths["document"], widths["viewport"], f"{agent}: {widths}")
        self.page.locator("#nav-toggle").click()
        self.page.locator('#app-nav [data-page="data"]').click()
        expect(self.page.locator("#data-page")).to_be_visible()
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), 390)

    def test_data_download_is_input_file_without_import_or_reset(self):
        self.open()
        self.page.locator('#app-nav [data-page="data"]').click()
        expect(self.page.locator("#data-content")).to_contain_text("snack-demo-v1")
        with self.page.expect_download() as download:
            self.page.locator('a[download][href$="stores.csv"]').click()
        contents = Path(download.value.path()).read_text(encoding="utf-8-sig")
        self.assertIn("store_id,store_name,region_id,status", contents)
        self.assertIn("STORE-HZ-001", contents)
        self.assertEqual(self.calls, [])

    def test_mobile_navigation_closes_on_backdrop_escape_and_current_page(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.open()
        self.page.locator("#nav-toggle").click()
        expect(self.page.locator("#nav-backdrop")).to_be_visible()
        self.page.locator("#nav-backdrop").click(position={"x": 380, "y": 30})
        expect(self.page.locator("#nav-backdrop")).to_be_hidden()
        self.page.locator("#nav-toggle").click()
        self.page.keyboard.press("Escape")
        expect(self.page.locator("#nav-backdrop")).to_be_hidden()
        self.page.locator("#nav-toggle").click()
        self.page.locator('#app-nav [data-agent="slow_moving"]').click()
        expect(self.page.locator("#nav-backdrop")).to_be_hidden()
        expect(self.page.locator("#nav-toggle")).to_have_attribute("aria-expanded", "false")
        self.submit()
        expect(self.page.locator(".result-card")).to_have_count(1)

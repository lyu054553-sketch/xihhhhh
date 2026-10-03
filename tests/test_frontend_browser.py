"""Browser and HTTP acceptance against the merged v1.2 backend on a temporary DB.

No API responses are replaced by browser fixtures. The model/ERP are not called:
this suite verifies Wei's actual deterministic rules and persisted workflow.
"""
from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from playwright.sync_api import expect, sync_playwright
from scripts.serve_frontend import serve

ROOT = Path(__file__).resolve().parents[1]
BACKEND_RUNNER = r"""
import json, os, pathlib, sys, threading
import uvicorn
from backend import api
config = uvicorn.Config(api.app, host='127.0.0.1', port=0, log_level='error', lifespan='off')
server = uvicorn.Server(config)
sock = config.bind_socket()
def stop_on_input():
    sys.stdin.readline()
    server.should_exit = True
threading.Thread(target=stop_on_input, daemon=True).start()
pathlib.Path(os.environ['TEST_READY_FILE']).write_text(json.dumps({'port':sock.getsockname()[1]}))
try:
    server.run(sockets=[sock])
finally:
    api.store.close()
    sock.close()
"""


class FrontendBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='inventory-v12-browser-')
        cls.addClassCleanup(cls.temporary.cleanup)
        temporary = Path(cls.temporary.name)
        cls.ready_file = temporary / 'ready.json'
        cls.backend_log = (temporary / 'backend.log').open('w', encoding='utf-8')
        cls.addClassCleanup(cls.backend_log.close)
        environment = dict(os.environ, INVENTORY_AGENT_DB=str(temporary / 'browser.db'),
                           INVENTORY_AGENT_MODE='demo', TEST_READY_FILE=str(cls.ready_file),
                           PYTHONIOENCODING='utf-8')
        cls.backend = subprocess.Popen([sys.executable, '-c', BACKEND_RUNNER], cwd=ROOT, env=environment,
                                       stdin=subprocess.PIPE, stdout=cls.backend_log, stderr=subprocess.STDOUT,
                                       text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        cls.addClassCleanup(cls._stop_backend)
        deadline = time.monotonic() + 15
        while not cls.ready_file.exists():
            if cls.backend.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('Isolated v1.2 backend did not start; inspect its temporary log')
            time.sleep(.05)
        cls.backend_url = 'http://127.0.0.1:' + str(json.loads(cls.ready_file.read_text())['port'])
        while True:
            try:
                cls.http(cls.backend_url + '/openapi.json')
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(.05)
        cls.server = serve(ROOT, api_base=cls.backend_url + '/api/v1', port=0)
        cls.server.RequestHandlerClass.log_message = lambda handler, *args: None
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.addClassCleanup(cls._stop_server)
        cls.base_url = f'http://127.0.0.1:{cls.server.server_port}'
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch(headless=True)
        cls.addClassCleanup(cls.browser.close)

    @staticmethod
    def http(url, method='GET', body=None, headers=None):
        headers = dict(headers or {})
        payload = None
        if body is not None:
            payload = json.dumps(body).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        request = Request(url, data=payload, headers=headers, method=method)
        try:
            response = urlopen(request, timeout=10)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.loads(response.read())

    @classmethod
    def _stop_backend(cls):
        if cls.backend.poll() is None:
            try:
                cls.backend.stdin.write('stop\n')
                cls.backend.stdin.flush()
                cls.backend.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                cls.backend.terminate()
                cls.backend.wait(timeout=5)
        cls.backend.stdin.close()

    @classmethod
    def _stop_server(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=5)

    def setUp(self):
        status, _ = self.http(self.backend_url + '/api/v1/demo/reset', 'POST', {})
        self.assertEqual(status, 200)
        self.api_calls, self.page_errors = [], []
        self.workflow_completed = False
        artifacts = os.environ.get('FRONTEND_TEST_ARTIFACTS')
        self.artifact_dir = Path(artifacts).resolve() if artifacts and self._testMethodName == 'test_live_transfer_workflow' else None
        options = {'viewport': {'width': 1440, 'height': 1000}}
        if self.artifact_dir:
            self.artifact_dir.mkdir(parents=True, exist_ok=True)
            options.update(record_video_dir=str(self.artifact_dir), record_video_size=options['viewport'])
        self.context = self.browser.new_context(**options)
        self.page = self.context.new_page()
        self.page.set_default_timeout(6000)
        self.page.on('pageerror', lambda error: self.page_errors.append(str(error)))
        self.page.on('request', lambda request: self.api_calls.append(request) if '/api/v1/' in request.url else None)
        self.addCleanup(self.close_context)

    def close_context(self):
        video = self.page.video
        artifact_name = 'live-flow' if self.workflow_completed else 'failed-live-flow'
        if self.artifact_dir and not self.page.is_closed():
            self.page.screenshot(path=str(self.artifact_dir / f'{artifact_name}.png'), full_page=True)
        self.context.close()
        if self.artifact_dir and video:
            original = Path(video.path())
            video.save_as(str(self.artifact_dir / f'{artifact_name}.webm'))
            original.unlink(missing_ok=True)

    def tearDown(self):
        self.assertEqual(self.page_errors, [], 'unhandled browser errors')
        self.assertFalse(any('/agent-runs' in call.url for call in self.api_calls))

    def open(self, route='overview'):
        self.page.goto(f'{self.base_url}/#{route}')
        expect(self.page.locator('#page-content')).to_be_visible()

    def posts_to(self, suffix):
        return [request for request in self.api_calls if request.method == 'POST' and urlparse(request.url).path.endswith(suffix)]

    def save_feedback(self, text):
        form = self.page.locator('#feedback-form')
        form.locator('[name="raw_text"]').fill(text)
        with self.page.expect_response(lambda response: response.url.endswith('/feedback')) as event:
            form.locator('button').click()
        feedback = event.value.json()
        expect(self.page.locator('#feedback-confirm-form [name="feedback_id"]')).to_have_value(feedback['id'])
        return feedback

    def frame(self):
        if self.artifact_dir:
            self.page.wait_for_timeout(700)

    def test_live_transfer_workflow(self):
        self.open('transfer')
        expect(self.page.locator('#calculation-result')).to_be_visible()
        self.frame()
        self.page.locator('#workbench-form [name="quantity"]').fill('41')
        expect(self.page.locator('[data-action="save"]')).to_be_disabled()
        with self.page.expect_response(lambda response: '/workbenches/transfer/calculate' in response.url) as event:
            self.page.locator('[data-action="calculate"]').click()
        self.assertTrue(event.value.json()['calculation']['valid'])
        expect(self.page.locator('#calculation-result')).to_contain_text('3,280.00')
        self.frame()
        with self.page.expect_response(lambda response: '/workbenches/transfer/save' in response.url) as event:
            self.page.locator('[data-action="save"]').click()
        proposal = event.value.json()['proposal']
        proposal_id = proposal['id']
        self.assertEqual(proposal['status'], 'draft')
        self.frame()
        with self.page.expect_response(lambda response: response.url.endswith('/submit')) as event:
            self.page.locator('[data-proposal-action="submit"]').click()
        self.assertEqual(event.value.json()['status'], 'pending_approval')
        self.page.locator('#app-nav a[href="#today"]').click()
        approve = self.page.locator(f'[data-proposal-action="approve"][data-id="{proposal_id}"]')
        expect(approve).to_be_visible()
        self.frame()
        with self.page.expect_response(lambda response: response.url.endswith('/approve')) as event:
            approve.click()
        self.assertEqual(event.value.json()['status'], 'approved')
        self.frame()
        with self.page.expect_response(lambda response: response.url.endswith('/execute')) as event:
            self.page.locator(f'[data-proposal-action="execute"][data-id="{proposal_id}"]').click()
        task = event.value.json()
        self.assertEqual(task['status'], 'draft_pending_external_execution')
        self.frame()
        task_form = self.page.locator(f'form[data-task-id="{task["id"]}"]')
        task_form.locator('[name="status"]').select_option('completed')
        task_form.locator('[name="receipt_ref"]').fill('SYNTHETIC-MANUAL-RECEIPT-001')
        with self.page.expect_response(lambda response: response.url.endswith('/status')) as event:
            task_form.locator('button').click()
        self.assertEqual(event.value.json()['status'], 'completed')
        expect(self.page.locator(f'article[data-task-id="{task["id"]}"]')).to_contain_text('人工记录已完成')
        expect(self.page.locator('#page-content')).to_contain_text('未向外部 ERP 写入')
        self.frame()
        for action in ('approve', 'execute'):
            requests = self.posts_to('/' + action)
            self.assertEqual(len(requests), 1)
            self.assertTrue(requests[0].header_value('Idempotency-Key'))
        self.workflow_completed = True

    def test_expiry_and_procurement_workbenches_use_live_calculations(self):
        for route in ('expiry-rescue', 'procurement-brake'):
            with self.subTest(route=route):
                self.open(route)
                expect(self.page.locator('#workbench-form')).to_be_visible()
                with self.page.expect_response(lambda response: response.url.endswith(f'/{route}/calculate')) as event:
                    self.page.locator('[data-action="calculate"]').click()
                self.assertTrue(event.value.json()['calculation']['valid'])
                expect(self.page.locator('#calculation-result')).to_contain_text('工具计算结果')

    def test_selecting_risks_opens_the_matching_workbench_and_selected_product(self):
        self.open('slow_moving')
        with self.page.expect_response(lambda response: response.url.endswith('/risks/3')):
            self.page.locator('#risk-form [name="risk_id"]').select_option('3')
        expect(self.page.locator('#page-content')).to_contain_text('纯牛奶整箱')
        entry = self.page.locator('[data-action="open-workbench"]')
        expect(entry).to_have_count(1)
        expect(entry).to_have_attribute('data-module', 'expiry-rescue')
        entry.click()
        expect(self.page.locator('#workbench-form [name="risk_id"]')).to_have_value('3')
        with self.page.expect_response(lambda response: '/workbenches/expiry-rescue?risk_id=6' in response.url):
            self.page.locator('#workbench-form [name="risk_id"]').select_option('6')
        expect(self.page.locator('#workbench-form [name="risk_id"]')).to_have_value('6')
        expect(self.page.locator('#page-content')).to_contain_text('海盐薯片分享装')
        with self.page.expect_response(lambda response: response.url.endswith('/expiry-rescue/calculate')) as event:
            self.page.locator('[data-action="calculate"]').click()
        self.assertEqual(event.value.json()['input']['risk_id'], 6)
        self.assertTrue(event.value.json()['calculation']['valid'])

    def test_feedback_requires_explicit_human_review_before_confirmation(self):
        self.open('slow_moving')
        feedback = self.save_feedback('合成核查：此前未上架，今日已补货上架；因果关系仍未知。')
        self.assertEqual(feedback['confirmation_status'], 'pending_confirmation')
        confirmation = self.page.locator('#feedback-confirm-form')
        expect(confirmation).to_be_visible()
        expect(confirmation.locator('[name="confirmed_json"]')).to_have_count(0)
        confirmation.locator('[name="factor_0_label"]').fill('人工确认此前未上架')
        confirmation.locator('[name="factor_0_status"]').select_option('accepted')
        confirmation.locator('[name="remediation_status"]').select_option('done')
        confirmation.locator('[name="reviewed"]').check()
        confirmation.locator('[name="current_status"]').fill('已核对上架记录，原因仍需后续销量验证。')
        expect(confirmation.locator('[name="reviewed"]')).not_to_be_checked()
        confirmation.locator('button').click()
        self.assertEqual(self.posts_to('/confirm'), [])
        confirmation.locator('[name="reviewed"]').check()
        with self.page.expect_response(lambda response: response.url.endswith('/confirm')) as event:
            confirmation.locator('button').click()
        self.assertEqual(event.value.json()['confirmation_status'], 'confirmed')
        confirmed = self.posts_to('/confirm')[0].post_data_json['confirmed']
        self.assertEqual(confirmed['factors'][0]['confirmation_status'], 'confirmed')
        self.assertEqual(confirmed['factors'][0]['causal_status'], 'unknown')
        self.assertEqual(confirmed['raw_text'], feedback['raw_text'])
        with self.page.expect_response(lambda response: response.url.endswith('/replan')) as event:
            self.page.locator('[data-action="replan"]').click()
        self.assertEqual(event.value.json()['status'], 'pending_approval')

    def test_feedback_review_keeps_unverified_draft_claims_unknown(self):
        self.open('slow_moving')
        feedback = self.save_feedback('上个月可能有一段时间未上架，具体日期和处理结果尚未核实。')
        form = self.page.locator('#feedback-confirm-form')
        expect(form.locator('[name="factor_0_status"]')).to_have_value('unknown')
        expect(form.locator('[name="remediation_status"]')).to_have_value('unknown')
        expect(form.locator('[name="current_status"]')).to_have_value('')
        expect(form.locator('[name="date_status"]')).to_have_value('unknown')
        form.locator('[name="reviewed"]').check()
        with self.page.expect_response(lambda response: response.url.endswith('/confirm')):
            form.locator('button').click()
        confirmed = self.posts_to('/confirm')[0].post_data_json['confirmed']
        self.assertEqual(confirmed['raw_text'], feedback['raw_text'])
        self.assertEqual(confirmed['factors'][0]['confirmation_status'], 'pending_confirmation')
        self.assertEqual(confirmed['factors'][0]['causal_status'], 'unknown')
        self.assertEqual(confirmed['remediation_status'], 'unknown')
        self.assertIsNone(confirmed['current_status'])
        self.assertTrue(confirmed['date_interpretation']['needs_confirmation'])
        self.assertIsNone(confirmed['date_interpretation']['relative_date_resolved'])
        self.assertEqual(confirmed['date_interpretation']['uncertain_ranges'], [])

    def test_feedback_original_and_review_are_isolated_per_risk(self):
        self.open('slow_moving')
        first = self.save_feedback('合成记录A：坚果陈列待核查。')
        review = self.page.locator('#feedback-confirm-form')
        review.locator('[name="factor_0_status"]').select_option('excluded')
        review.locator('[name="current_status"]').fill('坚果已有独立门店说明A。')
        with self.page.expect_response(lambda response: response.url.endswith('/risks/3')):
            self.page.locator('#risk-form [name="risk_id"]').select_option('3')
        expect(self.page.locator('#feedback-form [name="raw_text"]')).to_have_value('')
        expect(self.page.locator('#feedback-confirm-form')).to_have_count(0)
        second = self.save_feedback('合成记录B：牛奶批次待核查。')
        self.assertNotEqual(first['id'], second['id'])
        self.assertNotEqual(first['investigation_id'], second['investigation_id'])
        with self.page.expect_response(lambda response: response.url.endswith('/risks/1')):
            self.page.locator('#risk-form [name="risk_id"]').select_option('1')
        expect(self.page.locator('#feedback-form [name="raw_text"]')).to_have_value(first['raw_text'])
        expect(self.page.locator('#feedback-confirm-form [name="feedback_id"]')).to_have_value(first['id'])
        expect(self.page.locator('#feedback-confirm-form [name="factor_0_status"]')).to_have_value('excluded')
        expect(self.page.locator('#feedback-confirm-form [name="current_status"]')).to_have_value('坚果已有独立门店说明A。')
        self.assertEqual(self.posts_to('/confirm'), [])

    def test_editing_saved_feedback_requires_a_new_review_version(self):
        self.open('slow_moving')
        first = self.save_feedback('合成原文：尚未核查。')
        self.page.locator('#feedback-confirm-form [name="reviewed"]').check()
        self.page.locator('#feedback-form [name="raw_text"]').fill('合成更正原文：检查记录仍待提供。')
        expect(self.page.locator('#feedback-confirm-form')).to_have_count(0)
        expect(self.page.locator('#feedback-review-content')).to_contain_text('原文已修改')
        self.assertEqual(self.posts_to('/confirm'), [])
        second = self.save_feedback('合成更正原文：检查记录仍待提供。')
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(first['investigation_id'], second['investigation_id'])
        expect(self.page.locator('#feedback-confirm-form [name="reviewed"]')).not_to_be_checked()
        expect(self.page.locator('#feedback-confirm-form [name="factor_0_status"]')).to_have_value('unknown')

    def test_saved_proposal_exports_csv_and_json_without_write_requests(self):
        self.open('transfer')
        csv_button = self.page.locator('[data-action="export-proposal"][data-format="csv"]')
        expect(csv_button).to_be_disabled()  # Initial seed has actions but no saved input/calculation.
        self.page.locator('#workbench-form [name="quantity"]').fill('41')
        with self.page.expect_response(lambda response: response.url.endswith('/transfer/calculate')):
            self.page.locator('[data-action="calculate"]').click()
        with self.page.expect_response(lambda response: response.url.endswith('/transfer/save')) as event:
            self.page.locator('[data-action="save"]').click()
        proposal = event.value.json()['proposal']
        expect(csv_button).to_be_enabled()
        before = len([call for call in self.api_calls if call.method == 'POST'])
        with self.page.expect_download() as event:
            csv_button.click()
        downloaded = event.value
        self.assertTrue(downloaded.suggested_filename.endswith(f'-v{proposal["current_version"]}.csv'))
        raw = Path(downloaded.path()).read_bytes()
        self.assertTrue(raw.startswith(b'\xef\xbb\xbf'))
        rows = list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))))
        self.assertEqual(rows[0], ['分类','字段','值','单位'])
        self.assertTrue(all(len(row)==4 for row in rows))
        self.assertEqual(next(row[2] for row in rows if row[1]=='方案编号'), proposal['id'])
        self.assertEqual(next(row[2] for row in rows if row[1]=='方案版本'), str(proposal['current_version']))
        self.assertEqual(next(row[2] for row in rows if row[1]=='调拨数量'), '41')
        self.assertIn('不代表审批或执行完成', raw.decode('utf-8-sig'))
        with self.page.expect_download() as event:
            self.page.locator('[data-action="export-proposal"][data-format="json"]').click()
        data = json.loads(Path(event.value.path()).read_text(encoding='utf-8'))
        self.assertEqual(data['metadata']['proposal_version'], proposal['current_version'])
        self.assertEqual(data['metadata']['proposal_status'], 'draft')
        self.assertEqual(len([call for call in self.api_calls if call.method=='POST']), before)
        self.page.locator('#workbench-form [name="quantity"]').fill('42')
        expect(csv_button).to_be_disabled()
        with self.page.expect_response(lambda response: response.url.endswith('/transfer/calculate')):
            self.page.locator('[data-action="calculate"]').click()
        expect(csv_button).to_be_disabled()

    def test_export_refuses_a_newer_saved_backend_version(self):
        self.open('transfer')
        with self.page.expect_response(lambda response: response.url.endswith('/transfer/save')) as event:
            self.page.locator('[data-action="save"]').click()
        proposal = event.value.json()['proposal']
        button = self.page.locator('[data-action="export-proposal"][data-format="csv"]')
        expect(button).to_be_enabled()
        status, newer = self.http(self.backend_url + '/api/v1/workbenches/transfer/save', 'POST', {'input':{'risk_id':1,'quantity':41}})
        self.assertEqual(status,200)
        self.assertGreater(newer['proposal']['current_version'],proposal['current_version'])
        downloads = []
        self.page.on('download', lambda download: downloads.append(download))
        before = len([call for call in self.api_calls if call.method=='POST'])
        button.click()
        expect(self.page.locator('#page-status')).to_contain_text('方案或输入已经变化')
        self.assertEqual(downloads, [])
        self.assertEqual(len([call for call in self.api_calls if call.method=='POST']), before)

    def test_export_refuses_a_version_saved_between_its_two_read_checks(self):
        self.open('transfer')
        with self.page.expect_response(lambda response: response.url.endswith('/transfer/save')) as event:
            self.page.locator('[data-action="save"]').click()
        proposal = event.value.json()['proposal']
        button = self.page.locator('[data-action="export-proposal"][data-format="csv"]')
        expect(button).to_be_enabled()
        changes, downloads = [], []

        def save_new_version_before_workbench_read(route):
            # A second client saves after /proposals was read. The browser still
            # receives the real backend response; no successful response is mocked.
            changes.append(self.http(self.backend_url + '/api/v1/workbenches/transfer/save',
                                     'POST', {'input': {'risk_id': 1, 'quantity': 41}}))
            route.continue_()

        self.page.route('**/api/v1/workbenches/transfer?risk_id=1', save_new_version_before_workbench_read)
        self.page.on('download', lambda download: downloads.append(download))
        before = len([call for call in self.api_calls if call.method == 'POST'])
        button.click()
        expect(self.page.locator('#page-status')).to_contain_text('核对期间方案版本或状态已变化')
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0][0], 200)
        self.assertGreater(changes[0][1]['proposal']['current_version'], proposal['current_version'])
        self.assertEqual(downloads, [])
        self.assertEqual(len([call for call in self.api_calls if call.method == 'POST']), before)

    def test_action_queue_opens_the_returned_workbench_and_risk(self):
        status, work = self.http(self.backend_url + '/api/v1/work-items')
        self.assertEqual(status, 200)
        candidate = next(item for item in work['items']
                         if item['route'] == 'expiry-rescue'
                         and isinstance(item.get('workbench_risk_id', item.get('risk_id')), int))
        risk_id = candidate.get('workbench_risk_id', candidate.get('risk_id'))
        self.open('today')
        self.page.locator('[data-action="tab"][data-tab="actions"]').click()
        card = self.page.locator(f'[data-work-id="{candidate["id"]}"]')
        expect(card).to_contain_text(candidate['title'])
        card.locator('[data-action="open-workbench"]').click()
        expect(self.page).to_have_url(f'{self.base_url}/#expiry-rescue')
        expect(self.page.locator('#workbench-form [name="risk_id"]')).to_have_value(str(risk_id))
        self.assertEqual(self.posts_to('/expiry-rescue/calculate'), [])
        self.assertEqual(self.posts_to('/expiry-rescue/save'), [])

    def test_overview_displays_live_data_and_can_change_period(self):
        self.open()
        expect(self.page.locator('#page-content')).to_contain_text('合成')
        expect(self.page.locator('#page-content')).to_contain_text('155,283.70')
        self.assertTrue(any('/retail/overview' in call.url for call in self.api_calls))
        self.page.locator('#overview-form [name="period"]').select_option('30')
        with self.page.expect_response(lambda response: '/retail/overview?period=30' in response.url) as event:
            self.page.locator('#overview-form button.primary-button').click()
        self.assertEqual(event.value.json()['scope']['period'], 30)
        expect(self.page.locator('#page-content')).to_contain_text('155,283.70')

    def test_cash_simulation_requires_preview_confirmation_and_uses_live_result(self):
        self.open('cashflow_simulation')
        form = self.page.locator('#simulation-form')
        expect(form).to_be_visible()
        form.locator('[name="horizon_days"]').fill('14')
        form.locator('[name="reduction_pct"]').fill('20')
        form.locator('[name="request_text"]').fill('核对未来14天减少20%采购的缺货风险')
        form.locator('button.primary-button').click()
        expect(self.page.locator('#scenario-preview')).to_be_visible()
        self.assertEqual(self.posts_to('/retail/simulate'), [])
        with self.page.expect_response(lambda response: '/retail/simulate' in response.url) as event:
            self.page.locator('[data-action="confirm-simulation"]').click()
        result = event.value.json()
        self.assertEqual(event.value.status, 200)
        self.assertEqual(result['metrics']['purchase_outflow']['baseline'], 132712.3)
        expect(self.page.locator('#page-content')).to_contain_text('132,712.30')
        expect(self.page.locator('#page-content')).to_contain_text('105,690.80')
        request = self.posts_to('/retail/simulate')[0].post_data_json
        self.assertEqual((request['horizon_days'], request['reduction_pct']), (14, 20))

    def test_editing_simulation_invalidates_the_unsubmitted_preview(self):
        self.open('cashflow_simulation')
        form = self.page.locator('#simulation-form')
        form.locator('button.primary-button').click()
        expect(self.page.locator('[data-action="confirm-simulation"]')).to_be_visible()
        form.locator('[name="reduction_pct"]').fill('25')
        expect(self.page.locator('[data-action="confirm-simulation"]')).to_have_count(0)
        self.assertEqual(self.posts_to('/retail/simulate'), [])

    def test_workbench_calculation_displays_backend_constraints(self):
        self.open('transfer')
        form = self.page.locator('#workbench-form')
        expect(form).to_be_visible()
        form.locator('[name="quantity"]').fill('100')
        with self.page.expect_response(lambda response: '/workbenches/transfer/calculate' in response.url) as event:
            self.page.locator('[data-action="calculate"]').click()
        result = event.value.json()
        self.assertFalse(result['calculation']['valid'])
        expect(self.page.locator('#page-content')).to_contain_text('超出调出门店可调数量')
        self.assertEqual(self.posts_to('/workbenches/transfer/save'), [])

    def test_calculated_but_unsaved_input_cannot_approve_the_older_proposal(self):
        self.open('transfer')
        self.page.locator('#workbench-form [name="quantity"]').fill('41')
        with self.page.expect_response(lambda response: '/workbenches/transfer/calculate' in response.url):
            self.page.locator('[data-action="calculate"]').click()
        expect(self.page.locator('#calculation-result')).to_be_visible()
        self.page.locator('#app-nav a[href="#today"]').click()
        approve = self.page.locator('[data-proposal-action="approve"][data-id="PROP-AC10-001"]')
        expect(approve).to_be_disabled()
        self.assertEqual(self.posts_to('/approve'), [])
        # Reloading must still inspect the persisted draft; local state is not the authority.
        self.page.reload()
        approve = self.page.locator('[data-proposal-action="approve"][data-id="PROP-AC10-001"]')
        expect(approve).to_be_visible()
        if approve.is_enabled():
            approve.click()
            expect(self.page.locator('#page-status')).to_contain_text('请求未完成')
        self.assertEqual(self.posts_to('/approve'), [])

    def test_read_failure_shows_error_and_can_reload_the_actual_backend(self):
        self.page.route('**/api/v1/retail/overview*', lambda route: route.abort('connectionfailed'))
        self.open()
        expect(self.page.locator('#page-status')).to_contain_text('请求未完成')
        expect(self.page.locator('#page-content')).not_to_contain_text('155,283.70')
        self.page.unroute('**/api/v1/retail/overview*')
        self.page.locator('#page-status [data-action="reload"]').click()
        expect(self.page.locator('#page-content')).to_contain_text('155,283.70')

    def test_changing_overview_scope_and_failing_read_removes_old_metrics(self):
        self.open()
        expect(self.page.locator('#page-content')).to_contain_text('155,283.70')
        self.page.route('**/api/v1/retail/overview*store_id=STORE-001', lambda route: route.abort('connectionfailed'))
        self.page.locator('#overview-form [name="store_id"]').select_option('STORE-001')
        self.page.locator('#overview-form button.primary-button').click()
        expect(self.page.locator('#page-status')).to_contain_text('请求未完成')
        expect(self.page.locator('#page-content')).not_to_contain_text('155,283.70')
        expect(self.page.locator('#page-content .metric')).to_have_count(0)

    def test_pending_save_locks_other_business_forms_and_keeps_original_risk(self):
        pending = []
        self.page.route('**/api/v1/workbenches/transfer/save', lambda route: pending.append(route))
        self.addCleanup(lambda: [route.abort() for route in pending])
        self.open('transfer')
        self.page.locator('#workbench-form [name="quantity"]').fill('41')
        with self.page.expect_response(lambda response: response.url.endswith('/transfer/calculate')):
            self.page.locator('[data-action="calculate"]').click()
        self.page.locator('[data-action="save"]').click()
        expect(self.page.locator('#workbench-form [name="quantity"]')).to_be_disabled()
        self.assertEqual(len(pending), 1)
        self.page.locator('#app-nav a[href="#slow_moving"]').click()
        expect(self.page.locator('#feedback-form [name="raw_text"]')).to_be_disabled()
        expect(self.page.locator('#risk-form [name="risk_id"]')).to_be_disabled()
        expect(self.page.locator('[data-action="open-workbench"]')).to_be_disabled()
        with self.page.expect_response(lambda response: response.url.endswith('/transfer/save')) as event:
            pending.pop().continue_()
        self.assertEqual(event.value.json()['proposal']['risk_id'], 1)
        expect(self.page.locator('#feedback-form [name="raw_text"]')).to_be_enabled()
        expect(self.page.locator('#page-title')).to_have_text('滞销诊断')
        self.page.locator('#app-nav a[href="#transfer"]').click()
        expect(self.page.locator('#workbench-form [name="risk_id"]')).to_have_value('1')
        expect(self.page.locator('#workbench-form [name="quantity"]')).to_have_value('41')
        expect(self.page.locator('#workbench-proposal')).to_contain_text('方案草稿')

    def test_empty_tenant_overview_keeps_unknown_money_out_of_sample_values(self):
        self.context.set_extra_http_headers({'X-Tenant-Id':'empty-browser-view'})
        self.open()
        expect(self.page.locator('#page-content')).to_contain_text('未接入')
        expect(self.page.locator('#page-content')).not_to_contain_text('155,283.70')
        self.assertFalse(any(request.method == 'POST' for request in self.api_calls))

    def test_data_page_loads_the_current_manifest_and_downloads_public_inputs(self):
        self.open('data')
        links = self.page.locator('#page-content a[href^="/sample-data/"]')
        expect(links.first).to_be_visible()
        expect(self.page.locator('#page-content')).to_contain_text('合成')
        self.assertTrue(any('/data-center' in request.url for request in self.api_calls))
        for href in links.evaluate_all('(links) => links.map(link => link.getAttribute("href"))'):
            with self.subTest(href=href), urlopen(self.base_url + href, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertTrue(response.read())

    def test_mobile_layout_and_navigation(self):
        self.page.set_viewport_size({'width':390, 'height':844})
        self.open()
        expect(self.page.locator('#page-content')).to_contain_text('合成')
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 390)
        toggle = self.page.locator('#nav-toggle')
        toggle.click()
        expect(toggle).to_have_attribute('aria-expanded', 'true')
        self.page.locator('#app-nav a[href="#cashflow_simulation"]').click()
        expect(self.page.locator('#simulation-form')).to_be_visible()
        expect(toggle).to_have_attribute('aria-expanded', 'false')

    def test_live_backend_version_and_public_api_boundary(self):
        status, schema = self.http(self.backend_url + '/openapi.json')
        self.assertEqual(status, 200)
        self.assertEqual(schema['info']['version'], '1.2.0')
        self.assertNotIn('/api/v1/agent-runs', schema['paths'])
        status, _ = self.http(self.base_url + '/api/v1/agent-runs', 'POST', {})
        self.assertEqual(status, 404)

    def test_proxy_uses_actual_backend_and_preserves_validation_errors(self):
        for payload in ({'reduction_pct':101}, {'horizon_days':1.2}, {'store_id':'not-a-store'}):
            with self.subTest(payload=payload):
                expected = self.http(self.backend_url + '/api/v1/retail/simulate', 'POST', payload)
                observed = self.http(self.base_url + '/api/v1/retail/simulate', 'POST', payload)
                self.assertEqual(observed, expected)
                self.assertEqual(observed[0], 422)

    def test_proxy_preserves_tenant_isolation_and_real_unavailable_state(self):
        headers = {'X-Tenant-Id':'browser-empty-tenant'}
        _, overview = self.http(self.base_url + '/api/v1/retail/overview', headers=headers)
        _, options = self.http(self.base_url + '/api/v1/retail/simulation-options', headers=headers)
        _, simulation = self.http(self.base_url + '/api/v1/retail/simulate', 'POST', {}, headers)
        self.assertFalse(overview['is_demo'])
        self.assertIsNone(overview['inventory']['cost'])
        self.assertIsNone(overview['account']['balance'])
        self.assertEqual(options['stores'], [])
        self.assertEqual(simulation['status'], 'unavailable')
        self.assertIsNone(simulation['metrics'])

    def test_real_saved_proposal_creates_one_external_execution_draft(self):
        for module, risk_id in [('transfer', 1), ('expiry-rescue', 3), ('procurement-brake', 4)]:
            with self.subTest(module=module):
                status, result = self.http(self.base_url + f'/api/v1/workbenches/{module}/calculate',
                                           'POST', {'input': {'risk_id': risk_id}})
                self.assertEqual(status, 200)
                self.assertTrue(result['calculation']['valid'])
        status, saved = self.http(self.base_url + '/api/v1/workbenches/transfer/save',
                                 'POST', {'input': {'risk_id': 1}})
        self.assertEqual(status, 200)
        proposal_id = saved['proposal']['id']
        self.assertEqual(saved['proposal']['status'], 'draft')
        status, submitted = self.http(self.base_url + f'/api/v1/proposals/{proposal_id}/submit', 'POST', {})
        self.assertEqual((status, submitted['status']), (200, 'pending_approval'))
        for action in ('approve', 'execute'):
            url = self.base_url + f'/api/v1/proposals/{proposal_id}/{action}'
            headers = {'Idempotency-Key': f'browser-{action}-{proposal_id}'}
            status, first = self.http(url, 'POST', {}, headers)
            repeated_status, repeated = self.http(url, 'POST', {}, headers)
            self.assertEqual((status, repeated_status), (200, 200))
            self.assertEqual(first['id'], repeated['id'])
        self.assertEqual(first['status'], 'draft_pending_external_execution')
        _, tasks = self.http(self.base_url + '/api/v1/execution-tasks')
        self.assertEqual(len([task for task in tasks['items'] if task['proposal_id'] == proposal_id]), 1)

    def test_real_confirmed_feedback_invalidates_the_previous_proposal(self):
        _, investigation = self.http(self.base_url + '/api/v1/risks/1/investigations', 'POST', {})
        status, feedback = self.http(self.base_url + f"/api/v1/investigations/{investigation['id']}/feedback",
                                     'POST', {'raw_text': '今天已核查此前未上架，现已补上',
                                              'submitted_at': '2026-10-03T10:00:00+08:00'})
        self.assertEqual(status, 200)
        self.assertEqual(feedback['confirmation_status'], 'pending_confirmation')
        _, before = self.http(self.base_url + '/api/v1/proposals')
        previous = next(item for item in before['items'] if item['id'] == 'PROP-AC10-001')
        self.assertEqual(previous['status'], 'pending_approval')
        status, _ = self.http(self.base_url + f"/api/v1/feedback/{feedback['id']}/confirm", 'POST',
                              {'confirmed': {'factors': [{'label': '此前未上架', 'causal_status': 'unknown'}],
                                             'remediation_status': 'done'}})
        self.assertEqual(status, 200)
        _, after = self.http(self.base_url + '/api/v1/proposals')
        invalidated = next(item for item in after['items'] if item['id'] == previous['id'])
        self.assertEqual(invalidated['status'], 'needs_replan')
        status, updated = self.http(self.base_url + '/api/v1/risks/1/replan', 'POST', {})
        self.assertEqual((status, updated['current_version']), (200, previous['current_version'] + 1))
        self.assertEqual(updated['status'], 'pending_approval')


if __name__ == '__main__':
    unittest.main()

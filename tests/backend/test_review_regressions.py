"""Regressions for verified review R2–R5; only temporary databases."""
import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend import api
from backend.imports import inventory_fingerprint
from backend.serialization import dumps
from backend.store import Store
from fastapi.testclient import TestClient

HEADER = 'sku,store,store_id,product,unit,inventory_qty,unit_cost,sales_30,sales_90,sales_cost_30,stat_class,purchase_status'
ROW_A = 'SKU-X,真实甲店,REAL-A,真实商品,箱,100,12.50,10,30,125,C,在采'
ROW_B = 'SKU-Y,真实乙店,REAL-B,另一商品,箱,150,10,20,60,200,C,在采'

class ReviewRegressions(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='review-ca0661b-')
        self.addCleanup(self.directory.cleanup)
        self.store = Store(str(Path(self.directory.name) / 'test.db'))
        self.addCleanup(self.store.close)
        self.store.seed_demo()
        patcher = patch.object(api, 'store', self.store)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(api.app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)

    def upload(self, rows):
        response = self.client.post('/api/v1/data-center/imports', json={
            'filename': 'inventory.csv', 'as_of_date': '2026-10-03',
            'content': HEADER + '\n' + '\n'.join(rows),
        })
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result['status'], 'imported', result)
        return result

    def confirm_quantity(self, risk_id, quantity):
        investigation = self.store.create_investigation(risk_id)
        feedback = self.store.add_feedback(investigation['id'], '盘点核实数量',
            '2026-10-03T12:00:00+08:00', {})
        self.store.confirm_feedback(feedback['id'], {
            'observed_values': {'inventory_qty': quantity},
            'evidence_ref': 'manual-review-count',
        })

    def save(self, module, risk_id, updates):
        draft = self.store.workbench_draft(module, risk_id)
        prior = self.store.risk(risk_id)
        response = self.client.post(f'/api/v1/workbenches/{module}/save', json={
            'expected_version': draft['version'] if draft else 0,
            'expected_proposal_version': prior['proposal_version'] or 0,
            'input': {'risk_id': risk_id, **updates},
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def simulate(self, horizon):
        response = self.client.post('/api/v1/scenarios/simulate', json={
            'target': 1000, 'horizon_days': horizon,
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_row_reordering_reuses_snapshot_and_preserves_effective_facts(self):
        first = self.upload([ROW_A, ROW_B])
        risk_id = next(r['id'] for r in self.store.risks() if r['sku'] == 'SKU-X')
        self.confirm_quantity(risk_id, 90)
        second = self.upload([ROW_B, ROW_A])
        self.assertEqual(first['summary']['snapshot_id'], second['summary']['snapshot_id'],
            'Same tenant, date and normalized row set must not create a new snapshot')
        current = next(r for r in self.store.risks() if r['sku'] == 'SKU-X')
        self.assertEqual(current['id'], risk_id)
        self.assertEqual(current['inventory_qty'], 90)
        self.assertEqual(current['current_fact_version'], 2)
        self.assertEqual(current['investigation_status'], 'confirmed')

    def test_reservation_uses_current_confirmed_inventory_not_demo_quantity(self):
        self.confirm_quantity(1, 200)  # Safety stock remains 30: 170 available.
        first = self.save('transfer', 1, {'quantity': 50, 'target_store_id': 'STORE-002'})
        p = first['proposal']
        self.store.submit_proposal(p['id'])
        self.store.approve(p['id'])
        self.store.execute(p['id'])
        second = self.save('transfer', 1, {'quantity': 50, 'target_store_id': 'STORE-005'})
        self.assertTrue(second['calculation']['valid'])
        self.assertEqual(second['calculation']['limits']['available_to_transfer'], 170)
        p = second['proposal']
        self.store.submit_proposal(p['id'])
        response = self.client.post(f"/api/v1/proposals/{p['id']}/approve", json={
            'expected_version': p['current_version'],
        })
        self.assertEqual(response.status_code, 200, response.text)

    def test_cash_window_excludes_payment_after_one_day(self):
        # Seed snapshot as_of=2026-10-03; original payment=2026-10-13.
        # These tests propose snapshot-anchored future planning semantics.
        # A historical replay API must instead expose that distinct contract.
        self.save('procurement-brake', 4, {'action': 'reduce', 'adjustment_qty': 40})
        short = self.simulate(1)
        long = self.simulate(30)
        self.assertEqual(long['achieved'], 2360)
        self.assertEqual(short['achieved'], 0,
            'A payment ten days later does not improve cash within a one-day window')

    def test_completed_action_is_not_a_new_executable_candidate(self):
        saved = self.save('procurement-brake', 4, {'action': 'reduce', 'adjustment_qty': 40})
        p = saved['proposal']
        self.store.submit_proposal(p['id'])
        self.store.approve(p['id'])
        task = self.store.execute(p['id'])
        self.store.update_execution_status(task['id'], 'completed',
            receipt_ref='manual-completed-review', expected_version=1)
        result = self.simulate(30)
        self.assertNotIn(p['id'], [item.get('proposal_id') for item in result['selected']],
            'A completed action cannot be recommended again as a new executable action')

    def test_legacy_order_dependent_snapshot_is_reused_after_restart(self):
        def legacy_fingerprint(tenant, rows, as_of):
            return hashlib.sha256(dumps({'tenant_id': tenant, 'rows': rows,
                                         'as_of_date': as_of}).encode()).hexdigest()
        with patch('backend.store.inventory_fingerprint', legacy_fingerprint):
            first = self.upload([ROW_A, ROW_B])
        snapshot_id = first['summary']['snapshot_id']
        risk_id = next(r['id'] for r in self.store.risks() if r['sku'] == 'SKU-X')
        self.confirm_quantity(risk_id, 90)
        metadata = json.loads(self.store.one('SELECT metadata_json FROM snapshots WHERE id=?', (snapshot_id,))['metadata_json'])
        metadata.pop('semantic_sha256')
        metadata.pop('fingerprint_version')
        for table in ('snapshots', 'real_inventory_snapshots'):
            self.store.conn.execute(f'UPDATE {table} SET metadata_json=? WHERE id=?', (dumps(metadata), snapshot_id))
        self.store.conn.commit()
        reopened = Store(str(Path(self.directory.name) / 'test.db'))
        try:
            with patch.object(api, 'store', reopened):
                second = self.upload([ROW_B, ROW_A])
            self.assertEqual(second['summary']['snapshot_id'], snapshot_id)
            self.assertEqual(second['summary']['content_sha256'], first['summary']['content_sha256'])
            self.assertNotEqual(second['summary']['semantic_sha256'], second['summary']['content_sha256'])
            self.assertTrue(second['summary']['replayed'])
            self.assertEqual(reopened.risk(risk_id)['inventory_qty'], 90)
            self.assertEqual(reopened.risk(risk_id)['current_fact_version'], 2)
            self.assertEqual(reopened.one('SELECT COUNT(*) AS n FROM real_inventory_snapshots')['n'], 1)
        finally:
            reopened.close()

    def test_changed_source_quantity_creates_snapshot_and_old_retry_does_not_activate_it(self):
        first = self.upload([ROW_A, ROW_B])
        changed = self.upload([ROW_A.replace(',100,12.50,', ',101,12.50,'), ROW_B])
        self.assertNotEqual(first['summary']['snapshot_id'], changed['summary']['snapshot_id'])
        replay = self.upload([ROW_B, ROW_A])
        self.assertEqual(replay['summary']['snapshot_id'], first['summary']['snapshot_id'])
        self.assertEqual(self.store.real_inventory_snapshot()['id'], changed['summary']['snapshot_id'])

    def test_fingerprint_ignores_order_but_distinguishes_tenant_date_and_exact_money(self):
        rows = [dict(sku='A', store_id='S', unit_cost=Decimal('9007199254740992.01'),
                     cost_amount=Decimal('9007199254740992.01'), sales_cost_30=None),
                dict(sku='B', store_id='S', unit_cost=Decimal('1.00'),
                     cost_amount=Decimal('1.00'), sales_cost_30=None)]
        original = inventory_fingerprint('demo', rows, '2026-10-03')
        reversed_keys = [dict(reversed(list(row.items()))) for row in reversed(rows)]
        self.assertEqual(original, inventory_fingerprint('demo', reversed_keys, '2026-10-03'))
        self.assertNotEqual(original, inventory_fingerprint('other', rows, '2026-10-03'))
        self.assertNotEqual(original, inventory_fingerprint('demo', rows, '2026-10-04'))
        rows[0]['unit_cost'] += Decimal('.01')
        self.assertNotEqual(original, inventory_fingerprint('demo', rows, '2026-10-03'))

    def test_decreased_current_inventory_still_blocks_existing_plus_new_reservations(self):
        self.confirm_quantity(1, 200)
        first = self.save('transfer', 1, {'quantity': 50, 'target_store_id': 'STORE-002'})['proposal']
        self.store.submit_proposal(first['id'])
        self.store.approve(first['id'])
        self.store.execute(first['id'])
        self.confirm_quantity(1, 80)
        second = self.save('transfer', 1, {'quantity': 30, 'target_store_id': 'STORE-005'})
        self.assertEqual(second['calculation']['limits']['available_to_transfer'], 50)
        p = second['proposal']
        self.store.submit_proposal(p['id'])
        response = self.client.post(f"/api/v1/proposals/{p['id']}/approve", json={'expected_version': p['current_version']})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['detail']['code'], 'inventory_conflict')

    def test_cash_window_is_inclusive_and_does_not_overwrite_saved_calculation(self):
        saved = self.save('procurement-brake', 4, {'action': 'reduce', 'adjustment_qty': 40})
        before = self.store.workbench_draft('procurement-brake', 4)
        self.assertEqual(self.simulate(10)['achieved'], 0)
        at_payment = self.simulate(11)
        self.assertEqual(at_payment['achieved'], 2360)
        self.assertEqual(at_payment['cash_basis']['window_start'], '2026-10-03')
        self.assertEqual(at_payment['cash_basis']['window_end'], '2026-10-13')
        self.assertEqual(at_payment['cash_basis']['snapshot_id'], saved['proposal']['snapshot_id'])
        self.assertEqual(self.store.workbench_draft('procurement-brake', 4), before)

    def test_deferred_payment_is_savings_only_until_the_new_payment_enters_window(self):
        self.save('procurement-brake', 4, {'action': 'delay_payment', 'adjustment_qty': 40})
        self.assertEqual(self.simulate(30)['achieved'], 2360)
        self.assertEqual(self.simulate(60)['achieved'], 0)

    def test_past_payment_and_unknown_dates_do_not_become_savings(self):
        data = self.store.workbench_input('procurement-brake', 4, {'action': 'reduce', 'adjustment_qty': 40})
        result = api._procurement_in_window(data, date(2026, 10, 14), date(2026, 11, 1))
        self.assertEqual(result['cash']['estimated_net_cash_improvement'], 0)
        result = api._procurement_in_window({**data, 'payment_date': None}, date(2026, 10, 3), date(2026, 11, 1))
        self.assertIsNone(result['cash']['estimated_net_cash_improvement'])
        self.assertEqual(result['cash']['completeness'], 'unavailable')

    def test_missing_snapshot_date_fails_explicitly(self):
        self.store.conn.execute("UPDATE snapshots SET metadata_json='{}'")
        self.store.conn.commit()
        response = self.client.post('/api/v1/scenarios/simulate', json={'target': 1000, 'horizon_days': 30})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['detail']['code'], 'missing_planning_date')

    def test_snapshot_change_during_planning_cannot_mix_cash_dates_and_candidates(self):
        self.save('procurement-brake', 4, {'action': 'reduce', 'adjustment_qty': 40})
        original = self.store.planning_drafts
        def import_before_read(tenant_id, expected_snapshot_id=None):
            self.upload([ROW_A, ROW_B])
            return original(tenant_id, expected_snapshot_id=expected_snapshot_id)
        with patch.object(self.store, 'planning_drafts', import_before_read):
            response = self.client.post('/api/v1/scenarios/simulate', json={'target': 1000, 'horizon_days': 30})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['detail']['code'], 'stale_snapshot')

    def test_approval_excludes_action_before_task_generation(self):
        p = self.save('procurement-brake', 4, {'action': 'reduce', 'adjustment_qty': 40})['proposal']
        self.assertEqual(self.simulate(30)['selected'][0]['proposal_version'], p['current_version'])
        self.store.submit_proposal(p['id'])
        self.assertEqual(self.simulate(30)['achieved'], 2360)
        self.store.approve(p['id'])
        self.assertEqual(self.simulate(30)['selected'], [])

    def test_new_procurement_candidate_respects_occupied_order_even_without_legacy_reservation_row(self):
        p = self.save('procurement-brake', 4, {'action': 'reduce', 'adjustment_qty': 40})['proposal']
        self.store.submit_proposal(p['id'])
        self.store.approve(p['id'])
        self.store.execute(p['id'])
        self.store.conn.execute('DELETE FROM inventory_reservations WHERE proposal_id=?', (p['id'],))
        self.store.conn.commit()
        blocked = self.save('procurement-brake', 4, {'action': 'reduce', 'adjustment_qty': 30})
        self.assertTrue(blocked['calculation']['valid'])
        self.assertEqual(self.simulate(30)['selected'], [])
        allowed = self.save('procurement-brake', 4, {'action': 'reduce', 'adjustment_qty': 20})['proposal']
        before = list(self.store.conn.iterdump())
        result = self.simulate(30)
        self.assertEqual(result['achieved'], 1180)
        self.assertEqual(result['selected'][0]['proposal_id'], allowed['id'])
        self.assertEqual(result['selected'][0]['resources'][0]['remaining'], 20)
        self.assertEqual(list(self.store.conn.iterdump()), before)

    def test_unsaved_input_change_cannot_reuse_saved_proposal_identity(self):
        p = self.save('procurement-brake', 4, {'action': 'reduce', 'adjustment_qty': 40})['proposal']
        draft = self.store.workbench_draft('procurement-brake', 4)
        response = self.client.post('/api/v1/workbenches/procurement-brake/calculate', json={
            'expected_version': draft['version'], 'input': {'risk_id': 4, 'adjustment_qty': 30}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.simulate(30)['selected'], [])
        self.assertEqual(self.store.proposal(p['id'])['version']['payload']['input']['adjustment_qty'], 40)

    def test_new_facts_invalidate_candidate_until_resaved(self):
        self.save('procurement-brake', 4, {'action': 'reduce', 'adjustment_qty': 40})
        self.confirm_quantity(4, 100)
        self.assertEqual(self.simulate(30)['selected'], [])
        self.save('procurement-brake', 4, {'action': 'reduce', 'adjustment_qty': 40})
        selected = self.simulate(30)['selected']
        self.assertEqual(selected[0]['fact_version'], 2)

    def test_bundle_checks_shared_destination_and_purchase_resources(self):
        candidates = [{'snapshot_id': 'S', 'resources': [{'key': 'capacity:store:sku', 'quantity': 30, 'remaining': 50}]},
                      {'snapshot_id': 'S', 'resources': [{'key': 'capacity:store:sku', 'quantity': 30, 'remaining': 50}]}]
        self.assertFalse(api._validate_candidate_bundle(candidates)['valid'])
        for item in candidates:
            item['resources'][0]['key'] = 'po:order:1'
        self.assertFalse(api._validate_candidate_bundle(candidates)['valid'])
        candidates[1]['resources'][0]['quantity'] = 20
        self.assertTrue(api._validate_candidate_bundle(candidates)['valid'])

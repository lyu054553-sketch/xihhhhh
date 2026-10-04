"""Real shared-Store transactions, injected business services and isolated HTTP."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import httpx

from backend.errors import BusinessConflict
from backend.hackathon_ai import AIService, migrate
from backend.hackathon_ai.gateway import ModelGateway
from backend.hackathon_shared import CONTRACT_VERSION
from backend.serialization import dumps
from backend.store import Store
from tests.hackathon.test_ai_materials import PNG, call, config, facts, output_for, response


class Facts:
    """A minimal authoritative version table participating in the same tx."""
    def __init__(self, database):
        self.database = database
        self.fail_after_write = False
        self.queries = []
        self.context = {"tenant_id": "tenant-a", "scenario_id": "S01", "branch_id": "base",
                        "snapshot_id": "snapshot-S01-base", "as_of": "2026-10-04T12:00:00+08:00",
                        "data_version": "retail-v2", "fact_version": 1, "is_demo": True,
                        "source_refs": [], "missing_fields": []}
        with database.transaction() as tx:
            tx.execute("CREATE TABLE test_facts (version INTEGER NOT NULL)")
            tx.execute("INSERT INTO test_facts VALUES(1)")
            tx.execute("CREATE TABLE test_events (payload TEXT NOT NULL)")

    def get_context(self, tenant_id, scenario_id, branch_id=None, tx=None):
        if tenant_id != self.context["tenant_id"] or scenario_id != self.context["scenario_id"] or branch_id not in (None, "base"):
            raise ValueError("Scope not found")
        with self.database.transaction() as cursor:
            version = cursor.execute("SELECT version FROM test_facts").fetchone()[0]
        return {**deepcopy(self.context), "fact_version": version}

    def query(self, query):
        self.queries.append(deepcopy(query))
        context = self.get_context(query["context"]["tenant_id"], query["context"]["scenario_id"], query["context"]["branch_id"])
        if query["context"]["fact_version"] != context["fact_version"]:
            raise BusinessConflict("version_conflict", "Facts changed", current_version=context["fact_version"])
        reference = facts()
        return {"contract_version": CONTRACT_VERSION, "query_id": "QUERY-1", "context": context,
                "inventory": [{"store_id": "ST-1", "sku_id": "SKU-1", "lot_id": "LOT-1", "stock_state": "on_hand",
                               "quantity": 50, "base_unit": "件", "unit_cost_cny": 3.5, "blocked_qty": 0,
                               "reserved_qty": 0, "sellable_until": "2026-10-31", "source_ref": "data/01_inventory.csv"}],
                "sales_history": [], "availability_history": [], "demand_forecasts": [], "procurement": {},
                "routes": [], "policies": {}, "payables": [], "missing_fields": [], "warnings": [],
                "reference_data": {"tables": reference["tables"], "target": reference["target"], "evaluation_end": reference["evaluation_end"]}}

    def apply_business_events(self, tx, events, *, expected_fact_version):
        current = tx.execute("SELECT version FROM test_facts").fetchone()[0]
        if current != expected_fact_version:
            raise BusinessConflict("version_conflict", "Facts changed", current_version=current)
        for event in events:
            tx.execute("INSERT INTO test_events VALUES(?)", (dumps(event),))
        tx.execute("UPDATE test_facts SET version=version+1")
        if self.fail_after_write:
            raise ValueError("Injected failure after business write")
        return {"fact_version": current + 1}


class Calculations:
    def __init__(self):
        self.calls = []

    def compare(self, facts, request):
        self.calls.append((deepcopy(facts), deepcopy(request)))
        return {"contract_version": CONTRACT_VERSION, "comparison_id": "COMP-1", "context": facts["context"],
                "candidates": [{"candidate_id": "CAND-1", "calculation": {"expected_cash_in": 100.0,
                    "expected_cash_out": 10.0, "expected_net_cash": 90.0, "expected_sold_qty": 10}}],
                "missing_fields": []}


class AIServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Store(str(Path(self.temp.name) / "ai.db"))
        with self.database.transaction() as tx:
            migrate(tx)
        self.facts = Facts(self.database)
        self.calculations = Calculations()
        self.requests = []
        self.next_response = lambda request: response(json.dumps(output_for(), ensure_ascii=False))

        def handler(request):
            self.assertEqual(self.database._transaction_depth, 0, "HTTP must not hold a shared DB transaction")
            self.requests.append(json.loads(request.content))
            return httpx.Response(200, json=self.next_response(request))
        self.gateway = ModelGateway(config(vision=True), transport=httpx.MockTransport(handler), max_retries=0)
        self.service = AIService(self.database, self.facts, self.calculations, gateway=self.gateway)
        self.extract = {"context": deepcopy(self.facts.context), "actor_id": "reviewer", "idempotency_key": "extract-1",
                        "kind": "purchase_intent", "text": "SKU-1 10件", "source_name": "订单草案"}
        self.fields = {"store_id": "ST-1", "sku_id": "SKU-1", "quantity": 10, "unit": "件", "unit_cost_cny": 3.5,
                       "supplier_id": "SUP-1", "expected_arrival_date": "2026-10-06", "payment_date": "2026-10-09"}

    def tearDown(self):
        self.database.close()
        self.temp.cleanup()

    def confirmation(self, **changes):
        return {"tenant_id": "tenant-a", "actor_id": "reviewer", "idempotency_key": "confirm-1",
                "fields": deepcopy(self.fields), "accepted_unresolved_fields": [], **changes}

    def stored(self, table, field):
        with self.database.transaction() as tx:
            return [row[0] for row in tx.execute("SELECT " + field + " FROM " + table).fetchall()]

    def test_draft_survives_refresh_and_does_not_change_facts_until_confirm(self):
        draft = self.service.extract_material(self.extract)
        self.assertEqual(draft["status"], "needs_review")
        self.assertEqual(draft["context"], self.extract["context"])
        self.assertEqual(draft["fields"]["quantity"]["value"], 10)
        self.assertIn("supplier_id", draft["missing_fields"])
        self.assertEqual(self.stored("test_facts", "version"), [1])
        other = AIService(self.database, self.facts, self.calculations, gateway=self.gateway)
        self.assertEqual(other.get_draft(draft["draft_id"], tenant_id="tenant-a"), draft)
        self.assertEqual(other.get_material(draft["material_id"], tenant_id="tenant-a")["text"], "SKU-1 10件")
        confirmed = other.confirm_material(draft["draft_id"], self.confirmation(), expected_fact_version=1)
        self.assertEqual(confirmed["fact_version"], 2)
        self.assertEqual(confirmed["context"], self.facts.get_context("tenant-a", "S01"))
        self.assertEqual(confirmed["confirmed_fields"]["unit_cost_cny"], 3.5)
        event = json.loads(self.stored("test_events", "payload")[0])
        self.assertEqual(event["event_type"], "material_confirmed")
        self.assertEqual(event["details"]["material_kind"], "purchase_intent")
        self.assertIsNone(event["task_id"])
        self.assertFalse(event["external_write"])
        self.assertEqual(other.get_draft(draft["draft_id"], tenant_id="tenant-a")["status"], "confirmed")
        reread = other.get_draft(draft["draft_id"], tenant_id="tenant-a")
        self.assertEqual(reread["context"], confirmed["context"])
        self.assertEqual(reread["source_context"], draft["context"])

    def test_published_material_context_must_match_authoritative_scope(self):
        draft = self.service.extract_material(self.extract)
        publish = self.facts.apply_business_events
        def corrupt_context(tx, events, *, expected_fact_version):
            result = publish(tx, events, expected_fact_version=expected_fact_version)
            return {**result, "context": {**self.facts.context, "fact_version": 2, "branch_id": "other"}}
        self.facts.apply_business_events = corrupt_context
        with self.assertRaisesRegex(ValueError, "scope and version"):
            self.service.confirm_material(draft["draft_id"], self.confirmation(), expected_fact_version=1)
        self.assertEqual(self.stored("test_facts", "version"), [1])
        self.assertEqual(self.service.get_draft(draft["draft_id"], tenant_id="tenant-a")["status"], "needs_review")

    def test_historical_confirmed_draft_does_not_invent_or_downgrade_context(self):
        draft = self.service.extract_material(self.extract)
        confirmed = self.service.confirm_material(draft["draft_id"], self.confirmation(), expected_fact_version=1)
        saved = self.service.get_draft(draft["draft_id"], tenant_id="tenant-a")
        del saved["context"]
        with self.database.transaction() as tx:
            tx.execute("UPDATE ha_ai_drafts SET draft_json=? WHERE id=?", (dumps(saved), draft["draft_id"]))
        self.assertEqual(self.service.get_draft(draft["draft_id"], tenant_id="tenant-a")["context"], confirmed["context"])
        del confirmed["context"]
        with self.database.transaction() as tx:
            tx.execute("UPDATE ha_ai_drafts SET confirmation_json=? WHERE id=?", (dumps(confirmed), draft["draft_id"]))
        historical = self.service.get_draft(draft["draft_id"], tenant_id="tenant-a")
        self.assertEqual(historical["fact_version"], 2)
        self.assertIsNone(historical["context"])
        self.assertEqual(historical["source_context"], draft["context"])

    def test_idempotency_payload_conflict_and_confirm_replay_after_version_change(self):
        draft = self.service.extract_material(self.extract)
        self.assertEqual(self.service.extract_material(self.extract), draft)
        self.assertEqual(len(self.requests), 1)
        with self.assertRaises(BusinessConflict) as caught:
            self.service.extract_material({**self.extract, "text": "SKU-1 20件"})
        self.assertEqual(caught.exception.code, "idempotency_conflict")
        result = self.service.confirm_material(draft["draft_id"], self.confirmation(), expected_fact_version=1)
        self.assertEqual(self.service.confirm_material(draft["draft_id"], self.confirmation(), expected_fact_version=1), result)
        self.assertEqual(len(self.stored("test_events", "payload")), 1)
        with self.assertRaises(BusinessConflict):
            self.service.confirm_material(draft["draft_id"], self.confirmation(fields={**self.fields, "quantity": 20}), expected_fact_version=1)

    def test_confirmation_joins_transaction_rolls_back_all_writes(self):
        draft = self.service.extract_material(self.extract)
        self.facts.fail_after_write = True
        with self.assertRaisesRegex(ValueError, "Injected failure"):
            self.service.confirm_material(draft["draft_id"], self.confirmation(), expected_fact_version=1)
        self.assertEqual(self.stored("test_facts", "version"), [1])
        self.assertEqual(self.stored("test_events", "payload"), [])
        self.assertEqual(self.service.get_draft(draft["draft_id"], tenant_id="tenant-a")["status"], "needs_review")
        self.facts.fail_after_write = False
        self.assertEqual(self.service.confirm_material(draft["draft_id"], self.confirmation(), expected_fact_version=1)["fact_version"], 2)

    def test_tenant_scope_and_stale_fact_version_rejected(self):
        draft = self.service.extract_material(self.extract)
        for method, identifier in ((self.service.get_draft, draft["draft_id"]),
                                   (self.service.get_material, draft["material_id"]),
                                   (self.service.get_run, draft["model_run_id"])):
            with self.assertRaises(ValueError):
                method(identifier, tenant_id="tenant-other")
        with self.assertRaises(ValueError):
            self.service.confirm_material(draft["draft_id"], self.confirmation(tenant_id="tenant-other"), expected_fact_version=1)
        with self.database.transaction() as tx:
            tx.execute("UPDATE test_facts SET version=2")
        with self.assertRaises(BusinessConflict) as caught:
            self.service.confirm_material(draft["draft_id"], self.confirmation(), expected_fact_version=1)
        self.assertEqual(caught.exception.current_version, 2)
        self.assertEqual(self.stored("test_events", "payload"), [])

    def test_money_reference_unit_and_extra_fields_fail_without_publishing(self):
        draft = self.service.extract_material(self.extract)
        for field, value in (("unit_cost_cny", 1.234), ("quantity", -1), ("sku_id", "UNKNOWN"),
                             ("unit", "箱"), ("supplier_confirmed", True), ("supplier_id", "UNKNOWN")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.service.confirm_material(draft["draft_id"], self.confirmation(fields={**self.fields, field: value}), expected_fact_version=1)
        self.assertEqual(self.stored("test_events", "payload"), [])

    def test_unresolved_fields_must_be_explicit_and_remain_null(self):
        draft = self.service.extract_material(self.extract)
        fields = {key: value for key, value in self.fields.items() if key != "payment_date"}
        with self.assertRaises(BusinessConflict):
            self.service.confirm_material(draft["draft_id"], self.confirmation(fields=fields), expected_fact_version=1)
        result = self.service.confirm_material(draft["draft_id"], self.confirmation(fields=fields, accepted_unresolved_fields=["payment_date"]), expected_fact_version=1)
        self.assertIsNone(result["confirmed_fields"]["payment_date"])
        self.assertEqual(result["missing_fields"], ["payment_date"])

    def test_return_terms_percentage_and_contract_acceptance_separate(self):
        draft = self.service.extract_material({**self.extract, "kind": "return_terms"})
        fields = {"supplier_id": "SUP-1", "sku_id": "SKU-1", "settlement_mode": "cash_refund",
                  "return_deadline": "2026-10-09", "refund_pct": 90, "contract_allows_return": True,
                  "requires_supplier_acceptance": True, "freight_fee_cny": 12.50}
        result = self.service.confirm_material(draft["draft_id"], self.confirmation(fields=fields), expected_fact_version=1)
        self.assertEqual(result["confirmed_fields"]["refund_pct"], 90)
        event = json.loads(self.stored("test_events", "payload")[0])
        self.assertNotIn("supplier_confirmed", event["details"]["fields"])
        self.assertEqual(event["event_type"], "material_confirmed")

    def test_unavailable_preserves_image_text_and_manual_confirmation(self):
        gateway = ModelGateway(config(model=""), transport=httpx.MockTransport(lambda request: self.fail("No model selected")))
        service = AIService(self.database, self.facts, self.calculations, gateway=gateway)
        draft = service.extract_material({**self.extract, "image_data_url": PNG})
        self.assertEqual(draft["status"], "failed")
        run = service.get_run(draft["model_run_id"], tenant_id="tenant-a")
        self.assertEqual(run["status"], "unavailable")
        self.assertEqual(run["events"][-1]["event_type"], "run_unavailable")
        material = service.get_material(draft["material_id"], tenant_id="tenant-a")
        self.assertEqual(material["image_ref"], "ai-material:" + draft["material_id"])
        self.assertEqual(material["text"], self.extract["text"])
        self.assertEqual(service.get_material_image(draft["material_id"], tenant_id="tenant-a")["mime_type"], "image/png")
        self.assertNotIn("base64", json.dumps(run))
        with self.assertRaises(ValueError):
            service.get_material_image(draft["material_id"], tenant_id="other")
        self.assertEqual(service.confirm_material(draft["draft_id"], self.confirmation(), expected_fact_version=1)["status"], "confirmed")

    def test_bad_images_rejected_before_persistence(self):
        for value in ("https://unsafe.invalid/a.png", "data:image/png;base64,YQ==", "data:application/pdf;base64,YQ=="):
            with self.assertRaises(ValueError):
                self.service.extract_material({**self.extract, "image_data_url": value})
        self.assertEqual(self.stored("ha_ai_materials", "id"), [])

    def test_run_uses_actual_queries_calculations_and_persisted_events(self):
        outputs = [response("<think>secret deliberation</think>", calls=[call("facts_query", {}, "read-1")], reasoning_content="hidden rationale"),
                   response(calls=[call("compare_options", {"quantity": 10, "transport_fee": 2.5}, "calc-1")]),
                   response("<think>private thoughts</think>建议核对方案 COMP-1。")]
        self.next_response = lambda request: outputs.pop(0)
        request = {"context": self.facts.context, "actor_id": "reviewer", "idempotency_key": "run-1", "goal": "请比较库存处置方案"}
        run = self.service.run(request)
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["proposal_comparison_id"], "COMP-1")
        self.assertIn("模型草稿", run["summary"])
        self.assertEqual(run["usage"], {"input_tokens": 36, "output_tokens": 12, "cost_cny": None})
        self.assertEqual([e["event_type"] for e in run["events"]], ["run_started", "tool_started", "tool_succeeded", "tool_started", "tool_succeeded", "run_completed"])
        self.assertEqual([e["sequence"] for e in run["events"]], list(range(1, 7)))
        self.assertEqual(self.calculations.calls[0][1]["inputs"], {"quantity": 10, "transport_fee": 2.5})
        self.assertEqual(self.calculations.calls[0][0]["context"], self.facts.context)
        self.assertIn("expected_cash_in", self.requests[-1]["messages"][-1]["content"])
        model_messages = json.dumps(self.requests, ensure_ascii=False)
        self.assertNotIn("snapshot-S01-base", model_messages)
        self.assertNotIn("01_inventory.csv", model_messages)
        persisted = "".join(str(value) for value in self.stored("ha_ai_runs", "result_json") + self.stored("ha_ai_events", "event_json"))
        self.assertNotIn("secret deliberation", persisted)
        self.assertNotIn("hidden rationale", persisted)
        self.assertNotIn("private thoughts", persisted)
        self.assertNotIn("reasoning_content", persisted)
        self.assertEqual(self.service.run(request), run)
        self.assertEqual(len(self.requests), 3)
        refreshed = AIService(self.database, self.facts, self.calculations, gateway=self.gateway).get_run(run["run_id"], tenant_id="tenant-a", after_sequence=4)
        self.assertEqual([e["sequence"] for e in refreshed["events"]], [5, 6])

    def test_text_only_run_is_unverified_and_requires_calculation(self):
        self.next_response = lambda request: response("收益是 1000 元")
        run = self.service.run({"context": self.facts.context, "actor_id": "reviewer", "idempotency_key": "run-1", "goal": "算现金"})
        self.assertEqual(run["status"], "needs_input")
        self.assertIn("program_calculation", run["missing_fields"])
        self.assertIn("模型草稿", run["summary"])
        self.assertIsNone(run["proposal_comparison_id"])

    def test_all_candidates_missing_data_requires_input(self):
        original = self.calculations.compare
        def incomplete(facts, request):
            result = original(facts, request)
            result["candidates"][0].update(feasible=False, missing_fields=["unit_cost_cny"])
            return result
        self.calculations.compare = incomplete
        outputs = [response(calls=[call("facts_query", {}, "read")]), response(calls=[call("compare_options", {}, "calc")]), response("金额待补充")]
        self.next_response = lambda request: outputs.pop(0)
        run = self.service.run({"context": self.facts.context, "actor_id": "reviewer", "idempotency_key": "run-missing", "goal": "检查缺项"})
        self.assertEqual(run["status"], "needs_input")
        self.assertIn("unit_cost_cny", run["missing_fields"])

    def test_unconfirmed_feedback_cannot_enter_run(self):
        draft = self.service.extract_material(self.extract)
        with self.assertRaises(BusinessConflict) as caught:
            self.service.run({"context": self.facts.context, "actor_id": "reviewer", "idempotency_key": "run-feedback", "goal": "按反馈重算",
                              "feedback_material_ids": [draft["material_id"]]})
        self.assertEqual(caught.exception.code, "unconfirmed_material")
        self.assertEqual(len(self.requests), 1)

    def test_model_cannot_set_supplier_acceptance_or_call_business_write(self):
        for index, forbidden in enumerate((call("compare_options", {"supplier_confirmed": True}, "bad-1"), call("apply_business_events", {}, "bad-2"))):
            outputs = [response(calls=[call("facts_query", {})]), response(calls=[forbidden])]
            self.next_response = lambda request: outputs.pop(0)
            run = self.service.run({"context": self.facts.context, "actor_id": "reviewer", "idempotency_key": "run-" + str(index), "goal": "确认供应商已接受"})
            self.assertEqual(run["status"], "failed")
            self.assertEqual(sum(e["event_type"] == "tool_failed" for e in run["events"]), 1)
        self.assertEqual(self.calculations.calls, [])
        self.assertEqual(self.stored("test_events", "payload"), [])

    def test_extract_thoughts_never_persist_and_resolves_injected_context(self):
        self.next_response = lambda request: response("<think>private chain</think>" + json.dumps(output_for(), ensure_ascii=False), reasoning_content="hidden chain")
        request = {key: value for key, value in self.extract.items() if key != "context"}
        request.update(tenant_id="tenant-a", scenario_id="S01", branch_id="base")
        draft = self.service.extract_material(request)
        self.assertEqual(draft["fields"]["quantity"]["value"], 10)
        persisted = self.stored("ha_ai_drafts", "internal_json")[0]
        self.assertNotIn("private chain", persisted)
        self.assertNotIn("hidden chain", persisted)

    def test_migration_joins_caller_transaction_and_is_repeatable(self):
        with self.database.transaction() as tx:
            migrate(tx)
        second = Store(str(Path(self.temp.name) / "migration.db"))
        try:
            with self.assertRaises(RuntimeError):
                with second.transaction() as tx:
                    migrate(tx)
                    raise RuntimeError("rollback DDL")
            self.assertIsNone(second.conn.execute("SELECT name FROM sqlite_master WHERE name='ha_ai_materials'").fetchone())
        finally:
            second.close()


class RealFactIntegrationTests(unittest.TestCase):
    def setUp(self):
        from backend.hackathon_data.service import RetailFactService, migrate as migrate_facts
        from backend.hackathon_calculations.service import CalculationService
        self.temp = tempfile.TemporaryDirectory()
        self.database = Store(str(Path(self.temp.name) / "real-services.db"))
        with self.database.transaction() as tx:
            migrate(tx)
            migrate_facts(tx)
        self.facts = RetailFactService(self.database)
        self.context = self.facts.import_scenario("tenant-real", "S07")["context"]
        self.outputs = [response('{"fields":{}}')]
        self.requests = []
        def handler(request):
            self.requests.append(json.loads(request.content))
            return httpx.Response(200, json=self.outputs.pop(0))
        self.gateway = ModelGateway(config(), transport=httpx.MockTransport(handler), max_retries=0)
        self.service = AIService(self.database, self.facts, CalculationService(), gateway=self.gateway)

    def tearDown(self):
        self.database.close()
        self.temp.cleanup()

    def test_confirmed_purchase_publishes_fact_version_without_inventory_or_order(self):
        before = self.facts.query({"context": self.context})
        target = before["reference_data"]["target"]
        product = next(row for row in before["reference_data"]["tables"]["products"] if row["sku_id"] == target["sku_id"])
        draft = self.service.extract_material({"context": self.context, "actor_id": "manager", "idempotency_key": "e-1", "kind": "purchase_intent", "text": "人工录入采购意向"})
        self.assertEqual(self.facts.get_context("tenant-real", "S07")["fact_version"], 1)
        result = self.service.confirm_material(draft["draft_id"], {"tenant_id": "tenant-real", "actor_id": "manager", "idempotency_key": "c-1",
            "fields": {"store_id": target["store_id"], "sku_id": target["sku_id"], "quantity": 10, "unit": product["base_unit"],
                       "unit_cost_cny": 5, "supplier_id": product["supplier_id"], "expected_arrival_date": "2026-10-10", "payment_date": "2026-10-15"}}, expected_fact_version=1)
        after = self.facts.query({"context": self.facts.get_context("tenant-real", "S07")})
        self.assertEqual(result["fact_version"], 2)
        self.assertEqual(before["inventory"], after["inventory"])
        self.assertEqual(before["procurement"], after["procurement"])
        intent = next(row for row in after["reference_data"]["tables"]["purchase_intents"] if row["intent_id"] == draft["draft_id"])
        self.assertEqual(intent["intent_status"], "draft_unconfirmed")
        self.assertEqual(intent["quantity"], 10)
        self.assertEqual(intent["unit_cost"], 5)
        self.outputs = [response(calls=[call("facts_query", {}, "read-current")]),
                        response(calls=[call("compare_options", {}, "calc-current")]), response("新意向已纳入重新计算，待确认")]
        rerun = self.service.run({"context": after["context"], "actor_id": "manager", "idempotency_key": "r-new-feedback", "goal": "按确认后的意向重算",
                                 "feedback_material_ids": [draft["material_id"]]})
        self.assertEqual(rerun["context"]["fact_version"], 2)
        self.assertEqual(rerun["status"], "completed")
        self.assertTrue(rerun["proposal_comparison_id"])

    def test_real_fact_and_calculation_tool_roundtrip_keeps_amounts_and_business_ids(self):
        self.outputs = [response(calls=[call("facts_query", {}, "read")]),
                        response(calls=[call("compare_options", {}, "calc")]), response("请人工核对计算方案")]
        run = self.service.run({"context": self.context, "actor_id": "manager", "idempotency_key": "r-1", "goal": "比较当前库存与采购现金影响"})
        self.assertEqual(run["status"], "completed", run)
        self.assertIsNotNone(run["proposal_comparison_id"])
        fact_result = json.loads(self.requests[1]["messages"][-1]["content"])
        self.assertTrue(fact_result["row_coverage"]["sales_history"]["truncated"])
        self.assertLessEqual(len(fact_result["sales_history"]), 60)
        target = self.facts.query({"context": self.context})["reference_data"]["target"]
        self.assertIn(target["lot_id"], {row["lot_id"] for row in fact_result["inventory"]})
        self.assertIn("INTENT-S07-001", {row["intent_id"] for row in fact_result["reference_data"]["tables"]["purchase_intents"]})
        calculation = json.loads(self.requests[-1]["messages"][-1]["content"])
        self.assertTrue(calculation["candidates"])
        self.assertIn("expected_cash_in_cny", calculation["candidates"][0]["calculation"])
        self.assertIn("expected_sold_qty", calculation["candidates"][0]["calculation"])
        for message in self.requests:
            for record in message["messages"]:
                if record["role"] == "tool":
                    self.assertNotIn('"risk_inputs"', record["content"])
                    self.assertNotIn('"branch_id"', record["content"])
                    self.assertNotIn('"snapshot_id"', record["content"])


if __name__ == "__main__":
    unittest.main()

"""AI boundary tests: no environment, dotenv, database or live model access."""

import base64
from copy import deepcopy
from decimal import Decimal
import json
import unittest
from unittest.mock import patch

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from backend.hackathon_ai.runner import AgentTool, run_agent
from backend.hackathon_ai.materials import (MAX_TEXT_CHARS, MaterialFields, MaterialInput, extract_material,
                               validate_confirmed_fields, validate_image)
from backend.model_config import ModelConfig, ProviderConfig
from backend.hackathon_ai.gateway import ModelError, ModelGateway, model_context, model_value, scoped_facts


PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aL3sAAAAASUVORK5CYII="


def config(provider="deepseek", vision=False, model="test-text", key="test-secret-not-real"):
    return ModelConfig(text_provider=provider, vision_provider=provider if vision else "",
                       providers={provider: ProviderConfig(api_key=SecretStr(key),
                           base_url="https://unit-test.invalid/v1", model=model,
                           vision_model="test-vision" if vision else "")})


def facts():
    return {"dataset_id": "test", "scenario_id": "S01", "branch_id": "base",
            "clock_at": "2026-10-04T12:00:00+08:00", "snapshot_id": "snap1", "data_version": 1,
            "target": {"store_id": "ST-1", "sku_id": "SKU-1", "lot_id": "LOT-1"},
            "evaluation_end": "2026-10-31", "is_demo": True,
            "tables": {"products": [{"sku_id": "SKU-1", "product_name": "饼干", "base_unit": "件",
                                        "supplier_id": "SUP-1"}],
                       "stores": [{"store_id": "ST-1"}, {"store_id": "ST-2"}],
                       "suppliers": [{"supplier_id": "SUP-1"}],
                       "lots": [{"lot_id": "LOT-1", "sku_id": "SKU-1"}],
                       "inventory": [{"store_id": "ST-1", "sku_id": "SKU-1", "lot_id": "LOT-1", "quantity": 50}]}}


def response(content="完成", *, calls=None, reason=None, **extra):
    message = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = calls
    message.update(extra)
    return {"choices": [{"message": message, "finish_reason": reason or ("tool_calls" if calls else "stop")}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16}}


def call(name="calculate_quantity", arguments=None, identifier="call-1"):
    return {"id": identifier, "type": "function", "function": {
        "name": name, "arguments": json.dumps(arguments if arguments is not None else {"quantity": 10})}}


def model_with(handler, **kwargs):
    return ModelGateway(config(**kwargs), transport=httpx.MockTransport(handler), max_retries=0)


def output_for(text="SKU-1 10件", quantity="10"):
    positions = {"sku_id": (0, 5), "quantity": (6, 6 + len(quantity)), "unit": (6 + len(quantity), 7 + len(quantity))}
    return {"fields": {"sku_id": "SKU-1", "quantity": quantity, "unit": "件"},
            "factors": [], "evidence_refs": [
                {"id": "E-" + key, "field": key, "source": "text", "quote": text[start:end],
                 "start": start, "end": end} for key, (start, end) in positions.items()
            ], "missing_fields": [], "unrecognized_products": []}


class GatewayTests(unittest.TestCase):
    def test_provider_routing_and_actual_http_request(self):
        for provider in ("deepseek", "qwen", "minimax"):
            seen = []
            def handle(request):
                seen.append(request)
                return httpx.Response(200, json=response('{"x":1}'))
            result = model_with(handle, provider=provider).complete(
                [{"role": "user", "content": "实际材料"}], response_schema={"type": "object"})
            body = json.loads(seen[0].content)
            self.assertEqual(str(seen[0].url), "https://unit-test.invalid/v1/chat/completions")
            self.assertEqual(body["messages"][-1]["content"], "实际材料")
            self.assertEqual(body["model"], "test-text")
            self.assertEqual(result.provider, provider)
            self.assertEqual(result.usage["total_tokens"], 16)
            self.assertEqual("response_format" in body, provider != "minimax")

    def test_missing_model_does_not_make_request(self):
        seen = []
        gateway = model_with(lambda request: seen.append(request), model="")
        with self.assertRaises(ModelError) as caught:
            gateway.complete([{"role": "user", "content": "hello"}])
        self.assertEqual(caught.exception.code, "not_configured")
        self.assertEqual(seen, [])

    def test_transient_retry_bounded_and_permanent_error_redacted(self):
        count = 0
        def transient(request):
            nonlocal count
            count += 1
            return httpx.Response(503, json={"error": "test-secret-not-real"}) if count == 1 else httpx.Response(200, json=response())
        gateway = ModelGateway(config(), transport=httpx.MockTransport(transient), max_retries=1)
        with patch("backend.hackathon_ai.gateway.time.sleep"):
            result = gateway.complete([{"role": "user", "content": "hello"}])
        self.assertEqual(result.attempts, 2)
        seen = []
        gateway = ModelGateway(config(), transport=httpx.MockTransport(lambda request: (
            seen.append(request) or httpx.Response(401, text="test-secret-not-real"))), max_retries=2)
        with self.assertRaises(ModelError) as caught:
            gateway.complete([{"role": "user", "content": "hello"}])
        self.assertEqual(len(seen), 1)
        self.assertNotIn("test-secret-not-real", json.dumps(caught.exception.as_dict()))

    def test_timeout_is_explicit_and_bounded(self):
        def handler(request):
            raise httpx.ReadTimeout("credential should not surface", request=request)
        gateway = model_with(handler)
        with self.assertRaises(ModelError) as caught:
            gateway.complete([{"role": "user", "content": "hello"}])
        self.assertEqual(caught.exception.code, "timeout")
        self.assertNotIn("credential", str(caught.exception))

    def test_malformed_truncated_and_empty_responses_fail(self):
        cases = [(response("", reason="length"), "truncated_response"),
                 (response(""), "empty_response"), ({"choices": []}, "invalid_response"),
                 (response(calls=[call(), call()]), "invalid_response")]
        for body, code in cases:
            gateway = model_with(lambda request: httpx.Response(200, json=body))
            with self.assertRaises(ModelError) as caught:
                gateway.complete([{"role": "user", "content": "hello"}])
            self.assertEqual(caught.exception.code, code)

    def test_config_not_read_and_secrets_redacted(self):
        with patch("backend.model_config.dotenv_values", side_effect=AssertionError("must not read dotenv")):
            gateway = model_with(lambda request: httpx.Response(200, json=response()))
            gateway.complete([{"role": "user", "content": "hello"}])
        redacted = gateway.redact({"content": "echo test-secret-not-real", "headers": {"Authorization": "secret"}})
        self.assertEqual(redacted, {"content": "echo [REDACTED]"})

    def test_images_and_incomplete_thoughts_do_not_enter_log_payloads(self):
        gateway = model_with(lambda request: httpx.Response(200, json=response()))
        safe = gateway.redact({"content": "材料引用 " + PNG, "analysis": "<think>unfinished private reasoning"})
        self.assertEqual(safe, {"content": "材料引用 [IMAGE_DATA_REDACTED]", "analysis": ""})


class MaterialTests(unittest.TestCase):
    def test_input_change_is_sent_and_changes_draft(self):
        seen = []
        def handle(request):
            body = json.loads(request.content)
            material = json.loads(body["messages"][-1]["content"])
            text = material["raw_text"]
            seen.append(text)
            quantity = "10" if "10" in text else "20"
            return httpx.Response(200, json=response(json.dumps(output_for(text, quantity), ensure_ascii=False)))
        gateway = model_with(handle)
        before = deepcopy(facts())
        one = extract_material({"kind": "purchase_intent", "raw_text": "SKU-1 10件"}, gateway=gateway, facts=before)
        two = extract_material({"kind": "purchase_intent", "raw_text": "SKU-1 20件"}, gateway=gateway, facts=before)
        self.assertEqual(seen, ["SKU-1 10件", "SKU-1 20件"])
        self.assertEqual(one["draft"]["fields"]["quantity"], Decimal("10"))
        self.assertEqual(two["draft"]["fields"]["quantity"], Decimal("20"))
        self.assertNotEqual(one["draft"]["source_hash"], two["draft"]["source_hash"])
        self.assertFalse(one["draft"]["published"])
        self.assertEqual(one["draft"]["confirmation_status"], "pending_confirmation")
        self.assertEqual(before, facts())

    def test_screenshot_routes_actual_data_url_to_vision(self):
        seen = []
        data = {"fields": {"quantity": "10"}, "evidence_refs": [{"id": "E1", "field": "quantity",
            "source": "image", "quote": "10件", "bbox": [0.1, 0.2, 0.3, 0.4]}]}
        gateway = model_with(lambda request: (seen.append(json.loads(request.content)) or
                             httpx.Response(200, json=response(json.dumps(data)))), vision=True)
        result = extract_material({"kind": "purchase_intent", "raw_text": "请识别", "image_data_url": PNG}, gateway=gateway, facts=facts())
        self.assertEqual(seen[0]["model"], "test-vision")
        parts = seen[0]["messages"][-1]["content"]
        self.assertEqual(parts[1]["image_url"]["url"], PNG)
        self.assertIn("请识别", parts[0]["text"])
        self.assertEqual(result["draft"]["evidence_refs"][0]["verification"], "model_reading_unconfirmed")

    def test_no_vision_has_manual_draft_without_fake_output(self):
        gateway = model_with(lambda request: self.fail("must not request text model for image"))
        result = extract_material({"kind": "supplier_terms", "image_data_url": PNG}, gateway=gateway, facts=facts())
        self.assertEqual(result["status"], "manual_required")
        self.assertIsNone(result["raw_output"])
        self.assertEqual(result["error"]["code"], "not_configured")

    def test_untrusted_or_missing_evidence_cannot_supply_fields(self):
        data = output_for()
        data["fields"]["price"] = "999"
        data["evidence_refs"][1]["quote"] = "999"
        gateway = model_with(lambda request: httpx.Response(200, json=response(json.dumps(data))))
        result = extract_material({"kind": "purchase_intent", "raw_text": "SKU-1 10件"}, gateway=gateway, facts=facts())
        fields = result["draft"]["fields"]
        self.assertIsNone(fields["price"])
        self.assertIsNone(fields["quantity"])
        self.assertIn("price", result["draft"]["missing_fields"])
        self.assertIn("quantity", result["draft"]["missing_fields"])

    def test_quantity_must_match_quoted_amount(self):
        data = output_for()
        data["fields"]["quantity"] = "999"
        gateway = model_with(lambda request: httpx.Response(200, json=response(json.dumps(data))))
        result = extract_material({"kind": "purchase_intent", "raw_text": "SKU-1 10件"}, gateway=gateway, facts=facts())
        self.assertIsNone(result["draft"]["fields"]["quantity"])
        self.assertIn("quantity", result["draft"]["missing_fields"])

    def test_unknown_product_and_unit_do_not_publish(self):
        data = output_for("BAD-1 10件")
        data["fields"]["sku_id"] = "BAD-1"
        gateway = model_with(lambda request: httpx.Response(200, json=response(json.dumps(data))))
        result = extract_material({"kind": "purchase_intent", "raw_text": "BAD-1 10件"}, gateway=gateway, facts=facts())
        self.assertIsNone(result["draft"]["fields"]["sku_id"])
        self.assertIsNone(result["draft"]["fields"]["unit"])
        self.assertTrue(result["draft"]["unrecognized_products"])

    def test_invalid_schema_and_json_fail_without_claiming_success(self):
        for raw in ("not JSON", json.dumps({"fields": {"closed": "true"}}),
                    json.dumps({"fields": {"execute_now": True}})):
            gateway = model_with(lambda request: httpx.Response(200, json=response(raw)))
            result = extract_material({"kind": "store_feedback", "raw_text": "关店"}, gateway=gateway)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["error"]["code"], "invalid_extraction")
            self.assertEqual(result["draft"]["raw_text"], "关店")

    def test_callback_trace_is_ordered_and_mutation_isolated(self):
        saved = []
        def event_callback(event):
            saved.append(deepcopy(event))
            event["status"] = "tampered"
        gateway = model_with(lambda request: httpx.Response(200, json=response(json.dumps(output_for()))))
        result = extract_material({"kind": "purchase_intent", "raw_text": "SKU-1 10件"},
                                  gateway=gateway, facts=facts(), on_event=event_callback)
        self.assertEqual(saved, result["events"])
        self.assertEqual([e["sequence"] for e in saved], list(range(1, len(saved) + 1)))
        self.assertTrue(all(e["run_id"] == result["run_id"] for e in saved))
        self.assertNotIn("test-secret-not-real", json.dumps(saved))

    def test_callback_failure_stops_before_model_request(self):
        gateway = model_with(lambda request: self.fail("must stop if persistence fails"))
        def fail(event):
            raise RuntimeError("storage unavailable")
        with self.assertRaises(RuntimeError):
            extract_material({"kind": "store_feedback", "raw_text": "反馈"}, gateway=gateway, on_event=fail)

    def test_image_and_text_boundaries(self):
        self.assertEqual(validate_image(PNG)["mime_type"], "image/png")
        invalid = ["https://example.org/image.png", "data:image/svg+xml;base64,AAAA", "data:image/png;base64,!!!!",
                   "data:image/png;base64," + base64.b64encode(b"not an image").decode()]
        for image in invalid:
            with self.assertRaises(ValueError):
                validate_image(image)
        with self.assertRaises(ValidationError):
            MaterialInput.model_validate({"kind": "store_feedback", "raw_text": "x" * (MAX_TEXT_CHARS + 1)})
        with self.assertRaises(ValidationError):
            MaterialInput.model_validate({"kind": "store_feedback", "raw_text": "x", "submitted_at": "2026-10-04T12:00:00"})

    def test_manual_confirmation_reuses_types_and_master_references(self):
        valid = {"store_id": "ST-1", "sku_id": "SKU-1", "lot_id": "LOT-1", "quantity": "10", "unit": "件", "price": "2.50"}
        confirmed = validate_confirmed_fields(valid, facts())
        self.assertEqual(confirmed["price"], Decimal("2.50"))
        for changes in ({"store_id": "ST-2"}, {"sku_id": "missing"}, {"unit": "箱"}, {"closed": "false"},
                        {"quantity": True}, {"quantity": "NaN"}, {"price": "-2"}, {"refund_ratio": "1.5"},
                        {"date": "2026-02-30"}, {"supplier_id": "missing"}, {"run_sql": "delete"}):
            with self.assertRaises((ValueError, ValidationError)):
                validate_confirmed_fields({**valid, **changes}, facts())

    def test_no_future_or_alternate_facts_schema(self):
        for table in ("future_events", "acceptance", "05_business_events", "06_expected_results"):
            context = facts()
            context["tables"][table] = []
            with self.assertRaises(ValueError):
                scoped_facts(context)
        with self.assertRaises(ValueError):
            scoped_facts({"scope": {}, "version": 1, "tables": {}})

    def test_model_context_strips_answer_metadata_and_limits_rows(self):
        context = facts()
        context["scenario_id"] = "S01"
        context["branch_id"] = "transfer_80"
        context["tables"]["risk_inputs"] = [{"expected_answer": 80}]
        context["tables"]["sales_daily"] = [{"sku_id": "SKU-1", "quantity": 2} for _ in range(100)]
        context["tables"]["products"][0].update({"scenario_id": "S01", "branch_id": "transfer_80",
            "notes": "验收80", "scope": "S01答案", "expected_answer": 80,
            "evidence_uri": "sample-data/05_business_events/S01/transfer_80.xlsx",
            "description": "按件计价"})
        projected = model_context(context)
        encoded = json.dumps(projected, ensure_ascii=False)
        for forbidden in ("S01", "transfer_80", "risk_inputs", "验收80", "expected_answer", "05_business_events"):
            self.assertNotIn(forbidden, encoded)
        self.assertIn("按件计价", encoded)
        self.assertEqual(projected["table_coverage"]["sales_daily"], {"available_rows": 100, "included_rows": 40, "truncated": True})
        self.assertTrue(projected["tables"]["products"][0]["evidence_uri"].startswith("EVID-"))
        self.assertEqual(model_value(projected, context), projected)

    def test_semantic_inferences_and_invented_ids_need_human_review(self):
        text = "ST-1 normal opening; exchange only"
        data = {"fields": {"store_id": "ST-2", "closed": True, "settlement_type": "refund", "date": "2026-10-05"},
                "evidence_refs": [{"id": field, "field": field, "source": "text", "quote": text,
                                   "start": 0, "end": len(text)}
                                  for field in ("store_id", "closed", "settlement_type", "date")]}
        gateway = model_with(lambda request: httpx.Response(200, json=response(json.dumps(data))))
        result = extract_material({"kind": "store_feedback", "raw_text": text}, gateway=gateway, facts=facts())
        for field in ("store_id", "closed", "settlement_type", "date"):
            self.assertIsNone(result["draft"]["fields"][field])
            self.assertIn(field, result["draft"]["missing_fields"])
        suggestions = {item["field"]: item["value"] for item in result["draft"]["unverified_fields"]}
        self.assertEqual(suggestions["closed"], True)
        self.assertEqual(suggestions["settlement_type"], "refund")

    def test_real_loader_and_calculation_fields_survive_sanitization(self):
        from backend.hackathon_data.loader import load_scenario
        from backend.hackathon_calculations.calculations import calculate_purchase
        context = load_scenario("S07")
        context["target"]["lot_id"] = "SCLOT-S07-NEW"
        source = context["tables"]["purchase_intents"][0]
        business = {"lot_id": "SCLOT-S07-NEW", "intent_id": source["intent_id"],
                    "expected_arrival_date": source["expected_arrival_date"],
                    "source_ref": "fixtures/S07/reduce_to_60.txt", "snapshot_id": "S07-reduce_to_60"}
        clean = model_value(business, context)
        self.assertEqual(clean["lot_id"], "SCLOT-S07-NEW")
        self.assertEqual(clean["intent_id"], source["intent_id"])
        self.assertEqual(clean["expected_arrival_date"], source["expected_arrival_date"])
        self.assertTrue(clean["source_ref"].startswith("EVID-"))
        self.assertNotIn("snapshot_id", clean)
        context["target"]["lot_id"] = "LOT-004-003"
        calculation = calculate_purchase(context, {"sales_settlement_days": 0})
        safe = model_value(calculation, context)
        for key in ("expected_cash_in", "expected_cash_out", "expected_net_cash", "expected_sold_qty"):
            self.assertIn(key, safe)
            self.assertEqual(safe[key], float(calculation[key]) if isinstance(calculation[key], Decimal) else calculation[key])
        self.assertEqual(safe["actions"][0]["intent_id"], source["intent_id"])
        with self.assertRaises(ValueError):
            model_value({"source_role": "future_replay", "expected_quantity": 80}, context)


class QuantityInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    quantity: int = Field(ge=0, le=100)


class AgentTests(unittest.TestCase):
    def tool(self, handler=None):
        return AgentTool("calculate_quantity", "计算数量", QuantityInput,
                         handler or (lambda arguments, context: {"quantity": arguments["quantity"] * 2}), kind="calc")

    def test_actual_multistep_tool_calls_feed_next_model_request(self):
        seen, executed, saved = [], [], []
        def handler(request):
            body = json.loads(request.content)
            seen.append(body)
            if len(seen) == 1:
                return httpx.Response(200, json=response("", calls=[call()], reasoning_content="internal protocol state"))
            return httpx.Response(200, json=response("工具计算数量为20，待确认。"))
        def calculate(arguments, context):
            executed.append(deepcopy(arguments))
            context["tables"]["inventory"][0]["quantity"] = 0
            return {"quantity": arguments["quantity"] * 2}
        original = facts()
        tool = self.tool(calculate)
        result = run_agent("核算数量", gateway=model_with(handler), facts=original,
                           tools={tool.name: tool}, on_event=saved.append)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(executed, [{"quantity": 10}])
        self.assertEqual(seen[0]["tools"][0]["function"]["name"], tool.name)
        self.assertEqual(seen[1]["messages"][-1]["role"], "tool")
        self.assertEqual(json.loads(seen[1]["messages"][-1]["content"]), {"quantity": 20})
        self.assertEqual(seen[1]["messages"][-2]["reasoning_content"], "internal protocol state")
        self.assertNotIn("internal protocol state", json.dumps(result))
        self.assertEqual(original, facts())
        self.assertEqual(result["events"], saved)
        self.assertFalse(result["published"])

    def test_unknown_or_invalid_tool_call_never_runs_handler(self):
        executed = []
        tool = self.tool(lambda args, context: executed.append(args))
        invalid_calls = [(call(name="run_sql"), "tool_not_allowed"),
                         (call(arguments={"quantity": "10"}), "invalid_tool_arguments"),
                         (call(arguments={"quantity": 10, "sql": "delete"}), "invalid_tool_arguments")]
        for item, expected in invalid_calls:
            gateway = model_with(lambda request: httpx.Response(200, json=response("", calls=[item])))
            result = run_agent("核算", gateway=gateway, facts=facts(), tools={tool.name: tool})
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["error"]["code"], expected)
        self.assertEqual(executed, [])

    def test_steps_and_tool_call_limits(self):
        count = 0
        def handler(request):
            nonlocal count
            count += 1
            return httpx.Response(200, json=response("", calls=[call(identifier=f"c{count}")]))
        tool = self.tool()
        result = run_agent("核算", gateway=model_with(handler), facts=facts(), tools={tool.name: tool}, max_steps=2)
        self.assertEqual(result["error"]["code"], "step_limit")
        self.assertEqual(count, 2)
        count = 0
        result = run_agent("核算", gateway=model_with(handler), facts=facts(), tools={tool.name: tool}, max_tool_calls=1)
        self.assertEqual(result["error"]["code"], "tool_limit")
        self.assertEqual(len(result["tool_results"]), 1)

    def test_repeated_tool_identifier_and_handler_failure(self):
        tool = self.tool()
        gateway = model_with(lambda request: httpx.Response(200, json=response("", calls=[call()])))
        result = run_agent("核算", gateway=gateway, facts=facts(), tools={tool.name: tool})
        self.assertEqual(result["error"]["code"], "duplicate_tool_call")
        def broken(args, context):
            raise RuntimeError("do not expose test-secret-not-real")
        tool = self.tool(broken)
        result = run_agent("核算", gateway=gateway, facts=facts(), tools={tool.name: tool})
        self.assertEqual(result["error"]["code"], "tool_failed")
        self.assertEqual(result["tool_results"], [])
        self.assertNotIn("test-secret-not-real", json.dumps(result))

    def test_write_or_code_tools_cannot_be_registered(self):
        for name in ("execute_sql", "send_email", "approve_proposal", "write_inventory", "execute_inventory", "transfer_stock"):
            with self.assertRaises(ValueError):
                AgentTool(name, "不可调用", QuantityInput, lambda args, facts: None)
        with self.assertRaises(ValueError):
            AgentTool("read_data", "描述", QuantityInput, lambda args, facts: None, kind="write")

    def test_model_failure_is_explicit_and_does_not_fake_answer(self):
        gateway = model_with(lambda request: httpx.Response(503, text="unavailable"))
        result = run_agent("核算", gateway=gateway, facts=facts(), tools={})
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["answer"])
        self.assertEqual(result["tool_results"], [])

    def test_plain_model_answer_is_explicitly_unverified(self):
        gateway = model_with(lambda request: httpx.Response(200, json=response("预计回款1000元")))
        result = run_agent("估算回款", gateway=gateway, facts=facts(), tools={})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["answer_status"], "unverified_model_draft")
        self.assertEqual(result["calculation_status"], "not_run")
        self.assertFalse(result["financial_claims_verified"])

    def test_time_limit_is_checked_before_tools(self):
        executed = []
        tool = self.tool(lambda args, context: executed.append(args))
        gateway = model_with(lambda request: httpx.Response(200, json=response("", calls=[call()])))
        reply = gateway.complete([{"role": "user", "content": "test"}])
        with patch.object(gateway, "complete", return_value=reply), patch("backend.hackathon_ai.runner.time.monotonic", side_effect=[0, 0, 2]):
            result = run_agent("核算", gateway=gateway, facts=facts(), tools={tool.name: tool}, timeout_seconds=1)
        self.assertEqual(result["error"]["code"], "run_timeout")
        self.assertEqual(executed, [])

    def test_tool_results_strip_fixture_answers_before_next_model_call(self):
        seen = []
        def handler(request):
            seen.append(json.loads(request.content))
            return httpx.Response(200, json=response("", calls=[call()])) if len(seen) == 1 else httpx.Response(200, json=response("待确认"))
        context = facts()
        context["branch_id"] = "transfer_80"
        tool = self.tool(lambda args, state: {"calculated_quantity": 12, "branch_id": "transfer_80",
            "expected_answer": 80, "notes": "hidden expected value", "evidence_ref": "05_events/transfer_80.xlsx"})
        result = run_agent("核查", gateway=model_with(handler), facts=context, tools={tool.name: tool})
        second_request = json.dumps(seen[-1], ensure_ascii=False)
        for value in ("transfer_80", "expected_answer", "hidden expected value", "05_events"):
            self.assertNotIn(value, second_request)
        self.assertIn("calculated_quantity", second_request)
        self.assertEqual(result["status"], "completed")


if __name__ == "__main__":
    unittest.main()

"""Public AgentService with AI-only persistence in the injected shared Store.

Migrations run in the caller's transaction. Model calls never hold a database
transaction. Human confirmation and FactService publication share one transaction.
"""
from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from backend.errors import BusinessConflict
from backend.hackathon_shared import CONTRACT_VERSION, Transaction, TransactionProvider, FactService, CalculationService
from backend.serialization import dumps, json_value
from .gateway import MODEL_TABLES, ModelGateway
from .materials import MaterialInput, Money, extract_material, validate_confirmed_fields, validate_image
from .runner import AgentTool, run_agent


SCHEMA = (
    """CREATE TABLE IF NOT EXISTS ha_ai_materials (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, context_json TEXT NOT NULL,
        source_name TEXT NOT NULL, raw_text TEXT NOT NULL, image BLOB, mime_type TEXT,
        source_hash TEXT NOT NULL, actor_id TEXT NOT NULL, created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS ha_ai_drafts (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, material_id TEXT NOT NULL,
        context_json TEXT NOT NULL, draft_json TEXT NOT NULL, internal_json TEXT,
        confirmation_json TEXT, FOREIGN KEY(material_id) REFERENCES ha_ai_materials(id))""",
    """CREATE TABLE IF NOT EXISTS ha_ai_runs (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, request_json TEXT NOT NULL,
        run_json TEXT NOT NULL, result_json TEXT)""",
    """CREATE TABLE IF NOT EXISTS ha_ai_events (
        run_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_id TEXT NOT NULL UNIQUE,
        event_json TEXT NOT NULL, PRIMARY KEY(run_id,sequence),
        FOREIGN KEY(run_id) REFERENCES ha_ai_runs(id))""",
    """CREATE TABLE IF NOT EXISTS ha_ai_commands (
        tenant_id TEXT NOT NULL, operation TEXT NOT NULL, command_key TEXT NOT NULL,
        fingerprint TEXT NOT NULL, result_id TEXT NOT NULL, response_json TEXT,
        PRIMARY KEY(tenant_id,operation,command_key))""",
)


def migrate(tx: Transaction) -> None:
    if not getattr(tx, "in_transaction", False):
        raise ValueError("AI migrations require the shared active transaction")
    for statement in SCHEMA:
        tx.execute(statement)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _id(prefix):
    return prefix + "-" + uuid4().hex


def _loads(value):
    return json.loads(value)


def _fingerprint(value):
    return hashlib.sha256(json.dumps(json_value(value), ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class ContextInput(StrictInput):
    tenant_id: str = Field(min_length=1, max_length=100)
    scenario_id: str = Field(min_length=1, max_length=100)
    branch_id: str | None
    snapshot_id: str = Field(min_length=1, max_length=200)
    as_of: str = Field(min_length=1, max_length=50)
    data_version: str = Field(min_length=1, max_length=200)
    fact_version: int = Field(ge=1)
    is_demo: bool
    source_refs: list[dict] = Field(default_factory=list, max_length=10000)
    missing_fields: list[str] = Field(default_factory=list, max_length=1000)


class QueryInput(StrictInput):
    store_ids: list[str] = Field(default_factory=list, max_length=50)
    sku_ids: list[str] = Field(default_factory=list, max_length=50)
    lot_ids: list[str] = Field(default_factory=list, max_length=100)
    include: list[Literal["inventory", "sales_history", "availability_history", "demand_forecasts", "procurement", "routes", "policies", "payables"]] = Field(default_factory=lambda: ["inventory", "sales_history", "availability_history", "demand_forecasts", "procurement", "routes", "policies", "payables"])
    history_start: str | None = None
    history_end: str | None = None


class CompareInput(StrictInput):
    objective: str = Field(default="比较适用的库存处置方式", max_length=2000)
    risk_keys: list[str] = Field(default_factory=list, max_length=100)
    horizon_start: str | None = None
    horizon_end: str | None = None
    assumption_ids: list[str] = Field(default_factory=list, max_length=50)
    store_id: str | None = None
    sku_id: str | None = None
    lot_id: str | None = None
    quantity: int | None = Field(default=None, ge=0)
    target_store_id: str | None = None
    transport_fee: Money | None = None
    eta_days: int | None = Field(default=None, ge=0, le=365)
    sales_settlement_days: int | None = Field(default=None, ge=0, le=365)
    recommended_quantity: int | None = Field(default=None, ge=0)
    new_payment_date: str | None = None


FIELD_MAP = {"price": "unit_cost_cny", "receiving_deadline": "expected_arrival_date",
             "payment_due_date": "payment_date", "transport_fee": "freight_fee_cny",
             "handling_fee": "restocking_fee_cny", "settlement_type": "settlement_mode"}
INVERSE_FIELDS = {value: key for key, value in FIELD_MAP.items()}
MODE_OUT = {"refund": "cash_refund", "credit": "payable_credit", "exchange": "exchange", "unknown": "unknown"}
MODE_IN = {value: key for key, value in MODE_OUT.items()}
PURCHASE_FIELDS = {"store_id", "sku_id", "lot_id", "product_name", "quantity", "unit", "unit_cost_cny",
                   "expected_arrival_date", "payment_date", "supplier_id"}
RETURN_FIELDS = {"store_id", "sku_id", "lot_id", "supplier_id", "quantity", "unit", "unit_cost_cny",
                 "settlement_mode", "return_deadline", "refund_pct", "max_return_qty", "freight_fee_cny",
                 "restocking_fee_cny", "settlement_days", "contract_allows_return", "requires_supplier_acceptance"}
REQUIRED_FIELDS = {"purchase_intent": {"store_id", "sku_id", "quantity", "unit", "unit_cost_cny", "expected_arrival_date", "payment_date", "supplier_id"},
                   "return_terms": {"supplier_id", "sku_id", "settlement_mode", "return_deadline"}}


def _private_facts(result):
    """Adapt the shared query DTO, not a concrete data module or fixture reader."""
    context = result["context"]
    reference = result.get("reference_data") or {}
    tables = {name: deepcopy(rows) for name, rows in (reference.get("tables") or {}).items() if name in MODEL_TABLES}
    tables["inventory"] = [{**row, "unit_cost": row.get("unit_cost_cny"), "unit": row.get("base_unit")}
                           for row in result.get("inventory", [])]
    for public, internal in {"sales_history": "sales_daily", "availability_history": "availability_daily",
                             "demand_forecasts": "demand_forecasts", "routes": "routes", "payables": "payables"}.items():
        if result.get(public):
            tables[internal] = deepcopy(result[public])
    return {"dataset_id": None, "scenario_id": context["scenario_id"], "branch_id": context["branch_id"],
            "clock_at": context["as_of"], "snapshot_id": context["snapshot_id"], "data_version": context["data_version"],
            "target": deepcopy(reference.get("target") or {}), "evaluation_end": reference.get("evaluation_end"),
            "tables": tables, "is_demo": context["is_demo"]}


def _tool_view(result):
    """Bound model-facing rows; calculators still receive the full query result."""
    result = deepcopy(result)
    coverage = {}
    target = (result.get("reference_data") or {}).get("target") or {}
    remaining = 60_000

    def preview(rows, name):
        nonlocal remaining
        # Put the target batch first without changing stable business IDs or
        # pretending that this preview represents the complete query result.
        ordered = sorted(rows, key=lambda row: tuple(row.get(field) != target.get(field)
                         for field in ("sku_id", "lot_id", "store_id"))) if rows and all(isinstance(row, dict) for row in rows) else rows
        shown, chars = [], 0
        for row in ordered[:60]:
            size = len(dumps(row))
            if chars + size > 5000 or size > remaining:
                break
            shown.append(row)
            chars += size
            remaining -= size
        if len(shown) != len(rows):
            coverage[name] = {"total_rows": len(rows), "shown_rows": len(shown), "truncated": True}
        return shown

    for key, value in result.items():
        if isinstance(value, list):
            result[key] = preview(value, key)
    reference = result.get("reference_data")
    if isinstance(reference, dict):
        reference["tables"] = {name: preview(rows, "reference_data.tables." + name)
                               for name, rows in reference.get("tables", {}).items() if name in MODEL_TABLES}
    if coverage:
        result["row_coverage"] = coverage
    return result


class AIService:
    def __init__(self, database: TransactionProvider, facts: FactService,
                 calculations: CalculationService, *, gateway: ModelGateway):
        self.database, self.facts, self.calculations, self.gateway = database, facts, calculations, gateway

    def _context(self, request, *, tx=None):
        context = request.get("context")
        if context is None:
            if not callable(getattr(self.facts, "get_context", None)):
                raise ValueError("A full FactContext is required")
            context = self.facts.get_context(request["tenant_id"], request["scenario_id"], request.get("branch_id"), tx=tx)
        context = ContextInput.model_validate(context).model_dump()
        datetime.fromisoformat(context["as_of"].replace("Z", "+00:00"))
        if datetime.fromisoformat(context["as_of"].replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("FactContext.as_of requires timezone")
        for field in ("tenant_id", "scenario_id", "branch_id", "fact_version"):
            if field in request and request[field] != context[field]:
                raise BusinessConflict("context_conflict", "请求与事实上下文不一致")
        return context

    def _write_identity(self, request):
        actor, key = request.get("actor_id"), request.get("idempotency_key")
        if not isinstance(actor, str) or not actor.strip() or len(actor) > 100:
            raise ValueError("actor_id is required and must be bounded")
        if not isinstance(key, str) or not key.strip() or len(key) > 200:
            raise ValueError("idempotency_key is required and must be bounded")
        return actor, key

    def _query(self, context, selectors=None):
        query = {"context": deepcopy(context), **QueryInput.model_validate(selectors or {}).model_dump()}
        result = self.facts.query(query)
        actual = result["context"]
        if any(actual.get(key) != context.get(key) for key in
               ("tenant_id", "scenario_id", "branch_id", "snapshot_id", "fact_version", "as_of")):
            raise BusinessConflict("version_conflict", "事实查询返回了不同范围或版本", current_version=actual.get("fact_version"))
        if result.get("contract_version") != CONTRACT_VERSION or result.get("fixture_only"):
            raise ValueError("Fact service returned an invalid contract or fixture")
        return result

    def _prior(self, tx, tenant, operation, key, fingerprint):
        row = tx.execute("SELECT * FROM ha_ai_commands WHERE tenant_id=? AND operation=? AND command_key=?",
                         (tenant, operation, key)).fetchone()
        if row and row["fingerprint"] != fingerprint:
            raise BusinessConflict("idempotency_conflict", "同一幂等键不能用于不同请求")
        return row

    def _new_run(self, tx, context, request, run_id):
        run = {"contract_version": CONTRACT_VERSION, "run_id": run_id, "status": "running", "context": context,
               "summary": None, "events": [], "missing_fields": [], "proposal_comparison_id": None,
               "usage": None, "created_at": _now(), "finished_at": None}
        tx.execute("INSERT INTO ha_ai_runs VALUES(?,?,?,?,?)", (run_id, context["tenant_id"], dumps(self.gateway.redact(request)), dumps(run), None))
        return run

    def _event(self, run_id, tenant, event_type, *, tool_name=None, input_summary=None, result_ref=None, error=None):
        with self.database.transaction() as tx:
            if tx.execute("SELECT id FROM ha_ai_runs WHERE id=? AND tenant_id=?", (run_id, tenant)).fetchone() is None:
                raise ValueError("Unknown run")
            sequence = tx.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM ha_ai_events WHERE run_id=?", (run_id,)).fetchone()[0]
            event = {"sequence": sequence, "event_id": _id("EV"), "event_type": event_type, "occurred_at": _now(),
                     "tool_name": tool_name, "input_summary": self.gateway.redact(input_summary),
                     "result_ref": result_ref, "error": self.gateway.redact(error)}
            tx.execute("INSERT INTO ha_ai_events VALUES(?,?,?,?)", (run_id, sequence, event["event_id"], dumps(event)))
        return event

    def _finish(self, run_id, context, status, *, summary=None, result=None, missing=None, comparison_id=None, usage=None, error=None):
        event = {"completed": "run_completed", "needs_input": "needs_input", "unavailable": "run_unavailable"}.get(status, "run_failed")
        with self.database.transaction() as tx:
            self._event(run_id, context["tenant_id"], event, result_ref=comparison_id, error=error)
            row = tx.execute("SELECT run_json FROM ha_ai_runs WHERE id=? AND tenant_id=?", (run_id, context["tenant_id"])).fetchone()
            run = _loads(row["run_json"])
            run.update(status=status, summary=self.gateway.redact(summary), missing_fields=sorted(set(missing or [])),
                       proposal_comparison_id=comparison_id, usage=usage, finished_at=_now())
            tx.execute("UPDATE ha_ai_runs SET run_json=?,result_json=? WHERE id=?", (dumps(run), dumps(self.gateway.redact(result)), run_id))
        return self.get_run(run_id, tenant_id=context["tenant_id"])

    def get_run(self, run_id, *, tenant_id, after_sequence=0):
        if type(after_sequence) is not int or after_sequence < 0:
            raise ValueError("after_sequence must be a nonnegative integer")
        with self.database.transaction() as tx:
            row = tx.execute("SELECT run_json FROM ha_ai_runs WHERE id=? AND tenant_id=?", (run_id, tenant_id)).fetchone()
            if row is None:
                raise ValueError("Unknown run")
            run = _loads(row["run_json"])
            run["events"] = [_loads(row["event_json"]) for row in tx.execute(
                "SELECT event_json FROM ha_ai_events WHERE run_id=? AND sequence>? ORDER BY sequence", (run_id, after_sequence)).fetchall()]
            return run

    def run(self, request):
        context = self._context(request)
        actor, key = self._write_identity(request)
        goal = request.get("goal")
        if not isinstance(goal, str) or not goal.strip() or len(goal) > 10000:
            raise ValueError("A bounded goal is required")
        fingerprint = _fingerprint(request)
        tenant = context["tenant_id"]
        material_ids = request.get("feedback_material_ids", [])
        if not isinstance(material_ids, list) or len(material_ids) > 50 or any(not isinstance(item, str) or not item for item in material_ids) or len(set(material_ids)) != len(material_ids):
            raise ValueError("feedback_material_ids must be a bounded unique list")
        purchase_intents = []
        with self.database.transaction() as tx:
            prior = self._prior(tx, tenant, "run", key, fingerprint)
            if prior:
                return self.get_run(prior["result_id"], tenant_id=tenant)
            for material_id in material_ids:
                row = tx.execute("SELECT id,draft_json,context_json,confirmation_json FROM ha_ai_drafts WHERE material_id=? AND tenant_id=?", (material_id, tenant)).fetchone()
                if not row or not row["confirmation_json"]:
                    raise BusinessConflict("unconfirmed_material", "反馈材料尚未人工确认")
                prior_context = _loads(row["context_json"])
                if any(prior_context[k] != context[k] for k in ("tenant_id", "scenario_id", "branch_id")):
                    raise BusinessConflict("context_conflict", "反馈材料不属于当前事实范围")
                if _loads(row["draft_json"])["kind"] == "purchase_intent":
                    purchase_intents.append(row["id"])
            if len(purchase_intents) > 1:
                raise BusinessConflict("ambiguous_purchase_intent", "每次重新评估需选择一个已确认采购意向")
            run_id = _id("RUN")
            self._new_run(tx, context, request, run_id)
            tx.execute("INSERT INTO ha_ai_commands VALUES(?,?,?,?,?,?)", (tenant, "run", key, fingerprint, run_id, None))
        self._event(run_id, tenant, "run_started")
        comparisons, missing, usage = [], [], {"input_tokens": 0, "output_tokens": 0, "cost_cny": None}
        queried = None
        def query_tool(arguments, ignored):
            nonlocal queried
            queried = self._query(context, arguments)
            missing.extend(queried.get("missing_fields", []))
            return _tool_view(queried)
        def compare_tool(arguments, ignored):
            nonlocal queried
            if queried is None:
                raise ValueError("Read facts before requesting calculations")
            arguments = {k: v for k, v in arguments.items() if v is not None}
            inputs = {k: arguments.pop(k) for k in tuple(arguments) if k in
                      {"quantity", "target_store_id", "transport_fee", "eta_days", "sales_settlement_days", "recommended_quantity", "new_payment_date"}}
            if purchase_intents:
                inputs["purchase_intent"] = {"intent_id": purchase_intents[0]}
            comparison = self.calculations.compare(queried, {**arguments, "inputs": inputs})
            if comparison.get("fixture_only") or comparison.get("contract_version") != CONTRACT_VERSION:
                raise ValueError("Calculation service returned a fixture or invalid contract")
            if any(comparison.get("context", {}).get(k) != context[k] for k in ("tenant_id", "scenario_id", "branch_id", "snapshot_id", "fact_version", "as_of")):
                raise ValueError("Calculation service returned a different fact context")
            missing.extend(comparison.get("missing_fields", []))
            candidates = comparison.get("candidates", []) + comparison.get("candidate_groups", [])
            if not any(candidate.get("feasible") for candidate in candidates):
                missing.extend(field for candidate in candidates for field in candidate.get("missing_fields", []))
            comparisons.append(comparison)
            return comparison
        tools = {"facts_query": AgentTool("facts_query", "读取当前租户、场景和版本下的事实；必须先查事实再计算", QueryInput, query_tool),
                 "compare_options": AgentTool("compare_options", "使用刚查询的事实执行确定性库存与现金方案比较", CompareInput, compare_tool, kind="calc")}
        def callback(event):
            kind, details = event["event_type"], event["details"]
            if kind == "model_responded":
                tokens = details.get("usage", {})
                usage["input_tokens"] += int(tokens.get("prompt_tokens") or 0)
                usage["output_tokens"] += int(tokens.get("completion_tokens") or 0)
            if kind in {"tool_started", "tool_completed", "tool_failed", "tool_rejected"}:
                result = details.get("result") or {}
                self._event(run_id, tenant, "tool_succeeded" if kind == "tool_completed" else "tool_failed" if kind != "tool_started" else "tool_started",
                            tool_name=details.get("tool_name"), input_summary=details.get("arguments") if kind == "tool_started" else None,
                            result_ref=result.get("query_id") or result.get("comparison_id"),
                            error={"code": details.get("code"), "message": "受控工具未完成"} if kind in {"tool_failed", "tool_rejected"} else None)
        try:
            # The model starts with scope-free operational clock data; it must
            # actually call facts_query to obtain current evidence.
            empty = {"dataset_id": None, "scenario_id": context["scenario_id"], "branch_id": context["branch_id"],
                     "clock_at": context["as_of"], "snapshot_id": context["snapshot_id"], "data_version": context["data_version"],
                     "target": {}, "evaluation_end": None, "tables": {}, "is_demo": context["is_demo"]}
            result = run_agent(goal, gateway=self.gateway, facts=empty, tools=tools, on_event=callback)
            error = result.get("error")
            unavailable = error and error.get("code") in {"not_configured", "timeout", "network_error", "authentication_failed", "rate_limited", "upstream_error"}
            status = "unavailable" if unavailable else result["status"]
            if status == "completed" and (not comparisons or missing):
                status = "needs_input"
                if not comparisons:
                    missing.append("program_calculation")
            comparison_id = comparisons[-1]["comparison_id"] if comparisons else None
            answer = result.get("answer")
            summary = "模型草稿（金额以关联计算结果为准，待人工核对）：" + answer if answer else None
            return self._finish(run_id, context, status, summary=summary,
                                result={"model_draft": result, "comparisons": comparisons}, missing=missing,
                                comparison_id=comparison_id, usage=usage, error=error)
        except Exception:
            self._finish(run_id, context, "failed", error={"code": "run_failed", "message": "运行未完成，输入已保留"})
            raise

    def get_draft(self, draft_id, *, tenant_id):
        with self.database.transaction() as tx:
            row = tx.execute("SELECT draft_json FROM ha_ai_drafts WHERE id=? AND tenant_id=?", (draft_id, tenant_id)).fetchone()
            if row is None:
                raise ValueError("Unknown material draft")
            return _loads(row["draft_json"])

    def get_material(self, material_id, *, tenant_id):
        with self.database.transaction() as tx:
            row = tx.execute("SELECT id,source_name,raw_text,mime_type,source_hash,created_at FROM ha_ai_materials WHERE id=? AND tenant_id=?", (material_id, tenant_id)).fetchone()
            if row is None:
                raise ValueError("Unknown material")
            return {"contract_version": CONTRACT_VERSION, "material_id": row["id"], "source_name": row["source_name"],
                    "text": row["raw_text"], "mime_type": row["mime_type"], "source_hash": row["source_hash"],
                    "image_ref": "ai-material:" + row["id"] if row["mime_type"] else None, "created_at": row["created_at"]}

    def get_material_image(self, material_id, *, tenant_id):
        with self.database.transaction() as tx:
            row = tx.execute("SELECT image,mime_type FROM ha_ai_materials WHERE id=? AND tenant_id=?", (material_id, tenant_id)).fetchone()
            if row is None or row["image"] is None:
                raise ValueError("Unknown material image")
            return {"mime_type": row["mime_type"], "content": bytes(row["image"])}

    def extract_material(self, request):
        context = self._context(request)
        actor, key = self._write_identity(request)
        kind = request.get("kind")
        if kind not in {"purchase_intent", "return_terms"}:
            raise ValueError("Material kind must be purchase_intent or return_terms")
        material = MaterialInput.model_validate({"kind": "supplier_terms" if kind == "return_terms" else kind,
                    "raw_text": request.get("text", ""), "image_data_url": request.get("image_data_url"),
                    "source_name": request.get("source_name", "用户材料"), "submitted_at": context["as_of"]})
        if material.image_data_url and not material.image_data_url.startswith(("data:image/png;", "data:image/jpeg;")):
            raise ValueError("Public materials support PNG/JPG only")
        fingerprint, tenant = _fingerprint(request), context["tenant_id"]
        with self.database.transaction() as tx:
            prior = self._prior(tx, tenant, "extract", key, fingerprint)
            if prior:
                return self.get_draft(prior["result_id"], tenant_id=tenant)
            material_id, draft_id, run_id = _id("MAT"), _id("DRAFT"), _id("RUN")
            metadata = validate_image(material.image_data_url) if material.image_data_url else {}
            image = base64.b64decode(material.image_data_url.split(",", 1)[1], validate=True) if material.image_data_url else None
            source_hash = _fingerprint({"text": material.raw_text, "image_sha256": metadata.get("sha256"), "source_name": material.source_name})
            tx.execute("INSERT INTO ha_ai_materials VALUES(?,?,?,?,?,?,?,?,?,?)", (material_id, tenant, dumps(context), material.source_name,
                       material.raw_text, image, metadata.get("mime_type"), source_hash, actor, _now()))
            draft = {"contract_version": CONTRACT_VERSION, "draft_id": draft_id, "material_id": material_id,
                     "tenant_id": tenant, "scenario_id": context["scenario_id"], "fact_version": context["fact_version"],
                     "kind": kind, "status": "needs_review", "source": "manager_image" if image else "manager_text", "is_demo": context["is_demo"],
                     "external_write": False, "fields": {}, "missing_fields": ["extraction_pending"], "unmatched_entities": [],
                     "created_at": _now(), "model_run_id": run_id}
            tx.execute("INSERT INTO ha_ai_drafts VALUES(?,?,?,?,?,?,?)", (draft_id, tenant, material_id, dumps(context), dumps(draft), None, None))
            self._new_run(tx, context, {"operation": "extract_material", "material_id": material_id, "actor_id": actor}, run_id)
            tx.execute("INSERT INTO ha_ai_commands VALUES(?,?,?,?,?,?)", (tenant, "extract", key, fingerprint, draft_id, None))
        self._event(run_id, tenant, "run_started")
        try:
            query = self._query(context)
            result = extract_material(material.model_dump(), gateway=self.gateway, facts=_private_facts(query))
            internal = result["draft"]
            allowed = PURCHASE_FIELDS if kind == "purchase_intent" else RETURN_FIELDS
            fields = {}
            unmatched = set(internal.get("reference_errors", {}))
            for name, value in internal["fields"].items():
                public = FIELD_MAP.get(name, name)
                if public not in allowed:
                    continue
                if name == "settlement_type" and value is not None:
                    value = MODE_OUT[value]
                evidence = next((r for r in internal["evidence_refs"] if r["field"] == name), None)
                unit = internal["fields"].get("unit") if name == "quantity" else "CNY" if public.endswith("_cny") else "%" if public.endswith("_pct") else "date" if public.endswith("date") else None
                fields[public] = {"value": json_value(value), "unit": unit,
                                  "evidence_text": evidence["quote"] if evidence else None,
                                  "page": 1 if evidence and evidence["source"] == "image" else None,
                                  "confidence": None, "review_status": "unmatched" if name in unmatched else "missing" if value is None else "needs_review"}
            missing = sorted(key for key in REQUIRED_FIELDS[kind] if fields.get(key, {}).get("value") is None)
            draft.update(fields=fields, missing_fields=missing, unmatched_entities=internal["unrecognized_products"],
                         status="failed" if result["status"] != "completed" else "needs_review")
            with self.database.transaction() as tx:
                tx.execute("UPDATE ha_ai_drafts SET draft_json=?,internal_json=? WHERE id=?", (dumps(draft), dumps(self.gateway.redact(result)), draft_id))
            status = "needs_input" if result["status"] == "completed" else "unavailable" if result["error"]["code"] in {"not_configured", "timeout", "network_error", "authentication_failed", "rate_limited", "upstream_error"} else "failed"
            metadata = result.get("model") or {}
            tokens = metadata.get("usage") or {}
            self._finish(run_id, context, status, summary="材料草稿等待人工确认" if result["status"] == "completed" else None,
                         result={"draft_id": draft_id}, missing=missing, error=result.get("error"),
                         usage={"input_tokens": tokens.get("prompt_tokens", 0), "output_tokens": tokens.get("completion_tokens", 0), "cost_cny": None})
            return self.get_draft(draft_id, tenant_id=tenant)
        except Exception:
            draft.update(status="failed", missing_fields=["manual_review"])
            with self.database.transaction() as tx:
                tx.execute("UPDATE ha_ai_drafts SET draft_json=? WHERE id=?", (dumps(draft), draft_id))
            self._finish(run_id, context, "failed", error={"code": "extraction_failed", "message": "材料已保留，可人工录入"})
            raise

    def confirm_material(self, draft_id, request, *, expected_fact_version):
        actor, key = self._write_identity(request)
        if type(expected_fact_version) is not int or expected_fact_version < 1:
            raise ValueError("expected_fact_version must be positive")
        tenant = request.get("tenant_id") or request.get("context", {}).get("tenant_id")
        if not tenant:
            raise ValueError("tenant_id is required")
        fingerprint = _fingerprint({"draft_id": draft_id, "request": request, "expected_fact_version": expected_fact_version})
        with self.database.transaction() as tx:
            prior = self._prior(tx, tenant, "confirm", key, fingerprint)
            if prior:
                return _loads(prior["response_json"])
            row = tx.execute("SELECT * FROM ha_ai_drafts WHERE id=? AND tenant_id=?", (draft_id, tenant)).fetchone()
            if row is None:
                raise ValueError("Unknown material draft")
            if row["confirmation_json"]:
                raise BusinessConflict("already_confirmed", "材料已确认，修改请建立新草稿")
            draft, context = _loads(row["draft_json"]), _loads(row["context_json"])
            for supplied in (request, request.get("context") or {}):
                if any(field in supplied and supplied[field] != context[field] for field in ("tenant_id", "scenario_id", "branch_id", "snapshot_id", "fact_version")):
                    raise BusinessConflict("context_conflict", "确认请求与材料草稿范围不一致")
            if context["fact_version"] != expected_fact_version:
                raise BusinessConflict("version_conflict", "草稿基于不同事实版本", current_version=context["fact_version"])
            query = self._query(context)
            values = request.get("fields")
            allowed = PURCHASE_FIELDS if draft["kind"] == "purchase_intent" else RETURN_FIELDS
            if not isinstance(values, dict) or set(values) - allowed:
                raise ValueError("Unknown or invalid confirmed material fields")
            internal = {INVERSE_FIELDS.get(name, name): value for name, value in values.items()}
            if internal.get("settlement_type") is not None:
                internal["settlement_type"] = MODE_IN.get(internal["settlement_type"], internal["settlement_type"])
            validated = validate_confirmed_fields(internal, _private_facts(query))
            confirmed = {FIELD_MAP.get(name, name): value for name, value in validated.items()}
            if confirmed.get("settlement_mode") is not None:
                confirmed["settlement_mode"] = MODE_OUT[confirmed["settlement_mode"]]
            if confirmed.get("settlement_mode") == "unknown":
                confirmed["settlement_mode"] = None
            missing = sorted(name for name in REQUIRED_FIELDS[draft["kind"]] if confirmed.get(name) is None)
            accepted = request.get("accepted_unresolved_fields", [])
            if not isinstance(accepted, list) or any(not isinstance(v, str) for v in accepted) or set(accepted) != set(missing):
                raise BusinessConflict("missing_business_data", "需要明确接受尚未解决的必填字段")
            for name in missing:
                confirmed[name] = None
            known_at = context["as_of"]
            event = {"event_id": _id("MATCONF"), "tenant_id": tenant, "scenario_id": context["scenario_id"],
                     "branch_id": context["branch_id"], "task_id": None, "proposal_id": None, "proposal_version": None,
                     "event_type": "material_confirmed", "occurred_at": known_at, "known_at": known_at,
                     "store_id": confirmed.get("store_id"), "target_store_id": None, "sku_id": confirmed.get("sku_id"),
                     "lot_id": confirmed.get("lot_id"), "quantity": confirmed.get("quantity"), "base_unit": confirmed.get("unit"),
                     "amount_cny": None, "business_ref": draft_id, "receipt_ref": row["material_id"], "source": "human_confirmed_material",
                     "is_demo": context["is_demo"], "external_write": False,
                     "details": {"material_kind": draft["kind"], "fields": json_value(confirmed), "accepted_unresolved_fields": missing}}
            published = self.facts.apply_business_events(tx, [event], expected_fact_version=expected_fact_version)
            version = published.get("fact_version") or published.get("context", {}).get("fact_version")
            if type(version) is not int or version <= expected_fact_version:
                raise ValueError("Fact service did not return the published fact version")
            response = {"contract_version": CONTRACT_VERSION, "draft_id": draft_id, "material_id": row["material_id"],
                        "status": "confirmed", "fact_version": version, "confirmed_by": actor, "confirmed_at": _now(),
                        "confirmed_fields": json_value(confirmed), "evidence_refs": [{"material_id": row["material_id"], "field": name,
                        "quoted_text": draft.get("fields", {}).get(name, {}).get("evidence_text")} for name in confirmed],
                        "missing_fields": missing, "is_demo": context["is_demo"], "external_write": False}
            draft.update(status="confirmed", fact_version=version)
            for name, value in confirmed.items():
                field = draft["fields"].setdefault(name, {"unit": None, "evidence_text": None, "page": None, "confidence": None})
                field.update(value=json_value(value), review_status="missing" if value is None else "confirmed")
            draft["missing_fields"] = missing
            tx.execute("UPDATE ha_ai_drafts SET draft_json=?,confirmation_json=? WHERE id=?", (dumps(draft), dumps(response), draft_id))
            tx.execute("INSERT INTO ha_ai_commands VALUES(?,?,?,?,?,?)", (tenant, "confirm", key, fingerprint, draft_id, dumps(response)))
            return response

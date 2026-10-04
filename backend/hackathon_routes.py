"""HTTP integration boundary for the four hackathon.v1 services.

The feature modules stay framework agnostic. This router owns HTTP context,
tenant, idempotency handling and public DTO validation boundaries.
"""
from __future__ import annotations

import base64
from decimal import Decimal
from email import policy
from email.parser import BytesParser
import json
import os
from typing import Any

from fastapi import APIRouter, Body, Header, HTTPException, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from .errors import BusinessConflict
from .hackathon_shared import CONTRACT_VERSION, HackathonServices, get_services, install_services
from .hackathon_data import RetailFactService, list_scenarios, load_replay, migrate as migrate_data
from .hackathon_calculations import CalculationService
from .hackathon_ai import AIService, ModelGateway, migrate as migrate_ai
from .hackathon_ai.gateway import ModelError
from .hackathon_execution import ExecutionService, migrate as migrate_execution


DEFAULT_HACKATHON_DEMO_TENANT = os.environ.get("HACKATHON_DEMO_TENANT", "hackathon-demo")
MAX_MULTIPART_BYTES = 6 * 1024 * 1024
router = APIRouter(prefix="/api/v1/hackathon", tags=["hackathon.v1"])


def initialize_hackathon(app, *, demo_tenant: str | None = None) -> HackathonServices:
    """Migrate and load isolated demo scopes before exposing the feature graph."""
    if getattr(app.state, "hackathon_ready", False):
        return get_services(app)
    database = app.state.store
    facts = RetailFactService(database)
    calculations = CalculationService()
    agent = AIService(database, facts, calculations, gateway=ModelGateway(app.state.model_config))
    execution = ExecutionService(
        database, facts, calculations, replay_reader=load_replay, clock_advancer=facts.advance_clock,
    )
    with database.transaction() as tx:
        migrate_data(tx)
        migrate_ai(tx)
        migrate_execution(tx)
        if os.environ.get("INVENTORY_AGENT_MODE", "demo") != "real":
            tenant = demo_tenant or DEFAULT_HACKATHON_DEMO_TENANT
            directory = list_scenarios()
            for item in directory["items"]:
                for branch_id in item["branches"]:
                    facts.import_scenario(tenant, item["scenario_id"], branch_id, actor_id="system", tx=tx)
    services = HackathonServices(database=database, facts=facts, calculations=calculations, agent=agent, execution=execution)
    install_services(app, services)
    app.state.hackathon_ready = True
    return services


def _services(request: Request) -> HackathonServices:
    try:
        services = get_services(request.app)
    except RuntimeError as exc:
        raise HTTPException(503, detail={"code": "services_unavailable", "message": str(exc)}) from None
    if not all((services.facts, services.calculations, services.agent, services.execution)):
        raise HTTPException(503, detail={"code": "services_unavailable", "message": "hackathon.v1 服务尚未初始化"})
    return services


def _tenant(value: str | None) -> str:
    tenant = value or DEFAULT_HACKATHON_DEMO_TENANT
    if not isinstance(tenant, str) or not tenant.strip() or len(tenant) > 120:
        raise HTTPException(422, detail={"code": "invalid_tenant", "message": "X-Tenant-Id 无效"})
    return tenant


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, BusinessConflict):
        return HTTPException(409, detail=error.detail())
    if isinstance(error, ModelError):
        detail = error.as_dict()
        return HTTPException(503, detail=detail)
    if isinstance(error, (KeyError, TypeError, ValueError)):
        message = str(error)
        not_found = any(token in message.lower() for token in (
            "unknown run", "unknown material", "unknown task", "unknown proposal",
            "scenario has not been imported", "scenario branch is missing", "不存在或无权访问",
        ))
        if not_found:
            return HTTPException(404, detail={"code": "not_found", "message": "记录不存在或无权访问"})
        if isinstance(error, KeyError):
            message = "请求缺少必需字段：" + str(error.args[0])
        return HTTPException(422, detail={"code": "invalid_request", "message": message})
    return HTTPException(500, detail={"code": "internal_error", "message": "服务处理失败"})


def _context(services: HackathonServices, tenant: str, scenario_id: str, branch_id: str | None,
             supplied: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        current = services.facts.get_context(tenant, scenario_id, branch_id)
        if supplied is not None:
            if not isinstance(supplied, dict):
                raise ValueError("context 必须为对象")
            if supplied.get("tenant_id") != tenant:
                raise BusinessConflict("context_conflict", "请求租户与 X-Tenant-Id 不一致")
            # query() is the fact service's authoritative scope/version check.
            services.facts.query({"context": supplied})
            current = supplied
        return current
    except Exception as exc:
        raise _http_error(exc) from None


def _context_for_body(services: HackathonServices, tenant: str, body: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(body, dict) or not isinstance(body.get("context"), dict):
        raise HTTPException(422, detail={"code": "invalid_request", "message": "缺少完整 context"})
    supplied = body["context"]
    return _context(services, tenant, supplied.get("scenario_id"), supplied.get("branch_id"), supplied)


def _query_from_facts(context: dict[str, Any]) -> dict[str, Any]:
    return {"context": context, "store_ids": [], "sku_ids": [], "lot_ids": [], "include": [],
            "history_start": None, "history_end": None}


def _check_context_query(context: dict[str, Any], params: dict[str, Any]) -> None:
    for key in ("snapshot_id", "as_of", "data_version", "fact_version"):
        if params.get(key) is not None and params[key] != context[key]:
            raise BusinessConflict("version_conflict", "事实版本或时点已变化，请重新读取", context["fact_version"])


def _present_params(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _overview(services: HackathonServices, context: dict[str, Any], store_filter: str | None = None) -> dict[str, Any]:
    """Use the execution projection over the authoritative fact overview."""
    result = services.execution.get_overview({"context": context})
    if store_filter and store_filter != "all":
        result["overview"]["stores"] = [row for row in result["overview"]["stores"]
                                        if row.get("store_id") == store_filter]
    return result


def _task_context(services: HackathonServices, tenant: str, task_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    with services.database.transaction() as tx:
        row = tx.execute(
            "SELECT t.metadata_json,pv.payload_json FROM execution_tasks t "
            "JOIN proposals p ON p.id=t.proposal_id JOIN proposal_versions pv ON pv.proposal_id=p.id AND pv.version=t.proposal_version "
            "WHERE t.id=? AND t.tenant_id=?", (task_id, tenant),
        ).fetchone()
    if not row:
        raise HTTPException(404, detail={"code": "not_found", "message": "任务不存在或无权访问"})
    saved_context = json.loads(row["payload_json"]).get("context")
    if not saved_context:
        raise HTTPException(404, detail={"code": "not_found", "message": "任务缺少可验证的事实范围"})
    current = _context(services, tenant, saved_context["scenario_id"], saved_context["branch_id"])
    try:
        result = services.execution.get_task({"context": current, "task_id": task_id})
    except (KeyError, ValueError) as exc:
        raise _http_error(exc) from None
    return current, result["task"]


def _proposal_context(services: HackathonServices, tenant: str, proposal_id: str) -> dict[str, Any]:
    with services.database.transaction() as tx:
        row = tx.execute(
            "SELECT pv.payload_json FROM proposals p JOIN proposal_versions pv ON pv.proposal_id=p.id AND pv.version=p.current_version WHERE p.id=? AND p.tenant_id=?",
            (proposal_id, tenant),
        ).fetchone()
    if not row:
        raise HTTPException(404, detail={"code": "not_found", "message": "方案不存在或无权访问"})
    payload = json.loads(row["payload_json"])
    context = payload.get("context")
    if not context:
        raise HTTPException(404, detail={"code": "not_found", "message": "方案缺少可验证的事实范围"})
    return context


async def _bounded_body(request: Request, limit: int = MAX_MULTIPART_BYTES) -> bytes:
    raw_length = request.headers.get("content-length")
    if raw_length and (not raw_length.isdigit() or int(raw_length) > limit):
        raise HTTPException(413, detail={"code": "body_too_large", "message": "材料请求超过 6 MiB"})
    chunks, length = [], 0
    async for chunk in request.stream():
        length += len(chunk)
        if length > limit:
            raise HTTPException(413, detail={"code": "body_too_large", "message": "材料请求超过 6 MiB"})
        chunks.append(chunk)
    return b"".join(chunks)


def _parse_multipart(content_type: str, raw: bytes) -> tuple[dict[str, str], bytes | None, str | None, str | None]:
    headers = f"MIME-Version: 1.0\r\nContent-Type: {content_type}\r\n\r\n".encode("ascii", "strict")
    message = BytesParser(policy=policy.default).parsebytes(headers + raw)
    if not message.is_multipart():
        raise ValueError("multipart/form-data 缺少有效 boundary")
    values, image, filename, mime_type = {}, None, None, None
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        payload = part.get_payload(decode=True) or b""
        part_filename = part.get_filename()
        if name == "file":
            if image is not None:
                raise ValueError("仅允许上传一张图片")
            if len(payload) > 5 * 1024 * 1024:
                raise ValueError("单张图片不能超过 5 MiB")
            image, filename, mime_type = payload, part_filename, part.get_content_type()
        else:
            values[name] = payload.decode(part.get_content_charset() or "utf-8", "strict")
    return values, image, filename, mime_type


# Routes use request.app rather than a module-level database. This keeps the
# exact same router usable with the temporary Store used by integration tests.
@router.get("/context")
def get_context(request: Request, scenario_id: str = Query(default="S01"), branch_id: str = Query(default="transfer_80"),
                x_tenant_id: str | None = Header(default=None)):
    services = _services(request)
    tenant = _tenant(x_tenant_id)
    context = _context(services, tenant, scenario_id, branch_id)
    facts = services.facts.query(_query_from_facts(context))
    reference = facts.get("reference_data", {})
    return {"contract_version": CONTRACT_VERSION, "context": context,
            "selection": {"target": reference.get("target", {}), "evaluation_end": reference.get("evaluation_end")}}


@router.get("/data-connections/erp")
def get_sample_erp_connection(request: Request, x_tenant_id: str | None = Header(default=None)):
    """Describe the persisted retail fixture used by the decision workspace."""
    services, tenant = _services(request), _tenant(x_tenant_id)
    context = _context(services, tenant, "S01", "transfer_80")
    facts = services.facts.query({"context": context, "include": ["inventory", "procurement"]})
    reference = facts["reference_data"]["tables"]
    stores = {row["store_id"]: row for row in reference["stores"]}
    products = {row["sku_id"]: row for row in reference["products"]}
    inventory = [row for row in facts["inventory"]
                 if row["stock_state"] == "on_hand" and stores[row["store_id"]]["include_in_summary"]]
    purchase_orders = [row for row in facts["procurement"] if row["record_type"] == "purchase_order"]

    def inventory_cost(row):
        return (Decimal(str(row["quantity"])) * Decimal(str(row["unit_cost_cny"]))) if row["unit_cost_cny"] is not None else None
    inventory.sort(key=lambda row: (
        row["store_id"] != "ST-001" or row["sku_id"] != "SKU-001",
        -(inventory_cost(row) or Decimal(0)),
    ))
    preview = [{"store_id": row["store_id"], "store_name": stores[row["store_id"]]["store_name"],
                "sku_id": row["sku_id"], "product_name": products[row["sku_id"]]["product_name"],
                "lot_id": row["lot_id"], "quantity": row["quantity"], "unit": row["base_unit"],
                "unit_cost_cny": row["unit_cost_cny"],
                "inventory_cost_cny": str(inventory_cost(row)) if inventory_cost(row) is not None else None}
               for row in inventory[:5]]
    purchase_preview = [{"po_id": row["po_id"], "po_line_id": row["po_line_id"],
                         "store_name": stores[row["store_id"]]["store_name"],
                         "product_name": products[row["sku_id"]]["product_name"],
                         "ordered_qty": row["ordered_qty"], "received_qty": row["received_qty"],
                         "unit": products[row["sku_id"]]["base_unit"],
                         "order_amount_cny": str(Decimal(str(row["ordered_qty"])) * Decimal(str(row["unit_cost"]))) if row.get("unit_cost") is not None else None,
                         "order_status": row["order_status"], "payment_status": row["payment_status"]}
                        for row in purchase_orders[:5]]
    model_config = request.app.state.model_config
    text_model = model_config.providers.get(model_config.text_provider)
    vision_model = model_config.providers.get(model_config.vision_provider)
    return {"status": "connected", "source_name": "零食仓 ERP", "source_type": "sample_erp",
            "data_as_of": max((row["source_ref"]["known_at"] for row in inventory), default=context["as_of"]),
            "analysis_as_of": context["as_of"], "fact_version": context["fact_version"],
            "complete_store_count": sum(bool(row["include_in_summary"]) for row in stores.values()),
            "directory_store_count": len(stores), "sku_count": len(products),
            "lot_count": len({row["lot_id"] for row in inventory}),
            "inventory_row_count": len(inventory),
            "purchase_order_count": len(purchase_orders),
            "preview": preview, "purchase_preview": purchase_preview,
            "ai": {"provider": model_config.text_provider,
                   "model": text_model.model if text_model else None,
                   "text_configured": bool(text_model and text_model.api_key.get_secret_value() and text_model.model),
                   "vision_model": vision_model.vision_model if vision_model else None,
                   "vision_configured": bool(vision_model and vision_model.api_key.get_secret_value() and vision_model.vision_model)}}


@router.post("/facts/query")
def query_facts(request: Request, body: dict[str, Any] = Body(...), x_tenant_id: str | None = Header(default=None)):
    services, tenant = _services(request), _tenant(x_tenant_id)
    try:
        context = _context_for_body(services, tenant, body)
        result = services.facts.query({**body, "context": context})
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc) from None


@router.post("/risks/assess")
def assess_risks(request: Request, body: dict[str, Any] = Body(...), x_tenant_id: str | None = Header(default=None)):
    services, tenant = _services(request), _tenant(x_tenant_id)
    try:
        context = _context_for_body(services, tenant, body)
        return services.facts.assess_risks({**body, "context": context})
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc) from None


@router.post("/proposals/compare")
def compare_proposals(request: Request, body: dict[str, Any] = Body(...), x_tenant_id: str | None = Header(default=None)):
    services, tenant = _services(request), _tenant(x_tenant_id)
    try:
        context = _context_for_body(services, tenant, body)
        facts = services.facts.query(_query_from_facts(context))
        payload = dict(body)
        payload["context"] = context
        return services.calculations.compare(facts, payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc) from None


@router.get("/proposals")
def list_hackathon_proposals(request: Request, scenario_id: str = Query(default="S01"), branch_id: str = Query(default="transfer_80"),
                             status: str | None = Query(default=None), proposal_id: str | None = Query(default=None),
                             proposal_version: int | None = Query(default=None, ge=1),
                             snapshot_id: str | None = Query(default=None), as_of: str | None = Query(default=None),
                             data_version: str | None = Query(default=None), fact_version: int | None = Query(default=None),
                             x_tenant_id: str | None = Header(default=None)):
    services, tenant = _services(request), _tenant(x_tenant_id)
    try:
        context = _context(services, tenant, scenario_id, branch_id)
        _check_context_query(context, {"snapshot_id": snapshot_id, "as_of": as_of,
                                      "data_version": data_version, "fact_version": fact_version})
        return services.execution.list_proposals({"context": context, **_present_params({
            "status": status, "proposal_id": proposal_id, "proposal_version": proposal_version})})
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc) from None


@router.get("/overview")
def get_overview(request: Request, scenario_id: str = Query(default="S01"), branch_id: str = Query(default="transfer_80"),
                 snapshot_id: str | None = Query(default=None), as_of: str | None = Query(default=None),
                 data_version: str | None = Query(default=None), fact_version: int | None = Query(default=None),
                 store_id: str | None = Query(default=None), x_tenant_id: str | None = Header(default=None)):
    services, tenant = _services(request), _tenant(x_tenant_id)
    try:
        context = _context(services, tenant, scenario_id, branch_id)
        _check_context_query(context, {"snapshot_id": snapshot_id, "as_of": as_of, "data_version": data_version, "fact_version": fact_version})
        return _overview(services, context, store_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc) from None


@router.post("/proposals")
def save_proposal(request: Request, body: dict[str, Any] = Body(...), x_tenant_id: str | None = Header(default=None),
                  idempotency_key: str | None = Header(default=None)):
    services, tenant = _services(request), _tenant(x_tenant_id)
    if not idempotency_key:
        raise HTTPException(422, detail={"code": "idempotency_key_required", "message": "写请求需要 Idempotency-Key"})
    try:
        context = _context_for_body(services, tenant, body)
        payload = dict(body)
        payload.update(context=context, actor_id=body.get("actor_id"), idempotency_key=idempotency_key)
        return services.execution.save_proposal(payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc) from None


@router.post("/proposals/{proposal_id}/confirm")
def confirm_proposal(proposal_id: str, request: Request, body: dict[str, Any] = Body(...),
                     x_tenant_id: str | None = Header(default=None), idempotency_key: str | None = Header(default=None)):
    services, tenant = _services(request), _tenant(x_tenant_id)
    if not idempotency_key:
        raise HTTPException(422, detail={"code": "idempotency_key_required", "message": "写请求需要 Idempotency-Key"})
    try:
        context = _proposal_context(services, tenant, proposal_id)
        payload = {**body, "context": context, "proposal_id": proposal_id, "actor_id": body.get("actor_id"), "idempotency_key": idempotency_key}
        return services.execution.confirm_and_schedule(payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc) from None


@router.get("/tasks")
def list_hackathon_tasks(request: Request, scenario_id: str = Query(default="S01"), branch_id: str = Query(default="transfer_80"),
                         status: str | None = Query(default=None), task_id: str | None = Query(default=None),
                         task_version: int | None = Query(default=None, ge=1), proposal_id: str | None = Query(default=None),
                         proposal_version: int | None = Query(default=None, ge=1),
                         snapshot_id: str | None = Query(default=None), as_of: str | None = Query(default=None),
                         data_version: str | None = Query(default=None), fact_version: int | None = Query(default=None),
                         x_tenant_id: str | None = Header(default=None)):
    services, tenant = _services(request), _tenant(x_tenant_id)
    try:
        context = _context(services, tenant, scenario_id, branch_id)
        _check_context_query(context, {"snapshot_id": snapshot_id, "as_of": as_of,
                                      "data_version": data_version, "fact_version": fact_version})
        return services.execution.list_tasks({"context": context, **_present_params({
            "status": status, "task_id": task_id, "task_version": task_version,
            "proposal_id": proposal_id, "proposal_version": proposal_version})})
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc) from None


@router.get("/tasks/{task_id}")
def get_task(task_id: str, request: Request, task_version: int | None = Query(default=None, ge=1),
             proposal_id: str | None = Query(default=None), proposal_version: int | None = Query(default=None, ge=1),
             snapshot_id: str | None = Query(default=None), as_of: str | None = Query(default=None),
             data_version: str | None = Query(default=None), fact_version: int | None = Query(default=None),
             x_tenant_id: str | None = Header(default=None)):
    services, tenant = _services(request), _tenant(x_tenant_id)
    try:
        context, task = _task_context(services, tenant, task_id)
        _check_context_query(context, {"snapshot_id": snapshot_id, "as_of": as_of,
                                      "data_version": data_version, "fact_version": fact_version})
        return services.execution.get_task({"context": context, "task_id": task_id, **_present_params({
            "task_version": task_version, "proposal_id": proposal_id, "proposal_version": proposal_version})})
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc) from None


@router.post("/tasks/{task_id}/channel-actions")
def record_channel_action(task_id: str, request: Request, body: dict[str, Any] = Body(...),
                          x_tenant_id: str | None = Header(default=None), idempotency_key: str | None = Header(default=None)):
    services, tenant = _services(request), _tenant(x_tenant_id)
    if not idempotency_key:
        raise HTTPException(422, detail={"code": "idempotency_key_required", "message": "写请求需要 Idempotency-Key"})
    try:
        context, task = _task_context(services, tenant, task_id)
        status = {"published": "sent", "submitted": "sent"}.get(body.get("status"), body.get("status"))
        payload = {**body, "context": context, "task_id": task_id, "task_version": body.get("task_version", task.get("version")),
                   "status": status, "actor_id": body.get("actor_id"), "idempotency_key": idempotency_key,
                   "proposal_id": body.get("proposal_id") or task.get("proposal_id"),
                   "proposal_version": body.get("proposal_version", task.get("proposal_version")),
                   "is_demo": context["is_demo"], "external_write": False}
        return services.execution.record_channel_action(payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc) from None


@router.post("/tasks/{task_id}/events")
def record_business_events(task_id: str, request: Request, body: dict[str, Any] = Body(...),
                           x_tenant_id: str | None = Header(default=None), idempotency_key: str | None = Header(default=None)):
    services, tenant = _services(request), _tenant(x_tenant_id)
    if not idempotency_key:
        raise HTTPException(422, detail={"code": "idempotency_key_required", "message": "写请求需要 Idempotency-Key"})
    try:
        context, task = _task_context(services, tenant, task_id)
        if isinstance(body.get("events"), list):
            events = body["events"]
        else:
            record = dict(body)
            for key in ("actor_id", "is_demo", "external_write", "detail", "content_snapshot"):
                if key in {"detail", "content_snapshot"}:
                    continue
                record.pop(key, None)
            event_type = record.get("event_type")
            mapped = {"exception": "execution_exception", "price_effective": "promotion_price_effective",
                      "supplier_reply": "supplier_reply_recorded", "supplier_terms_confirmed": "supplier_terms_reviewed"}.get(event_type, event_type)
            record["event_type"] = mapped
            record["task_id"] = task_id
            record["task_version"] = body.get("task_version", task.get("version"))
            record["proposal_id"] = body.get("proposal_id", task.get("proposal_id"))
            record["proposal_version"] = body.get("proposal_version", task.get("proposal_version"))
            record["known_at"] = body.get("known_at") or context["as_of"]
            record["occurred_at"] = body.get("occurred_at") or context["as_of"]
            record["source"] = body.get("source") or "manual_execution_receipt"
            record["receipt_ref"] = body.get("receipt_ref")
            if body.get("detail") is not None:
                record["detail"] = body["detail"]
            action = task.get("plan", {}).get("actions", [{}])[0]
            if mapped == "transfer_shipped":
                record.setdefault("store_id", action.get("source_store_id"))
                record.setdefault("to_store_id", action.get("target_store_id"))
                record.setdefault("sku_id", action.get("sku_id"))
                record.setdefault("lot_id", action.get("lot_id"))
            elif mapped == "transfer_received":
                record.setdefault("store_id", action.get("target_store_id"))
                record.setdefault("from_store_id", action.get("source_store_id"))
                record.setdefault("sku_id", action.get("sku_id"))
                record.setdefault("lot_id", action.get("lot_id"))
            elif mapped == "promotion_price_effective":
                record.setdefault("promotion_id", action.get("promotion_id"))
            events = [{"kind": body.get("kind", "business"), "record": record}]
        request_body = {"context": context, "task_id": task_id, "events": events,
                        "actor_id": body.get("actor_id"), "idempotency_key": idempotency_key}
        result = services.execution.record_business_events(request_body)
        return {**result, "task_version": next((row.get("version") for row in result.get("accounting", {}).get("tasks", []) if row.get("task_id") == task_id), task.get("version"))}
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc) from None


@router.post("/replays/advance")
def advance_replay(request: Request, body: dict[str, Any] = Body(...), x_tenant_id: str | None = Header(default=None),
                   idempotency_key: str | None = Header(default=None)):
    services, tenant = _services(request), _tenant(x_tenant_id)
    if not idempotency_key:
        raise HTTPException(422, detail={"code": "idempotency_key_required", "message": "写请求需要 Idempotency-Key"})
    try:
        context = _context(services, tenant, body.get("scenario_id"), body.get("branch_id"))
        payload = {**body, "context": context, "actor_id": body.get("actor_id"), "idempotency_key": idempotency_key}
        return services.execution.advance_replay(payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc) from None


@router.get("/accounting")
def get_accounting(request: Request, scenario_id: str = Query(default="S01"), branch_id: str = Query(default="transfer_80"),
                   task_id: str | None = Query(default=None), proposal_id: str | None = Query(default=None),
                   x_tenant_id: str | None = Header(default=None)):
    services, tenant = _services(request), _tenant(x_tenant_id)
    try:
        context = _context(services, tenant, scenario_id, branch_id)
        return services.execution.get_accounting({"context": context, "task_id": task_id, "proposal_id": proposal_id})
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc) from None


@router.get("/agent-runs/{run_id}")
def get_agent_run(run_id: str, request: Request, after_sequence: int = Query(default=0, ge=0),
                  x_tenant_id: str | None = Header(default=None)):
    services, tenant = _services(request), _tenant(x_tenant_id)
    try:
        return services.agent.get_run(run_id, tenant_id=tenant, after_sequence=after_sequence)
    except Exception as exc:
        raise _http_error(exc) from None


@router.post("/agent-runs")
async def start_agent_run(request: Request, body: dict[str, Any] = Body(...), x_tenant_id: str | None = Header(default=None),
                          idempotency_key: str | None = Header(default=None)):
    services, tenant = _services(request), _tenant(x_tenant_id)
    if not idempotency_key:
        raise HTTPException(422, detail={"code": "idempotency_key_required", "message": "写请求需要 Idempotency-Key"})
    try:
        context = _context_for_body(services, tenant, body)
        payload = {**body, "context": context, "actor_id": body.get("actor_id"), "idempotency_key": idempotency_key}
        return await run_in_threadpool(services.agent.run, payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc) from None


@router.post("/materials/extract")
async def extract_material(request: Request, x_tenant_id: str | None = Header(default=None),
                          idempotency_key: str | None = Header(default=None)):
    services, tenant = _services(request), _tenant(x_tenant_id)
    if not idempotency_key:
        raise HTTPException(422, detail={"code": "idempotency_key_required", "message": "写请求需要 Idempotency-Key"})
    content_type = request.headers.get("content-type", "")
    try:
        raw = await _bounded_body(request)
        if content_type.lower().startswith("application/json"):
            body = json.loads(raw.decode("utf-8"))
        elif content_type.lower().startswith("multipart/form-data"):
            form, image, filename, mime_type = _parse_multipart(content_type, raw)
            body = dict(form)
            if "context" not in body:
                raise ValueError("multipart 请求缺少 context")
            body["context"] = json.loads(body["context"])
            if image is not None:
                if mime_type not in {"image/png", "image/jpeg"}:
                    raise ValueError("只接受 PNG/JPG 图片")
                body["image_data_url"] = f"data:{mime_type};base64," + base64.b64encode(image).decode("ascii")
                body["source_name"] = body.get("source_name") or filename or "uploaded-image"
        else:
            raise ValueError("材料请求仅支持 JSON 或 multipart/form-data")
        context = _context_for_body(services, tenant, body)
        payload = {**body, "context": context, "actor_id": body.get("actor_id"), "idempotency_key": idempotency_key}
        return await run_in_threadpool(services.agent.extract_material, payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc) from None


@router.get("/materials/drafts/{draft_id}")
def get_material_draft(draft_id: str, request: Request, x_tenant_id: str | None = Header(default=None)):
    services, tenant = _services(request), _tenant(x_tenant_id)
    try:
        return services.agent.get_draft(draft_id, tenant_id=tenant)
    except Exception as exc:
        raise _http_error(exc) from None


@router.post("/materials/{draft_id}/confirm")
def confirm_material(draft_id: str, request: Request, body: dict[str, Any] = Body(...),
                     x_tenant_id: str | None = Header(default=None), idempotency_key: str | None = Header(default=None)):
    services, tenant = _services(request), _tenant(x_tenant_id)
    if not idempotency_key:
        raise HTTPException(422, detail={"code": "idempotency_key_required", "message": "写请求需要 Idempotency-Key"})
    try:
        draft = services.agent.get_draft(draft_id, tenant_id=tenant)
        payload = {**body, "context": draft["context"], "tenant_id": tenant,
                   "actor_id": body.get("actor_id"), "idempotency_key": idempotency_key}
        result = services.agent.confirm_material(draft_id, payload, expected_fact_version=body.get("expected_fact_version"))
        result["context"] = services.facts.get_context(tenant, draft["context"]["scenario_id"], draft["context"]["branch_id"])
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc) from None


@router.get("/materials/{material_id}")
def get_material(material_id: str, request: Request, x_tenant_id: str | None = Header(default=None)):
    services, tenant = _services(request), _tenant(x_tenant_id)
    try:
        return services.agent.get_material(material_id, tenant_id=tenant)
    except Exception as exc:
        raise _http_error(exc) from None


@router.get("/materials/{material_id}/image")
def get_material_image(material_id: str, request: Request, x_tenant_id: str | None = Header(default=None)):
    services, tenant = _services(request), _tenant(x_tenant_id)
    try:
        image = services.agent.get_material_image(material_id, tenant_id=tenant)
        return Response(content=image["content"], media_type=image["mime_type"], headers={"Cache-Control": "private, no-store"})
    except Exception as exc:
        raise _http_error(exc) from None


@router.get("/cases/{case_id}")
def get_case(case_id: str, request: Request, proposal_version: int | None = Query(default=None, ge=1),
             task_id: str | None = Query(default=None), task_version: int | None = Query(default=None, ge=1),
             snapshot_id: str | None = Query(default=None), as_of: str | None = Query(default=None),
             data_version: str | None = Query(default=None), fact_version: int | None = Query(default=None),
             x_tenant_id: str | None = Header(default=None)):
    services, tenant = _services(request), _tenant(x_tenant_id)
    try:
        saved_context = _proposal_context(services, tenant, case_id)
        context = _context(services, tenant, saved_context["scenario_id"], saved_context["branch_id"])
        _check_context_query(context, {"snapshot_id": snapshot_id, "as_of": as_of,
                                      "data_version": data_version, "fact_version": fact_version})
        return services.execution.get_case({"context": context, "case_id": case_id, **_present_params({
            "proposal_version": proposal_version, "task_id": task_id, "task_version": task_version})})
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc) from None

"""Bounded OpenAI-compatible requests using the existing model configuration.

This module never loads environment variables or reads a dotenv file. Applications
pass their already-loaded ModelConfig; tests can pass an httpx.MockTransport.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import hashlib
import math
import re
import time
from typing import Any, Callable, Literal
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from backend.model_config import ModelConfig
from backend.serialization import json_value


MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MODEL_TABLES = {
    "stores", "products", "suppliers", "people", "store_products", "risk_policies",
    "inventory", "lots", "sales_daily", "availability_daily", "inventory_movements",
    "historical_orders", "demand_forecasts", "routes", "store_calendar", "purchase_orders",
    "in_transit", "accounts", "payables", "return_terms", "promotion_stages", "bundle_items",
    "assumptions", "materials", "purchase_intents", "procurement_policy", "transfer_policy",
}
HIDDEN_KEYS = {"scenario_id", "branch_id", "canonical_branch_id", "dataset_id", "data_version", "snapshot_id",
               "scope", "version", "warnings", "warning", "notes", "note", "expected", "replay",
               "acceptance", "future_events", "input_scope", "input_role", "pending_overrides",
               "applied_override_ids", "risk_inputs", "is_demo", "expected_answer", "expected_result",
               "expected_results", "expected_output", "reference_answer"}
SOURCE_KEYS = {"evidence_ref", "evidence_refs", "evidence_uri", "source_location", "source_file",
               "source_path", "source_ref", "file_path", "filename", "material_id"}


def visible_text(text: str) -> str:
    """Strip provider thinking blocks, including an unfinished final block."""
    return re.sub(r"<(think|thinking|analysis|reasoning)\b[^>]*>[\s\S]*?(?:</\1\s*>|$)",
                  "", text, flags=re.IGNORECASE).strip()


class ModelError(Exception):
    """Safe public error: never includes upstream bodies, URLs or credentials."""

    def __init__(self, code: str, message: str, *, retryable: bool = False,
                 attempts: int = 0, http_status: int | None = None):
        super().__init__(message)
        self.code, self.message = code, message
        self.retryable, self.attempts, self.http_status = retryable, attempts, http_status

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message,
                "retryable": self.retryable, "attempts": self.attempts,
                "http_status": self.http_status}


@dataclass
class ModelReply:
    content: str
    tool_calls: list[dict]
    message: dict
    provider: str
    model: str
    finish_reason: str
    usage: dict = field(default_factory=dict)
    elapsed_ms: int = 0
    attempts: int = 1

    def metadata(self) -> dict:
        return {"provider": self.provider, "model": self.model,
                "finish_reason": self.finish_reason, "usage": self.usage,
                "elapsed_ms": self.elapsed_ms, "attempts": self.attempts}


class RunEvents:
    """Synchronous callbacks must persist successfully before work continues."""

    def __init__(self, on_event: Callable[[dict], None] | None = None):
        self.run_id = "RUN-" + uuid4().hex
        self.events: list[dict] = []
        self.on_event = on_event

    def emit(self, event_type: str, status: str, details: dict | None = None) -> dict:
        event = {"event_id": "EV-" + uuid4().hex, "run_id": self.run_id,
                 "sequence": len(self.events) + 1, "event_type": event_type,
                 "status": status, "occurred_at": datetime.now(timezone.utc).isoformat(),
                 "details": json_value(details or {})}
        if self.on_event:
            self.on_event(deepcopy(event))
        self.events.append(event)
        return event


def scoped_facts(facts: dict | None) -> dict:
    """Take only the shared loader's published facts, never load scenario files."""
    if facts is None:
        return {"dataset_id": None, "scenario_id": None, "branch_id": None, "clock_at": None,
                "snapshot_id": None, "data_version": None, "target": {}, "evaluation_end": None,
                "tables": {}, "is_demo": True}
    if not isinstance(facts, dict) or not isinstance(facts.get("tables"), dict):
        raise ValueError("facts 必须包含 tables 对象")
    if "scope" in facts or "version" in facts:
        raise ValueError("facts 必须使用统一加载器的顶层 dataset_id/scenario_id/snapshot_id 字段")
    result = {key: deepcopy(facts.get(key)) for key in
              ("dataset_id", "scenario_id", "branch_id", "clock_at", "snapshot_id", "data_version",
               "target", "evaluation_end", "tables", "is_demo")}
    for name, rows in result["tables"].items():
        normalized = str(name).lower()
        if any(part in normalized for part in ("future", "acceptance", "replay", "05", "06")):
            raise ValueError("AI 上下文不能包含未来回放或验收表")
        if not isinstance(name, str) or not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("facts.tables 的每张表必须为行对象列表")
    return result


def fact_metadata(facts: dict) -> dict:
    return {"scope": {key: facts.get(key) for key in
                       ("dataset_id", "scenario_id", "branch_id", "clock_at", "evaluation_end")},
            "version": {key: facts.get(key) for key in ("snapshot_id", "data_version")}}


def model_value(value: Any, facts: dict | None = None) -> Any:
    """Strip fixture metadata and turn source paths into opaque evidence refs.

    This is applied to *both* initial facts and every tool result before they are
    sent to a model. Business identifiers (SKU, store, lot, order) remain usable.
    """
    labels = [str((facts or {}).get(key) or "") for key in
              ("scenario_id", "branch_id", "canonical_branch_id", "dataset_id")]
    labels = [label for label in labels if label]

    def opaque(item):
        if isinstance(item, list):
            return [opaque(v) for v in item]
        if isinstance(item, str) and re.fullmatch(r"EVID-[0-9a-f]{20}", item):
            return item
        encoded = json.dumps(json_value(item), ensure_ascii=False, sort_keys=True)
        return "EVID-" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:20]

    def clean(item):
        if isinstance(item, dict):
            if item.get("source_role") in {"future_replay", "expected_answers", "acceptance_only"}:
                raise ValueError("模型上下文不能使用未来回放或验收来源")
            result = {}
            for key, val in item.items():
                name = str(key).lower().lstrip("_")
                if name in HIDDEN_KEYS or name.startswith(("acceptance_", "replay_", "future_")):
                    continue
                if name in SOURCE_KEYS or name.endswith(("_source_path", "_source_file")):
                    result[key] = opaque(val) if val is not None else None
                elif name.endswith("_id"):
                    # SKU/lot/order/intent IDs are executable tool references.
                    # Embedded scenario tokens must not corrupt those identities.
                    result[key] = val
                else:
                    result[key] = clean(val)
            return result
        if isinstance(item, list):
            return [clean(val) for val in item]
        if isinstance(item, str):
            text = item
            for label in labels:
                text = re.sub(r"(?<![A-Za-z0-9_])" + re.escape(label) + r"(?![A-Za-z0-9_])", "[范围标识]", text)
            if re.search(r"(?:^|[/\\])(?:05|06)[_\-/\\]|[/\\](?:expected|replay|acceptance)(?:[/\\.]|$)", text, re.I):
                return opaque(text)
            return text
        return item
    return clean(json_value(value))


def model_context(facts: dict, *, tables: set[str] | None = None) -> dict:
    """Bound context size; full rows stay available only to controlled tools."""
    selected = MODEL_TABLES if tables is None else MODEL_TABLES & tables
    result = {"clock_at": facts.get("clock_at"), "evaluation_end": facts.get("evaluation_end"),
              "target": {key: value for key, value in (facts.get("target") or {}).items()
                         if key in {"store_id", "sku_id", "lot_id"}}, "tables": {}, "table_coverage": {}}
    target_sku = result["target"].get("sku_id")
    remaining_chars = 140_000
    for table, rows in facts["tables"].items():
        if table not in selected:
            continue
        scoped_rows = [row for row in rows if table in {"products", "stores", "suppliers"}
                       or not target_sku or not row.get("sku_id") or row.get("sku_id") == target_sku]
        safe_rows = []
        for row in scoped_rows[:40]:
            safe = model_value(row, facts)
            encoded_len = len(json.dumps(safe, ensure_ascii=False))
            if encoded_len > remaining_chars:
                break
            safe_rows.append(safe)
            remaining_chars -= encoded_len
        result["tables"][table] = safe_rows
        result["table_coverage"][table] = {"available_rows": len(scoped_rows), "included_rows": len(safe_rows),
                                           "truncated": len(safe_rows) < len(scoped_rows)}
    return result


class ModelGateway:
    def __init__(self, config: ModelConfig, *, transport: httpx.BaseTransport | None = None,
                 timeout_seconds: float = 30, max_retries: int = 1):
        if isinstance(timeout_seconds, bool) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 120:
            raise ValueError("timeout_seconds 必须在 0 至 120 秒之间")
        if type(max_retries) is not int or not 0 <= max_retries <= 2:
            raise ValueError("max_retries 必须为 0 至 2")
        self.config, self.transport = config, transport
        self.timeout_seconds, self.max_retries = timeout_seconds, max_retries

    def redact(self, value: Any) -> Any:
        """Remove configured credentials if upstream text happens to echo one."""
        secrets = [p.api_key.get_secret_value() for p in self.config.providers.values()
                   if p.api_key.get_secret_value()]
        def clean(item):
            if isinstance(item, str):
                for secret in secrets:
                    item = item.replace(secret, "[REDACTED]")
                item = re.sub(r"data:image/[a-z0-9.+-]+;base64,[A-Za-z0-9+/]*={0,2}",
                              "[IMAGE_DATA_REDACTED]", item, flags=re.IGNORECASE)
                return visible_text(item)
            if isinstance(item, list):
                return [clean(v) for v in item]
            if isinstance(item, dict):
                return {str(k): clean(v) for k, v in item.items()
                        if str(k).lower() not in {"authorization", "api_key", "headers", "reasoning_content", "reasoning_details", "thinking"}}
            return item
        return clean(value)

    def _selected(self, capability: str):
        if capability not in {"text", "vision"}:
            raise ValueError("capability 仅支持 text 或 vision")
        provider = self.config.vision_provider if capability == "vision" else self.config.text_provider
        settings = self.config.providers.get(provider)
        model = (settings.vision_model if capability == "vision" else settings.model) if settings else ""
        if not settings or not settings.api_key.get_secret_value() or not model:
            raise ModelError("not_configured", "图片模型未配置" if capability == "vision" else "文本模型未配置")
        parsed = urlsplit(settings.base_url)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ModelError("invalid_configuration", "模型服务地址配置不合法")
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ModelError("invalid_configuration", "远程模型服务必须使用 HTTPS")
        base = settings.base_url.rstrip("/")
        endpoint = base if base.endswith("/chat/completions") else base + "/chat/completions"
        return provider, model, settings, endpoint

    def complete(self, messages: list[dict], *, capability: Literal["text", "vision"] = "text",
                 tools: list[dict] | None = None, response_schema: dict | None = None) -> ModelReply:
        provider, model, settings, endpoint = self._selected(capability)
        if not messages or len(messages) > 100 or any(not isinstance(m, dict) for m in messages):
            raise ValueError("messages 必须为非空消息列表")
        payload: dict = {"model": model, "messages": deepcopy(messages), "stream": False,
                         "max_tokens": 4096}
        if tools:
            payload.update(tools=deepcopy(tools), tool_choice="auto")
        if response_schema:
            # JSON mode is supported by DeepSeek/Qwen. MiniMax receives the same
            # schema in the prompt; local Pydantic validation remains mandatory.
            payload["messages"].insert(0, {"role": "system", "content":
                "Return one JSON object only, conforming to this JSON Schema: " +
                json.dumps(response_schema, ensure_ascii=False)})
            if provider in {"deepseek", "qwen"}:
                payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": "Bearer " + settings.api_key.get_secret_value(),
                   "Content-Type": "application/json"}
        started = time.monotonic()
        for attempt in range(1, self.max_retries + 2):
            try:
                with httpx.Client(transport=self.transport, timeout=self.timeout_seconds,
                                  follow_redirects=False, trust_env=False) as client:
                    with client.stream("POST", endpoint, headers=headers, json=payload) as response:
                        status = response.status_code
                        if not 200 <= status < 300:
                            retryable = status in {408, 429, 500, 502, 503, 504}
                            code = "authentication_failed" if status in {401, 403} else "rate_limited" if status == 429 else "upstream_error"
                            raise ModelError(code, "模型服务请求失败", retryable=retryable,
                                             attempts=attempt, http_status=status)
                        chunks, size = [], 0
                        for chunk in response.iter_bytes():
                            if time.monotonic() - started > self.timeout_seconds * (self.max_retries + 1):
                                raise ModelError("timeout", "模型请求超过总运行时限", attempts=attempt)
                            size += len(chunk)
                            if size > MAX_RESPONSE_BYTES:
                                raise ModelError("invalid_response", "模型响应超过大小限制", attempts=attempt)
                            chunks.append(chunk)
                        body = b"".join(chunks)
                return self._parse(body, provider, model, attempt, started)
            except httpx.TimeoutException:
                error = ModelError("timeout", "模型请求超时", retryable=True, attempts=attempt)
            except httpx.RequestError:
                error = ModelError("network_error", "无法连接模型服务", retryable=True, attempts=attempt)
            except ModelError as exc:
                error = exc
            if not error.retryable or attempt > self.max_retries:
                raise error from None
            time.sleep(min(0.2 * attempt, 0.5))
        raise AssertionError("unreachable")

    def _parse(self, body: bytes, provider: str, model: str, attempt: int, started: float) -> ModelReply:
        try:
            data = json.loads(body)
            if not isinstance(data, dict) or data.get("error"):
                raise ValueError()
            if data.get("base_resp", {}).get("status_code", 0) != 0:
                raise ModelError("upstream_error", "模型服务返回业务错误", attempts=attempt)
            choice = data["choices"][0]
            message = choice["message"]
            if not isinstance(message, dict) or message.get("role", "assistant") != "assistant":
                raise ValueError()
            reason = choice.get("finish_reason")
            if reason == "length":
                raise ModelError("truncated_response", "模型响应被长度限制截断", attempts=attempt)
            if reason in {"content_filter", "safety"} or message.get("refusal"):
                raise ModelError("model_refused", "模型未处理该输入", attempts=attempt)
            content = message.get("content") or ""
            calls = message.get("tool_calls") or []
            if not isinstance(content, str) or not isinstance(calls, list) or len(calls) > 16:
                raise ValueError()
            if not content.strip() and not calls:
                raise ModelError("empty_response", "模型未返回可用内容", attempts=attempt)
            if reason == "tool_calls" and not calls:
                raise ValueError()
            for call in calls:
                if not isinstance(call, dict) or call.get("type") != "function" or not isinstance(call.get("id"), str) or not call["id"]:
                    raise ValueError()
                function = call.get("function", {})
                if not isinstance(function.get("name"), str) or not isinstance(function.get("arguments"), str):
                    raise ValueError()
            if len({call["id"] for call in calls}) != len(calls):
                raise ValueError()
            usage = data.get("usage") or {}
            if not isinstance(usage, dict):
                raise ValueError()
            # Preserve assistant fields needed for multi-turn provider protocols.
            safe_message = {key: deepcopy(value) for key, value in message.items()
                            if key in {"role", "content", "tool_calls", "reasoning_content", "reasoning_details"}}
            safe_message["role"] = "assistant"
            visible = self.redact(content)
            if not visible.strip() and not calls:
                raise ModelError("empty_response", "模型未返回可用内容", attempts=attempt)
            return ModelReply(visible, calls, safe_message, provider, model,
                              reason or "stop", self.redact(usage),
                              int((time.monotonic() - started) * 1000), attempt)
        except ModelError:
            raise
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            raise ModelError("invalid_response", "模型响应格式不合法", attempts=attempt) from None


def gateway(config: ModelConfig, messages: list[dict], *, capability: Literal["text", "vision"] = "text",
            tools: list[dict] | None = None, response_schema: dict | None = None,
            transport: httpx.BaseTransport | None = None, timeout_seconds: float = 30,
            max_retries: int = 1) -> ModelReply:
    """One-shot convenience function; applications may instead reuse ModelGateway."""
    return ModelGateway(config, transport=transport, timeout_seconds=timeout_seconds,
                        max_retries=max_retries).complete(messages, capability=capability,
                                                          tools=tools, response_schema=response_schema)

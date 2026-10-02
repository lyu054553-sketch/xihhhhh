import { ApiError } from "./api-client.mjs";

export const AGENT_TYPES = Object.freeze(["slow_moving", "store_transfer", "near_expiry", "procurement_brake", "cashflow_simulation"]);
export const RUN_STATUSES = Object.freeze(["succeeded", "partial", "no_data", "needs_input", "awaiting_confirmation", "failed"]);
const ACTION_TYPES = ["pause_replenishment", "reduce_open_purchase_order", "transfer_stock", "markdown", "prioritize_sale", "review_data", "no_action"];
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const UNITS = { piece: "件", bag: "袋", bottle: "瓶", box: "箱", kg: "kg", day: "天", days: "天" };

export class ContractError extends ApiError {
  constructor(path, message, outcomeUnknown = false) {
    super(`接口契约不符：${path} ${message}`, {
      code: "CONTRACT_INVALID", outcomeUnknown, fieldErrors: [{ field: path, message }],
    });
    this.name = "ContractError";
  }
}

function requireValue(condition, path, message) {
  if (!condition) throw new ContractError(path, message);
}
function object(value, path) {
  requireValue(value !== null && typeof value === "object" && !Array.isArray(value) && [Object.prototype, null].includes(Object.getPrototypeOf(value)), path, "必须为 JSON 对象");
}
function string(value, path, allowEmpty = false) {
  requireValue(typeof value === "string" && (allowEmpty || value.trim().length > 0), path, "必须为字符串");
}
function array(value, path, check) {
  requireValue(Array.isArray(value), path, "必须为数组");
  value.forEach((item, index) => check?.(item, `${path}[${index}]`));
}
function strings(value, path) { array(value, path, string); }
function oneOf(value, allowed, path) { requireValue(allowed.includes(value), path, `必须为 ${allowed.join(" / ")}`); }
function fen(value, path) { requireValue(value === null || Number.isSafeInteger(value), path, "必须为整数分或 null"); }
function date(value, path) {
  string(value, path);
  requireValue(/^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value, path, "必须为有效的 YYYY-MM-DD 日期");
}
function timestamp(value, path) {
  string(value, path);
  requireValue(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})$/.test(value) && Number.isFinite(Date.parse(value)), path, "必须为带时区的 ISO 8601 时间");
  date(value.slice(0, 10), path);
}
function unique(values, path) { requireValue(new Set(values).size === values.length, path, "标识不得重复"); }

// Validate documented numeric conventions at every depth without inventing a details schema.
function jsonValues(value, path = "payload", key = "") {
  if (key.endsWith("_fen")) fen(value, path);
  if (/(?:^|_)qty$/.test(key)) requireValue(value === null || (typeof value === "number" && Number.isFinite(value)), path, "数量必须为数字或 null");
  if (value === null || typeof value === "string" || typeof value === "boolean") return;
  if (typeof value === "number") { requireValue(Number.isFinite(value), path, "必须为有限数字"); return; }
  if (Array.isArray(value)) { value.forEach((item, index) => jsonValues(item, `${path}[${index}]`)); return; }
  object(value, path);
  for (const [name, item] of Object.entries(value)) jsonValues(item, `${path}.${name}`, name);
}

function metric(value, path) {
  object(value, path);
  for (const key of ["key", "label", "unit"]) string(value[key], `${path}.${key}`);
  requireValue(value.value === null || ["string", "boolean"].includes(typeof value.value) || typeof value.value === "number" && Number.isFinite(value.value), `${path}.value`, "必须为有限数值、文本、布尔值或 null");
  requireValue(!["yuan", "cny", "rmb", "元", "人民币", "人民币元", "¥", "￥"].includes(value.unit.toLowerCase()), `${path}.unit`, "金额必须以 fen 返回，由展示层换算为元");
  if (value.key.endsWith("_fen") || value.unit === "fen") {
    requireValue(value.key.endsWith("_fen") && value.unit === "fen", path, "金额指标必须使用 _fen 字段名和 fen 单位");
    fen(value.value, `${path}.value`);
  }
  if (/(?:^|_)qty$/.test(value.key)) requireValue(value.value === null || (typeof value.value === "number" && Number.isFinite(value.value)), `${path}.value`, "数量指标必须为数字或 null");
  if (["ratio", "percent", "%"].includes(value.unit)) requireValue(value.value === null || (typeof value.value === "number" && value.value >= 0 && value.value <= 1), `${path}.value`, "比例必须在 0 到 1 之间");
}

function evidence(value, path) {
  object(value, path);
  for (const key of ["source", "record_id", "field", "as_of"]) string(value[key], `${path}.${key}`);
  if (value.as_of.includes("T")) timestamp(value.as_of, `${path}.as_of`);
  else date(value.as_of, `${path}.as_of`);
  requireValue(Object.hasOwn(value, "value"), `${path}.value`, "不可缺省；未知值使用 null");
  if (value.field.endsWith("_fen")) fen(value.value, `${path}.value`);
  if (/(?:^|_)qty$/.test(value.field)) requireValue(value.value === null || (typeof value.value === "number" && Number.isFinite(value.value)), `${path}.value`, "数量证据必须为数字或 null");
}

function adjustment(value, path) {
  object(value, path);
  oneOf(value.action_type, ACTION_TYPES.slice(0, 5), `${path}.action_type`);
  object(value.action_params, `${path}.action_params`);
  requireValue(["store_id", "source_store_id", "target_store_id", "sku_id", "po_id"].some((key) => typeof value.action_params[key] === "string" && value.action_params[key].trim()), path, "调整必须关联门店、SKU 或采购单");
  if (Object.hasOwn(value.action_params, "qty")) string(value.action_params.unit, `${path}.action_params.unit`);
}

function preview(value, path) {
  object(value, path);
  for (const key of ["scenario_id", "title"]) string(value[key], `${path}.${key}`);
  requireValue(Number.isSafeInteger(value.horizon_days) && value.horizon_days > 0, `${path}.horizon_days`, "必须为正整数天数");
  strings(value.store_ids, `${path}.store_ids`);
  strings(value.assumptions, `${path}.assumptions`);
  array(value.adjustments, `${path}.adjustments`, adjustment);
  requireValue(value.confirmation_required === true, `${path}.confirmation_required`, "待确认情景必须要求人工确认");
}

function recommendation(value, path, recordIds) {
  object(value, path);
  string(value.recommendation_id, `${path}.recommendation_id`);
  oneOf(value.action_type, ACTION_TYPES, `${path}.action_type`);
  object(value.action_params, `${path}.action_params`);
  string(value.rationale, `${path}.rationale`);
  strings(value.evidence_ids, `${path}.evidence_ids`);
  requireValue(value.evidence_ids.length > 0 && value.evidence_ids.every((id) => recordIds.has(id)), `${path}.evidence_ids`, "必须引用本结果项的证据记录");
  requireValue(typeof value.approval_required === "boolean", `${path}.approval_required`, "必须为布尔值");
  if (value.impact_estimate !== undefined && value.impact_estimate !== null) {
    const impact = value.impact_estimate;
    object(impact, `${path}.impact_estimate`);
    string(impact.kind, `${path}.impact_estimate.kind`);
    fen(impact.amount_fen, `${path}.impact_estimate.amount_fen`);
    strings(impact.assumptions, `${path}.impact_estimate.assumptions`);
    requireValue(impact.amount_fen === null || impact.assumptions.length > 0, `${path}.impact_estimate.assumptions`, "金额估算必须列出假设");
  }
}

function resultItem(value, path) {
  object(value, path);
  string(value.item_id, `${path}.item_id`);
  object(value.entity, `${path}.entity`);
  object(value.details, `${path}.details`);
  oneOf(value.priority, ["high", "medium", "low"], `${path}.priority`);
  array(value.metrics, `${path}.metrics`, metric);
  array(value.evidence, `${path}.evidence`, evidence);
  requireValue(value.evidence.length > 0, `${path}.evidence`, "每项结果至少需要一条证据");
  const recordIds = new Set(value.evidence.map((entry) => entry.record_id));
  array(value.recommendations, `${path}.recommendations`, (entry, entryPath) => recommendation(entry, entryPath, recordIds));
  unique(value.recommendations.map((entry) => entry.recommendation_id), `${path}.recommendations`);
}

export function buildRunRequest({ agentType, userInput, scope, params = {}, dataVersion, policyVersion, sessionId, requestId = globalThis.crypto.randomUUID() } = {}) {
  oneOf(agentType, AGENT_TYPES, "agent_type");
  requireValue(typeof requestId === "string" && UUID.test(requestId), "request_id", "必须为 UUID");
  string(dataVersion, "data_version");
  object(scope, "scope");
  date(scope.as_of, "scope.as_of");
  for (const key of ["store_ids", "sku_ids", "category_ids"]) if (scope[key] !== undefined) strings(scope[key], `scope.${key}`);
  object(params, "params");
  if (agentType === "cashflow_simulation") {
    oneOf(params.operation, ["preview", "simulate"], "params.operation");
    if (params.operation === "simulate") {
      string(params.scenario_id, "params.scenario_id");
      requireValue(params.confirmed === true, "params.confirmed", "开始模拟前必须人工确认");
      array(params.adjustments, "params.adjustments", adjustment);
    }
  }
  const result = { request_id: requestId, agent_type: agentType, scope, params, data_version: dataVersion };
  for (const [key, value] of [["user_input", userInput], ["policy_version", policyVersion], ["session_id", sessionId]]) {
    if (value !== undefined && value !== null) { string(value, key, key === "user_input"); result[key] = value; }
  }
  jsonValues(result, "request");
  return structuredClone(result);
}

export function validateRunResponse(payload, request) {
  try {
    object(payload, "response");
    jsonValues(payload, "response");
    for (const key of ["request_id", "run_id", "agent_type", "data_version", "policy_version"]) string(payload[key], key);
    for (const key of ["summary", "assistant_message"]) string(payload[key], key, true);
    oneOf(payload.agent_type, AGENT_TYPES, "agent_type");
    oneOf(payload.status, RUN_STATUSES, "status");
    requireValue(payload.session_id === null || typeof payload.session_id === "string" && payload.session_id.trim().length > 0, "session_id", "必须为会话 ID 或 null");
    for (const key of ["request_id", "agent_type", "data_version", "policy_version", "session_id"]) {
      if (request[key] !== undefined && request[key] !== null) requireValue(payload[key] === request[key], key, "与本次请求不一致，结果未采用");
    }
    timestamp(payload.created_at, "created_at");
    if (payload.completed_at !== null) timestamp(payload.completed_at, "completed_at");
    for (const key of ["missing_fields", "follow_up_questions"]) strings(payload[key], key);
    array(payload.warnings, "warnings", object);
    array(payload.steps, "steps", (step, path) => {
      object(step, path);
      for (const key of ["step_id", "name", "label", "message"]) string(step[key], `${path}.${key}`, key === "message");
      oneOf(step.status, ["succeeded", "skipped", "failed"], `${path}.status`);
    });
    unique(payload.steps.map((step) => step.step_id), "steps");
    array(payload.items, "items", resultItem);
    unique(payload.items.map((item) => item.item_id), "items");
    if (payload.error !== null) {
      object(payload.error, "error");
      for (const key of ["code", "message"]) string(payload.error[key], `error.${key}`);
      requireValue(typeof payload.error.retryable === "boolean", "error.retryable", "必须为布尔值");
      array(payload.error.field_errors, "error.field_errors");
    }
    if (payload.status === "failed") requireValue(payload.error !== null, "error", "失败状态必须提供错误信息");
    if (payload.status === "succeeded") requireValue(payload.error === null, "error", "成功状态不得携带错误");
    if (payload.status !== "needs_input") requireValue(payload.follow_up_questions.length === 0, "follow_up_questions", "仅 needs_input 状态可返回补充问题");
    if (payload.status === "awaiting_confirmation") {
      preview(payload.scenario_preview, "scenario_preview");
      requireValue(payload.items.length === 0, "items", "确认前不得返回模拟结果");
    } else requireValue(payload.scenario_preview === null, "scenario_preview", "仅待确认状态可返回情景卡");
    if (payload.status === "no_data") requireValue(payload.items.length === 0, "items", "无数据状态不得携带结果");
    if (request.agent_type === "cashflow_simulation" && request.params.operation === "preview") {
      requireValue(payload.items.length === 0 && !["succeeded", "partial"].includes(payload.status), "status", "预览阶段不得返回已计算结果");
    }
    return payload;
  } catch (error) {
    if (error instanceof ContractError) error.outcomeUnknown = true;
    throw error;
  }
}

export function validateDecisionResponse(payload, expected) {
  try {
    object(payload, "decision");
    for (const key of ["run_id", "item_id", "recommendation_id", "decision"]) {
      string(expected[key], `expected.${key}`);
      requireValue(payload[key] === expected[key], key, "与本次模拟决策不一致");
    }
    oneOf(payload.decision, ["approve", "reject"], "decision");
    requireValue(payload.decision_status === "recorded", "decision_status", "必须为 recorded");
    requireValue(payload.execution_mode === "simulation", "execution_mode", "必须为 simulation，不能声明真实业务执行");
    return payload;
  } catch (error) {
    if (error instanceof ContractError) error.outcomeUnknown = true;
    throw error;
  }
}

export function formatFen(value) {
  if (value === null || value === undefined) return "未知";
  fen(value, "amount_fen");
  const integer = BigInt(value), absolute = integer < 0n ? -integer : integer;
  return `${integer < 0n ? "-" : ""}¥${(absolute / 100n).toLocaleString("zh-CN")}.${String(absolute % 100n).padStart(2, "0")}`;
}

export function formatMetric(value) {
  metric(value, "metric");
  if (value.value === null) return "未知";
  if (value.unit === "fen") return formatFen(value.value);
  if (["ratio", "percent", "%"].includes(value.unit)) return new Intl.NumberFormat("zh-CN", { style: "percent", maximumFractionDigits: 2 }).format(value.value);
  const displayed = typeof value.value === "number" ? value.value.toLocaleString("zh-CN", { maximumFractionDigits: 6 }) : String(value.value);
  return `${displayed} ${UNITS[value.unit] || value.unit}`;
}

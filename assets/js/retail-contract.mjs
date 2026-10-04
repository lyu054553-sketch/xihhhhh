import { ApiError } from "./api-client.mjs";

export class RetailContractError extends ApiError {
  constructor(path, message, { input = false } = {}) {
    super(`${input ? "输入" : "接口响应"}不符合 v1.2 约定：${path} ${message}`, {
      code: input ? "invalid_input" : "contract_invalid",
      fieldErrors: [{ field: path, message }],
      outcomeUnknown: !input,
    });
    this.name = "RetailContractError";
  }
}

const unknown = "未接入／待补充";
const modules = ["transfer", "expiry-rescue", "procurement-brake"];
const fail = (path, message) => { throw new RetailContractError(path, message); };
const own = (value, key) => Object.hasOwn(value, key);

// FastAPI serializes workbench Decimal values as JSON strings. Accept only
// canonical decimal text at that display boundary, never empty strings or null.
function decimal(value, path, { money: isMoney = false } = {}) {
  if (typeof value !== "string") return value;
  const pattern = isMoney ? /^-?(?:0|[1-9]\d*)(?:\.\d{1,2})?$/ : /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/;
  if (!pattern.test(value)) fail(path, "应为规范十进制数值");
  const parsed = Number(value);
  number(parsed, path);
  return parsed;
}

function object(value, path) {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail(path, "应为对象");
  return value;
}
function array(value, path) {
  if (!Array.isArray(value)) fail(path, "应为数组");
  return value;
}
function text(value, path, { nullable = false, empty = false } = {}) {
  if (nullable && value === null) return value;
  if (typeof value !== "string" || (!empty && !value.trim())) fail(path, "应为文本");
  return value;
}
function number(value, path, { nullable = false, integer = false, min = -Infinity, max = Infinity } = {}) {
  if (nullable && value === null) return value;
  if (typeof value !== "number" || !Number.isFinite(value) || (integer && !Number.isSafeInteger(value)) || value < min || value > max) fail(path, "应为有效数值");
  return value;
}
function money(value, path, { nullable = true } = {}) {
  number(value, path, { nullable });
  if (value !== null && (Math.abs(value) > Number.MAX_SAFE_INTEGER / 100 || Math.abs(value * 100 - Math.round(value * 100)) > 1e-6)) fail(path, "应为最多两位小数的人民币元金额");
  return value;
}
function boolean(value, path) {
  if (typeof value !== "boolean") fail(path, "应为布尔值");
}
function date(value, path, { nullable = false } = {}) {
  if (nullable && value === null) return;
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value) || !Number.isFinite(Date.parse(value)) || new Date(value).toISOString().slice(0, 10) !== value) fail(path, "应为有效日期");
}
function strings(value, path) {
  array(value, path).forEach((item, index) => text(item, `${path}[${index}]`, { empty: true }));
}
function numericFields(value, fields, path, validator = number) {
  for (const key of fields) if (own(value, key)) validator(value[key], `${path}.${key}`, { nullable: true });
}
function source(value, { asOf = false } = {}) {
  boolean(value.is_demo, "is_demo");
  text(value.source, "source");
  if (asOf) date(value.as_of_date, "as_of_date", { nullable: !value.is_demo });
}
function metadata(value) {
  object(value, "metadata");
  strings(value.missing, "metadata.missing");
  strings(value.assumptions, "metadata.assumptions");
  if (own(value, "currency") && value.currency !== "CNY") fail("metadata.currency", "应为 CNY");
  if (value.units && value.units.money !== "CNY") fail("metadata.units.money", "应为 CNY（人民币元）");
}

// v1.2 amounts are already yuan. Formatting never rescales money or percentages.
export function formatYuan(value) {
  if (value == null) return unknown;
  value = decimal(value, "amount", { money: true });
  money(value, "amount");
  return `¥${value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
export function formatNumber(value, { unit = "", maximumFractionDigits = 2 } = {}) {
  if (value == null) return unknown;
  value = decimal(value, "value");
  number(value, "value");
  return `${value.toLocaleString("zh-CN", { maximumFractionDigits })}${unit ? ` ${unit}` : ""}`;
}
export function formatPercent(value) {
  return value == null ? unknown : `${formatNumber(value)}%`;
}

export function validateOverview(payload, { storeId, period } = {}) {
  object(payload, "overview");
  source(payload, { asOf: true });
  object(payload.scope, "scope");
  text(payload.scope.store_id, "scope.store_id");
  number(payload.scope.store_count, "scope.store_count", { integer: true, min: 0 });
  if (![7, 30].includes(payload.scope.period)) fail("scope.period", "仅支持 7 或 30 天");
  if (storeId != null && payload.scope.store_id !== storeId) fail("scope.store_id", "与请求门店不一致");
  if (period != null && payload.scope.period !== period) fail("scope.period", "与请求周期不一致");
  for (const key of ["account", "sales", "inventory", "purchase_commitments", "pending_approvals"]) object(payload[key], key);
  money(payload.account.balance, "account.balance");
  money(payload.inventory.cost, "inventory.cost");
  money(payload.inventory.risk_cost, "inventory.risk_cost");
  money(payload.purchase_commitments.amount, "purchase_commitments.amount");
  numericFields(payload.account, ["opening_balance", "cash_in", "cash_out"], "account", money);
  numericFields(payload.sales, ["amount", "gross_profit", "amount_7d"], "sales", money);
  numericFields(payload.sales, ["gross_margin_pct", "gross_margin_7d_pct", "change_pct"], "sales");
  numericFields(payload.inventory, ["risk_count", "risk_store_count", "stockout_risk_count", "turnover_days", "sku_count", "store_sku_count"], "inventory");
  numericFields(payload.pending_approvals, ["amount", "known_amount"], "pending_approvals", money);
  array(payload.stores, "stores").forEach((store, index) => {
    const path = `stores[${index}]`;
    object(store, path);
    text(store.store_id, `${path}.store_id`);
    text(store.store_name, `${path}.store_name`);
    numericFields(store, ["sales", "gross_profit", "inventory_cost", "risk_cost"], path, money);
    numericFields(store, ["gross_margin_pct", "turnover_days", "risk_count"], path);
    strings(store.risk_types, `${path}.risk_types`);
    array(store.risk_items, `${path}.risk_items`).forEach((item, itemIndex) => {
      object(item, `${path}.risk_items[${itemIndex}]`);
      money(item.inventory_cost, `${path}.risk_items[${itemIndex}].inventory_cost`);
    });
  });
  array(payload.trend, "trend").forEach((row, index) => {
    object(row, `trend[${index}]`);
    date(row.date, `trend[${index}].date`);
    numericFields(row, ["sales", "gross_profit", "cash_balance", "cash_in", "purchase_outflow", "operating_outflow"], `trend[${index}]`, money);
  });
  metadata(payload.metadata);
  return payload;
}

function risk(value, path) {
  object(value, path);
  number(value.id, `${path}.id`, { integer: true, min: 1 });
  for (const key of ["sku", "product", "store", "store_id"]) text(value[key], `${path}.${key}`);
  numericFields(value, ["inventory_qty", "sales_30", "days_to_sell"], path);
  // Risk rows store unit_cost as decimal text in SQLite; retail aggregate
  // responses use JSON numbers. Validate each endpoint's real wire format.
  if (own(value, "unit_cost")) money(decimal(value.unit_cost, `${path}.unit_cost`, { money: true }), `${path}.unit_cost`);
  if (own(value, "missing_fields")) strings(value.missing_fields, `${path}.missing_fields`);
}
export function validateRisks(payload) {
  object(payload, "risks");
  array(payload.items, "items").forEach((item, index) => risk(item, `items[${index}]`));
  number(payload.total, "total", { integer: true, min: 0 });
  return payload;
}
export function validateRiskDetail(payload, { riskId } = {}) {
  object(payload, "risk_detail");
  risk(payload.risk, "risk");
  if (riskId != null && payload.risk.id !== riskId) fail("risk.id", "与请求商品风险不一致");
  object(payload.comparison, "comparison");
  object(payload.diagnosis, "diagnosis");
  object(payload.evidence, "evidence");
  strings(payload.evidence.missing_fields, "evidence.missing_fields");
  array(payload.facts, "facts");
  array(payload.factors, "factors");
  return payload;
}

export function validateCalculation(payload) {
  object(payload, "calculation");
  boolean(payload.valid, "calculation.valid");
  array(payload.errors, "calculation.errors");
  return payload;
}
function draft(value) {
  object(value, "draft");
  text(value.status, "draft.status");
  number(value.version, "draft.version", { integer: true, min: 0 });
}
export function validateWorkbench(payload, { moduleType, riskId } = {}) {
  object(payload, "workbench");
  if (!modules.includes(payload.module_type)) fail("module_type", "不是支持的工作台");
  if (moduleType != null && payload.module_type !== moduleType) fail("module_type", "与请求工作台不一致");
  text(payload.mode, "mode");
  text(payload.snapshot_id, "snapshot_id");
  risk(payload.risk, "risk");
  if (riskId != null && payload.risk.id !== riskId) fail("risk.id", "与请求商品风险不一致");
  array(payload.items, "items").forEach((item, index) => risk(item, `items[${index}]`));
  object(payload.input, "input");
  if (payload.calculation !== null) validateCalculation(payload.calculation);
  draft(payload.draft);
  if (payload.proposal !== null) validateProposal(payload.proposal);
  array(payload.tasks, "tasks").forEach((item) => validateExecutionTask(item));
  return payload;
}
export function validateWorkbenchCalculation(payload) {
  object(payload, "workbench_calculation");
  object(payload.input, "input");
  validateCalculation(payload.calculation);
  draft(payload.draft);
  return payload;
}
export function validateWorkbenchDraft(payload, { moduleType, riskId } = {}) {
  object(payload, 'workbench_draft');
  draft(payload.draft);
  const value = payload.draft;
  text(value.id, 'draft.id');
  if (value.module_type !== moduleType || value.risk_id !== riskId) fail('draft', '与当前工作台或商品不一致');
  object(value.input, 'draft.input');
  if (value.input.risk_id !== riskId) fail('draft.input.risk_id', '与保存商品不一致');
  if (value.status !== 'needs_recalculation') fail('draft.status', '应为输入已保存、待重新计算');
  return payload;
}
export function validateWorkbenchSave(payload) {
  object(payload, "workbench_save");
  validateProposal(payload.proposal);
  validateCalculation(payload.calculation);
  if (!payload.calculation.valid) fail("calculation.valid", "无效测算不能保存为方案");
  return payload;
}

export function validateSimulationOptions(payload) {
  object(payload, "simulation_options");
  source(payload, { asOf: true });
  const ids = new Set();
  array(payload.stores, "stores").forEach((store, index) => {
    object(store, `stores[${index}]`);
    text(store.id, `stores[${index}].id`);
    text(store.name, `stores[${index}].name`);
    if (ids.has(store.id)) fail(`stores[${index}].id`, "不能重复");
    ids.add(store.id);
  });
  strings(payload.categories, "categories");
  return payload;
}
export function buildSimulationRequest({ horizon_days, reduction_pct, store_id = "all", category = null, request_text = "" }, options) {
  try {
    number(horizon_days, "horizon_days", { integer: true, min: 1, max: 90 });
    number(reduction_pct, "reduction_pct", { min: 0, max: 100 });
    text(store_id, "store_id");
    text(category, "category", { nullable: true });
    text(request_text, "request_text", { empty: true });
    if (request_text.length > 2000) fail("request_text", "不能超过 2000 字符");
    if (options) {
      validateSimulationOptions(options);
      if (store_id !== "all" && !options.stores.some((store) => store.id === store_id)) fail("store_id", "应来自当前门店列表");
      if (category !== null && !options.categories.includes(category)) fail("category", "应来自当前品类列表");
    }
  } catch (error) {
    if (!(error instanceof RetailContractError)) throw error;
    throw new RetailContractError(error.fieldErrors[0].field, error.fieldErrors[0].message, { input: true });
  }
  return { horizon_days, reduction_pct, store_id, category, request_text };
}
export function validateSimulation(payload, request) {
  object(payload, "simulation");
  if (!["completed", "unavailable"].includes(payload.status)) fail("status", "应为 completed 或 unavailable");
  source(payload);
  object(payload.scenario, "scenario");
  // The unavailable response uses Pydantic's Decimal JSON serializer, whereas
  // completed simulations return numbers. Keep this transport exception local.
  const reduction = payload.status === "unavailable" ? decimal(payload.scenario.reduction_pct, "scenario.reduction_pct") : payload.scenario.reduction_pct;
  for (const key of ["horizon_days", "reduction_pct", "store_id", "category", "request_text"]) {
    const returned = key === "reduction_pct" ? reduction : payload.scenario[key];
    if (request && returned !== request[key]) fail(`scenario.${key}`, "与已确认的请求不一致");
  }
  number(payload.scenario.horizon_days, "scenario.horizon_days", { integer: true, min: 1, max: 90 });
  number(reduction, "scenario.reduction_pct", { min: 0, max: 100 });
  text(payload.scenario.store_id, "scenario.store_id");
  text(payload.scenario.category, "scenario.category", { nullable: true });
  metadata(payload.metadata);
  array(payload.weekly, "weekly");
  array(payload.risks, "risks");
  if (payload.status === "unavailable") {
    if (payload.metrics !== null || payload.weekly.length || payload.risks.length) fail("metrics", "不可用的模拟应保留空结果");
    return payload;
  }
  object(payload.metrics, "metrics");
  for (const key of ["purchase_outflow", "ending_inventory_cost", "stockout_risk_count"]) {
    const metric = object(payload.metrics[key], `metrics.${key}`);
    for (const side of ["baseline", "scenario", "delta"]) {
      if (key === "stockout_risk_count") number(metric[side], `metrics.${key}.${side}`, { integer: true, min: side === "delta" ? -Infinity : 0 });
      else money(metric[side], `metrics.${key}.${side}`, { nullable: false });
    }
  }
  payload.weekly.forEach((row, index) => {
    object(row, `weekly[${index}]`);
    text(row.label, `weekly[${index}].label`);
    date(row.start_date, `weekly[${index}].start_date`);
    date(row.end_date, `weekly[${index}].end_date`);
    money(row.baseline, `weekly[${index}].baseline`, { nullable: false });
    money(row.scenario, `weekly[${index}].scenario`, { nullable: false });
  });
  payload.risks.forEach((row, index) => {
    const path = `risks[${index}]`;
    object(row, path);
    for (const key of ["sku", "product", "store_id", "store_name", "risk_level"]) text(row[key], `${path}.${key}`);
    numericFields(row, ["baseline_days", "scenario_days", "safety_days", "shortage_qty"], path);
    boolean(row.is_new_risk, `${path}.is_new_risk`);
  });
  return payload;
}

export function validateProposal(payload, { proposalId } = {}) {
  object(payload, "proposal");
  text(payload.id, "proposal.id");
  if (proposalId != null && payload.id !== proposalId) fail("proposal.id", "与请求方案不一致");
  text(payload.status, "proposal.status");
  number(payload.current_version, "proposal.current_version", { integer: true, min: 1 });
  if (payload.version != null) {
    object(payload.version, "proposal.version");
    if (payload.version.version !== payload.current_version) fail("proposal.version.version", "与当前方案版本不一致");
    text(payload.version.status, "proposal.version.status");
    object(payload.version.payload, "proposal.version.payload");
  }
  return payload;
}
export function validateProposalList(payload) {
  object(payload, "proposals");
  array(payload.items, "items").forEach((item) => validateProposal(item));
  return payload;
}
function mutation(payload, { proposalId, version } = {}) {
  object(payload, "result");
  text(payload.id, "id");
  text(payload.proposal_id, "proposal_id");
  number(payload.proposal_version, "proposal_version", { integer: true, min: 1 });
  if (proposalId != null && payload.proposal_id !== proposalId) fail("proposal_id", "与请求方案不一致");
  if (version != null && payload.proposal_version !== version) fail("proposal_version", "与用户确认的方案版本不一致");
}
export function validateApproval(payload, expected = {}) {
  mutation(payload, expected);
  if (payload.status !== "approved") fail("status", "应为 approved");
  return payload;
}
export function validateExecutionTask(payload, expected = {}) {
  mutation(payload, expected);
  text(payload.status, "status");
  return payload;
}
export function validateTaskList(payload) {
  object(payload, "execution_tasks");
  array(payload.items, "items").forEach((item) => validateExecutionTask(item));
  return payload;
}

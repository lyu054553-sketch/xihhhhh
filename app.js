import { createApiClient } from "./assets/js/api-client.mjs";
import { createRequestState } from "./assets/js/request-state.mjs";
import { AGENT_TYPES, buildRunRequest, validateRunResponse, validateDecisionResponse, formatFen, formatMetric } from "./assets/js/agent-contract.mjs";
import { AGENT_CONFIG, initialValues, paramsFromValues } from "./assets/js/agent-config.mjs";
import { validateManifest, sampleDownloadTarget } from "./assets/js/dataset.mjs";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
const apiBase = location.protocol === "file:" ? null : $('meta[name="api-base"]').content;
const api = createApiClient({ baseUrl: apiBase, timeoutMs: 60000 });
const requests = createRequestState();
const state = { manifest: null, manifestError: null, agents: new Map(), active: "slow_moving", page: "agent", connected: false };
const STATUS = {
  succeeded: ["分析完成", "is-success"], partial: ["部分结果 · 请核对告警", "is-warning"],
  no_data: ["当前范围没有数据", ""], needs_input: ["需要补充或确认输入", "is-warning"],
  awaiting_confirmation: ["情景待确认 · 尚未计算", "is-warning"], failed: ["本次运行失败", "is-error"],
};
const ACTIONS = { pause_replenishment: "暂停补货", reduce_open_purchase_order: "减少未收货采购", transfer_stock: "门店调拨", markdown: "促销调价", prioritize_sale: "优先销售", review_data: "复核数据", no_action: "保持观察" };
const LABELS = {
  avg_daily_sales_qty: "日均净销量", days_since_last_sale: "距最近销售天数", days_of_supply: "库存覆盖天数",
  target_stock_qty: "目标库存", excess_qty: "超额库存", excess_value_at_cost_fen: "超额库存成本",
  source_available_qty: "调出店可用库存", target_available_qty: "接收店可用库存", recommended_transfer_qty: "建议调拨量",
  source_after_qty: "调出后库存", target_after_qty: "调入后库存", lot_id: "批次", expiry_date: "到期日期",
  days_to_expiry: "距到期天数", qty: "数量", unit: "计量单位", expected_sales_before_expiry_qty: "到期前预计销量",
  risk_qty: "风险数量", risk_value_at_cost_fen: "成本风险敞口", open_qty: "未收货采购量",
  projected_stock_qty: "预计库存", recommended_order_qty: "建议采购量", suggested_reduction_qty: "建议减少量",
  stockout_risk: "缺货风险", case_pack_adjusted_qty: "整箱调整量",
  baseline_inventory_capital_fen: "基线库存资金占用", scenario_inventory_capital_fen: "方案库存资金占用",
  baseline_purchase_commitment_fen: "基线采购承诺", scenario_purchase_commitment_fen: "方案采购承诺",
  estimated_avoided_purchase_commitment_fen: "预计减少采购承诺", stockout_risks: "各门店缺货风险",
  inventory_capital_series: "库存资金占用趋势", baseline_capital_fen: "基线库存资金", scenario_capital_fen: "方案库存资金",
  date: "日期", store_id: "门店编号", sku_id: "商品编号", source_store_id: "调出店编号", target_store_id: "接收店编号",
  po_id: "采购单", reduction_qty: "减少数量", transfer_qty: "调拨数量", price_fen: "价格", sale_price_fen: "销售价格",
  markdown_price_fen: "促销价格", unit_cost_fen: "单位成本", on_hand_qty: "实物库存", reserved_qty: "已预留库存",
  net_sold_qty: "净销量", min_display_qty: "最低陈列量", risk_level: "风险等级", coverage_days: "覆盖天数",
  as_of: "分析基准日", policy_version: "规则版本", data_version: "数据版本",
};
const labelFor = (key) => LABELS[key] || key;

function toast(message) {
  const target = $("#toast");
  clearTimeout(toast.timer);
  target.textContent = message;
  target.hidden = false;
  toast.timer = setTimeout(() => { target.hidden = true; }, 4200);
}

function createAgent(type) {
  return {
    values: initialValues(state.manifest, type), revision: 0, pending: false, controller: null,
    sessionId: type === "cashflow_simulation" ? crypto.randomUUID() : null,
    run: null, request: null, error: null, edited: false, decisions: new Map(),
  };
}

function renderNavigation() {
  $$("#app-nav [data-agent]").forEach((button) => {
    const selected = state.page === "agent" && button.dataset.agent === state.active;
    if (selected) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
    button.classList.toggle("is-running", Boolean(state.agents.get(button.dataset.agent)?.pending));
  });
  const data = $('#app-nav [data-page="data"]');
  if (state.page === "data") data.setAttribute("aria-current", "page"); else data.removeAttribute("aria-current");
}

function renderConnection() {
  const target = $("#connection-status");
  if (state.manifestError) {
    target.className = "status-panel is-error";
    target.innerHTML = `<strong>合成数据包读取失败</strong><p>${escapeHtml(state.manifestError.message)}</p><button type="button" class="secondary-button" data-action="reload-manifest">重新读取</button>`;
    return;
  }
  target.className = "status-panel";
  target.innerHTML = state.manifest
    ? `<strong>合成零食演示 · ${escapeHtml(state.manifest.data_version)}</strong><p>${state.connected ? "已收到接口响应；模型使用情况以本次返回步骤为准。" : "输入包已就绪，等待 v0.3 服务运行。"} 所有金额均为模拟口径，不代表银行余额或真实收益。</p>`
    : "<strong>正在读取合成数据包…</strong>";
}

function selection(name, label, options, selected = []) {
  return `<label class="field"><span>${escapeHtml(label)}</span><select name="${name}" multiple size="3">${options.map(([value, text]) => `<option value="${escapeHtml(value)}" ${selected.includes(value) ? "selected" : ""}>${escapeHtml(text)}</option>`).join("")}</select><small>可多选；全部取消表示不按此项筛选。</small></label>`;
}

function renderForm(type) {
  const agent = state.agents.get(type), config = AGENT_CONFIG[type], values = agent.values;
  const scopes = state.manifest.scope_options;
  const stores = scopes.stores.map((store) => [store.store_id, `${store.store_name} · ${store.store_id}`]);
  const skus = scopes.skus.map((sku) => [sku.sku_id, `${sku.sku_name} · ${sku.unit}`]);
  const categories = scopes.categories.map((category) => [category.category_id, category.category_name]);
  const fields = config.fields.map((field) => {
    if (field.type === "stores") return selection(field.key, field.label, stores, values[field.key]);
    if (field.type === "checkbox") return `<label class="field checkbox-field"><input type="checkbox" name="${field.key}" ${values[field.key] ? "checked" : ""}><span>${escapeHtml(field.label)}</span></label>`;
    return `<label class="field"><span>${escapeHtml(field.label)}</span><input name="${field.key}" type="number" required min="${field.min}" step="${field.step || 1}" value="${escapeHtml(values[field.key])}"></label>`;
  }).join("");
  $("#agent-form").innerHTML = `<fieldset class="form-section" ${agent.pending ? "disabled" : ""}>
    <legend>分析范围</legend><div class="form-grid">
      <label class="field"><span>分析基准日期</span><input name="as_of" type="date" required value="${escapeHtml(values.as_of)}"></label>
      <label class="field"><span>数据版本</span><input name="data_version" required value="${escapeHtml(values.data_version)}" autocomplete="off"></label>
      <label class="field"><span>规则版本</span><input name="policy_version" required value="${escapeHtml(values.policy_version)}" autocomplete="off"></label>
      ${selection("store_ids", "门店", stores, values.store_ids)}${selection("sku_ids", "商品", skus, values.sku_ids)}${selection("category_ids", "品类", categories, values.category_ids)}
    </div></fieldset>
    <fieldset class="form-section" ${agent.pending ? "disabled" : ""}><legend>${type === "cashflow_simulation" ? "整理模拟情景" : "分析条件"}</legend><div class="form-grid">${fields}
      <label class="field field-wide"><span>${type === "cashflow_simulation" ? "想调整什么？" : "补充说明（可选）"}</span><textarea name="user_input" rows="3" ${type === "cashflow_simulation" ? "required" : ""} placeholder="${escapeHtml(config.example)}">${escapeHtml(values.user_input)}</textarea></label>
    </div><button type="button" class="secondary-button" data-action="example">填入合成示例问题</button><p class="form-hint">结构化条件优先；缺项、冲突及可行性由后端校验。修改输入后，旧结果和情景确认立即失效。</p></fieldset>
    <div class="form-actions"><button type="submit" class="primary-button" ${agent.pending ? "disabled" : ""}>${type === "cashflow_simulation" ? "整理情景，待确认后计算" : "运行分析"}</button>${agent.pending ? '<button type="button" class="secondary-button" data-action="cancel">取消等待</button>' : ""}</div>`;
}

function readValues(form) {
  const values = {};
  for (const input of [...form.elements]) {
    if (!input.name) continue;
    values[input.name] = input.type === "checkbox" ? input.checked : input.multiple ? [...input.selectedOptions].map((option) => option.value) : input.value;
  }
  return values;
}

function editInput() {
  const type = state.active, agent = state.agents.get(type);
  if (!agent || agent.pending) return;
  const values = readValues($("#agent-form"));
  if (JSON.stringify(values) === JSON.stringify(agent.values)) return;
  const resetSession = ["data_version", "policy_version", "as_of"].some((key) => values[key] !== agent.values[key]);
  agent.values = values;
  agent.revision++;
  agent.run = null; agent.error = null; agent.request = null; agent.edited = true;
  agent.decisions.clear();
  if (resetSession && type === "cashflow_simulation") agent.sessionId = crypto.randomUUID();
  requests.invalidate(type);
  renderOutput(type);
}

function errorMarkup(error) {
  const message = error?.message || "请求未完成";
  const fields = error?.fieldErrors || error?.field_errors || [];
  const fieldMessages = fields.map((field) => {
    if (!field || typeof field !== "object") return String(field);
    const path = field.field || field.path || (Array.isArray(field.loc) ? field.loc.join(".") : "输入");
    return `${path}：${field.message || field.msg || JSON.stringify(field)}`;
  });
  return `<p>${escapeHtml(message)}</p>${error?.code ? `<p class="error-code">错误编号：${escapeHtml(error.code)}</p>` : ""}${fieldMessages.length ? `<ul class="warning-list">${fieldMessages.map((message) => `<li>${escapeHtml(message)}</li>`).join("")}</ul>` : ""}${error?.outcomeUnknown ? "<p>等待已结束，但服务端可能仍在处理。请保留请求编号，与后端核对后再重新提交。</p>" : ""}`;
}

function runMeta(agent) {
  const run = agent.run, request = agent.request;
  if (!request) return "";
  return `<details class="request-details"><summary>请求、版本与复现信息</summary><dl class="details-grid"><div><dt>请求编号</dt><dd>${escapeHtml(request.request_id)}</dd></div>${run ? `<div><dt>运行编号</dt><dd>${escapeHtml(run.run_id)}</dd></div>` : ""}<div><dt>数据版本</dt><dd>${escapeHtml(run?.data_version || request.data_version)}</dd></div><div><dt>规则版本</dt><dd>${escapeHtml(run?.policy_version || request.policy_version)}</dd></div><div><dt>分析基准</dt><dd>${escapeHtml(request.scope.as_of)}</dd></div></dl><details><summary>结构化请求</summary><pre>${escapeHtml(JSON.stringify(request, null, 2))}</pre></details></details>`;
}

function detailValue(value, key = "") {
  if (value === null || value === undefined) return "未知";
  if (key.endsWith("_fen")) return escapeHtml(formatFen(value));
  if (Array.isArray(value)) {
    if (!value.length) return '<span class="muted">未提供条目</span>';
    return `<ul class="detail-list">${value.map((item) => `<li>${detailValue(item)}</li>`).join("")}</ul>`;
  }
  if (typeof value === "object") return detailsMarkup(value);
  if (typeof value === "boolean") return value ? "是" : "否";
  return escapeHtml(value);
}

function detailsMarkup(details) {
  return `<dl class="details-grid">${Object.entries(details || {}).map(([key, value]) => `<div><dt>${escapeHtml(labelFor(key))}</dt><dd>${detailValue(value, key)}</dd></div>`).join("")}</dl>`;
}

function renderSteps(steps) {
  return `<section class="run-steps"><h2>本次运行过程</h2>${steps.length ? `<ol class="step-list">${steps.map((step) => `<li class="step-${step.status}"><span class="badge">${{succeeded: "完成", skipped: "跳过", failed: "失败"}[step.status]}</span><div><strong>${escapeHtml(step.label)}</strong><p>${escapeHtml(step.message)}</p></div></li>`).join("")}</ol>` : '<p class="muted">本次响应未提供步骤记录。</p>'}<p class="form-hint">这是服务返回的已发生步骤；等待期间不展示推测进度。</p></section>`;
}

function renderWarnings(run) {
  const entries = [
    ...(run.warnings || []).map((warning) => typeof warning.message === "string" ? `${warning.code ? `[${warning.code}] ` : ""}${warning.message}` : JSON.stringify(warning)),
    ...(run.missing_fields || []).map((field) => `缺少：${labelFor(field)}`),
  ];
  return entries.length ? `<section class="status-panel is-warning"><h2>数据与口径提醒</h2><ul class="warning-list">${entries.map((value) => `<li>${escapeHtml(value)}</li>`).join("")}</ul></section>` : "";
}

function decisionKey(runId, itemId, recommendationId) {
  return JSON.stringify([runId, itemId, recommendationId]);
}

function recommendationMarkup(run, item, recommendation, agent) {
  const key = decisionKey(run.run_id, item.item_id, recommendation.recommendation_id);
  const record = agent.decisions.get(key);
  const impact = recommendation.impact_estimate;
  const disabled = Boolean(record?.pending || record?.response);
  return `<section class="recommendation" data-recommendation-id="${escapeHtml(recommendation.recommendation_id)}"><h3>${escapeHtml(ACTIONS[recommendation.action_type] || recommendation.action_type)}</h3><p>${escapeHtml(recommendation.rationale)}</p>
    ${impact ? `<div class="impact-estimate"><strong>${impact.amount_fen == null ? "影响金额待补充" : `估算金额：${escapeHtml(formatFen(impact.amount_fen))}`}</strong><span>周期 ${escapeHtml(impact.period_days ?? "未知")} 天</span><p>${escapeHtml(({ avoid_future_purchase: "预计减少未来采购支出，不代表银行余额增加", inventory_reallocation: "库存配置改善，不代表现金到账" })[impact.kind] || "估算含义以本次假设和口径为准")}</p><ul class="assumptions">${(impact.assumptions || []).map((text) => `<li>${escapeHtml(text)}</li>`).join("")}</ul></div>` : ""}
    <details><summary>动作参数与引用证据</summary>${detailsMarkup(recommendation.action_params)}<p>证据记录：${escapeHtml((recommendation.evidence_ids || []).join("、") || "未提供")}</p></details>
    <label class="field decision-note"><span>模拟确认说明（可选）</span><input data-decision-note="${escapeHtml(key)}" value="${escapeHtml(record?.note || "")}" ${disabled ? "disabled" : ""}></label>
    <div class="decision-actions"><button class="primary-button" type="button" data-decision="approve" data-item-id="${escapeHtml(item.item_id)}" data-recommendation="${escapeHtml(recommendation.recommendation_id)}" ${disabled ? "disabled" : ""}>模拟确认</button><button class="secondary-button" type="button" data-decision="reject" data-item-id="${escapeHtml(item.item_id)}" data-recommendation="${escapeHtml(recommendation.recommendation_id)}" ${disabled ? "disabled" : ""}>模拟拒绝</button></div>
    <div class="decision-status" role="status">${record?.pending ? "正在记录模拟决策…" : record?.response ? `已记录：${record.response.decision === "approve" ? "模拟确认" : "模拟拒绝"}。未修改库存、采购或收银数据。` : record?.error ? errorMarkup(record.error) : "仅记录演示决策，不执行真实业务动作。"}</div></section>`;
}

function itemMarkup(run, item, agent) {
  const entity = item.entity;
  const title = [entity.store_name, entity.sku_name].filter(Boolean).join(" · ") || entity.id || "分析结果";
  return `<article class="result-card" data-item-id="${escapeHtml(item.item_id)}"><header class="result-header"><h2>${escapeHtml(title)}</h2><span class="badge">${{high:"高",medium:"中",low:"低"}[item.priority]}优先级</span></header>
    <div class="metric-grid">${item.metrics.map((metric) => `<div class="metric"><span>${escapeHtml(metric.label)}</span><strong class="value">${escapeHtml(formatMetric(metric))}</strong></div>`).join("")}</div>
    <details class="result-details"><summary>结果明细</summary>${detailsMarkup(item.details)}</details>
    <details open class="evidence-details"><summary>支撑证据（${item.evidence.length}）</summary><ul class="evidence-list">${item.evidence.map((evidence) => `<li><strong>${escapeHtml(labelFor(evidence.field))}</strong><span>${detailValue(evidence.value, evidence.field)}</span><small>${escapeHtml(evidence.source)} · ${escapeHtml(evidence.record_id)} · ${escapeHtml(evidence.as_of)}</small></li>`).join("")}</ul></details>
    ${item.recommendations.map((recommendation) => recommendationMarkup(run, item, recommendation, agent)).join("")}
    </article>`;
}

function scenarioMarkup(preview) {
  return `<section class="scenario-card"><span class="badge">待确认情景 · 尚未计算</span><h2>${escapeHtml(preview.title)}</h2><p>模拟 ${preview.horizon_days} 天；门店：${escapeHtml(preview.store_ids.join("、"))}</p><ul class="scenario-adjustments">${preview.adjustments.map((adjustment) => `<li><h3>${escapeHtml(ACTIONS[adjustment.action_type] || adjustment.action_type)}</h3>${detailsMarkup(adjustment.action_params)}</li>`).join("")}</ul><h3>本次假设</h3><ul class="assumptions">${preview.assumptions.map((assumption) => `<li>${escapeHtml(assumption)}</li>`).join("")}</ul><p>确认仅启动模拟计算，不批准或执行采购、调拨及促销。</p><div class="scenario-actions"><button type="button" class="primary-button" data-action="simulate">确认并开始模拟</button><button type="button" class="secondary-button" data-action="revise">修改情景</button></div></section>`;
}

function renderOutput(type) {
  if (state.page !== "agent" || state.active !== type) return;
  const agent = state.agents.get(type), status = $("#run-status"), output = $("#run-output");
  if (agent.pending) {
    status.className = "status-panel is-loading";
    status.innerHTML = "<strong>请求处理中…</strong><p>完成后展示服务返回的查询、计算和模型步骤。取消等待不会撤销服务端运行。</p>";
    output.innerHTML = runMeta(agent); return;
  }
  if (agent.error) {
    status.className = "status-panel is-error";
    status.innerHTML = `<strong>请求未取得可用结果</strong>${errorMarkup(agent.error)}${agent.error.retryable !== false ? '<button type="button" class="secondary-button" data-action="retry">重新提交请求</button>' : ""}`;
    output.innerHTML = runMeta(agent); return;
  }
  if (!agent.run) {
    status.className = "status-panel";
    status.innerHTML = `<strong>${agent.edited ? "输入已改变，请重新运行" : "准备就绪"}</strong><p>${type === "cashflow_simulation" ? "先整理情景并人工确认；确认前不展示模拟结果。" : "结果由后端实际计算并返回，当前未生成分析结论。"}</p>`;
    output.innerHTML = ""; return;
  }
  const run = agent.run, [label, tone] = STATUS[run.status];
  status.className = `status-panel ${tone}`;
  status.innerHTML = `<strong>${label}</strong><p>${escapeHtml(run.summary)}</p>${run.status === "failed" ? errorMarkup(run.error) + (run.error?.retryable ? '<button type="button" class="secondary-button" data-action="retry">重新提交请求</button>' : "") : ""}`;
  output.innerHTML = `${run.assistant_message ? `<section class="assistant-message"><h2>Agent 回复</h2><p>${escapeHtml(run.assistant_message)}</p></section>` : ""}
    ${renderWarnings(run)}
    ${run.status === "needs_input" ? `<section class="status-panel is-warning"><h2>请补充或确认</h2><ul class="warning-list">${run.follow_up_questions.map((question) => `<li>${escapeHtml(question)}</li>`).join("")}</ul><button type="button" class="secondary-button" data-action="edit">返回输入</button></section>` : ""}
    ${run.status === "no_data" ? '<div class="empty-state">当前数据范围没有结果。请检查门店、商品、日期及数据版本。</div>' : ""}
    ${run.status === "awaiting_confirmation" ? scenarioMarkup(run.scenario_preview) : ["succeeded", "partial"].includes(run.status) ? run.items.map((item) => itemMarkup(run, item, agent)).join("") || '<div class="empty-state">本次运行未返回结果项。</div>' : ""}
    ${renderSteps(run.steps)}${runMeta(agent)}`;
}

function renderPage() {
  const isData = state.page === "data";
  $("#agent-page").hidden = isData;
  $("#data-page").hidden = !isData;
  $("#page-title").textContent = isData ? "数据与版本" : AGENT_CONFIG[state.active].title;
  $("#page-description").textContent = isData ? "下载可复现的合成输入包，核对数据、规则和契约版本。" : AGENT_CONFIG[state.active].description;
  renderNavigation();
  if (!state.manifest) {
    for (const selector of ["#agent-form", "#run-status", "#run-output", "#data-content"]) $(selector).replaceChildren();
    return;
  }
  if (isData) renderData(); else { renderForm(state.active); renderOutput(state.active); }
}

function setNavigationOpen(open) {
  document.body.classList.toggle("nav-open", open);
  $("#nav-toggle").setAttribute("aria-expanded", String(open));
  $("#nav-backdrop").hidden = !open;
}

function navigate() {
  const route = location.hash.slice(1);
  state.page = route === "data" ? "data" : "agent";
  state.active = AGENT_TYPES.includes(route) ? route : "slow_moving";
  setNavigationOpen(false);
  renderPage();
}

async function runAgent(operation = "preview") {
  const type = state.active, agent = state.agents.get(type);
  if (!agent || agent.pending) return;
  const form = $("#agent-form");
  if (operation !== "simulate" && !form.reportValidity()) return;
  let request;
  try {
    let params, scope, sourceValues = agent.values;
    if (type === "cashflow_simulation" && operation === "simulate") {
      if (agent.run?.status !== "awaiting_confirmation" || !agent.request || agent.error) return;
      const preview = agent.run.scenario_preview;
      params = { operation: "simulate", scenario_id: preview.scenario_id, confirmed: true, horizon_days: preview.horizon_days, adjustments: structuredClone(preview.adjustments), assumptions: [...preview.assumptions] };
      scope = { ...agent.request.scope, store_ids: [...preview.store_ids] };
    } else {
      editInput();
      sourceValues = agent.values;
      params = paramsFromValues(type, sourceValues);
      scope = { as_of: sourceValues.as_of, store_ids: [...sourceValues.store_ids], sku_ids: [...sourceValues.sku_ids], category_ids: [...sourceValues.category_ids] };
    }
    request = buildRunRequest({ agentType: type, userInput: sourceValues.user_input.trim(), scope, params, dataVersion: sourceValues.data_version.trim(), policyVersion: sourceValues.policy_version.trim(), ...(agent.sessionId ? { sessionId: agent.sessionId } : {}) });
  } catch (error) { toast(error.message); return; }
  const revision = agent.revision, token = requests.start(type, "运行 Agent");
  agent.pending = true; agent.controller = new AbortController(); agent.request = request; agent.run = null; agent.error = null; agent.decisions.clear();
  renderForm(type); renderOutput(type); renderNavigation();
  try {
    const response = await api("/agent-runs", { method: "POST", body: JSON.stringify(request), signal: agent.controller.signal });
    if (agent.revision !== revision || requests.get(type).token !== token) return;
    agent.run = validateRunResponse(response, request);
    state.connected = true;
    agent.edited = false;
    requests.finish(type, token, "ready");
  } catch (error) {
    if (agent.revision === revision && requests.finish(type, token, "error", error)) agent.error = error;
  } finally {
    agent.pending = false; agent.controller = null;
    if (state.page === "agent" && state.active === type) { renderForm(type); renderOutput(type); }
    renderNavigation(); renderConnection();
  }
}

async function recordDecision(button) {
  const type = state.active, agent = state.agents.get(type), run = agent?.run;
  if (!run || !["succeeded", "partial"].includes(run.status)) return;
  const item = run.items.find((value) => value.item_id === button.dataset.itemId);
  const recommendation = item?.recommendations.find((value) => value.recommendation_id === button.dataset.recommendation);
  if (!recommendation) return;
  const decision = button.dataset.decision;
  const key = decisionKey(run.run_id, item.item_id, recommendation.recommendation_id), old = agent.decisions.get(key);
  if (old?.pending || old?.response) return;
  if (old?.error?.outcomeUnknown && !window.confirm("上次记录结果未知。请先与后端核对；确定重新提交这条模拟决策？")) return;
  const note = $$("[data-decision-note]").find((input) => input.dataset.decisionNote === key)?.value.trim() || "";
  const record = { pending: true, note, response: null, error: null };
  agent.decisions.set(key, record); renderOutput(type);
  const payload = { item_id: item.item_id, recommendation_id: recommendation.recommendation_id, decision, note };
  try {
    const response = await api(`/agent-runs/${encodeURIComponent(run.run_id)}/decisions`, { method: "POST", body: JSON.stringify(payload) });
    record.response = validateDecisionResponse(response, { run_id: run.run_id, ...payload });
  } catch (error) { record.error = error; }
  finally {
    record.pending = false;
    if (agent.run?.run_id === run.run_id) renderOutput(type);
  }
}

function renderData() {
  const manifest = state.manifest;
  const titles = { dataset: "完整输入数据包", stores: "门店", skus: "商品", inventory_snapshots: "库存快照", sales_daily: "日销售", purchase_orders: "采购单", inventory_lots: "批次库存", policies: "经营规则" };
  const rows = Object.entries(manifest.files).filter(([key]) => titles[key]).map(([key, file]) => `<tr><th scope="row">${titles[key]}</th><td><a href="${escapeHtml(sampleDownloadTarget(manifest, key))}" download>下载 ${file.path.endsWith(".json") ? "JSON" : "CSV"}</a></td><td><code>${escapeHtml(file.sha256)}</code></td></tr>`).join("");
  $("#data-content").innerHTML = `<section class="result-card"><h2>固定合成输入 · 可复现</h2><dl class="details-grid"><div><dt>契约</dt><dd>${escapeHtml(manifest.contract_version)}</dd></div><div><dt>数据版本</dt><dd>${escapeHtml(manifest.data_version)}</dd></div><div><dt>规则版本</dt><dd>${escapeHtml(manifest.policy_version)}</dd></div><div><dt>固定分析日</dt><dd>${escapeHtml(manifest.as_of)}</dd></div><div><dt>随机种子</dt><dd>${manifest.seed}</dd></div><div><dt>时区</dt><dd>${escapeHtml(manifest.timezone)}</dd></div></dl><p>页面筛选项来自这份本地合成输入包。下载不会把文件自动加载到后端；实际运行的版本由服务响应确认。</p><p>当前契约只定义运行与模拟决策接口。数据加载由魏的后端完成，前端不调用旧版导入、审批、执行或重置接口。</p></section><section class="result-card"><h2>七类共享模型与完整数据包</h2><div class="table-wrap" tabindex="0" role="region" aria-label="合成数据下载与校验值"><table class="data-table"><thead><tr><th>数据</th><th>文件</th><th>SHA-256</th></tr></thead><tbody>${rows}</tbody></table></div></section><section class="result-card"><h2>复现与联调</h2><p>所有金额字段使用整数分；数量保留商品计量单位。零销量与缺失销量分别处理，未知值显示为未知。</p><ul><li><a href="docs/API_CONTRACT.md">魏的 v0.3 接口原文</a></li><li><a href="sample-data/README.md">数据口径、场景与参考预期</a></li><li><a href="docs/FRONTEND_INTEGRATION.md">联调说明与待确认事项</a></li><li><a href="docs/VALIDATION_RESULT.md">本次验证记录</a></li></ul><p>样例预期只供验收，页面不会读取预期文件生成运行结果。</p></section>`;
}

async function loadManifest() {
  state.manifestError = null; renderConnection();
  try {
    const load = createApiClient({ baseUrl: location.protocol === "file:" ? null : "/sample-data" });
    state.manifest = validateManifest(await load("/manifest.json"));
    for (const type of AGENT_TYPES) state.agents.set(type, createAgent(type));
  } catch (error) { state.manifest = null; state.manifestError = error; }
  renderConnection(); renderPage();
}

$("#agent-form").addEventListener("submit", (event) => { event.preventDefault(); runAgent(); });
$("#agent-form").addEventListener("input", editInput);
$("#agent-form").addEventListener("change", editInput);
document.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button || button.disabled) return;
  if (button.dataset.agent || button.dataset.page) {
    setNavigationOpen(false);
    location.hash = button.dataset.agent || button.dataset.page;
    return;
  }
  if (button.dataset.decision) { recordDecision(button); return; }
  const action = button.dataset.action, agent = state.agents.get(state.active);
  if (action === "reload-manifest") { loadManifest(); return; }
  if (!agent) return;
  if (action === "cancel") agent.controller?.abort();
  if (action === "example" && !agent.pending) {
    $('[name="user_input"]', $("#agent-form")).value = AGENT_CONFIG[state.active].example;
    editInput();
  }
  if (action === "simulate") runAgent("simulate");
  if (action === "retry") {
    if (agent.error?.outcomeUnknown && !window.confirm("上次运行是否完成未知。请先核对请求编号；确定提交一个新请求？")) return;
    // A failed calculation must go through a fresh preview; an old confirmation
    // cannot silently authorize a second scenario run.
    runAgent();
  }
  if (action === "revise") {
    agent.revision++; requests.invalidate(state.active); agent.run = null; agent.error = null; agent.request = null; agent.edited = true; agent.decisions.clear();
    renderOutput(state.active);
  }
  if (action === "revise" || action === "edit") {
    $("#agent-form").scrollIntoView({ behavior: "auto", block: "start" });
    $('[name="user_input"]', $("#agent-form")).focus();
  }
});
$(".skip-link").addEventListener("click", (event) => { event.preventDefault(); $("#workspace").focus(); });
$("#nav-toggle").addEventListener("click", () => setNavigationOpen(!document.body.classList.contains("nav-open")));
$("#nav-backdrop").addEventListener("click", () => setNavigationOpen(false));
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") setNavigationOpen(false);
});
window.addEventListener("hashchange", navigate);
navigate(); renderConnection(); loadManifest();

import { buildDataCenterView, downloadTemplate, downloadSample } from "./assets/js/data-center.mjs";
import { createApiClient } from "./assets/js/api-client.mjs";
import { createRequestState } from "./assets/js/request-state.mjs";

const API_BASE = window.location.protocol === "file:" ? null : "/api/v1";
const validRoutes = new Set([
  "overview", "today", "slow-diagnosis", "transfer", "expiry-rescue", "procurement-brake",
  "risks", "tasks", "approvals", "execution", "simulation", "cases", "data", "settings",
]);
const state = {
  risks: [],
  dashboard: null,
  selectedId: null,
  riskTotal: 0,
  detail: null,
  diagnosisRiskId: null,
  diagnosisDetail: null,
  diagnosisView: "list",
  diagnosisSearch: "",
  diagnosisPriority: "all",
  diagnosisRisks: null,
  diagnosisTotal: 0,
  parentRoute: null,
  priorityFilter: "全部",
  typeFilter: "全部",
  evidenceFilter: "全部",
  search: "",
  investigationId: null,
  feedbackId: null,
  toastTimer: null,
  workbenches: {},
  workItems: [],
  proposals: [],
  executionTasks: [],
  dataCenter: null,
  health: null,
  workbenchQueues: {},
  workbenchPending: {},
  workbenchRevisions: {},
  simulationExcluded: [],
  simulationCandidates: [],
  simulationResult: null,
  feedback: null,
  feedbackRiskId: null,
  feedbackRevision: 0,
  manifest: null,
  datasetEpoch: 0,
  resetting: false,
  mutationCount: 0,
  apiPending: 0,
  region: "all",
  todayFilter: "pending",
  todaySelectedItemId: null,
  todayWorkbenchCache: {},
  chatMessages: [],
  caseFilter: "all",
  selectedCaseId: null,
  confirmedCases: [],
  analysisSearch: "",
  analysisStatus: "全部状态",
  analysisSort: "按创建时间",
  overviewShowAllStores: false,
  overviewSelectedStore: null,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const REGIONS = {
  all: { label: "当前全部门店", stores: [] },
  "west-lake": { label: "西湖区区域", stores: ["西湖"] },
  shangcheng: { label: "上城区区域", stores: ["上城"] },
  gongshu: { label: "拱墅区区域", stores: ["拱墅"] },
  yuhang: { label: "余杭区区域", stores: ["余杭"] },
  linping: { label: "临平区区域", stores: ["临平"] },
  binjiang: { label: "滨江区区域", stores: ["滨江"] },
  xiaoshan: { label: "萧山区区域", stores: ["萧山"] },
  qiantang: { label: "钱塘区区域", stores: ["钱塘"] },
  fuyang: { label: "富阳区区域", stores: ["富阳"] },
};

function scopedRisks() {
  const region = REGIONS[state.region] || REGIONS.all;
  return !region.stores.length ? state.risks : state.risks.filter((risk) => region.stores.some((name) => String(risk.store || "").includes(name)));
}

const requestApi = createApiClient({ baseUrl: API_BASE });
const requests = createRequestState(() => renderRuntimeStatus());
const WORKBENCH_ROUTES = ["transfer", "expiry-rescue", "procurement-brake"];
const AGENT_NAMES = { "slow-diagnosis": "滞销诊断", transfer: "跨门店调拨", "expiry-rescue": "近效期处置", "procurement-brake": "采购刹车", simulation: "现金流模拟" };
const RESOURCE_LOADERS = {
  health: { path: "/health", label: "服务运行模式", apply: (data) => { state.health = data; } },
  dashboard: { path: "/dashboard", label: "经营总览", apply: (data) => { state.dashboard = data; } },
  risks: { path: "/risks", label: "风险队列", apply: (data) => {
    if (!Array.isArray(data.items)) throw new Error("风险接口缺少 items 数组");
    state.risks = data.items; state.riskTotal = data.total ?? data.items.length;
    state.diagnosisRisks = null; state.diagnosisTotal = data.filtered_total ?? state.riskTotal;
  } },
  cases: { path: "/cases", label: "核查案例", apply: (data) => { state.confirmedCases = data.items || []; } },
  workItems: { path: "/work-items", label: "行动清单", apply: (data) => { state.workItems = data.items || []; } },
  proposals: { path: "/proposals", label: "方案审批", apply: (data) => { state.proposals = data.items || []; } },
  executionTasks: { path: "/execution-tasks", label: "执行追踪", apply: (data) => { state.executionTasks = data.items || []; } },
  dataCenter: { path: "/data-center", label: "数据来源", apply: (data) => { state.dataCenter = data; } },
};

function errorCopy(error) {
  return error?.outcomeUnknown ? `${error.message}。写入结果待确认，请刷新记录并人工核对后再操作。` : error?.message || "请求失败";
}

async function api(path, options) {
  state.apiPending++;
  renderRuntimeStatus();
  try { return await requestApi(path, options); }
  finally { state.apiPending--; renderRuntimeStatus(); }
}

async function readResource(key, path, apply, label = key) {
  if (state.resetting) return false;
  const token = requests.start(key, label);
  const epoch = state.datasetEpoch;
  try {
    const data = await api(path);
    if (epoch !== state.datasetEpoch || requests.get(key).token !== token) return false;
    apply(data);
    requests.finish(key, token, "ready");
    return true;
  } catch (error) {
    if (epoch === state.datasetEpoch) requests.finish(key, token, "error", error);
    return false;
  }
}

function resourceNotice(key, empty = "暂无记录") {
  const resource = requests.get(key);
  if (resource.status === "loading") return '<div class="empty-state" role="status">正在读取，请稍候…</div>';
  if (resource.status === "error") return `<div class="empty-state request-error" role="alert">${escapeHtml(errorCopy(resource.error))}<button class="secondary-action" data-retry-resource="${escapeHtml(key)}">重新读取</button></div>`;
  return `<div class="empty-state">${escapeHtml(empty)}</div>`;
}

function renderRuntimeStatus() {
  const target = $("#runtime-status");
  if (!target) return;
  const entries = requests.entries();
  const errors = entries.filter(([, resource]) => resource.status === "error");
  const loading = state.apiPending > 0 || entries.some(([, resource]) => resource.status === "loading");
  const dataReady = requests.get("dataCenter").status === "ready";
  const mode = dataReady ? state.dataCenter?.mode : null;
  const source = mode === "sample_replay" ? "合成测试数据 · 模拟测算，不代表真实客户收益" : mode === "real_inventory_snapshot" ? "真实库存快照 · 缺项需人工补充" : "数据来源尚未确认";
  target.className = `runtime-status ${errors.length ? "is-error" : loading ? "is-loading" : ""}`;
  target.innerHTML = `<div><strong>${escapeHtml(source)}</strong><p>规则模式 · 真实 AI 未接入；模型名称、模型原文与调用证据尚无接口提供。</p>${errors.length ? `<p role="alert">${errors.map(([, item]) => `${escapeHtml(item.label)}：${escapeHtml(errorCopy(item.error))}`).join("；")}</p>` : loading ? "<p>正在读取服务数据…</p>" : ""}</div><button class="secondary-action" data-refresh-all ${state.resetting ? "disabled" : ""}>重新读取</button>`;
  const freshness = $("#data-freshness");
  const updated = requests.get("dataCenter").updatedAt;
  if (freshness) freshness.textContent = updated ? `读取于 ${new Date(updated).toLocaleTimeString("zh-CN")}${dataReady ? "" : " · 数据待确认"}` : "尚未读取快照";
  const reset = $("#demo-reset");
  if (reset) reset.disabled = !dataReady || mode !== "sample_replay" || requests.get("health").status !== "ready" || state.health?.sample_data !== true || state.resetting || state.apiPending > 0 || state.mutationCount > 0;
  for (const route of Object.keys(AGENT_NAMES)) renderAgentRuntime(route);
}

function renderAgentRuntime(route) {
  const target = document.querySelector(`[data-agent-runtime="${route}"]`);
  if (!target) return;
  const key = route === "slow-diagnosis" ? "diagnosis" : route;
  const request = requests.get(key);
  const data = route === "slow-diagnosis" ? state.diagnosisDetail : route === "simulation" ? state.simulationResult : state.workbenches[route];
  const input = route === "slow-diagnosis" ? data?.risk : route === "simulation" ? state.simulationInput : data?.input;
  const result = route === "slow-diagnosis" ? data?.diagnosis : route === "simulation" ? data : data?.calculation;
  const missing = data?.evidence?.missing_fields || result?.cash?.missing_fields || result?.cash_basis?.missing_fields || [];
  const evidence = data?.facts || data?.evidence || [];
  const confirmation = data?.proposal ? `方案 ${data.proposal.id} · V${data.proposal.current_version} · ${data.proposal.status}` : "待人工检查；当前未批准执行";
  const label = request.status === "loading" ? request.label : request.status === "error" ? "请求失败 / 待人工处理" : data?.dirty ? "输入已变更 · 待重新计算" : result ? "规则结果已返回 · 待人工确认" : "等待输入或读取";
  const endpoint = route === "slow-diagnosis" ? `GET /risks/${state.diagnosisRiskId || "{id}"}` : route === "simulation" ? "POST /scenarios/simulate" : `/workbenches/${route}`;
  target.innerHTML = `<div class="agent-runtime-heading"><strong>${escapeHtml(AGENT_NAMES[route])}运行过程</strong><span>${escapeHtml(label)}</span></div><ol class="agent-runtime-steps"><li>输入与快照</li><li>后端规则工具</li><li>证据与缺项</li><li>人工确认</li></ol><p>${escapeHtml(endpoint)} · ${escapeHtml(confirmation)}</p>${request.status === "error" ? `<p class="request-error" role="alert">${escapeHtml(errorCopy(request.error))}</p>` : ""}<p>缺失字段：${escapeHtml(missing.join("、") || "以本次返回为准")}。AI 输出：未提供。</p><details><summary>查看本次输入、计算结果与证据</summary><div class="runtime-payload"><div><h3>输入</h3><pre>${escapeHtml(JSON.stringify(input ?? null, null, 2))}</pre></div><div><h3>规则结果</h3><pre>${escapeHtml(JSON.stringify(result ?? null, null, 2))}</pre></div><div><h3>来源与证据</h3><pre>${escapeHtml(JSON.stringify(evidence, null, 2))}</pre></div></div></details>`;
}

async function performAction(key, label, action, onSuccess) {
  if (state.resetting || requests.get(key).status === "loading") return false;
  const token = requests.start(key, label);
  state.mutationCount++;
  if (key.startsWith("approval:") || key.startsWith("execute:")) {
    const id = key.slice(key.indexOf(":") + 1);
    $$("[data-approve-proposal], [data-execute-proposal]").filter((button) => button.dataset.approveProposal === id || button.dataset.executeProposal === id).forEach((button) => { button.disabled = true; });
  }
  renderRuntimeStatus();
  try {
    const result = await action();
    await onSuccess?.(result);
    requests.finish(key, token, "ready");
    return true;
  } catch (error) {
    requests.finish(key, token, "error", error);
    showToast(errorCopy(error), "error");
    return false;
  } finally {
    state.mutationCount--;
    if (key.startsWith("approval:") || key.startsWith("execute:")) renderApprovalList();
    renderRuntimeStatus();
  }
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  })[character]);
}

function money(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "未知";
  return `¥${Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 2 })}`;
}

function moneyWan(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return `${(Number(value) / 10000).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} 万元`;
}

function riskAmount(risk) {
  return Number(risk.inventory_qty || 0) * Number(risk.unit_cost || 0);
}

function median(values = []) {
  const sorted = values.map(Number).filter(Number.isFinite).sort((a, b) => a - b);
  if (!sorted.length) return null;
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function differencePercent(local, peer) {
  if (!peer) return null;
  return Math.round(((Number(peer) - Number(local || 0)) / Number(peer)) * 100);
}

function evidenceLabel(level) {
  return { sufficient: "证据充分", partial: "部分支持", insufficient: "证据不足" }[level] || "证据不足";
}

function riskLabel(type) {
  return { "调拨": "销售差异", "促销": "近效期风险", "退供": "库存积压", "采购刹车": "采购敞口" }[type] || "库存风险";
}

function teacherPriority(risk) {
  return risk?.teacher_priority || risk?.priority || "待确认";
}

function isUrgentPriority(priority) {
  return priority === "P1" || priority === "紧急";
}

function actionFor(risk) {
  return {
    "调拨": "补充证据后评估跨店调拨",
    "促销": "核查可售天数后评估近效促销",
    "退供": "核查供应商条款后评估退换",
    "采购刹车": "核对在途采购后评估采购调整",
  }[risk.risk_type] || "补充证据后生成处置方案";
}

const agentModules = {
  "slow-diagnosis": {
    listId: "slow-list", countId: "slow-count", amountId: "slow-amount", navCountId: "slow-nav-count", overviewCountId: "overview-slow-count",
    action: "诊断原因", match: (risk) => risk.teacher_baseline?.candidate || Number(risk.days_to_sell || 0) >= 120,
  },
  transfer: {
    listId: "transfer-list", countId: "transfer-count", amountId: "transfer-amount", navCountId: "transfer-nav-count", overviewCountId: "overview-transfer-count",
    action: "测算调拨", match: (risk) => risk.risk_type === "调拨",
  },
  "expiry-rescue": {
    listId: "expiry-list", countId: "expiry-count", amountId: "expiry-amount", navCountId: "expiry-nav-count", overviewCountId: "overview-expiry-count",
    action: "制定抢救方案", match: (risk) => risk.risk_type === "促销",
  },
  "procurement-brake": {
    listId: "procurement-list", countId: "procurement-count", amountId: "procurement-amount", navCountId: "procurement-nav-count", overviewCountId: "overview-procurement-count",
    action: "检查采购敞口", match: (risk) => risk.risk_type === "采购刹车",
  },
};

function agentRouteForRisk(risk) {
  if (risk?.risk_type === "调拨") return "transfer";
  if (risk?.risk_type === "促销") return "expiry-rescue";
  if (risk?.risk_type === "采购刹车") return "procurement-brake";
  return "slow-diagnosis";
}

function missingLabel(field) {
  return {
    shelf_availability: "货架可用性数据",
    stockout_records: "缺货记录",
    supplier_return_terms: "供应商退换条款",
    sellable_days: "批次可售天数",
    purchase_order_status: "采购单与在途状态",
    store_scale: "门店规模与客群",
    trade_area_tag: "商圈标签",
    price_history: "价格与折扣历史",
    peer_price: "同品价格",
    seasonality_history: "历史季节销量曲线",
    in_transit_qty: "在途数量",
    replenishment_rule: "自动补货规则",
    replenishment_log: "补货触发记录",
    target_store_future_sales_receipts: "接收门店后续销量与回款",
    price_sales_elasticity: "促销价格与销量关系",
    payment_date_in_horizon: "目标期限内的付款日期",
    comparison_sales: "同品对照销量",
    non_zero_comparison_denominator: "有效的非零对照销量",
  }[field] || field;
}

function showToast(message, tone = "success") {
  const toast = $("#toast");
  clearTimeout(state.toastTimer);
  $("p", toast).textContent = message;
  toast.style.color = tone === "error" ? "#a42d35" : "";
  toast.classList.add("show");
  state.toastTimer = setTimeout(() => toast.classList.remove("show"), 3200);
}

async function switchRegion(regionId) {
  if (state.mutationCount || Object.values(state.workbenchPending).some(Boolean)) {
    $("#region-select").value = state.region; showToast("请等待当前写入完成后切换区域", "error"); return;
  }
  state.region = REGIONS[regionId] ? regionId : "all";
  state.overviewShowAllStores = false; state.overviewSelectedStore = null;
  const firstRisk = scopedRisks()[0];
  state.selectedId = firstRisk?.id ?? null;
  state.diagnosisRiskId = state.selectedId;
  state.detail = null; state.diagnosisDetail = null;
  state.workbenches = {};
  for (const route of WORKBENCH_ROUTES) requests.invalidate(route);
  invalidateSimulation("区域已改变，请重新计算当前范围");
  renderRiskList(); renderSupportPages();
  await loadSelectedDetail(); await loadDiagnosisReport(state.diagnosisRiskId);
  if (WORKBENCH_ROUTES.includes(currentRoute())) await loadWorkbench(currentRoute());
  renderChat();
  showToast(`已切换至${REGIONS[state.region].label}`);
}

function filteredRisks() {
  const query = state.search.trim().toLowerCase();
  return scopedRisks().filter((risk) => {
    const matchesSearch = !query || [risk.product, risk.store, risk.sku, risk.risk_type, risk.observation].join(" ").toLowerCase().includes(query);
    const matchesPriority = state.priorityFilter === "全部" || teacherPriority(risk) === state.priorityFilter;
    const matchesType = state.typeFilter === "全部" || risk.risk_type === state.typeFilter;
    const matchesEvidence = state.evidenceFilter === "全部" || risk.evidence_level === state.evidenceFilter;
    return matchesSearch && matchesPriority && matchesType && matchesEvidence;
  });
}

function selectedRisk() {
  return state.risks.find((risk) => Number(risk.id) === Number(state.selectedId));
}

function renderRiskList() {
  const list = filteredRisks();
  const container = $("#risk-list");
  if (requests.get("risks").status !== "ready") {
    container.innerHTML = resourceNotice("risks"); return;
  }
  container.innerHTML = list.map((risk) => {
    const selected = Number(risk.id) === Number(state.selectedId);
    const priorityClass = isUrgentPriority(teacherPriority(risk)) ? "urgent" : "";
    return `
      <button class="risk-item${selected ? " selected" : ""}" data-risk-id="${risk.id}" aria-label="查看 ${escapeHtml(risk.product)} 案件">
        <span class="risk-priority ${priorityClass}">${escapeHtml(teacherPriority(risk))}</span>
        <span class="risk-copy">
          <strong>${escapeHtml(risk.product)}</strong>
          <span>${escapeHtml(risk.store)}</span>
          <small>${escapeHtml(riskLabel(risk.risk_type))} · ${escapeHtml(risk.observation)}</small>
        </span>
        <span class="risk-meta">
          <strong>${money(riskAmount(risk))}</strong>
          <span>关注成本</span>
          <small>${risk.investigation_status === "pending" ? "核查中" : "待核查"}</small>
        </span>
        <span class="risk-evidence">${escapeHtml(evidenceLabel(risk.evidence_level))}</span>
      </button>`;
  }).join("") || '<div class="empty-state">没有符合当前筛选条件的风险案件。</div>';

  const total = state.riskTotal || state.risks.length;
  const limited = total > state.risks.length;
  $("[id='list-total']").textContent = limited ? `当前展示 ${list.length} / ${total} 条` : `共 ${list.length} 条`;
  $("#mine-count").textContent = total;
  $("#all-count").textContent = total;
  $$("[data-risk-id]", container).forEach((button) => {
    button.addEventListener("click", async () => {
      state.selectedId = Number(button.dataset.riskId);
      state.detail = null;
      renderRiskList();
      await loadSelectedDetail();
      if (window.matchMedia("(max-width: 650px)").matches) $(".risk-module").classList.add("show-detail");
    });
  });
}

function renderEvidence(risk, evidence) {
  const missing = evidence?.missing_fields || risk.missing_fields || [];
  const rows = [
    `<div class="evidence-row">
      <span class="evidence-state complete"><span class="material-symbols-rounded">check_circle</span></span>
      <span class="evidence-name"><strong>基础销售数据</strong><small>近30天销量与对照门店数据已具备</small></span>
      <span class="evidence-badge complete">已完成</span>
      <span></span>
    </div>`,
    ...missing.map((field) => `
      <div class="evidence-row">
        <span class="evidence-state"></span>
        <span class="evidence-name"><strong>${escapeHtml(field)}</strong><small>${escapeHtml(missingLabel(field))}</small></span>
        <span class="evidence-badge">待补充</span>
        <button class="evidence-action" data-add-evidence="${escapeHtml(field)}">补充数据</button>
      </div>`),
  ];
  $("#evidence-list").innerHTML = rows.join("");
  $$("[data-add-evidence]").forEach((button) => button.addEventListener("click", () => openInvestigationModal(button.dataset.addEvidence)));
}

function renderSelectedDetail() {
  const risk = selectedRisk();
  const ready = requests.get("detail").status === "ready" && state.detail?.risk?.id === risk?.id;
  const panel = $("#case-pane");
  panel.classList.toggle("is-unavailable", !ready);
  $("#create-investigation").disabled = !ready;
  $("#case-title").textContent = risk ? `${risk.product} · ${risk.store}` : "暂无风险案件";
  $("#fact-copy").textContent = requests.get("detail").status === "error" ? errorCopy(requests.get("detail").error) : risk ? "正在读取事实与证据…" : "当前没有可查看的风险，或数据尚未读取。";
  if (!ready) return;
  const detailRisk = state.detail?.risk || risk;
  const comparison = state.detail?.comparison;
  const peerMedian = comparison?.comparison_median ?? median(detailRisk.comparison || []);
  const diff = comparison?.difference_percent ?? differencePercent(detailRisk.sales_30, peerMedian);
  const evidence = state.detail?.evidence || {
    level: detailRisk.evidence_level,
    label: detailRisk.evidence_label || evidenceLabel(detailRisk.evidence_level),
    missing_fields: detailRisk.missing_fields || [],
  };
  const fact = peerMedian === null
    ? (detailRisk.observation || "当前数据不足以形成可计算的门店对照。")
    : `近30天销量 ${detailRisk.sales_30} 盒，对照门店中位数 ${peerMedian} 盒，差异 ${diff}%；尚未推断形成原因。`;
  const knownCost = "以工作台本次计算为准";

  $("#case-id").textContent = `RISK-${String(risk.sku || risk.id).replace("SKU-", "")}`;
  $("#case-title").textContent = `${risk.product} · ${risk.store}`;
  $("#case-risk-type").textContent = `风险类型　${riskLabel(risk.risk_type)}`;
  $("#case-priority").textContent = risk.priority;
  $("#case-priority").className = `priority-badge ${risk.priority === "紧急" ? "urgent" : ""}`;
  $("#fact-copy").textContent = fact;
  $("#attention-cost").textContent = money(riskAmount(risk));
  $("#known-cost").textContent = knownCost;
  $("#agent-cost").textContent = knownCost;
  $("#agent-action").textContent = actionFor(risk);
  $("#agent-why").textContent = peerMedian === null
    ? `${risk.observation} 当前仍缺少形成原因所需的关键证据。`
    : `该商品近30天销量 ${risk.sales_30} 盒，低于同类门店中位数 ${peerMedian} 盒，差异 ${diff}%。这可能由陈列位置、缺货、季节性或门店需求变化等多种因素导致，尚未推断形成原因。`;
  $("#create-investigation").innerHTML = risk.investigation_status === "pending"
    ? '<span class="material-symbols-rounded">assignment</span>继续核查任务'
    : '<span class="material-symbols-rounded">assignment_add</span>创建核查任务';
  renderEvidence(risk, evidence);
}

async function loadSelectedDetail() {
  const id = state.selectedId;
  closeInvestigationModal();
  state.feedbackRiskId = null;
  state.detail = null;
  state.investigationId = null; state.feedbackId = null; state.feedback = null;
  $("#case-note").value = ""; $("#note-count").textContent = "0";
  if (!id) { requests.invalidate("detail"); renderSelectedDetail(); return; }
  const pending = readResource("detail", `/risks/${id}`, (data) => { state.detail = data; }, "风险详情");
  renderSelectedDetail();
  await pending;
  renderSelectedDetail();
}

async function loadDiagnosisReport(riskId) {
  state.diagnosisRiskId = riskId ? Number(riskId) : null;
  state.diagnosisDetail = null;
  if (!riskId) { requests.invalidate("diagnosis"); renderDiagnosis(); return; }
  const pending = readResource("diagnosis", `/risks/${riskId}`, (data) => { state.diagnosisDetail = data; }, "读取诊断证据");
  renderDiagnosis();
  await pending;
  renderDiagnosis(); renderAgentRuntime("slow-diagnosis");
}

function inputField(label, name, value, type = "number", attributes = {}) {
  const constraints = Object.entries(attributes).map(([key, setting]) => ` ${key}="${escapeHtml(setting)}"`).join("");
  return `<label>${escapeHtml(label)}<input name="${escapeHtml(name)}" type="${type}" value="${escapeHtml(value ?? "")}"${constraints}></label>`;
}

function workbenchStatus(data) {
  const status = data?.draft?.status || "not_saved";
  return { calculated: "已计算，尚未保存", saved: "已保存草稿", needs_recalculation: "待重新计算", blocked: "存在约束错误", not_saved: "尚未保存" }[status] || status;
}

function calculationNotice(calculation) {
  if (!calculation) return '<div class="workbench-notice stale">修改输入后需重新计算；旧测算不能提交审批。</div>';
  if (!calculation.valid) return `<div class="workbench-notice error">约束未通过：${escapeHtml((calculation.errors || []).join("；"))}</div>`;
  return '<div class="workbench-notice success">约束校验通过。现金口径、库存成本和避免报损分列显示。</div>';
}

function transferProductVisual(risk) {
  return Number(risk?.id) === 1
    ? '<img src="assets/transfer-vitamin-d-product.png" alt="钙维生素D软胶囊商品示意图" />'
    : '<span class="material-symbols-rounded" aria-hidden="true">inventory_2</span>';
}

function transferQueue(data, input) {
  const items = data.items || [];
  const selectedRiskId = Number(data.risk?.id || input.risk_id);
  return `<aside class="transfer-queue-panel"><header><div><h2>待调拨商品 <b>${items.length}</b></h2><p>按风险时效与库存占用排序</p></div><span>${items.length} 项</span></header><div class="transfer-filter-row"><span>全部商品分类</span><span>优先级排序</span></div><div class="transfer-case-list">${items.map((item) => {
    const selected = Number(item.id) === selectedRiskId;
    return `<button type="button" class="transfer-case ${selected ? "selected" : ""}" data-transfer-risk="${item.id}" aria-label="查看 ${escapeHtml(item.product)} 调拨方案"><span class="transfer-case-visual">${transferProductVisual(item)}</span><span class="transfer-case-copy"><span><strong>${escapeHtml(item.product)}</strong><i class="priority-badge ${item.priority === "紧急" ? "urgent" : ""}">${escapeHtml(item.priority)}</i></span><small>${escapeHtml(item.sku)} ｜ ${escapeHtml(item.store)}</small><em>库存 ${item.inventory_qty ?? "—"} 件 ｜ 建议数量待后端测算</em><b>库存成本 ${money(riskAmount(item))}</b></span><span class="material-symbols-rounded transfer-case-arrow">chevron_right</span></button>`;
  }).join("") || '<div class="empty-state">当前没有待调拨商品。</div>'}</div></aside>`;
}

function transferStockCard(label, store, before, after, safety, tone) {
  const maximum = Math.max(Number(before ?? 0), Number(after ?? 0), Number(safety ?? 0), 1);
  const barWidth = (value) => value == null ? 0 : Math.max(0, Math.round(Number(value) / maximum * 100));
  return `<section class="transfer-stock-card ${tone}"><h4>${escapeHtml(label)}：${escapeHtml(store || "未知门店")}</h4><div class="transfer-stock-line"><span>调拨前</span><i><b style="width:${barWidth(before)}%"></b></i><strong>${before ?? "未知"} 件</strong></div><div class="transfer-stock-line"><span>调拨后</span><i><b style="width:${barWidth(after)}%"></b></i><strong>${after ?? "待计算"} 件</strong></div><p>安全库存 ${safety ?? "未知"} 件</p></section>`;
}

function transferWorkbench(data) {
  const input = data.input || {};
  const calc = data.calculation || {};
  const risk = data.risk || {};
  const network = data.transfer_network || [];
  const selected = network.find((item) => item.store_id === input.target_store_id) || network.find((item) => item.name === input.target_store) || network[0] || {};
  const before = calc.before_after || {};
  const source = before.source || {}, target = before.target || {};
  const limits = calc.limits || {}, cash = calc.cash || {}, economic = calc.economic || {};
  const impactTone = economic.net_avoidable_loss == null ? "" : Number(economic.net_avoidable_loss) >= 0 ? "positive" : "negative";
  const selectedRank = network.findIndex((item) => item.store_id === input.target_store_id) + 1;
  const limitsSummary = [`后端可调上限 ${limits.available_to_transfer ?? "待计算"} 件`, `后端接收容量 ${limits.receiving_capacity ?? "待计算"} 件`, `预计配送 ${input.eta_days ?? "未知"} 天`];
  return `<div class="transfer-workbench-shell">
    ${transferQueue(data, input)}
    <section class="transfer-focus-panel">
      <header class="transfer-product-header"><div class="transfer-product-visual">${transferProductVisual(risk)}</div><div><div class="transfer-product-title"><h2>${escapeHtml(input.product || "调拨商品")}</h2><span class="priority-badge ${risk.priority === "紧急" ? "urgent" : ""}">${escapeHtml(risk.priority || "待确认")}</span></div><p>${escapeHtml(risk.sku || "SKU 未知")} ｜ 批次 ${escapeHtml(input.batch || "未知")} ｜ 可售期 ${input.sellable_days ?? "未知"} 天</p><div class="transfer-tag-list"><span>滞销诊断</span><span>可调拨</span><span>库存积压</span></div></div><button class="secondary-action" type="button" data-go="slow-diagnosis">查看诊断依据</button></header>
      <nav class="transfer-detail-tabs" aria-label="调拨详情"><span class="active">推荐方案</span><span>候选门店</span><span>库存对比</span><span>调拨影响</span><span>相关证据</span></nav>
      <section class="transfer-recommendation"><span class="material-symbols-rounded">recommend</span><div><p>推荐方案</p><h3>建议将 <b>${input.quantity ?? "—"} 件</b> 调至 ${escapeHtml(input.target_store || "推荐接收门店")}</h3><small>${escapeHtml(input.source_store || "调出门店")} <span class="material-symbols-rounded">arrow_forward</span> ${escapeHtml(input.target_store || "接收门店")} ｜ ${selected.distance_km ?? "—"} km ｜ 预计 ${selected.travel_minutes ?? "—"} 分钟到店 ｜ 配送费 ${money(input.transport_fee)}</small></div><div class="transfer-recommendation-metric"><span>本次调拨库存成本</span><strong>${money(cash.inventory_cost)}</strong><small>${input.quantity ?? "—"} 件 × ${money(input.unit_cost).replace("¥", "¥")}/件</small></div><div class="transfer-recommendation-metric positive"><span>预计避免报损</span><strong>${money(economic.avoided_loss)}</strong><small>不调拨预计损失 ${money(economic.potential_loss_without_transfer)}</small></div></section>
      <div class="transfer-validation-row">${limitsSummary.map((label) => `<span><i class="material-symbols-rounded">info</i>${escapeHtml(label)}</span>`).join("")}<button class="text-link" type="button" data-go="risks">查看计算依据 <span class="material-symbols-rounded">arrow_forward</span></button></div>
      <div class="transfer-route-grid"><section class="transfer-route-card"><header><div><h3>调拨路线（示意）</h3><p>${selected.distance_km ?? "—"} km ｜ 约 ${selected.travel_minutes ?? "—"} 分钟 ｜ 预计 ${selected.eta_days ?? input.eta_days ?? "—"} 天到店</p></div></header><div class="transfer-route-map"><img src="assets/today-transfer-route-map.png" alt="${escapeHtml(input.source_store || "调出门店")}至${escapeHtml(input.target_store || "接收门店")}的同城配送路线示意" /><span class="route-store source">${escapeHtml(input.source_store || "调出门店")}<small>调出 · ${source.on_hand_before ?? input.source_on_hand ?? "—"} 件</small></span><span class="route-store target">${escapeHtml(input.target_store || "接收门店")}<small>调入 · ${input.quantity ?? "—"} 件</small></span><b class="route-map-chip">配送费 ${money(input.transport_fee)}</b></div></section><section class="transfer-alternative-card"><header><h3>其他可接收门店</h3><button type="button" class="text-link" data-transfer-target="${escapeHtml(network[0]?.store_id || "")}">采用最优方案 <span class="material-symbols-rounded">arrow_forward</span></button></header><div class="transfer-alternative-head"><span>候选门店</span><span>距离</span><span>可接收</span><span>预计费用</span></div><div class="transfer-alternative-list">${network.slice(0, 5).map((item, index) => `<button type="button" class="transfer-alternative-row ${item.store_id === input.target_store_id ? "selected" : ""}" data-transfer-target="${escapeHtml(item.store_id)}"><b>${index + 1}</b><span><strong>${escapeHtml(item.district)}区 · ${escapeHtml(item.name)}</strong>${item.store_id === input.target_store_id ? '<em>推荐</em>' : ""}</span><span>${item.distance_km} km</span><span>${item.calculation?.limits?.receiving_capacity ?? "—"} 件</span><span>${money(item.transport_fee)}</span></button>`).join("")}</div></section></div>
      <div class="transfer-impact-grid-new"><div class="transfer-stock-compare">${transferStockCard("调出店", input.source_store, source.on_hand_before ?? input.source_on_hand, source.on_hand_after, source.safety_stock ?? input.source_safety, "source")}${transferStockCard("调入店", input.target_store, target.on_hand_before ?? input.target_on_hand, target.on_hand_after, target.safety_stock ?? input.target_safety, "target")}</div><section class="transfer-impact-card"><h3>预计经营影响（未来 ${input.sellable_days ?? "—"} 天）</h3><div><span class="material-symbols-rounded">inventory</span><p><small>预计可消化</small><strong>${economic.target_sale_before_expiry_qty ?? "未知"} 件</strong></p></div><div class="${impactTone}"><span class="material-symbols-rounded">savings</span><p><small>调拨后净经营影响</small><strong>${money(economic.net_avoidable_loss)}</strong></p></div><div><span class="material-symbols-rounded">swap_vert</span><p><small>调出店覆盖天数</small><strong>${source.coverage_before ?? "未知"} → ${source.coverage_after ?? "未知"} 天</strong></p></div></section></div>
      <form class="transfer-edit-form" data-workbench-form="transfer"><input type="hidden" name="risk_id" value="${escapeHtml(input.risk_id || risk.id || "")}" /><label>调拨数量<input name="quantity" type="number" min="1" value="${escapeHtml(input.quantity ?? "")}" /></label><label>接收门店<select id="transfer-target-picker">${network.map((item) => `<option value="${escapeHtml(item.store_id)}" ${item.store_id === input.target_store_id ? "selected" : ""}>${escapeHtml(item.district)}区 · ${escapeHtml(item.name)}（${item.distance_km} km）</option>`).join("")}</select></label><label>配送费用<input name="transport_fee" type="number" min="0" step="0.01" required value="${escapeHtml(input.transport_fee ?? "")}" /></label><label>预计到货天数<input name="eta_days" type="number" min="0" value="${escapeHtml(input.eta_days ?? "")}" /></label><div class="transfer-form-actions"><small class="workbench-status">${workbenchStatus(data)} · 修改数量、门店或费用后，旧测算即失效。</small><button class="secondary-action" type="button" data-workbench-save="transfer" ${calc.valid ? "" : "disabled"}>保存草稿</button><button class="secondary-action" type="submit">重新计算</button><button class="primary-action" type="button" data-workbench-submit="transfer" ${data.proposal?.status === "draft" ? "" : "disabled"}>提交审批</button></div></form>
      ${calculationNotice(calc)}
      <p class="transfer-calculation-note"><span class="material-symbols-rounded">info</span>${escapeHtml(cash.note || "内部调拨不直接算作现金释放。")} 已知现金流出为配送费 ${money(Math.abs(Number(cash.known_cash_effect || input.transport_fee || 0)))}；实际销售和回款需在执行追踪中确认。当前推荐门店在 ${network.length} 家候选中排名第 ${selectedRank}。</p>
    </section>
  </div>`;
}

function expiryQueuePanel(data, activeRiskId) {
  const queue = data.expiry_queue || [];
  return `<section class='expiry-queue-panel'><div class='surface-toolbar'><div><span class='agent-page-mark'><span class='material-symbols-rounded'>inventory_2</span>近效期处置队列</span><h3>先看哪一批货最来不及卖完</h3><p>${escapeHtml(data.queue_note || '按最晚处置日期排序。')}</p></div><span class='status-pill'>${queue.length} 个批次</span></div><div class='expiry-queue-head'><span>门店／商品／批次</span><span>剩余可售时间</span><span>库存与预计可售</span><span>不处置的风险</span><span>建议动作</span><span></span></div>${queue.map((entry) => { const row = entry.input || {}, forecast = entry.forecast || {}, cash = entry.cash || {}, active = Number(entry.risk?.id) === Number(activeRiskId); return `<div class='expiry-queue-row ${active ? 'active' : ''}'><span><strong>${escapeHtml(row.store)} · ${escapeHtml(row.product)}</strong><small>批次 ${escapeHtml(row.batch)} · 最晚处置 ${escapeHtml(row.latest_disposal_date)}</small></span><b>${row.sellable_days} 天</b><span>${row.inventory_qty} 件<small>预计正常售 ${forecast.normal_sale_qty ?? '未知'} 件</small></span><span><strong>预计剩余 ${forecast.expected_remaining_qty ?? '未知'} 件</strong><small>库存成本 ${money(cash.inventory_cost)}</small></span><span><b class='evidence-badge ${row.sellable_days <= 15 ? 'insufficient' : 'partial'}'>${row.sellable_days <= 15 ? '紧急处理' : '本周处理'}</b><small>调拨＋促销＋退供组合测算</small></span><button class='secondary-action' type='button' data-expiry-select='${entry.risk?.id}'>${active ? '当前方案' : '查看方案'}</button></div>`; }).join('')}</section>`;
}

function expiryWorkbench(data) {
  const rawInput = data.input || {};
  const input = rawInput;
  const calc = data.calculation;
  const forecast = calc?.forecast || {}, cash = calc?.cash || {};
  return `<div class="workbench-shell">${expiryQueuePanel(data, data.risk?.id)}<section class='expiry-plan-header'><span class='agent-page-mark'><span class='material-symbols-rounded'>crisis_alert</span>当前批次处置方案</span><h3>现在处理：${escapeHtml(input.store || "未知门店")} · ${escapeHtml(input.product || "未知商品")}</h3><p>请先确定可分配到调拨、促销、退供的数量，再保存为待审批方案。</p></section><div class="workbench-context"><strong>${escapeHtml(input.store || "未知门店")} · ${escapeHtml(input.product || "未知商品")}</strong><span>批次 ${escapeHtml(input.batch || "未知")} · 剩余可售 ${input.sellable_days ?? "未知"} 天 · 最晚处置 ${escapeHtml(input.latest_disposal_date || "未知")}</span><small>库存 ${input.inventory_qty ?? "未知"} 件 · 当前30日销量 ${input.sales_30 ?? "未知"} 件</small></div>
  <form class="workbench-form four-fields" data-workbench-form="expiry-rescue"><input type="hidden" name="risk_id" value="${escapeHtml(input.risk_id || data.risk?.id || "")}" />${inputField("调拨数量", "transfer_qty", input.transfer_qty, "number", { min: 0 })}${inputField("促销数量", "promo_qty", input.promo_qty, "number", { min: 0 })}${inputField("审核促销价", "promo_price", input.promo_price, "number", { min: 0, step: "0.01" })}${inputField("退供数量", "return_qty", input.return_qty, "number", { min: 0 })}<div class="workbench-actions"><button class="primary-action" type="submit">重新计算</button><button class="secondary-action" type="button" data-workbench-save="expiry-rescue" ${calc?.valid ? "" : "disabled"}>保存方案</button><button class="text-action" type="button" data-workbench-submit="expiry-rescue" ${data.proposal?.status === "draft" ? "" : "disabled"}>提交审批</button></div><small class="workbench-status">${workbenchStatus(data)}</small></form>${calculationNotice(calc)}
  <div class="calculation-kpis"><span>正常可售 <b>${forecast.normal_sale_qty ?? "未知"} 件</b></span><span>预计剩余 <b>${forecast.expected_remaining_qty ?? "未知"} 件</b></span><span>避免报损 <b>${money(cash.avoided_loss)}</b></span><span>预计净现金改善 <b>未知</b></span></div>
  <div class="alternative-table">${(calc?.alternatives || []).map((item) => `<div><strong>${escapeHtml(item.type)}</strong><span>${item.quantity} 件 · 费用 ${money(item.fee)} · 现金 ${money(item.cash_impact)}</span><small>${escapeHtml(item.assumption || `剩余风险 ${item.remaining_risk} 件`)}</small></div>`).join("") || '<div class="empty-state">先计算后比较正常销售、调拨、促销、退供和组合处置。</div>'}</div>
  <p class="workbench-footnote">药品相关沟通仅可生成待审核草稿；未配置审批流程前不自动发送。缺项：${escapeHtml((cash.missing_fields || []).join("、") || "无")}</p></div>`;
}

function procurementEvidencePanel(data, input, inventory) {
  const calculation = data.calculation;
  return `<section class="procurement-evidence-panel"><div class="surface-toolbar"><div><h3>采购调整依据</h3><p>来源：本次后端工作台输入与计算；金额和库存约束由后端计算。</p></div><span class="evidence-badge">${calculation?.valid ? "约束通过，待审批" : "待重新核查"}</span></div><div class="procurement-evidence-grid"><section><span>当前库存</span><strong>${escapeHtml(input.current_inventory ?? "未知")} 件</strong><small>安全库存 ${escapeHtml(input.safety_stock ?? "未知")} 件</small></section><section><span>在途数量</span><strong>${escapeHtml(input.in_transit_qty ?? "未知")} 件</strong><small>不是现有库存</small></section><section><span>未执行采购</span><strong>${escapeHtml(input.open_purchase_qty ?? "未知")} 件</strong><small>调整需供应商与负责人确认</small></section><section><span>调整后预计库存位</span><strong>${escapeHtml(inventory.projected_after_adjustment ?? "待计算")} 件</strong><small>仅展示后端本次结果</small></section></div><p>合同、取消费用和供应商确认仍需人工核查。约束失败时不能保存方案。</p></section>`;
}

function procurementWorkbench(data) {
  const input = data.input || {}, calc = data.calculation, inventory = calc?.inventory_position || {}, payment = calc?.payment || {}, cash = calc?.cash || {};
  return `<div class="workbench-shell">${procurementEvidencePanel(data, input, inventory)}<div class="workbench-context"><strong>${escapeHtml(input.po_number || "未知采购单")} · 行 ${escapeHtml(input.line_number || "未知")}</strong><span>${escapeHtml(input.product || "未知商品")} · ${escapeHtml(input.store || "未知门店")} · 状态 ${escapeHtml(input.order_status || "未知")}</span><small>到货 ${escapeHtml(input.arrival_date || "未知")} · 付款 ${escapeHtml(input.payment_date || "未知")}</small></div>
  <form class="workbench-form" data-workbench-form="procurement-brake"><label>调整方式<select name="action">${[["reduce","减少采购量"],["cancel","取消未执行量"],["delay_arrival","延期到货"],["delay_payment","协商延期付款"]].map(([v,l]) => `<option value="${v}" ${input.action === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>${inputField("调整数量", "adjustment_qty", input.adjustment_qty, "number", "min=1")}${inputField("新付款日", "new_payment_date", input.new_payment_date, "date")}<div class="workbench-actions"><button class="primary-action" type="submit">重新试算</button><button class="secondary-action" type="button" data-workbench-save="procurement-brake" ${calc?.valid ? "" : "disabled"}>保存待审批方案</button><button class="text-action" type="button" data-workbench-submit="procurement-brake" ${data.proposal?.status === "draft" ? "" : "disabled"}>提交审批</button></div><small class="workbench-status">${workbenchStatus(data)}</small></form>${calculationNotice(calc)}
  <div class="before-after-grid"><section><h3>库存与在途（不重复统计）</h3><dl><div><dt>现有库存</dt><dd>${inventory.current_inventory ?? "未知"}</dd></div><div><dt>在途数量</dt><dd>${inventory.in_transit_qty ?? "未知"}</dd></div><div><dt>未执行采购</dt><dd>${inventory.unexecuted_purchase_qty ?? "未知"}</dd></div><div><dt>调整后库存位</dt><dd>${inventory.projected_after_adjustment ?? "未知"} / 安全 ${inventory.safety_stock ?? "未知"}</dd></div></dl></section><section><h3>付款安排</h3><dl><div><dt>原付款日</dt><dd>${escapeHtml(payment.baseline_payment_date || "未知")}</dd></div><div><dt>调整后付款日</dt><dd>${escapeHtml(payment.scenario_payment_date || "未知")}</dd></div><div><dt>变更金额</dt><dd>${money(payment.adjusted_amount)}</dd></div><div><dt>后续付款压力</dt><dd>${money(payment.deferred_payment_pressure)}</dd></div></dl></section></div>
  <div class="calculation-kpis"><span>减少采购支出 <b>${input.action === "reduce" || input.action === "cancel" ? money(cash.known_cash_effect) : "¥0"}</b></span><span>推迟付款 <b>${input.action === "delay_payment" ? money(cash.known_cash_effect) : "¥0"}</b></span><span>预计净现金改善 <b>${money(cash.estimated_net_cash_improvement)}</b></span></div><p class="workbench-footnote">${escapeHtml(cash.note || "采购变更仅生成待审批方案，不会直接修改外部采购单。")}</p></div>`;
}

function renderWorkbench(route) {
  const data = state.workbenches[route];
  const target = $(`#${agentModules[route].listId}`);
  if (!target) return;
  if (state.dashboard?.operating_summary?.mixed_units && !state.risks.length) {
    target.innerHTML = '<div class="empty-state">当前真实库存快照尚未包含销售、批次效期或采购订单，补齐对应数据后才能生成可执行方案。</div>';
    return;
  }
  if ((requests.get(route).status === "loading" || (requests.get(route).status === "error" && !data?.input)) && !state.workbenchPending[route]) {
    target.innerHTML = resourceNotice(route); return;
  }
  if (data?.mode === "real_inventory_snapshot" || data?.mode === "unavailable" || !data?.input || !Object.keys(data.input).length) {
    target.innerHTML = '<div class="empty-state">当前快照缺少可计算的工作台输入，请人工补充批次、门店需求或采购单。</div>'; return;
  }
  if (!data) { target.innerHTML = '<div class="empty-state">工作台数据尚未加载，或接口读取失败。</div>'; return; }
  target.innerHTML = route === "transfer" ? transferWorkbench(data) : route === "expiry-rescue" ? expiryWorkbench(data) : procurementWorkbench(data);
  bindWorkbenchEvents(route, target);
  target.classList.toggle("has-stale-calculation", Boolean(data.dirty));
  if (data.dirty || requests.get(route).status === "error") $$("[data-workbench-save], [data-workbench-submit]", target).forEach((button) => { button.disabled = true; });
  if (state.workbenchPending[route]) setWorkbenchBusy(route);
  renderAgentRuntime(route);
  if (route === "transfer") {
    const statusNode = $("#transfer-approval-count");
    const executionNode = $("#transfer-execution-count");
    if (statusNode) statusNode.textContent = data.proposal?.status === "pending_approval" ? "待审批" : data.draft?.status === "saved" ? "草稿" : "待测算";
    if (executionNode) executionNode.textContent = `${data.tasks?.filter((task) => !["received", "completed"].includes(task.status)).length || 0} 项`;
    $$('[data-transfer-risk]', target).forEach((button) => button.addEventListener("click", () => loadWorkbench("transfer", button.dataset.transferRisk)));
    $$('[data-transfer-target]', target).forEach((button) => button.addEventListener("click", () => selectTransferTarget(button.dataset.transferTarget)));
    $('#transfer-target-picker', target)?.addEventListener("change", (event) => selectTransferTarget(event.target.value));
  }
  if (route === "expiry-rescue") {
    $$('[data-expiry-select]', target).forEach((button) => button.addEventListener("click", () => loadWorkbench("expiry-rescue", button.dataset.expirySelect)));
  }
}

async function selectTransferTarget(storeId) {
  const data = state.workbenches.transfer;
  const candidate = data?.transfer_network?.find((item) => item.store_id === storeId);
  if (!candidate || state.workbenchPending.transfer) return;
  updateWorkbenchInput("transfer", { target_store: candidate.name, target_store_id: candidate.store_id, target_on_hand: candidate.on_hand, target_capacity: candidate.capacity, target_safety: candidate.safety_stock, target_daily_sales: candidate.daily_sales, transport_fee: candidate.transport_fee, eta_days: candidate.eta_days });
  renderWorkbench("transfer");
  await persistWorkbenchInput("transfer");
}

function formInput(form) {
  const input = {};
  new FormData(form).forEach((value, key) => { input[key] = value; });
  return input;
}

function updateWorkbenchInput(route, values) {
  const data = state.workbenches[route];
  if (!data) return;
  state.workbenchRevisions[route] = (state.workbenchRevisions[route] || 0) + 1;
  requests.invalidate(route);
  state.workbenches[route] = { ...data, input: { ...data.input, ...values }, calculation: null, proposal: null, dirty: true, draft: { ...data.draft, status: "needs_recalculation" } };
  invalidateSimulation("工作台输入已变化，请重新运行现金模拟。");
  const target = document.querySelector(`[data-workbench-form="${route}"]`);
  if (target) {
    $$("[data-workbench-save], [data-workbench-submit]", target).forEach((button) => { button.disabled = true; });
    const status = $(".workbench-status", target);
    if (status) status.textContent = "输入已修改，待重新计算";
    const notice = target.parentElement.querySelector(".workbench-notice");
    if (notice) { notice.className = "workbench-notice stale"; notice.textContent = "输入已修改；下方旧结果已失效，重新计算后才能保存与提交。"; }
    target.parentElement.classList.add("has-stale-calculation");
  }
  renderAgentRuntime(route);
}

function queueWorkbench(route, label, action, apply) {
  if (state.resetting) return Promise.resolve();
  const revision = state.workbenchRevisions[route] || 0;
  const data = state.workbenches[route];
  const epoch = state.datasetEpoch;
  state.workbenchPending[route] = (state.workbenchPending[route] || 0) + 1;
  const previous = state.workbenchQueues[route] || Promise.resolve();
  const pending = previous.catch(() => {}).then(async () => {
    if (epoch !== state.datasetEpoch || (state.workbenchRevisions[route] || 0) !== revision) return;
    const token = requests.start(route, label);
    state.mutationCount++; renderRuntimeStatus();
    try {
      const result = await action(data);
      if ((state.workbenchRevisions[route] || 0) === revision && epoch === state.datasetEpoch) {
        apply?.(result);
        requests.finish(route, token, "ready");
      }
    } catch (error) {
      if ((state.workbenchRevisions[route] || 0) === revision) {
        requests.finish(route, token, "error", error);
        showToast(errorCopy(error), "error");
      }
    } finally { state.mutationCount--; renderRuntimeStatus(); }
  }).finally(() => {
    state.workbenchPending[route]--;
    if (!state.workbenchPending[route]) renderWorkbench(route);
  });
  state.workbenchQueues[route] = pending;
  return pending;
}

function persistWorkbenchInput(route) {
  const input = { ...state.workbenches[route]?.input };
  return queueWorkbench(route, "保存输入，旧测算作废", () => api(`/workbenches/${route}/draft`, { method: "POST", body: JSON.stringify({ input }) }), (result) => {
    state.workbenches[route] = { ...state.workbenches[route], draft: result.draft };
  });
}

async function calculateWorkbench(route, form) {
  if (!form.reportValidity()) return;
  const input = { ...state.workbenches[route]?.input, ...formInput(form) };
  updateWorkbenchInput(route, input);
  const pending = queueWorkbench(route, "后端规则工具计算中", () => api(`/workbenches/${route}/calculate`, { method: "POST", body: JSON.stringify({ input }) }), (result) => {
    state.workbenches[route] = { ...state.workbenches[route], input: result.input, calculation: result.calculation, draft: result.draft, proposal: null, dirty: false };
    showToast(result.calculation.valid ? "测算已返回，请检查约束和证据" : "约束未通过，已阻止保存方案", result.calculation.valid ? "success" : "error");
  });
  setWorkbenchBusy(route);
  await pending;
}

function setWorkbenchBusy(route) {
  const target = document.querySelector(`[data-workbench-form="${route}"]`);
  if (target) $$("button, input, select", target).forEach((node) => { node.disabled = true; });
}

async function saveWorkbench(route) {
  const data = state.workbenches[route];
  if (!data?.calculation?.valid || data.dirty || state.workbenchPending[route]) return;
  const input = { ...data.input };
  const pending = queueWorkbench(route, "保存待审批方案", () => api(`/workbenches/${route}/save`, { method: "POST", body: JSON.stringify({ input }) }), (result) => {
    state.workbenches[route] = { ...state.workbenches[route], calculation: result.calculation, proposal: result.proposal, draft: { ...data.draft, status: "saved" } };
    showToast("方案已保存，尚未审批或执行");
  });
  setWorkbenchBusy(route);
  await pending; await refreshCommonRecords();
}

async function submitWorkbench(route) {
  const data = state.workbenches[route];
  if (data?.proposal?.status !== "draft" || data.dirty || state.workbenchPending[route]) return;
  const pending = queueWorkbench(route, "提交人工审批", () => api(`/proposals/${data.proposal.id}/submit`, { method: "POST" }), (proposal) => {
    state.workbenches[route] = { ...state.workbenches[route], proposal };
    showToast("已提交负责人审批");
  });
  setWorkbenchBusy(route);
  await pending; await refreshCommonRecords();
}

function bindWorkbenchEvents(route, target) {
  const form = $("[data-workbench-form]", target);
  form?.addEventListener("submit", (event) => { event.preventDefault(); calculateWorkbench(route, form); });
  form?.addEventListener("input", (event) => { if (event.target.id !== "transfer-target-picker") updateWorkbenchInput(route, formInput(form)); });
  form?.addEventListener("change", (event) => {
    if (event.target.id === "transfer-target-picker") return;
    updateWorkbenchInput(route, formInput(form));
    persistWorkbenchInput(route);
  });
  $("[data-workbench-save]", target)?.addEventListener("click", () => saveWorkbench(route));
  $("[data-workbench-submit]", target)?.addEventListener("click", () => submitWorkbench(route));
}

async function loadWorkbench(route, riskId = null) {
  if (state.resetting || state.workbenchPending[route]) return;
  const current = state.workbenches[route];
  if (!riskId && current?.dirty) { renderWorkbench(route); return; }
  if (riskId && current?.dirty && Number(current.input?.risk_id) !== Number(riskId)) {
    if (!window.confirm("当前输入尚未重新计算，切换商品后可从服务重新读取草稿。继续切换？")) return;
  }
  const regionalCandidate = scopedRisks().find((risk) => agentRouteForRisk(risk) === route);
  if (state.region !== "all" && !riskId && !current && !regionalCandidate) {
    state.workbenches[route] = { input: {}, mode: "unavailable" }; renderWorkbench(route); return;
  }
  const selected = riskId || current?.risk?.id || regionalCandidate?.id;
  state.workbenchRevisions[route] = (state.workbenchRevisions[route] || 0) + 1;
  const pending = readResource(route, `/workbenches/${route}${selected ? `?risk_id=${encodeURIComponent(selected)}` : ""}`, (data) => { state.workbenches[route] = {
    ...data,
    dirty: data.draft?.status === "needs_recalculation",
    calculation: data.draft?.status === "needs_recalculation" ? null : data.calculation,
    proposal: data.draft?.status === "saved" ? data.proposal : null,
  }; }, "读取工作台快照");
  renderWorkbench(route);
  await pending; renderWorkbench(route);
}

async function loadDiagnosisCandidates() {
  const priority = state.diagnosisPriority === "all" ? "" : `?priority=${encodeURIComponent(state.diagnosisPriority)}`;
  await readResource("diagnosisCandidates", `/risks${priority}`, (payload) => {
    state.diagnosisRisks = payload.items || [];
    state.diagnosisTotal = payload.filtered_total ?? payload.total ?? state.diagnosisRisks.length;
  }, "诊断候选清单");
  renderDiagnosis();
}

function renderDiagnosis() {
  const target = $("#slow-list");
  if (!target) return;
  if (requests.get("risks").status !== "ready") { target.innerHTML = resourceNotice("risks"); return; }
  if (requests.get("diagnosisCandidates").status === "error") { target.innerHTML = resourceNotice("diagnosisCandidates"); return; }
  const regionNames = (REGIONS[state.region] || REGIONS.all).stores;
  const regionRisks = (state.diagnosisRisks || state.risks).filter((risk) => !regionNames.length || regionNames.some((name) => String(risk.store || "").includes(name)));
  const selectedRisk = regionRisks.find((item) => Number(item.id) === Number(state.diagnosisRiskId)) || regionRisks[0];
  const baselineSummary = state.dashboard?.teacher_baseline || {};
  const operatingSummary = state.dashboard?.operating_summary || {};
  const snapshotLabel = $("#slow-snapshot-label");
  if (snapshotLabel) snapshotLabel.textContent = operatingSummary.source_label || "当前库存快照";

  const candidates = regionRisks.filter((item) => item.teacher_baseline?.candidate || Number(item.days_to_sell || 0) >= 120);
  const countFor = (priority) => baselineSummary.status === "ready"
    ? Number(baselineSummary[`${priority.toLowerCase()}_count`] || 0)
    : candidates.filter((item) => teacherPriority(item) === priority).length;
  const p1Count = countFor("P1"), p2Count = countFor("P2"), p3Count = countFor("P3");
  const candidateCount = baselineSummary.status === "ready" ? Number(baselineSummary.candidate_count || 0) : candidates.length;
  const candidateAmount = baselineSummary.status === "ready"
    ? Number(baselineSummary.candidate_inventory_amount || 0)
    : candidates.reduce((sum, item) => sum + riskAmount(item), 0);
  const suggestedReduction = baselineSummary.status === "ready"
    ? Number(baselineSummary.suggested_reduction_amount || 0)
    : candidates.reduce((sum, item) => sum + Number(item.teacher_baseline?.suggested_reduction_amount || 0), 0);
  const query = state.diagnosisSearch.trim().toLowerCase();
  const displayedCandidateTotal = state.diagnosisTotal ?? candidateCount;
  const visibleCandidates = candidates.filter((item) => {
    const matchesText = !query || [item.product, item.store, item.sku].join(" ").toLowerCase().includes(query);
    return matchesText && (state.diagnosisPriority === "all" || teacherPriority(item) === state.diagnosisPriority);
  });
  const stores = [...(operatingSummary.stores || [])]
    .filter((store) => Number(store.candidate_inventory_value || 0) > 0)
    .sort((left, right) => Number(right.candidate_inventory_value || 0) - Number(left.candidate_inventory_value || 0));
  const topStores = stores.slice(0, 10);
  const maxStoreCandidate = Math.max(...topStores.map((store) => Number(store.candidate_inventory_value || 0)), 1);
  const priorityTotal = Math.max(p1Count + p2Count + p3Count, 1);
  const priorityRows = [
    ["P1", p1Count, "不动销或无可计算销量，优先核查"],
    ["P2", p2Count, "降库存存销比大于目标值 3"],
    ["P3", p3Count, "超过目标，但未达到 P2 阈值"],
  ];
  const risk = selectedRisk;
  const detail = state.diagnosisDetail?.risk?.id === risk?.id ? state.diagnosisDetail : null;
  const factors = detail?.factors || [];
  const factRows = detail?.facts || [];
  const report = detail?.diagnosis;
  const viewTabs = [["list", "滞销库存列表"], ["reasons", "原因分析"], ["actions", "处置建议"], ["stores", "门店分布"]];
  if (!viewTabs.some(([view]) => view === state.diagnosisView)) state.diagnosisView = "list";
  const listMarkup = `<div class="slow-list-tools"><label class="slow-search"><span class="material-symbols-rounded">search</span><input id="slow-search" type="search" value="${escapeHtml(state.diagnosisSearch)}" placeholder="搜索商品名称、SKU 或门店" /></label><select id="slow-priority-filter" aria-label="按优先级筛选"><option value="all">全部优先级</option><option value="P1" ${state.diagnosisPriority === "P1" ? "selected" : ""}>P1 优先核查</option><option value="P2" ${state.diagnosisPriority === "P2" ? "selected" : ""}>P2 高存销</option><option value="P3" ${state.diagnosisPriority === "P3" ? "selected" : ""}>P3 关注</option></select><span>${visibleCandidates.length} / ${displayedCandidateTotal.toLocaleString()} 条</span></div><div class="slow-candidate-table"><div class="slow-candidate-head"><span>商品信息</span><span>门店</span><span>库存数量</span><span>库存金额</span><span>近90天销量</span><span>库存天数</span><span>主要原因</span><span>建议动作</span><span>处理状态</span><span>操作</span></div>${visibleCandidates.map((item) => { const unit = escapeHtml(item.unit || ""); const sales90 = item.sales_90 === null || item.sales_90 === undefined ? "—" : `${Number(item.sales_90).toLocaleString()} ${unit}`; const daysToSell = item.days_to_sell === null || item.days_to_sell === undefined ? "—" : `${Number(item.days_to_sell).toLocaleString()} 天`; return `<div class="slow-candidate-row ${item.id === risk?.id ? "selected" : ""}"><span><strong>${escapeHtml(item.product || "未命名商品")}</strong><small>${escapeHtml(item.sku || "SKU 未知")} · ${unit || "单位未知"}</small></span><span>${escapeHtml(item.store || "门店未知")}</span><span>${Number(item.inventory_qty || 0).toLocaleString()} ${unit}</span><span>${money(riskAmount(item))}</span><span>${sales90}</span><span>${daysToSell}</span><span class="slow-empty-field">—</span><span class="slow-empty-field">—</span><span class="slow-empty-field">—</span><button class="text-link" type="button" data-diagnosis-select="${item.id}">查看计算</button></div>`; }).join("") || '<div class="empty-state">没有符合当前筛选条件的候选记录。</div>'}</div><p class="slow-table-note">近90天销量、库存天数来自当前快照；主要原因、建议动作和处理状态尚无经核查的数据，暂以“—”占位。</p>`;
  const storesMarkup = `<section class="analysis-view"><header class="analysis-view-header"><div><h2>门店分布</h2><p>定位候选库存集中在哪些门店；金额和占比需分开查看。</p></div><div class="analysis-summary"><span><small>涉及门店</small><strong>${stores.length} 家</strong></span><span><small>涉及库存成本</small><strong>${money(candidateAmount)}</strong></span></div></header><div class="analysis-split"><article class="analysis-panel"><header><h3>各门店疑似滞销库存成本</h3><span>按金额</span></header><div class="slow-store-bars large">${topStores.map((store, index) => `<button type="button" data-diagnosis-view="list"><b>${index + 1}</b><span>${escapeHtml(store.name || "未命名门店")}</span><i><em style="width:${Math.max((Number(store.candidate_inventory_value || 0) / maxStoreCandidate) * 100, 4)}%"></em></i><strong>${money(store.candidate_inventory_value)}</strong></button>`).join("") || '<div class="empty-state">没有可展示的门店候选汇总。</div>'}</div></article><article class="analysis-panel store-current"><header><h3>当前门店概览</h3><span>按候选成本最高</span></header><strong>${escapeHtml(topStores[0]?.name || "—")}</strong><p>本店库存成本 ${topStores[0] ? money(topStores[0].inventory_value) : "—"}。</p><div class="store-current-metrics"><span><small>疑似滞销成本</small><b>${topStores[0] ? money(topStores[0].candidate_inventory_value) : "—"}</b></span><span><small>占本店库存</small><b>${topStores[0] && Number(topStores[0].inventory_value || 0) > 0 ? `${((Number(topStores[0].candidate_inventory_value || 0) / Number(topStores[0].inventory_value || 0)) * 100).toFixed(1)}%` : "—"}</b></span><span><small>涉及商品</small><b>${topStores[0] ? Number(topStores[0].slow_moving_skus || 0).toLocaleString() : "—"}</b></span></div><p class="analysis-note">门店表现与滞销成因仍需结合客群、陈列与经营记录核查。</p></article></div><section class="analysis-panel analysis-records"><header><div><h3>门店明细</h3><p>占比为候选库存成本占该门店当前库存成本，不代表门店整体经营评价。</p></div><span>${stores.length} 家门店</span></header><div class="analysis-table-wrap"><div class="analysis-table store-table"><div class="analysis-table-head"><span>门店</span><span>全店库存成本</span><span>疑似滞销成本</span><span>占本店库存</span><span>涉及商品</span><span>核查状态</span><span>操作</span></div>${stores.map((store) => { const share = Number(store.inventory_value || 0) > 0 ? `${((Number(store.candidate_inventory_value || 0) / Number(store.inventory_value || 0)) * 100).toFixed(1)}%` : "—"; return `<div class="analysis-table-row"><strong>${escapeHtml(store.name || "未命名门店")}</strong><span>${money(store.inventory_value)}</span><span>${money(store.candidate_inventory_value)}</span><span>${share}</span><span>${Number(store.slow_moving_skus || 0).toLocaleString()} 条</span><span class="slow-empty-field">—</span><button class="text-link" type="button" data-diagnosis-view="list">查看清单</button></div>`; }).join("") || '<div class="empty-state">当前快照没有可汇总的门店候选数据。</div>'}</div></div></section></section>`;
  const dataMarkup = `<div class="slow-data-grid"><section><span class="section-kicker">已用于计算</span><h3>当前快照可确认的数据</h3><ul><li>门店、SKU、商品单位与库存数量</li><li>库存成本、近 30 天销量、近 90 天销量</li><li>30 天销售成本、统计分类与采购状态</li><li>当前售价与会员价快照（用于留存，不参与本次规则）</li></ul></section><section><span class="section-kicker">待接入后核查</span><h3>当前不能下结论的数据</h3><ul><li>上架、陈列、导购推荐与缺货记录</li><li>历史售价、促销记录和季节销量曲线</li><li>采购订单、在途量、补货规则与补货日志</li><li>批次、有效期与供应商可退条件</li></ul></section></div><p class="slow-table-note">因此本页把“门店客群不匹配、定价不合理、陈列不足、季节变化、采购过量、自动补货”保留为待核查假设，不以当前快照直接判断为事实。</p>`;
  const reasonsMarkup = `<section class="analysis-view"><header class="analysis-view-header"><div><h2>原因分析</h2><p>先看原因线索，再查证据；当前快照尚不能直接确认滞销成因。</p></div><div class="analysis-summary"><span><small>涉及库存成本</small><strong>${money(candidateAmount)}</strong></span><span><small>疑似库存记录</small><strong>${candidateCount.toLocaleString()} 条</strong></span></div></header><div class="analysis-split"><article class="analysis-panel"><header><h3>原因线索分布</h3><span>待核查</span></header><div class="reason-distribution"><div><b>采购偏多</b><i></i><strong>—</strong></div><div><b>门店需求差异</b><i></i><strong>—</strong></div><div><b>陈列或上架问题</b><i></i><strong>—</strong></div><div><b>持续补货</b><i></i><strong>—</strong></div><div><b>季节性因素</b><i></i><strong>—</strong></div><div><b>价格因素</b><i></i><strong>—</strong></div></div><p class="analysis-note">现有快照不包含陈列、价格历史、采购订单或补货日志，不能为商品归因。</p></article><article class="analysis-panel analysis-current"><header><h3>当前选中原因</h3><span>证据状态 —</span></header><strong>主要原因待核查</strong><p>需补充门店客群、陈列、价格、采购及补货记录后，才能确认原因。</p><div class="analysis-steps"><div><b>1</b><span>当前可观察什么</span><small>库存、销量、成本及当前采购状态。</small></div><div><b>2</b><span>还需确认什么</span><small>陈列、价格历史、采购订单、补货规则与日志。</small></div></div><button type="button" class="secondary-action" data-diagnosis-view="list">查看候选清单</button></article></div><section class="analysis-panel analysis-records"><header><div><h3>待核查原因涉及的库存</h3><p>同一商品可能涉及多个待核查方向，原因在完成核查前均以“—”占位。</p></div><span>前 ${Math.min(visibleCandidates.length, 8)} 条</span></header><div class="analysis-table-wrap"><div class="analysis-table reason-table"><div class="analysis-table-head"><span>商品 / SKU</span><span>门店</span><span>库存数量</span><span>库存成本</span><span>近30天销量</span><span>证据状态</span><span>操作</span></div>${visibleCandidates.slice(0, 8).map((item) => { const unit = escapeHtml(item.unit || ""); return `<div class="analysis-table-row"><span><strong>${escapeHtml(item.product || "未命名商品")}</strong><small>${escapeHtml(item.sku || "SKU 未知")}</small></span><span>${escapeHtml(item.store || "门店未知")}</span><span>${Number(item.inventory_qty || 0).toLocaleString()} ${unit}</span><span>${money(riskAmount(item))}</span><span>${item.sales_30 === null || item.sales_30 === undefined ? "—" : `${Number(item.sales_30).toLocaleString()} ${unit}`}</span><span class="slow-empty-field">—</span><button class="text-link" type="button" data-diagnosis-select="${item.id}">查看计算</button></div>`; }).join("") || '<div class="empty-state">当前没有可展示的候选记录。</div>'}</div></div></section></section>`;
  const actionsMarkup = `<section class="analysis-view"><header class="analysis-view-header"><div><h2>处置建议</h2><p>先完成核查再形成调拨、促销、退供或采购刹车方案；建议不代表已执行。</p></div><div class="analysis-summary"><span><small>建议草案</small><strong>—</strong></span><span><small>待核对方案</small><strong>—</strong></span><span><small>需补充条件</small><strong>—</strong></span></div></header><section class="analysis-panel action-panel"><header><div class="action-tabs"><b>全部建议</b><span>跨店调拨 —</span><span>近效期处置 —</span><span>申请退供 —</span><span>采购调整 —</span><span>陈列改善 —</span></div><small>当前未产生可执行建议</small></header><div class="analysis-table-wrap"><div class="analysis-table action-table"><div class="analysis-table-head"><span>商品 / 门店</span><span>建议动作</span><span>本次操作数量</span><span>涉及库存成本</span><span>当前状态</span><span>下一步</span></div>${visibleCandidates.slice(0, 8).map((item) => `<div class="analysis-table-row"><span><strong>${escapeHtml(item.product || "未命名商品")}</strong><small>${escapeHtml(item.store || "门店未知")} · ${escapeHtml(item.sku || "SKU 未知")}</small></span><span class="slow-empty-field">—</span><span class="slow-empty-field">—</span><span>${money(riskAmount(item))}</span><span class="slow-empty-field">—</span><button class="text-link" type="button" data-diagnosis-select="${item.id}">发起核查</button></div>`).join("") || '<div class="empty-state">当前没有可展示的候选记录。</div>'}</div></div><p class="analysis-note">缺少原因核查、批次效期、采购订单、补货和供应商退换条件时，不生成具体处置方案。</p></section></section>`;
  const suppliersMarkup = `<section class="analysis-view"><header class="analysis-view-header"><div><h2>供应商分布</h2><p>按库存的供货来源归属后，才能集中整理退换、返利与协商事项。</p></div><div class="analysis-summary"><span><small>已确认供应商</small><strong>—</strong></span><span><small>来源待确认成本</small><strong>—</strong></span><span><small>涉及库存成本</small><strong>${money(candidateAmount)}</strong></span></div></header><div class="analysis-split"><article class="analysis-panel supplier-empty"><header><h3>疑似滞销库存的供货来源</h3><span>待接入</span></header><span class="material-symbols-rounded">local_shipping</span><strong>供应商字段尚未导入</strong><p>当前源表没有供应商、批次、退换条件或历史进货来源，无法按供应商汇总。</p></article><article class="analysis-panel supplier-empty"><header><h3>当前供应商协同</h3><span>待接入</span></header><span class="material-symbols-rounded">handshake</span><strong>协商对象 —</strong><p>退换货数量、截止日期、退款或换货方式均待接入供应商与采购单数据后确认。</p></article></div><section class="analysis-panel analysis-records"><header><div><h3>供应商明细</h3><p>同一商品可能对应多个供货来源，未接入前不进行归属或金额汇总。</p></div><span>当前无来源数据</span></header><div class="analysis-table-wrap"><div class="analysis-table supplier-table"><div class="analysis-table-head"><span>供应商</span><span>疑似滞销成本</span><span>涉及商品</span><span>涉及门店</span><span>退换条件</span><span>操作</span></div><div class="analysis-table-row"><span class="slow-empty-field">—</span><span class="slow-empty-field">—</span><span class="slow-empty-field">—</span><span class="slow-empty-field">—</span><span class="slow-empty-field">—</span><span class="slow-empty-field">—</span></div></div></div></section></section>`;
  const panelMarkup = state.diagnosisView === "reasons" ? reasonsMarkup : state.diagnosisView === "actions" ? actionsMarkup : state.diagnosisView === "stores" ? storesMarkup : state.diagnosisView === "suppliers" ? suppliersMarkup : listMarkup;
  const detailMarkup = !detail || !risk ? "" : `<section id="slow-calculation-detail" class="slow-calculation-detail"><div class="surface-toolbar"><div><span class="section-kicker">计算明细</span><h2>${escapeHtml(risk.product || "未命名商品")} · ${escapeHtml(risk.store || "门店未知")}</h2><p>${escapeHtml(risk.sku || "SKU 未知")}；以下为已有数据和老师口径计算，不代表形成原因已经确认。</p></div><button class="secondary-action" type="button" data-open-risk="${risk.id}">发起核查</button></div><div class="slow-detail-grid"><section><h3>本次计算依据</h3><div class="fact-source-table"><div><span>数据项</span><span>当前值</span><span>数据来源／口径</span></div>${factRows.map((fact) => `<div><strong>${escapeHtml(fact.label)}</strong><b>${escapeHtml(fact.value)}</b><small>${escapeHtml(fact.source)}<br/>${escapeHtml(fact.source_detail)}</small></div>`).join("")}</div></section><section><h3>待核查形成原因</h3>${factors.map((factor) => `<div class="factor-row"><strong>${escapeHtml(factor.label)}</strong><span class="evidence-badge ${factor.evidence_level}">${escapeHtml(factor.evidence_label)}</span><small>${factor.basis?.length ? `现有依据：${escapeHtml(factor.basis.join("、"))}。` : "当前没有直接依据。"}<br/>缺少：${escapeHtml((factor.missing_fields || []).map(missingLabel).join("、"))}。</small></div>`).join("")}</section></div><section class="diagnosis-next"><span class="material-symbols-rounded">arrow_forward</span><div><strong>建议下一步</strong><p>${escapeHtml(report?.suggested_next_step || "先补齐证据，再选择调拨、促销、退供或采购刹车。")}</p></div></section></section>`;

  target.innerHTML = `<div class="slow-dashboard-shell"><section class="slow-kpi-grid"><article class="slow-kpi candidates"><span class="material-symbols-rounded">inventory_2</span><div><small>疑似滞销商品</small><strong>${candidateCount.toLocaleString()}</strong><em>按老师口径形成的库存候选</em></div></article><article class="slow-kpi inventory"><span class="material-symbols-rounded">layers</span><div><small>滞销库存金额</small><strong>${money(candidateAmount)}</strong><em>候选记录对应的当前库存成本</em></div></article><article class="slow-kpi expiry-pending"><span class="material-symbols-rounded">timer</span><div><small>近效期滞销商品</small><strong>待接入</strong><em>需接入批次与有效期数据</em></div></article><article class="slow-kpi replenishment-pending"><span class="material-symbols-rounded">shopping_cart</span><div><small>仍在自动补货</small><strong>待接入</strong><em>需接入补货规则与补货日志</em></div></article></section><section class="slow-insight-grid"><article class="slow-card priority-card"><header><div><h2>候选优先级结构</h2><p>按老师规则形成的候选分层；建议压降 ${money(suggestedReduction)}，非已回收现金。</p></div><span>目标存销比 3</span></header><div class="priority-track">${priorityRows.map(([priority, count]) => `<i class="${priority.toLowerCase()}" style="width:${(Number(count) / priorityTotal) * 100}%"></i>`).join("")}</div><div class="priority-legend">${priorityRows.map(([priority, count, note]) => `<div><b class="slow-priority ${priority.toLowerCase()}">${priority}</b><strong>${Number(count).toLocaleString()}</strong><small>${escapeHtml(note)}</small></div>`).join("")}</div></article><article class="slow-card store-ranking-card"><header><div><h2>各门店候选库存金额 Top 10</h2><p>按门店候选库存成本排序。</p></div><button type="button" class="text-link" data-diagnosis-view="stores">查看全部</button></header><div class="slow-store-bars">${topStores.map((store, index) => `<button type="button" data-diagnosis-view="stores"><b>${index + 1}</b><span>${escapeHtml(store.name || "未命名门店")}</span><i><em style="width:${Math.max((Number(store.candidate_inventory_value || 0) / maxStoreCandidate) * 100, 4)}%"></em></i><strong>${(Number(store.candidate_inventory_value || 0) / 10000).toFixed(1)}万</strong></button>`).join("") || '<div class="empty-state">没有可展示的门店候选汇总。</div>'}</div></article><article class="slow-card trend-card"><header><div><h2>滞销商品趋势</h2><p>连续导入快照后生成环比趋势。</p></div><span>近6个月</span></header><div class="trend-empty"><span class="material-symbols-rounded">show_chart</span><strong>趋势待形成</strong><p>当前仅有 1 期库存快照，下一次月度导入后开始积累趋势。</p></div><div class="trend-current"><span><small>本期疑似商品</small><b>${candidateCount.toLocaleString()} 条</b></span><span><small>本期滞销库存金额</small><b>${money(candidateAmount)}</b></span></div></article></section><section class="slow-list-card"><div class="slow-list-tabs" role="tablist" aria-label="滞销库存分析视图">${viewTabs.map(([view, label]) => `<button type="button" role="tab" aria-selected="${state.diagnosisView === view}" class="${state.diagnosisView === view ? "active" : ""}" data-diagnosis-view="${view}">${label}</button>`).join("")}</div><div class="slow-list-panel">${panelMarkup}</div></section>${detailMarkup}</div>`;

  $$('[data-diagnosis-view]', target).forEach((button) => button.addEventListener("click", () => { state.diagnosisView = button.dataset.diagnosisView; renderDiagnosis(); }));
  $("#slow-search", target)?.addEventListener("input", (event) => { state.diagnosisSearch = event.target.value; renderDiagnosis(); $("#slow-search", target)?.focus(); });
  $("#slow-priority-filter", target)?.addEventListener("change", async (event) => { state.diagnosisPriority = event.target.value; state.diagnosisSearch = ""; await loadDiagnosisCandidates(); });
  $$('[data-diagnosis-select]', target).forEach((button) => button.addEventListener("click", async () => { await loadDiagnosisReport(button.dataset.diagnosisSelect); requestAnimationFrame(() => $("#slow-calculation-detail")?.scrollIntoView({ behavior: "smooth", block: "start" })); }));

}

function renderAgentModules() {
  Object.entries(agentModules).forEach(([route, module]) => {
    const risks = scopedRisks().filter(module.match), amount = risks.reduce((total, risk) => total + riskAmount(risk), 0);
    const teacherCount = module === agentModules["slow-diagnosis"] ? state.dashboard?.teacher_baseline?.candidate_count : null;
    const teacherAmount = module === agentModules["slow-diagnosis"] ? state.dashboard?.teacher_baseline?.candidate_inventory_amount : null;
    const nodes = [$(`#${module.countId}`), $(`#${module.amountId}`), $(`#${module.navCountId}`), $(`#${module.overviewCountId}`)];
    if (nodes[0]) nodes[0].textContent = teacherCount ?? risks.length;
    if (nodes[1]) nodes[1].textContent = money(teacherAmount ?? amount);
    if (nodes[2]) nodes[2].textContent = teacherCount ?? risks.length;
    if (nodes[3]) nodes[3].textContent = teacherCount ?? risks.length;
  });
  renderDiagnosis();
  ["transfer", "expiry-rescue", "procurement-brake"].forEach(renderWorkbench);
}

function renderOperatingOverview() {
  const summary = state.dashboard?.operating_summary || {};
  const overview = document.querySelector('[data-view="overview"]');
  overview.classList.toggle("is-unavailable", requests.get("dashboard").status !== "ready");
  let notice = overview.querySelector(".page-resource-notice");
  if (!notice) { notice = document.createElement("div"); notice.className = "page-resource-notice"; overview.prepend(notice); }
  notice.innerHTML = requests.get("dashboard").status !== "ready" ? resourceNotice("dashboard") : "";
  const isRealSnapshot = Boolean(summary.mixed_units);
  const district = { all: null, "west-lake": "西湖", shangcheng: "上城", gongshu: "拱墅", yuhang: "余杭", linping: "临平", binjiang: "滨江", xiaoshan: "萧山", qiantang: "钱塘", fuyang: "富阳" }[state.region] || null;
  const stores = (summary.stores || []).filter((store) => !district || store.district === district).sort((left, right) => Number(right.inventory_value || 0) - Number(left.inventory_value || 0));
  const totalValue = stores.reduce((total, store) => total + Number(store.inventory_value || 0), 0);
  const expiry = stores.reduce((total, store) => total + Number(store.near_expiry_lots || 0), 0);
  const transfers = stores.reduce((total, store) => total + Number(store.transfer_suggestions || 0), 0);
  const slow = stores.reduce((total, store) => total + Number(store.slow_moving_skus || 0), 0);
  const scopedAttention = scopedRisks().reduce((total, risk) => total + riskAmount(risk), 0);
  const attentionRaw = state.region === "all" ? (state.dashboard?.attention_inventory_cost ?? (isRealSnapshot ? null : scopedAttention)) : scopedAttention;
  const attention = attentionRaw == null ? null : Number(attentionRaw);
  const otherInventory = attention == null ? null : Math.max(totalValue - attention, 0);
  const attentionRate = attention == null ? null : (totalValue ? Math.min(Math.round((attention / totalValue) * 1000) / 10, 100) : 0);
  const attentionTitle = isRealSnapshot ? "疑似滞销库存" : "已识别需关注库存";
  const attentionDescription = isRealSnapshot ? "按库存成本计，占总库存" : "占总库存";
  const riskAttentionByStore = scopedRisks().reduce((amounts, risk) => {
    const storeName = String(risk.store || "");
    amounts.set(storeName, (amounts.get(storeName) || 0) + riskAmount(risk));
    return amounts;
  }, new Map());
  const storeAttention = (store) => isRealSnapshot
    ? Number(store.candidate_inventory_value || 0)
    : Number(riskAttentionByStore.get(store.name) || 0);
  const maxStoreValue = Math.max(...stores.map((store) => Number(store.inventory_value || 0)), 1);
  const topStores = stores.slice(0, 10);
  const chartStores = state.overviewShowAllStores ? stores : topStores;
  const selectedStore = stores.find((store) => store.name === state.overviewSelectedStore);
  const detailStores = selectedStore ? [selectedStore] : topStores;
  const regionLabel = district ? `${district}区区域` : (summary.region_label || "当前全部门店");
  $("#profile-region-name").textContent = regionLabel;
  const regionSelect = $("#region-select");
  if (regionSelect && isRealSnapshot && state.region === "all") {
    const selectedOption = regionSelect.options[0];
    if (selectedOption) selectedOption.textContent = regionLabel;
  }
  if (regionSelect) regionSelect.disabled = isRealSnapshot;
  $("#overview-total-inventory").textContent = moneyWan(totalValue);
  $("#overview-store-count").textContent = `当前导入范围：${stores.length} 家门店`;
  $("#overview-attention-title").textContent = attentionTitle;
  $("#overview-attention-status").hidden = !isRealSnapshot || attention == null;
  $("#overview-attention-detail").textContent = attentionDescription;
  $("#overview-attention").textContent = moneyWan(attention);
  $("#overview-attention-rate").textContent = attentionRate == null ? "暂无可计算占比" : `${attentionRate}%`;
  $("#overview-season-purchase").textContent = summary.season_purchase_amount == null ? "待补充" : money(summary.season_purchase_amount);
  $("#overview-season-label").textContent = summary.season_purchase_amount == null ? "未导入采购数据" : (summary.season_label || "本季度");
  $("#overview-expiry-lots").textContent = summary.near_expiry_lots == null ? "待补充" : `${expiry} 批`;
  $("#overview-expiry-label").textContent = summary.near_expiry_lots == null ? "需导入批次与有效期数据" : "需在处置窗口内确认";
  $("#overview-transfer-suggestions").textContent = summary.transfer_suggestions == null ? "待补充" : `${transfers} 项`;
  $("#overview-transfer-label").textContent = summary.transfer_suggestions == null ? "需导入门店需求与调拨约束" : "有跨店需求匹配机会";
  $("#overview-slow-skus").textContent = `${slow.toLocaleString()} 条`;
  $("#overview-slow-label").textContent = isRealSnapshot ? "依据导入表标记，成因待核查" : "当前记录需核查成因与处置条件";
  $("#overview-store-caption").textContent = `${summary.source_label || "经营快照"}；按库存总成本排序。`;
  $("#overview-store-detail-caption").textContent = selectedStore
    ? `已按“${selectedStore.name}”筛选；可清除筛选返回 Top 10。`
    : `${summary.source_label || "经营快照"}；默认展示库存成本最高的 10 家门店。`;
  $("#overview-store-total").textContent = selectedStore ? `已筛选 1 / ${stores.length} 家` : `Top ${Math.min(10, stores.length)} / ${stores.length} 家`;
  const toggleChart = $("#overview-toggle-store-chart");
  toggleChart.innerHTML = `${state.overviewShowAllStores ? "仅看 Top 10" : `查看全部 ${stores.length} 家`} <span class="material-symbols-rounded">arrow_forward</span>`;
  toggleChart.disabled = stores.length <= 10;
  $("#overview-clear-store-filter").hidden = !selectedStore;
  $("#overview-attention-chart-label").textContent = attentionTitle;
  $("#overview-attention-share-title").textContent = `${attentionTitle}占比`;
  $("#overview-funds-ring-label").textContent = `${attentionTitle}占比`;
  $("#overview-attention-legend-label").textContent = attentionTitle;
  $("#overview-attention-legend").textContent = attention == null ? "—" : money(attention);
  $("#overview-attention-method").textContent = attention == null ? "当前缺少可识别的规则数据" : (isRealSnapshot ? "依据导入表标记；成因待核查" : "当前规则已识别");
  $("#overview-other-inventory").textContent = otherInventory == null ? "—" : money(otherInventory);
  $("#overview-other-rate").textContent = attentionRate == null ? "—" : `${Math.max(100 - attentionRate, 0)}%`;
  $("#overview-funds-rate").textContent = attentionRate == null ? "—" : `${attentionRate}%`;
  $("#overview-funds-note").textContent = `“${attentionTitle}”按当前导入数据标记，反映库存成本，不是预计可回收现金。`;
  $("#overview-funds-ring").style.setProperty("--attention-share", `${attentionRate == null ? 0 : attentionRate}%`);
  const chart = $("#overview-store-bars");
  chart.classList.toggle("show-all", state.overviewShowAllStores);
  chart.innerHTML = chartStores.map((store) => {
    const height = Math.max(Math.round((Number(store.inventory_value || 0) / maxStoreValue) * 100), 8);
    const isSelected = store.name === state.overviewSelectedStore;
    const attentionValue = Math.min(storeAttention(store), Number(store.inventory_value || 0));
    const storeAttentionRate = Number(store.inventory_value || 0) ? (attentionValue / Number(store.inventory_value || 0)) * 100 : 0;
    const label = `${store.name}：库存成本 ${money(store.inventory_value)}，${attentionTitle} ${money(attentionValue)}，占 ${storeAttentionRate.toFixed(1)}%`;
    return `<button class="store-cost-bar ${isSelected ? "selected" : ""}" data-overview-store="${escapeHtml(store.name)}" aria-pressed="${isSelected}" aria-label="${escapeHtml(label)}" title="筛选 ${escapeHtml(store.name)} 的门店明细"><span>${(Number(store.inventory_value || 0) / 10000).toFixed(1)}</span><i style="height:${height}%"><em style="height:${storeAttentionRate}%"></em></i><b>${escapeHtml(store.name)}</b></button>`;
  }).join("") || '<div class="empty-state">当前区域没有门店经营快照。</div>';
  $("#overview-store-list").innerHTML = detailStores.map((store) => {
    const attentionValue = Math.min(storeAttention(store), Number(store.inventory_value || 0));
    const storeAttentionRate = Number(store.inventory_value || 0) ? `${((attentionValue / Number(store.inventory_value || 0)) * 100).toFixed(1)}%` : "—";
    const signal = (label, value, unit) => value === null || value === undefined ? "" : `<span class="${value ? "is-risk" : ""}">${label} ${value ? `${value} ${unit}` : "—"}</span>`;
    const signals = [
      signal("近效期", store.near_expiry_lots, "批"),
      signal("调拨", store.transfer_suggestions, "项"),
      signal(isRealSnapshot ? "候选" : "滞销", store.slow_moving_skus, "条"),
    ].filter(Boolean).join("") || "<span>—</span>";
    return `<div class="store-overview-row"><strong>${escapeHtml(store.district)} · ${escapeHtml(store.name)}</strong><b>${money(store.inventory_value)}</b><b class="attention-amount">${money(attentionValue)}</b><span class="attention-rate">${storeAttentionRate}</span><span class="store-signals">${signals}</span><button class="overview-detail-link" data-go="slow-diagnosis">查看详情 <span class="material-symbols-rounded">arrow_forward</span></button></div>`;
  }).join("") || '<div class="empty-state">当前区域没有门店经营快照。</div>';
}

function todayDetailCacheKey(item) {
  return item?.route && item?.risk_id ? `${item.route}:${item.risk_id}` : "";
}

function todayActionText(item, risk, input = {}) {
  if (item?.route === "transfer") return `确认调拨 ${input.quantity || 40} 件至 ${input.target_store || "推荐接收门店"}`;
  if (item?.route === "expiry-rescue") return "确认调拨、促销与退供的处置数量";
  if (item?.route === "procurement-brake") return "确认暂停、减量或延期到货的采购方案";
  if (item?.route === "approvals") return "确认方案版本、执行边界与负责人";
  if (risk?.risk_type === "退供") return "确认供应商退换条件与可退数量";
  return item?.action_label || "进入方案处理";
}

function todayProgressMarkup(item) {
  const approvalActive = item.status === "待审批";
  const executionActive = ["待出库", "在途", "待收货"].includes(item.status);
  const received = ["已收货", "completed", "received"].includes(item.status);
  const steps = [["核对方案", !approvalActive && !executionActive && !received], ["提交审批", approvalActive], ["门店执行", executionActive], ["确认结果", received]];
  return `<ol class="today-progress">${steps.map(([label, active], index) => `<li class="${active ? "active" : ""} ${received || (executionActive && index < 2) || (approvalActive && index < 1) ? "done" : ""}"><span>${index + 1}</span><b>${label}</b></li>`).join("")}</ol>`;
}

function todayTransferDetail(item, risk, detail) {
  const input = detail?.input || {};
  const calc = detail?.calculation || {};
  const before = calc.before_after || {};
  const economic = calc.economic || {};
  const cash = calc.cash || {};
  const quantity = input.quantity || "—";
  const source = before.source || {};
  const target = before.target || {};
  const loading = requests.get(`today:${todayDetailCacheKey(item)}`).status === "loading";
  return `<div class="today-detail-inner transfer-task-detail">
    <div class="today-detail-top"><span class="priority-badge urgent"><span class="material-symbols-rounded">priority_high</span>${escapeHtml(item.priority || "紧急")}</span><small>任务编号 #${escapeHtml(item.id)}</small><span class="today-status">${escapeHtml(item.status)}</span></div>
    <h2>${escapeHtml(risk?.store || input.source_store || "调出门店")} · ${escapeHtml(risk?.product || input.product || "调拨商品")}</h2>
    <h3>${escapeHtml(todayActionText(item, risk, input))}</h3>
    <p class="today-detail-reason">${escapeHtml(item.reason)}</p>
    <div class="today-decision-metrics">
      <div><span>当前库存</span><strong>${input.source_on_hand ?? risk?.inventory_qty ?? "—"} 件</strong><small>库存成本 ${money((input.source_on_hand ?? risk?.inventory_qty ?? 0) * Number(input.unit_cost ?? risk?.unit_cost ?? 0))}</small></div>
      <div><span>建议调拨数量</span><strong class="positive-number">${quantity} 件</strong><small>调拨库存成本 ${money(cash.inventory_cost ?? Number(quantity || 0) * Number(input.unit_cost ?? risk?.unit_cost ?? 0))}</small></div>
      <div><span>不调拨的报损风险</span><strong class="danger-number">${money(economic.potential_loss_without_transfer)}</strong><small>${economic.source_surplus_at_deadline_qty ?? "—"} 件可能无法及时售完</small></div>
      <div><span>执行后覆盖天数</span><strong>${source.coverage_after ?? "—"} 天</strong><small>调出店从 ${source.coverage_before ?? "—"} 天降至目标范围</small></div>
    </div>
    ${todayProgressMarkup(item)}
    <section class="today-plan-section">
      <div class="today-section-title"><div><span class="material-symbols-rounded">swap_horiz</span><h3>调拨方案</h3></div><button class="text-link" data-go="transfer" data-workbench-risk="${escapeHtml(item.workbench_risk_id || "")}">查看完整方案 <span class="material-symbols-rounded">arrow_forward</span></button></div>
      <div class="today-transfer-pair"><div><span>调出门店</span><strong>${escapeHtml(input.source_store || risk?.store || "—")}</strong><small>调前 ${source.on_hand_before ?? input.source_on_hand ?? "—"} 件 · 安全库存 ${source.safety_stock ?? input.source_safety ?? "—"} 件</small></div><span class="material-symbols-rounded transfer-arrow">arrow_forward</span><div><span>调入门店</span><strong>${escapeHtml(input.target_store || "推荐接收门店")}</strong><small>调前 ${target.on_hand_before ?? input.target_on_hand ?? "—"} 件 · 近30日预估日销 ${target.daily_sales ?? input.target_daily_sales ?? "—"} 件</small></div><div><span>配送费用</span><strong>${money(input.transport_fee)}</strong><small>预计 ${input.eta_days ?? "—"} 天内到店</small></div></div>
      <div class="today-route-map"><img src="assets/today-transfer-route-map.png" alt="西湖文三店至余杭未来店的同城配送路线示意" /><span class="route-store source">${escapeHtml(input.source_store || risk?.store || "调出门店")}</span><span class="route-store target">${escapeHtml(input.target_store || "推荐接收门店")}</span><small>配送路径示意 · ${loading ? "正在读取最新测算…" : `${input.eta_days ?? "—"} 天内到店`}</small></div>
      <p class="today-boundary"><span class="material-symbols-rounded">info</span>预计避免报损 ${money(economic.avoided_loss)}；扣除配送费后的净经营影响为 ${money(economic.net_avoidable_loss)}。这不是调拨盈利或现金回款。</p>
    </section>
    <footer class="today-detail-actions"><button class="secondary-action" data-go="transfer" data-workbench-risk="${escapeHtml(item.workbench_risk_id || "")}">修改方案</button><button class="primary-action" data-go="transfer" data-workbench-risk="${escapeHtml(item.workbench_risk_id || "")}">进入调拨方案</button></footer>
  </div>`;
}

function todayGenericDetail(item, risk, detail) {
  const input = detail?.input || {};
  const inventoryCost = risk ? riskAmount(risk) : null;
  const isApproval = item.status === "待审批";
  return `<div class="today-detail-inner generic-task-detail">
    <div class="today-detail-top"><span class="priority-badge ${item.priority === "紧急" ? "urgent" : ""}">${escapeHtml(item.priority || "一般")}</span><small>任务编号 #${escapeHtml(item.id)}</small><span class="today-status">${escapeHtml(item.status)}</span></div>
    <h2>${escapeHtml(item.title)}</h2><h3>${escapeHtml(todayActionText(item, risk, input))}</h3>
    <p class="today-detail-reason">${escapeHtml(item.reason)}</p>
    <div class="today-decision-metrics generic">
      <div><span>当前库存</span><strong>${risk?.inventory_qty ?? "—"} 件</strong><small>${risk?.store || "对应门店"}</small></div>
      <div><span>库存成本</span><strong>${money(inventoryCost)}</strong><small>当前库存占用，不是收益</small></div>
      <div><span>建议处理时间</span><strong>${escapeHtml(item.due_date || "今天")}</strong><small>负责人：${escapeHtml(item.owner || "待分配")}</small></div>
      <div><span>${isApproval ? "审批后动作" : "下一步"}</span><strong>${isApproval ? "生成执行任务" : "进入方案确认"}</strong><small>${isApproval ? "不会自动修改 ERP 订单" : "修改后需要重新计算"}</small></div>
    </div>
    ${todayProgressMarkup(item)}
    <section class="today-plan-section generic-plan"><div class="today-section-title"><div><span class="material-symbols-rounded">fact_check</span><h3>为什么现在处理</h3></div><span class="evidence-badge">${escapeHtml(item.type || "业务任务")}</span></div><p>${escapeHtml(item.reason)}</p><div class="today-next-action"><span class="material-symbols-rounded">check_circle</span><div><strong>建议动作</strong><p>${escapeHtml(todayActionText(item, risk, input))}</p></div></div>${item.boundary ? `<p class="today-boundary"><span class="material-symbols-rounded">info</span>${escapeHtml(item.boundary)}</p>` : ""}</section>
    <footer class="today-detail-actions"><button class="secondary-action" data-go="${escapeHtml(item.route || "tasks")}" data-workbench-risk="${escapeHtml(item.workbench_risk_id || "")}">查看依据</button><button class="primary-action" data-go="${escapeHtml(item.route || "tasks")}" data-workbench-risk="${escapeHtml(item.workbench_risk_id || "")}">${escapeHtml(item.action_label || "开始处理")}</button></footer>
  </div>`;
}

async function queueTodayWorkbench(item) {
  const key = todayDetailCacheKey(item);
  const resource = `today:${key}`;
  if (!key || !WORKBENCH_ROUTES.includes(item?.route) || requests.get(resource).status !== "idle") return;
  await readResource(resource, `/workbenches/${item.route}?risk_id=${item.risk_id}`, (data) => { state.todayWorkbenchCache[key] = data; }, "今日任务方案");
  renderSupportPages();
}

function renderSupportPages() {
  const dashboard = state.dashboard || {};
  const regionalAttention = scopedRisks().reduce((total, risk) => total + riskAmount(risk), 0);
  const attention = state.region === "all" ? (dashboard.attention_inventory_cost ?? regionalAttention) : regionalAttention;
  const regionalRiskIds = new Set(scopedRisks().map((risk) => Number(risk.id)));
  const actionItems = state.workItems.filter((item) => !item.risk_id || regionalRiskIds.has(Number(item.risk_id)));
  const pendingItems = actionItems.filter((item) => item.status !== "待审批" && !["received", "completed"].includes(item.status));
  const approvalItems = actionItems.filter((item) => item.status === "待审批");
  const completedItems = state.executionTasks.filter((item) => ["received", "completed"].includes(item.status));
  const pendingActions = pendingItems.length;
  const pendingApprovals = state.proposals.filter((item) => item.status === "pending_approval").length || dashboard.pending_approvals || 0;
  const todayItems = [...pendingItems, ...approvalItems];
  renderAgentModules();
  renderOperatingOverview();
  $("#today-attention").textContent = money(attention);
  $("#today-tasks").textContent = pendingActions;
  $("#today-approvals").textContent = pendingApprovals;
  $("#today-completed").textContent = completedItems.length;
  $("#today-nav-count").textContent = pendingActions + pendingApprovals;
  const taskNavCount = $("#task-nav-count");
  const approvalNavCount = $("#approval-nav-count");
  if (taskNavCount) taskNavCount.textContent = pendingActions;
  if (approvalNavCount) approvalNavCount.textContent = pendingApprovals;
  $("#task-page-count").textContent = `${todayItems.length} 项任务`;

  const todayFilters = { pending: pendingItems, approval: approvalItems, completed: completedItems.map((task) => ({ ...task, title: `执行任务 ${task.id}`, route: "execution", action_label: "查看执行回执" })) };
  const visibleTodayItems = todayFilters[state.todayFilter] || pendingItems;
  if (!visibleTodayItems.some((item) => item.id === state.todaySelectedItemId)) state.todaySelectedItemId = visibleTodayItems[0]?.id || null;
  const selectedTodayItem = visibleTodayItems.find((item) => item.id === state.todaySelectedItemId) || null;
  const selectedTodayRisk = state.risks.find((risk) => Number(risk.id) === Number(selectedTodayItem?.risk_id));
  const selectedTodayDetail = state.todayWorkbenchCache[todayDetailCacheKey(selectedTodayItem)];
  $("#today-header-copy").textContent = `${pendingActions} 项待我处理，${pendingApprovals} 项等待审批。按紧急程度和建议处理时间排序。`;
  $("#today-pending-tab-count").textContent = pendingItems.length;
  $("#today-approval-tab-count").textContent = approvalItems.length;
  $("#today-completed-tab-count").textContent = completedItems.length;
  $("#today-order-note").textContent = state.todayFilter === "pending" ? "按紧急程度和建议处理时间排序" : state.todayFilter === "approval" ? "只展示需要负责人拍板的方案" : "已完成任务会保留在执行追踪中";
  $("#today-list").innerHTML = visibleTodayItems.map((item, index) => `
    <button class="today-task-row ${item.id === state.todaySelectedItemId ? "selected" : ""}" type="button" data-today-select="${escapeHtml(item.id)}">
      <span class="work-rank" aria-label="处理顺序第 ${index + 1} 项">${index + 1}</span>
      <span class="today-task-copy"><span><i class="priority-badge ${item.priority === "紧急" ? "urgent" : ""}">${escapeHtml(item.priority || "一般")}</i><strong>${escapeHtml(item.title)}</strong></span><small>${escapeHtml(todayActionText(item, state.risks.find((risk) => Number(risk.id) === Number(item.risk_id))))}</small><em>${escapeHtml(item.impact || "进入方案查看金额与约束")}</em></span>
      <span class="today-task-deadline">建议 ${escapeHtml(item.due_date || "今天")}<span class="material-symbols-rounded">chevron_right</span></span>
    </button>`).join("") || `<div class="empty-state">${state.todayFilter === "completed" ? "今天还没有完成的任务；完成后会保留在执行追踪中。" : "当前区域没有这类任务。"}</div>`;
  $("#today-detail").innerHTML = selectedTodayItem
    ? (selectedTodayItem.route === "transfer" ? todayTransferDetail(selectedTodayItem, selectedTodayRisk, selectedTodayDetail) : todayGenericDetail(selectedTodayItem, selectedTodayRisk, selectedTodayDetail))
    : '<div class="today-detail-empty"><span class="material-symbols-rounded">task_alt</span><h2>当前没有可查看的任务</h2><p>切换“待我处理”或“等待审批”查看今天需要推进的事项。</p></div>';
  const todayKey = `today:${todayDetailCacheKey(selectedTodayItem)}`;
  if (selectedTodayItem && requests.get(todayKey).status === "error") $("#today-detail").innerHTML = resourceNotice(todayKey);
  if (selectedTodayItem && currentRoute() === "today") queueTodayWorkbench(selectedTodayItem);

  $("#task-list").innerHTML = todayItems.map((item) => `
    <div class="task-row">
      <div><strong>${escapeHtml(item.title)}</strong><p>负责人：${escapeHtml(item.owner)} · 建议处理时段：${escapeHtml(item.due_date || "今天")}</p></div>
      <div><strong>${escapeHtml(item.reason)}</strong><p>${escapeHtml(item.impact || "进入方案后查看库存、现金与执行影响")}</p></div>
      <span class="evidence-badge">${escapeHtml(item.status)}</span>
      ${item.route ? `<button class="secondary-action" data-go="${item.route}" data-workbench-risk="${item.workbench_risk_id || ""}">${escapeHtml(item.action_label || "进入处理")}</button>` : '<span></span>'}
    </div>`).join("") || '<div class="empty-state">当前区域没有待推进的业务动作。</div>';

  renderApprovalList();
  renderExecutionList();
  renderDataCenter();
  if (requests.get("workItems").status !== "ready") {
    $("#today-list").innerHTML = resourceNotice("workItems");
    $("#today-detail").innerHTML = resourceNotice("workItems");
    $("#task-list").innerHTML = resourceNotice("workItems");
  }
}

function renderApprovalList() {
  const target = $("#approval-list"); if (!target) return;
  if (requests.get("proposals").status !== "ready") { target.innerHTML = resourceNotice("proposals"); return; }
  const items = state.proposals.filter((proposal) => ["pending_approval", "approved", "needs_replan", "execution_task_created"].includes(proposal.status));
  $("#approval-page-count").textContent = `${items.length} 项`;
  target.innerHTML = items.map((proposal) => {
    const summary = proposal.approval_summary || { title: `处置方案 ${proposal.id}`, detail: "确认当前事实与计算版本后再进入执行。", boundary: "审批仅绑定当前版本。" };
    return `<div class="task-row"><div><strong>${escapeHtml(summary.title)}</strong><p>${escapeHtml(summary.detail)}</p></div><div><strong>${escapeHtml(proposal.status === "pending_approval" ? "等待负责人确认" : proposal.status)}</strong><p>${escapeHtml(proposal.status === "needs_replan" ? "事实或输入已变更，旧审批不可沿用" : summary.boundary)}</p></div><span class="evidence-badge">V${proposal.current_version}</span>${proposal.status === "pending_approval" ? `<button class="secondary-action" data-approve-proposal="${proposal.id}">确认并审批</button>` : proposal.status === "approved" ? `<button class="secondary-action" data-execute-proposal="${proposal.id}">生成执行任务</button>` : "<span></span>"}</div>`;
  }).join("") || '<div class="empty-state">暂无待审批或待执行的方案版本。</div>';
  $$("[data-approve-proposal]", target).forEach((button) => button.addEventListener("click", () => approveProposal(button.dataset.approveProposal)));
  $$("[data-execute-proposal]", target).forEach((button) => button.addEventListener("click", () => executeProposal(button.dataset.executeProposal)));
}

async function approveProposal(id) {
  const proposal = state.proposals.find((item) => item.id === id);
  if (!proposal || proposal.status !== "pending_approval") return;
  await performAction(`approval:${id}`, "人工审批", () => api(`/proposals/${id}/approve`, { method: "POST", headers: { "Idempotency-Key": `ui-approve-${id}-v${proposal.current_version}` } }), async () => {
    await refreshCommonRecords(); showToast("当前方案版本已审批；下一步可生成执行草稿");
  });
}

async function executeProposal(id) {
  const proposal = state.proposals.find((item) => item.id === id);
  if (!proposal || proposal.status !== "approved") return;
  await performAction(`execute:${id}`, "生成执行草稿", () => api(`/proposals/${id}/execute`, { method: "POST", headers: { "Idempotency-Key": `ui-execute-${id}-v${proposal.current_version}` } }), async () => {
    await refreshCommonRecords(); showToast("执行草稿已生成，待人工在原系统执行并回填回执");
  });
}

function renderExecutionList() {
  const target = $("#execution-list");
  if (requests.get("executionTasks").status !== "ready") { target.innerHTML = resourceNotice("executionTasks"); return; }
  const statuses = { draft_pending_external_execution: "待原系统执行（草稿）", pending_dispatch: "待出库", in_transit: "在途", awaiting_receipt: "待收货", received: "已收货", completed: "已完成", exception: "异常 / 待人工核对" };
  $("#execution-page-count").textContent = `${state.executionTasks.length} 项`;
  target.innerHTML = state.executionTasks.map((task) => `<div class="execution-row"><div><strong>${escapeHtml(task.id)}</strong><p>方案 ${escapeHtml(task.proposal_id)} · V${escapeHtml(task.proposal_version)} · ${escapeHtml(statuses[task.status] || task.status)}</p><div class="timeline-mini">${(task.metadata?.timeline || []).map((event) => `<span>${escapeHtml(statuses[event.status] || event.status)} · ${escapeHtml(event.at)}</span>`).join("") || "<span>已生成草稿，尚未执行外部操作</span>"}</div></div><form data-execution-form="${escapeHtml(task.id)}"><label>更新状态<select name="status">${Object.entries(statuses).filter(([value]) => value !== "draft_pending_external_execution").map(([value,label]) => `<option value="${value}">${label}</option>`).join("")}</select></label><label>回执号（收货/完成必填）<input name="receipt_ref" placeholder="外部单据或签收回执" /></label><button class="secondary-action" type="submit">记录状态</button><p class="execution-error" role="status"></p></form></div>`).join("") || '<div class="empty-state">暂无执行任务。审批后可生成待原系统执行的草稿。</div>';
  $$("[data-execution-form]", target).forEach((form) => {
    const receipt = $("[name=receipt_ref]", form);
    $("[name=status]", form).addEventListener("change", (event) => { receipt.required = ["received", "completed"].includes(event.target.value); });
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!form.reportValidity()) return;
      const values = formInput(form), id = form.dataset.executionForm;
      $$("button, input, select", form).forEach((node) => { node.disabled = true; });
      const ok = await performAction(`receipt:${id}`, "记录人工执行回执", () => api(`/execution-tasks/${id}/status`, { method: "POST", body: JSON.stringify(values) }), async () => { await refreshCommonRecords(); showToast("状态与回执已记录"); });
      if (!ok && form.isConnected) {
        $(".execution-error", form).textContent = errorCopy(requests.get(`receipt:${id}`).error);
        $$("button, input, select", form).forEach((node) => { node.disabled = false; });
      }
    });
  });
}

function renderDataCenter() {
  const source = $("#data-sources"), history = $("#import-history");
  if (requests.get("dataCenter").status !== "ready") {
    source.innerHTML = resourceNotice("dataCenter"); history.innerHTML = "";
    $("#data-import-form button[type=submit]").disabled = true;
    return;
  }
  $("#data-import-form button[type=submit]").disabled = false;
  const view = buildDataCenterView({ data: state.dataCenter, search: state.analysisSearch, status: state.analysisStatus, sort: state.analysisSort, kind: $("#import-kind").value, escapeHtml, money });
  source.innerHTML = view.sourcesHtml;
  history.innerHTML = view.historyHtml;
  $("#import-requirements").innerHTML = view.requirementsHtml;
  $("#analysis-count").textContent = `共 ${view.count} 条校验记录`;
}

function fileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
    reader.onerror = () => reject(new Error("文件读取失败"));
    reader.readAsDataURL(file);
  });
}

async function refreshCommonRecords() {
  // The backend owns one SQLite connection. Reads remain independent in state.
  for (const key of ["health", "workItems", "proposals", "executionTasks", "dataCenter"]) {
    const loader = RESOURCE_LOADERS[key];
    await readResource(key, loader.path, loader.apply, loader.label);
  }
  renderSupportPages();
}

async function hydrate() {
  const epoch = state.datasetEpoch;
  for (const [key, loader] of Object.entries(RESOURCE_LOADERS)) {
    await readResource(key, loader.path, loader.apply, loader.label);
    if (epoch !== state.datasetEpoch) return false;
  }
  if (!state.risks.some((risk) => Number(risk.id) === Number(state.selectedId))) state.selectedId = state.risks[0]?.id ?? null;
  if (!state.risks.some((risk) => Number(risk.id) === Number(state.diagnosisRiskId))) state.diagnosisRiskId = state.selectedId;
  renderRiskList(); renderSupportPages(); renderCases(state.confirmedCases);
  await loadSelectedDetail();
  await loadDiagnosisReport(state.diagnosisRiskId);
  renderRuntimeStatus();
  if (WORKBENCH_ROUTES.includes(currentRoute())) await loadWorkbench(currentRoute());
  return !requests.entries().some(([, resource]) => resource.status === "error");
}

function renderCases(cases) {
  state.confirmedCases = cases || [];
  renderCaseLibrary();
}

function caseItems() {
  return state.confirmedCases.map((entry) => {
    const content = entry.content || {};
    return { id: entry.id, title: `${content.store || "门店"} · ${content.sku || "商品"}核查`,
      summary: content.raw_feedback || "后端未返回原始反馈", status: content.outcome_status || "待观察",
      category: content.risk_type || "核查", factVersion: content.fact_version ?? "未知", content, route: agentRouteForRisk({ risk_type: content.risk_type }) };
  });
}

function caseCategoryCount(category) {
  return category === "all" ? caseItems().length : caseItems().filter((item) => item.category === category).length;
}

function renderCaseLibrary() {
  const tabs = $("#case-category-tabs"), target = $("#case-library");
  const categories = ["all", ...new Set(caseItems().map((item) => item.category))];
  if (!categories.includes(state.caseFilter)) state.caseFilter = "all";
  tabs.innerHTML = categories.map((category) => `<button role="tab" aria-selected="${category === state.caseFilter}" data-case-category="${escapeHtml(category)}">${escapeHtml(category === "all" ? "全部核查" : category)} (${caseCategoryCount(category)})</button>`).join("");
  if (requests.get("cases").status !== "ready") { target.innerHTML = resourceNotice("cases"); return; }
  const visible = caseItems().filter((item) => state.caseFilter === "all" || item.category === state.caseFilter);
  target.innerHTML = visible.map((item) => `<article class="success-case-card"><div class="success-case-copy"><span class="evidence-badge">核查已确认 · 效果${escapeHtml(item.status)}</span><h2>${escapeHtml(item.title)}</h2><p>${escapeHtml(item.summary)}</p><p>事实版本 ${escapeHtml(item.factVersion)}；核查记录不代表处置成功或现金到账。</p><button class="secondary-action" data-case-detail="${escapeHtml(item.id)}">查看证据</button></div></article>`).join("") || '<div class="empty-state">暂无已确认的核查案例。完成反馈确认后，记录会从服务载入。</div>';
}

function openCaseDetail(caseId) {
  const item = caseItems().find((entry) => entry.id === caseId);
  if (!item) return;
  state.selectedCaseId = item.id;
  $("#case-detail-category").textContent = item.category;
  $("#case-detail-title").textContent = item.title;
  $("#case-detail-summary").textContent = "核查记录；处置效果与实际现金需另有执行回执证明。";
  $("#case-detail-body").innerHTML = `<pre class="evidence-json">${escapeHtml(JSON.stringify(item.content, null, 2))}</pre>`;
  $("#case-detail-modal").classList.add("open");
  $("#case-detail-modal").setAttribute("aria-hidden", "false");
}

function closeCaseDetail() {
  const modal = $("#case-detail-modal");
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
}

function currentRoute() {
  const route = window.location.hash.replace("#", "");
  return validRoutes.has(route) ? route : "overview";
}

function renderPageBack(route) {
  $$(".page-back").forEach((button) => button.remove());
  if (route === "overview" || route === "cases") return;
  const activeView = $(`.module-view[data-view="${route}"]`);
  const header = activeView?.querySelector(".module-header") || (route === "risks" ? $("#case-pane .case-header") : null);
  if (!header) return;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "page-back";
  button.dataset.go = route === "risks" ? (state.parentRoute || "overview") : "overview";
  button.innerHTML = '<span class="material-symbols-rounded">arrow_back</span>返回总览';
  header.prepend(button);
}

function renderRoute() {
  const route = currentRoute();
  $$(".module-view").forEach((view) => view.classList.toggle("active", view.dataset.view === route));
  $$("[data-route]").forEach((link) => link.classList.toggle("active", link.dataset.route === route));
  if (route === "risks") {
    const parentRoute = state.parentRoute || agentRouteForRisk(selectedRisk());
    $(`[data-route="${parentRoute}"]`)?.classList.add("active");
  } else {
    state.parentRoute = null;
  }
  document.body.classList.remove("nav-open");
  $("#drawer-backdrop").classList.remove("open");
  closeAgent();
  renderPageBack(route);
  const titles = {
    overview: "经营总览", today: "今日工作台", "slow-diagnosis": "滞销库存诊断", transfer: "跨门店智能调拨",
    "expiry-rescue": "近效期现金抢救", "procurement-brake": "采购刹车", risks: "风险案件",
    tasks: "核查任务", approvals: "方案审批", execution: "执行追踪", simulation: "现金流模拟",
    cases: "案例库", data: "数据中心", settings: "系统设置",
  };
  document.title = `资金活水 Agent · ${titles[route]}`;
  if (route === "cases") renderCaseLibrary();
  renderAgentRuntime(route);
  if (["transfer", "expiry-rescue", "procurement-brake"].includes(route) && state.dashboard && !state.workbenches[route]) loadWorkbench(route);
  if (route === "slow-diagnosis" && state.dashboard) {
    const diagnosisId = state.risks.some((risk) => Number(risk.id) === Number(state.diagnosisRiskId)) ? state.diagnosisRiskId : scopedRisks()[0]?.id;
    if (diagnosisId) loadDiagnosisReport(diagnosisId);
    else renderDiagnosis();
  }
  if (["today", "tasks", "approvals", "execution", "data"].includes(route)) refreshCommonRecords();
}

function openAgent() {
  $("#agent-pane").classList.add("open");
  $("#drawer-backdrop").classList.add("open");
}

function closeAgent() {
  $("#agent-pane").classList.remove("open");
  if (!document.body.classList.contains("nav-open")) $("#drawer-backdrop").classList.remove("open");
}

function openInvestigationModal(focusField = "") {
  const risk = selectedRisk();
  if (!risk || requests.get("detail").status !== "ready") return;
  state.feedbackRevision++;
  state.feedbackRiskId = risk.id;
  state.feedbackId = null; state.feedback = null;
  $("#investigation-title").textContent = `核查 ${risk.product} · ${risk.store}`;
  $("#feedback-text").value = focusField ? `请补充${missingLabel(focusField)}：` : $("#case-note").value.trim();
  $("#feedback-draft").hidden = true;
  $("#feedback-reviewed").checked = false;
  $("#confirm-feedback").disabled = true;
  $("#feedback-status").textContent = "第 1 步：描述发现；当前使用规则草稿，未经模型分析";
  $$(".modal-steps li").forEach((step, index) => step.classList.toggle("active", index === 0));
  $("#investigation-modal").classList.add("open");
  $("#investigation-modal").setAttribute("aria-hidden", "false");
  $("#feedback-text").focus();
}

function closeInvestigationModal() {
  state.feedbackRevision++;
  $("#investigation-modal").classList.remove("open");
  $("#investigation-modal").setAttribute("aria-hidden", "true");
}

async function createInvestigation() {
  const risk = selectedRisk();
  if (!risk || requests.get("detail").status !== "ready") return;
  await performAction("investigation", "创建核查任务", () => api(`/risks/${risk.id}/investigations`, { method: "POST", body: "{}" }), (investigation) => {
    if (state.selectedId !== risk.id) return;
    state.investigationId = investigation.id;
    risk.investigation_status = "pending";
    renderRiskList(); renderSelectedDetail(); openInvestigationModal();
  });
}

async function submitFeedback() {
  const rawText = $("#feedback-text").value.trim();
  const riskId = state.feedbackRiskId;
  const revision = state.feedbackRevision;
  let investigationId = state.investigationId;
  if (!rawText || !riskId) { showToast("请先描述核查发现", "error"); return; }
  $("#submit-feedback").disabled = true; $("#confirm-feedback").disabled = true;
  await performAction("feedback", "生成规则核查草稿", async () => {
    if (!investigationId) {
      const investigation = await api(`/risks/${riskId}/investigations`, { method: "POST", body: "{}" });
      investigationId = investigation.id;
    }
    return api(`/investigations/${investigationId}/feedback`, { method: "POST", body: JSON.stringify({ raw_text: rawText, submitted_at: new Date().toISOString() }) });
  }, (feedback) => {
    if (revision !== state.feedbackRevision || state.feedbackRiskId !== riskId || $("#feedback-text").value.trim() !== rawText) return;
    state.investigationId = investigationId;
    state.feedbackId = feedback.id; state.feedback = feedback;
    const panel = $("#feedback-draft"); panel.hidden = false;
    panel.innerHTML = `<h3>请逐项核对原文和规则草稿</h3><p>当前草稿含预设因子，不能作为 AI 结论。请修正后再确认；无法核实的内容应标为未知。</p><h4>原始反馈</h4><p>${escapeHtml(feedback.raw_text)}</p><h4>后端草稿（留作对照）</h4><pre>${escapeHtml(JSON.stringify(feedback.draft, null, 2))}</pre><label for="feedback-correction">确认事实（可修改）</label><textarea id="feedback-correction" rows="4">${escapeHtml(feedback.raw_text)}</textarea>`;
    $("#feedback-reviewed").checked = false;
    $("#feedback-status").textContent = "第 2 步：草稿待核对；勾选确认后才能保存正式事实";
    $$(".modal-steps li").forEach((step, index) => step.classList.toggle("active", index === 1));
  });
  $("#submit-feedback").disabled = false;
}

async function confirmFeedback() {
  if (!state.feedbackId || !$("#feedback-reviewed").checked) return;
  const confirmedText = $("#feedback-correction")?.value.trim();
  if (!confirmedText) { showToast("请填写经人工核对的事实，未知项可明确写未知", "error"); return; }
  $("#confirm-feedback").disabled = true;
  const feedbackId = state.feedbackId;
  const revision = state.feedbackRevision;
  const ok = await performAction("confirmFeedback", "保存人工确认的事实", () => api(`/feedback/${feedbackId}/confirm`, {
    method: "POST", body: JSON.stringify({ confirmed: { verification_method: $("#verification-status").value, confirmed_text: confirmedText, remediation_status: "unknown", user_checked: true } }),
  }), async () => {
    state.workbenches = {}; state.todayWorkbenchCache = {};
    invalidateSimulation("核查事实已更新，请重新计算工作台与现金模拟。");
    for (const route of WORKBENCH_ROUTES) {
      state.workbenchRevisions[route] = (state.workbenchRevisions[route] || 0) + 1;
      requests.invalidate(route);
    }
    for (const [key] of requests.entries()) if (key.startsWith("today:")) requests.invalidate(key);
    $("#feedback-status").textContent = "第 3 步：事实已确认，旧审批方案需要重算";
    if (revision === state.feedbackRevision) closeInvestigationModal();
    await hydrate();
    showToast("新事实已保存；请在对应工作台重新计算方案");
  });
  if (!ok && revision === state.feedbackRevision) $("#confirm-feedback").disabled = !$("#feedback-reviewed").checked;
}

function renderChat() {
  const thread = $("#agent-chat-thread");
  if (!thread) return;
  const greeting = { role: "agent", text: `当前是规则模式，未接入语言模型。当前分析范围是“${REGIONS[state.region]?.label || "全市门店"}”。你可以直接说“30天内释放20万元，不要降价”，文本只按关键词预填表单，请人工核对金额、期限与约束后点击生成方案。` };
  const messages = [greeting, ...state.chatMessages];
  thread.innerHTML = messages.map((message) => `<article class="chat-message ${message.role}"><span class="chat-avatar"><span class="material-symbols-rounded">${message.role === "agent" ? "auto_awesome" : "person"}</span></span><div class="chat-bubble">${escapeHtml(message.text)}</div></article>`).join("");
  thread.scrollTop = thread.scrollHeight;
}

function parseChatRequest(text) {
  const amount = text.match(/(\d+(?:\.\d+)?)\s*万/);
  const days = text.match(/(15|30|45)\s*天/);
  const constraintTerms = ["不要降价", "不促销", "不调拨", "不要让门店缺货", "不缺货"].filter((term) => text.includes(term));
  return { targetWan: amount ? Number(amount[1]) : null, days: days ? days[1] : null, constraints: constraintTerms.join("，") };
}

function invalidateSimulation(message = "输入已变化，请重新运行模拟。") {
  requests.invalidate("simulation");
  state.simulationResult = null; state.simulationInput = null; state.simulationCandidates = []; state.simulationExcluded = [];
  $("#simulation-status").textContent = "待重新计算";
  $("#simulation-output").innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
  renderAgentRuntime("simulation");
}

async function sendChatMessage(rawText) {
  const text = rawText.trim();
  if (!text) return;
  state.chatMessages.push({ role: "user", text });
  const parsed = parseChatRequest(text);
  if (parsed.targetWan !== null) $("#simulation-target").value = parsed.targetWan;
  if (parsed.days) $("#simulation-days").value = parsed.days;
  $("#simulation-constraints").value = parsed.constraints;
  $("#simulation-request").value = text;
  invalidateSimulation();
  state.chatMessages.push({ role: "agent", text: "已按关键词预填目标表单。规则仅识别部分金额、期限和约束；请打开现金流模拟逐项确认后再计算。" });
  $("#simulation-understanding").textContent = "关键词预填草稿：请人工核对目标、期限和业务约束。";
  renderChat();
}

async function runSimulation(event) {
  event?.preventDefault();
  if (!$("#simulation-form").reportValidity()) return null;
  await Promise.all(Object.values(state.workbenchQueues));
  const dirtyRoutes = WORKBENCH_ROUTES.filter((route) => state.workbenches[route]?.dirty);
  if (dirtyRoutes.length) {
    $("#simulation-status").textContent = "待重新计算工作台";
    $("#simulation-output").innerHTML = `<div class="empty-state">请先重新计算：${dirtyRoutes.map((route) => AGENT_NAMES[route]).join("、")}，再运行现金模拟。</div>`;
    return null;
  }
  const input = { target: Number($("#simulation-target").value) * 10000, horizon_days: Number($("#simulation-days").value), constraints: { text: $("#simulation-constraints").value.trim(), natural_request: $("#simulation-request").value.trim(), region_store_keywords: (REGIONS[state.region] || REGIONS.all).stores }, excluded_action_ids: [...state.simulationExcluded] };
  state.simulationInput = input;
  state.simulationResult = null;
  const token = requests.start("simulation", "组合规则计算中");
  $("#simulation-status").textContent = "正在计算";
  $("#simulation-output").innerHTML = '<div class="empty-state" role="status">正在计算当前草稿组合…</div>';
  try {
    const result = await api("/scenarios/simulate", { method: "POST", body: JSON.stringify(input) });
    if (requests.get("simulation").token !== token) return null;
    state.simulationResult = result;
    state.simulationCandidates = [...new Map([...state.simulationCandidates, ...(result.selected || [])].map((item) => [item.id, item])).values()];
    requests.finish("simulation", token, "ready");
    $("#simulation-status").textContent = result.status === "feasible" ? "模拟可行，待人工检查" : `仍有缺口 ${money(result.gap)}`;
    $("#simulation-understanding").textContent = `规则计算采用：${input.horizon_days} 天、目标 ${money(input.target)}，约束“${input.constraints.text || "无"}”；未调用语言模型。`;
    $("#simulation-output").innerHTML = `<div class="simulation-summary"><span>模拟净现金改善 <b>${money(result.achieved)}</b></span><span>目标缺口 <b>${money(result.gap)}</b></span><span>现金口径 <b>${escapeHtml(result.cash_basis?.completeness || "未知")}</b></span></div>${state.simulationCandidates.map((item) => `<label class="simulation-result-row"><input type="checkbox" data-simulation-action="${escapeHtml(item.id)}" ${state.simulationExcluded.includes(item.id) ? "" : "checked"} /><div><strong>${escapeHtml(item.label)}</strong><p>后端工作台草稿 ${escapeHtml(item.id)}；当前${result.selected?.some((selected) => selected.id === item.id) ? "已选入" : "未选入"}组合。</p></div><b>${money(item.cash_effect)}</b></label>`).join("") || '<div class="empty-state">当前约束下没有可计算的候选动作。请先完成工作台计算或补充缺失事实。</div>'}<p>缺项：${escapeHtml((result.cash_basis?.missing_fields || []).join("、") || "以本次结果为准")}</p><p>组合校验：${escapeHtml((result.bundle_validation?.errors || []).join("；") || (result.bundle_validation?.valid ? "通过" : "未提供"))}</p><p class="workbench-footnote">这是模拟测算，不代表真实收益；内部调拨不等同于现金到账。</p>`;
    return result;
  } catch (error) {
    if (requests.finish("simulation", token, "error", error)) {
      $("#simulation-status").textContent = "计算失败";
      $("#simulation-output").innerHTML = resourceNotice("simulation");
    }
    return null;
  }
}

async function resetDemo() {
  if (state.resetting || state.apiPending || state.mutationCount || Object.values(state.workbenchPending).some(Boolean)) return;
  if (requests.get("dataCenter").status !== "ready" || state.dataCenter?.mode !== "sample_replay" || requests.get("health").status !== "ready" || state.health?.sample_data !== true) return;
  if (!window.confirm("重置将清空当前演示库的核查、审批和执行记录，恢复后端内置合成样例。确认重置？")) return;
  state.resetting = true; renderRuntimeStatus();
  state.datasetEpoch++;
  for (const [key] of requests.entries()) requests.invalidate(key);
  try {
    const health = await api("/health");
    const source = await api("/data-center");
    if (health.sample_data !== true || source.mode !== "sample_replay") throw new Error("当前并非演示模式，已阻止重置");
    await api("/demo/reset", { method: "POST" });
    Object.assign(state, { risks: [], dashboard: null, selectedId: null, diagnosisRiskId: null, detail: null, diagnosisDetail: null, workbenches: {}, todayWorkbenchCache: {}, proposals: [], executionTasks: [], confirmedCases: [], workItems: [], investigationId: null, feedbackId: null, feedback: null, simulationResult: null, simulationCandidates: [], simulationExcluded: [], chatMessages: [] });
    $("#simulation-output").innerHTML = '<div class="empty-state">演示已重置，请重新运行模拟。</div>';
    $("#simulation-status").textContent = "尚未运行";
    closeInvestigationModal(); closeCaseDetail();
    showToast("后端合成样例已重置");
  } catch (error) { showToast(errorCopy(error), "error"); }
  finally { state.resetting = false; await hydrate(); renderChat(); }
}

async function loadSampleManifest() {
  const target = $("#sample-data-panel");
  try {
    const manifest = await createApiClient({ baseUrl: "/sample-data" })("/manifest.json");
    state.manifest = manifest;
    target.innerHTML = `<div><strong>固定种子场景包</strong><p>${escapeHtml(manifest.scenario_count ?? manifest.metadata?.scenario_count ?? manifest.scenarios?.length)} 个合成场景；下载文件用于字段校验和测试，不会替换当前快照。<a href="sample-data/README.md">数据说明</a></p></div><div class="sample-downloads">${["inventory", "sales", "purchase", "expiry"].map((key) => `<button class="secondary-action" data-sample-file="${key}">${{inventory:"库存",sales:"销售",purchase:"采购",expiry:"效期"}[key]} CSV</button>`).join("")}</div>`;
  } catch (error) { target.textContent = `场景包读取失败：${errorCopy(error)}`; }
}


async function refreshView() {
  if (state.resetting || requests.get("refresh").status === "loading") return;
  const token = requests.start("refresh", "重新读取");
  const ok = await hydrate();
  requests.finish("refresh", token, "ready");
  if (ok) showToast("已重新读取服务快照");
}

async function retryResource(key) {
  if (WORKBENCH_ROUTES.includes(key)) return loadWorkbench(key);
  if (key === "detail") return loadSelectedDetail();
  if (key === "diagnosis") return loadDiagnosisReport(state.diagnosisRiskId);
  if (key === "diagnosisCandidates") return loadDiagnosisCandidates();
  if (key === "simulation") return runSimulation();
  if (key.startsWith("today:")) { requests.invalidate(key); renderSupportPages(); return; }
  const loader = RESOURCE_LOADERS[key];
  if (loader) await readResource(key, loader.path, loader.apply, loader.label);
  renderRiskList(); renderSupportPages(); renderCaseLibrary();
}

function renderSelectedFiles() {
  const files = [...($("#import-file").files || [])];
  $("#import-file-name").textContent = files.length ? `已选择 ${files.length} 个文件` : "尚未选择文件";
  $("#selected-file-count").textContent = String(files.length);
  $("#selected-file-list").innerHTML = files.map((file, index) => `<div class="selected-file-row"><span><strong>${escapeHtml(file.name)}</strong><small>${(file.size / 1024).toFixed(1)} KB</small></span><b>已选择，尚未上传</b><button type="button" data-remove-file="${index}" aria-label="移除 ${escapeHtml(file.name)}">移除</button></div>`).join("") || '<div class="selected-files-empty">选择文件后会显示在这里</div>';
  $("#import-status").textContent = files.length ? "等待字段校验；同批文件使用下方所选数据类型" : "尚未选择文件";
}

async function importFiles(event) {
  event.preventDefault();
  const files = [...($("#import-file").files || [])];
  if (!files.length) return;
  const kind = $("#import-kind").value;
  const sheet = $("#import-sheet-name").value.trim() || null;
  const form = $("#data-import-form");
  $$("button, input, select", form).forEach((node) => { node.disabled = true; });
  $("#import-status").textContent = "正在逐个校验文件…";
  const results = [];
  const ok = await performAction("import", "文件字段校验", async () => {
    for (const file of files) {
      const result = await api("/data-center/imports", { method: "POST", body: JSON.stringify({ filename: file.name, file_base64: await fileAsBase64(file), data_kind: kind, sheet_name: sheet, mode: "erp_file" }) });
      results.push(`${file.name}：${result.status === "validated" ? "仅字段校验通过，未覆写快照" : (result.errors || []).map((error) => error.message).join("；") || "校验失败"}`);
      $("#import-status").textContent = results.join("；");
    }
  });
  if (!ok) $("#import-status").textContent = `${results.join("；")} ${errorCopy(requests.get("import").error)}`;
  $$("button, input, select", form).forEach((node) => { node.disabled = false; });
  await refreshCommonRecords();
}

function bindEvents() {
  window.addEventListener("hashchange", renderRoute);
  document.addEventListener("click", async (event) => {
    const button = event.target.closest("button, a");
    if (!button || button.disabled) return;
    if (button.hasAttribute("data-refresh-all")) return refreshView();
    if (button.dataset.retryResource) return retryResource(button.dataset.retryResource);
    if (button.dataset.sampleFile) {
      try { downloadSample(state.manifest, button.dataset.sampleFile); } catch (error) { showToast(error.message, "error"); }
      return;
    }
    if (button.dataset.templateKind) {
      try { downloadTemplate(button.dataset.templateKind, state.dataCenter?.import_schemas?.[button.dataset.templateKind]); } catch (error) { showToast(error.message, "error"); }
      return;
    }
    if (button.dataset.todayFilter) { state.todayFilter = button.dataset.todayFilter; state.todaySelectedItemId = null; renderSupportPages(); return; }
    if (button.dataset.todaySelect) { state.todaySelectedItemId = button.dataset.todaySelect; renderSupportPages(); return; }
    if (button.dataset.openRisk) {
      const id = Number(button.dataset.openRisk);
      const risk = [...state.risks, ...(state.diagnosisRisks || [])].find((item) => Number(item.id) === id);
      if (!risk) return;
      if (!state.risks.some((item) => Number(item.id) === id)) state.risks.push(risk);
      state.selectedId = id; state.parentRoute = button.dataset.sourceRoute || agentRouteForRisk(risk);
      window.location.hash = "risks"; renderRiskList(); await loadSelectedDetail(); return;
    }
    if (button.dataset.go) {
      const id = Number(button.dataset.workbenchRisk || 0);
      window.location.hash = button.dataset.go;
      if (id && WORKBENCH_ROUTES.includes(button.dataset.go)) await loadWorkbench(button.dataset.go, id);
    }
  });
  $("#overview-toggle-store-chart").addEventListener("click", () => { state.overviewShowAllStores = !state.overviewShowAllStores; renderOperatingOverview(); });
  $("#overview-store-bars").addEventListener("click", (event) => {
    const bar = event.target.closest("[data-overview-store]");
    if (bar) { state.overviewSelectedStore = state.overviewSelectedStore === bar.dataset.overviewStore ? null : bar.dataset.overviewStore; renderOperatingOverview(); }
  });
  $("#overview-clear-store-filter").addEventListener("click", () => { state.overviewSelectedStore = null; renderOperatingOverview(); });
  [["#priority-filter", "priorityFilter"], ["#type-filter", "typeFilter"], ["#evidence-filter", "evidenceFilter"]].forEach(([selector, key]) => $(selector).addEventListener("change", (event) => { state[key] = event.target.value; renderRiskList(); }));
  $("#filter-toggle").addEventListener("click", () => { $("#filter-row").hidden = !$("#filter-row").hidden; });
  $("#global-search").addEventListener("input", (event) => { state.search = event.target.value; if (state.search) window.location.hash = "risks"; renderRiskList(); });
  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); $("#global-search").focus(); }
    if (event.key === "Escape") { closeAgent(); closeInvestigationModal(); closeCaseDetail(); document.body.classList.remove("nav-open"); $("#drawer-backdrop").classList.remove("open"); }
    const modal = document.querySelector('.modal-backdrop.open .modal');
    if (event.key === "Tab" && modal) {
      const focusable = [...modal.querySelectorAll('button:not([disabled]), input:not([disabled]), textarea, select, a[href], summary')].filter((node) => node.getClientRects().length);
      const first = focusable[0], last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
  });
  $("#refresh-data").addEventListener("click", refreshView);
  $("#slow-refresh-analysis").addEventListener("click", refreshView);
  $("#demo-reset").addEventListener("click", resetDemo);
  $("#agent-toggle").addEventListener("click", openAgent);
  $("#agent-close").addEventListener("click", closeAgent);
  $("#drawer-backdrop").addEventListener("click", () => { closeAgent(); document.body.classList.remove("nav-open"); $("#drawer-backdrop").classList.remove("open"); });
  $("#mobile-nav").addEventListener("click", () => { document.body.classList.toggle("nav-open"); $("#drawer-backdrop").classList.toggle("open", document.body.classList.contains("nav-open")); });
  $("#mobile-back").addEventListener("click", () => $(".risk-module").classList.remove("show-detail"));
  $("#create-investigation").addEventListener("click", createInvestigation);
  $("#defer-case").addEventListener("click", () => showToast("案件仍在待核查队列，业务状态未改变"));
  $("#case-note").addEventListener("input", (event) => { $("#note-count").textContent = event.target.value.length; });
  $("#toast button").addEventListener("click", () => $("#toast").classList.remove("show"));
  $("#modal-close").addEventListener("click", closeInvestigationModal);
  $("#investigation-modal").addEventListener("click", (event) => { if (event.target === $("#investigation-modal")) closeInvestigationModal(); });
  $("#case-category-tabs").addEventListener("click", (event) => { const tab = event.target.closest("[data-case-category]"); if (tab) { state.caseFilter = tab.dataset.caseCategory; renderCaseLibrary(); } });
  $("#case-library").addEventListener("click", (event) => { const detail = event.target.closest("[data-case-detail]"); if (detail) openCaseDetail(detail.dataset.caseDetail); });
  $("#case-detail-close").addEventListener("click", closeCaseDetail);
  $("#case-detail-modal").addEventListener("click", (event) => { if (event.target === $("#case-detail-modal")) closeCaseDetail(); });
  $("#case-detail-use").addEventListener("click", closeCaseDetail);
  $("#case-detail-secondary").addEventListener("click", () => { const item = caseItems().find((entry) => entry.id === state.selectedCaseId); if (item) { closeCaseDetail(); window.location.hash = item.route; } });
  $("#submit-feedback").addEventListener("click", submitFeedback);
  $("#confirm-feedback").addEventListener("click", confirmFeedback);
  $("#feedback-reviewed").addEventListener("change", (event) => { $("#confirm-feedback").disabled = !event.target.checked || !state.feedbackId; });
  $("#feedback-text").addEventListener("input", () => { state.feedbackRevision++; state.feedbackId = null; state.feedback = null; $("#feedback-draft").hidden = true; $("#feedback-reviewed").checked = false; $("#confirm-feedback").disabled = true; });
  $("#simulation-form").addEventListener("submit", runSimulation);
  $("#simulation-output").addEventListener("change", (event) => {
    const box = event.target.closest("[data-simulation-action]"); if (!box) return;
    const ids = new Set(state.simulationExcluded);
    if (box.checked) ids.delete(box.dataset.simulationAction); else ids.add(box.dataset.simulationAction);
    state.simulationExcluded = [...ids]; runSimulation();
  });
  $("#region-select").addEventListener("change", (event) => switchRegion(event.target.value));
  $("#agent-chat-form").addEventListener("submit", (event) => { event.preventDefault(); const input = $("#agent-chat-input"); sendChatMessage(input.value); input.value = ""; });
  $$("[data-chat-prompt]").forEach((button) => button.addEventListener("click", () => sendChatMessage(button.dataset.chatPrompt)));
  ["#simulation-target", "#simulation-days", "#simulation-constraints", "#simulation-request"].forEach((selector) => $(selector).addEventListener("input", () => {
    invalidateSimulation();
    $("#simulation-understanding").textContent = `待人工确认：${$("#simulation-days").value} 天内目标 ${money(Number($("#simulation-target").value) * 10000)}。`;
  }));
  $("#import-kind").addEventListener("change", renderDataCenter);
  $("#import-select-file").addEventListener("click", (event) => { event.preventDefault(); $("#import-file").click(); });
  $("#import-template").addEventListener("click", (event) => {
    event.preventDefault();
    const kind = $("#import-kind").value;
    try { downloadTemplate(kind, state.dataCenter?.import_schemas?.[kind]); } catch (error) { showToast(error.message, "error"); }
  });
  $("#clear-import-files").addEventListener("click", () => { $("#import-file").value = ""; renderSelectedFiles(); });
  $("#import-file").addEventListener("change", renderSelectedFiles);
  $("#selected-file-list").addEventListener("click", (event) => {
    const remove = event.target.closest("[data-remove-file]"); if (!remove) return;
    const files = new DataTransfer();
    [...$("#import-file").files].forEach((file, index) => { if (index !== Number(remove.dataset.removeFile)) files.items.add(file); });
    $("#import-file").files = files.files; renderSelectedFiles();
  });
  $("#analysis-search").addEventListener("input", (event) => { state.analysisSearch = event.target.value; renderDataCenter(); });
  $("#analysis-status-filter").addEventListener("change", (event) => { state.analysisStatus = event.target.value; renderDataCenter(); });
  $("#analysis-sort").addEventListener("change", (event) => { state.analysisSort = event.target.value; renderDataCenter(); });
  $("#data-import-form").addEventListener("submit", importFiles);
}

bindEvents();
if (!window.location.hash || !validRoutes.has(window.location.hash.slice(1))) window.location.hash = "overview";
renderRoute();
renderRuntimeStatus();
renderChat();
hydrate();
loadSampleManifest();

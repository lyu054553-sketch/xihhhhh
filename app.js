const fallbackRisks = [
  { id: 1, sku: "SKU-88310", product: "每日坚果 25g", store: "西湖文三店", sales_30: 12, comparison: [18, 22, 26, 30, 30, 34, 38, 42], inventory_qty: 120, unit_cost: 80, days_to_sell: 168, risk_type: "调拨", priority: "紧急", observation: "近30天销量低于同规格对照门店中位数 60%；原因待核查。", evidence_level: "partial", evidence_label: "部分支持", missing_fields: ["shelf_availability", "stockout_records"], proposal_id: "PROP-AC10-001", proposal_status: "pending_approval" },
  { id: 3, sku: "SKU-34106", product: "芒果果汁 300ml", store: "拱墅运河店", sales_30: 16, comparison: [18, 22, 25], inventory_qty: 90, unit_cost: 76, days_to_sell: 146, risk_type: "促销", priority: "紧急", observation: "近效期批次预计无法在当前速度下售完；需求与效期证据部分支持。", evidence_level: "partial", evidence_label: "部分支持", missing_fields: ["sellable_days"] },
  { id: 2, sku: "SKU-10428", product: "巧克力礼盒 200g", store: "余杭未来店", sales_30: 8, comparison: [12, 18, 20, 25], inventory_qty: 110, unit_cost: 80, days_to_sell: 214, risk_type: "退供", priority: "高", observation: "库存覆盖天数偏高；采购量与退换条件待核查。", evidence_level: "insufficient", evidence_label: "信息不足", missing_fields: ["supplier_return_terms"] },
  { id: 4, sku: "SKU-55091", product: "香辣薯片 110g", store: "上城庆春店", sales_30: 14, comparison: [19, 20, 23], inventory_qty: 80, unit_cost: 59, days_to_sell: 137, risk_type: "采购刹车", priority: "高", observation: "销量下降但在途采购状态待核查。", evidence_level: "insufficient", evidence_label: "信息不足", missing_fields: ["purchase_order_status"] },
  { id: 5, sku: "SKU-79033", product: "海盐薯片 80g", store: "临平东湖店", sales_30: 20, comparison: [24, 28, 30], inventory_qty: 70, unit_cost: 55, days_to_sell: 119, risk_type: "调拨", priority: "中", observation: "门店间销量差异需结合规模和可售天数核查。", evidence_level: "insufficient", evidence_label: "信息不足", missing_fields: ["store_scale", "sellable_days"] },
];

const caseCategories = [
  { id: "all", label: "全部案例" },
  { id: "transfer", label: "跨店调拨" },
  { id: "expiry", label: "近效期处置" },
  { id: "procurement", label: "采购调整" },
  { id: "return", label: "退供回款" },
  { id: "display", label: "陈列改善" },
  { id: "launch", label: "新品上市" },
];

const featuredCases = [
  {
    id: "CASE-TRANSFER-01", featured: true, tags: ["transfer"], image: "assets/retail-nuts.png", visual: "nuts", product: "每日坚果礼盒",
    category: "跨店调拨", title: "古荡店坚果礼盒调往文三店",
    summary: "古荡店有 600 袋慢销，文三店缺货。调拨 80 袋后，文三店 21 天售出 64 袋。",
    metrics: [["80 袋", "古荡 → 文三"], ["64 袋", "21 天售出"], ["¥24", "调拨运费"]],
    scenario: "一店积压、另一店动销较快", route: "transfer",
    outcome: { value: "¥1,256", label: "模拟多赚（扣商品成本与运费）", status: "模拟已执行", note: "假设文三店调入前无可售库存，64 袋销量来自本次调拨；古荡店调出后仍能满足本店需求。" },
    flow: [
      { stage: "发现", module: "滞销诊断 Agent", title: "古荡店积压，文三店有需求", detail: "古荡店每日坚果礼盒库存 600 袋、日销约 2 袋；文三店可售库存为 0，预计 21 天可售 64 袋。" },
      { stage: "测算", module: "跨店调拨 Agent", title: "建议古荡店 → 文三店调拨 80 袋", detail: "按安全库存、门店销量和运输条件核算；古荡店调出后剩 520 袋，文三店收到 80 袋。" },
      { stage: "执行", module: "门店确认与调拨回执", title: "80 袋完成调拨，运费 ¥24", detail: "商品成本 ¥6,400 仅从一店转到另一店；调拨当时没有产生销售回款。" },
      { stage: "结果", module: "销售回执", title: "文三店 21 天售出 64 袋", detail: "按演示售价 ¥100／袋收到销售款 ¥6,400；其余 16 袋仍在文三店库存。" },
    ],
    moneyFlow: [
      { label: "库存成本位置变化", value: "¥6,400", detail: "80 袋 × ¥80；店间调拨，不是现金流入", type: "neutral" },
      { label: "销售回款", value: "+¥6,400", detail: "64 袋 × ¥100；出售后形成回款", type: "in" },
      { label: "已售商品成本", value: "−¥5,120", detail: "64 袋 × ¥80；成本结转，不是出售当天的现金流出", type: "neutral" },
      { label: "调拨运费", value: "−¥24", detail: "实际执行成本", type: "out" },
    ],
    formula: "¥6,400 销售回款 − ¥5,120 商品成本 − ¥24 运费 = ¥1,256 模拟多赚",
  },
  {
    id: "CASE-EXPIRY-01", featured: true, tags: ["expiry"], image: "assets/retail-drink.png", visual: "drink", product: "气泡果汁整箱",
    category: "近效期处置", title: "湖滨店气泡果汁分批处置",
    summary: "40 箱气泡果汁仅剩 18 天可售，方案把调拨、促销和退供分开测算。",
    metrics: [["18 天", "剩余可售"], ["10 箱", "计划调拨"], ["16 箱", "计划促销"]],
    scenario: "批次可售时间短、单店销量不足", route: "expiry-rescue",
    outcome: { value: "¥1,600", label: "方案预计回款，尚未到账", status: "待执行测算", note: "促销和退供都需实际售出或收到供应商退款；调拨 10 箱只改变库存位置，不计为回款。" },
    flow: [
      { stage: "发现", module: "近效期 Agent", title: "40 箱果汁剩余可售 18 天", detail: "按现有销量，湖滨店难以在效期内卖完全部批次。" },
      { stage: "测算", module: "近效期处置 Agent", title: "拆分为调拨 10 箱、促销 16 箱、退供 8 箱", detail: "剩余 6 箱继续观察；调拨去向和退供条件都需人工确认。" },
      { stage: "待执行", module: "门店与供应商确认", title: "先审批价格和退供条款", detail: "促销价按 ¥62／箱、供应商退供按 ¥76／箱做演示测算。" },
      { stage: "预计", module: "现金回收测算", title: "若促销卖出且退供到账，预计回款 ¥1,600", detail: "这是两类未来回款的合计，当前未形成实际到账。" },
    ],
    moneyFlow: [
      { label: "跨店调拨货值", value: "¥760", detail: "10 箱 × ¥76；仅改变库存位置", type: "neutral" },
      { label: "促销预计回款", value: "+¥992", detail: "16 箱 × ¥62；售出后才形成现金", type: "future" },
      { label: "退供预计退款", value: "+¥608", detail: "8 箱 × ¥76；供应商到账后确认", type: "future" },
    ],
    formula: "¥992 促销预计回款 + ¥608 退供预计退款 = ¥1,600 方案预计回款；不等于利润",
  },
  {
    id: "CASE-RETURN-01", featured: true, tags: ["return"], image: "assets/retail-nuts.png", visual: "nuts", product: "混合坚果礼盒",
    category: "退供回款", title: "未来店坚果礼盒核对条款后退供",
    summary: "慢销坚果礼盒符合退供条款，退回 40 袋，并在演示回执中确认到账。",
    metrics: [["40 袋", "退回供应商"], ["8 天", "演示到账"], ["¥80", "每袋成本"]],
    scenario: "合同允许退供、库存长期慢销", route: "slow-diagnosis",
    outcome: { value: "¥3,200", label: "演示已到账退款", status: "模拟已执行", note: "退款是原库存成本的回收，不是新增销售收入或利润。真实业务必须以供应商退款回执与银行到账为准。" },
    flow: [
      { stage: "发现", module: "滞销诊断 Agent", title: "未来店坚果礼盒长期慢销", detail: "40 袋库存按 ¥80／袋占用 ¥3,200。" },
      { stage: "核查", module: "退供条件核查", title: "确认合同允许退供", detail: "核对包装、批次、退货期限和供应商确认记录。" },
      { stage: "执行", module: "退供与物流回执", title: "40 袋退回供应商", detail: "库存成本减少 ¥3,200，但发货时不能算作到账。" },
      { stage: "到账", module: "退款回执", title: "第 8 天收到 ¥3,200", detail: "款项回到企业账户，完成本次演示退供闭环。" },
    ],
    moneyFlow: [
      { label: "退回库存成本", value: "−¥3,200", detail: "40 袋 × ¥80；货品离开企业库存", type: "neutral" },
      { label: "供应商退款到账", value: "+¥3,200", detail: "以演示退款回执确认", type: "in" },
    ],
    formula: "40 袋 × ¥80／袋 = ¥3,200 演示已回收资金；不计作新增利润",
  },
  {
    id: "CASE-PROCUREMENT-01", featured: true, tags: ["procurement"], image: "assets/retail-cookies.png", visual: "cookies", product: "酸奶夹心饼干",
    category: "采购调整", title: "庆春店饼干库存偏高，暂停重复补货",
    summary: "庆春店已有 80 箱、在途 40 箱，仍有 60 箱未执行采购；建议减量 40 箱。",
    metrics: [["40 箱", "减少未执行量"], ["80 箱", "现有库存"], ["0 项", "测算缺货风险"]],
    scenario: "库存偏高且仍有未执行采购", route: "procurement-brake",
    outcome: { value: "¥2,360", label: "未来采购付款预计减少", status: "待供应商确认", note: "金额是原计划少付的采购款，不是已到账现金或新增利润；最终取决于供应商变更确认。" },
    flow: [
      { stage: "发现", module: "采购刹车 Agent", title: "重复补货将继续增加库存", detail: "庆春店现有 80 箱、在途 40 箱，采购单另有 60 箱未执行。" },
      { stage: "测算", module: "采购刹车 Agent", title: "建议未执行采购从 60 箱减到 20 箱", detail: "按每箱 ¥59 计算，减量 40 箱；同时核对安全库存和缺货风险。" },
      { stage: "待确认", module: "采购主管与供应商", title: "提交订单变更", detail: "确认最小起订量、取消费用和供应商是否接受变更。" },
      { stage: "预计", module: "付款计划对比", title: "原计划 ¥3,540 → 调整后 ¥1,180", detail: "若变更生效，未来采购付款少流出 ¥2,360。" },
    ],
    moneyFlow: [
      { label: "原计划采购付款", value: "−¥3,540", detail: "60 箱 × ¥59", type: "out" },
      { label: "调整后采购付款", value: "−¥1,180", detail: "20 箱 × ¥59；待供应商确认", type: "future" },
      { label: "未来少付款", value: "+¥2,360", detail: "现金少流出，不是新增现金收入", type: "future" },
    ],
    formula: "(60 − 20) 箱 × ¥59／箱 = ¥2,360 未来采购付款预计减少",
  },
  {
    id: "CASE-DISPLAY-01", featured: true, tags: ["display"], image: "assets/retail-cookies.png", visual: "cookies", product: "黄油曲奇分享装",
    category: "陈列改善", title: "蒋村店曲奇销量异常，先查陈列",
    summary: "演示回放：核查发现商品连续 20 天未上架；恢复陈列后，用下一期销量验证改善是否持续。",
    metrics: [["20 天", "未上架时长"], ["8→22 盒", "两期销量"], ["30 天", "观察周期"]],
    scenario: "有库存却卖得慢，陈列记录缺失", route: "slow-diagnosis",
    outcome: { value: "+¥140", label: "两期毛利差额，归因待核查", status: "观察结果", note: "14 盒销量差额按演示单盒毛利 ¥10 估算；季节、价格、客流等因素未剔除，不能全部归功于陈列调整。" },
    flow: [
      { stage: "发现", module: "滞销诊断 Agent", title: "有库存但只售出 8 盒", detail: "系统提示销量异常，要求先核对门店陈列记录。" },
      { stage: "核查", module: "门店反馈", title: "商品连续 20 天未上架", detail: "店员确认陈列问题，主管记录核查结果。" },
      { stage: "执行", module: "门店陈列整改", title: "恢复货架陈列并保持 30 天", detail: "先改陈列，再观察下一期销量。" },
      { stage: "观察", module: "销售复盘", title: "销量从 8 盒到 22 盒", detail: "毛利差额约 ¥140，仍需核查客流和价格变化。" },
    ],
    moneyFlow: [
      { label: "两期销量差额", value: "+14 盒", detail: "22 − 8；仅为观察值", type: "neutral" },
      { label: "毛利差额", value: "+¥140", detail: "14 盒 × 演示单盒毛利 ¥10；归因待核查", type: "future" },
    ],
    formula: "(22 − 8) 盒 × ¥10／盒 = ¥140 两期毛利差额；不等于已证实的陈列增益",
  },
  {
    id: "CASE-LAUNCH-01", featured: true, tags: ["launch"], image: "assets/retail-drink.png", visual: "drink", product: "气泡果汁整箱",
    category: "新品上市", title: "滨江店气泡果汁先小范围试销",
    summary: "演示回放：先在 12 家门店试销，再依据首轮动销决定是否扩大铺货，避免一开始就压进过多库存。",
    metrics: [["12 家", "试销门店"], ["14 天", "首轮复盘"], ["约72%", "演示动销率"]],
    scenario: "新品需求尚未验证，先控制铺货量", route: "slow-diagnosis",
    outcome: { value: "¥1,800", label: "首轮少占用库存成本", status: "方案对比", note: "与一次铺到 30 家门店的对照方案相比；只是推迟占用库存资金，不是节约采购成本或增加利润。" },
    flow: [
      { stage: "发现", module: "新品铺货评估", title: "需求尚无跨店验证", detail: "直接铺满 30 家店，首轮每店 10 箱、每箱成本 ¥10，会占用 ¥3,000。" },
      { stage: "建议", module: "库存资金对比", title: "先在 12 家店各铺 10 箱", detail: "初期库存成本为 ¥1,200，其余门店暂不压货。" },
      { stage: "执行", module: "试销回执", title: "14 天复盘 120 箱首轮库存", detail: "演示售出 86 箱，动销率约 72%。" },
      { stage: "决策", module: "扩大铺货评估", title: "依据门店动销决定下一轮", detail: "是否扩大到其他门店仍需核对缺货风险与补货周期。" },
    ],
    moneyFlow: [
      { label: "一次铺 30 店占用成本", value: "¥3,000", detail: "30 店 × 10 箱 × ¥10", type: "neutral" },
      { label: "先铺 12 店占用成本", value: "¥1,200", detail: "12 店 × 10 箱 × ¥10", type: "neutral" },
      { label: "首轮少占用", value: "¥1,800", detail: "暂未进货的库存资金；并非现金收益", type: "future" },
    ],
    formula: "(30 − 12) 家 × 10 箱 × ¥10／箱 = ¥1,800 首轮少占用库存成本",
  },
];

const API_BASE = window.location.protocol === "file:" ? null : "/api/v1";
const HACKATHON_PREVIEW = new URLSearchParams(window.location.search).get("hackathonPreview") === "1";
const validRoutes = new Set([
  "overview", "today", "slow-diagnosis", "transfer", "expiry-rescue", "procurement-brake", "decision-entry", "execution-followup",
  "risks", "tasks", "approvals", "execution", "simulation", "cases", "data", "settings",
]);
const state = {
  risks: [...fallbackRisks],
  dashboard: null,
  selectedId: 1,
  riskTotal: 0,
  detail: null,
  diagnosisRiskId: 1,
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
  workbenchLoading: {},
  region: "all",
  todayFilter: "pending",
  todaySelectedItemId: null,
  todayWorkbenchCache: {},
  todayWorkbenchLoading: null,
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
  all: { label: "杭州市 · 全部50家门店", stores: [] },
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

function hackathonMountContext() {
  const configured = window.RETAIL_HACKATHON_CONTEXT || {};
  const dashboard = state.dashboard || {};
  const dataCenter = state.dataCenter || {};
  return {
    tenantId: configured.tenantId || dashboard.tenant_id || "demo",
    scenarioId: configured.scenarioId ?? null,
    branchId: configured.branchId ?? null,
    snapshotId: configured.snapshotId ?? dashboard.snapshot_id ?? dataCenter.snapshot_id ?? null,
    asOf: configured.asOf ?? dashboard.as_of ?? dashboard.as_of_date ?? null,
    dataVersion: configured.dataVersion ?? dashboard.data_version ?? dataCenter.data_version ?? null,
    factVersion: configured.factVersion ?? dashboard.fact_version ?? null,
    isDemo: configured.isDemo ?? (dataCenter.mode === "real_inventory_snapshot" ? false : true),
    sourceRefs: Array.isArray(configured.sourceRefs) ? [...configured.sourceRefs] : [],
    missingFields: Array.isArray(configured.missingFields) ? [...configured.missingFields] : [],
    area: configured.area || "transfer",
    horizonStart: configured.horizonStart ?? null,
    horizonEnd: configured.horizonEnd ?? null,
    assumptionIds: Array.isArray(configured.assumptionIds) ? [...configured.assumptionIds] : [],
    riskId: configured.riskId ?? null,
    storeId: configured.storeId ?? null,
    skuId: configured.skuId ?? null,
    lotId: configured.lotId ?? null,
    actorId: configured.actorId ?? null,
    proposalId: configured.proposalId ?? null,
    proposalVersion: configured.proposalVersion ?? null,
    taskId: configured.taskId ?? null,
    businessInputs: configured.businessInputs && typeof configured.businessInputs === "object" ? { ...configured.businessInputs } : {},
  };
}

window.RetailHackathonHost = Object.freeze({ getContext: hackathonMountContext });

function scopedRisks() {
  const region = REGIONS[state.region] || REGIONS.all;
  return !region.stores.length ? state.risks : state.risks.filter((risk) => region.stores.some((name) => String(risk.store || "").includes(name)));
}

async function api(path, options = {}) {
  if (!API_BASE) throw new Error("请通过本地服务打开系统");
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || payload.message || `请求失败（${response.status}）`);
  return payload;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  })[character]);
}

function money(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "未知";
  return `¥${Math.round(Number(value)).toLocaleString("zh-CN")}`;
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
  state.region = REGIONS[regionId] ? regionId : "all";
  state.overviewShowAllStores = false;
  state.overviewSelectedStore = null;
  const label = REGIONS[state.region].label;
  const firstRisk = scopedRisks()[0];
  if (firstRisk) { state.selectedId = firstRisk.id; state.detail = null; state.diagnosisRiskId = firstRisk.id; state.diagnosisDetail = null; }
  renderRiskList();
  renderSupportPages();
  if (firstRisk) await loadSelectedDetail();
  renderDiagnosis();
  renderChat();
  showToast(`已切换至${label}；当前页面按该区域的样例门店范围展示`);
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
  return state.risks.find((risk) => Number(risk.id) === Number(state.selectedId)) || state.risks[0];
}

function riskEvidenceFraction(risk) {
  const missing = (risk.missing_fields || []).length;
  const total = Math.max(2, missing + 1);
  return `${Math.max(1, total - missing)}/${total}`;
}

function renderRiskList() {
  const list = filteredRisks();
  const container = $("#risk-list");
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
        <span class="risk-evidence">证据 ${riskEvidenceFraction(risk)}</span>
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
  if (!risk) return;
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
  const knownCost = Number(risk.id) === 1 ? "¥86（已知）" : "未知";

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
  if (!API_BASE) {
    renderSelectedDetail();
    return;
  }
  try {
    state.detail = await api(`/risks/${state.selectedId}`);
  } catch (error) {
    state.detail = null;
    showToast(`详情读取失败：${error.message}`, "error");
  }
  renderSelectedDetail();
}

async function loadDiagnosisReport(riskId) {
  if (!riskId) { state.diagnosisDetail = null; renderDiagnosis(); return; }
  state.diagnosisRiskId = Number(riskId);
  if (!API_BASE) { state.diagnosisDetail = null; renderDiagnosis(); return; }
  try {
    state.diagnosisDetail = await api(`/risks/${state.diagnosisRiskId}`);
  } catch (error) {
    state.diagnosisDetail = null;
    showToast(`诊断报告读取失败：${error.message}`, "error");
  }
  renderDiagnosis();
}

function inputField(label, name, value, type = "number", extra = "") {
  return `<label>${label}<input name="${name}" type="${type}" value="${escapeHtml(value ?? "")}" ${extra}/></label>`;
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
    ? '<img src="assets/retail-nuts.png" alt="每日坚果 25g商品示意图" />'
    : '<span class="material-symbols-rounded" aria-hidden="true">inventory_2</span>';
}

function transferQueue(data, input) {
  const items = data.items || [];
  const selectedRiskId = Number(data.risk?.id || input.risk_id);
  return `<aside class="transfer-queue-panel"><header><div><h2>待调拨商品 <b>${items.length}</b></h2><p>按风险时效与库存占用排序</p></div><span>${items.length} 项</span></header><div class="transfer-filter-row"><span>全部商品分类</span><span>优先级排序</span></div><div class="transfer-case-list">${items.map((item) => {
    const selected = Number(item.id) === selectedRiskId;
    return `<button type="button" class="transfer-case ${selected ? "selected" : ""}" data-transfer-risk="${item.id}" aria-label="查看 ${escapeHtml(item.product)} 调拨方案"><span class="transfer-case-visual">${transferProductVisual(item)}</span><span class="transfer-case-copy"><span><strong>${escapeHtml(item.product)}</strong><i class="priority-badge ${item.priority === "紧急" ? "urgent" : ""}">${escapeHtml(item.priority)}</i></span><small>${escapeHtml(item.sku)} ｜ ${escapeHtml(item.store)}</small><em>库存 ${item.inventory_qty ?? "—"} 件 ｜ 建议调拨 ${Number(item.id) === 1 ? "40" : "35"} 件</em><b>库存成本 ${money(riskAmount(item))}</b></span><span class="material-symbols-rounded transfer-case-arrow">chevron_right</span></button>`;
  }).join("") || '<div class="empty-state">当前没有待调拨商品。</div>'}</div></aside>`;
}

function transferStockCard(label, store, before, after, safety, tone) {
  const safeBefore = Number(before || 0), safeAfter = Number(after || 0), safeMax = Math.max(safeBefore, safeAfter, Number(safety || 0), 1);
  const beforeWidth = Math.max(6, Math.round((safeBefore / safeMax) * 100));
  const afterWidth = Math.max(6, Math.round((safeAfter / safeMax) * 100));
  return `<section class="transfer-stock-card ${tone}"><h4>${escapeHtml(label)}：${escapeHtml(store || "未知门店")}</h4><div class="transfer-stock-line"><span>调拨前</span><i><b style="width:${beforeWidth}%"></b></i><strong>${safeBefore} 件</strong></div><div class="transfer-stock-line"><span>调拨后</span><i><b style="width:${afterWidth}%"></b></i><strong>${safeAfter} 件</strong></div><p>安全库存 ${safety ?? "未知"} 件</p></section>`;
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
  const netEconomicImpact = Number(economic.net_avoidable_loss ?? 0);
  const impactTone = netEconomicImpact >= 0 ? "positive" : "negative";
  const selectedRank = Math.max(1, network.findIndex((item) => item.store_id === input.target_store_id) + 1);
  const checks = [
    [Number(input.quantity || 0) <= Number(limits.available_to_transfer || 0), "调出店保留安全库存"],
    [Number(input.quantity || 0) <= Number(limits.receiving_capacity || 0), "接收店可承接该数量"],
    [Number(input.eta_days || 0) < Number(input.sellable_days || Infinity), "配送条件满足可售期"],
  ];
  return `<div class="transfer-workbench-shell">
    ${transferQueue(data, input)}
    <section class="transfer-focus-panel">
      <header class="transfer-product-header"><div class="transfer-product-visual">${transferProductVisual(risk)}</div><div><div class="transfer-product-title"><h2>${escapeHtml(input.product || "调拨商品")}</h2><span class="priority-badge ${risk.priority === "紧急" ? "urgent" : ""}">${escapeHtml(risk.priority || "待确认")}</span></div><p>${escapeHtml(risk.sku || "SKU 未知")} ｜ 批次 ${escapeHtml(input.batch || "未知")} ｜ 可售期 ${input.sellable_days ?? "未知"} 天</p><div class="transfer-tag-list"><span>滞销诊断</span><span>可调拨</span><span>库存积压</span></div></div><button class="secondary-action" type="button" data-go="slow-diagnosis">查看诊断依据</button></header>
      <nav class="transfer-detail-tabs" aria-label="调拨详情"><span class="active">推荐方案</span><span>候选门店</span><span>库存对比</span><span>调拨影响</span><span>相关证据</span></nav>
      <section class="transfer-recommendation"><span class="material-symbols-rounded">recommend</span><div><p>推荐方案</p><h3>建议将 <b>${input.quantity ?? "—"} 件</b> 调至 ${escapeHtml(input.target_store || "推荐接收门店")}</h3><small>${escapeHtml(input.source_store || "调出门店")} <span class="material-symbols-rounded">arrow_forward</span> ${escapeHtml(input.target_store || "接收门店")} ｜ ${selected.distance_km ?? "—"} km ｜ 预计 ${selected.travel_minutes ?? "—"} 分钟到店 ｜ 配送费 ${money(input.transport_fee)}</small></div><div class="transfer-recommendation-metric"><span>本次调拨库存成本</span><strong>${money(cash.inventory_cost)}</strong><small>${input.quantity ?? "—"} 件 × ${money(input.unit_cost).replace("¥", "¥")}/件</small></div><div class="transfer-recommendation-metric positive"><span>预计避免报损</span><strong>${money(economic.avoided_loss)}</strong><small>不调拨预计损失 ${money(economic.potential_loss_without_transfer)}</small></div></section>
      <div class="transfer-validation-row">${checks.map(([passed, label]) => `<span class="${passed ? "passed" : "blocked"}"><i class="material-symbols-rounded">${passed ? "check_circle" : "error"}</i>${escapeHtml(label)}</span>`).join("")}<button class="text-link" type="button" data-go="risks">查看计算依据 <span class="material-symbols-rounded">arrow_forward</span></button></div>
      <div class="transfer-route-grid"><section class="transfer-route-card"><header><div><h3>调拨路线（示意）</h3><p>${selected.distance_km ?? "—"} km ｜ 约 ${selected.travel_minutes ?? "—"} 分钟 ｜ 预计 ${selected.eta_days ?? input.eta_days ?? "—"} 天到店</p></div></header><div class="transfer-route-map"><img src="assets/today-transfer-route-map.png" alt="${escapeHtml(input.source_store || "调出门店")}至${escapeHtml(input.target_store || "接收门店")}的同城配送路线示意" /><span class="route-store source">${escapeHtml(input.source_store || "调出门店")}<small>调出 · ${source.on_hand_before ?? input.source_on_hand ?? "—"} 件</small></span><span class="route-store target">${escapeHtml(input.target_store || "接收门店")}<small>调入 · ${input.quantity ?? "—"} 件</small></span><b class="route-map-chip">配送费 ${money(input.transport_fee)}</b></div></section><section class="transfer-alternative-card"><header><h3>其他可接收门店</h3><button type="button" class="text-link" data-transfer-target="${escapeHtml(network[0]?.store_id || "")}">采用最优方案 <span class="material-symbols-rounded">arrow_forward</span></button></header><div class="transfer-alternative-head"><span>候选门店</span><span>距离</span><span>可接收</span><span>预计费用</span></div><div class="transfer-alternative-list">${network.slice(0, 5).map((item, index) => `<button type="button" class="transfer-alternative-row ${item.store_id === input.target_store_id ? "selected" : ""}" data-transfer-target="${escapeHtml(item.store_id)}"><b>${index + 1}</b><span><strong>${escapeHtml(item.district)}区 · ${escapeHtml(item.name)}</strong>${item.store_id === input.target_store_id ? '<em>推荐</em>' : ""}</span><span>${item.distance_km} km</span><span>${item.calculation?.limits?.receiving_capacity ?? "—"} 件</span><span>${money(item.transport_fee)}</span></button>`).join("")}</div></section></div>
      <div class="transfer-impact-grid-new"><div class="transfer-stock-compare">${transferStockCard("调出店", input.source_store, source.on_hand_before ?? input.source_on_hand, source.on_hand_after, source.safety_stock ?? input.source_safety, "source")}${transferStockCard("调入店", input.target_store, target.on_hand_before ?? input.target_on_hand, target.on_hand_after, target.safety_stock ?? input.target_safety, "target")}</div><section class="transfer-impact-card"><h3>预计经营影响（未来 ${input.sellable_days ?? "—"} 天）</h3><div><span class="material-symbols-rounded">inventory</span><p><small>预计可消化</small><strong>${economic.target_sale_before_expiry_qty ?? "未知"} 件</strong></p></div><div class="${impactTone}"><span class="material-symbols-rounded">savings</span><p><small>调拨后净经营影响</small><strong>${money(economic.net_avoidable_loss)}</strong></p></div><div><span class="material-symbols-rounded">swap_vert</span><p><small>调出店覆盖天数</small><strong>${source.coverage_before ?? "未知"} → ${source.coverage_after ?? "未知"} 天</strong></p></div></section></div>
      <form class="transfer-edit-form" data-workbench-form="transfer"><input type="hidden" name="risk_id" value="${escapeHtml(input.risk_id || risk.id || "")}" /><label>调拨数量<input name="quantity" type="number" min="1" value="${escapeHtml(input.quantity ?? "")}" /></label><label>接收门店<select id="transfer-target-picker">${network.map((item) => `<option value="${escapeHtml(item.store_id)}" ${item.store_id === input.target_store_id ? "selected" : ""}>${escapeHtml(item.district)}区 · ${escapeHtml(item.name)}（${item.distance_km} km）</option>`).join("")}</select></label><label>配送费用<input name="transport_fee" type="number" min="0" value="${escapeHtml(input.transport_fee ?? "")}" /></label><label>预计到货天数<input name="eta_days" type="number" min="0" value="${escapeHtml(input.eta_days ?? "")}" /></label><div class="transfer-form-actions"><small>${workbenchStatus(data)} · 修改数量、门店或费用后，旧测算即失效。</small><button class="secondary-action" type="button" data-workbench-save="transfer" ${calc.valid ? "" : "disabled"}>保存草稿</button><button class="secondary-action" type="submit">重新计算</button><button class="primary-action" type="button" data-workbench-submit="transfer" ${data.proposal?.status === "draft" ? "" : "disabled"}>提交审批</button></div></form>
      ${calculationNotice(calc)}
      <p class="transfer-calculation-note"><span class="material-symbols-rounded">info</span>${escapeHtml(cash.note || "内部调拨不直接算作现金释放。")} 已知现金流出为配送费 ${money(Math.abs(Number(cash.known_cash_effect || input.transport_fee || 0)))}；实际销售和回款需在执行追踪中确认。当前推荐门店在 50 家候选中排名第 ${selectedRank}。</p>
    </section>
  </div>`;
}

function expiryQueuePanel(data, activeRiskId) {
  const queue = data.expiry_queue || [];
  return `<section class='expiry-queue-panel'><div class='surface-toolbar'><div><span class='agent-page-mark'><span class='material-symbols-rounded'>inventory_2</span>近效期处置队列</span><h3>先看哪一批货最来不及卖完</h3><p>${escapeHtml(data.queue_note || '按最晚处置日期排序。')}</p></div><span class='status-pill'>${queue.length} 个批次</span></div><div class='expiry-queue-head'><span>门店／商品／批次</span><span>剩余可售时间</span><span>库存与预计可售</span><span>不处置的风险</span><span>建议动作</span><span></span></div>${queue.map((entry) => { const row = entry.input || {}, forecast = entry.forecast || {}, cash = entry.cash || {}, active = Number(entry.risk?.id) === Number(activeRiskId); return `<div class='expiry-queue-row ${active ? 'active' : ''}'><span><strong>${escapeHtml(row.store)} · ${escapeHtml(row.product)}</strong><small>批次 ${escapeHtml(row.batch)} · 最晚处置 ${escapeHtml(row.latest_disposal_date)}</small></span><b>${row.sellable_days} 天</b><span>${row.inventory_qty} 件<small>预计正常售 ${forecast.normal_sale_qty ?? '未知'} 件</small></span><span><strong>预计剩余 ${forecast.expected_remaining_qty ?? '未知'} 件</strong><small>库存成本 ${money(cash.inventory_cost)}</small></span><span><b class='evidence-badge ${row.sellable_days <= 15 ? 'insufficient' : 'partial'}'>${row.sellable_days <= 15 ? '紧急处理' : '本周处理'}</b><small>调拨＋促销＋退供组合测算</small></span><button class='secondary-action' type='button' data-expiry-select='${entry.risk?.id}'>${active ? '当前方案' : '查看方案'}</button></div>`; }).join('')}</section>`;
}

function expiryWorkbench(data) {
  const queuedEntry = (data.expiry_queue || []).find((item) => Number(item.risk?.id) === Number(data.risk?.id)) || (data.expiry_queue || [])[0] || {};
  const rawInput = data.input || {};
  const input = rawInput.product ? rawInput : (queuedEntry.input || {});
  const calc = rawInput.product ? data.calculation : { valid: true, forecast: queuedEntry.forecast || {}, cash: queuedEntry.cash || {}, alternatives: [] };
  const forecast = calc?.forecast || {}, cash = calc?.cash || {};
  return `<div class="workbench-shell">${expiryQueuePanel(data, data.risk?.id)}<section class='expiry-plan-header'><span class='agent-page-mark'><span class='material-symbols-rounded'>crisis_alert</span>当前批次处置方案</span><h3>现在处理：${escapeHtml(input.store || "未知门店")} · ${escapeHtml(input.product || "未知商品")}</h3><p>请先确定可分配到调拨、促销、退供的数量，再保存为待审批方案。</p></section><div class="workbench-context"><strong>${escapeHtml(input.store || "未知门店")} · ${escapeHtml(input.product || "未知商品")}</strong><span>批次 ${escapeHtml(input.batch || "未知")} · 剩余可售 ${input.sellable_days ?? "未知"} 天 · 最晚处置 ${escapeHtml(input.latest_disposal_date || "未知")}</span><small>库存 ${input.inventory_qty ?? "未知"} 件 · 当前30日销量 ${input.sales_30 ?? "未知"} 件</small></div>
  <form class="workbench-form four-fields" data-workbench-form="expiry-rescue"><input type="hidden" name="risk_id" value="${escapeHtml(input.risk_id || data.risk?.id || "")}" />${inputField("调拨数量", "transfer_qty", input.transfer_qty, "number", "min=0")}${inputField("促销数量", "promo_qty", input.promo_qty, "number", "min=0")}${inputField("审核促销价", "promo_price", input.promo_price, "number", "min=0")}${inputField("退供数量", "return_qty", input.return_qty, "number", "min=0")}<div class="workbench-actions"><button class="primary-action" type="submit">重新计算</button><button class="secondary-action" type="button" data-workbench-save="expiry-rescue" ${calc?.valid ? "" : "disabled"}>保存方案</button><button class="text-action" type="button" data-workbench-submit="expiry-rescue" ${data.proposal?.status === "draft" ? "" : "disabled"}>提交审批</button></div><small class="workbench-status">${workbenchStatus(data)}</small></form>${calculationNotice(calc)}
  <div class="calculation-kpis"><span>正常可售 <b>${forecast.normal_sale_qty ?? "未知"} 件</b></span><span>预计剩余 <b>${forecast.expected_remaining_qty ?? "未知"} 件</b></span><span>避免报损 <b>${money(cash.avoided_loss)}</b></span><span>预计净现金改善 <b>未知</b></span></div>
  <div class="alternative-table">${(calc?.alternatives || []).map((item) => `<div><strong>${escapeHtml(item.type)}</strong><span>${item.quantity} 件 · 费用 ${money(item.fee)} · 现金 ${money(item.cash_impact)}</span><small>${escapeHtml(item.assumption || `剩余风险 ${item.remaining_risk} 件`)}</small></div>`).join("") || '<div class="empty-state">先计算后比较正常销售、调拨、促销、退供和组合处置。</div>'}</div>
  <p class="workbench-footnote">供应商沟通仅可生成待审核草稿；未配置审批流程前不自动发送。缺项：${escapeHtml((cash.missing_fields || []).join("、") || "无")}</p></div>`;
}

function procurementEvidencePanel(data, input, inventory) {
  const risk = data.risk || {};
  const sales30 = Number(risk.sales_30 || 0);
  const totalBefore = Number(input.current_inventory || 0) + Number(input.in_transit_qty || 0) + Number(input.open_purchase_qty || 0);
  const dailySales = sales30 ? sales30 / 30 : null;
  const coverage = dailySales ? Math.round(totalBefore / dailySales) : null;
  const safety = Number(input.safety_stock || 0);
  const cushion = totalBefore - safety;
  return `<section class='procurement-evidence-panel'><div class='surface-toolbar'><div><span class='agent-page-mark'><span class='material-symbols-rounded'>fact_check</span>采购刹车依据</span><h3>不是直接停单，而是先确认这笔采购是否仍有必要</h3><p>来源：当前库存、在途采购、未执行采购单和近30天销售快照（演示数据）。</p></div><span class='evidence-badge partial'>部分支持</span></div><div class='procurement-evidence-grid'><section><span>当前库存</span><strong>${input.current_inventory ?? '未知'} 件</strong><small>安全库存 ${safety} 件</small></section><section><span>已在路上</span><strong>${input.in_transit_qty ?? '未知'} 件</strong><small>不能当作现货，但会形成后续库存</small></section><section><span>尚未执行采购</span><strong>${input.open_purchase_qty ?? '未知'} 件</strong><small>这是可以和供应商协商的部分</small></section><section><span>若不调整，预计库存位</span><strong>${totalBefore} 件</strong><small>比安全库存多 ${cushion} 件；按近30天销量 ${sales30 || '未知'} 件，约覆盖 ${coverage ?? '未知'} 天</small></section></div><div class='procurement-judgement'><span class='material-symbols-rounded'>lightbulb</span><div><strong>系统判断：可以提出“减量／取消未执行量／延期到货”的待审批方案</strong><p>理由是：即使只调整 ${input.adjustment_qty ?? '未知'} 件，调整后预计库存位仍为 ${inventory.projected_after_adjustment ?? '未知'} 件，高于安全库存 ${safety} 件。最终是否调整，还需要采购合同最小起订量、取消费用、供应商确认和未来促销计划；这些未接入的数据不能由系统替你决定。</p></div></div></section>`;
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
  if (state.workbenchLoading[route]) { target.innerHTML = '<div class="empty-state">正在读取工作台数据…</div>'; return; }
  if (!data) { target.innerHTML = '<div class="empty-state">工作台数据尚未加载，或接口读取失败。</div>'; return; }
  if (window.RetailWorkbenches) {
    const context = { state, api, money, escapeHtml, showToast, loadWorkbench, renderWorkbench, refreshCommonRecords, saveWorkbench, submitWorkbench };
    target.innerHTML = window.RetailWorkbenches.render(route, data, context);
    window.RetailWorkbenches.bind(route, target, context);
    return;
  }
  target.innerHTML = route === "transfer" ? transferWorkbench(data) : route === "expiry-rescue" ? expiryWorkbench(data) : procurementWorkbench(data);
  bindWorkbenchEvents(route, target);
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
  const data = state.workbenches.transfer, candidate = (data?.transfer_network || []).find((item) => item.store_id === storeId);
  if (!candidate) return;
  const input = { ...(data.input || {}), target_store: candidate.name, target_store_id: candidate.store_id, target_on_hand: candidate.on_hand, target_capacity: candidate.capacity, target_safety: candidate.safety_stock, target_daily_sales: candidate.daily_sales, transport_fee: candidate.transport_fee, eta_days: candidate.eta_days };
  try {
    const result = await api('/workbenches/transfer/draft', { method: 'POST', body: JSON.stringify({ input }) });
    state.workbenches.transfer = { ...data, input, calculation: null, draft: result.draft };
    renderWorkbench('transfer');
    showToast(`已选择${candidate.district}区·${candidate.name}；请重新测算后保存方案`);
  } catch (error) { showToast(`切换接收门店失败：${error.message}`, 'error'); }
}

function formInput(form) {
  const input = {};
  new FormData(form).forEach((value, key) => { input[key] = value; });
  return input;
}

async function markWorkbenchDirty(route, form) {
  const data = state.workbenches[route];
  const input = { ...(data?.input || {}), ...formInput(form) };
  try {
    const result = await api(`/workbenches/${route}/draft`, { method: "POST", body: JSON.stringify({ input }) });
    state.workbenches[route] = { ...data, input, calculation: null, draft: result.draft };
    renderWorkbench(route);
    showToast("输入已保存，旧测算已标记为待重新计算");
  } catch (error) { showToast(`保存输入失败：${error.message}`, "error"); }
}

async function calculateWorkbench(route, form) {
  const data = state.workbenches[route], input = { ...(data?.input || {}), ...formInput(form) };
  try {
    const result = await api(`/workbenches/${route}/calculate`, { method: "POST", body: JSON.stringify({ input }) });
    state.workbenches[route] = { ...data, input: result.input, calculation: result.calculation, draft: result.draft };
    renderWorkbench(route);
    showToast(result.calculation.valid ? "测算已更新" : "约束未通过，已阻止保存方案", result.calculation.valid ? "success" : "error");
  } catch (error) { showToast(`计算失败：${error.message}`, "error"); }
}

async function saveWorkbench(route) {
  const data = state.workbenches[route];
  try {
    const result = await api(`/workbenches/${route}/save`, { method: "POST", body: JSON.stringify({ input: data.input }) });
    state.workbenches[route] = { ...data, calculation: result.calculation, proposal: result.proposal, draft: { ...(data.draft || {}), status: "saved" } };
    renderWorkbench(route); await refreshCommonRecords(); showToast("方案草稿已保存；尚未修改外部业务单据");
  } catch (error) { showToast(`保存方案失败：${error.message}`, "error"); }
}

async function submitWorkbench(route) {
  const proposalId = state.workbenches[route]?.proposal?.id;
  if (!proposalId) return;
  try { const proposal = await api(`/proposals/${proposalId}/submit`, { method: "POST" }); state.workbenches[route].proposal = proposal; renderWorkbench(route); await refreshCommonRecords(); showToast("已提交负责人审批"); }
  catch (error) { showToast(`提交失败：${error.message}`, "error"); }
}

function bindWorkbenchEvents(route, target) {
  const form = $("[data-workbench-form]", target);
  form?.addEventListener("submit", (event) => { event.preventDefault(); calculateWorkbench(route, form); });
  form?.addEventListener("change", () => markWorkbenchDirty(route, form));
  $("[data-workbench-save]", target)?.addEventListener("click", () => saveWorkbench(route));
  $("[data-workbench-submit]", target)?.addEventListener("click", () => submitWorkbench(route));
}

async function loadWorkbench(route, riskId = null) {
  if (!API_BASE || state.workbenchLoading[route] || !state.risks.length) { renderWorkbench(route); return; }
  state.workbenchLoading[route] = true; renderWorkbench(route);
  try { state.workbenches[route] = await api(`/workbenches/${route}${riskId ? `?risk_id=${riskId}` : ""}`); }
  catch (error) { showToast(`工作台读取失败：${error.message}`, "error"); }
  finally { state.workbenchLoading[route] = false; renderWorkbench(route); }
}

async function loadDiagnosisCandidates() {
  if (!API_BASE) { renderDiagnosis(); return; }
  const priority = state.diagnosisPriority === "all" ? "" : `?priority=${encodeURIComponent(state.diagnosisPriority)}`;
  try {
    const payload = await api(`/risks${priority}`);
    state.diagnosisRisks = payload.items || [];
    state.diagnosisTotal = Number(payload.filtered_total ?? payload.total ?? state.diagnosisRisks.length);
    if (!state.diagnosisRisks.some((item) => Number(item.id) === Number(state.diagnosisRiskId))) {
      state.diagnosisRiskId = state.diagnosisRisks[0]?.id || null;
      state.diagnosisDetail = null;
    }
  } catch (error) {
    showToast(`候选清单读取失败：${error.message}`, "error");
  }
  renderDiagnosis();
}

function renderDiagnosis() {
  const target = $("#slow-list");
  if (!target) return;
  if (window.RetailApp) { window.RetailApp.renderDiagnosis(); return; }
  const regionRisks = state.diagnosisRisks || scopedRisks();
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
  const displayedCandidateTotal = state.diagnosisTotal || candidateCount;
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
  const viewTabs = [["list", "滞销库存列表"], ["reasons", "原因分析"], ["actions", "处置建议"], ["stores", "门店分布"], ["suppliers", "供应商分布"]];
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
  $("[data-open-risk]", target)?.addEventListener("click", async (event) => {
    const riskId = Number(event.currentTarget.dataset.openRisk);
    const riskForInvestigation = regionRisks.find((item) => Number(item.id) === riskId);
    if (riskForInvestigation && !state.risks.some((item) => Number(item.id) === riskId)) state.risks = [riskForInvestigation, ...state.risks];
    state.selectedId = riskId;
    state.parentRoute = "slow-diagnosis";
    window.location.hash = "risks";
    renderRiskList();
    await loadSelectedDetail();
  });
  $("#slow-refresh-analysis")?.addEventListener("click", async () => {
    if (!API_BASE) return;
    try {
      const [dashboard, riskPayload] = await Promise.all([api("/dashboard"), api("/risks")]);
      state.dashboard = dashboard;
      state.risks = riskPayload.items || [];
      state.riskTotal = riskPayload.total || state.risks.length;
      await loadDiagnosisCandidates();
      renderAgentModules();
      showToast("已按当前导入快照刷新老师口径分析结果");
    } catch (error) { showToast(`刷新分析结果失败：${error.message}`, "error"); }
  });
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
  const regionLabel = district ? `${district}区区域` : (summary.region_label || "杭州市 · 全部50家门店");
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
  const loading = state.todayWorkbenchLoading === todayDetailCacheKey(item);
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

function queueTodayWorkbench(item) {
  const key = todayDetailCacheKey(item);
  if (!key || !["transfer", "expiry-rescue", "procurement-brake"].includes(item?.route) || state.todayWorkbenchCache[key] || state.todayWorkbenchLoading === key || !API_BASE) return;
  state.todayWorkbenchLoading = key;
  api(`/workbenches/${item.route}?risk_id=${item.risk_id}`)
    .then((data) => { state.todayWorkbenchCache[key] = data; })
    .catch((error) => showToast(`读取任务方案失败：${error.message}`, "error"))
    .finally(() => { state.todayWorkbenchLoading = null; renderSupportPages(); });
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
  window.RetailApp?.renderDiagnosis();
  window.RetailApp?.renderToday();
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

  const todayFilters = { pending: pendingItems, approval: approvalItems, completed: [] };
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
  $$("[data-today-filter]").forEach((button) => button.addEventListener("click", () => { state.todayFilter = button.dataset.todayFilter; state.todaySelectedItemId = null; renderSupportPages(); }));
  $$("[data-today-select]").forEach((button) => button.addEventListener("click", () => { state.todaySelectedItemId = button.dataset.todaySelect; renderSupportPages(); }));
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

  $$("[data-open-risk]").forEach((button) => button.addEventListener("click", async () => {
    state.selectedId = Number(button.dataset.openRisk);
    state.parentRoute = button.dataset.sourceRoute || agentRouteForRisk(selectedRisk());
    window.location.hash = "risks";
    renderRiskList();
    await loadSelectedDetail();
  }));
  $$("[data-approve-proposal]").forEach((button) => button.addEventListener("click", () => approveProposal(button.dataset.approveProposal)));
}

function renderApprovalList() {
  const target = $("#approval-list"); if (!target) return;
  const items = state.proposals.filter((proposal) => ["pending_approval", "approved", "needs_replan", "execution_task_created"].includes(proposal.status));
  $("#approval-page-count").textContent = `${items.length} 项`;
  target.innerHTML = items.map((proposal) => {
    const summary = proposal.approval_summary || { title: `处置方案 ${proposal.id}`, detail: "确认当前事实与计算版本后再进入执行。", boundary: "审批仅绑定当前版本。" };
    return `<div class="task-row"><div><strong>${escapeHtml(summary.title)}</strong><p>${escapeHtml(summary.detail)}</p></div><div><strong>${escapeHtml(window.RetailApp?.taskLabel(proposal.status) || proposal.status)}</strong><p>${escapeHtml(proposal.status === "needs_replan" ? "事实或输入已变更，旧审批不可沿用" : summary.boundary)}</p></div><span class="evidence-badge">V${proposal.current_version}</span>${proposal.status === "pending_approval" ? `<button class="secondary-action" data-approve-proposal="${proposal.id}">确认并审批</button>` : proposal.status === "approved" ? `<button class="secondary-action" data-execute-proposal="${proposal.id}">生成待执行任务</button>` : proposal.status === "execution_task_created" ? '<button class="secondary-action" data-go="execution">查看执行进度</button>' : "<span></span>"}</div>`;
  }).join("") || '<div class="empty-state">暂无待审批或待执行的方案版本。</div>';
  $$("[data-approve-proposal]", target).forEach((button) => button.addEventListener("click", () => approveProposal(button.dataset.approveProposal)));
  $$("[data-execute-proposal]", target).forEach((button) => button.addEventListener("click", () => executeProposal(button.dataset.executeProposal)));
}

async function approveProposal(id) {
  const version = state.proposals.find((proposal) => proposal.id === id)?.current_version;
  try { await api(`/proposals/${id}/approve`, { method: "POST", headers: { "Idempotency-Key": `ui-approve-${id}-v${version}` } }); await refreshCommonRecords(); window.RetailApp?.showApprovalFollowUp(id); showToast("审批通过，已移入「审批后跟进」；请继续安排执行"); return true; }
  catch (error) { showToast(`审批失败：${error.message}`, "error"); return false; }
}

async function executeProposal(id) {
  const version = state.proposals.find((proposal) => proposal.id === id)?.current_version;
  try { const task = await api(`/proposals/${id}/execute`, { method: "POST", headers: { "Idempotency-Key": `ui-execute-${id}-v${version}` } }); await refreshCommonRecords(); showToast("已生成待执行任务，可在「审批后跟进」查看；仍需负责人执行并回填回执"); return task; }
  catch (error) { showToast(`创建执行任务失败：${error.message}`, "error"); return null; }
}

function renderExecutionList() {
  const target = $("#execution-list"); if (!target) return;
  $("#execution-page-count").textContent = `${state.executionTasks.length} 项`;
  const statusLabel = (status) => window.RetailApp?.taskLabel(status) || status;
  target.innerHTML = state.executionTasks.map((task) => {
    const proposal = state.proposals.find((item) => item.id === task.proposal_id);
    const title = proposal?.approval_summary?.title?.replace(/^审批/, "") || `任务 ${task.id}`;
    const statuses = ["pending_dispatch", "in_transit", "awaiting_receipt", "received", "completed", "exception"];
    return `<div class="execution-row"><div><strong>${escapeHtml(title)}</strong><p>${escapeHtml(proposal?.approval_summary?.detail || "请安排负责人执行并记录回执。")}</p><p>任务 ${escapeHtml(task.id)} · V${task.proposal_version} · ${escapeHtml(statusLabel(task.status))}</p><div class="timeline-mini">${(task.metadata?.timeline || []).map((event) => `<span>${escapeHtml(statusLabel(event.status))} · ${escapeHtml(event.at)}</span>`).join("") || "<span>任务已生成，待安排负责人执行；尚未派单到门店</span>"}</div></div><form data-execution-form="${escapeHtml(task.id)}"><label>更新状态<select name="status" required>${statuses.includes(task.status) ? '' : '<option value="" selected disabled>选择实际执行状态</option>'}${statuses.map((status) => `<option value="${status}" ${task.status === status ? 'selected' : ''}>${escapeHtml(statusLabel(status))}</option>`).join('')}</select></label><label>回执号（收货/完成必填）<input name="receipt_ref" value="${escapeHtml(task.metadata?.receipt_ref || '')}" placeholder="外部单据或签收回执" /></label><button class="secondary-action" type="submit">记录状态</button></form></div>`;
  }).join("") || '<div class="empty-state">暂无执行任务。请在今日工作台的「审批后跟进」中生成待执行任务。</div>';
  $$("[data-execution-form]", target).forEach((form) => form.addEventListener("submit", async (event) => { event.preventDefault(); const values = formInput(form); try { await api(`/execution-tasks/${form.dataset.executionForm}/status`, { method: "POST", body: JSON.stringify(values) }); await refreshCommonRecords(); showToast("执行状态与回执已记录"); } catch (error) { showToast(`状态更新失败：${error.message}`, "error"); } }));
}

function renderDataCenter() {
  const data = state.dataCenter, sourceTarget = $("#data-sources"), history = $("#import-history");
  if (!sourceTarget || !history) return;
  const source = data?.sources?.[0] || {};
  const isReal = data?.mode === "real_inventory_snapshot";
  const realSummary = source.summary || {};
  const currentTitle = isReal ? `当前查看：真实库存快照（${source.last_snapshot || "未标注时点"}）` : "当前查看：2026年第二季度库存分析";
  const currentMeta = isReal
    ? `库存时点：${source.last_snapshot || "未标注"} <i></i> 覆盖范围：${realSummary.stores || 0} 个门店 <i></i> 明细行：${Number(realSummary.rows || 0).toLocaleString()} <i></i> 数据来源：真实文件导入`
    : "销售期间：2026-04-01 ～ 2026-06-30 <i></i> 库存时点：2026-06-30 <i></i> 覆盖范围：50家门店 <i></i> 数据来源：手动导入 <i></i> 更新于：2026-07-02 14:21";
  const statusLabel = isReal ? "已接入" : "已完成";
  sourceTarget.innerHTML = `<section class="data-current-analysis"><div class="data-current-icon"><span class="material-symbols-rounded">database</span></div><div class="data-current-copy"><div class="data-current-title"><strong>${escapeHtml(currentTitle)}</strong><span class="status-pill success">${statusLabel}</span></div><p>${currentMeta}</p><small>当前数据源：${escapeHtml(source.name || "季度经营数据")} · 已覆盖 ${escapeHtml((source.fields || []).join("、") || "库存、销售、采购、效期")}${isReal ? ` · 库存成本 ${money(realSummary.cost_total)} · SKU ${Number(realSummary.skus || 0).toLocaleString()}` : ""}</small></div><div class="data-current-actions"><button class="secondary-action" type="button" data-go="overview">查看分析结果</button><button class="secondary-action" id="data-view-files" type="button">查看本次文件</button></div></section>`;
  $("#data-view-files")?.addEventListener("click", () => showToast(isReal ? `本次文件：${source.name || "真实库存明细表"}` : "本次分析包含库存、销售与采购共 3 份文件"));
  const schemas = data?.import_schemas || {};
  const kind = $("#import-kind")?.value || "inventory";
  const schema = schemas[kind] || { label: "库存表", required: ["sku", "store", "inventory_qty"], description: "每行一个商品在一个门店的当前库存。" };
  const requirements = $("#import-requirements");
  if (requirements) requirements.innerHTML = `<strong>${escapeHtml(schema.label)}需要的字段</strong><span>${schema.required.map((field) => `<code>${escapeHtml(field)}</code>`).join("")}</span><small>${escapeHtml(schema.description)}</small>`;
  const demoHistory = [
    { name: "2026年第二季度库存分析", sales: "2026-04-01 ～ 2026-06-30", inventory: "2026-06-30", stores: "50家门店", files: 3, status: "已完成", created: "2026-07-02 14:21" },
    { name: "2026年第一季度库存分析", sales: "2026-01-01 ～ 2026-03-31", inventory: "2026-03-31", stores: "50家门店", files: 3, status: "已完成", created: "2026-04-03 10:15" },
    { name: "2026年8月近效期专项分析", sales: "2026-08-01 ～ 2026-08-31", inventory: "2026-08-31", stores: "48家门店", files: 2, status: "已完成", created: "2026-09-01 16:32" },
    { name: "2026年9月库存检查", sales: "2026-09-01 ～ 2026-09-15", inventory: "2026-09-15", stores: "50家门店", files: 2, status: "待修正", created: "2026-09-15 11:20" },
    { name: "2026年3月采购复盘", sales: "2026-03-01 ～ 2026-03-31", inventory: "2026-03-31", stores: "50家门店", files: 4, status: "已完成", created: "2026-04-01 09:26" },
  ];
  const importedHistory = (data?.imports || []).map((item) => {
    const summary = item.summary || {}, errors = item.errors || [];
    return { name: item.filename?.replace(/\.(xlsx?|csv|tsv)$/i, "") || item.id, sales: "本次导入", inventory: "待分析", stores: "当前区域", files: 1, status: item.status === "validated" ? "已完成" : "待修正", created: item.created_at || "刚刚", note: errors.map((error) => error.message).join("；") };
  });
  const realHistory = isReal ? [{
    name: source.name || "真实库存快照",
    sales: "未提供销售明细",
    inventory: source.last_snapshot || "未标注",
    stores: `${realSummary.stores || 0} 个门店`,
    files: 1,
    status: "已完成",
    created: source.last_snapshot || "已导入",
  }] : [];
  let historyRows = realHistory.length ? realHistory : (importedHistory.length ? importedHistory : demoHistory);
  const search = state.analysisSearch.trim().toLowerCase();
  historyRows = historyRows.filter((item) => (!search || item.name.toLowerCase().includes(search)) && (state.analysisStatus === "全部状态" || item.status === state.analysisStatus));
  if (state.analysisSort === "按创建时间") historyRows = [...historyRows].sort((a, b) => b.created.localeCompare(a.created));
  history.innerHTML = historyRows.map((item) => `<div class="analysis-history-row"><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.sales)}</span><span>${escapeHtml(item.inventory)}</span><span>${escapeHtml(item.stores)}</span><span>${item.files}</span><b class="analysis-status ${item.status === "已完成" ? "done" : "fix"}">${escapeHtml(item.status)}</b><time>${escapeHtml(item.created)}</time><div class="analysis-history-actions"><button type="button" data-go="overview">${item.status === "已完成" ? "查看结果" : "继续处理"}</button><button type="button" data-history-files="${escapeHtml(item.name)}">查看文件</button><button type="button" aria-label="更多操作">•••</button></div></div>`).join("") || '<div class="empty-state">没有匹配的分析记录。</div>';
  const count = $("#analysis-count");
  if (count) count.textContent = `共 ${historyRows.length || 0} 条记录`;
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
  if (!API_BASE) return;
  try {
    const [items, proposals, tasks, data] = await Promise.all([api("/work-items"), api("/proposals"), api("/execution-tasks"), api("/data-center")]);
    state.workItems = items.items || []; state.proposals = proposals.items || []; state.executionTasks = tasks.items || []; state.dataCenter = data;
    renderSupportPages();
  } catch (error) { showToast(`协同记录读取失败：${error.message}`, "error"); }
}

async function hydrate() {
  if (HACKATHON_PREVIEW) {
    state.dataCenter = { mode: "sample_replay" };
    renderRiskList();
    renderSupportPages();
    renderCases([]);
    return;
  }
  try {
    const [dashboard, riskPayload, casePayload, items, proposals, tasks, data] = API_BASE
      ? await Promise.all([api("/dashboard"), api("/risks"), api("/cases"), api("/work-items"), api("/proposals"), api("/execution-tasks"), api("/data-center")])
      : [null, { items: fallbackRisks }, { items: [] }, { items: [] }, { items: [] }, { items: [] }, null];
    state.dashboard = dashboard;
    const realMode = data?.mode === "real_inventory_snapshot";
    state.risks = riskPayload.items?.length ? riskPayload.items : (realMode ? [] : fallbackRisks);
    state.riskTotal = riskPayload.total || state.risks.length;
    state.diagnosisRisks = state.risks;
    state.diagnosisTotal = Number(riskPayload.filtered_total ?? riskPayload.total ?? state.risks.length);
    state.workItems = items.items || []; state.proposals = proposals.items || []; state.executionTasks = tasks.items || []; state.dataCenter = data;
    window.RetailHackathonIntegration?.refreshContext?.();
    window.RetailApp?.renderOverview();
    if (!state.risks.some((risk) => Number(risk.id) === Number(state.selectedId))) state.selectedId = state.risks[0]?.id;
    renderRiskList();
    renderSupportPages();
    renderCases(casePayload.items || []);
    if (state.risks.length) {
      await loadSelectedDetail();
      await loadDiagnosisReport(state.diagnosisRiskId || state.selectedId);
      if (!realMode) await Promise.all(["transfer", "expiry-rescue", "procurement-brake"].map((route) => loadWorkbench(route)));
    }
  } catch (error) {
    state.risks = [...fallbackRisks]; state.riskTotal = state.risks.length;
    window.RetailHackathonIntegration?.refreshContext?.();
    renderRiskList();
    renderSupportPages();
    renderSelectedDetail();
    showToast(`本地 API 暂不可用，正在显示可重复样例：${error.message}`, "error");
  }
}

function renderCases(cases) {
  state.confirmedCases = cases || [];
  renderCaseLibrary();
}

function caseCategoryCount(category) {
  return category === "all" ? featuredCases.length : featuredCases.filter((item) => item.tags.includes(category)).length;
}

function caseCover(item, detail = false) {
  return `<div class="case-snack-cover case-snack-cover-${escapeHtml(item.visual)}${detail ? " case-snack-cover-detail" : ""}">
    <div class="case-snack-cover-copy"><span>零食仓 · 演示案例</span><strong>${escapeHtml(item.product)}</strong><small>${escapeHtml(item.category)}</small></div>
    <img src="${escapeHtml(item.image)}" alt="${escapeHtml(item.product)}商品示意图" />
  </div>`;
}

function renderCaseLibrary() {
  const tabs = $("#case-category-tabs");
  const target = $("#case-library");
  if (!tabs || !target) return;
  tabs.innerHTML = caseCategories.map((category) => `<button type="button" role="tab" aria-selected="${state.caseFilter === category.id}" class="${state.caseFilter === category.id ? "active" : ""}" data-case-category="${category.id}">${escapeHtml(category.label)} (${caseCategoryCount(category.id)})</button>`).join("");
  let visible = state.caseFilter === "all"
    ? featuredCases
    : featuredCases.filter((item) => item.tags.includes(state.caseFilter));
  target.innerHTML = visible.map((item) => `
    <article class="success-case-card ${item.id === "CASE-TRANSFER-01" ? "case-featured" : ""}">
      ${caseCover(item)}
      <div class="success-case-copy">
        <div class="case-card-kicker"><span>${escapeHtml(item.category)}</span><span>${escapeHtml(item.outcome.status)}</span></div>
        <h2>${escapeHtml(item.title)}</h2>
        <p>${escapeHtml(item.summary)}</p>
        <div class="case-card-route" aria-label="案例处理路线"><span>${escapeHtml(item.flow[0].module)}</span><i aria-hidden="true">→</i><span>${escapeHtml(item.flow[1].module)}</span><i aria-hidden="true">→</i><span>${escapeHtml(item.flow[3].stage)}</span></div>
        <div class="case-card-outcome"><span>${escapeHtml(item.outcome.label)}</span><strong>${escapeHtml(item.outcome.value)}</strong></div>
        <div class="success-case-metrics">${item.metrics.map((metric) => `<div><strong>${escapeHtml(metric[0])}</strong><span>${escapeHtml(metric[1])}</span></div>`).join("")}</div>
        <div class="success-case-footer"><p><b>适用场景：</b>${escapeHtml(item.scenario)}</p><button type="button" data-case-detail="${escapeHtml(item.id)}">查看过程与资金明细 <span class="material-symbols-rounded">arrow_forward</span></button></div>
      </div>
    </article>`).join("") || '<div class="case-library-empty">当前分类还没有演示案例。</div>';
}

function openCaseDetail(caseId) {
  const item = featuredCases.find((entry) => entry.id === caseId);
  if (!item) return;
  state.selectedCaseId = item.id;
  $("#case-detail-category").textContent = `演示案例 · ${item.category}`;
  $("#case-detail-title").textContent = item.title;
  $("#case-detail-summary").textContent = item.summary;
  $("#case-detail-body").innerHTML = `
    <section class="case-detail-result"><div><span>${escapeHtml(item.outcome.status)} · ${escapeHtml(item.outcome.label)}</span><strong>${escapeHtml(item.outcome.value)}</strong></div><p>${escapeHtml(item.outcome.note)}</p></section>
    <section class="case-detail-section"><header><h3>从发现到结果</h3><p>每一步都写清负责模块、决策和执行状态</p></header><ol class="case-journey">${item.flow.map((step) => `<li><span class="case-journey-stage">${escapeHtml(step.stage)}</span><div><small>${escapeHtml(step.module)}</small><strong>${escapeHtml(step.title)}</strong><p>${escapeHtml(step.detail)}</p></div></li>`).join("")}</ol></section>
    <section class="case-detail-section"><header><h3>钱是怎样流动的</h3><p>库存转移、销售回款和未来少付款分别计算</p></header><div class="case-money-path">${[...item.moneyFlow.slice(0, 2), { label: item.outcome.label, value: item.outcome.value }].map((node) => `<div><small>${escapeHtml(node.label)}</small><strong>${escapeHtml(node.value)}</strong></div>`).join('<span aria-hidden="true">→</span>')}</div><div class="case-money-flow">${item.moneyFlow.map((line) => `<div class="case-money-line is-${escapeHtml(line.type)}"><div><strong>${escapeHtml(line.label)}</strong><small>${escapeHtml(line.detail)}</small></div><b>${escapeHtml(line.value)}</b></div>`).join("")}</div><p class="case-money-formula">${escapeHtml(item.formula)}</p></section>
    <p class="case-detail-story">以上为“零食仓”的虚构演示回放，不代表真实企业的执行记录。进入相关工作台后，请以当前数据重新核查数量、审批状态和回执。</p>`;
  $("#case-detail-use").textContent = "打开相似场景工作台";
  const modal = $("#case-detail-modal");
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
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
  window.scrollTo({ top: 0, behavior: "instant" });
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
    "decision-entry": "方案决策", "execution-followup": "审批与执行跟进",
    "expiry-rescue": "近效期现金抢救", "procurement-brake": "采购刹车", risks: "风险案件",
    tasks: "核查任务", approvals: "方案审批", execution: "执行追踪", simulation: "现金流模拟",
    cases: "案例库", data: "数据中心", settings: "系统设置",
  };
  document.title = `货不压钱 · ${titles[route]}`;
  window.RetailApp?.routeChanged(route);
  if (route === "cases") renderCaseLibrary();
  if (["transfer", "expiry-rescue", "procurement-brake"].includes(route) && state.dashboard) loadWorkbench(route);
  if (route === "slow-diagnosis" && state.dashboard) {
    const diagnosisId = state.risks.some((risk) => Number(risk.id) === Number(state.diagnosisRiskId)) ? state.diagnosisRiskId : scopedRisks()[0]?.id;
    if (diagnosisId) loadDiagnosisReport(diagnosisId);
    else renderDiagnosis();
  }
  if (["today", "tasks", "approvals", "execution", "data"].includes(route)) refreshCommonRecords();
  window.dispatchEvent(new CustomEvent("retail:route-change", { detail: { route } }));
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
  $("#investigation-title").textContent = `核查 ${risk.product}`;
  $("#feedback-text").value = focusField ? `请补充${missingLabel(focusField)}：` : $("#case-note").value.trim();
  $("#investigation-modal").classList.add("open");
  $("#investigation-modal").setAttribute("aria-hidden", "false");
  setTimeout(() => $("#feedback-text").focus(), 0);
}

function closeInvestigationModal() {
  $("#investigation-modal").classList.remove("open");
  $("#investigation-modal").setAttribute("aria-hidden", "true");
}

async function createInvestigation() {
  const risk = selectedRisk();
  if (!risk) return;
  try {
    const investigation = API_BASE
      ? await api(`/risks/${risk.id}/investigations`, { method: "POST", body: JSON.stringify({}) })
      : { id: "INV-STATIC" };
    state.investigationId = investigation.id;
    risk.investigation_status = "pending";
    renderRiskList();
    renderSelectedDetail();
    openInvestigationModal();
  } catch (error) {
    showToast(`核查任务创建失败：${error.message}`, "error");
  }
}

async function submitFeedback() {
  const rawText = $("#feedback-text").value.trim();
  if (!rawText) {
    showToast("请先描述核查发现", "error");
    return;
  }
  if (!state.investigationId) {
    await createInvestigation();
    if (!state.investigationId) return;
  }
  try {
    const feedback = API_BASE
      ? await api(`/investigations/${state.investigationId}/feedback`, { method: "POST", body: JSON.stringify({ raw_text: rawText, submitted_at: new Date().toISOString() }) })
      : { id: "FB-STATIC" };
    state.feedbackId = feedback.id;
    $("#confirm-feedback").disabled = false;
    $("#feedback-status").textContent = "第 2 步：草稿已生成，请检查后确认";
    const steps = $$(".modal-steps li");
    steps[0].classList.remove("active");
    steps[1].classList.add("active");
    showToast("原文已留存，正式事实尚未改变");
  } catch (error) {
    showToast(`反馈草稿失败：${error.message}`, "error");
  }
}

async function confirmFeedback() {
  if (!state.feedbackId) return;
  try {
    if (API_BASE) {
      await api(`/feedback/${state.feedbackId}/confirm`, {
        method: "POST",
        body: JSON.stringify({ confirmed: { verification_method: $("#verification-status").value, remediation_status: "unknown", user_checked: true } }),
      });
    }
    $("#feedback-status").textContent = "第 3 步：反馈已确认，受影响方案需要重算";
    $("#confirm-feedback").disabled = true;
    const steps = $$(".modal-steps li");
    steps[1].classList.remove("active");
    steps[2].classList.add("active");
    await hydrate();
    showToast("新事实已保存；旧方案已失效并等待重新评估");
    setTimeout(closeInvestigationModal, 700);
  } catch (error) {
    showToast(`确认失败：${error.message}`, "error");
  }
}

function renderChat() {
  const thread = $("#agent-chat-thread");
  if (!thread) return;
  const greeting = { role: "agent", text: `我是现金流 Agent。当前分析范围是“${REGIONS[state.region]?.label || "全市门店"}”。你可以直接说“30天内释放20万元，不要降价”，我会同步到测算并如实标记未知数据。` };
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

async function sendChatMessage(rawText) {
  const text = rawText.trim();
  if (!text) return;
  state.chatMessages.push({ role: "user", text });
  const parsed = parseChatRequest(text);
  if (parsed.targetWan !== null) $("#simulation-target").value = parsed.targetWan;
  if (parsed.days) $("#simulation-days").value = parsed.days;
  if (parsed.constraints) $("#simulation-constraints").value = parsed.constraints;
  $("#simulation-request").value = text;
  renderChat();
  const result = await runSimulation();
  const goal = money(Number($("#simulation-target").value || 0) * 10000);
  const period = $("#simulation-days").value;
  if (!result) {
    state.chatMessages.push({ role: "agent", text: "当前测算接口未能返回结果，已保留你的输入；请稍后重试。" });
  } else if (result.cash_basis?.completeness === "unavailable") {
    state.chatMessages.push({ role: "agent", text: `我已将你的描述同步为 ${period} 天内 ${goal}。当前区域没有可确认的现金事件，缺少：${(result.cash_basis.missing_fields || []).join("、")}。我不会把调拨或未验证促销当作现金释放。` });
  } else {
    state.chatMessages.push({ role: "agent", text: `我已按 ${period} 天、目标 ${goal} 重新组合当前工作台草稿。预计可计算净现金改善 ${money(result.achieved)}，仍有缺口 ${money(result.gap)}；可在右侧排除动作后再次统一计算。` });
  }
  renderChat();
}

async function runSimulation(event) {
  event?.preventDefault();
  const targetWan = Number($("#simulation-target").value);
  const horizonDays = Number($("#simulation-days").value);
  const constraints = $("#simulation-constraints").value.trim();
  const naturalRequest = $("#simulation-request").value.trim();
  const region = REGIONS[state.region] || REGIONS.all;
  $("#simulation-status").textContent = "正在计算";
  try {
    const result = API_BASE
      ? await api("/scenarios/simulate", { method: "POST", body: JSON.stringify({ target: targetWan * 10000, horizon_days: horizonDays, constraints: { text: constraints, natural_request: naturalRequest, region_store_keywords: region.stores }, excluded_action_ids: state.simulationExcluded || [] }) })
      : { status: "gap", achieved: 5600, gap: targetWan * 10000 - 5600, selected: [] };
    state.simulationResult = result;
    $("#simulation-status").textContent = result.status === "feasible" ? "可行建议" : `仍有缺口 ${money(result.gap)}`;
    $("#simulation-understanding").textContent = `已确认输入：${naturalRequest || "未提供自然语言描述"}；按 ${horizonDays} 天、目标 ${money(targetWan * 10000)}、约束“${constraints || "无"}”计算。`;
    $("#simulation-output").className = "";
    $("#simulation-output").innerHTML = `<div class="simulation-summary"><span>基准方案 <b>${money(0)}</b></span><span>调整方案 <b>${money(result.achieved)}</b></span><span>目标缺口 <b>${money(result.gap)}</b></span><span>现金口径 <b>${escapeHtml(result.cash_basis?.completeness || "未知")}</b></span></div><div class="cash-curve"><i style="width:${Math.min(100, Number(result.achieved || 0) / Math.max(1, Number(result.target || 1)) * 100)}%"></i><span>第 0 天</span><span>第 ${horizonDays} 天</span></div>${(result.selected || []).map((item) => `<label class="simulation-result-row"><input type="checkbox" data-simulation-action="${escapeHtml(item.id)}" checked /><div><strong>${escapeHtml(item.label)}</strong><p>来自当前已计算工作台；同一草稿仅计一次。缺项：${escapeHtml((item.missing_fields || []).join("、") || "无")}</p></div><b>${money(item.cash_effect)}</b></label>`).join("") || '<div class="empty-state">当前约束下没有可计算的候选动作；请先在工作台完成计算，或补充缺失事实。</div>'}<p class="workbench-footnote">风险与缺项：${escapeHtml((result.cash_basis?.missing_fields || []).join("、") || "已按当前草稿检查；内部调拨和无回款依据的近效期动作不计入净现金改善。")}</p>`;
    $$('[data-simulation-action]', $("#simulation-output")).forEach((box) => box.addEventListener("change", () => { state.simulationExcluded = $$('[data-simulation-action]', $("#simulation-output")).filter((item) => !item.checked).map((item) => item.dataset.simulationAction); runSimulation(); }));
    return result;
  } catch (error) {
    $("#simulation-status").textContent = "计算失败";
    showToast(`模拟失败：${error.message}`, "error");
    return null;
  }
}

function bindEvents() {
  window.addEventListener("hashchange", renderRoute);
  document.addEventListener("click", (event) => {
    const go = event.target.closest("[data-go]");
    if (go) {
      window.location.hash = go.dataset.go;
      const riskId = Number(go.dataset.workbenchRisk || 0);
      const linkedRisk = state.risks.find((risk) => Number(risk.id) === riskId);
      if (riskId && linkedRisk && agentRouteForRisk(linkedRisk) === go.dataset.go) loadWorkbench(go.dataset.go, riskId);
    }
  });
  $("#overview-toggle-store-chart").addEventListener("click", () => {
    state.overviewShowAllStores = !state.overviewShowAllStores;
    renderOperatingOverview();
  });
  $("#overview-store-bars").addEventListener("click", (event) => {
    const bar = event.target.closest("[data-overview-store]");
    if (!bar) return;
    state.overviewSelectedStore = state.overviewSelectedStore === bar.dataset.overviewStore ? null : bar.dataset.overviewStore;
    renderOperatingOverview();
  });
  $("#overview-clear-store-filter").addEventListener("click", () => {
    state.overviewSelectedStore = null;
    renderOperatingOverview();
  });
  $("#priority-filter").addEventListener("change", (event) => { state.priorityFilter = event.target.value; renderRiskList(); });
  $("#type-filter").addEventListener("change", (event) => { state.typeFilter = event.target.value; renderRiskList(); });
  $("#evidence-filter").addEventListener("change", (event) => { state.evidenceFilter = event.target.value; renderRiskList(); });
  $("#filter-toggle").addEventListener("click", () => { $("#filter-row").hidden = !$("#filter-row").hidden; });
  $$(".queue-tabs button").forEach((button) => button.addEventListener("click", () => {
    $$(".queue-tabs button").forEach((item) => item.classList.toggle("active", item === button));
  }));
  $("#global-search").addEventListener("input", (event) => {
    state.search = event.target.value;
    if (state.search && currentRoute() !== "risks") window.location.hash = "risks";
    renderRiskList();
  });
  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      $("#global-search").focus();
    }
    if (event.key === "Escape") {
      closeAgent();
      closeInvestigationModal();
      closeCaseDetail();
      document.body.classList.remove("nav-open");
      $("#drawer-backdrop").classList.remove("open");
    }
  });
  $("#refresh-data").addEventListener("click", async (event) => {
    event.currentTarget.disabled = true;
    await hydrate();
    event.currentTarget.disabled = false;
    showToast("已重新读取本地数据快照");
  });
  $("#agent-toggle").addEventListener("click", openAgent);
  $("#agent-close").addEventListener("click", closeAgent);
  $("#drawer-backdrop").addEventListener("click", () => {
    closeAgent();
    document.body.classList.remove("nav-open");
    $("#drawer-backdrop").classList.remove("open");
  });
  $("#mobile-nav").addEventListener("click", () => {
    document.body.classList.toggle("nav-open");
    $("#drawer-backdrop").classList.toggle("open", document.body.classList.contains("nav-open"));
  });
  $("#mobile-back").addEventListener("click", () => $(".risk-module").classList.remove("show-detail"));
  $("#create-investigation").addEventListener("click", createInvestigation);
  $("#defer-case").addEventListener("click", () => showToast("案件保留在待核查队列，业务状态未改变"));
  $("#case-note").addEventListener("input", (event) => { $("#note-count").textContent = event.target.value.length; });
  $("#toast button").addEventListener("click", () => $("#toast").classList.remove("show"));
  $("#modal-close").addEventListener("click", closeInvestigationModal);
  $("#investigation-modal").addEventListener("click", (event) => { if (event.target === $("#investigation-modal")) closeInvestigationModal(); });
  $("#case-category-tabs").addEventListener("click", (event) => {
    const tab = event.target.closest("[data-case-category]");
    if (!tab) return;
    state.caseFilter = tab.dataset.caseCategory;
    renderCaseLibrary();
  });
  $("#case-library").addEventListener("click", (event) => {
    const detail = event.target.closest("[data-case-detail]");
    if (detail) openCaseDetail(detail.dataset.caseDetail);
  });
  $("#request-case").addEventListener("click", () => showToast("当前展示演示案例；真实案例需核查事实与执行回执后收录"));
  $("#case-detail-close").addEventListener("click", closeCaseDetail);
  $("#case-detail-modal").addEventListener("click", (event) => { if (event.target === $("#case-detail-modal")) closeCaseDetail(); });
  $("#case-detail-secondary").addEventListener("click", closeCaseDetail);
  $("#case-detail-use").addEventListener("click", () => {
    const item = featuredCases.find((entry) => entry.id === state.selectedCaseId);
    if (!item) return;
    closeCaseDetail();
    window.location.hash = item.route;
  });
  $("#submit-feedback").addEventListener("click", submitFeedback);
  $("#confirm-feedback").addEventListener("click", confirmFeedback);
  $("#simulation-form").addEventListener("submit", runSimulation);
  $("#region-select").addEventListener("change", (event) => switchRegion(event.target.value));
  $("#agent-chat-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = $("#agent-chat-input");
    const text = input.value;
    input.value = "";
    await sendChatMessage(text);
  });
  $$("[data-chat-prompt]").forEach((button) => button.addEventListener("click", () => sendChatMessage(button.dataset.chatPrompt)));
  ["#simulation-target", "#simulation-days", "#simulation-constraints", "#simulation-request"].forEach((selector) => $(selector).addEventListener("input", () => {
    $("#simulation-understanding").textContent = `待确认输入：${$("#simulation-request").value.trim() || "未提供自然语言描述"}；${$("#simulation-days").value} 天内目标 ${money(Number($("#simulation-target").value || 0) * 10000)}。`;
  }));
  $("#import-kind").addEventListener("change", renderDataCenter);
  $("#import-select-file").addEventListener("click", () => $("#import-file").click());
  $("#import-template").addEventListener("click", () => showToast("已打开数据模板选择；请先选择对应的数据类型"));
  $("#download-all-templates").addEventListener("click", () => showToast("全部数据模板已准备好，可按右侧数据类型逐项下载"));
  $$('[data-template-kind]').forEach((button) => button.addEventListener("click", () => showToast(`${button.dataset.templateKind === "store" ? "门店基础信息" : button.dataset.templateKind} 模板下载功能已就绪`)));
  $("#clear-import-files").addEventListener("click", () => {
    const input = $("#import-file");
    input.value = "";
    $("#import-file-name").textContent = "尚未选择文件";
    $("#selected-file-count").textContent = "0";
    $("#selected-file-list").innerHTML = '<div class="selected-files-empty">选择文件后会显示在这里</div>';
    $("#import-status").textContent = "尚未选择文件";
  });
  $("#import-file").addEventListener("change", (event) => {
    const files = [...(event.target.files || [])];
    $("#import-file-name").textContent = files.length ? `${files.length} 个文件已选择` : "尚未选择文件";
    $("#selected-file-count").textContent = String(files.length);
    $("#selected-file-list").innerHTML = files.map((file) => {
      const extension = file.name.split(".").pop()?.toLowerCase() || "file";
      const icon = extension === "csv" ? "description" : "table_view";
      return `<div class="selected-file-row"><i class="material-symbols-rounded ${extension === "csv" ? "violet" : "green"}">${icon}</i><span><strong>${escapeHtml(file.name)}</strong><small>${(file.size / 1024 / 1024).toFixed(1)} MB</small></span><b><span class="material-symbols-rounded">check_circle</span>上传成功</b><button type="button" aria-label="移除 ${escapeHtml(file.name)}">close</button></div>`;
    }).join("") || '<div class="selected-files-empty">选择文件后会显示在这里</div>';
    $("#import-status").textContent = files.length ? "文件已选择，等待字段校验" : "尚未选择文件";
  });
  $("#selected-file-list").addEventListener("click", (event) => {
    const remove = event.target.closest("button");
    if (!remove) return;
    const row = remove.closest(".selected-file-row");
    const name = row?.querySelector("strong")?.textContent;
    const input = $("#import-file");
    const remaining = [...(input.files || [])].filter((file) => file.name !== name);
    const transfer = new DataTransfer();
    remaining.forEach((file) => transfer.items.add(file));
    input.files = transfer.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
  $("#analysis-search").addEventListener("input", (event) => { state.analysisSearch = event.target.value; renderDataCenter(); });
  $("#analysis-status-filter").addEventListener("change", (event) => { state.analysisStatus = event.target.value; renderDataCenter(); });
  $("#analysis-sort").addEventListener("change", (event) => { state.analysisSort = event.target.value; renderDataCenter(); });
  $("#data-view-files")?.addEventListener("click", () => showToast("本次分析包含库存、销售与采购共 3 份文件"));
  $("#import-history").addEventListener("click", (event) => {
    const fileAction = event.target.closest("[data-history-files]");
    if (fileAction) showToast(`已展开“${fileAction.dataset.historyFiles}”使用的文件`);
  });
  $("#data-import-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const file = $("#import-file").files?.[0];
    if (!file) { $("#import-status").textContent = "请先选择一份 .xlsx、.csv 或 .tsv 文件"; return; }
    $("#import-status").textContent = "正在读取文件并校验字段…";
    try {
      const result = await api("/data-center/imports", { method: "POST", body: JSON.stringify({
        filename: file.name,
        file_base64: await fileAsBase64(file),
        data_kind: $("#import-kind").value,
        sheet_name: $("#import-sheet-name").value.trim() || null,
        mode: "erp_file",
      }) });
      $("#import-status").textContent = result.status === "validated" ? "字段校验通过，已保存导入批次；尚未覆写当前分析快照。" : `校验失败：${(result.errors || []).map((item) => item.message).join("；")}`;
      await refreshCommonRecords();
    } catch (error) { $("#import-status").textContent = `导入失败：${error.message}`; }
  });
}

bindEvents();
window.RetailApp?.init({ state, api, money, escapeHtml, missingLabel, agentRouteForRisk, approveProposal, executeProposal, currentRoute, renderRiskList, loadSelectedDetail, loadWorkbench, refreshCommonRecords });
if (!window.location.hash || !validRoutes.has(window.location.hash.replace("#", ""))) window.location.hash = "overview";
renderRoute();
renderChat();
hydrate();

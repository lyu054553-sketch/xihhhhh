const AREAS = [
  { id: "risk", label: "滞销与临期", title: "库存风险", description: "先分开判断风险，再比较可执行的处理方式。" },
  { id: "transfer", label: "跨店调拨", title: "调拨决策", description: "把候选门店、路线成本和批次去向放在同一张方案里。" },
  { id: "procurement", label: "采购检查", title: "采购前检查", description: "核对采购意向、库存与在途，再确认建议数量。" },
  { id: "promotion", label: "组合促销", title: "促销决策", description: "调整组合、阶段价格和期限后重新比较。" },
  { id: "return", label: "退供处理", title: "退供决策", description: "先确认条款和本次接受条件，再比较结算方式。" },
  { id: "cash", label: "现金模拟", title: "现金影响", description: "沿用同一次方案计算，与不行动基线按相同周期比较。" },
];

const MATERIAL_LABELS = {
  store_id: "门店", sku_id: "商品", product: "商品／规格", quantity: "数量", max_return_qty: "退供上限",
  unit: "单位", unit_cost_cny: "单价", amount_cny: "金额", fee_cny: "费用", fees_cny: "费用",
  expected_arrival_date: "预计到货日期", payment_date: "付款日期", return_deadline: "退供截止日期",
  supplier_id: "供应商", lot_id: "批次", settlement_method: "结算方式",
};

const ACTION_LABELS = { keep: "原店保留", transfer: "跨店调拨", promotion: "组合促销", return: "退供", procurement: "采购建议" };
const AREA_FIELDS = [
  { name: "objective", label: "经营目标", type: "text", required: true, help: "说明希望改善什么，计算仍由方案服务执行。" },
  { name: "horizon_start", label: "比较开始日期", type: "date", required: true },
  { name: "horizon_end", label: "比较截止日期", type: "date", required: true },
];
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;

export function formatRmb(value) {
  if (value === null || value === undefined || value === "") return "—";
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "—";
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "CNY",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

export function validateDecisionInput(schema = [], input = {}) {
  const errors = {};
  for (const field of schema) {
    const raw = input[field.name];
    const empty = raw === null || raw === undefined || String(raw).trim() === "";
    if (field.required && empty) {
      errors[field.name] = `请填写${field.label || field.name}`;
      continue;
    }
    if (empty || field.type !== "number") continue;
    const value = Number(raw);
    if (!Number.isFinite(value)) errors[field.name] = `${field.label || field.name}必须是有效数字`;
    else if (field.min !== undefined && value < Number(field.min)) errors[field.name] = `不能小于 ${field.min}${field.unit ? ` ${field.unit}` : ""}`;
    else if (field.max !== undefined && value > Number(field.max)) errors[field.name] = `不能大于 ${field.max}${field.unit ? ` ${field.unit}` : ""}`;
  }
  return errors;
}

export function canConfirm({ dirty, busy, comparison, selectedStrategy, status }) {
  return Boolean(
    !dirty &&
    !busy &&
    status === "ready" &&
    comparison &&
    comparison.confirmation_allowed === true &&
    Boolean(comparison.comparison_id) &&
    Boolean(selectedStrategy?.id) &&
    selectedStrategy?.feasibility === "feasible" &&
    selectedStrategy?.can_execute === true,
  );
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

function clone(value) {
  if (typeof structuredClone === "function") return structuredClone(value);
  return JSON.parse(JSON.stringify(value));
}

function areaById(id) {
  return AREAS.find((area) => area.id === id) || AREAS[1];
}

function amount(value) {
  return escapeHtml(formatRmb(value));
}

function displayDate(value) {
  if (!value) return "时间未提供";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "short" }).format(parsed);
}

function statusText(status) {
  const labels = {
    feasible: "可比较",
    blocked: "暂不可用",
    needs_confirmation: "需要补充确认",
    risk: "命中风险",
    clear: "未命中",
    unknown: "待补数据",
    loading: "读取中",
    empty: "暂无结果",
    error: "读取失败",
    model_unavailable: "模型暂不可用",
    unavailable: "模型不可用",
    queued: "排队中",
    running: "运行中",
    completed: "已完成",
    failed: "运行失败",
    needs_input: "等待补充",
    waiting_for_input: "等待补充",
    idle: "未启动",
    error: "请求失败",
    version_conflict: "版本已变化",
  };
  return labels[status] || status || "状态未知";
}

function safeList(items) {
  return Array.isArray(items) ? items : [];
}

function normalizeFactContext(context = {}) {
  return {
    tenant_id: context.tenantId ?? null,
    scenario_id: context.scenarioId ?? null,
    branch_id: context.branchId ?? null,
    snapshot_id: context.snapshotId ?? null,
    as_of: context.asOf ?? null,
    data_version: context.dataVersion ?? null,
    fact_version: context.factVersion ?? null,
    is_demo: context.isDemo ?? null,
    source_refs: safeList(context.sourceRefs),
    missing_fields: safeList(context.missingFields),
  };
}

function validateContext(context = {}) {
  const factContext = normalizeFactContext(context);
  const missing = ["tenant_id", "scenario_id", "snapshot_id", "as_of", "data_version", "fact_version", "is_demo"]
    .filter((key) => factContext[key] === null || factContext[key] === "");
  return missing.map((key) => ({
    tenant_id: "tenantId", scenario_id: "scenarioId", snapshot_id: "snapshotId", as_of: "asOf",
    data_version: "dataVersion", fact_version: "factVersion", is_demo: "isDemo",
  })[key]);
}

function contextWithInput(context, input = {}) {
  return {
    ...context,
    storeId: input.store_id ?? context.storeId,
    skuId: input.product_id ?? context.skuId,
    lotId: input.lot_id ?? context.lotId,
  };
}

function selectionScope(context = {}) {
  return {
    tenantId: context.tenantId ?? null,
    scenarioId: context.scenarioId ?? null,
    branchId: context.branchId ?? null,
    snapshotId: context.snapshotId ?? null,
    factVersion: context.factVersion ?? null,
    storeId: context.storeId ?? null,
    skuId: context.skuId ?? null,
    lotId: context.lotId ?? null,
  };
}

function normalizeBusinessInputs(area, input = {}, context = {}) {
  const supplied = input.business_inputs ?? context.businessInputs ?? {};
  if (!supplied || typeof supplied !== "object" || Array.isArray(supplied)) return {};
  const actionTypes = ["transfer", "promotion", "return", "procurement"];
  const hasActionMap = actionTypes.some((key) => Object.prototype.hasOwnProperty.call(supplied, key));
  if (hasActionMap) return clone(supplied);
  return actionTypes.includes(area) ? { [area]: clone(supplied) } : {};
}

function factQueryBody(context, input = {}, area = "transfer") {
  const storeId = input.store_id ?? context.storeId;
  const skuId = input.product_id ?? context.skuId;
  const lotId = input.lot_id ?? context.lotId;
  return {
    context: normalizeFactContext(context),
    store_ids: area === "transfer" ? [] : storeId ? [storeId] : [],
    sku_ids: skuId ? [skuId] : [],
    lot_ids: lotId ? [lotId] : [],
    include: ["inventory", "sales_history", "availability_history", "demand_forecasts", "procurement", "routes", "policies"],
    history_start: context.historyStart ?? null,
    history_end: context.historyEnd ?? null,
  };
}

function uniqueOptions(rows, key, labelKey = null) {
  const seen = new Set();
  return safeList(rows).flatMap((row) => {
    const id = row?.[key];
    if (id == null || seen.has(String(id))) return [];
    seen.add(String(id));
    return [{ id: String(id), label: row?.[labelKey] || String(id) }];
  });
}

export function mapRiskResult(result) {
  if (result === "risk") return "risk";
  if (result === "normal") return "clear";
  return "unknown";
}

export function mapRiskAssessment(assessment, input = {}) {
  const items = safeList(assessment?.items);
  const selectItem = (type) => items.find((item) =>
    item.risk_type === type &&
    (!input.product_id || item.sku_id === input.product_id) &&
    (!input.store_id || item.store_id === input.store_id) &&
    (!input.lot_id || item.lot_id === input.lot_id),
  );
  const mapItem = (item) => item ? {
    status: mapRiskResult(item.result),
    label: item.result === "risk" ? "命中风险规则" : item.result === "normal" ? "未命中风险规则" : "待补数据",
    explanation: safeList(item.evidence_refs).map((ref) => ref.source || ref.record_id).filter(Boolean).join("；") || (item.result === "insufficient_data" ? "缺少完成此项判断所需的事实。" : "风险判断由当前规则服务返回。"),
    inventory_cost: item.amount_cny,
    item,
  } : { status: "unknown", label: "待补数据", explanation: "当前服务没有返回该风险类型的数据。", inventory_cost: null };
  const missing = [...new Set([...safeList(assessment?.missing_fields), ...items.flatMap((item) => safeList(item.missing_fields))])];
  return {
    slow_moving: mapItem(selectItem("slow_moving")),
    near_expiry: mapItem(selectItem("near_expiry")),
    overlap: {
      inventory_cost: assessment?.attention_inventory_cost_cny ?? null,
      description: `按命中库存行并集去重；共 ${safeList(assessment?.counted_inventory_keys).length} 行。`,
    },
    missing_data: missing,
    items,
  };
}

export function mapCandidate(candidate, storeOptions = []) {
  const storeName = (id) => storeOptions.find((store) => String(store.id) === String(id))?.label || id;
  const feasible = candidate.feasible === true && !safeList(candidate.missing_fields).length;
  const feasibility = feasible ? "feasible" : safeList(candidate.missing_fields).length ? "needs_confirmation" : "blocked";
  const plan = candidate.calculation?.execution_plan || {};
  const executableActions = safeList(plan.actions).length;
  return {
    id: candidate.candidate_id,
    candidate_id: candidate.candidate_id,
    action_type: candidate.action_type,
    label: candidate.action_type === "transfer" && candidate.target_store_id
      ? `调拨至${storeName(candidate.target_store_id)}`
      : ACTION_LABELS[candidate.action_type] || candidate.action_type,
    feasibility,
    can_execute: executableActions > 0,
    feasibility_label: feasible ? "可确认候选" : feasibility === "blocked" ? "暂不可用" : "需要补充确认",
    blocking_reasons: safeList(candidate.exclusion_reasons),
    missing_fields: safeList(candidate.missing_fields),
    assumptions: safeList(candidate.assumptions),
    allocated_quantity: candidate.quantity,
    planned_quantity: candidate.calculation?.planned_qty ?? null,
    unit: candidate.base_unit,
    expected_cash_in: candidate.calculation?.expected_cash_in_cny ?? null,
    actual_cash_in: candidate.calculation?.actual_cash_in_cny ?? null,
    execution_cost: candidate.calculation?.execution_cost_cny ?? null,
    gross_profit: candidate.calculation?.gross_profit_cny ?? null,
    expected_sold_quantity: candidate.calculation?.expected_sold_qty ?? null,
    ending_quantity: candidate.calculation?.ending_qty ?? null,
    cash_flow: safeList(candidate.calculation?.cash_flow),
    inventory_changes: safeList(candidate.inventory_changes),
    store_id: candidate.store_id,
    target_store_id: candidate.target_store_id,
    sku_id: candidate.sku_id,
    lot_id: candidate.lot_id,
    execution_plan: plan,
  };
}

export function mapComparison(response, storeOptions = []) {
  const candidates = safeList(response?.candidates).map((item) => mapCandidate(item, storeOptions));
  return {
    comparison_id: response?.comparison_id || null,
    calculation_version: response?.calculation_version || null,
    policy_version: response?.policy_version || null,
    baseline_id: response?.baseline_id || null,
    horizon_start: response?.horizon_start || null,
    horizon_end: response?.horizon_end || null,
    calculation_id: response?.comparison_id || null,
    confirmation_allowed: candidates.some((candidate) => candidate.feasibility === "feasible" && candidate.can_execute),
    selected_strategy_id: response?.selected_candidate_id || null,
    strategies: candidates,
    summary: response?.objective || "方案比较来自当前已知事实和显式假设。",
  };
}

function areaWorkspace(area, facts, riskAssessment, context, input = {}) {
  const inventories = safeList(facts?.inventory);
  const routes = safeList(facts?.routes);
  const products = uniqueOptions(inventories, "sku_id");
  const stores = uniqueOptions([...inventories, ...routes.flatMap((route) => [
    { store_id: route.origin_store_id }, { store_id: route.target_store_id },
  ])], "store_id");
  const lots = uniqueOptions(inventories, "lot_id");
  const riskFindings = mapRiskAssessment(riskAssessment, input);
  const selectedInventory = inventories.find((item) =>
    item.store_id === (input.store_id || context.storeId) &&
    item.sku_id === (input.product_id || context.skuId) &&
    item.lot_id === (input.lot_id || context.lotId) && item.stock_state === "on_hand",
  );
  const route = routes.find((item) => item.origin_store_id === (input.store_id || context.storeId)) || routes[0] || {};
  const destinationInventory = inventories.find((item) => item.store_id === route.target_store_id && item.sku_id === (input.product_id || context.skuId) && item.stock_state === "on_hand") || null;
  const sceneTitle = areaById(area).title;
  const startDate = (context.asOf || "").slice(0, 10);
  const people = uniqueOptions(facts?.reference_data?.tables?.people, "person_id", "display_name");
  const personRows = safeList(facts?.reference_data?.tables?.people);
  const mappedPeople = people.map((person) => ({
    ...person,
    store_id: personRows.find((row) => row.person_id === person.id)?.store_id || null,
    role: personRows.find((row) => row.person_id === person.id)?.role || null,
  }));
  const mappedContextOptions = { products, stores, lots, people: mappedPeople };
  const defaultInput = {
    product_id: input.product_id || context.skuId || products[0]?.id || "",
    store_id: input.store_id || context.storeId || stores[0]?.id || "",
    lot_id: input.lot_id || context.lotId || lots[0]?.id || "",
    risk_type: input.risk_type || "slow_moving",
    group_by: input.group_by || "product",
    objective: input.objective || areaById(area).description,
    horizon_start: input.horizon_start || context.horizonStart || startDate,
    horizon_end: input.horizon_end || context.horizonEnd || "",
  };
  const factsMissing = safeList(facts?.missing_fields);
  const riskMissing = safeList(riskAssessment?.missing_fields);
  const missing = [...new Set([...factsMissing, ...riskMissing])];
  return {
    status: missing.length ? "missing_data" : "ready",
    title: sceneTitle,
    description: areaById(area).description,
    scene_label: context.sceneLabel || `${context.scenarioId || "场景"}${context.branchId ? ` · ${context.branchId}` : ""}`,
    source_label: facts?.context?.is_demo ? "场景样例事实" : "当前业务事实",
    fact_version: facts?.context?.fact_version ?? context.factVersion ?? null,
    as_of_label: facts?.context?.as_of || context.asOf || "时间未提供",
    unit: selectedInventory?.base_unit || "",
    context_options: mappedContextOptions,
    input: defaultInput,
    fields: AREA_FIELDS,
    missing_data: missing,
    risk_findings: riskFindings,
    origin_store: { id: route.origin_store_id || context.storeId, name: stores.find((item) => item.id === route.origin_store_id)?.label || route.origin_store_id || context.storeId },
    candidate_stores: routes.map((item) => ({ id: item.target_store_id, name: stores.find((store) => store.id === item.target_store_id)?.label || item.target_store_id, reason: item.source || "路线事实已接入，供需由比较服务校验。", feasibility: "needs_confirmation", feasibility_label: "待比较" })),
    route: {
      unit: selectedInventory?.base_unit || "",
      source_label: route.source || "路线待服务返回",
      distance_km: route.distance_km ?? null,
      route_fee_cny: route.route_fee_cny ?? route.quoted_amount_cny ?? null,
      origin_stock_before: selectedInventory?.quantity ?? null,
      destination_stock_before: destinationInventory?.quantity ?? null,
      destination_stock_after: null,
      origin_inventory_ref: selectedInventory?.source_ref || null,
    },
    procurement: safeList(facts?.procurement).find((item) => item.sku_id === defaultInput.product_id) || {},
    promotion: safeList(facts?.policies).find((item) => item.promotion || item.stages || item.promotion_stages) || {},
    return_terms: safeList(facts?.policies).find((item) => item.return_terms || item.supplier_terms) || {},
    agent: { status: "idle", events: [], basis: [], missing_fields: [] },
    query_id: facts?.query_id || null,
    risk_keys: riskFindings.items.map((item) => item.risk_key),
    context: facts?.context || normalizeFactContext(context),
  };
}

function createDecisionApiAdapter(client) {
  let latest = { facts: null, risks: null, comparison: null, compareRequest: null, workspace: null, materialDraftId: null };
  const loadWorkspace = async ({ context, area, input = {} }) => {
    const selectedContext = contextWithInput(context, input);
    const missingContext = validateContext(selectedContext);
    if (missingContext.length) {
      const error = new Error(`场景上下文缺少：${missingContext.join("、")}`);
      error.code = "missing_business_data";
      error.detail = { missing_fields: missingContext };
      throw error;
    }
    const query = factQueryBody(selectedContext, input, area);
    const [facts, risks] = await Promise.all([client.queryFacts(query), client.assessRisks(query)]);
    const workspace = areaWorkspace(area, facts, risks, selectedContext, input);
    const sameScope = JSON.stringify(selectionScope(selectedContext)) === JSON.stringify(latest.selectionScope);
    const reuseComparison = area === "cash" && sameScope && Boolean(latest.comparison);
    if (reuseComparison) {
      workspace.comparison = latest.comparison;
      workspace.selected_strategy_id = latest.comparison.selected_strategy_id || null;
    }
    latest = {
      ...latest,
      facts,
      risks,
      workspace,
      comparison: reuseComparison ? latest.comparison : null,
      compareRequest: reuseComparison ? latest.compareRequest : null,
      selectionScope: reuseComparison ? latest.selectionScope : null,
    };
    return workspace;
  };
  return {
    mode: client?.mode || "http",
    fetchDecisionWorkspace: loadWorkspace,
    async calculateDecision({ context, input }) {
      const area = context.area || "transfer";
      const workspace = await loadWorkspace({ context, area, input });
      const selectedContext = contextWithInput(context, input);
      const riskKeys = safeList(latest.risks?.items)
        .filter((item) => (!input.product_id || item.sku_id === input.product_id) && (!input.store_id || item.store_id === input.store_id) && (!input.lot_id || item.lot_id === input.lot_id))
        .map((item) => item.risk_key);
      const compareRequest = {
        context: normalizeFactContext(selectedContext),
        risk_keys: riskKeys,
        objective: input.objective,
        horizon_start: input.horizon_start,
        horizon_end: input.horizon_end,
        assumption_ids: safeList(context.assumptionIds),
        business_inputs: normalizeBusinessInputs(area, input, selectedContext),
      };
      const response = await client.compareProposals(compareRequest);
      const comparison = mapComparison(response, workspace.context_options.stores);
      workspace.comparison = comparison;
      workspace.candidate_stores = safeList(response?.candidates)
        .filter((candidate) => candidate.action_type === "transfer" && candidate.target_store_id)
        .map((candidate) => ({ id: candidate.target_store_id, candidate_id: candidate.candidate_id, target_store_id: candidate.target_store_id, name: workspace.context_options.stores.find((store) => store.id === candidate.target_store_id)?.label || candidate.target_store_id, reason: safeList(candidate.exclusion_reasons).join("；") || "供需、路线与容量由服务校验。", feasibility: candidate.feasible ? "feasible" : "blocked", feasibility_label: candidate.feasible ? "可比较" : "暂不可用" }));
      const samePendingComparison = latest.pendingComparisonId === comparison.comparison_id;
      latest = {
        ...latest,
        comparison,
        compareRequest,
        workspace,
        selectionScope: selectionScope(selectedContext),
        pendingComparisonId: comparison.comparison_id,
        pendingProposalVersion: samePendingComparison ? latest.pendingProposalVersion : null,
        pendingProposalId: samePendingComparison ? latest.pendingProposalId : null,
      };
      return { comparison, workspace, fact_version: factsVersion(workspace), selected_strategy_id: comparison.selected_strategy_id || comparison.strategies.find((item) => item.feasibility === "feasible")?.id || null };
    },
    async confirmAndScheduleExecution({ context, strategy_id, idempotency_key }) {
      if (!latest.comparison || !latest.compareRequest) throw Object.assign(new Error("请先生成方案比较"), { code: "missing_business_data" });
      if (!context.actorId) throw Object.assign(new Error("宿主上下文缺少当前操作者 actorId"), { code: "missing_business_data", detail: { missing_fields: ["actorId"] } });
      if (context.proposalId && context.proposalVersion == null) throw Object.assign(new Error("现有方案上下文缺少 proposalVersion"), { code: "missing_business_data", detail: { missing_fields: ["proposalVersion"] } });
      const saveRequest = {
        ...latest.compareRequest,
        comparison_id: latest.comparison.comparison_id,
        candidate_id: strategy_id,
        expected_current_proposal_version: context.proposalVersion ?? (latest.pendingComparisonId === latest.comparison.comparison_id ? latest.pendingProposalVersion : null) ?? 0,
        actor_id: context.actorId,
      };
      const saved = await client.saveProposal(saveRequest, `${idempotency_key}:save`);
      latest.pendingProposalVersion = saved.proposal_version;
      latest.pendingProposalId = saved.proposal_id;
      const expectedFactVersion = latest.workspace?.fact_version ?? context.factVersion;
      const people = safeList(latest.workspace?.context_options?.people);
      const dueDate = latest.compareRequest?.horizon_end || latest.workspace?.input?.horizon_end || context.horizonEnd;
      if (!dueDate) throw Object.assign(new Error("当前比较缺少执行截止日期，无法安全创建任务"), { code: "missing_business_data" });
      const dueAt = `${dueDate}T18:00:00+08:00`;
      const assignments = safeList(saved.action_lines).map((line) => {
        const preferredStore = line.target_store_id || line.store_id;
        const person = people.find((item) => item.store_id && item.store_id === preferredStore)
          || people.find((item) => line.action_type === "procurement" && item.role === "purchaser")
          || people.find((item) => item.role === "administrator");
        if (!person) throw Object.assign(new Error(`缺少 ${preferredStore || line.action_type} 对应的执行负责人`), { code: "missing_business_data" });
        return { action_line_id: line.action_line_id, assignee_id: person.id, due_at: dueAt };
      });
      if (!assignments.length) throw Object.assign(new Error("此候选没有可执行的动作行，不能创建执行任务"), { code: "infeasible_proposal" });
      const confirmed = await client.confirmProposal(saved.proposal_id, {
        expected_proposal_version: saved.proposal_version,
        expected_fact_version: expectedFactVersion,
        expected_snapshot_id: saved.snapshot_id || context.snapshotId,
        actor_id: context.actorId,
        candidate_id: strategy_id,
        task_assignments: assignments,
      }, `${idempotency_key}:confirm`);
      return { ...confirmed, saved_proposal: saved };
    },
    async extractMaterial({ context, material }) {
      const kind = context.area === "procurement" ? "purchase_intent" : "return_terms";
      const input = {
        context: normalizeFactContext(context),
        actor_id: context.actorId,
        kind,
        text: material.text || undefined,
        source_name: material.filename || "粘贴材料",
        file: material.image || undefined,
      };
      if (!client || typeof client.extractMaterial !== "function") throw Object.assign(new Error("共享 API 客户端缺少 extractMaterial 方法"), { code: "api_not_connected" });
      const request = { ...input };
      if (!material.image) delete request.file;
      const draft = await client.extractMaterial(request, generateIdempotencyKey());
      // The service persists a failed extraction draft too. Keep its ID so a
      // human can review and confirm manually entered fields against the exact
      // uploaded material; never call that manual entry an AI extraction.
      const usableDraftId = draft?.draft_id || null;
      latest.materialDraftId = usableDraftId;
      const fieldValues = Object.fromEntries(Object.entries(draft?.fields || {}).map(([key, field]) => [key, field?.value ?? null]));
      return {
        ...draft,
        source_text: material.text || "",
        extracted_fields: fieldValues,
        field_metadata: draft?.fields || {},
        missing_fields: safeList(draft?.missing_fields),
        unmatched_entities: safeList(draft?.unmatched_entities),
        draft_id: usableDraftId,
        material_id: draft?.material_id || null,
        extraction_source: draft?.source,
        model_status: draft?.status === "failed" ? "model_unavailable" : null,
        message: draft?.status === "failed" ? "材料提取失败；字段仍可手工录入。" : "提取草稿已返回，请核对证据并确认。",
      };
    },
    async confirmMaterial({ context, draft_id, fields, accepted_unresolved_fields, idempotency_key }) {
      const draftId = draft_id || latest.materialDraftId;
      if (!draftId) throw Object.assign(new Error("请先请求材料提取，取得草稿编号后再确认"), { code: "missing_business_data" });
      if (!context.actorId) throw Object.assign(new Error("宿主上下文缺少当前操作者 actorId"), { code: "missing_business_data", detail: { missing_fields: ["actorId"] } });
      const body = {
        expected_fact_version: context.factVersion,
        actor_id: context.actorId,
        fields,
        accepted_unresolved_fields: safeList(accepted_unresolved_fields),
      };
      if (!client || typeof client.confirmMaterial !== "function") throw Object.assign(new Error("共享 API 客户端缺少 confirmMaterial 方法"), { code: "api_not_connected" });
      const result = await client.confirmMaterial(draftId, body, idempotency_key);
      if (result?.context) {
        latest.context = result.context;
      }
      return { ...result, input_patch: null, message: "材料事实已确认；请重新计算方案。" };
    },
    async startAgentRun({ context, goal }) {
      const result = await client.startAgentRun({ context: normalizeFactContext(context), goal, feedback_material_ids: [], actor_id: context.actorId }, generateIdempotencyKey());
      return result;
    },
    getAgentRun({ runId, afterSequence = 0 } = {}) { return client.getAgentRun(runId, afterSequence); },
  };
}

function factsVersion(workspace) {
  return workspace?.context?.fact_version ?? workspace?.fact_version ?? null;
}

function fieldValue(input, field) {
  const value = input?.[field.name];
  return value === null || value === undefined ? "" : value;
}

function renderSelect(name, label, options, selected, extra = "") {
  const items = safeList(options);
  if (!items.length) return "";
  return `<label class="d-control"><span>${escapeHtml(label)}</span><select name="${escapeHtml(name)}" ${extra}>${items.map((item) => {
    const value = typeof item === "string" ? item : item.id ?? item.value;
    const text = typeof item === "string" ? item : item.label ?? item.name ?? value;
    return `<option value="${escapeHtml(value)}"${String(value) === String(selected ?? "") ? " selected" : ""}>${escapeHtml(text)}</option>`;
  }).join("")}</select></label>`;
}

function renderContextFields(workspace, input, disabled = false) {
  const options = workspace.context_options || {};
  const locked = disabled ? "disabled" : "";
  return `<div class="d-context-fields">
    ${renderSelect("product_id", "商品", options.products, input.product_id, locked)}
    ${renderSelect("store_id", "门店", options.stores, input.store_id, locked)}
    ${renderSelect("lot_id", "批次", options.lots, input.lot_id, locked)}
  </div>`;
}

function renderField(field, input, errors = {}, disabled = false) {
  const value = fieldValue(input, field);
  const id = `decision-${String(field.name).replace(/[^a-zA-Z0-9_-]/g, "-")}`;
  const unit = field.unit ? `<span class="d-unit">${escapeHtml(field.unit)}</span>` : "";
  const common = `id="${id}" name="${escapeHtml(field.name)}" ${field.required ? "required" : ""} ${disabled ? "disabled" : ""} ${field.min !== undefined ? `min="${escapeHtml(field.min)}"` : ""} ${field.max !== undefined ? `max="${escapeHtml(field.max)}"` : ""} ${field.step !== undefined ? `step="${escapeHtml(field.step)}"` : ""} aria-invalid="${Boolean(errors[field.name])}"`;
  let control;
  if (field.type === "select") {
    control = `<select ${common}>${safeList(field.options).map((option) => `<option value="${escapeHtml(option.value ?? option.id)}"${String(option.value ?? option.id) === String(value) ? " selected" : ""}>${escapeHtml(option.label ?? option.name ?? option.value ?? option.id)}</option>`).join("")}</select>`;
  } else {
    const type = ["number", "date", "text"].includes(field.type) ? field.type : "text";
    control = `<input ${common} type="${type}" value="${escapeHtml(value)}" inputmode="${type === "number" ? "decimal" : "text"}">`;
  }
  return `<label class="d-control" for="${id}"><span>${escapeHtml(field.label || field.name)}${field.required ? `<b aria-hidden="true">*</b>` : ""}</span><span class="d-input-wrap">${control}${unit}</span>${errors[field.name] ? `<small class="d-field-error">${escapeHtml(errors[field.name])}</small>` : field.help ? `<small>${escapeHtml(field.help)}</small>` : ""}</label>`;
}

function renderRisk(workspace, state) {
  const risk = workspace.risk_findings || {};
  const missing = safeList(risk.missing_data);
  const activeRisk = state.input.risk_type || "slow_moving";
  const groupBy = state.input.group_by || "product";
  const finding = risk[activeRisk] || {};
  const overlap = risk.overlap || {};
  const records = safeList(risk.items).filter((item) => item.risk_type === activeRisk);
  const groupLabels = { product: "商品", store: "门店", lot: "批次" };
  const groupKeys = { product: "sku_id", store: "store_id", lot: "lot_id" };
  const groupKey = groupKeys[groupBy] || "sku_id";
  return `<section class="d-panel d-risk-panel" aria-labelledby="d-risk-heading">
    <div class="d-panel-heading"><div><h3 id="d-risk-heading">两类风险分别判断</h3><p>风险允许重叠；金额按同一库存行去重。</p></div><span class="d-status d-status-${escapeHtml(finding.status || "unknown")}">${escapeHtml(statusText(finding.status || "unknown"))}</span></div>
    <div class="d-switch-row" role="group" aria-label="风险类型">
      <button type="button" class="d-segment${activeRisk === "slow_moving" ? " is-active" : ""}" data-risk-type="slow_moving" aria-pressed="${activeRisk === "slow_moving"}"${state.busy || state.confirmBusy ? " disabled" : ""}>滞销</button>
      <button type="button" class="d-segment${activeRisk === "near_expiry" ? " is-active" : ""}" data-risk-type="near_expiry" aria-pressed="${activeRisk === "near_expiry"}"${state.busy || state.confirmBusy ? " disabled" : ""}>临期</button>
    </div>
    <div class="d-switch-row d-group-row" role="group" aria-label="查看维度">
      <span>按</span>
      ${["product", "store", "lot"].map((key) => `<button type="button" class="d-chip${groupBy === key ? " is-active" : ""}" data-group-by="${key}" aria-pressed="${groupBy === key}"${state.busy || state.confirmBusy ? " disabled" : ""}>${{ product: "商品", store: "门店", lot: "批次" }[key]}</button>`).join("")}
    </div>
    <div class="d-risk-summary"><div><strong>${escapeHtml(finding.label || statusText(finding.status || "unknown"))}</strong><p>${escapeHtml(finding.explanation || "当前服务没有返回风险依据。")}</p></div><div class="d-risk-number"><span>该项库存成本</span><strong>${amount(finding.inventory_cost)}</strong></div></div>
    <div class="d-overlap"><span>风险库存成本（库存行并集去重）</span><strong>${amount(overlap.inventory_cost)}</strong><small>${escapeHtml(overlap.description || "重叠风险金额由服务按同一库存行去重返回。")}</small></div>
    <div class="d-risk-records"><div class="d-subheading"><strong>${escapeHtml(groupLabels[groupBy])}风险明细</strong><span>${records.length} 条服务记录</span></div>${records.length ? `<div class="d-table-wrap"><table><thead><tr><th>${escapeHtml(groupLabels[groupBy])}</th><th>门店</th><th>商品</th><th>批次</th><th>风险结果</th><th>覆盖天数</th><th>库存成本</th></tr></thead><tbody>${records.map((item) => `<tr><th scope="row">${escapeHtml(item[groupKey] || "未知")}</th><td>${escapeHtml(item.store_id || "—")}</td><td>${escapeHtml(item.sku_id || "—")}</td><td>${escapeHtml(item.lot_id || "—")}</td><td><span class="d-status d-status-${item.result === "risk" ? "risk" : item.result === "normal" ? "clear" : "unknown"}">${escapeHtml(item.result === "risk" ? "命中" : item.result === "normal" ? "未命中" : "待补数据")}</span></td><td>${item.coverage_days == null ? "—" : `${escapeHtml(item.coverage_days)} 天`}</td><td>${amount(item.amount_cny)}</td></tr>`).join("")}</tbody></table></div>` : `<p class="d-empty-inline">当前查询没有返回这类风险的明细记录。</p>`}</div>
    <div class="d-missing"><strong>待补数据</strong>${missing.length ? `<ul>${missing.map((item) => `<li>${escapeHtml(typeof item === "string" ? item : item.label || item.field || "缺少一项数据")}</li>`).join("")}</ul>` : `<p>本次判断所需字段齐全。</p>`}</div>
  </section>`;
}

function renderTransfer(workspace, input, comparison, selectedStrategyId, disabled = false) {
  const route = workspace.route || {};
  const candidates = safeList(workspace.candidate_stores);
  const transferCandidates = safeList(comparison?.strategies).filter((item) => item.action_type === "transfer");
  const selectedCandidate = transferCandidates.find((item) => item.id === selectedStrategyId) || null;
  const selectedId = selectedCandidate?.target_store_id || input.target_store_id;
  const destination = candidates.find((store) => String(store.id) === String(selectedId)) || candidates[0] || {};
  const origin = workspace.origin_store || {};
  const inventoryChangeFor = (storeId) => safeList(selectedCandidate?.inventory_changes).find((change) =>
    String(change.store_id) === String(storeId) &&
    String(change.sku_id || selectedCandidate?.sku_id || "") === String(selectedCandidate?.sku_id || "") &&
    String(change.lot_id || selectedCandidate?.lot_id || "") === String(selectedCandidate?.lot_id || ""),
  );
  const originChange = inventoryChangeFor(selectedCandidate?.store_id || origin.id);
  const destinationChange = inventoryChangeFor(selectedCandidate?.target_store_id || destination.id);
  const originBefore = originChange?.quantity_before ?? route.origin_stock_before;
  const destinationBefore = destinationChange?.quantity_before ?? route.destination_stock_before;
  return `<section class="d-panel d-route-panel" aria-labelledby="d-route-heading">
    <div class="d-panel-heading"><div><h3 id="d-route-heading">货物流向</h3><p>路线示意由当前方案数据提供，不代表地图导航。</p></div><span class="d-status d-status-info">${escapeHtml(route.source_label || "路线待核对")}</span></div>
    <div class="d-route-visual"><div class="d-route-stop"><span class="d-stop-dot"></span><small>调出门店</small><strong>${escapeHtml(origin.name || input.store_name || "待选择")}</strong><span>调拨前 ${escapeHtml(originBefore ?? "—")} · 调拨后 ${escapeHtml(originChange?.quantity_after ?? "—")} ${escapeHtml(originChange?.base_unit || route.unit || "件")}</span></div><div class="d-route-line"><span>${escapeHtml(route.distance_km == null ? "路线待核对" : `${route.distance_km} 公里`)}</span><i aria-hidden="true"></i></div><div class="d-route-stop"><span class="d-stop-dot is-destination"></span><small>候选门店</small><strong>${escapeHtml(destination.name || "待选择")}</strong><span>调拨前 ${escapeHtml(destinationBefore ?? "—")} · 调拨后 ${escapeHtml(destinationChange?.quantity_after ?? "—")} ${escapeHtml(destinationChange?.base_unit || route.unit || "件")}</span></div></div>
    <div class="d-route-stats"><div><span>方案数量</span><strong>${selectedCandidate?.planned_quantity == null ? "—" : `${escapeHtml(selectedCandidate.planned_quantity)} ${escapeHtml(selectedCandidate.unit || route.unit || "")}`}</strong></div><div><span>执行费用 / 路线报价</span><strong>${amount(selectedCandidate?.execution_cost ?? route.route_fee_cny)}</strong></div><div><span>该批期末数量</span><strong>${selectedCandidate?.ending_quantity == null ? "—" : `${escapeHtml(selectedCandidate.ending_quantity)} ${escapeHtml(selectedCandidate.unit || route.unit || "")}`}</strong></div></div>
    ${transferCandidates.length ? `<div class="d-candidates"><strong>候选门店</strong><ul>${transferCandidates.map((candidate) => {
      const store = candidates.find((item) => String(item.id) === String(candidate.target_store_id)) || {};
      return `<li><button type="button" data-strategy="${escapeHtml(candidate.id)}" class="d-candidate${candidate.id === selectedStrategyId ? " is-active" : ""}" aria-pressed="${candidate.id === selectedStrategyId}"${disabled || candidate.feasibility !== "feasible" ? " disabled" : ""}><span>${escapeHtml(store.name || candidate.target_store_id || "目标门店未提供")}</span><small>${escapeHtml(candidate.blocking_reasons.join("；") || store.reason || "供需与容量由服务校验。")}</small><b>${escapeHtml(candidate.feasibility_label || statusText(candidate.feasibility))}</b></button></li>`;
    }).join("")}</ul></div>` : candidates.length ? `<div class="d-candidates"><strong>候选路线事实</strong><ul>${candidates.map((store) => `<li><div class="d-candidate d-candidate-readonly"><span>${escapeHtml(store.name || store.id)}</span><small>${escapeHtml(store.reason || "路线事实已返回，等待方案服务评估。")}</small><b>${escapeHtml(store.feasibility_label || "等待比较")}</b></div></li>`).join("")}</ul><p class="d-note">选择路线以方案服务生成的候选为准。</p></div>` : `<div class="d-empty-inline"><strong>暂无候选路线</strong><p>当前事实没有返回可评估的调拨路线。</p></div>`}
  </section>`;
}

function renderProcurement(workspace, input) {
  const comparison = workspace.comparison;
  const intent = workspace.procurement || {};
  const recommendations = safeList(comparison?.strategies).filter((item) => item.action_type === "procurement");
  const unit = intent.base_unit || intent.unit || recommendations.find((item) => item.unit)?.unit || "";
  return `<section class="d-panel d-specific-panel" aria-labelledby="d-specific-heading"><div class="d-panel-heading"><div><h3 id="d-specific-heading">采购意向与方案候选</h3><p>分别展示材料意向与方案服务返回值；不会在前端推导建议差额。</p></div></div><div class="d-intent-grid"><div><span>意向数量</span><strong>${escapeHtml(intent.quantity ?? intent.intention_quantity ?? "—")} ${escapeHtml(unit)}</strong></div><div><span>意向单价</span><strong>${amount(intent.unit_cost_cny ?? intent.unit_price_cny)}${unit ? ` / ${escapeHtml(unit)}` : ""}</strong></div><div><span>期望到货</span><strong>${escapeHtml(intent.expected_arrival_date || "未提供")}</strong></div><div><span>付款日期</span><strong>${escapeHtml(intent.payment_date || "未提供")}</strong></div></div>${recommendations.length ? `<div class="d-service-candidates"><strong>采购建议（来自计算响应）</strong><ul>${recommendations.map((candidate) => `<li><span>${escapeHtml(candidate.feasibility_label || statusText(candidate.feasibility))}</span><strong>${candidate.planned_quantity == null ? "—" : `${escapeHtml(candidate.planned_quantity)} ${escapeHtml(candidate.unit || unit)}`}</strong>${candidate.blocking_reasons.length ? `<small>${escapeHtml(candidate.blocking_reasons.join("；"))}</small>` : ""}</li>`).join("")}</ul></div>` : `<p class="d-empty-inline">本次比较尚未返回采购建议候选。</p>`}${safeList(intent.missing_fields).length ? `<ul class="d-plain-list">${intent.missing_fields.map((item) => `<li>待补：${escapeHtml(item)}</li>`).join("")}</ul>` : ""}</section>`;
}

function renderPromotion(workspace, input) {
  const promotion = workspace.promotion || {};
  const stages = safeList(promotion.stages);
  return `<section class="d-panel d-specific-panel" aria-labelledby="d-specific-heading"><div class="d-panel-heading"><div><h3 id="d-specific-heading">组合与阶段价格</h3><p>组合、价格和期限仅按当前事实／候选响应展示。</p></div></div><div class="d-promo-composition">${safeList(promotion.products).map((item) => `<div><span class="d-product-mark">${escapeHtml((item.name || "商品").slice(0, 1))}</span><strong>${escapeHtml(item.name || item.sku_id || item.product_id || "商品未匹配")}</strong><small>${escapeHtml(item.quantity_per_bundle ?? "—")} ${escapeHtml(item.unit || "件")} / 组</small></div>`).join("") || `<p>当前服务未返回组合商品。</p>`}</div><div class="d-promo-steps">${stages.map((stage) => `<div><span>${escapeHtml(stage.label || "阶段")}</span><strong>${amount(stage.price_cny ?? stage.price)}</strong><small>${escapeHtml(stage.start_date || "起始日待定")} 至 ${escapeHtml(stage.end_date || "期限待定")}</small></div>`).join("") || `<p>阶段价格将在方案数据返回后显示。</p>`}</div><p class="d-note">${escapeHtml(promotion.demand_basis || "销量情景和价格响应来源待服务返回。")}</p></section>`;
}

function renderReturn(workspace, input) {
  const terms = workspace.return_terms || {};
  const settlement = input.settlement_method || terms.settlement_method;
  const method = safeList(terms.settlement_methods).find((item) => String(item.value ?? item.id) === String(settlement));
  return `<section class="d-panel d-specific-panel" aria-labelledby="d-specific-heading"><div class="d-panel-heading"><div><h3 id="d-specific-heading">退供条款与结算</h3><p>合同条款与本次供应商接受状态分开呈现。</p></div><span class="d-status d-status-${escapeHtml(terms.acceptance_status || "unknown")}">${escapeHtml(terms.acceptance_label || statusText(terms.acceptance_status || "unknown"))}</span></div><div class="d-terms-grid"><div><span>可退条件</span><strong>${escapeHtml(terms.conditions || "尚无已确认条款")}</strong></div><div><span>截止日期</span><strong>${escapeHtml(terms.deadline || "未提供")}</strong></div><div><span>费用或扣款</span><strong>${amount(terms.fee_cny ?? terms.fee_amount)}</strong></div><div><span>本次供应商回复</span><strong>${escapeHtml(terms.acceptance_status === "accepted" ? "已确认接受" : terms.acceptance_status === "rejected" ? "不接受" : "尚未确认")}</strong></div></div>${method ? `<p class="d-note"><strong>${escapeHtml(method.label || method.value)}：</strong>${escapeHtml(method.description || "结算方式详情待确认。")}</p>` : ""}</section>`;
}

function renderCash(workspace, comparison, selected) {
  if (!comparison) return `<section class="d-panel d-cash-panel"><h3>现金影响</h3><p>完成一次比较后，这里会用同一计算编号对照方案与基线。</p></section>`;
  const baseline = safeList(comparison.strategies).find((item) => item.action_type === "keep") || null;
  const source = workspace.source_label || "当前计算结果";
  return `<section class="d-panel d-cash-panel" aria-labelledby="d-cash-heading"><div class="d-panel-heading"><div><h3 id="d-cash-heading">同周期现金对照</h3><p>同一次计算里对照不行动与选中候选，预计流入与已知实收分开。</p></div><span class="d-calculation-ref">${escapeHtml(comparison.comparison_id || "比较编号待返回")}</span></div><div class="d-cash-grid"><div><span>不行动基线 · 预计流入</span><strong>${amount(baseline?.expected_cash_in)}</strong><small>已知实收 ${amount(baseline?.actual_cash_in)} · 执行费用 ${amount(baseline?.execution_cost)}</small></div><div><span>${escapeHtml(selected?.label || "已选方案")} · 预计流入</span><strong>${amount(selected?.expected_cash_in)}</strong><small>已知实收 ${amount(selected?.actual_cash_in)} · 执行费用 ${amount(selected?.execution_cost)}</small></div></div><p class="d-note">比较编号：${escapeHtml(comparison.comparison_id || "—")} · 基线编号：${escapeHtml(comparison.baseline_id || "未提供")} · 金额来源：${escapeHtml(source)}。预计现金不表示已到账；服务未提供的现金流出或净额保持未知。</p></section>`;
}

function renderMaterial(state) {
  const material = state.material;
  const preview = material.fileUrl
    ? `<img src="${escapeHtml(material.fileUrl)}" alt="${escapeHtml(material.fileName || "上传截图")}" class="d-source-image">`
    : `<pre>${escapeHtml(material.sourceText || material.rawText || "选择样例或粘贴文字后，原始内容会显示在这里。")}</pre>`;
  const missing = materialMissingKeys(material);
  const accepted = new Set(material.acceptedUnresolved || []);
  const keys = [...new Set([...Object.keys(material.fieldMetadata || {}), ...Object.keys(material.fields || {}), ...missing])];
  const locked = state.busy || state.confirmBusy || material.busy || state.apiMode === "fixture";
  const canSubmit = Boolean(material.draftId) && !safeList(material.unmatchedEntities).length && missing.every((key) => accepted.has(key));
  return `<section class="d-panel d-material-panel" aria-labelledby="d-material-heading"><div class="d-panel-heading"><div><h3 id="d-material-heading">材料提取与人工确认</h3><p>文字或单张清晰 PNG／JPG；原文、证据与字段并排核对。</p></div><span class="d-status d-status-${escapeHtml(material.status)}">${escapeHtml(materialStatusLabel(material.status))}</span></div>
    <div class="d-material-input"><label class="d-control"><span>粘贴采购意向或供应商材料</span><textarea name="material_raw_text" rows="4" placeholder="粘贴原始文字；提取前不会写入业务事实。"${locked ? " disabled" : ""}>${escapeHtml(material.rawText)}</textarea></label><div class="d-material-actions"><button type="button" class="d-button d-button-secondary" data-load-material-sample${locked ? " disabled" : ""}>载入文字样例</button><label class="d-file-label">上传单张截图<input type="file" data-material-file accept="image/png,image/jpeg" aria-label="上传一张 PNG 或 JPG 截图"${locked ? " disabled" : ""}></label><span>PNG／JPG · 单张 · 最大 5 MB · 不支持 PDF</span></div></div>
    ${material.error ? `<div class="d-alert d-alert-warning" role="alert">${escapeHtml(material.error)}</div>` : ""}
    <div class="d-material-grid"><div class="d-source-column"><strong>原始材料</strong><div class="d-source-preview">${preview}</div>${material.fileName ? `<small>${escapeHtml(material.fileName)}</small>` : ""}<button type="button" class="d-button d-button-secondary" data-extract-material${locked || (!material.rawText.trim() && !material.file) ? " disabled" : ""}>${material.busy ? "正在请求提取" : "提取字段"}</button>${material.draftId ? `<small>草稿 ${escapeHtml(material.draftId)} · 材料 ${escapeHtml(material.materialId || "编号待返回")}</small>` : ""}</div><div class="d-fields-column"><strong>提取字段 · 可修改</strong>${keys.length ? `<div class="d-extracted-fields">${keys.map((key) => {
      const metadata = material.fieldMetadata?.[key] || {};
      const value = material.fields?.[key] ?? "";
      const label = MATERIAL_LABELS[key] || key;
      const type = materialFieldType(key, value, metadata.unit);
      const id = `material-${String(key).replace(/[^a-zA-Z0-9_-]/g, "-")}`;
      const isMissing = missing.includes(key);
      const unit = metadata.unit || "";
      const displayUnit = unit === "CNY" || unit === "CNY/元" ? "元" : unit.startsWith("CNY/") ? `元/${unit.slice(4)}` : unit === "date" ? "" : unit;
      return `<div class="d-material-field"><label class="d-control" for="${id}"><span>${escapeHtml(label)}${isMissing ? `<b aria-hidden="true"> · 待核对</b>` : ""}</span><span class="d-input-wrap"><input id="${id}" name="material_${escapeHtml(key)}" type="${type}" value="${escapeHtml(value)}" aria-invalid="${isMissing}" autocomplete="off"${locked ? " disabled" : ""}>${displayUnit ? `<span class="d-unit">${escapeHtml(displayUnit)}</span>` : ""}</span></label>${metadata.evidence_text ? `<small class="d-field-evidence">原文依据：${escapeHtml(metadata.evidence_text)}${metadata.page ? ` · 第 ${escapeHtml(metadata.page)} 页` : ""}</small>` : isMissing ? `<small class="d-field-error">服务标记为缺项，未知值保留为空。</small>` : ""}${metadata.review_status ? `<small class="d-review-status">${escapeHtml(materialReviewLabel(metadata.review_status))}${metadata.confidence == null ? "" : ` · 置信度 ${escapeHtml(metadata.confidence)}`}</small>` : ""}${isMissing ? `<label class="d-unresolved-control"><input type="checkbox" data-accept-unresolved="${escapeHtml(key)}"${accepted.has(key) ? " checked" : ""}${locked ? " disabled" : ""}>接受保留此未知字段</label>` : ""}</div>`;
    }).join("")}</div>` : `<p class="d-empty-inline">提取草稿返回后，字段和原文证据会显示在这里。</p>`}${missing.length ? `<p class="d-missing-inline">待补：${missing.map((key) => escapeHtml(MATERIAL_LABELS[key] || key)).join("、")}</p>` : `<p class="d-ready-inline">没有服务标记的缺项。</p>`}${safeList(material.unmatchedEntities).length ? `<div class="d-unmatched"><strong>未匹配实体</strong><ul>${material.unmatchedEntities.map((item) => `<li>${escapeHtml(item.name || item.value || item.text || "实体")}${safeList(item.candidates).length ? ` · 候选：${escapeHtml(item.candidates.map((candidate) => candidate.label || candidate.id || candidate).join("、"))}` : ""}</li>`).join("")}</ul></div>` : ""}<button type="button" class="d-button d-button-primary" data-confirm-material${!canSubmit || locked ? " disabled" : ""}>确认材料字段</button>${!material.draftId && (material.status === "model_unavailable" || material.status === "error") ? `<small class="d-field-error">未取得可确认的服务草稿；手工填写不会直接写入事实。</small>` : ""}</div></div>
  </section>`;
}

function materialFieldType(key, value, unit) {
  if (unit === "date" || /(_date|deadline)$/.test(key)) return "date";
  if (typeof value === "number" || /^(quantity|max_return_qty|unit_cost_cny|amount_cny|fee_cny|fees_cny)$/.test(key)) return "number";
  return "text";
}

function materialMissingKeys(material) {
  const missing = new Set();
  for (const item of safeList(material.missingFields)) {
    const key = typeof item === "string" ? item : item.field || item.key;
    const value = material.fields?.[key];
    if (key && (value === null || value === undefined || String(value).trim() === "")) missing.add(key);
  }
  return [...missing];
}

function validateMaterialFields(fields = {}) {
  const errors = {};
  for (const [key, value] of Object.entries(fields)) {
    if (!/^(quantity|max_return_qty|unit_cost_cny|amount_cny|fee_cny|fees_cny)$/.test(key)) continue;
    if (value === null || value === undefined || String(value).trim() === "") continue;
    if (!Number.isFinite(Number(value))) errors[key] = `${MATERIAL_LABELS[key] || key}必须是有效数字`;
    else if (Number(value) < 0) errors[key] = `${MATERIAL_LABELS[key] || key}不能小于 0`;
  }
  return errors;
}

function materialReviewLabel(status) {
  return ({ needs_review: "待人工核对", missing: "缺项", unmatched: "未匹配", confirmed: "已确认" })[status] || status;
}
function materialStatusLabel(status) {
  return ({ idle: "待输入", extracting: "请求中", extracted: "待人工确认", edited: "字段已修改", confirmed: "已确认", model_unavailable: "模型不可用", error: "提取失败" })[status] || "待输入";
}

function mapAgentRun(run) {
  const statusMap = {
    queued: "queued", running: "running", completed: "completed", failed: "failed",
    unavailable: "model_unavailable", needs_input: "waiting_for_input",
  };
  const eventLabels = {
    run_started: "Agent 运行已开始", tool_started: "调用业务工具", tool_succeeded: "工具返回结果",
    tool_failed: "工具调用失败", needs_input: "等待补充信息", run_completed: "运行完成",
    run_failed: "运行失败", run_unavailable: "模型不可用",
  };
  const events = safeList(run?.events).map((event) => ({
    id: event.event_id,
    type: event.event_type,
    status: event.event_type === "tool_failed" || event.event_type === "run_failed" || event.event_type === "run_unavailable" ? "error" : "complete",
    label: event.tool_name ? `${eventLabels[event.event_type] || event.event_type} · ${event.tool_name}` : eventLabels[event.event_type] || event.event_type,
    message: event.error?.message || (event.input_summary ? JSON.stringify(event.input_summary) : event.result_ref ? `服务结果引用：${event.result_ref}` : "服务记录了此阶段。"),
    source: event.tool_name || "Agent 服务",
    occurred_at: event.occurred_at,
    result_ref: event.result_ref,
    sequence: event.sequence,
  }));
  return {
    run_id: run?.run_id || null,
    status: statusMap[run?.status] || "failed",
    message: run?.summary || safeList(run?.events).find((event) => event.error?.message)?.error?.message || "",
    events,
    missing_fields: safeList(run?.missing_fields),
    basis: [run?.proposal_comparison_id, run?.context?.snapshot_id, run?.context?.fact_version].filter((item) => item != null).map((item) => `服务引用 ${item}`),
    last_sequence: events.reduce((max, event) => Math.max(max, event.sequence || 0), 0),
  };
}

function renderAgent(agent = {}, { busy = false, disabled = false } = {}) {
  const events = safeList(agent.events);
  const status = agent.status || "idle";
  const descriptions = {
    model_unavailable: "模型服务不可用，本次未生成新的模型分析。原始输入仍保留，可继续手工录入或运行规则计算。",
    unavailable: agent.message || "本次运行返回模型不可用状态。",
    failed: agent.message || "本次运行失败；保留已保存输入和旧结果。",
    waiting_for_input: agent.message || "正在等待你补充所需信息。",
    needs_input: agent.message || "Agent 已返回待补字段，请先补齐业务事实。",
    completed: agent.message || "本次运行已完成；以下仅列出服务返回的实际业务事件。",
    queued: agent.message || "运行已排队，等待服务返回事件。",
    running: events.length ? "以下是服务返回的查询和工具事件。" : "服务尚未返回运行事件；收到事件前不显示推测进度。",
    idle: "尚无运行事件。运行 Agent 需由你明确触发。",
    error: agent.message || "读取运行事件失败；可以稍后重试。",
  };
  const description = agent.read_error
    ? `${descriptions[status] || statusText(status)} ${agent.read_error}`
    : descriptions[status] || (events.length ? "以下是服务返回的查询和工具事件。" : "尚无运行事件。运行 Agent 需由你明确触发。");
  const details = (value) => typeof value === "string" ? value : value == null ? "" : JSON.stringify(value);
  const active = ["queued", "running"].includes(status);
  return `<section class="d-panel d-agent-panel" aria-labelledby="d-agent-heading"><div class="d-panel-heading"><div><h3 id="d-agent-heading">Agent 过程</h3><p>只展示服务记录的业务事件，不展示隐藏推理。</p></div><span class="d-status d-status-${escapeHtml(status)}">${escapeHtml(statusText(status))}</span></div><p class="d-agent-summary">${escapeHtml(description)}</p><button type="button" class="d-button d-button-secondary" data-agent-run${disabled || busy || active ? " disabled" : ""}>${busy ? "正在请求运行" : active ? "等待真实运行事件" : "运行 Agent 核查"}</button>${events.length ? `<ol class="d-event-list">${events.map((event) => `<li class="d-event d-event-${escapeHtml(event.status || "complete")}"><span class="d-event-mark" aria-hidden="true"></span><div><strong>${escapeHtml(event.label || event.type || "业务事件")}</strong><p>${escapeHtml(event.message || details(event.input_summary) || "服务未提供事件说明。")}</p><small>${escapeHtml(event.source || "来源未提供")}${event.occurred_at ? ` · ${escapeHtml(displayDate(event.occurred_at))}` : ""}${event.result_ref ? ` · 结果 ${escapeHtml(event.result_ref)}` : ""}</small></div></li>`).join("")}</ol>` : ""}${safeList(agent.missing_fields).length ? `<div class="d-agent-missing"><strong>等待补充</strong><ul>${agent.missing_fields.map((item) => `<li>${escapeHtml(item.label || item)}</li>`).join("")}</ul></div>` : ""}${safeList(agent.basis).length ? `<details class="d-basis"><summary>方案依据</summary><ul>${agent.basis.map((item) => `<li>${escapeHtml(item.label || item)}</li>`).join("")}</ul></details>` : ""}</section>`;
}

function renderComparison(workspace, state) {
  const comparison = state.comparison;
  if (!comparison) return `<section class="d-panel d-comparison-panel"><div class="d-panel-heading"><div><h3>方案比较</h3><p>结果由统一计算服务返回，输入变化后需要重新计算。</p></div></div><div class="d-empty-inline"><strong>还没有计算结果</strong><p>补齐输入后运行一次比较，系统会并列展示可用方案及原因。</p></div></section>`;
  const selected = safeList(comparison.strategies).find((item) => item.id === state.selectedStrategyId) || safeList(comparison.strategies).find((item) => item.feasibility === "feasible");
  const stale = state.dirty;
  return `<section class="d-panel d-comparison-panel" aria-labelledby="d-comparison-heading"><div class="d-panel-heading"><div><h3 id="d-comparison-heading">方案比较</h3><p>同一快照、事实版本、周期与基线；金额按人民币元显示。</p></div><span class="d-status ${stale ? "d-status-stale" : "d-status-feasible"}">${stale ? "输入已改 · 结果已过期" : `比较 ${escapeHtml(comparison.comparison_id || "—")} · ${escapeHtml(comparison.calculation_version || "版本待返回")}`}</span></div>${comparison.summary ? `<p class="d-comparison-summary">${escapeHtml(comparison.summary)}</p>` : ""}<div class="d-comparison-meta">政策版本 ${escapeHtml(comparison.policy_version || "—")} · 基线 ${escapeHtml(comparison.baseline_id || "未提供")} · 周期 ${escapeHtml(comparison.horizon_start || "—")} 至 ${escapeHtml(comparison.horizon_end || "—")}</div><div class="d-strategy-grid">${safeList(comparison.strategies).map((strategy) => {
    const isSelected = strategy.id === (selected?.id || state.selectedStrategyId);
    const feasible = strategy.feasibility === "feasible";
    const unit = strategy.unit || workspace.unit || "";
    const flows = safeList(strategy.cash_flow);
    return `<article class="d-strategy${isSelected ? " is-selected" : ""}${!feasible ? " is-blocked" : ""}"><div class="d-strategy-top"><button type="button" class="d-strategy-pick" data-strategy="${escapeHtml(strategy.id)}" aria-pressed="${isSelected}"${!feasible || stale ? " disabled" : ""}><span class="d-radio-mark" aria-hidden="true"></span><strong>${escapeHtml(strategy.label || strategy.id)}</strong></button><span class="d-status d-status-${escapeHtml(strategy.feasibility)}">${escapeHtml(strategy.feasibility_label || statusText(strategy.feasibility))}</span></div><div class="d-strategy-metrics"><div><span>计划数量</span><strong>${strategy.planned_quantity == null ? "—" : `${escapeHtml(strategy.planned_quantity)} ${escapeHtml(unit)}`}</strong></div><div><span>预计现金流入</span><strong>${amount(strategy.expected_cash_in)}</strong></div><div><span>已知实际流入</span><strong>${amount(strategy.actual_cash_in)}</strong></div><div><span>执行费用</span><strong>${amount(strategy.execution_cost)}</strong></div><div><span>预计毛利</span><strong>${amount(strategy.gross_profit)}</strong></div><div><span>预计售出 / 期末库存</span><strong>${strategy.expected_sold_quantity == null ? "—" : `${escapeHtml(strategy.expected_sold_quantity)} ${escapeHtml(unit)}`} / ${strategy.ending_quantity == null ? "—" : `${escapeHtml(strategy.ending_quantity)} ${escapeHtml(unit)}`}</strong></div></div>${flows.length ? `<details class="d-cash-flows"><summary>现金流时点与来源</summary><ul>${flows.map((flow) => `<li><span>${escapeHtml(flow.direction === "in" ? "流入" : flow.direction === "out" ? "流出" : flow.direction || "现金流")}</span> ${amount(flow.amount_cny)} · ${escapeHtml(flow.status || "状态未知")} · ${escapeHtml(flow.expected_at || "时点未提供")} · ${escapeHtml(flow.source_ref || "来源未提供")}</li>`).join("")}</ul></details>` : ""}${safeList(strategy.blocking_reasons).length ? `<div class="d-reason-list"><strong>不可用原因</strong><ul>${strategy.blocking_reasons.map((reason) => `<li>${escapeHtml(reason)}</li>`).join("")}</ul></div>` : ""}${safeList(strategy.missing_fields).length ? `<div class="d-reason-list"><strong>待补字段</strong><ul>${strategy.missing_fields.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>` : ""}${safeList(strategy.assumptions).length ? `<details class="d-assumptions"><summary>查看假设与依据</summary><ul>${strategy.assumptions.map((item) => `<li>${escapeHtml(item.label || item)}</li>`).join("")}</ul></details>` : ""}</article>`;
  }).join("") || `<div class="d-empty-inline"><strong>没有可比较的方案</strong><p>请补齐缺失数据，或调整当前约束。</p></div>`}</div></section>${renderCash(workspace, comparison, selected)}`;
}

function renderBody(state) {
  const workspace = state.workspace;
  const area = areaById(state.area);
  if (state.status === "loading") return `<div class="d-state-panel" role="status"><span class="d-loader" aria-hidden="true"></span><strong>正在读取当前场景</strong><p>等待业务服务返回数据。</p></div>`;
  if ((state.status === "error" || state.status === "version_conflict" || state.status === "model_unavailable") && !state.workspace) {
    return `<div class="d-state-panel d-state-error" role="alert"><strong>${escapeHtml(state.error?.title || statusText(state.status))}</strong><p>${escapeHtml(state.error?.message || "业务接口暂时无法读取，请检查服务状态。")}</p><button type="button" class="d-button d-button-secondary" data-reload>重新读取</button></div>`;
  }
  if (state.status === "missing_data" && !state.workspace) {
    const fields = safeList(state.error?.missing_fields || state.error?.detail?.missing_fields);
    return `<div class="d-state-panel d-state-warning" role="status"><strong>${escapeHtml(state.error?.title || "缺少当前场景上下文")}</strong><p>${escapeHtml(state.error?.message || "请让宿主提供完成事实查询所需的场景版本字段。")}</p>${fields.length ? `<ul>${fields.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}<button type="button" class="d-button d-button-secondary" data-reload>重新读取</button></div>`;
  }
  if (state.status === "empty" && !state.workspace) return `<div class="d-state-panel"><strong>当前场景没有可展示的事项</strong><p>选择商品、门店或场景后，重新读取业务数据。</p></div>`;
  if (!workspace) return `<div class="d-state-panel d-state-error" role="alert"><strong>业务接口未接通</strong><p>正式组件需要注入决策服务 API。预览页面使用独立的显式 fixture。</p></div>`;

  const fields = safeList(workspace.fields);
  const fieldErrors = validateDecisionInput(fields, state.input);
  const selected = safeList(state.comparison?.strategies).find((item) => item.id === state.selectedStrategyId) || safeList(state.comparison?.strategies).find((item) => item.feasibility === "feasible");
  const agent = workspace.agent || {};
  const calculationBlocked = Object.keys(fieldErrors).length > 0;
  const operationLocked = state.busy || state.material.busy || state.confirmBusy || state.status === "confirmed";
  return `<div class="d-workbench-heading"><div><p class="d-context-kicker">${escapeHtml(workspace.scene_label || state.context.scene_label || "当前业务场景")}</p><h2>${escapeHtml(workspace.title || area.title)}</h2><p>${escapeHtml(workspace.description || area.description)}</p></div><div class="d-fact-version"><span>事实版本</span><strong>${escapeHtml(workspace.fact_version ?? "待服务返回")}</strong><small>${escapeHtml(workspace.as_of_label || "时点未提供")}</small></div></div>
    ${state.status === "missing_data" || safeList(workspace.missing_data).length ? `<div class="d-alert d-alert-warning" role="status"><strong>部分结果需要补数据</strong><span>${safeList(workspace.missing_data).map((item) => escapeHtml(item.label || item)).join("；") || "缺项已单独列出，未知值不会按 0 处理。"}</span></div>` : ""}
    ${state.error ? `<div class="d-alert d-alert-error" role="alert"><strong>${escapeHtml(state.error.title)}</strong><span>${escapeHtml(state.error.message)}</span></div>` : ""}
    ${renderContextFields(workspace, state.input, operationLocked)}
    ${state.area === "risk" ? renderRisk(workspace, state) : ""}
    ${state.area === "transfer" ? renderTransfer(workspace, state.input, state.comparison, state.selectedStrategyId, operationLocked) : ""}
    ${state.area === "procurement" ? renderProcurement(workspace, state.input) : ""}
    ${state.area === "promotion" ? renderPromotion(workspace, state.input) : ""}
    ${state.area === "return" ? renderReturn(workspace, state.input) : ""}
    <section class="d-panel d-input-panel" aria-labelledby="d-input-heading"><div class="d-panel-heading"><div><h3 id="d-input-heading">决策参数</h3><p>改动任何参数都会使当前计算失效。</p></div><span class="d-required-note">* 必填</span></div><form data-decision-form novalidate><div class="d-input-grid">${fields.map((field) => renderField(field, state.input, fieldErrors, operationLocked)).join("") || `<p class="d-empty-inline">当前服务未返回可编辑参数。</p>`}</div><div class="d-form-footer"><p class="d-validation-note" role="status">${calculationBlocked ? `请修正 ${Object.keys(fieldErrors).length} 项输入后再计算。` : state.dirty ? "输入已修改，确认旧方案已锁定。" : "计算结果与输入版本一致。"}</p><button type="submit" class="d-button d-button-primary" data-calculate${state.busy || state.material.busy || state.confirmBusy || calculationBlocked ? " disabled" : ""}>${state.busy ? "正在计算" : state.dirty ? "重新计算" : "计算方案"}</button></div></form></section>
    ${state.area === "procurement" || state.area === "return" ? renderMaterial(state) : ""}
    ${renderComparison(workspace, state)}
    ${renderAgent(agent, { busy: state.agentBusy, disabled: operationLocked || !state.workspace || state.apiMode === "fixture" })}
    <p class="d-source-footnote">库存、数量和金额均来自当前服务响应。未知值显示为 —；预计回款不表示已经到账。</p>`;
}

function renderStrategyReason(strategy) {
  if (!strategy) return "先选择一个可用方案。";
  if (strategy.feasibility !== "feasible") return safeList(strategy.blocking_reasons).join("；") || "该方案需要补充确认。";
  if (strategy.blocking_reasons?.length) return strategy.blocking_reasons.join("；");
  return "方案版本与当前输入一致，可安排执行。";
}

function renderRail(state) {
  const comparison = state.comparison;
  const selected = safeList(comparison?.strategies).find((item) => item.id === state.selectedStrategyId) || safeList(comparison?.strategies).find((item) => item.feasibility === "feasible");
  const enabled = state.apiMode !== "fixture" && canConfirm({ dirty: state.dirty, busy: state.busy || state.confirmBusy, comparison, selectedStrategy: selected, status: state.status });
  const reason = state.status === "confirmed"
    ? "已完成一次确认，执行跟进已创建。"
    : state.apiMode === "fixture" ? "开发预览为只读，确认操作不会调用真实服务。"
      : state.error?.message || (state.dirty ? "输入已改动，请重算后再确认。" : comparison ? renderStrategyReason(selected) : "需要先获得一份可确认的最新计算结果。");
  const railNote = state.apiMode === "fixture" ? "本页仅展示 fixture；确认和执行操作已禁用。" : "确认后直接创建执行跟进；不会要求管理员再次审批。";
  return `<aside class="d-rail" aria-label="确认与导航"><button type="button" class="d-return-link" data-return>返回决策入口</button><div class="d-rail-paper"><div class="d-rail-top"><span class="d-rail-symbol" aria-hidden="true">↗</span><div><small>当前选择</small><strong>${escapeHtml(selected?.label || "尚未选方案")}</strong></div></div><div class="d-rail-amount"><span>预计现金流入</span><strong>${amount(selected?.expected_cash_in)}</strong><small>已知实际流入 ${amount(selected?.actual_cash_in)}</small></div><div class="d-rail-version"><span>比较编号</span><strong>${escapeHtml(comparison?.comparison_id || "未生成")}</strong></div><p class="d-confirm-reason" role="status">${escapeHtml(reason)}</p><button type="button" class="d-button d-button-primary d-confirm-button" data-confirm-decision${enabled ? "" : " disabled"}>${state.confirmBusy ? "正在保存确认" : state.status === "confirmed" ? "已确认并安排执行" : "确认方案并安排执行"}</button><small class="d-rail-note">${escapeHtml(railNote)}</small></div><div class="d-rail-boundary"><strong>决策边界</strong><p>批准只安排执行。签收、销售与现金到账仍需各自的回执和回放事实。</p></div></aside>`;
}

function renderShell(state) {
  const area = areaById(state.area);
  const preview = state.apiMode === "fixture" ? `<aside class="d-preview-note" role="note"><strong>开发预览 · 本地 fixture</strong><span>查询和比较结果不是服务端响应，不代表真实接口成功；不会调用真实 API／模型，确认、材料写入和 Agent 操作已禁用。</span></aside>` : "";
  const demo = state.context.isDemo === true ? "演示场景" : state.context.isDemo === false ? "正式场景" : "场景状态未知";
  return `${preview}<div class="d-topbar"><div class="d-brand-lockup"><span class="d-brand-mark" aria-hidden="true"><i></i><i></i><i></i></span><span><strong>货不压钱</strong><small>库存资金决策台</small></span></div><div class="d-topbar-status"><span class="d-health-dot ${state.status === "error" || state.status === "version_conflict" ? "is-error" : ""}" aria-hidden="true"></span>${escapeHtml(state.context.organization_label || "业务决策场景")} · ${escapeHtml(demo)}</div></div><div class="d-heading-row"><div><p class="d-eyebrow">库存处理工作区</p><h1>让库存重新流动</h1><p>看清事实、比较办法，再确认下一步。</p></div><div class="d-heading-index"><span>当前工作区</span><strong>${escapeHtml(area.label)}</strong></div></div><nav class="d-workspaces" role="tablist" aria-label="业务决策工作区">${AREAS.map((item) => `<button type="button" role="tab" aria-selected="${item.id === state.area}" class="d-workspace-tab${item.id === state.area ? " is-active" : ""}" data-area="${item.id}">${escapeHtml(item.label)}</button>`).join("")}</nav><main class="d-layout"><div class="d-main-column">${renderBody(state)}</div>${renderRail(state)}</main>`;
}

function makeError(error) {
  const code = error?.code || error?.detail?.code || error?.response?.code || "service_error";
  const message = error?.message || error?.detail?.message || "业务服务暂时无法完成请求。";
  const detail = error?.detail || error?.payload?.detail || null;
  const extras = { code, detail, missing_fields: safeList(detail?.missing_fields) };
  if (code === "version_conflict" || code === "facts_changed" || code === "stale_snapshot") return { status: "version_conflict", title: "数据版本已变化", message: "当前数据或方案版本已更新。请重新读取最新事实并重新计算后再确认。", ...extras };
  if (code === "model_unavailable" || code === "provider_unavailable") return { status: "model_unavailable", title: "模型服务暂不可用", message: "本次没有生成新的模型结果。原始输入已保留，可手工录入字段或使用可用的规则计算。", ...extras };
  if (code === "missing_business_data" || code === "missing_data") return { status: "missing_data", title: "缺少业务数据", message, ...extras };
  if (code === "no_feasible_plan") return { status: "empty", title: "没有可确认的方案", message, ...extras };
  return { status: "error", title: "业务接口请求失败", message, ...extras };
}

function emptyMaterial() {
  return { rawText: "", sourceText: "", file: null, fileName: "", fileUrl: "", status: "idle", fields: {}, fieldMetadata: {}, missingFields: [], unmatchedEntities: [], acceptedUnresolved: [], draftId: null, materialId: null, extractionSource: null, error: "", busy: false, confirmed: false };
}

function generateIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `decision-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function setControlError(control, message) {
  if (!control) return;
  control.setAttribute("aria-invalid", "true");
  control.focus();
  const note = control.form?.querySelector(".d-validation-note");
  if (note) note.textContent = message;
}

export function mountDecisionWorkbench({ root, api, navigation, context = {} } = {}) {
  const hostElement = typeof root === "string" ? document.querySelector(root) : root;
  if (!hostElement || typeof hostElement.append !== "function") throw new TypeError("mountDecisionWorkbench requires a host container");
  const rootElement = hostElement.ownerDocument.createElement("div");
  rootElement.className = "d-root";
  rootElement.setAttribute("data-decision-root", "");
  hostElement.append(rootElement);
  const eventController = new AbortController();
  let destroyed = false;
  const requestIds = { workspace: 0, decision: 0, material: 0 };
  const requestControllers = { workspace: null, decision: null, material: null };
  let agentPollTimer = null;
  let agentPollRunId = null;
  const state = {
    area: context.area || context.module || "transfer",
    context: { ...context },
    apiMode: api?.mode || "http",
    workspace: null,
    input: {},
    comparison: null,
    selectedStrategyId: null,
    factVersion: null,
    status: "loading",
    busy: false,
    confirmBusy: false,
    dirty: false,
    error: null,
    material: emptyMaterial(),
    agentBusy: false,
  };

  const navigate = (route, nextContext) => {
    if (typeof navigation === "function") navigation(route, nextContext);
    else if (typeof navigation?.navigate === "function") navigation.navigate(route, nextContext);
  };

  const emit = (name, detail = {}) => {
    const EventClass = rootElement.ownerDocument.defaultView?.CustomEvent || globalThis.CustomEvent;
    if (typeof EventClass !== "function") return;
    rootElement.dispatchEvent(new EventClass(name, {
      bubbles: true,
      detail: { context: { ...state.context }, ...detail },
    }));
  };

  const paint = () => {
    if (!destroyed) rootElement.innerHTML = renderShell(state);
  };

  const updateDirtyPresentation = () => {
    if (destroyed) return;
    const note = rootElement.querySelector(".d-validation-note");
    if (note) note.textContent = state.dirty ? "输入已修改，旧结果已锁定；重算后才能确认。" : "计算结果与输入版本一致。";
    const resultStatus = rootElement.querySelector(".d-comparison-panel .d-panel-heading .d-status");
    if (resultStatus && state.dirty) {
      resultStatus.className = "d-status d-status-stale";
      resultStatus.textContent = "输入已改 · 结果已过期";
    }
    const confirm = rootElement.querySelector("[data-confirm-decision]");
    const selected = safeList(state.comparison?.strategies).find((item) => item.id === state.selectedStrategyId) || safeList(state.comparison?.strategies).find((item) => item.feasibility === "feasible");
    const allowed = state.apiMode !== "fixture" && canConfirm({ dirty: state.dirty, busy: state.busy || state.confirmBusy, comparison: state.comparison, selectedStrategy: selected, status: state.status });
    if (confirm) confirm.disabled = !allowed || state.confirmBusy;
    rootElement.querySelectorAll("[data-strategy]").forEach((button) => { button.disabled = button.disabled || state.dirty || state.busy || state.confirmBusy; });
    const calculateButton = rootElement.querySelector("[data-calculate]");
    if (calculateButton) calculateButton.textContent = state.dirty ? "重新计算" : "计算方案";
    const reason = rootElement.querySelector(".d-confirm-reason");
    if (reason && state.dirty) reason.textContent = "输入已改动，请重算后再确认。";
  };

  const callApi = async (name, payload, signal) => {
    if (typeof api?.[name] !== "function") {
      const error = new Error(`缺少注入的 API 方法：${name}`);
      error.code = "api_not_connected";
      throw error;
    }
    return api[name](payload, { signal });
  };

  const publishAgentRun = (run, appendEvents = false) => {
    const incoming = mapAgentRun(run);
    const previous = state.workspace?.agent || {};
    const events = appendEvents
      ? [...new Map([...safeList(previous.events), ...incoming.events].map((item) => [item.sequence ?? item.id, item])).values()].sort((a, b) => (a.sequence || 0) - (b.sequence || 0))
      : incoming.events;
    state.workspace.agent = { ...previous, ...incoming, events, read_error: null };
    emit("hackathon:run-updated", {
      runId: incoming.run_id,
      status: run?.status,
      lastSequence: Math.max(previous.last_sequence || 0, incoming.last_sequence || 0),
    });
    paint();
    return state.workspace.agent;
  };

  const pollAgentRun = async (runId, afterSequence) => {
    if (destroyed || !runId || agentPollRunId !== runId) return;
    try {
      const run = await callApi("getAgentRun", { runId, afterSequence });
      if (destroyed || agentPollRunId !== runId) return;
      const agent = publishAgentRun(run, true);
      if (["queued", "running"].includes(run?.status)) {
        agentPollTimer = setTimeout(() => pollAgentRun(runId, agent.last_sequence || afterSequence), 1500);
      } else {
        agentPollTimer = null;
        agentPollRunId = null;
      }
    } catch (error) {
      if (destroyed || agentPollRunId !== runId || error?.name === "AbortError") return;
      const mapped = makeError(error);
      state.workspace.agent = { ...state.workspace.agent, read_error: mapped.message };
      emit("hackathon:error", { code: mapped.code, message: mapped.message, retryable: [0, 429].includes(error?.status) || error?.status >= 500 });
      paint();
      agentPollTimer = setTimeout(() => pollAgentRun(runId, state.workspace.agent?.last_sequence || afterSequence), 3000);
    }
  };

  const startAgentRun = async () => {
    if (state.apiMode === "fixture") return;
    if (!state.workspace || state.agentBusy || state.busy || state.confirmBusy) return;
    if (agentPollTimer) clearTimeout(agentPollTimer);
    agentPollTimer = null;
    agentPollRunId = null;
    state.agentBusy = true;
    state.error = null;
    paint();
    const objective = state.input.objective || areaById(state.area).description;
    const start = state.input.horizon_start || "";
    const end = state.input.horizon_end || "";
    const goal = `${areaById(state.area).title}：${objective}${start || end ? `；比较周期 ${start || "—"} 至 ${end || "—"}` : ""}`;
    try {
      const run = await callApi("startAgentRun", { context: { ...state.context, area: state.area }, goal });
      if (destroyed) return;
      state.agentBusy = false;
      const agent = publishAgentRun(run);
      if (agent.run_id && ["queued", "running"].includes(run?.status)) {
        agentPollRunId = agent.run_id;
        agentPollTimer = setTimeout(() => pollAgentRun(agent.run_id, agent.last_sequence || 0), 1200);
      }
    } catch (error) {
      if (destroyed) return;
      const mapped = makeError(error);
      state.agentBusy = false;
      const status = mapped.status === "model_unavailable" ? "model_unavailable" : "error";
      state.workspace.agent = { ...(state.workspace.agent || {}), status, message: mapped.message };
      emit("hackathon:error", { code: mapped.code, message: mapped.message, retryable: [0, 429].includes(error?.status) || error?.status >= 500 });
      paint();
    }
  };

  const load = async () => {
    if (agentPollTimer) clearTimeout(agentPollTimer);
    agentPollTimer = null;
    agentPollRunId = null;
    requestControllers.workspace?.abort();
    requestControllers.decision?.abort();
    requestIds.decision += 1;
    requestControllers.material?.abort();
    requestIds.material += 1;
    requestControllers.workspace = new AbortController();
    const currentRequest = ++requestIds.workspace;
    state.status = "loading";
    state.error = null;
    state.workspace = null;
    state.comparison = null;
    state.dirty = false;
    state.busy = false;
    state.material.busy = false;
    if (state.material.fileUrl) URL.revokeObjectURL(state.material.fileUrl);
    state.material = emptyMaterial();
    state.agentBusy = false;
    paint();
    try {
      const workspace = await callApi("fetchDecisionWorkspace", {
        context: { ...state.context, area: state.area },
        area: state.area,
      }, requestControllers.workspace.signal);
      if (destroyed || currentRequest !== requestIds.workspace) return;
      if (!workspace || workspace.status === "empty" || workspace.status === "no_result") {
        state.status = "empty";
        state.workspace = workspace || null;
        paint();
        return;
      }
      state.workspace = workspace;
      state.input = clone(workspace.input || {});
      state.comparison = workspace.comparison || null;
      state.factVersion = workspace.fact_version ?? null;
      state.selectedStrategyId = workspace.selected_strategy_id || workspace.comparison?.selected_strategy_id || safeList(workspace.comparison?.strategies).find((item) => item.feasibility === "feasible")?.id || null;
      state.status = workspace.status === "missing_data" ? "missing_data" : "ready";
      if (workspace.model_status === "model_unavailable") state.workspace.agent = { ...(workspace.agent || {}), status: "model_unavailable" };
      paint();
    } catch (error) {
      if (destroyed || currentRequest !== requestIds.workspace || error?.name === "AbortError") return;
      state.error = makeError(error);
      state.status = state.error.status;
      emit("hackathon:error", { code: state.error.code, message: state.error.message, retryable: [0, 429].includes(error?.status) || error?.status >= 500 });
      paint();
    }
  };

  const calculate = async (form) => {
    const fields = safeList(state.workspace?.fields);
    const errors = validateDecisionInput(fields, state.input);
    if (Object.keys(errors).length) {
      const first = form?.querySelector(`[name="${CSS.escape(Object.keys(errors)[0])}"]`);
      setControlError(first, Object.values(errors)[0]);
      return;
    }
    requestControllers.decision?.abort();
    requestControllers.decision = new AbortController();
    const currentRequest = ++requestIds.decision;
    state.busy = true;
    state.error = null;
    state.dirty = true;
    paint();
    try {
      const response = await callApi("calculateDecision", {
        context: { ...state.context, area: state.area },
        input: clone(state.input),
        expected_fact_version: state.factVersion,
      }, requestControllers.decision.signal);
      if (destroyed || currentRequest !== requestIds.decision) return;
      state.comparison = response?.comparison || response || null;
      state.workspace = { ...state.workspace, ...(response?.workspace || {}) };
      if (response?.agent) state.workspace.agent = response.agent;
      state.factVersion = response?.fact_version ?? state.factVersion;
      state.selectedStrategyId = response?.selected_strategy_id || state.comparison?.selected_strategy_id || safeList(state.comparison?.strategies).find((item) => item.feasibility === "feasible")?.id || null;
      state.status = response?.status === "missing_data" ? "missing_data" : state.comparison ? "ready" : "empty";
      state.dirty = false;
      state.busy = false;
      paint();
    } catch (error) {
      if (destroyed || currentRequest !== requestIds.decision || error?.name === "AbortError") return;
      const mapped = makeError(error);
      state.error = mapped;
      state.status = mapped.status;
      state.busy = false;
      state.dirty = true;
      emit("hackathon:error", { code: mapped.code, message: mapped.message, retryable: [0, 429].includes(error?.status) || error?.status >= 500 });
      paint();
    }
  };

  const extractMaterial = async () => {
    if (state.apiMode === "fixture") return;
    if (!state.material.rawText.trim() && !state.material.file) {
      state.material.error = "请先粘贴文字或选择一张 PNG／JPG 截图。";
      paint();
      return;
    }
    requestControllers.material?.abort();
    requestControllers.material = new AbortController();
    const currentRequest = ++requestIds.material;
    state.material.busy = true;
    state.material.error = "";
    state.material.status = "extracting";
    paint();
    try {
      const result = await callApi("extractMaterial", {
        context: { ...state.context, area: state.area },
        material: { text: state.material.rawText, image: state.material.file, filename: state.material.fileName },
      }, requestControllers.material.signal);
      if (destroyed || currentRequest !== requestIds.material) return;
      state.material.fields = { ...result.extracted_fields };
      state.material.fieldMetadata = { ...result.field_metadata };
      state.material.sourceText = result.source_text || state.material.rawText;
      state.material.status = result.model_status === "model_unavailable" ? "model_unavailable" : "extracted";
      state.material.extractionSource = result.extraction_source || null;
      state.material.draftId = result.draft_id || null;
      state.material.materialId = result.material_id || null;
      state.material.missingFields = safeList(result.missing_fields);
      state.material.unmatchedEntities = safeList(result.unmatched_entities);
      state.material.acceptedUnresolved = [];
      state.material.busy = false;
      state.material.error = result.message || "";
      if (result.model_status === "model_unavailable") state.material.error = result.message || "模型服务不可用；可以手工填写字段，但本次不会标记为 AI 已提取。";
      paint();
    } catch (error) {
      if (destroyed || currentRequest !== requestIds.material || error?.name === "AbortError") return;
      const mapped = makeError(error);
      state.material.status = mapped.status === "model_unavailable" ? "model_unavailable" : "error";
      state.material.error = mapped.message;
      state.material.busy = false;
      emit("hackathon:error", { code: mapped.code, message: mapped.message, retryable: [0, 429].includes(error?.status) || error?.status >= 500 });
      paint();
    }
  };

  const confirmMaterial = async () => {
    if (state.apiMode === "fixture") return;
    const missing = materialMissingKeys(state.material);
    const errors = validateMaterialFields(state.material.fields);
    const accepted = new Set(state.material.acceptedUnresolved || []);
    const unresolved = missing.filter((key) => !accepted.has(key));
    if (!state.material.draftId || unresolved.length || safeList(state.material.unmatchedEntities).length || Object.keys(errors).length) {
      state.material.error = !state.material.draftId
        ? "需要先取得服务草稿，才能确认材料事实。"
        : safeList(state.material.unmatchedEntities).length ? "请先人工匹配未匹配的门店、商品或供应商。"
        : unresolved.length ? `请补齐或明确接受保留：${unresolved.map((key) => MATERIAL_LABELS[key] || key).join("、")}`
          : Object.values(errors)[0];
      paint();
      return;
    }
    requestControllers.material?.abort();
    requestControllers.material = new AbortController();
    const currentRequest = ++requestIds.material;
    state.material.busy = true;
    state.material.error = "";
    paint();
    try {
      const fields = Object.fromEntries(Object.entries(state.material.fields).map(([key, value]) => [
        key,
        value === "" ? null : /^(quantity|max_return_qty|unit_cost_cny|amount_cny|fee_cny|fees_cny)$/.test(key) ? Number(value) : value,
      ]));
      for (const key of missing) if (!(key in fields)) fields[key] = null;
      const result = await callApi("confirmMaterial", {
        context: { ...state.context, area: state.area },
        draft_id: state.material.draftId,
        fields,
        accepted_unresolved_fields: missing.filter((key) => accepted.has(key)),
        idempotency_key: generateIdempotencyKey(),
      }, requestControllers.material.signal);
      if (destroyed || currentRequest !== requestIds.material) return;
      state.material.status = "confirmed";
      state.material.busy = false;
      state.material.error = result?.message || "字段已确认。旧计算已失效，请重新计算。";
      state.material.confirmed = true;
      state.dirty = true;
      const updatedFactVersion = result?.context?.fact_version ?? result?.fact_version;
      if (updatedFactVersion != null) {
        state.context.factVersion = updatedFactVersion;
        state.factVersion = updatedFactVersion;
        emit("hackathon:context-change", { patch: {
          factVersion: updatedFactVersion,
          ...(result?.context?.snapshot_id ? { snapshotId: result.context.snapshot_id } : {}),
          ...(result?.context?.as_of ? { asOf: result.context.as_of } : {}),
          ...(result?.context?.data_version ? { dataVersion: result.context.data_version } : {}),
          ...(result?.context?.source_refs ? { sourceRefs: result.context.source_refs } : {}),
          ...(result?.context?.missing_fields ? { missingFields: result.context.missing_fields } : {}),
        } });
      }
      paint();
    } catch (error) {
      if (destroyed || currentRequest !== requestIds.material || error?.name === "AbortError") return;
      const mapped = makeError(error);
      state.material.status = "error";
      state.material.busy = false;
      state.material.error = mapped.message;
      emit("hackathon:error", { code: mapped.code, message: mapped.message, retryable: [0, 429].includes(error?.status) || error?.status >= 500 });
      paint();
    }
  };

  const confirmDecision = async () => {
    if (state.apiMode === "fixture") return;
    const selected = safeList(state.comparison?.strategies).find((item) => item.id === state.selectedStrategyId) || safeList(state.comparison?.strategies).find((item) => item.feasibility === "feasible");
    if (!canConfirm({ dirty: state.dirty, busy: state.busy || state.confirmBusy, comparison: state.comparison, selectedStrategy: selected, status: state.status })) return;
    state.confirmBusy = true;
    state.error = null;
    paint();
    try {
      const result = await callApi("confirmAndScheduleExecution", {
        context: { ...state.context, area: state.area },
        strategy_id: selected.id,
        idempotency_key: generateIdempotencyKey(),
      });
      if (destroyed) return;
      state.confirmBusy = false;
      const saved = result?.saved_proposal || {};
      const proposalId = result?.proposal_id || saved.proposal_id || state.context.proposalId || null;
      const proposalVersion = result?.proposal_version ?? saved.proposal_version ?? null;
      const taskIds = safeList(result?.task_ids || result?.tasks).map((item) => typeof item === "string" ? item : item.task_id).filter(Boolean);
      const followupContext = { ...state.context, proposalId, proposalVersion, approvalId: result?.approval_id || null, taskIds };
      if (result?.context) {
        followupContext.snapshotId = result.context.snapshot_id ?? followupContext.snapshotId;
        followupContext.asOf = result.context.as_of ?? followupContext.asOf;
        followupContext.dataVersion = result.context.data_version ?? followupContext.dataVersion;
        followupContext.factVersion = result.context.fact_version ?? followupContext.factVersion;
        followupContext.isDemo = result.context.is_demo ?? followupContext.isDemo;
        followupContext.sourceRefs = result.context.source_refs ?? followupContext.sourceRefs;
        followupContext.missingFields = result.context.missing_fields ?? followupContext.missingFields;
      }
      state.context = followupContext;
      state.status = "confirmed";
      emit("hackathon:context-change", { patch: followupContext });
      emit("hackathon:proposal-confirmed", {
        context: followupContext,
        approvalId: result?.approval_id || null,
        proposalId,
        proposalVersion,
        taskIds,
      });
      paint();
      try {
        navigate("execution-followup", followupContext);
      } catch (navigationError) {
        emit("hackathon:error", { code: "navigation_failed", message: navigationError?.message || "执行跟进导航失败。", retryable: false });
      }
    } catch (error) {
      if (destroyed) return;
      const mapped = makeError(error);
      state.error = mapped;
      state.status = mapped.status;
      state.confirmBusy = false;
      emit("hackathon:error", { code: mapped.code, message: mapped.message, retryable: [0, 429].includes(error?.status) || error?.status >= 500 });
      paint();
    }
  };

  const markDirty = () => {
    if (!state.workspace) return;
    state.dirty = true;
    updateDirtyPresentation();
  };

  const updateSelectorContext = (name, value) => {
    const keys = { product_id: "skuId", store_id: "storeId", lot_id: "lotId" };
    const key = keys[name];
    if (!key || state.context[key] === value) return;
    state.context[key] = value;
    emit("hackathon:context-change", { patch: { [key]: value } });
  };

  const onInput = (event) => {
    const control = event.target;
    if (state.busy || state.confirmBusy || state.material.busy || state.status === "confirmed") return;
    if (control.name === "material_raw_text") {
      state.material.rawText = control.value;
      state.material.fields = {};
      state.material.fieldMetadata = {};
      state.material.missingFields = [];
      state.material.unmatchedEntities = [];
      state.material.acceptedUnresolved = [];
      state.material.draftId = null;
      state.material.materialId = null;
      state.material.extractionSource = null;
      state.material.sourceText = "";
      state.material.status = "idle";
      state.material.confirmed = false;
      state.material.error = "";
      const submit = rootElement.querySelector("[data-confirm-material]");
      if (submit) submit.disabled = true;
      const fieldList = rootElement.querySelector(".d-extracted-fields");
      if (fieldList) fieldList.innerHTML = `<p class="d-empty-inline">原文已修改，请重新提取字段。</p>`;
      const missingHint = rootElement.querySelector(".d-missing-inline");
      if (missingHint) missingHint.textContent = "原文已修改，请重新提取字段。";
      const metadataPanel = rootElement.querySelector(".d-unmatched");
      if (metadataPanel) metadataPanel.remove();
      if (!state.material.file) {
        const rawPreview = rootElement.querySelector(".d-source-preview pre");
        if (rawPreview) rawPreview.textContent = control.value || "选择样例或粘贴文字后，原始内容会显示在这里。";
      }
      const status = rootElement.querySelector(".d-material-panel .d-panel-heading .d-status");
      if (status) {
        status.className = "d-status d-status-idle";
        status.textContent = materialStatusLabel("idle");
      }
      return;
    }
    if (control.name?.startsWith("material_")) {
      const key = control.name.slice("material_".length);
      state.material.fields[key] = control.value;
      if (String(control.value).trim() !== "") {
        state.material.missingFields = safeList(state.material.missingFields).filter((item) => (typeof item === "string" ? item : item.field || item.key) !== key);
        state.material.acceptedUnresolved = safeList(state.material.acceptedUnresolved).filter((item) => item !== key);
        state.material.unmatchedEntities = safeList(state.material.unmatchedEntities).filter((item) => (item.field || item.key) !== key);
        if (state.material.fieldMetadata?.[key]?.review_status === "unmatched") {
          state.material.fieldMetadata[key] = { ...state.material.fieldMetadata[key], review_status: "needs_review" };
        }
      }
      state.material.status = state.material.draftId ? "edited" : state.material.status;
      state.material.confirmed = false;
      state.material.error = "";
      const missing = materialMissingKeys(state.material);
      const accepted = new Set(state.material.acceptedUnresolved || []);
      const submit = rootElement.querySelector("[data-confirm-material]");
      if (submit) submit.disabled = !state.material.draftId || missing.some((keyName) => !accepted.has(keyName)) || state.material.busy;
      const hint = rootElement.querySelector(".d-missing-inline");
      if (hint) hint.textContent = missing.length ? `待补：${missing.map((keyName) => MATERIAL_LABELS[keyName] || keyName).join("、")}` : "没有服务标记的缺项。";
      return;
    }
    if (control.name) {
      state.input[control.name] = control.value;
      updateSelectorContext(control.name, control.value);
      markDirty();
    }
  };

  const onChange = (event) => {
    const control = event.target;
    if (state.busy || state.confirmBusy || state.material.busy || state.status === "confirmed") return;
    if (control.matches("[data-accept-unresolved]")) {
      const key = control.dataset.acceptUnresolved;
      const accepted = new Set(state.material.acceptedUnresolved || []);
      if (control.checked) accepted.add(key);
      else accepted.delete(key);
      state.material.acceptedUnresolved = [...accepted];
      const missing = materialMissingKeys(state.material);
      const submit = rootElement.querySelector("[data-confirm-material]");
      if (submit) submit.disabled = !state.material.draftId || missing.some((field) => !accepted.has(field)) || state.material.busy;
      paint();
      return;
    }
    if (control.matches("[data-material-file]")) {
      const file = control.files?.[0] || null;
      state.material.error = "";
      if (file && !["image/png", "image/jpeg"].includes(file.type)) {
        state.material.error = "请选择 PNG 或 JPG 图片。其他文件类型不支持提取。";
        control.value = "";
        paint();
        return;
      }
      if (file && file.size > MAX_IMAGE_BYTES) {
        state.material.error = "截图超过 5 MB，请压缩后重新选择。";
        control.value = "";
        paint();
        return;
      }
      if (state.material.fileUrl) URL.revokeObjectURL(state.material.fileUrl);
      state.material.file = file;
      state.material.fileName = file?.name || "";
      state.material.fileUrl = file ? URL.createObjectURL(file) : "";
      state.material.sourceText = "";
      state.material.fields = {};
      state.material.fieldMetadata = {};
      state.material.missingFields = [];
      state.material.unmatchedEntities = [];
      state.material.acceptedUnresolved = [];
      state.material.draftId = null;
      state.material.materialId = null;
      state.material.extractionSource = null;
      state.material.status = "idle";
      paint();
      return;
    }
    if (control.name?.startsWith("material_")) {
      onInput(event);
      paint();
      return;
    }
    if (control.name) {
      state.input[control.name] = control.value;
      updateSelectorContext(control.name, control.value);
      if (control.name === "risk_type" || control.name === "group_by") state.area = "risk";
      markDirty();
    }
  };

  const onClick = async (event) => {
    const button = event.target.closest("button");
    if (!button || !rootElement.contains(button)) return;
    if (state.busy || state.confirmBusy || state.material.busy) return;
    if (button.dataset.area) {
      state.area = button.dataset.area;
      await load();
    } else if (button.dataset.riskType) {
      state.input.risk_type = button.dataset.riskType;
      paint();
    } else if (button.dataset.groupBy) {
      state.input.group_by = button.dataset.groupBy;
      paint();
    } else if (button.dataset.strategy) {
      if (state.dirty) return;
      const strategy = safeList(state.comparison?.strategies).find((item) => item.id === button.dataset.strategy);
      if (!strategy || strategy.feasibility !== "feasible") return;
      state.selectedStrategyId = strategy.id;
      paint();
    } else if (button.hasAttribute("data-calculate")) {
      event.preventDefault();
      await calculate(rootElement.querySelector("[data-decision-form]"));
    } else if (button.hasAttribute("data-extract-material")) {
      await extractMaterial();
    } else if (button.hasAttribute("data-confirm-material")) {
      await confirmMaterial();
    } else if (button.hasAttribute("data-confirm-decision")) {
      await confirmDecision();
    } else if (button.hasAttribute("data-agent-run")) {
      await startAgentRun();
    } else if (button.hasAttribute("data-load-material-sample")) {
      state.material.rawText = state.area === "procurement"
        ? "采购意向：每日坚果礼盒 100 盒，单价 40 元，希望 2026-10-10 到货。"
        : "供应商退供沟通：果汁饮料 100 桶，单价 10 元，申请于 2026-10-18 前退货，预计退款 900 元。";
      state.material.file = null;
      state.material.fileName = "";
      state.material.sourceText = "";
      state.material.status = "idle";
      state.material.fields = {};
      state.material.fieldMetadata = {};
      state.material.missingFields = [];
      state.material.unmatchedEntities = [];
      state.material.acceptedUnresolved = [];
      state.material.draftId = null;
      state.material.materialId = null;
      state.material.extractionSource = null;
      state.material.confirmed = false;
      state.material.error = "";
      if (state.material.fileUrl) URL.revokeObjectURL(state.material.fileUrl);
      state.material.fileUrl = "";
      paint();
    } else if (button.hasAttribute("data-return")) {
      navigate("decision-entry", { ...state.context });
    } else if (button.hasAttribute("data-reload")) {
      await load();
    }
  };

  const onSubmit = async (event) => {
    if (!event.target.matches("[data-decision-form]")) return;
    event.preventDefault();
    await calculate(event.target);
  };

  rootElement.addEventListener("click", onClick, { signal: eventController.signal });
  rootElement.addEventListener("input", onInput, { signal: eventController.signal });
  rootElement.addEventListener("change", onChange, { signal: eventController.signal });
  rootElement.addEventListener("submit", onSubmit, { signal: eventController.signal });
  paint();
  load();

  return {
    updateContext(nextContext = {}) {
      state.context = { ...state.context, ...nextContext };
      if (nextContext.area || nextContext.module) state.area = nextContext.area || nextContext.module;
      load();
    },
    destroy() {
      if (destroyed) return;
      destroyed = true;
      requestIds.workspace += 1;
      requestIds.decision += 1;
      requestIds.material += 1;
      if (agentPollTimer) clearTimeout(agentPollTimer);
      agentPollTimer = null;
      agentPollRunId = null;
      for (const controller of Object.values(requestControllers)) controller?.abort();
      eventController.abort();
      if (state.material.fileUrl) URL.revokeObjectURL(state.material.fileUrl);
      rootElement.remove();
    },
  };
}

export function mount(container, options = {}) {
  if (!options.api) throw new TypeError("HackathonDecision.mount requires an injected API client");
  const mounted = mountDecisionWorkbench({
    root: container,
    api: createDecisionApiAdapter(options.api),
    navigation: options.navigate,
    context: options.context || {},
  });
  return { destroy: mounted.destroy, updateContext: mounted.updateContext };
}

if (typeof window !== "undefined") {
  window.HackathonDecision = Object.freeze({ mount });
}

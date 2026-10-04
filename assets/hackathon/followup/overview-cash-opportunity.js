(function installCashOpportunity(global, factory) {
  "use strict";
  const component = factory(global);
  if (typeof module === "object" && module.exports) module.exports = component;
  if (global) global.HackathonCashOpportunity = component;
})(typeof globalThis !== "undefined" ? globalThis : this, function createCashOpportunity(global) {
  "use strict";

  const FOLLOWUP_ROUTE = "execution-followup";
  const CLOSED_STATUSES = new Set(["cancelled", "archived"]);

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[char]);
  }

  function finiteMoney(value) {
    return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
  }

  function firstMoney(...values) {
    for (const value of values) {
      const parsed = finiteMoney(value);
      if (parsed !== null) return parsed;
    }
    return null;
  }

  function cents(value) {
    return Math.round((value + Number.EPSILON) * 100) / 100;
  }

  function moneyText(value) {
    if (value === null) return "未知";
    return `¥${new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value)}`;
  }

  function largeAmount(value) {
    if (value === null) return { value: "—", unit: "" };
    if (value >= 10000) {
      const amount = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(value / 10000);
      return { value: amount, unit: "万元" };
    }
    return { value: new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(value), unit: "元" };
  }

  function array(value) { return Array.isArray(value) ? value : []; }
  function object(value) { return value && typeof value === "object" && !Array.isArray(value) ? value : {}; }
  function accountingOf(task) { return object(task.accounting || task.result?.accounting); }
  function expectedIn(task) {
    const accounting = accountingOf(task);
    return firstMoney(accounting.expected_cash_cny, accounting.expected_cash_in_cny,
      task.expected_cash_in_cny, task.candidate_calculation?.expected_cash_in_cny,
      task.calculation?.expected_cash_in_cny);
  }
  function actualIn(task) {
    const accounting = accountingOf(task);
    return firstMoney(accounting.actual_cash_cny, accounting.actual_cash_in_cny,
      task.actual_cash_in_cny, task.result?.actual_cash_in_cny);
  }
  function expectedInForProposal(proposal) {
    return firstMoney(proposal.calculation?.expected_cash_in_cny,
      proposal.candidate_calculation?.expected_cash_in_cny,
      proposal.expected_cash_in_cny);
  }
  function shiftDay(day, offset) {
    const date = new Date(`${day}T00:00:00Z`);
    if (!Number.isFinite(date.getTime())) return null;
    date.setUTCDate(date.getUTCDate() + offset);
    return date.toISOString().slice(0, 10);
  }
  function remainingWeek(asOf) {
    const day = typeof asOf === "string" ? asOf.slice(0, 10) : "";
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || !Number.isFinite(Date.parse(`${day}T00:00:00Z`))) return null;
    const weekday = new Date(`${day}T00:00:00Z`).getUTCDay();
    const mondayOffset = (weekday + 6) % 7;
    const daysUntilMonday = weekday === 0 ? 1 : 8 - weekday;
    return { start: day, end: shiftDay(day, daysUntilMonday), monday: shiftDay(day, -mondayOffset) };
  }
  function weeklyCashIn(task, week) {
    if (!week) return null;
    const calculation = object(task.candidate_calculation || task.calculation || task.proposal?.calculation);
    const flows = Array.isArray(calculation.cash_flow) ? calculation.cash_flow : null;
    if (flows === null) return null;
    const inflows = flows.filter((flow) => ["in", "inflow", "cash_in", "incoming", "receipt"].includes(String(flow.direction || "").toLowerCase()));
    if (!inflows.length) return flows.length > 0 || expectedIn(task) === 0 ? 0 : null;
    let total = 0;
    for (const flow of inflows) {
      const amount = finiteMoney(flow.amount_cny ?? flow.amount);
      const expectedAt = typeof flow.expected_at === "string" ? flow.expected_at.slice(0, 10) : "";
      if (amount === null || !/^\d{4}-\d{2}-\d{2}$/.test(expectedAt)) return null;
      if (expectedAt >= week.start && expectedAt < week.end) total += amount;
    }
    return cents(total);
  }
  function taskTitle(task) {
    return task.title || task.proposal?.title || task.plan?.title || task.action_label || "待跟进事项";
  }
  function proposalTitle(proposal) { return proposal.title || proposal.action_type || "待确认方案"; }
  function timeValue(item) {
    const candidates = [item.updated_at, item.completed_at, item.created_at, item.confirmed_at];
    for (const value of candidates) {
      const parsed = typeof value === "string" ? Date.parse(value) : NaN;
      if (Number.isFinite(parsed)) return parsed;
    }
    return 0;
  }
  function isClosed(task) {
    const status = String(task.display_status || task.status || "").toLowerCase();
    if (task.cancelled || CLOSED_STATUSES.has(status)) return true;
    if (task.display_status === "completed") return true;
    const accounting = accountingOf(task);
    return task.display_status == null && status === "completed" &&
      actualIn(task) !== null && (accounting.uncollected_expected_cny == null || accounting.uncollected_expected_cny === 0);
  }

  function taskStoreIds(task) {
    const ids = new Set();
    const actions = array(task.plan?.actions || task.action_lines);
    for (const action of actions) {
      if (action.store_id) ids.add(String(action.store_id));
      if (action.target_store_id) ids.add(String(action.target_store_id));
    }
    for (const id of [task.store_id, task.target_store_id]) if (id) ids.add(String(id));
    return ids;
  }
  function belongsToStore(item, storeId) {
    if (!storeId || storeId === "all") return true;
    if (item.store_id || item.target_store_id) {
      return String(item.store_id || "") === String(storeId) || String(item.target_store_id || "") === String(storeId);
    }
    return taskStoreIds(item).has(String(storeId));
  }

  function requiredContext(context) {
    return ["scenarioId", "branchId", "snapshotId", "asOf", "dataVersion", "factVersion"]
      .filter((key) => context[key] === undefined || context[key] === null || context[key] === "");
  }

  function contextQuery(context) {
    return {
      scenario_id: context.scenarioId,
      branch_id: context.branchId,
      snapshot_id: context.snapshotId,
      as_of: context.asOf,
      data_version: context.dataVersion,
      fact_version: context.factVersion,
    };
  }

  function validateResponse(response, label, query) {
    const envelope = object(response);
    const responseContext = object(envelope.context);
    const contextFields = {
      scenario_id: query.scenario_id,
      branch_id: query.branch_id,
      snapshot_id: query.snapshot_id,
      as_of: query.as_of,
      data_version: query.data_version,
      fact_version: query.fact_version,
    };
    for (const [key, expected] of Object.entries(contextFields)) {
      if (responseContext[key] === undefined || String(responseContext[key]) !== String(expected)) {
        throw new Error(`${label}返回的${key}与当前场景不一致，请重新读取。`);
      }
    }
    return envelope;
  }

  function normalizeData(overviewResponse, tasksResponse, proposalsResponse, context) {
    const overviewEnvelope = object(overviewResponse);
    const overview = object(overviewEnvelope.overview || overviewEnvelope);
    const metadata = object(overviewEnvelope.metadata);
    const storeId = context.storeId;
    const tasks = array(object(tasksResponse).tasks)
      .filter((task) => belongsToStore(task, storeId))
      .map((task) => ({ ...task, _expectedCashIn: expectedIn(task), _actualCashIn: actualIn(task) }));
    const proposals = array(object(proposalsResponse).proposals)
      .filter((proposal) => belongsToStore(proposal, storeId))
      .map((proposal) => ({ ...proposal, _expectedCashIn: expectedInForProposal(proposal) }));
    const openTasks = tasks.filter((task) => !isClosed(task));
    const week = remainingWeek(context.asOf);
    for (const task of tasks) task._weeklyCashIn = weeklyCashIn(task, week);
    const knownAmounts = openTasks.map((task) => task._weeklyCashIn).filter((value) => value !== null);
    const unknownCount = openTasks.length - knownAmounts.length;
    const expectedTotal = openTasks.length === 0 || knownAmounts.length === 0
      ? null : cents(knownAmounts.reduce((sum, value) => sum + value, 0));
    const cashResultItems = tasks.filter((task) => task._expectedCashIn !== null || task._actualCashIn !== null)
      .sort((left, right) => timeValue(right) - timeValue(left));
    const lastCashItem = cashResultItems.find((task) => task._actualCashIn !== null) || cashResultItems[0] || null;
    const proposalsOrdered = [...proposals].sort((left, right) => timeValue(right) - timeValue(left));
    const tasksOrdered = [...openTasks].sort((left, right) => timeValue(right) - timeValue(left));
    const nextItem = proposalsOrdered[0]
      ? { kind: "proposal", item: proposalsOrdered[0] }
      : tasksOrdered[0] ? { kind: "task", item: tasksOrdered[0] } : null;

    return {
      overview,
      metadata,
      tasks,
      openTasks: tasksOrdered,
      proposals: proposalsOrdered,
      expectedTotal,
      unknownCount,
      knownCount: knownAmounts.length,
      week,
      lastCashItem,
      nextItem,
      context,
      storeId,
    };
  }

  function asOfText(metadata) {
    const value = metadata.as_of || metadata.as_of_date;
    if (typeof value !== "string" || !value) return "数据时点未知";
    const normalized = value.replace("T", " ").replace(/([+-]\d{2}:?\d{2}|Z)$/, "");
    return `数据截至 ${normalized.slice(0, 16) || value}`;
  }

  function sourceText(metadata) {
    if (metadata.source === "versioned_retail_facts") return "经营事实快照";
    return typeof metadata.source === "string" && metadata.source ? metadata.source : "来源待确认";
  }

  function statusText(task) {
    if (task.exception || task.display_status === "exception" || task.status === "exception") return "异常待处理";
    if (task.display_status === "completed") return "执行与核算已完成";
    return task.next_action || task.display_status || task.status || "跟进中";
  }

  function itemRouteContext(view, item, kind) {
    const next = { ...view.context };
    if (kind === "proposal") {
      next.proposalId = item.proposal_id || item.id || null;
      next.proposalVersion = item.proposal_version || item.version || null;
      next.taskId = null;
    } else {
      next.taskId = item.task_id || item.id || null;
      next.proposalId = item.proposal_id || null;
      next.proposalVersion = item.proposal_version || null;
    }
    return next;
  }

  function renderBreakdown(view) {
    if (!view.openTasks.length && !view.proposals.length) {
      return '<div class="hco-empty-detail">当前快照没有待跟进方案；已有经营总览数据仍由原页面展示。</div>';
    }
    const taskRows = view.openTasks.map((task) => {
      const cash = task._weeklyCashIn === null ? "未知" : moneyText(task._weeklyCashIn);
      const proposalVersion = task.proposal_version || task.proposal?.version;
      const versionLabel = proposalVersion ? `方案 V${escapeHtml(proposalVersion)}` : "方案版本未知";
      const source = task.accounting?.source || task.calculation?.source || task.source || "已批准方案及任务核算";
      return `<article class="hco-breakdown-row">
        <div class="hco-breakdown-name"><strong>${escapeHtml(taskTitle(task))}</strong><small>${escapeHtml(versionLabel)} · ${escapeHtml(statusText(task))}</small></div>
        <div class="hco-breakdown-cash"><b>${escapeHtml(cash)}</b><small>${escapeHtml(view.week ? `${view.week.start} 至 ${shiftDay(view.week.end, -1)} · ` : "")}预计现金流入 · ${escapeHtml(source)}</small></div>
        <button type="button" class="hco-inline-link" data-hco-action="open-task" data-hco-id="${escapeHtml(task.task_id || task.id || "")}" aria-label="查看${escapeHtml(taskTitle(task))}的任务与回执">查看依据</button>
      </article>`;
    }).join("");
    const proposalRows = view.proposals.map((proposal) => {
      const estimate = proposal._expectedCashIn === null ? "未提供" : moneyText(proposal._expectedCashIn);
      return `<article class="hco-breakdown-row hco-breakdown-pending">
        <div class="hco-breakdown-name"><strong>${escapeHtml(proposalTitle(proposal))}</strong><small>待确认 · 不计入已批准预测</small></div>
        <div class="hco-breakdown-cash"><b>${escapeHtml(estimate)}</b><small>如有金额，仅作方案估算</small></div>
        <button type="button" class="hco-inline-link" data-hco-action="open-proposal" data-hco-id="${escapeHtml(proposal.proposal_id || proposal.id || "")}" aria-label="查看${escapeHtml(proposalTitle(proposal))}">去确认</button>
      </article>`;
    }).join("");
    return `<div class="hco-breakdown-list">
      ${taskRows ? `<h3>已批准方案的预计回款</h3>${taskRows}` : ""}
      ${proposalRows ? `<h3>待确认方案</h3>${proposalRows}` : ""}
      <p class="hco-breakdown-note">预计金额只统计服务端已返回的预计现金流入。签收、库存成本和销售额不会当作到账；执行费用单独核算；实际到账只读核销后的现金流水。</p>
    </div>`;
  }

  function render(view, state = {}) {
    if (state.loading) return `<section class="hco-panel" data-hco-panel aria-busy="true"><div class="hco-state"><span class="hco-spinner" aria-hidden="true"></span><p>正在读取本场景的经营与核算数据…</p></div></section>`;
    if (state.error) return `<section class="hco-panel" data-hco-panel><div class="hco-state hco-state-error"><span class="hco-state-mark" aria-hidden="true">!</span><div><h2>现金机会数据暂不可用</h2><p>${escapeHtml(state.error)}</p><button type="button" class="hco-button hco-button-primary" data-hco-action="refresh">重新读取</button></div></div></section>`;
    if (!view) return `<section class="hco-panel" data-hco-panel><div class="hco-state"><p>经营结果尚未加载。</p></div></section>`;

    const amount = largeAmount(view.expectedTotal);
    const knownLabel = view.unknownCount > 0 ? "已知预计回款" : "本周预计可释放现金";
    const pending = view.proposals.length;
    const demo = view.metadata.is_demo === true || view.context.isDemo === true;
    const last = view.lastCashItem;
    const latestExpected = last ? last._expectedCashIn : null;
    const latestActual = last ? last._actualCashIn : null;
    const delta = latestExpected !== null && latestActual !== null ? cents(latestActual - latestExpected) : null;
    const next = view.nextItem;
    const nextName = next ? (next.kind === "proposal" ? proposalTitle(next.item) : taskTitle(next.item)) : "目前没有待确认或跟进事项";
    const nextCopy = next
      ? next.kind === "proposal" ? "方案待确认；确认前不会计入预计回款。" : `下一步：${statusText(next.item)}`
      : "新的方案或回执产生后，这里会显示下一步。";
    const latestName = last ? taskTitle(last) : "尚无已核销的到账记录";
    const latestStatus = !last ? "实际到账以已记录的现金流水为准。"
      : latestActual === null ? "尚未记录到账回执。"
        : delta === null ? "已读取实际到账金额；预计金额未知。"
          : delta === 0 ? "实际到账与预计金额一致。"
            : `与预计相差 ${moneyText(Math.abs(delta))}（${delta > 0 ? "高于" : "低于"}预计）。`;
    const message = state.notice ? `<p class="hco-notice" role="status">${escapeHtml(state.notice)}</p>` : "";
    const dataWarnings = [];
    if (view.openTasks.length === 0) dataWarnings.push("暂无已批准且待跟进的回款预测");
    if (view.unknownCount > 0) dataWarnings.push(`${view.unknownCount} 项金额或到账日期未知，未计入已知金额`);
    if (pending > 0) dataWarnings.push(`${pending} 项待确认方案，未计入预测`);
    const chips = dataWarnings.length
      ? dataWarnings.map((warning, index) => `<span class="hco-chip ${index === 0 && view.openTasks.length === 0 ? "hco-chip-muted" : ""}">${escapeHtml(warning)}</span>`).join("")
      : `<span class="hco-chip hco-chip-positive">${view.openTasks.length} 项已批准方案纳入估算</span>`;
    const currentMeta = `${demo ? '<span class="hco-source-badge">演示数据</span>' : ""}<span>${escapeHtml(sourceText(view.metadata))}</span><span>${escapeHtml(asOfText(view.metadata))}</span>`;
    const moneyCaption = view.unknownCount > 0
      ? `本周可核对的已知预计回款${view.knownCount ? "；未知金额或日期的事项未计入" : "为未知"}`
      : view.expectedTotal === null ? "没有可用预测金额；不会以 0 代替未知" : `按 ${view.week?.start || "当前周"} 至 ${view.week ? shiftDay(view.week.end, -1) : "本周末"} 的已批准回款计划估算，到账以回执为准`;
    const lastExpectedText = latestExpected === null ? "—" : moneyText(latestExpected);
    const lastActualText = latestActual === null ? "待回执" : moneyText(latestActual);
    const actionButton = next
      ? `<button type="button" class="hco-button hco-button-secondary" data-hco-action="open-next" data-hco-kind="${next.kind}" data-hco-id="${escapeHtml(next.item.proposal_id || next.item.task_id || next.item.id || "")}">${next.kind === "proposal" ? "去确认" : "查看进度"}<span aria-hidden="true">→</span></button>`
      : "";
    const lastButton = last
      ? `<button type="button" class="hco-inline-link" data-hco-action="open-task" data-hco-id="${escapeHtml(last.task_id || last.id || "")}">查看差额与回执 <span aria-hidden="true">→</span></button>`
      : "";

    return `<section class="hco-panel" data-hco-panel>
      <header class="hco-header"><div><p class="hco-eyebrow">本周机会</p><h2>库存处置预计回款</h2></div><div class="hco-meta" aria-label="数据来源和时点">${currentMeta}</div></header>
      <div class="hco-hero">
        <p class="hco-value-label">${escapeHtml(knownLabel)}</p>
        <div class="hco-value" aria-label="${escapeHtml(view.expectedTotal === null ? "预计回款未知" : `预计回款${moneyText(view.expectedTotal)}`)}"><span class="hco-value-currency">${view.expectedTotal === null ? "" : "¥"}</span><strong>${escapeHtml(amount.value)}</strong><span class="hco-value-unit">${escapeHtml(amount.unit)}</span></div>
        <p class="hco-caption">${escapeHtml(moneyCaption)}</p><p class="hco-accounting-note">金额按预计现金流入统计，执行费用另列；到账以现金流水与回执核对为准。</p>
        <div class="hco-chips" aria-label="金额口径">${chips}</div>
        <div class="hco-hero-actions"><button type="button" class="hco-button hco-button-primary" data-hco-action="details" aria-expanded="${state.showDetails === true}">${state.showDetails === true ? "收起金额依据" : "查看金额依据"}<span aria-hidden="true">${state.showDetails === true ? "⌃" : "⌄"}</span></button><button type="button" class="hco-button hco-button-quiet" data-hco-action="export" ${view.openTasks.length || pending ? "" : "disabled"}>导出处置清单</button></div>
      </div>
      ${message}
      <div class="hco-lower-grid">
        <article class="hco-lower-card hco-next-card"><div class="hco-card-heading"><span class="hco-card-icon" aria-hidden="true">✓</span><div><p class="hco-card-label">${pending ? (pending === 1 ? "今天只需确认一件事" : `今天有 ${pending} 项待确认`) : "今日优先处理"}</p><h3>${escapeHtml(nextName)}</h3></div></div><p class="hco-card-copy">${escapeHtml(nextCopy)}</p>${actionButton}</article>
        <article class="hco-lower-card hco-reconcile-card"><div><p class="hco-card-label">上次预计，后来到账了吗？</p><h3>${escapeHtml(latestName)}</h3></div><div class="hco-reconcile-values"><div><small>预计</small><b>${escapeHtml(lastExpectedText)}</b></div><div><small>实际到账</small><b>${escapeHtml(lastActualText)}</b></div></div><p class="hco-card-copy">${escapeHtml(latestStatus)}</p>${lastButton}</article>
      </div>
      <div class="hco-details" ${state.showDetails === true ? "" : "hidden"}><div class="hco-details-heading"><div><p class="hco-eyebrow">计算依据</p><h3>预计回款如何汇总</h3></div><span>${view.knownCount} 项已知 · ${view.unknownCount} 项未知</span></div>${renderBreakdown(view)}</div>
    </section>`;
  }

  function csvCell(value) {
    let text = String(value == null ? "" : value);
    if (/^[\s]*[=+@\-]/.test(text)) text = `'${text}`;
    return `"${text.replace(/"/g, '""')}"`;
  }

  function exportCsv(view, documentRef, urlRef, BlobCtor) {
    if (!view.openTasks.length && !view.proposals.length) return false;
    const rows = [["事项类型", "事项编号", "方案版本", "事项", "本周预计现金流入／待确认估值（元）", "是否计入本周预测", "当前状态", "下一步"]];
    for (const task of view.openTasks) {
      rows.push(["已批准任务", task.task_id || task.id, task.proposal_version || task.proposal?.version,
        taskTitle(task), task._weeklyCashIn, task._weeklyCashIn === null ? "否：金额或日期未知" : "是",
        task.status || task.display_status, task.next_action || "等待跟进"]);
    }
    for (const proposal of view.proposals) {
      rows.push(["待确认方案", proposal.proposal_id || proposal.id, proposal.proposal_version || proposal.version,
        proposalTitle(proposal), proposal._expectedCashIn, "否：尚未确认", proposal.status || "pending_approval", "待确认"]);
    }
    const content = `\uFEFF${rows.map((row) => row.map(csvCell).join(",")).join("\r\n")}`;
    const blob = new BlobCtor([content], { type: "text/csv;charset=utf-8" });
    const url = urlRef.createObjectURL(blob);
    const link = documentRef.createElement("a");
    link.href = url;
    link.download = `经营处置清单-${String(view.context.scenarioId || "场景").replace(/[^\w-]/g, "_")}.csv`;
    link.hidden = true;
    documentRef.body.appendChild(link);
    link.click();
    link.remove();
    urlRef.revokeObjectURL(url);
    return true;
  }

  function createCustomEvent(documentRef, name, detail) {
    const EventCtor = documentRef.defaultView?.CustomEvent || global.CustomEvent;
    return typeof EventCtor === "function" ? new EventCtor(name, { bubbles: true, detail }) : null;
  }

  function mount(container, options = {}) {
    if (!container || typeof container.appendChild !== "function" || !container.ownerDocument) {
      throw new TypeError("HackathonCashOpportunity.mount requires a DOM container");
    }
    const documentRef = container.ownerDocument;
    const root = documentRef.createElement("div");
    root.setAttribute("data-hackathon-cash-opportunity", "");
    container.appendChild(root);
    const state = { context: { ...(options.context || {}) }, loading: false, error: "", notice: "", showDetails: false, view: null, destroyed: false, requestId: 0 };
    const api = options.api || {};

    function paint() { if (!state.destroyed) root.innerHTML = render(state.view, state); }
    function fail(message, error = null) {
      state.loading = false;
      state.error = message || error?.message || "接口读取失败，请稍后重试。";
      state.view = null;
      paint();
      const event = createCustomEvent(documentRef, "hackathon:error", {
        context: state.context,
        code: error?.code || "overview_read_failed",
        message: state.error,
        retryable: true,
      });
      if (event) container.dispatchEvent(event);
    }
    async function refresh() {
      const requestId = ++state.requestId;
      const missing = requiredContext(state.context);
      if (missing.length) {
        fail(`经营场景上下文不完整：${missing.join("、")}。`);
        return null;
      }
      if (!["getOverview", "listTasks", "listProposals"].every((method) => typeof api[method] === "function")) {
        fail("缺少共享经营 API（getOverview、listTasks、listProposals），请由总集成注入后再读取。");
        return null;
      }
      state.loading = true;
      state.error = "";
      state.notice = "";
      paint();
      const query = contextQuery(state.context);
      try {
        const [overview, tasks, proposals] = await Promise.all([
          api.getOverview({ ...query, ...(state.context.storeId && state.context.storeId !== "all" ? { store_id: state.context.storeId } : {}) }),
          api.listTasks(query),
          api.listProposals({ ...query, status: "pending_approval" }),
        ]);
        if (state.destroyed || requestId !== state.requestId) return null;
        if (!object(overview).overview || !Array.isArray(object(tasks).tasks) || !Array.isArray(object(proposals).proposals)) {
          throw new Error("经营接口返回结构不完整，请检查共享 API 适配器。");
        }
        validateResponse(overview, "经营总览", query);
        validateResponse(tasks, "执行任务", query);
        validateResponse(proposals, "待确认方案", query);
        state.view = normalizeData(overview, tasks, proposals, state.context);
        state.loading = false;
        state.error = "";
        paint();
        return state.view;
      } catch (error) {
        if (state.destroyed || requestId !== state.requestId) return null;
        fail(error?.message || "接口读取失败，请稍后重试。", error);
        return null;
      }
    }
    function open(kind, id) {
      const list = kind === "proposal" ? state.view?.proposals : state.view?.tasks;
      const item = array(list).find((row) => String(row.proposal_id || row.task_id || row.id || "") === String(id));
      if (!item) {
        state.notice = "该事项已变化，请重新读取最新数据。";
        paint();
        return;
      }
      if (typeof options.navigate !== "function") {
        state.notice = "总集成尚未提供页面导航。";
        paint();
        return;
      }
      options.navigate(FOLLOWUP_ROUTE, itemRouteContext(state.view, item, kind));
    }
    function onClick(event) {
      const button = event.target?.closest?.("[data-hco-action]");
      if (!button || !root.contains(button)) return;
      const action = button.getAttribute("data-hco-action");
      if (action === "refresh") { refresh(); return; }
      if (action === "details") { state.showDetails = !state.showDetails; paint(); return; }
      if (action === "export") {
        try {
          const urlRef = documentRef.defaultView?.URL || global.URL;
          const BlobCtor = documentRef.defaultView?.Blob || global.Blob;
          if (typeof BlobCtor !== "function" || typeof urlRef?.createObjectURL !== "function") throw new Error("当前浏览器不支持导出 CSV。");
          state.notice = exportCsv(state.view, documentRef, urlRef, BlobCtor) ? "处置清单已导出。" : "当前没有可导出的处理事项。";
        } catch (error) { state.notice = error.message || "导出失败，请重试。"; }
        paint();
        return;
      }
      if (action === "open-next") { open(button.getAttribute("data-hco-kind"), button.getAttribute("data-hco-id")); return; }
      if (action === "open-task") { open("task", button.getAttribute("data-hco-id")); return; }
      if (action === "open-proposal") open("proposal", button.getAttribute("data-hco-id"));
    }
    root.addEventListener("click", onClick);
    paint();
    const initialLoad = refresh();

    return {
      refresh,
      getState: () => ({ ...state, context: { ...state.context } }),
      updateContext(nextContext = {}) {
        state.context = { ...state.context, ...nextContext };
        state.showDetails = false;
        return refresh();
      },
      destroy() {
        if (state.destroyed) return;
        state.destroyed = true;
        state.requestId += 1;
        root.removeEventListener("click", onClick);
        if (root.parentNode === container) container.removeChild(root);
      },
      ready: initialLoad,
    };
  }

  return Object.freeze({ mount, render, normalizeData });
});

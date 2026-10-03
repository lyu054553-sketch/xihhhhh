(function (root, factory) {
  const followup = factory();
  if (typeof module === 'object' && module.exports) module.exports = followup;
  if (root) root.HackathonFollowup = followup;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const GROUPS = [
    { id: 'suggestions', label: '待评估建议' },
    { id: 'approvals', label: '待我审批' },
    { id: 'followups', label: '审批后跟进' },
    { id: 'completed', label: '已完成' },
    { id: 'archived', label: '已归档' },
  ];
  const SECTION_LABELS = { workbench: '今日工作台', overview: '经营总览', cases: '案例复盘' };
  const CHANNEL_COMMANDS = new Set([
    'feishu_send_notification', 'feishu_take_over', 'feishu_submit_result', 'feishu_report_exception',
    'wecom_publish', 'wecom_record_price_effective',
    'email_save_draft', 'email_send', 'email_record_supplier_reply', 'email_confirm_terms',
  ]);
  const EVENT_LABELS = {
    proposal_confirmed: '方案已确认并安排执行', approved: '方案已确认', task_created: '执行任务已生成',
    dispatch: '已发货', shipment: '已发货', receipt: '已签收', signed_receipt: '已签收',
    sale: '商品已售出', cash_receipt: '销售款到账', cash_in: '资金到账', cash_payment: '费用已支付',
    cash_out: '资金已支出', fee: '费用已记录', exception: '执行异常', supplier_reply: '供应商已回复',
    terms_confirmed: '条款已确认', promotion_published: '促销内容已发布', price_effective: '价格已生效',
    channel_sent: '渠道动作已发送', stock_balance: '库存余额', receipt_recorded: '回执已记录',
  };
  const STATUS_LABELS = {
    draft: '草稿', pending_approval: '待我审批', approved: '已确认 · 待跟进', execution_task_created: '已安排执行',
    draft_pending_external_execution: '待发送', pending_dispatch: '待发货', in_transit: '运输中',
    awaiting_receipt: '待签收', received: '已签收 · 结果待核算', completed: '已完成',
    in_progress: '执行中', partial: '部分完成', exception: '需处理', failed: '执行失败',
    cancelled: '已取消', canceled: '已取消', archived: '已归档', suggested: '待评估建议', draft_saved: '草稿已保存',
    sent: '已发送', waiting_reply: '等待回复', published: '已发布', price_effective: '价格已生效',
    taken_over: '已接手', accepted: '已接手', replied: '已回复',
    pending: '待核算', reconciling: '核算中', calculating: '核算中', reconciled: '已核算', settled: '已核算',
    superseded: '已被新版本替代', invalidated: '已失效，需重新确认', unavailable: '暂无法判断', not_recorded: '尚未记录',
  };

  function own(object, key) { return Object.prototype.hasOwnProperty.call(object || {}, key); }
  function finite(value) { return value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value)); }
  function numberOrNull(value) { return finite(value) ? Number(value) : null; }
  function nonNegative(value) { const n = numberOrNull(value); return n === null ? null : Math.max(0, n); }
  function firstValue() {
    for (let index = 0; index < arguments.length; index += 1) {
      if (arguments[index] !== null && arguments[index] !== undefined) return arguments[index];
    }
    return null;
  }
  function escapeHTML(value) {
    return String(value === null || value === undefined ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function money(value) {
    const n = numberOrNull(value);
    return n === null ? '未知' : '¥' + n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function quantity(value, unit) {
    const n = numberOrNull(value);
    return n === null ? '未知' : n.toLocaleString('zh-CN') + (unit ? ' ' + unit : ' 单位未知');
  }
  function dateTime(value) {
    if (!value) return '未记录时间';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return String(value);
    return new Intl.DateTimeFormat('zh-CN', {
      timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
    }).format(parsed).replace(/\//g, '-');
  }
  function dataMeta(snapshot) { return snapshot && snapshot.metadata ? snapshot.metadata : (snapshot || {}); }
  function array(value) { return Array.isArray(value) ? value : []; }
  function statusText(value) { return STATUS_LABELS[value] || value || '状态未知'; }
  function eventText(event) { return event.label || EVENT_LABELS[event.kind] || event.title || '业务记录'; }
  function eventTime(event) { return event.occurred_at || event.created_at || event.at || null; }
  function compareEventTime(a, b) {
    const left = Date.parse(eventTime(a) || '');
    const right = Date.parse(eventTime(b) || '');
    if (Number.isFinite(left) && Number.isFinite(right)) return left - right;
    return String(eventTime(a) || '').localeCompare(String(eventTime(b) || ''));
  }
  function eventReality(event) {
    if (event.is_actual === true || event.actual === true) return true;
    if (event.is_actual === false || event.actual === false || event.expected === true) return false;
    if (event.basis === 'forecast' || event.status === 'expected' || event.status === 'forecast') return false;
    return null;
  }
  function isActual(event) { return eventReality(event) === true; }
  function isOpenException(matter) {
    if (matter.exception) {
      const exception = matter.exception;
      if (typeof exception === 'string') return true;
      if (exception.open === false || exception.status === 'resolved' || exception.status === 'closed') return false;
      return true;
    }
    return array(matter.exceptions).some((item) => item && item.status !== 'resolved' && item.status !== 'closed');
  }
  function completionCriteriaSatisfied(task, accounting) {
    const criteria = task.completion_criteria;
    if (task.completion_criteria_met === true || task.completion_criteria_satisfied === true) return true;
    if (criteria && typeof criteria === 'object') {
      if (criteria.satisfied === true || criteria.complete === true || criteria.met === true) return true;
      if (Array.isArray(criteria.required) && criteria.required.length) {
        const checks = criteria.completed || criteria.results || {};
        if (criteria.required.every((key) => checks[key] === true)) return true;
      }
    }
    const evidence = array(accounting.event_refs).length || array(accounting.cash_event_ids).length ||
      array(accounting.allocation_ids).length || array(accounting.return_event_ids).length ||
      array(task.completion_evidence).length || task.completion_evidence === true;
    const rawAccountingStatus = String(accounting.execution_status || accounting.status || '').toLowerCase();
    const unmatched = numberOrNull(accounting.unmatched_cash_cny);
    const hasExpectedCash = numberOrNull(accounting.expected_cash_in_cny) > 0 || numberOrNull(accounting.expected_cash_out_cny) > 0;
    const actualIn = numberOrNull(accounting.actual_cash_in_cny);
    const actualOut = numberOrNull(accounting.actual_cash_out_cny);
    const cashReconciled = !hasExpectedCash || (
      (!numberOrNull(accounting.expected_cash_in_cny) || (actualIn !== null && actualIn >= numberOrNull(accounting.expected_cash_in_cny))) &&
      (!numberOrNull(accounting.expected_cash_out_cny) || (actualOut !== null && actualOut >= numberOrNull(accounting.expected_cash_out_cny))) &&
      (unmatched === null || unmatched === 0)
    );
    return evidence && rawAccountingStatus === 'completed' && cashReconciled;
  }
  function mapFollowupDisplay(task, accounting) {
    const source = task || {};
    const books = accounting || source.accounting || {};
    const rawStatus = String(source.status || 'unknown');
    const planned = nonNegative(firstValue(source.planned_qty, source.planned_quantity, books.planned_qty));
    const completed = nonNegative(firstValue(source.completed_qty, source.received_qty, source.shipped_qty, books.received_qty, books.shipped_qty));
    const uncompleted = planned === null || completed === null ? null : Math.max(0, planned - completed);
    const lower = rawStatus.toLowerCase();
    const cancelled = ['cancelled', 'canceled'].includes(lower);
    const archived = lower === 'archived' || source.archived === true;
    const exception = source.exception || null;
    const closedReason = source.closed_reason || source.cancellation_reason || null;
    const needsAttention = Boolean(exception && !(exception.open === false || exception.status === 'resolved' || exception.status === 'closed')) ||
      ['exception', 'failed', 'rejected'].includes(lower);
    const pendingStatuses = new Set(['draft', 'draft_pending_external_execution', 'pending', 'pending_dispatch', 'approved', 'execution_task_created', 'queued']);
    const fullQuantity = planned !== null && completed !== null && completed >= planned;
    const completionSatisfied = fullQuantity && completionCriteriaSatisfied(source, books);
    let executionDisplayStatus;
    if (cancelled) executionDisplayStatus = '已取消';
    else if (archived) executionDisplayStatus = '已归档';
    else if (completionSatisfied) executionDisplayStatus = '已完成';
    else if (pendingStatuses.has(lower)) executionDisplayStatus = '待执行';
    else if (['in_transit', 'awaiting_receipt', 'received', 'in_progress', 'partial', 'partially_completed', 'completed', 'exception', 'failed'].includes(lower) || (completed !== null && completed > 0)) executionDisplayStatus = '执行中';
    else executionDisplayStatus = statusText(rawStatus);

    const accountingStatus = String(books.status || books.accounting_status || '').toLowerCase();
    const evidencePresent = [books.sold_qty, books.sales_amount_cny, books.actual_cash_in_cny, books.actual_cash_out_cny, books.unmatched_cash_cny]
      .some((value) => numberOrNull(value) !== null) || array(books.cash_event_ids).length > 0 ||
      array(books.allocation_ids).length > 0 || Boolean(books.return_evidence || books.exchange_evidence) ||
      Boolean(source.completion_criteria_met || (source.completion_criteria && source.completion_criteria.satisfied === true));
    const rawAccountingStatus = String(books.execution_status || '').toLowerCase();
    const accountingComplete = (['reconciled', 'settled', 'completed'].includes(accountingStatus) || ['reconciled', 'settled', 'completed'].includes(rawAccountingStatus)) &&
      (fullQuantity ? completionCriteriaSatisfied(source, books) : false);
    let accountingDisplayStatus = accountingComplete ? '已核算' : (evidencePresent ? '核算中' : '待核算');
    if (cancelled || archived) accountingDisplayStatus = evidencePresent ? '核算中' : '待核算';
    return {
      raw_execution_status: rawStatus,
      execution_display_status: executionDisplayStatus,
      accounting_display_status: accountingDisplayStatus,
      planned_qty: planned,
      completed_qty: completed,
      uncompleted_qty: uncompleted,
      exception,
      closed_reason: closedReason,
      needs_attention: needsAttention,
    };
  }
  function hasOutstanding(matter) {
    const result = matter.result || {};
    const task = matter.execution || matter.task || {};
    const outstanding = firstValue(result.outstanding_cash_amount, result.pending_cash_amount, task.pending_cash_amount);
    if (numberOrNull(outstanding) !== null && Number(outstanding) > 0) return true;
    const totals = aggregateMatter(matter);
    if (totals.outstandingCash !== null && totals.outstandingCash > 0) return true;
    if (totals.expectedCashIn > 0 && totals.actualCash === null) return true;
    if (totals.expectedCashOut > 0 && totals.actualCashOut === null) return true;
    if (totals.expectedCashUnclassified > 0) return true;
    if (totals.plannedQty !== null && totals.receivedQty !== null && totals.receivedQty < totals.plannedQty) return true;
    if (totals.plannedQty > 0 && totals.receivedQty === null && (task.status === 'received' || task.status === 'completed' || matter.status === 'received' || matter.status === 'completed')) return true;
    return false;
  }
  function classifyMatter(matter) {
    const item = matter || {};
    const raw = item.status || (item.proposal && item.proposal.status) || (item.execution && item.execution.status) || '';
    const result = item.result || {};
    const task = item.execution || item.task || {};
    if (['cancelled', 'canceled', 'archived'].includes(String(raw).toLowerCase()) || ['cancelled', 'canceled', 'archived'].includes(String(task.status || '').toLowerCase()) || item.closed === true) return 'archived';
    if (raw === 'pending_approval' || (item.proposal && item.proposal.status === 'pending_approval')) return 'approvals';
    if (raw === 'draft' || raw === 'suggested' || raw === 'pending_evaluation' || item.has_proposal === false) return 'suggestions';
    if (!item.proposal && !task.id && !task.task_id && !item.execution_task_id && !item.execution_task) return 'suggestions';
    const resultDone = result.status === 'completed' || result.status === 'reconciled' || result.status === 'settled';
    const projection = mapFollowupDisplay(task, accountingForDisplay(item));
    if (['exception', 'failed', 'rejected'].includes(String(raw).toLowerCase()) || projection.needs_attention) return 'followups';
    const taskDone = projection.execution_display_status === '已完成';
    if (taskDone && resultDone && !hasOutstanding(item) && !isOpenException(item) && !projection.needs_attention) return 'completed';
    return 'followups';
  }
  function groupItems(snapshot, group) {
    const matters = array(snapshot && (snapshot.matters || snapshot.items || snapshot.work_items));
    return matters.filter((matter) => classifyMatter(matter) === group);
  }
  function sumEvents(events, predicate, field) {
    const matching = events.filter(predicate);
    if (!matching.length) return null;
    let total = 0;
    matching.forEach((event) => {
      const value = numberOrNull(firstValue(event[field], field === 'amount' ? event.cash_amount : null, field === 'expected_amount' ? event.amount : null, event.qty, event.sold_qty));
      if (value === null) { total = null; return; }
      if (total !== null) total += value;
    });
    return total;
  }
  function eventKind(event) { return String(event.kind || event.type || '').toLowerCase(); }
  function eventIs(kindSet, event) { return kindSet.has(eventKind(event)); }
  function sumActualEvents(events, kindSet, field) {
    const candidates = events.filter((event) => eventIs(kindSet, event));
    if (!candidates.length || candidates.some((event) => eventReality(event) === null)) return null;
    const actual = candidates.filter(isActual);
    return actual.length ? sumEvents(actual, () => true, field) : null;
  }
  function eventOrSnapshot(events, kindSet, field, fallback) {
    const hasEvents = events.some((event) => eventIs(kindSet, event));
    return hasEvents ? sumActualEvents(events, kindSet, field) : numberOrNull(fallback);
  }
  function latestInventory(events) {
    const balances = new Map();
    const inventoryEvents = events.filter((event) => eventIs(new Set(['stock_balance', 'inventory_balance', 'current_stock']), event));
    if (inventoryEvents.some((event) => eventReality(event) === null)) return null;
    const actualBalances = inventoryEvents.filter(isActual);
    if (!actualBalances.length || actualBalances.some((event) => !(event.store_id || event.location_id || event.store))) return null;
    actualBalances.forEach((event) => {
        const key = String(event.store_id || event.location_id || event.store);
        const current = balances.get(key);
        if (!current || compareEventTime(event, current) >= 0) balances.set(key, event);
      });
    if (!balances.size) return null;
    let total = 0;
    for (const event of balances.values()) {
      const value = numberOrNull(firstValue(event.quantity, event.qty, event.balance_qty));
      if (value === null) return null;
      total += value;
    }
    return total;
  }
  function aggregateMatter(matter) {
    const item = matter || {};
    const events = array(item.events).slice();
    const proposal = item.proposal || {};
    const task = item.execution || item.task || {};
    const result = item.result || {};
    const accounting = item.accounting || result.accounting || task.accounting || {};
    const salesKinds = new Set(['sale', 'sales', 'sale_completed']);
    const sales = eventOrSnapshot(events, salesKinds, 'quantity', accounting.sold_qty);
    const salesAmount = eventOrSnapshot(events, salesKinds, 'amount', accounting.sales_amount_cny);
    const dispatchKinds = new Set(['dispatch', 'shipment']);
    const receiptKinds = new Set(['receipt', 'signed_receipt']);
    const dispatched = eventOrSnapshot(events, dispatchKinds, 'quantity', firstValue(accounting.shipped_qty, task.shipped_qty, task.dispatched_qty, task.dispatched_quantity));
    const received = eventOrSnapshot(events, receiptKinds, 'quantity', firstValue(accounting.received_qty, task.received_qty, task.received_quantity, task.completed_qty));
    const cashInCandidates = events.filter((event) => (
      eventIs(new Set(['cash_receipt', 'cash_in', 'settlement_in']), event) ||
      (event.direction === 'in' && eventIs(new Set(['cash', 'cash_event', 'settlement']), event))
    ));
    const cashInUnknown = cashInCandidates.some((event) => eventReality(event) === null);
    const cashInEvents = cashInCandidates.filter(isActual);
    const cashOutCandidates = events.filter((event) => (
      eventIs(new Set(['fee', 'transport_fee', 'cash_payment', 'cash_out', 'settlement_out', 'purchase_payment', 'payable_payment']), event) ||
      (event.direction === 'out' && eventIs(new Set(['cash', 'cash_event', 'settlement', 'payment', 'purchase_payment', 'fee', 'transport']), event))
    ));
    const cashOutUnknown = cashOutCandidates.some((event) => eventReality(event) === null);
    const cashOutEvents = cashOutCandidates.filter(isActual);
    const feeCandidates = cashOutCandidates.filter((event) => eventIs(new Set(['fee', 'transport_fee']), event) || event.category === 'fee' || event.category === 'transport');
    const feeUnknown = feeCandidates.some((event) => eventReality(event) === null);
    const feeEvents = feeCandidates.filter(isActual);
    const actualCash = cashInUnknown ? null : (cashInEvents.length ? sumEvents(cashInEvents, () => true, 'amount') : numberOrNull(accounting.actual_cash_in_cny));
    const actualCashOut = cashOutUnknown ? null : (cashOutEvents.length ? sumEvents(cashOutEvents, () => true, 'amount') : numberOrNull(accounting.actual_cash_out_cny));
    const actualFees = feeUnknown ? null : (feeEvents.length ? sumEvents(feeEvents, () => true, 'amount') : numberOrNull(firstValue(accounting.execution_cost_cny, accounting.transport_cost_cny)));
    const expectedEvents = array(firstValue(result.expected_cash_events, proposal.expected_cash_events));
    const accountingExpectedIn = numberOrNull(accounting.expected_cash_in_cny);
    const accountingExpectedOut = numberOrNull(accounting.expected_cash_out_cny);
    const scalarExpected = numberOrNull(firstValue(result.expected_cash_amount, proposal.expected_cash_amount));
    const scalarDirection = String(firstValue(result.expected_cash_direction, proposal.expected_cash_direction, '')).toLowerCase();
    const directionIsIn = ['in', 'inflow', 'cash_in', 'receipt', 'incoming'].includes(scalarDirection);
    const directionIsOut = ['out', 'outflow', 'cash_out', 'payment', 'outgoing'].includes(scalarDirection);
    const expectedCashUnclassified = scalarExpected !== null && scalarExpected > 0 && !directionIsIn && !directionIsOut ? scalarExpected : null;
    function expectedAmount(direction) {
      if (expectedEvents.length) {
        const matching = expectedEvents.filter((event) => {
          const value = String(event.direction || '').toLowerCase();
          return direction === 'in' ? ['in', 'inflow', 'cash_in', 'receipt', 'incoming'].includes(value)
            : ['out', 'outflow', 'cash_out', 'payment', 'outgoing'].includes(value);
        });
        return matching.length ? sumEvents(matching, () => true, 'expected_amount') : 0;
      }
      const accountingValue = direction === 'in' ? accountingExpectedIn : accountingExpectedOut;
      if (accountingValue !== null) return accountingValue;
      if (scalarExpected !== null && (direction === 'in' ? directionIsIn : directionIsOut)) return scalarExpected;
      return null;
    }
    const expectedCashIn = expectedAmount('in');
    const expectedCashOut = expectedAmount('out');
    const outstandingCashIn = expectedCashIn === null ? null : (expectedCashIn === 0 ? 0 : (actualCash === null ? null : Math.max(0, expectedCashIn - actualCash)));
    const outstandingCashOut = expectedCashOut === null ? null : (expectedCashOut === 0 ? 0 : (actualCashOut === null ? null : Math.max(0, expectedCashOut - actualCashOut)));
    const unmatchedCash = numberOrNull(accounting.unmatched_cash_cny);
    const computedOutstanding = expectedCashIn > 0 ? outstandingCashIn : (expectedCashOut > 0 ? outstandingCashOut : firstValue(outstandingCashIn, outstandingCashOut));
    const outstandingCash = unmatchedCash !== null && unmatchedCash > 0 ? Math.max(computedOutstanding || 0, unmatchedCash) : computedOutstanding;
    const remaining = firstValue(numberOrNull(accounting.ending_qty), latestInventory(events));
    const plannedQty = numberOrNull(firstValue(accounting.planned_qty, task.planned_qty, task.planned_quantity, proposal.planned_qty, proposal.quantity));
    const unit = firstValue(task.base_unit, accounting.base_unit, task.unit, proposal.unit, item.unit);
    const actualQty = received;
    return {
      plannedQty, dispatchedQty: dispatched,
      receivedQty: actualQty, soldQty: sales, salesAmount,
      expectedCash: expectedCashIn !== null ? expectedCashIn : expectedCashOut,
      expectedCashIn, expectedCashOut, actualCash, actualCashOut, actualFees,
      expectedCashUnclassified, outstandingCashIn, outstandingCashOut, outstandingCash, remainingInventoryQty: remaining,
      unit, cashInCount: cashInEvents.length, hasActualEvents: events.some(isActual),
    };
  }
  function accountingForDisplay(matter) {
    const item = matter || {};
    const source = item.accounting || (item.result || {}).accounting || {};
    if (Object.keys(source).length || !array(item.events).length) return source;
    const totals = aggregateMatter(item);
    const actualEventIds = array(item.events).filter(isActual).map((event) => event.event_id || event.id).filter(Boolean);
    return {
      ...source,
      execution_status: source.execution_status || (item.result || {}).status,
      planned_qty: totals.plannedQty,
      shipped_qty: totals.dispatchedQty,
      received_qty: totals.receivedQty,
      sold_qty: totals.soldQty,
      expected_cash_in_cny: totals.expectedCashIn,
      expected_cash_out_cny: totals.expectedCashOut,
      actual_cash_in_cny: totals.actualCash,
      actual_cash_out_cny: totals.actualCashOut,
      unmatched_cash_cny: source.unmatched_cash_cny,
      event_refs: actualEventIds,
      cash_event_ids: actualEventIds.filter((id) => /cash/i.test(id)),
    };
  }
  function formatGroupStatus(matter) {
    const raw = matter.status || (matter.proposal && matter.proposal.status) || (matter.execution && matter.execution.status) || '';
    const totals = aggregateMatter(matter);
    const task = matter.execution || matter.task || {};
    const result = matter.result || {};
    if (classifyMatter(matter) === 'archived') {
      const closedStatus = ['cancelled', 'canceled', 'archived'].includes(String(raw).toLowerCase()) ? raw : task.status;
      return statusText(closedStatus || 'archived');
    }
    if (classifyMatter(matter) === 'completed') return '已完成';
    if (classifyMatter(matter) === 'followups') {
      const resultStatus = result.status;
      if (isOpenException(matter) || ['exception', 'failed', 'rejected'].includes(String(raw).toLowerCase()) || mapFollowupDisplay(task, accountingForDisplay(matter)).needs_attention) return '需处理';
      const display = mapFollowupDisplay(task, accountingForDisplay(matter));
      const taskDone = display.execution_display_status === '已完成';
      if (taskDone && totals.plannedQty > 0 && totals.receivedQty === null) return '签收数量待核对';
      if (totals.plannedQty !== null && totals.receivedQty !== null && totals.receivedQty < totals.plannedQty) return '部分执行';
      if (totals.expectedCashIn > 0 && totals.actualCash === null) return '待核对到账';
      if (totals.outstandingCashIn > 0) return '待到账 ' + money(totals.outstandingCashIn);
      if (totals.expectedCashOut > 0 && totals.actualCashOut === null) return '待核对支付';
      if (totals.outstandingCashOut > 0) return '待支付 ' + money(totals.outstandingCashOut);
      if (totals.expectedCashUnclassified > 0) return '现金方向待核对';
      const resultDone = display.accounting_display_status === '已核算' || ['completed', 'reconciled', 'settled'].includes(resultStatus);
      const signed = raw === 'received' || task.status === 'received';
      const executionDone = raw === 'completed' || task.status === 'completed';
      if (signed && !resultDone) return '已签收 · 结果待核算';
      if (executionDone && !resultDone) return ['reconciling', 'calculating', 'in_progress'].includes(resultStatus) ? '执行已完成 · 核算中' : '执行已完成 · 结果待核算';
    }
    return mapFollowupDisplay(matter.execution || matter.task || {}, accountingForDisplay(matter)).execution_display_status || statusText(raw);
  }
  function canShowAsCompleted(matter) { return classifyMatter(matter) === 'completed'; }
  function safeAssetUrl(value) {
    const url = String(value || '').trim();
    if (!url || /^(javascript|data|vbscript):/i.test(url) || /^\/\//.test(url)) return '';
    return /^(\/|\.\/|\.\.\/|assets\/)/i.test(url) ? url : '';
  }
  function actionLabel(command) {
    const labels = {
      confirm_and_arrange: '确认方案并安排执行', record_receipt: '保存回执',
      feishu_send_notification: '发送通知', feishu_take_over: '确认接手',
      feishu_submit_result: '提交执行结果', feishu_report_exception: '上报异常',
      wecom_publish: '发布促销内容', wecom_record_price_effective: '登记价格生效',
      email_save_draft: '保存草稿', email_send: '发送邮件',
      email_record_supplier_reply: '记录供应商回复', email_confirm_terms: '确认协商条款',
    };
    return labels[command] || '保存记录';
  }
  function previewData() {
    const source = 'retail-v2 · 本地前端预览夹具';
    const s01Events = [
      { event_id: 'S01-E01', kind: 'proposal_confirmed', occurred_at: '2026-10-03T09:34:00+08:00', label: '确认方案并安排执行', detail: '第 2 版方案 · 从西湖古荡店调往西湖文三店', is_actual: true, source: '本地回放记录' },
      { event_id: 'S01-E02', kind: 'dispatch', occurred_at: '2026-10-04T08:10:00+08:00', quantity: 80, unit: '盒', detail: '调出古荡店主线批次', is_actual: true, source: '发货回执' },
      { event_id: 'S01-E03', kind: 'receipt', occurred_at: '2026-10-04T10:02:00+08:00', quantity: 80, unit: '盒', detail: '文三店签收', is_actual: true, source: '签收回执', receipt_ref: 'S01-RECEIPT-80' },
      { event_id: 'S01-E04', kind: 'sale', occurred_at: '2026-10-24T19:20:00+08:00', quantity: 64, unit: '盒', amount: 6400, cost_amount: 5120, detail: '来自本次调拨批次的销售', is_actual: true, source: '销售明细' },
      { event_id: 'S01-E05', kind: 'cash_receipt', direction: 'in', occurred_at: '2026-10-24T20:00:00+08:00', amount: 6400, detail: '销售款已记账', is_actual: true, source: '账户流水', receipt_ref: 'S01-CASH-6400' },
      { event_id: 'S01-E06', kind: 'transport_fee', direction: 'out', occurred_at: '2026-10-04T10:04:00+08:00', amount: 24, category: 'fee', detail: '本次调拨运费', is_actual: true, source: '费用凭据', receipt_ref: 'S01-FEE-24' },
      { event_id: 'S01-E07', kind: 'stock_balance', occurred_at: '2026-10-24T20:05:00+08:00', quantity: 40, store_id: 'ST-001', store: '西湖古荡店', unit: '盒', detail: '原店主线批次剩余', is_actual: true, source: '库存事件' },
      { event_id: 'S01-E08', kind: 'stock_balance', occurred_at: '2026-10-24T20:05:00+08:00', quantity: 16, store_id: 'ST-002', store: '西湖文三店', unit: '盒', detail: '调入批次剩余', is_actual: true, source: '库存事件' },
    ];
    const s09Events = [
      { event_id: 'S09-E01', kind: 'proposal_confirmed', occurred_at: '2026-10-03T09:34:00+08:00', label: '确认方案并安排执行', detail: '第 2 版方案 · 计划调拨 80 盒', is_actual: true, source: '本地回放记录' },
      { event_id: 'S09-E02', kind: 'dispatch', occurred_at: '2026-10-04T08:10:00+08:00', quantity: 60, unit: '盒', detail: '本次发出 60 盒，另有 20 盒未执行', is_actual: true, source: '发货回执' },
      { event_id: 'S09-E03', kind: 'receipt', occurred_at: '2026-10-04T10:02:00+08:00', quantity: 60, unit: '盒', detail: '文三店签收 60 盒', is_actual: true, source: '签收回执', receipt_ref: 'S09-RECEIPT-60' },
      { event_id: 'S09-E04', kind: 'sale', occurred_at: '2026-10-24T19:20:00+08:00', quantity: 40, unit: '盒', amount: 4000, cost_amount: 3200, detail: '来自已签收部分的销售', is_actual: true, source: '销售明细' },
      { event_id: 'S09-E05', kind: 'cash_receipt', direction: 'in', occurred_at: '2026-10-24T20:00:00+08:00', amount: 3000, detail: '部分销售款已记账', is_actual: true, source: '账户流水', receipt_ref: 'S09-CASH-3000' },
      { event_id: 'S09-E06', kind: 'stock_balance', occurred_at: '2026-10-24T20:05:00+08:00', quantity: 60, store_id: 'ST-001', store: '西湖古荡店', unit: '盒', detail: '原店仍有可用库存', is_actual: true, source: '库存事件' },
      { event_id: 'S09-E07', kind: 'stock_balance', occurred_at: '2026-10-24T20:05:00+08:00', quantity: 20, store_id: 'ST-002', store: '西湖文三店', unit: '盒', detail: '签收批次扣除已售数量后的余额', is_actual: true, source: '库存事件' },
    ];
    const s01 = {
      id: 'CASE-S01-TRANSFER', case_id: 'CASE-S01', scenario_id: 'S01', title: '古荡店坚果调往文三店', kind: 'transfer', status: 'in_transit',
      owner: '张经理', due_at: '2026-10-04T15:30:00+08:00', next_step: '核对后续销售与账户到账记录',
      summary: '古荡店主线批次库存偏高，文三店有可承接需求。', is_demo: true, source,
      proposal: { id: 'PROP-S01', version: 2, status: 'approved', action: '跨店调拨', source_store: '西湖古荡店', target_store: '西湖文三店', planned_qty: 80, unit: '盒', unit_cost: 80, expected_cash_amount: 6400, expected_cash_direction: 'in', confirmed_at: '2026-10-03T09:34:00+08:00' },
      execution: { id: 'TASK-S01', status: 'completed', planned_qty: 80, dispatched_qty: 80, received_qty: 80, unit: '盒', version: 3 },
      result: { status: 'completed', expected_cash_amount: 6400, sold_qty: 64 }, events: s01Events,
      evidence: [
        { label: '调出店库存', value: '120 盒', source: '2026-10-03 库存快照' },
        { label: '近 30 天销量', value: '12 盒', source: '90 天经营事实' },
        { label: '调入店日均需求假设', value: '4 盒', source: '需求假设' },
        { label: '路线运费', value: '¥24.00', source: '人工录入路线' },
      ],
      versions: [
        { version: 1, status: 'superseded', created_at: '2026-10-03T09:31:00+08:00', summary: '初始候选方案' },
        { version: 2, status: 'approved', created_at: '2026-10-03T09:34:00+08:00', summary: '确认 80 盒，运费 ¥24.00' },
      ], channels: [],
    };
    const s09 = {
      id: 'CASE-S09-PARTIAL', case_id: 'CASE-S09', scenario_id: 'S09', title: '调拨部分签收，销售款待核对', kind: 'transfer', status: 'in_progress',
      owner: '李店长', due_at: '2026-10-25T17:00:00+08:00', next_step: '安排剩余 20 盒，并核对未到账金额',
      exception: null, is_demo: true, source,
      proposal: { id: 'PROP-S09', version: 2, status: 'approved', action: '跨店调拨', source_store: '西湖古荡店', target_store: '西湖文三店', planned_qty: 80, unit: '盒', unit_cost: 80, expected_cash_amount: 4000, expected_cash_direction: 'in', confirmed_at: '2026-10-03T09:34:00+08:00' },
      execution: { id: 'TASK-S09', status: 'in_progress', planned_qty: 80, dispatched_qty: 60, received_qty: 60, unit: '盒', version: 4 },
      result: { status: 'in_progress', expected_cash_amount: 4000, sold_qty: 40 }, events: s09Events,
      evidence: [
        { label: '本次計畫', value: '80 盒', source: '已确认方案 V2' },
        { label: '已签收', value: '60 盒', source: '门店签收回执' },
        { label: '已售出', value: '40 盒', source: '销售明细' },
        { label: '预计可结算金额', value: '¥4,000.00', source: '销售记录' },
      ],
      versions: [{ version: 2, status: 'approved', created_at: '2026-10-03T09:34:00+08:00', summary: '确认 80 盒' }],
      channels: [{ type: 'feishu', status: 'sent', sent_at: '2026-10-03T09:35:00+08:00', task_ref: 'TASK-S09', content: { title: '坚果调拨任务', body: '请确认本次调拨任务及预计完成时间。' } }],
    };
    const purchase = {
      id: 'CASE-S07-PURCHASE', case_id: 'CASE-S07', scenario_id: 'S07', title: '采购计划调整待采购员接手', kind: 'procurement', status: 'in_progress',
      owner: '王采购', due_at: '2026-10-05T12:00:00+08:00', next_step: '采购员核对调整数量并提交订单结果',
      summary: '现货与已付在途已纳入计划；建议数量仍需依据方案版本核对。', is_demo: true, source,
      proposal: { id: 'PROP-S07', version: 1, status: 'approved', action: '采购调整', planned_qty: 60, unit: '件', expected_cash_amount: 2400, expected_cash_direction: 'out', original_qty: 100, unit_cost: 40 },
      execution: { id: 'TASK-S07', status: 'pending_dispatch', planned_qty: 60, unit: '件', version: 1 },
      result: { status: 'pending' }, events: [{ event_id: 'S07-E01', kind: 'proposal_confirmed', occurred_at: '2026-10-03T10:00:00+08:00', label: '采购方案已确认并安排执行', detail: '建议采购 60 件', is_actual: true, source: '方案记录' }],
      versions: [{ version: 1, status: 'approved', created_at: '2026-10-03T10:00:00+08:00', summary: '建议采购 60 件' }],
      channels: [{ type: 'feishu', status: 'draft_saved', task_ref: 'TASK-S07', content: { title: '采购数量调整', body: '原意向 100 件，方案建议 60 件。请核对供应商与交期后提交订单结果。', owner: '王采购', due_at: '2026-10-05T12:00:00+08:00', original_qty: 100, proposed_qty: 60, reason: '现货与已付在途已纳入计算。' } }],
    };
    const promotion = {
      id: 'CASE-S06-PROMOTION', case_id: 'CASE-S06', scenario_id: 'S06', title: '饼干与饮料组合促销待发布', kind: 'promotion', status: 'approved',
      owner: '陈店长', due_at: '2026-10-06T10:00:00+08:00', next_step: '检查素材文案，再发布并登记价格生效',
      is_demo: true, source,
      proposal: { id: 'PROP-S06', version: 2, status: 'approved', action: '组合促销', planned_qty: 40, unit: '组', unit_cost: null },
      execution: { id: 'TASK-S06', status: 'pending_dispatch', planned_qty: 40, unit: '组', version: 1 }, result: { status: 'pending' },
      events: [{ event_id: 'S06-E01', kind: 'proposal_confirmed', occurred_at: '2026-10-03T10:20:00+08:00', label: '促销方案已确认', detail: '第一阶段 11 元，第二阶段 10 元', is_actual: true, source: '方案记录' }],
      versions: [{ version: 1, status: 'superseded', created_at: '2026-10-03T10:15:00+08:00', summary: '初始价格版本' }, { version: 2, status: 'approved', created_at: '2026-10-03T10:20:00+08:00', summary: '方案价格符合底价约束' }],
      channels: [{ type: 'wecom', status: 'draft_saved', task_ref: 'TASK-S06', content: { title: '每日坚果礼盒组合活动', body: '活动期间，精选商品组合价 11 元起。具体商品、门店、价格与期限以批准方案为准。', price_stages: [{ label: '第一阶段', price: 11 }, { label: '第二阶段', price: 10 }], start_at: '2026-10-05', end_at: '2026-10-12', image_url: 'assets/retail-nuts.png' } }],
    };
    const supplier = {
      id: 'CASE-S05-RETURN', case_id: 'CASE-S05', scenario_id: 'S05', title: '供应商退货条款待确认', kind: 'supplier_return', status: 'approved',
      owner: '赵采购', due_at: '2026-10-05T16:30:00+08:00', next_step: '确认供应商回复中的结算方式与有效期限',
      is_demo: true, source,
      proposal: { id: 'PROP-S05', version: 1, status: 'approved', action: '退货退款', planned_qty: 100, unit: '桶', unit_cost: 10, expected_cash_amount: 1000, expected_cash_direction: 'in' },
      execution: { id: 'TASK-S05', status: 'pending_dispatch', planned_qty: 100, unit: '桶', version: 1 }, result: { status: 'pending' },
      events: [{ event_id: 'S05-E01', kind: 'proposal_confirmed', occurred_at: '2026-10-03T10:40:00+08:00', label: '退供方案已确认', detail: '退款、换货、抵款为互斥分支', is_actual: true, source: '方案记录' }],
      versions: [{ version: 1, status: 'approved', created_at: '2026-10-03T10:40:00+08:00', summary: '确认现金退款路线' }],
      channels: [{ type: 'email', status: 'draft_saved', task_ref: 'TASK-S05', content: { to: '采购联系人', subject: '关于退货及结算方式的确认', body: '请确认本次退货商品、数量、退款方式和预计结算日期。确认结果将用于后续退货验收及资金核对。', terms: '退货数量、扣费、退款金额及结算日期以供应商书面确认和验收回执为准。' } }],
    };
    return {
      metadata: { is_demo: true, source, as_of_date: '2026-10-03', replay_clock_at: '2026-10-24T20:05:00+08:00', data_version: 'retail-v2.1' },
      matters: [s01, s09, purchase, promotion, supplier],
      overview: {
        account: { balance: null, status: 'unknown', source: '未接入当前账户快照' },
        inventory: { cost: null, risk_cost: null, source: '等待后端聚合库存快照' },
        purchase_commitments: { amount: null, status: 'unknown', source: '尚无已确认付款计划' },
        pending_approvals: { count: 1, amount: null, known_amount: null, missing_count: 1 },
        stores: [{
          store_id: 'ST-001', store_name: '西湖古荡店', inventory_cost: null,
          risk_cost: null, turnover_days: null, primary_risk: null,
          work_item_id: 'CASE-S01', work_item_label: '查看跟进',
          pending_label: '待接入', missing_fields: ['inventory_cost', 'risk_cost', 'turnover_days'],
        }],
      },
    };
  }

  function renderMetric(label, value, note, modifier) {
    return '<article class="hf-metric ' + (modifier || '') + '"><span>' + escapeHTML(label) + '</span><strong>' + escapeHTML(value) + '</strong><small>' + escapeHTML(note || '') + '</small></article>';
  }
  function renderMetaLine(snapshot, view) {
    const meta = dataMeta(snapshot);
    const bits = [];
    if (meta.source) bits.push('<span>数据来源：' + escapeHTML(meta.source) + '</span>');
    const sourceRefs = Array.from(new Set(array(meta.source_refs).map((ref) => typeof ref === 'string' ? ref : (ref.source || ref.record_id)).filter(Boolean)));
    if (sourceRefs.length) bits.push('<span>依据：' + escapeHTML(sourceRefs.join('、')) + '</span>');
    const factTime = firstValue(meta.as_of_date, meta.as_of);
    if (factTime) bits.push('<span>事实时点：' + escapeHTML(String(factTime).includes('T') ? dateTime(factTime) : factTime) + '</span>');
    if (view === 'cases' && meta.replay_clock_at) bits.push('<span>回放推进至：' + escapeHTML(dateTime(meta.replay_clock_at)) + '</span>');
    return bits.length ? '<div class="hf-meta-line">' + bits.join('') + '</div>' : '';
  }
  function renderTabs(section) {
    return '<nav class="hf-section-tabs" aria-label="工作区页面">' + Object.keys(SECTION_LABELS).map((key) =>
      '<button type="button" data-hf-view="' + key + '" class="' + (section === key ? 'is-active' : '') + '" aria-current="' + (section === key ? 'page' : 'false') + '">' + SECTION_LABELS[key] + '</button>'
    ).join('') + '</nav>';
  }
  function renderGroupNav(snapshot, activeGroup) {
    return '<nav class="hf-group-nav" aria-label="事项状态分组">' + GROUPS.map((group) => {
      const count = groupItems(snapshot, group.id).length;
      return '<button type="button" data-hf-group="' + group.id + '" class="' + (activeGroup === group.id ? 'is-active' : '') + '" aria-pressed="' + (activeGroup === group.id) + '"><span>' + group.label + '</span><b>' + count + '</b></button>';
    }).join('') + '</nav>';
  }
  function renderItemRow(matter, selectedId) {
    const active = matter.id === selectedId;
    const proposal = matter.proposal || {};
    const task = matter.execution || matter.task || {};
    const status = formatGroupStatus(matter);
    const location = [proposal.source_store, proposal.target_store].filter(Boolean).join(' → ');
    const due = matter.due_at || matter.due_date;
    const summary = matter.next_step || matter.summary || location || matter.kind || '查看事项进度';
    return '<li><button type="button" class="hf-item-row ' + (active ? 'is-selected' : '') + '" data-hf-select="' + escapeHTML(matter.id) + '" aria-pressed="' + active + '">' +
      '<span class="hf-item-top"><strong>' + escapeHTML(matter.title || matter.id || '未命名事项') + '</strong><span class="hf-status hf-status-' + escapeHTML(statusTone(status)) + '">' + escapeHTML(status) + '</span></span>' +
      '<span class="hf-item-summary">' + escapeHTML(summary) + '</span>' +
      '<span class="hf-item-foot"><span>' + escapeHTML(matter.owner || '负责人待安排') + '</span><span>' + escapeHTML(due ? '截止 ' + dateTime(due) : '截止时间未知') + '</span></span>' +
      (task.version !== undefined ? '<span class="hf-item-version">任务版本 V' + escapeHTML(task.version) + '</span>' : '') +
      '</button></li>';
  }
  function statusTone(value) {
    const status = String(value || '').toLowerCase();
    if (/异常|失败|驳回|需处理/.test(status) || status === 'exception' || status === 'failed') return 'danger';
    if (/待|部分|运输/.test(status) || status === 'pending_approval') return 'warning';
    if (/已完成|已签收/.test(status) || status === 'completed') return 'good';
    return 'info';
  }
  function renderEvidence(matter) {
    const accounting = matter.accounting || (matter.result || {}).accounting || {};
    const evidence = array(matter.evidence).slice();
    if (!evidence.length) {
      array(accounting.event_refs).forEach((ref) => evidence.push({ label: '业务事件', value: ref, source: '后端核算引用' }));
      array(accounting.cash_event_ids).forEach((ref) => evidence.push({ label: '现金流水', value: ref, source: '账户流水' }));
      array(accounting.allocation_ids).forEach((ref) => evidence.push({ label: '核销分配', value: ref, source: '核算记录' }));
    }
    if (!evidence.length) return '<p class="hf-empty-note">暂无可展示的依据，等待后端返回证据记录。</p>';
    return '<ul class="hf-evidence-list">' + evidence.map((entry) => '<li><span>' + escapeHTML(entry.label || '业务依据') + '</span><b>' + escapeHTML(entry.value === null || entry.value === undefined ? '未知' : entry.value) + '</b><small>' + escapeHTML(entry.source || '来源未知') + '</small></li>').join('') + '</ul>';
  }
  function renderEvents(matter) {
    const events = array(matter.events).slice().sort(compareEventTime);
    if (!events.length) return '<div class="hf-empty-state"><strong>还没有执行记录</strong><span>保存的方案、渠道动作和业务回执会按发生时间显示在这里。</span></div>';
    return '<ol class="hf-timeline">' + events.map((event) => {
      const reality = eventReality(event);
      const actual = reality === true;
      const realityLabel = actual ? '已发生' : (reality === false ? '预计' : '状态未知');
      const realityClass = actual ? 'is-actual' : (reality === false ? 'is-expected' : 'is-unknown');
      const qtyValue = firstValue(event.quantity, event.qty);
      const amountValue = firstValue(event.amount, event.cash_amount);
      const facts = [];
      const eventUnit = firstValue(event.unit, matter.unit, (matter.proposal || {}).unit, (matter.execution || {}).unit, (matter.task || {}).unit);
      if (qtyValue !== null) facts.push('<b>' + escapeHTML(quantity(qtyValue, eventUnit)) + '</b>');
      if (amountValue !== null) facts.push('<b>' + escapeHTML(money(amountValue)) + '</b>');
      if (event.receipt_ref) facts.push('<span>回执 ' + escapeHTML(event.receipt_ref) + '</span>');
      return '<li class="hf-timeline-event ' + realityClass + '"><span class="hf-timeline-dot" aria-hidden="true"></span><div class="hf-event-body"><div class="hf-event-head"><strong>' + escapeHTML(eventText(event)) + '</strong><span>' + realityLabel + '</span></div>' +
        '<time datetime="' + escapeHTML(eventTime(event) || '') + '">' + escapeHTML(dateTime(eventTime(event))) + '</time>' +
        (event.detail ? '<p>' + escapeHTML(event.detail) + '</p>' : '') +
        (facts.length ? '<div class="hf-event-facts">' + facts.join('') + '</div>' : '') +
        '<small>来源：' + escapeHTML(event.source || '来源未知') + (event.actor_name || event.actor_id ? ' · 处理人：' + escapeHTML(event.actor_name || event.actor_id) : '') + (event.known_at ? ' · 可知时间 ' + escapeHTML(dateTime(event.known_at)) : '') + '</small></div></li>';
    }).join('') + '</ol>';
  }
  function resultLine(label, value, note) {
    return '<div class="hf-result-line"><span>' + escapeHTML(label) + '</span><strong>' + escapeHTML(value) + '</strong>' + (note ? '<small>' + escapeHTML(note) + '</small>' : '') + '</div>';
  }
  function renderCaseSummary(matter, snapshot) {
    const totals = aggregateMatter(matter);
    const proposal = matter.proposal || {};
    const source = proposal.source_store || '未知';
    const target = proposal.target_store || '未知';
    const qtyText = quantity(totals.plannedQty, totals.unit);
    const shipped = quantity(totals.dispatchedQty, totals.unit);
    const received = quantity(totals.receivedQty, totals.unit);
    const sold = quantity(totals.soldQty, totals.unit);
    const remaining = quantity(totals.remainingInventoryQty, totals.unit);
    const cashInNote = totals.expectedCashIn === null ? '预计到账金额未知' : '预计 ' + money(totals.expectedCashIn);
    const cashOutNote = totals.expectedCashOut === null ? '预计支付金额未知' : '预计 ' + money(totals.expectedCashOut);
    const result = matter.result || {};
    const noCashSettlement = result.cash_required === false || proposal.cash_required === false || result.settlement_method === 'exchange' || proposal.settlement_method === 'exchange';
    const cashStatusParts = [];
    if (noCashSettlement) cashStatusParts.push('无需现金结算');
    else {
      if (totals.expectedCashIn > 0) {
        if (totals.actualCash === null) cashStatusParts.push('待核对到账');
        else if (totals.outstandingCashIn > 0) cashStatusParts.push('待到账 ' + money(totals.outstandingCashIn));
        else cashStatusParts.push('到账金额已核对');
      }
      if (totals.expectedCashOut > 0) {
        if (totals.actualCashOut === null) cashStatusParts.push('待核对支付');
        else if (totals.outstandingCashOut > 0) cashStatusParts.push('待支付 ' + money(totals.outstandingCashOut));
        else cashStatusParts.push('支付金额已核对');
      }
      if (totals.expectedCashUnclassified > 0) cashStatusParts.push('预计现金方向待核对 ' + money(totals.expectedCashUnclassified));
      if (!cashStatusParts.length) cashStatusParts.push('收付款状态未知');
    }
    const cashStatus = cashStatusParts.join(' · ');
    const cashPending = totals.expectedCashIn > 0 && (totals.actualCash === null || totals.outstandingCashIn > 0)
      || totals.expectedCashOut > 0 && (totals.actualCashOut === null || totals.outstandingCashOut > 0)
      || totals.expectedCashUnclassified > 0;
    const meta = { ...dataMeta(snapshot), ...dataMeta(matter) };
    const hasReplayEvents = array(matter.events).some((event) => eventIs(new Set(['sale', 'cash_receipt', 'cash_in', 'stock_balance', 'inventory_balance']), event) && isActual(event));
    const sourceLabel = hasReplayEvents && meta.replay_clock_at ? '历史回放' : ((matter.is_demo || meta.is_demo) ? '合成数据' : '业务记录');
    const route = proposal.source_store || proposal.target_store
      ? '<p class="hf-route-line"><span>' + escapeHTML(source) + '</span><i aria-hidden="true">→</i><span>' + escapeHTML(target) + '</span><b>' + escapeHTML(qtyText) + '</b></p>'
      : '<p class="hf-route-line"><span>业务动作</span><i aria-hidden="true">·</i><span>' + escapeHTML(proposal.action || matter.action_label || matter.kind || '事项处理') + '</span><b>' + escapeHTML(qtyText) + '</b></p>';
    return '<section class="hf-case-summary" aria-labelledby="hf-case-result-title"><div class="hf-case-title"><div><p>资金结果与案例</p><h3 id="hf-case-result-title">' + escapeHTML(matter.title || '当前事项结果') + '</h3></div><span class="hf-source-tag">' + escapeHTML(sourceLabel) + '</span></div>' +
      route +
      '<div class="hf-result-grid">' +
      resultLine('已发货', shipped, '实际执行记录') + resultLine('已签收', received, '签收不代表销售') +
      resultLine('已售出', sold, '销售明细') + resultLine('销售金额', money(totals.salesAmount), '销售明细；不等于现金到账') + resultLine('现金到账', money(totals.actualCash), cashInNote) +
      resultLine('现金已支付', money(totals.actualCashOut), cashOutNote) + resultLine('其中费用', money(totals.actualFees), '仅统计已记账费用') + resultLine('剩余库存', remaining, '按最新库存事件汇总') +
      '</div><div class="hf-outstanding ' + (cashPending ? 'is-pending' : '') + '"><span>' + escapeHTML(cashStatus) + '</span><small>计划数量 ' + escapeHTML(qtyText) + '；执行、销售、收款和支付分别核对。贡献金额不等于增量利润。</small></div>' +
      '<details class="hf-evidence-details"><summary>查看计算与数据依据</summary>' + renderEvidence(matter) +
      '<p class="hf-result-source">来源：' + escapeHTML(matter.source || meta.source || '来源未知') + (meta.replay_clock_at ? ' · 回放推进至 ' + escapeHTML(dateTime(meta.replay_clock_at)) : '') + '</p></details></section>';
  }
  function renderReceiptForm(matter, actionEnabled) {
    const task = matter.execution || matter.task || {};
    if (!task.id && !task.task_id && !matter.execution_task_id) return '';
    if (mapFollowupDisplay(task, matter.accounting || {}).execution_display_status === '已完成' || ['cancelled', 'canceled', 'archived'].includes(String(task.status || '').toLowerCase()) || matter.closed === true) return '<div class="hf-closed-note">执行阶段已归档；销售与到账仍按独立业务记录展示。</div>';
    const enabled = actionEnabled ? '' : ' disabled';
    const hint = actionEnabled ? '保存后会生成带任务版本与来源的业务事件，并重新读取最新记录。' : '业务事件接口尚未接入，当前不可保存。';
    return '<form class="hf-receipt-form" data-hf-form="receipt"><div class="hf-form-heading"><div><h4>回填执行回执</h4><p>' + hint + '</p></div><span>任务 V' + escapeHTML(task.version === undefined ? '未知' : task.version) + '</span></div>' +
      '<div class="hf-form-grid"><label>回执编号<input name="receipt_ref" required maxlength="120" autocomplete="off" placeholder="填写门店或供应商回执编号"' + enabled + '></label>' +
      '<label>回执类型<select name="event_type"' + enabled + '><option value="receipt">签收</option><option value="dispatch">发货</option></select></label>' +
      '<label>本次数量（' + escapeHTML(task.base_unit || task.unit || '单位未知') + '）<input name="quantity" type="number" min="0" step="1" inputmode="numeric" required placeholder="填写本次回执数量"' + enabled + '></label>' +
      '<label>业务发生时间<input name="occurred_at" type="datetime-local" required' + enabled + '></label>' +
      '<label class="hf-form-wide">处理说明<textarea name="note" rows="2" maxlength="1000" placeholder="说明签收数量、异常或待办"' + enabled + '></textarea></label></div>' +
      '<div class="hf-form-actions"><button type="button" class="hf-button hf-button-primary" data-hf-command="record_receipt"' + enabled + '>保存回执</button><small>签收只写入执行凭据，不自动标记销售或到账。</small></div></form>';
  }
  function renderVersions(matter) {
    const proposal = matter.proposal || {};
    const versions = array(matter.versions || proposal.versions);
    if (!versions.length) return '<div class="hf-empty-state"><strong>暂未返回方案版本</strong><span>版本历史由后端恢复；这里不从浏览器本地缓存补造。</span></div>';
    return '<ol class="hf-version-list">' + versions.map((version) => '<li><span class="hf-version-mark">V' + escapeHTML(version.version) + '</span><div><strong>' + escapeHTML(statusText(version.status)) + '</strong><p>' + escapeHTML(version.summary || version.reason || '未提供版本摘要') + '</p><small>' + escapeHTML(dateTime(version.created_at || version.updated_at)) + '</small></div>' +
      (version.invalid_reason ? '<em>' + escapeHTML(version.invalid_reason) + '</em>' : '') + '</li>').join('') + '</ol>';
  }
  function channelList(matter) { return array(matter.channels || matter.channel_actions); }
  function findChannel(matter, type) { return channelList(matter).find((channel) => normalizeChannelType(channel.type || channel.channel) === type) || null; }
  function channelContent(matter, type) {
    const channel = findChannel(matter, type);
    const task = matter && (matter.execution || matter.task) || {};
    const proposal = matter && matter.proposal || {};
    return {
      ...(task.channel_content || proposal.channel_content || proposal.content_snapshot || {}),
      ...(channel && (channel.content || channel.content_snapshot || channel.snapshot) || {}),
    };
  }
  function normalizeChannelType(value) {
    const type = String(value || '').toLowerCase();
    if (type === 'feishu' || type.includes('飞书') || type.includes('采购')) return 'feishu';
    if (type === 'wecom' || type === 'wechat_work' || type.includes('企微') || type.includes('促销')) return 'wecom';
    if (type === 'email' || type.includes('邮箱') || type.includes('退供')) return 'email';
    return type;
  }
  function field(label, value) { return '<div class="hf-channel-field"><span>' + escapeHTML(label) + '</span><b>' + escapeHTML(value === null || value === undefined || value === '' ? '未知' : value) + '</b></div>'; }
  function formValue(form, name) {
    const element = form && form.elements ? form.elements.namedItem(name) : null;
    return element ? element.value : '';
  }
  function renderChannelActions(matter, apiAvailable, preview) {
    const proposal = matter.proposal || {};
    const task = matter.execution || matter.task || {};
    const kind = normalizeChannelType(matter.kind || matter.action_type || proposal.action_type || proposal.action || '');
    let channel = null;
    if (kind.includes('promotion') || kind.includes('promot') || kind.includes('促销')) channel = findChannel(matter, 'wecom');
    else if (kind.includes('supplier') || kind.includes('return') || kind.includes('退供')) channel = findChannel(matter, 'email');
    else if (kind.includes('procurement') || kind.includes('purchase') || kind.includes('采购')) channel = findChannel(matter, 'feishu');
    if (!channel) channel = channelList(matter)[0] || null;
    if (!channel && (kind.includes('promotion') || kind.includes('promot') || kind.includes('促销'))) channel = { type: 'wecom', status: 'not_recorded', content: task.channel_content || proposal.channel_content || proposal.content_snapshot || {} };
    if (!channel && (kind.includes('supplier') || kind.includes('return') || kind.includes('退供'))) channel = { type: 'email', status: 'not_recorded', content: task.channel_content || proposal.channel_content || proposal.content_snapshot || {} };
    if (!channel && (kind.includes('procurement') || kind.includes('purchase') || kind.includes('采购'))) channel = { type: 'feishu', status: 'not_recorded', content: task.channel_content || proposal.channel_content || proposal.content_snapshot || {} };
    if (!channel) return '<div class="hf-empty-state"><strong>尚无已保存的渠道动作</strong><span>渠道任务会在后端保存后显示在这里。</span></div>';
    const type = normalizeChannelType(channel.type || channel.channel);
    const content = channelContent(matter, type);
    const disabled = apiAvailable && !preview ? '' : ' disabled';
    const blockedCopy = preview ? '<p class="hf-preview-readonly">预览数据只读，操作不会写入业务记录。</p>' : (!apiAvailable ? '<p class="hf-preview-readonly">渠道动作接口尚未接入，操作不会被保存。</p>' : '');
    const status = '<span class="hf-status hf-status-' + escapeHTML(statusTone(channel.status)) + '">' + escapeHTML(statusText(channel.status)) + '</span>';
    if (type === 'feishu') {
      return '<section class="hf-channel-card"><div class="hf-channel-head"><div><p>飞书采购任务</p><h4>' + escapeHTML(content.title || '采购任务') + '</h4></div>' + status + '</div>' +
        '<div class="hf-channel-fields">' + field('负责人', content.owner || matter.owner) + field('截止时间', content.due_at || matter.due_at || matter.due_date) +
        field('原计划数量', quantity(content.original_qty, content.unit || proposal.unit)) + field('建议数量', quantity(content.proposed_qty || proposal.planned_qty, content.unit || proposal.unit)) + '</div>' +
        '<p class="hf-channel-copy">' + escapeHTML(content.reason || content.body || '暂无已保存的任务说明') + '</p>' + blockedCopy +
        '<div class="hf-action-row"><button type="button" class="hf-button hf-button-secondary" data-hf-command="feishu_send_notification"' + disabled + '>发送通知</button>' +
        '<button type="button" class="hf-button hf-button-secondary" data-hf-command="feishu_take_over"' + disabled + '>确认接手</button></div>' +
        '<form class="hf-channel-form" data-hf-form="feishu-result"><label>订单／执行结果<textarea name="result" rows="3" maxlength="1000" placeholder="填写实际订单号、数量和交期"' + disabled + '></textarea></label><button type="button" class="hf-button hf-button-primary" data-hf-command="feishu_submit_result"' + disabled + '>提交结果</button></form>' +
        '<form class="hf-channel-form hf-exception-form" data-hf-form="feishu-exception"><label>异常情况<textarea name="reason" rows="2" maxlength="1000" placeholder="填写数量不符、供应中断等客观情况"' + disabled + '></textarea></label><div class="hf-form-grid"><label>异常凭据<input name="receipt_ref" maxlength="120" placeholder="记录编号或凭据"' + disabled + '></label><label>发生时间<input name="occurred_at" type="datetime-local"' + disabled + '></label><label>影响数量（' + escapeHTML(task.base_unit || task.unit || proposal.unit || '单位未知') + '）<input name="quantity" type="number" min="0" step="1"' + disabled + '></label></div><button type="button" class="hf-button hf-button-danger" data-hf-command="feishu_report_exception"' + disabled + '>上报异常</button></form>' +
        '<small class="hf-channel-state">渠道进度：' + escapeHTML(statusText(channel.status)) + ' · 业务执行进度：' + escapeHTML(formatGroupStatus(matter)) + '</small></section>';
    }
    if (type === 'wecom') {
      const imageUrl = safeAssetUrl(content.image_url || content.asset_url);
      const stages = array(content.price_stages).map((stage) => '<li>' + escapeHTML(stage.label || '价格阶段') + '：' + escapeHTML(money(stage.price)) + '</li>').join('');
      return '<section class="hf-channel-card"><div class="hf-channel-head"><div><p>企业微信促销任务</p><h4>' + escapeHTML(content.title || '促销素材预览') + '</h4></div>' + status + '</div>' +
        '<div class="hf-promotion-preview">' + (imageUrl ? '<img src="' + escapeHTML(imageUrl) + '" alt="促销商品素材" loading="lazy">' : '') + '<div><p>' + escapeHTML(content.body || '尚无已保存的促销文案') + '</p>' + (stages ? '<ul>' + stages + '</ul>' : '') +
        '<small>活动时间：' + escapeHTML(content.start_at || '未知') + ' 至 ' + escapeHTML(content.end_at || '未知') + '</small></div></div>' + blockedCopy +
        '<div class="hf-action-row"><button type="button" class="hf-button hf-button-primary" data-hf-command="wecom_publish"' + disabled + '>发布促销内容</button></div>' +
        '<form class="hf-channel-form" data-hf-form="price-effective"><div class="hf-form-grid"><label>生效凭据<input name="receipt_ref" maxlength="120" placeholder="门店确认或价格记录编号"' + disabled + '></label><label>生效时间<input name="occurred_at" type="datetime-local"' + disabled + '></label><label>适用数量（' + escapeHTML(task.base_unit || task.unit || proposal.unit || '单位未知') + '）<input name="quantity" type="number" min="0" step="1"' + disabled + '></label></div><button type="button" class="hf-button hf-button-secondary" data-hf-command="wecom_record_price_effective"' + disabled + '>登记价格生效</button></form>' +
        '<small class="hf-channel-state">发布状态与价格生效状态分开保存，促销发布不代表商品已售出。</small></section>';
    }
    if (type === 'email') {
      return '<section class="hf-channel-card"><div class="hf-channel-head"><div><p>邮箱退供协商</p><h4>供应商沟通记录</h4></div>' + status + '</div>' +
        '<form class="hf-email-form" data-hf-form="email"><div class="hf-form-grid"><label>收件人<input name="to" maxlength="200" value="' + escapeHTML(content.to || '') + '" placeholder="供应商联系人"' + disabled + '></label>' +
        '<label>主题<input name="subject" maxlength="200" value="' + escapeHTML(content.subject || '') + '" placeholder="退货与结算确认"' + disabled + '></label>' +
        '<label class="hf-form-wide">邮件正文<textarea name="body" rows="5" maxlength="4000" placeholder="填写退货商品、数量及拟确认条款"' + disabled + '>' + escapeHTML(content.body || '') + '</textarea></label>' +
        '<label class="hf-form-wide">拟确认条款<textarea name="terms" rows="3" maxlength="2000" placeholder="条款需由供应商回复并经人工确认"' + disabled + '>' + escapeHTML(content.terms || '') + '</textarea></label>' +
        '<label>条款确认凭据<input name="terms_receipt_ref" maxlength="120" placeholder="供应商邮件编号或确认记录"' + disabled + '></label><label>条款确认时间<input name="terms_occurred_at" type="datetime-local"' + disabled + '></label><label>确认数量（' + escapeHTML(task.base_unit || task.unit || proposal.unit || '单位未知') + '）<input name="terms_quantity" type="number" min="0" step="1"' + disabled + '></label></div></form>' + blockedCopy +
        '<div class="hf-action-row"><button type="button" class="hf-button hf-button-secondary" data-hf-command="email_save_draft"' + disabled + '>保存草稿</button><button type="button" class="hf-button hf-button-primary" data-hf-command="email_send"' + disabled + '>发送邮件</button></div>' +
      '<form class="hf-channel-form" data-hf-form="supplier-reply"><label>供应商回复<textarea name="reply" rows="3" maxlength="2000" placeholder="录入供应商原文回复"' + disabled + '></textarea></label><div class="hf-form-grid"><label>回复凭据编号<input name="receipt_ref" maxlength="120" placeholder="邮件编号或回复凭据"' + disabled + '></label><label>回复发生时间<input name="occurred_at" type="datetime-local"' + disabled + '></label><label>回复数量（' + escapeHTML(task.base_unit || task.unit || proposal.unit || '单位未知') + '）<input name="quantity" type="number" min="0" step="1"' + disabled + '></label></div><button type="button" class="hf-button hf-button-secondary" data-hf-command="email_record_supplier_reply"' + disabled + '>记录回复</button></form>' +
        '<div class="hf-channel-terms"><p>' + escapeHTML(channel.terms_status ? statusText(channel.terms_status) : '条款待确认') + '</p><button type="button" class="hf-button hf-button-secondary" data-hf-command="email_confirm_terms"' + disabled + '>确认协商条款</button></div>' +
        '<small class="hf-channel-state">邮件状态：' + escapeHTML(statusText(channel.status)) + ' · 供应商回复与条款确认独立记录</small></section>';
    }
    return '<div class="hf-empty-state"><strong>渠道类型未知</strong><span>后端返回渠道标识后再展示对应操作。</span></div>';
  }
  function commandPayload(command, form) {
    const value = (key) => formValue(form, key).trim();
    const payload = {};
    if (command === 'record_receipt') {
      payload.receipt_ref = value('receipt_ref'); payload.event_type = value('event_type') || 'receipt'; payload.note = value('note');
      payload.quantity = value('quantity') === '' ? null : Number(value('quantity'));
      payload.occurred_at = value('occurred_at');
    } else if (command === 'feishu_submit_result') payload.result = value('result');
    else if (command === 'feishu_report_exception') { payload.reason = value('reason'); payload.receipt_ref = value('receipt_ref'); payload.occurred_at = value('occurred_at'); payload.quantity = value('quantity') === '' ? null : Number(value('quantity')); }
    else if (command === 'wecom_record_price_effective') { payload.receipt_ref = value('receipt_ref'); payload.occurred_at = value('occurred_at'); payload.quantity = value('quantity') === '' ? null : Number(value('quantity')); }
    else if (command === 'email_save_draft' || command === 'email_send') {
      payload.to = value('to'); payload.subject = value('subject'); payload.body = value('body'); payload.terms = value('terms');
    } else if (command === 'email_record_supplier_reply') { payload.reply = value('reply'); payload.receipt_ref = value('receipt_ref'); payload.occurred_at = value('occurred_at'); payload.quantity = value('quantity') === '' ? null : Number(value('quantity')); }
    else if (command === 'email_confirm_terms') payload.confirmed = true;
    if (CHANNEL_COMMANDS.has(command)) { payload.is_demo = true; payload.external_write = false; }
    return payload;
  }
  function renderDetail(matter, activeTab, apiAvailable, preview, navigationAvailable, snapshot) {
    if (!matter) return '<section class="hf-empty-state hf-detail-empty"><strong>当前分组没有事项</strong><span>事项进入该状态后，会显示负责人、截止时间、下一步和业务记录。</span></section>';
    const proposal = matter.proposal || {};
    const task = matter.execution || matter.task || {};
    const projection = mapFollowupDisplay(task, accountingForDisplay(matter));
    const tabs = [ ['timeline', '执行与结果'], ['channels', '渠道动作'], ['versions', '方案版本'] ];
    const selectedTab = tabs.some((entry) => entry[0] === activeTab) ? activeTab : 'timeline';
    const due = matter.due_at || matter.due_date;
    const exceptionText = matter.exception && (typeof matter.exception === 'string' ? matter.exception : (matter.exception.message || matter.exception.reason)) || task.exception || projection.exception || array(matter.exceptions).find((entry) => entry && entry.status !== 'resolved' && entry.status !== 'closed');
    const exception = typeof exceptionText === 'object' ? exceptionText.reason || exceptionText.message : (exceptionText || (projection.needs_attention || ['exception', 'failed', 'rejected'].includes(String(matter.status || '').toLowerCase()) ? '任务当前标记为异常或失败，需核对后端返回的处理记录。' : null));
    let body = '';
    if (selectedTab === 'timeline') {
      body = '<div class="hf-execution-strip"><div><span>方案</span><b>V' + escapeHTML(proposal.version || proposal.current_version || '未知') + ' · ' + escapeHTML(statusText(proposal.status)) + '</b></div><div><span>执行 · 原始状态 ' + escapeHTML(projection.raw_execution_status) + '</span><b>' + escapeHTML(projection.execution_display_status) + (projection.planned_qty !== null ? ' · 已完成 ' + escapeHTML(quantity(projection.completed_qty, task.base_unit || task.unit || proposal.unit)) + ' / ' + escapeHTML(quantity(projection.planned_qty, task.base_unit || task.unit || proposal.unit)) : '') + '</b></div><div><span>核算</span><b>' + escapeHTML(projection.accounting_display_status) + '</b></div></div>' +
        (exception ? '<aside class="hf-exception"><strong>需处理异常</strong><p>' + escapeHTML(exception) + '</p><span>负责人：' + escapeHTML(matter.owner || '待安排') + ' · 下一步：' + escapeHTML(matter.next_step || '等待处理') + '</span></aside>' : '') +
        (projection.closed_reason ? '<aside class="hf-closed-note"><strong>关闭原因</strong> · ' + escapeHTML(projection.closed_reason) + '</aside>' : '') +
        renderCaseSummary(matter, snapshot) + '<section class="hf-section-block"><div class="hf-section-heading"><div><h3>业务时间线</h3><p>发货、签收、销售和现金流水各自依据对应记录。</p></div><button type="button" class="hf-button hf-button-tertiary" data-hf-refresh="true">刷新记录</button></div>' + renderEvents(matter) + '</section>' + renderReceiptForm(matter, apiAvailable && !preview);
    } else if (selectedTab === 'channels') {
      body = '<section class="hf-section-block"><div class="hf-section-heading"><div><h3>渠道动作</h3><p>渠道状态与业务状态分开记录。</p></div></div>' + renderChannelActions(matter, apiAvailable, preview) + '</section>';
    } else {
      body = '<section class="hf-section-block"><div class="hf-section-heading"><div><h3>方案历史</h3><p>当前方案 V' + escapeHTML(proposal.version || proposal.current_version || '未知') + ' · 执行任务 ' + escapeHTML(task.id || task.task_id || matter.execution_task_id || '尚未生成') + '</p></div></div>' + renderVersions(matter) + '</section>';
    }
    const matterId = matter.id || matter.case_id || '';
    return '<article class="hf-detail"><header class="hf-detail-header"><div><div class="hf-detail-kicker"><span>' + escapeHTML(matter.case_id || matter.id || '经营事项') + '</span>' + (proposal.version ? '<span>方案 V' + escapeHTML(proposal.version) + '</span>' : '') + '</div><h2>' + escapeHTML(matter.title || matterId || '未命名事项') + '</h2><p>' + escapeHTML(matter.summary || proposal.reason || '查看当前事项的执行、证据与资金进度。') + '</p></div><span class="hf-status hf-status-' + escapeHTML(statusTone(formatGroupStatus(matter))) + '">' + escapeHTML(formatGroupStatus(matter)) + '</span></header>' +
      '<div class="hf-owner-row"><span class="hf-avatar" aria-hidden="true">' + escapeHTML((matter.owner || '待').slice(0, 1)) + '</span><span><b>' + escapeHTML(matter.owner || '负责人待安排') + '</b><small>' + escapeHTML(due ? '截止 ' + dateTime(due) : '截止时间未知') + '</small></span><span class="hf-next-step"><small>下一步</small><b>' + escapeHTML(matter.next_step || (classifyMatter(matter) === 'approvals' ? '查看内容后一次确认并安排执行' : '等待后端返回下一步')) + '</b></span></div>' +
      (classifyMatter(matter) === 'suggestions' ? '<div class="hf-suggestion-callout"><div><strong>建议待评估</strong><p>先查看风险事实与可行方案；保存后再进入待确认分组。</p></div><button type="button" class="hf-button hf-button-secondary" data-hf-navigate-decision="true"' + (navigationAvailable ? '' : ' disabled') + '>查看风险与方案</button></div>' : '') +
      (classifyMatter(matter) === 'approvals' ? '<div class="hf-approval-callout"><div><strong>方案已保存，尚未确认</strong><p>确认后将按当前版本安排执行任务；不会要求管理员再审批自己发起的方案。</p>' + (preview ? '<small>预览数据只读，操作不会写入业务记录。</small>' : (!apiAvailable ? '<small>确认与安排接口尚未接入，操作未保存。</small>' : '')) + '</div><button type="button" class="hf-button hf-button-primary" data-hf-command="confirm_and_arrange"' + (apiAvailable && !preview ? '' : ' disabled') + '>' + actionLabel('confirm_and_arrange') + '</button></div>' : '') +
      '<nav class="hf-detail-tabs" aria-label="事项详情">' + tabs.map((tab) => '<button type="button" data-hf-detail-tab="' + tab[0] + '" class="' + (selectedTab === tab[0] ? 'is-active' : '') + '" aria-pressed="' + (selectedTab === tab[0]) + '">' + tab[1] + '</button>').join('') + '</nav>' + body + '</article>';
  }
  function renderWorkbench(state) {
    const snapshot = state.snapshot;
    const list = groupItems(snapshot, state.group);
    const selected = list.find((matter) => (matter.id || matter.case_id) === state.selectedId || matter.task_id === state.selectedId) || list[0] || null;
    const selectedId = selected ? selected.id || selected.case_id : null;
    state.selectedId = selectedId;
    const group = GROUPS.find((entry) => entry.id === state.group) || GROUPS[0];
    return '<section class="hf-workbench"><div class="hf-workbench-intro"><div><p class="hf-kicker">跟进记录</p><h1>今日工作台</h1><p>事项按当前状态互斥归组。已签收事项仍留在跟进，直到销售、结算与异常都完成核对。</p></div><button type="button" class="hf-button hf-button-secondary" data-hf-refresh="true">刷新数据</button></div>' +
      renderGroupNav(snapshot, group.id) + '<div class="hf-workspace-grid"><aside class="hf-item-list"><div class="hf-list-heading"><div><h2>' + group.label + '</h2><small>' + list.length + ' 件事项</small></div></div>' +
      (list.length ? '<ul>' + list.map((matter) => renderItemRow(matter, selectedId)).join('') + '</ul>' : '<div class="hf-empty-state hf-list-empty"><strong>这个分组目前为空</strong><span>已保存事项会按最新业务状态自动归组。</span></div>') + '</aside>' +
      '<div class="hf-detail-wrap">' + renderDetail(selected, selected ? state.detailTabs[selected.id || selected.case_id] : 'timeline', !!(state.api && typeof state.api.recordBusinessEvents === 'function'), state.preview, !!state.navigate, snapshot) + '</div></div></section>';
  }
  function overviewMetric(root, label, note) {
    const value = firstValue(root && root.value, root && root.amount, root && root.balance, root && root.cost);
    return renderMetric(label, value === null ? '未知' : money(value), (root && root.source) || note, 'hf-money-metric');
  }
  function renderOverview(snapshot) {
    const overview = snapshot.overview || {};
    const account = overview.account || {};
    const inventory = overview.inventory || {};
    const commitments = overview.purchase_commitments || overview.confirmed_purchase_commitments || {};
    const stores = array(overview.stores);
    const table = stores.length ? '<div class="hf-table-scroll"><table class="hf-store-table"><thead><tr><th>门店</th><th>库存占用成本</th><th>待关注库存成本</th><th>周转天数</th><th>主要风险</th><th>待处理事项</th></tr></thead><tbody>' + stores.map((store) => {
      const link = store.work_item_id || store.matter_id;
      return '<tr><th scope="row">' + escapeHTML(store.store_name || store.name || store.store_id || '未知门店') + '</th><td>' + escapeHTML(money(firstValue(store.inventory_cost, store.cost))) + '</td><td>' + escapeHTML(money(store.risk_cost)) + '</td><td>' + escapeHTML(finite(store.turnover_days) ? store.turnover_days + ' 天' : '未知') + '</td><td>' + escapeHTML(store.primary_risk || '未知') + '</td><td>' + (link ? '<button type="button" class="hf-text-button" data-hf-open-matter="' + escapeHTML(link) + '">' + escapeHTML(store.work_item_label || '查看事项') + '</button>' : escapeHTML(store.pending_label || '未知')) + '</td></tr>';
    }).join('') + '</tbody></table></div>' : '<div class="hf-empty-state"><strong>门店库存资金表尚未加载</strong><span>后端完成统一聚合后，门店成本、风险与待办会在这里显示。</span></div>';
    const meta = dataMeta(snapshot);
    return '<section class="hf-overview"><div class="hf-workbench-intro"><div><p class="hf-kicker">同一事项聚合</p><h1>经营总览</h1><p>资金、库存和已确认付款使用后端返回的同一份聚合结果；未知字段保持未知。</p></div></div>' +
      renderMetaLine(snapshot, 'overview') + '<div class="hf-overview-metrics">' +
      overviewMetric(account, '账户可用资金', '未接入账户余额') +
      overviewMetric(inventory, '库存占用资金', '按进货成本计算') +
      renderMetric('待关注库存成本', money(inventory.risk_cost), inventory.source || '风险库存成本') +
      overviewMetric(commitments, '未来 30 天已确认采购付款', '仅统计已确认付款计划') +
      '</div><section class="hf-section-block hf-store-section"><div class="hf-section-heading"><div><h2>门店库存资金状况</h2><p>库存金额按成本；周转天数缺数据时显示未知。</p></div></div>' + table + '</section>' +
      '<p class="hf-overview-footnote">' + escapeHTML(meta.source || '总览来源待接入') + (meta.as_of_date ? ' · 统计日期 ' + escapeHTML(meta.as_of_date) : '') + '</p></section>';
  }
  function renderCases(snapshot, selectedId) {
    const matters = array(snapshot.matters || snapshot.items || snapshot.work_items).filter((matter) => array(matter.events).length || matter.case_id);
    const selected = matters.find((matter) => (matter.id || matter.case_id) === selectedId || matter.task_id === selectedId) || matters[0] || null;
    return '<section class="hf-cases"><div class="hf-workbench-intro"><div><p class="hf-kicker">来自业务事件</p><h1>案例复盘</h1><p>案例摘要由方案、库存变化、销售明细和现金流水组成，不读取独立手写结论。</p></div></div>' +
      renderMetaLine(snapshot, 'cases') + (matters.length ? '<div class="hf-case-layout"><nav class="hf-case-list" aria-label="选择案例">' + matters.map((matter) => '<button type="button" data-hf-case="' + escapeHTML(matter.id || matter.case_id) + '" class="' + (selected && (matter.id || matter.case_id) === (selected.id || selected.case_id) ? 'is-selected' : '') + '"><strong>' + escapeHTML(matter.title || matter.case_id) + '</strong><small>' + escapeHTML(matter.case_id || matter.id) + '</small></button>').join('') + '</nav><div class="hf-case-detail">' + (selected ? renderCaseSummary(selected, snapshot) + '<section class="hf-section-block"><div class="hf-section-heading"><div><h3>关联业务事件</h3><p>各笔金额和数量可回到对应记录。</p></div></div>' + renderEvents(selected) + '</section>' : '') + '</div></div>' : '<div class="hf-empty-state"><strong>暂无可复盘案例</strong><span>案例会在后端按事项、方案版本及回放事件生成。</span></div>') + '</section>';
  }
  function renderLoading(message, isError) {
    return '<section class="hf-load-state ' + (isError ? 'is-error' : '') + '" role="' + (isError ? 'alert' : 'status') + '"><span class="hf-load-mark" aria-hidden="true">' + (isError ? '!' : '…') + '</span><strong>' + (isError ? '跟进记录暂时无法读取' : '正在读取跟进记录') + '</strong><p>' + escapeHTML(message || (isError ? '检查连接后重试。' : '请稍候。')) + '</p>' + (isError ? '<button type="button" class="hf-button hf-button-secondary" data-hf-retry="true">重试</button>' : '') + '</section>';
  }
  function render(state) {
    if (state.loading || !state.snapshot) return '<div class="hf-app" data-hackathon-followup>' + renderLoading(state.error || '', !!state.error) + '</div>';
    const view = SECTION_LABELS[state.view] ? state.view : 'workbench';
    let content = view === 'overview' ? renderOverview(state.snapshot) : (view === 'cases' ? renderCases(state.snapshot, state.caseId) : renderWorkbench(state));
    const refreshState = state.error
      ? '<div class="hf-inline-alert" role="alert"><span>最新进度未读取：' + escapeHTML(state.error) + '</span><button type="button" data-hf-retry="true">重试</button></div>'
      : (state.loading ? '<div class="hf-inline-loading" role="status">正在读取最新记录…</div>' : '');
    const developerPreview = state.preview || (state.api && state.api.mode === 'fixture');
    const previewLabel = state.preview ? '开发预览 · 只读 fixture（非服务端）' : '开发预览 · fixture（非服务端）';
    return '<div class="hf-app" data-hackathon-followup><header class="hf-app-header"><div class="hf-brand"><span class="hf-brand-mark" aria-hidden="true">货</span><div><strong>货不压钱</strong><small>库存资金工作台</small></div>' + (developerPreview ? '<span class="hf-preview-badge">' + previewLabel + '</span>' : '') + '</div>' +
      renderTabs(view) + '<button type="button" class="hf-button hf-button-back" data-hf-return="true">返回</button></header>' +
      refreshState + renderMetaLine(state.snapshot, view) + '<main class="hf-main">' + content + '</main>' +
      '<div class="hf-notice" role="status" aria-live="polite" data-hf-notice ' + (state.notice ? '' : 'hidden') + '>' + escapeHTML(state.notice || '') + '</div></div>';
  }
  function randomKey() {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
    return 'hf-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 12);
  }
  function requiredMissing(command, payload) {
    if (command === 'record_receipt' && !String(payload.receipt_ref || '').trim()) return '请填写回执编号后再保存。';
    if (command === 'record_receipt' && (!Number.isInteger(payload.quantity) || payload.quantity < 0)) return '本次数量必须是非负整数。';
    if (command === 'record_receipt' && !payload.occurred_at) return '请填写业务发生时间。';
    if (command === 'feishu_submit_result' && !String(payload.result || '').trim()) return '请填写采购或执行结果后再提交。';
    if (command === 'feishu_report_exception' && !String(payload.reason || '').trim()) return '请填写客观异常情况后再上报。';
    if (command === 'feishu_report_exception' && (!String(payload.receipt_ref || '').trim() || !payload.occurred_at || !Number.isInteger(payload.quantity) || payload.quantity < 0)) return '请补全异常凭据、发生时间和影响数量。';
    if (command === 'wecom_record_price_effective' && (!String(payload.receipt_ref || '').trim() || !payload.occurred_at || !Number.isInteger(payload.quantity) || payload.quantity < 0)) return '请补全价格生效凭据、时间和适用数量。';
    if (command === 'email_send' && (!String(payload.to || '').trim() || !String(payload.subject || '').trim() || !String(payload.body || '').trim())) return '请补全收件人、主题和邮件正文后再发送。';
    if (command === 'email_record_supplier_reply' && !String(payload.reply || '').trim()) return '请填写供应商回复原文后再记录。';
    if (['email_record_supplier_reply', 'email_confirm_terms'].includes(command) && !String(payload.receipt_ref || '').trim()) return '请填写邮件编号或回复凭据后再记录。';
    if (['email_record_supplier_reply', 'email_confirm_terms'].includes(command) && !payload.occurred_at) return '请填写供应商回复或条款确认的发生时间。';
    if (['email_record_supplier_reply', 'email_confirm_terms'].includes(command) && (!Number.isInteger(payload.quantity) || payload.quantity < 0)) return '请填写本次协商确认的数量。';
    if (command === 'email_confirm_terms' && !String(payload.terms || '').trim()) return '请先补全待确认条款。';
    if (command === 'wecom_publish' && (!String(payload.title || '').trim() || !String(payload.body || '').trim())) return '已批准方案尚未提供可发布的促销标题或文案。';
    return '';
  }
  function unwrap(response) {
    if (response && response.data !== undefined) return response.data;
    return response;
  }
  function rowsFrom(response) {
    const data = unwrap(response) || {};
    if (Array.isArray(data)) return data;
    for (const key of ['tasks', 'proposals', 'items', 'matters', 'work_items', 'results']) {
      if (Array.isArray(data[key])) return data[key];
    }
    return [];
  }
  function normalizeApiEvent(event) {
    const row = event || {};
    return {
      ...row,
      kind: row.kind || row.event_type || row.type,
      amount: firstValue(row.amount, row.amount_cny, row.cash_amount_cny),
      unit: firstValue(row.base_unit, row.unit),
      is_actual: own(row, 'is_actual') ? row.is_actual : (row.status === 'applied' || row.status === 'actual' ? true : undefined),
      detail: firstValue(row.detail, row.note, row.content_snapshot && row.content_snapshot.note),
    };
  }
  function mapApiMatter(task, accounting) {
    const row = task && task.task ? task.task : (task || {});
    const books = accounting || row.accounting || {};
    const taskId = row.task_id || row.id || null;
    const proposalId = row.proposal_id || (row.proposal || {}).proposal_id || (row.proposal || {}).id || null;
    const proposalVersion = firstValue(row.proposal_version, (row.proposal || {}).version, (row.proposal || {}).current_version);
    const execution = { ...row, id: taskId, task_id: taskId, base_unit: firstValue(row.base_unit, row.unit) };
    const proposal = row.proposal || {
      id: proposalId, proposal_id: proposalId, version: proposalVersion,
      status: row.proposal_status || (row.status === 'pending_approval' ? 'pending_approval' : 'approved'),
      planned_qty: firstValue(row.planned_qty, books.planned_qty), unit: firstValue(row.base_unit, row.unit),
      action: row.action_type || row.action_line_id, candidate_id: row.candidate_id,
    };
    const events = array(row.events || row.business_events || books.events).map(normalizeApiEvent);
    const resultStatus = firstValue(row.accounting_status, books.status, books.execution_status, 'pending');
    const expectedIn = numberOrNull(books.expected_cash_in_cny);
    const expectedOut = numberOrNull(books.expected_cash_out_cny);
    const result = row.result || {
      status: resultStatus,
      accounting,
      expected_cash_amount: expectedIn !== null ? expectedIn : expectedOut,
      expected_cash_direction: expectedIn !== null ? 'in' : (expectedOut !== null ? 'out' : null),
      outstanding_cash_amount: books.uncollected_expected_cny,
    };
    const evidence = array(row.evidence).slice();
    if (!evidence.length && books.accounting_note) evidence.push({ label: '核算依据', value: books.accounting_note, source: array(books.event_refs).join('、') || '后端核算' });
    const taskType = firstValue(row.action_type, row.channel_type, row.kind, proposal.action_type, proposal.action);
    return {
      ...row,
      id: row.case_id || row.task_group_id || taskId || proposalId,
      task_id: taskId,
      case_id: row.case_id || null,
      status: row.status || proposal.status,
      title: row.title || row.task_title || proposal.title || taskType || '执行事项',
      kind: taskType,
      owner: firstValue(row.assignee_name, row.assignee_id, row.owner),
      due_at: row.due_at || row.due_date,
      next_step: row.next_step || row.next_action || null,
      proposal,
      execution,
      result,
      accounting: books,
      events,
      evidence,
      channels: array(row.channel_actions || row.channels).map((action) => ({ ...action, id: action.action_id || action.id, type: action.channel, content: action.content_snapshot || action.content || {} })),
      versions: row.versions || (row.proposal || {}).versions || [],
      is_demo: own(row, 'is_demo') ? row.is_demo : (books.is_demo === true),
      source: row.source || (books.is_demo ? '本地业务记录' : '业务记录'),
    };
  }
  function mapApiProposal(proposal) {
    const row = proposal && proposal.proposal ? proposal.proposal : (proposal || {});
    const proposalId = row.proposal_id || row.id || null;
    const proposalVersion = firstValue(row.proposal_version, row.current_version, row.version);
    const status = row.status || 'pending_approval';
    return {
      ...row,
      id: row.case_id || proposalId,
      case_id: row.case_id || null,
      proposal_id: proposalId,
      proposal_version: proposalVersion,
      task_id: null,
      status,
      title: row.title || row.approval_summary?.title || row.action_type || '待确认方案',
      kind: row.action_type || row.kind || row.action,
      proposal: {
        ...row,
        id: proposalId,
        proposal_id: proposalId,
        version: proposalVersion,
        status,
        action: row.action || row.action_type,
      },
      execution: {},
      events: array(row.events || row.business_events),
      accounting: {},
      is_demo: own(row, 'is_demo') ? row.is_demo : (row.context || {}).is_demo,
      source: row.source || '方案记录',
    };
  }
  function normalizeMountContext(context) {
    const normalized = { ...(context || {}) };
    const aliases = {
      tenantId: 'tenant_id', scenarioId: 'scenario_id', branchId: 'branch_id',
      snapshotId: 'snapshot_id', asOf: 'as_of', dataVersion: 'data_version',
      factVersion: 'fact_version', isDemo: 'is_demo', sourceRefs: 'source_refs',
      missingFields: 'missing_fields', riskId: 'risk_id', storeId: 'store_id',
      skuId: 'sku_id', lotId: 'lot_id', actorId: 'actor_id', proposalId: 'proposal_id',
      proposalVersion: 'proposal_version', taskId: 'task_id',
    };
    Object.entries(aliases).forEach(([camel, snake]) => {
      if (own(context || {}, camel)) normalized[camel] = context[camel];
      else if (own(context || {}, snake)) normalized[camel] = context[snake];
      delete normalized[snake];
    });
    return normalized;
  }
  function contextQuery(context) {
    return {
      scenario_id: context.scenarioId || context.scenario_id,
      branch_id: context.branchId || context.branch_id,
      proposal_id: context.proposalId || context.proposal_id,
    };
  }
  function overviewQuery(context) {
    return {
      ...contextQuery(context),
      snapshot_id: context.snapshotId || context.snapshot_id,
      as_of: context.asOf || context.as_of,
      data_version: context.dataVersion || context.data_version,
      fact_version: context.factVersion ?? context.fact_version,
      store_id: context.storeId || context.store_id,
    };
  }
  function eventOccurredAt(value) {
    if (!value) return null;
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
  }
  function apiErrorRetryable(error) {
    if (error && typeof error.retryable === 'boolean') return error.retryable;
    const status = Number(error && error.status || 0);
    return status === 0 || status >= 500;
  }
  function mount(container, options) {
    if (!container || typeof container.addEventListener !== 'function') throw new TypeError('mount 需要一个可监听事件的容器');
    const opts = options || {};
    const preview = opts.preview === true || !!(opts.preview && opts.preview.enabled === true);
    const api = opts.api || null;
    const context = normalizeMountContext(opts.context || {});
    const navigate = typeof opts.navigate === 'function' ? opts.navigate : null;
    const state = {
      api, context, navigate, preview, snapshot: null, loading: false, error: '', notice: '',
      view: opts.initialView || 'workbench', group: opts.initialGroup || 'followups',
      selectedId: context.taskId || opts.matterId || null, caseId: opts.matterId || null, detailTabs: {},
    };
    const doc = container.ownerDocument || (typeof document !== 'undefined' ? document : null);
    const root = doc && typeof doc.createElement === 'function' ? doc.createElement('div') : container;
    if (root !== container) {
      root.setAttribute('data-hackathon-followup-host', '');
      container.appendChild(root);
    }
    let disposed = false;
    let loadGeneration = 0;
    const idempotency = new Map();

    function paint() { if (!disposed) root.innerHTML = render(state); }
    function dispatch(name, detail) {
      if (typeof container.dispatchEvent !== 'function') return;
      const EventConstructor = (doc && doc.defaultView && doc.defaultView.CustomEvent) || (typeof CustomEvent === 'function' ? CustomEvent : null);
      if (EventConstructor) container.dispatchEvent(new EventConstructor(name, { bubbles: true, detail }));
      else if (doc && typeof doc.createEvent === 'function') {
        const event = doc.createEvent('CustomEvent');
        event.initCustomEvent(name, true, false, detail);
        container.dispatchEvent(event);
      }
    }
    function emitContextChange(patch) {
      dispatch('hackathon:context-change', { context: { ...state.context }, patch: { ...patch } });
    }
    function findMatter(id) {
      return array(state.snapshot && (state.snapshot.matters || state.snapshot.items || state.snapshot.work_items))
        .find((matter) => (matter.id || matter.case_id || matter.task_id) === id || matter.task_id === id) || null;
    }
    async function loadFromApi() {
      if (!api || typeof api.listTasks !== 'function' || typeof api.getTask !== 'function' || typeof api.getAccounting !== 'function') {
        const error = new Error('共享 API 客户端缺少 listTasks、getTask 或 getAccounting。');
        error.code = 'api_unavailable';
        throw error;
      }
      if (api.contractVersion === 'hackathon.v1' && (typeof api.listProposals !== 'function' || typeof api.getOverview !== 'function')) {
        const error = new Error('hackathon.v1 共享客户端需要 listProposals 与 getOverview。');
        error.code = 'api_unavailable';
        throw error;
      }
      const params = contextQuery(state.context);
      const [listResponse, proposalResponse, overviewResponse] = await Promise.all([
        state.context.taskId ? Promise.resolve(null) : api.listTasks(params),
        state.context.taskId || typeof api.listProposals !== 'function' ? Promise.resolve(null) : api.listProposals({ ...params, status: 'pending_approval' }),
        typeof api.getOverview === 'function' ? api.getOverview(overviewQuery(state.context)) : Promise.resolve(null),
      ]);
      let rows = state.context.taskId
        ? [unwrap(await api.getTask(state.context.taskId))]
        : rowsFrom(listResponse);
      if (!Array.isArray(rows)) rows = [];
      const details = await Promise.all(rows.map(async (row) => {
        const rowTask = row && row.task ? row.task : row;
        const id = rowTask && (rowTask.task_id || rowTask.id);
        return id && typeof api.getTask === 'function' ? unwrap(await api.getTask(id)) : rowTask;
      }));
      const mapped = await Promise.all(details.map(async (detail) => {
        const task = detail && detail.task ? detail.task : detail;
        const taskId = task && (task.task_id || task.id);
        const proposalId = task && (task.proposal_id || (task.proposal || {}).id || (task.proposal || {}).proposal_id) || state.context.proposalId;
        let accounting = task && task.accounting;
        if (taskId) {
          accounting = unwrap(await api.getAccounting({
            ...contextQuery(state.context), task_id: taskId, proposal_id: proposalId,
          }));
        }
        return mapApiMatter(task, accounting);
      }));
      const data = unwrap(listResponse) || {};
      const proposals = rowsFrom(proposalResponse).map(mapApiProposal);
      const taskProposalIds = new Set(mapped.map((matter) => matter.proposal_id || (matter.proposal || {}).proposal_id).filter(Boolean));
      const uniqueProposals = proposals.filter((proposal) => !taskProposalIds.has(proposal.proposal_id));
      const overviewData = unwrap(overviewResponse) || {};
      const snapshot = {
        ...data,
        metadata: data.metadata || overviewData.metadata || data.context || overviewData.context || {},
        matters: [...uniqueProposals, ...mapped],
        overview: overviewData.overview || (overviewResponse ? overviewData : data.overview || {}),
      };
      if (state.view === 'cases' && typeof api.getCase === 'function') {
        const selectedMatter = mapped.find((matter) => matter.id === state.caseId || matter.case_id === state.caseId || matter.task_id === state.caseId);
        const caseId = (selectedMatter && selectedMatter.case_id) || state.caseId || (mapped[0] && mapped[0].case_id);
        if (caseId) {
          const caseResponse = unwrap(await api.getCase(caseId));
          const caseData = caseResponse && (caseResponse.case || caseResponse);
          if (caseData) {
            snapshot.matters = mapped.map((matter) => matter.case_id === caseId ? { ...matter, ...caseData, case_id: caseId, execution: matter.execution, task_id: matter.task_id, accounting: matter.accounting } : matter);
          }
        }
      }
      return snapshot;
    }
    async function refresh() {
      if (disposed) return null;
      const generation = ++loadGeneration;
      state.loading = true; state.error = ''; paint();
      try {
        const response = preview ? previewData() : await loadFromApi();
        if (disposed || generation !== loadGeneration) return null;
        if (!response) throw new Error('后端未返回跟进记录。');
        state.snapshot = response;
        state.loading = false; state.error = '';
        const matters = array(state.snapshot.matters || state.snapshot.items || state.snapshot.work_items);
        if (state.selectedId && !matters.some((matter) => (matter.id || matter.case_id || matter.task_id) === state.selectedId || matter.task_id === state.selectedId)) state.selectedId = null;
        if (state.caseId && !matters.some((matter) => (matter.id || matter.case_id) === state.caseId)) state.caseId = null;
        paint();
        return state.snapshot;
      } catch (error) {
        if (disposed || generation !== loadGeneration) return null;
        state.loading = false; state.error = error && error.message ? error.message : '读取跟进记录失败。';
        dispatch('hackathon:error', { context: { ...state.context }, code: error && error.code || 'followup_read_failed', message: state.error, retryable: apiErrorRetryable(error) });
        paint(); return null;
      }
    }
    async function perform(command, matter, payload) {
      if (preview) { state.notice = '预览数据只读，操作未保存。'; paint(); return; }
      if (!state.context.actorId) { state.notice = '宿主上下文缺少当前操作者 actorId，操作未提交。'; paint(); return; }
      const missing = requiredMissing(command, payload);
      if (missing) { state.notice = missing; paint(); return; }
      const target = {
        matter_id: matter.id || matter.case_id || matter.task_id,
        proposal_id: (matter.proposal || {}).id || (matter.proposal || {}).proposal_id || state.context.proposalId || null,
        proposal_version: firstValue((matter.proposal || {}).version, (matter.proposal || {}).current_version),
        task_id: ((matter.execution || matter.task || {}).task_id) || ((matter.execution || matter.task || {}).id) || matter.execution_task_id || matter.task_id || null,
        task_version: firstValue((matter.execution || matter.task || {}).version, (matter.execution || matter.task || {}).current_version),
      };
      const channelType = command.startsWith('feishu_') ? 'feishu' : (command.startsWith('wecom_') ? 'wecom' : (command.startsWith('email_') ? 'email' : null));
      const channel = channelType ? findChannel(matter, channelType) : null;
      const canonical = JSON.stringify({ command, target, payload });
      if (!idempotency.has(canonical)) idempotency.set(canonical, randomKey());
      const key = idempotency.get(canonical);
      const button = root.querySelector && root.querySelector('[data-hf-command="' + command + '"]');
      if (button) { button.disabled = true; button.setAttribute('aria-busy', 'true'); }
      state.notice = '正在保存并读取最新记录…';
      paint();
      try {
        let response;
        if (command === 'confirm_and_arrange') {
          if (!api || typeof api.confirmProposal !== 'function') throw new Error('方案确认接口尚未接入。');
          const proposal = matter.proposal || {};
          const proposalId = target.proposal_id || state.context.proposalId;
          const candidateId = proposal.candidate_id || proposal.selected_candidate_id || matter.candidate_id;
          if (!proposalId || !candidateId || target.proposal_version === null || target.proposal_version === undefined || !state.context.snapshotId || state.context.factVersion === undefined) {
            throw Object.assign(new Error('方案缺少 proposal_id、candidate_id、方案版本或事实快照版本，无法安全确认。'), { code: 'confirmation_context_missing' });
          }
          const body = {
            expected_proposal_version: Number(target.proposal_version),
            expected_fact_version: Number(state.context.factVersion),
            expected_snapshot_id: state.context.snapshotId,
            actor_id: state.context.actorId,
            candidate_id: candidateId,
            task_assignments: array(proposal.task_assignments || matter.task_assignments),
          };
          response = unwrap(await api.confirmProposal(proposalId, body, key)) || {};
          const tasks = array(response.tasks);
          const taskIds = tasks.map((row) => row.task_id || row.id).filter(Boolean);
          state.context = { ...state.context, proposalId, ...(taskIds[0] ? { taskId: taskIds[0] } : {}) };
          state.group = 'followups';
          state.selectedId = taskIds[0] || null;
          state.caseId = null;
          const approvalContext = { ...state.context };
          dispatch('hackathon:proposal-confirmed', {
            context: approvalContext,
            approvalId: response.approval_id || response.approvalId || null,
            proposalId: response.proposal_id || proposalId,
            proposalVersion: firstValue(response.proposal_version, response.proposalVersion, target.proposal_version),
            taskIds,
          });
          emitContextChange({ proposalId, ...(taskIds[0] ? { taskId: taskIds[0] } : {}) });
        } else if (['record_receipt', 'feishu_report_exception', 'wecom_record_price_effective', 'email_record_supplier_reply', 'email_confirm_terms'].includes(command)) {
          if (!api || typeof api.recordBusinessEvents !== 'function') throw new Error('业务事件接口尚未接入。');
          if (!target.task_id) throw Object.assign(new Error('当前事项尚无可写入的执行任务。'), { code: 'task_missing' });
          if (!Number.isInteger(Number(target.task_version)) || !Number.isInteger(Number(target.proposal_version))) throw Object.assign(new Error('任务或方案版本缺失，无法安全写入业务事件。'), { code: 'event_version_missing' });
          const occurredAt = eventOccurredAt(payload.occurred_at);
          if (!occurredAt) throw Object.assign(new Error('发生时间格式无效。'), { code: 'invalid_event_time' });
          const eventType = command === 'record_receipt' ? payload.event_type
            : (command === 'feishu_report_exception' ? 'exception' : (command === 'wecom_record_price_effective' ? 'price_effective' : (command === 'email_record_supplier_reply' ? 'supplier_reply' : 'supplier_terms_confirmed')));
          const task = matter.execution || matter.task || {};
          const eventBody = {
            task_id: target.task_id,
            task_version: Number(target.task_version),
            proposal_id: target.proposal_id,
            proposal_version: Number(target.proposal_version),
            event_id: 'EV-' + key,
            event_type: eventType,
            receipt_ref: payload.receipt_ref,
            quantity: payload.quantity,
            base_unit: firstValue(task.base_unit, task.unit, matter.proposal && matter.proposal.unit),
            occurred_at: occurredAt,
            known_at: new Date().toISOString(),
            source: command === 'record_receipt' ? 'manual_execution_receipt' : (command === 'feishu_report_exception' ? 'manual_exception_report' : (command === 'wecom_record_price_effective' ? 'manual_price_effective_record' : 'local_supplier_response_record')),
            content_snapshot: command === 'email_record_supplier_reply' ? { reply: payload.reply } : (command === 'email_confirm_terms' ? { terms: payload.terms } : (command === 'feishu_report_exception' ? { reason: payload.reason } : undefined)),
            detail: payload.note || payload.reply || payload.terms || payload.reason || null,
            is_demo: true,
            external_write: false,
            actor_id: state.context.actorId,
          };
          response = unwrap(await api.recordBusinessEvents(target.task_id, eventBody, key)) || {};
          const updatedTaskVersion = firstValue(response.task_version, response.version, target.task_version);
          dispatch('hackathon:task-updated', { context: { ...state.context, taskId: target.task_id }, taskId: target.task_id, taskVersion: updatedTaskVersion });
        } else {
          if (!api || typeof api.recordChannelAction !== 'function') throw new Error('本地渠道动作接口尚未接入。');
          if (!target.task_id) throw Object.assign(new Error('当前事项尚无可关联的执行任务。'), { code: 'task_missing' });
          const actionSpecs = {
            feishu_send_notification: ['feishu', 'procurement_task_notification', 'sent'],
            feishu_take_over: ['feishu', 'task_take_over', 'accepted'],
            feishu_submit_result: ['feishu', 'execution_result_submitted', 'submitted'],
            wecom_publish: ['wecom', 'promotion_publish', 'published'],
            email_save_draft: ['email', 'supplier_email_draft', 'draft_saved'],
            email_send: ['email', 'supplier_email', 'sent'],
          };
          const spec = actionSpecs[command];
          if (!spec) throw Object.assign(new Error('不支持此本地动作。'), { code: 'unsupported_action' });
          const oldContent = channelContent(matter, spec[0]);
          const contentSnapshot = command === 'feishu_submit_result' ? { ...oldContent, result: payload.result }
            : command === 'feishu_report_exception' ? { ...oldContent, reason: payload.reason }
              : command === 'email_save_draft' || command === 'email_send' ? { ...payload }
                : { ...oldContent, ...payload };
          const actionBody = {
            task_id: target.task_id,
            proposal_id: target.proposal_id,
            proposal_version: target.proposal_version,
            task_version: target.task_version,
            channel: spec[0],
            action_type: spec[1],
            status: spec[2],
            content_snapshot: contentSnapshot,
            target_ref: firstValue(channel && channel.target_ref, state.context.storeId, matter.store_id),
            actor_id: state.context.actorId,
            source: 'local_channel_simulation',
            is_demo: true,
            external_write: false,
          };
          response = unwrap(await api.recordChannelAction(target.task_id, actionBody, key)) || {};
        }
        state.notice = '操作已记录，正在读取最新状态。';
        const latest = await refresh();
        if (latest) state.notice = '操作已记录，最新进度已更新。';
        else state.notice = '操作已提交，但最新进度暂时无法读取；请刷新后核对记录。';
        paint();
      } catch (error) {
        state.notice = error && error.message ? error.message : '操作未保存，请检查连接后重试。';
        dispatch('hackathon:error', { context: { ...state.context }, code: error && error.code || 'followup_write_failed', message: state.notice, retryable: apiErrorRetryable(error) });
        paint();
        if (button && !disposed) { button.disabled = false; button.removeAttribute('aria-busy'); }
      }
    }
    function onClick(event) {
      const target = event.target && event.target.closest ? event.target.closest('[data-hf-view], [data-hf-group], [data-hf-select], [data-hf-detail-tab], [data-hf-case], [data-hf-refresh], [data-hf-retry], [data-hf-return], [data-hf-command], [data-hf-open-matter], [data-hf-navigate-decision]') : null;
      if (!target || !(root === container ? container.contains(target) : root.contains(target))) return;
      if (target.hasAttribute('data-hf-view')) { state.view = target.getAttribute('data-hf-view'); state.notice = ''; if (state.view === 'cases') { refresh(); return; } paint(); return; }
      if (target.hasAttribute('data-hf-group')) { state.group = target.getAttribute('data-hf-group'); state.selectedId = null; state.notice = ''; paint(); return; }
      if (target.hasAttribute('data-hf-select')) {
        state.selectedId = target.getAttribute('data-hf-select'); state.detailTabs[state.selectedId] = 'timeline';
        const matter = findMatter(state.selectedId);
        if (matter && matter.task_id && state.context.taskId !== matter.task_id) { state.context = { ...state.context, taskId: matter.task_id, proposalId: matter.proposal && (matter.proposal.id || matter.proposal.proposal_id) || state.context.proposalId }; emitContextChange({ taskId: matter.task_id, proposalId: state.context.proposalId }); }
        paint(); return;
      }
      if (target.hasAttribute('data-hf-detail-tab')) {
        const current = findMatter(state.selectedId);
        if (current) state.detailTabs[current.id || current.case_id] = target.getAttribute('data-hf-detail-tab');
        paint(); return;
      }
      if (target.hasAttribute('data-hf-case')) { state.caseId = target.getAttribute('data-hf-case'); state.selectedId = state.caseId; if (state.context.taskId) { state.context = { ...state.context, taskId: null }; emitContextChange({ taskId: null }); } refresh(); return; }
      if (target.hasAttribute('data-hf-refresh') || target.hasAttribute('data-hf-retry')) { state.notice = ''; refresh(); return; }
      if (target.hasAttribute('data-hf-return')) { if (navigate) navigate('workspace', { ...state.context }); return; }
      if (target.hasAttribute('data-hf-navigate-decision')) {
        const matter = findMatter(state.selectedId);
        if (navigate && matter) navigate('decision', { ...state.context, riskId: matter.risk_id || (matter.risk || {}).id || state.context.riskId, proposalId: matter.proposal && (matter.proposal.id || matter.proposal.proposal_id) || state.context.proposalId });
        return;
      }
      if (target.hasAttribute('data-hf-open-matter')) {
        const id = target.getAttribute('data-hf-open-matter');
        state.view = 'workbench'; state.group = GROUPS.find((group) => groupItems(state.snapshot, group.id).some((matter) => (matter.id || matter.case_id) === id))?.id || 'followups'; state.selectedId = id; paint(); return;
      }
      if (target.hasAttribute('data-hf-command')) {
        event.preventDefault();
        const command = target.getAttribute('data-hf-command');
        const matter = findMatter(state.selectedId || state.caseId);
        if (!matter) return;
        const form = target.closest('form') || ((command === 'email_save_draft' || command === 'email_send' || command === 'email_confirm_terms') ? root.querySelector('[data-hf-form="email"]') : null);
        const payload = commandPayload(command, form);
        if (command === 'wecom_publish') {
          const promo = channelContent(matter, 'wecom');
          payload.title = promo.title || '';
          payload.body = promo.body || '';
          payload.price_stages = promo.price_stages || [];
          payload.start_date = promo.start_date || promo.start_at || null;
          payload.end_date_exclusive = promo.end_date_exclusive || promo.end_at || null;
        }
        if (command === 'email_confirm_terms') {
          payload.terms = formValue(form, 'terms') || (findChannel(matter, 'email') || {}).content?.terms || '';
          payload.receipt_ref = formValue(form, 'terms_receipt_ref').trim();
          payload.occurred_at = formValue(form, 'terms_occurred_at');
          const rawQuantity = formValue(form, 'terms_quantity');
          payload.quantity = rawQuantity === '' ? null : Number(rawQuantity);
        }
        perform(command, matter, payload);
      }
    }
    function onSubmit(event) { if (event.preventDefault) event.preventDefault(); }
    root.addEventListener('click', onClick);
    root.addEventListener('submit', onSubmit);
    refresh();
    return {
      refresh,
      updateContext(nextContext) {
        const patch = normalizeMountContext(nextContext || {});
        const scopeKeys = ['tenantId', 'scenarioId', 'branchId', 'snapshotId', 'asOf', 'dataVersion', 'factVersion', 'isDemo', 'riskId', 'storeId', 'skuId', 'lotId', 'proposalId'];
        const changedScope = scopeKeys.some((key) => own(patch, key) && patch[key] !== state.context[key]);
        if (changedScope && !own(patch, 'taskId')) {
          patch.taskId = null;
          state.selectedId = null;
          state.caseId = null;
        }
        state.context = { ...state.context, ...patch };
        if (own(patch, 'taskId')) state.selectedId = patch.taskId || null;
        if (own(patch, 'taskId') && patch.taskId) state.group = 'followups';
        emitContextChange(patch);
        return refresh();
      },
      destroy() {
        disposed = true; loadGeneration += 1;
        root.removeEventListener('click', onClick);
        root.removeEventListener('submit', onSubmit);
        if (root !== container && root.parentNode) root.parentNode.removeChild(root);
        else if (root === container) root.innerHTML = '';
      },
      unmount() { this.destroy(); },
      getState() { return { ...state, context: { ...state.context }, snapshot: state.snapshot }; },
    };
  }

  return {
    mount,
    mapFollowupDisplay,
    classifyMatter,
    groupItems,
    aggregateMatter,
    previewData,
    escapeHTML,
    money,
    quantity,
    render,
  };
});

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const followup = require('../../../assets/hackathon/followup/followup.js');

function fixtureMatter(overrides = {}) {
  return {
    id: 'm-1', status: 'received', proposal: { id: 'p-1', version: 3, status: 'approved', planned_qty: 10, unit: '盒' },
    execution: { id: 't-1', task_id: 't-1', status: 'received', version: 2, planned_qty: 10, completed_qty: 10, base_unit: '盒' },
    result: { status: 'pending', outstanding_cash_amount: null }, events: [], ...overrides,
  };
}

function sampleTask(overrides = {}) {
  return {
    task_id: 'TASK-1', task_group_id: 'TG-1', case_id: 'CASE-1', proposal_id: 'PROP-1', proposal_version: 2,
    status: 'in_transit', version: 7, planned_qty: 10, completed_qty: 4, base_unit: '盒',
    assignee_id: 'person-1', due_at: '2026-10-04T18:00:00+08:00', exception: null, closed_reason: null,
    proposal: { id: 'PROP-1', version: 2, status: 'approved', planned_qty: 10, unit: '盒', candidate_id: 'CAND-1' },
    channel_actions: [], events: [], ...overrides,
  };
}

function accounting(overrides = {}) {
  return {
    task_id: 'TASK-1', proposal_id: 'PROP-1', planned_qty: 10, shipped_qty: 4, received_qty: 4,
    remaining_unexecuted_qty: 6, sold_qty: null, sales_amount_cny: null, expected_cash_in_cny: null,
    actual_cash_in_cny: null, unmatched_cash_cny: null, cash_event_ids: [], allocation_ids: [],
    event_refs: [], execution_status: 'in_transit', accounting_note: null, missing_fields: [],
    ...overrides,
  };
}

test('分组互斥；完成只在业务凭据和数量满足时归档，取消单列归档', () => {
  assert.equal(followup.classifyMatter({ id: 'draft', status: 'draft' }), 'suggestions');
  assert.equal(followup.classifyMatter({ id: 'pending', status: 'pending_approval', proposal: { status: 'pending_approval' } }), 'approvals');
  assert.equal(followup.classifyMatter({ id: 'approved', status: 'approved', proposal: { id: 'p1', status: 'approved' }, execution: { task_id: 't1', status: 'pending_dispatch' } }), 'followups');
  const partial = followup.mapFollowupDisplay(sampleTask(), accounting({ actual_cash_in_cny: 3000, expected_cash_in_cny: 4000, cash_event_ids: ['CASH-1'] }));
  assert.deepEqual({ execution: partial.execution_display_status, accounting: partial.accounting_display_status, left: partial.uncompleted_qty }, { execution: '执行中', accounting: '核算中', left: 6 });
  assert.equal(partial.raw_execution_status, 'in_transit');
  assert.equal(followup.mapFollowupDisplay(sampleTask(), accounting({ event_refs: ['RECEIPT-ONLY'] })).accounting_display_status, '待核算');
  assert.equal(followup.mapFollowupDisplay({ status: 'pending_dispatch', planned_qty: 10 }, {}).execution_display_status, '待执行');
  const attention = followup.mapFollowupDisplay({ status: 'exception', planned_qty: 10, completed_qty: 4, exception: { reason: '数量不符' } }, {});
  assert.equal(attention.needs_attention, true);
  assert.equal(attention.exception.reason, '数量不符');
  const complete = followup.mapFollowupDisplay(sampleTask({ status: 'completed', completed_qty: 10, completion_criteria_met: true }), accounting({ execution_status: 'completed', received_qty: 10, event_refs: ['RECEIPT-1'] }));
  assert.equal(complete.execution_display_status, '已完成');
  assert.equal(complete.accounting_display_status, '已核算');
  const cancelled = followup.mapFollowupDisplay({ status: 'cancelled', planned_qty: 10, completed_qty: 0, closed_reason: '库存不足' }, {});
  assert.equal(cancelled.execution_display_status, '已取消');
  assert.equal(cancelled.closed_reason, '库存不足');
  assert.equal(followup.classifyMatter(fixtureMatter({ status: 'cancelled' })), 'archived');
  assert.equal(followup.classifyMatter(fixtureMatter({
    status: 'completed', execution: { task_id: 't-1', status: 'completed', version: 2, planned_qty: 10, completed_qty: 10, completion_criteria_met: true },
    result: { status: 'completed', outstanding_cash_amount: 0, accounting: { execution_status: 'completed', event_refs: ['CASH-1'] } },
  })), 'completed');
  const matters = [{ id: 'a', status: 'pending_approval', proposal: { status: 'pending_approval' } }, fixtureMatter({ id: 'b' })];
  const snapshot = { matters };
  const memberships = matters.map((matter) => ['suggestions', 'approvals', 'followups', 'completed', 'archived'].filter((group) => followup.groupItems(snapshot, group).includes(matter)));
  assert.deepEqual(memberships, [['approvals'], ['followups']]);
});

test('案例结果从业务事件汇总：S01 完整结果与 S09 部分执行、待到账分开', () => {
  const preview = followup.previewData();
  const s01 = preview.matters.find((item) => item.scenario_id === 'S01');
  const s09 = preview.matters.find((item) => item.scenario_id === 'S09');
  const full = followup.aggregateMatter(s01);
  const partial = followup.aggregateMatter(s09);
  assert.equal(full.plannedQty, 80);
  assert.equal(full.dispatchedQty, 80);
  assert.equal(full.receivedQty, 80);
  assert.equal(full.soldQty, 64);
  assert.equal(full.salesAmount, 6400);
  assert.equal(full.actualCash, 6400);
  assert.equal(full.actualFees, 24);
  assert.equal(full.outstandingCash, 0);
  assert.equal(full.remainingInventoryQty, 56);
  assert.equal(followup.classifyMatter(s01), 'completed');
  assert.equal(partial.plannedQty, 80);
  assert.equal(partial.dispatchedQty, 60);
  assert.equal(partial.receivedQty, 60);
  assert.equal(partial.soldQty, 40);
  assert.equal(partial.salesAmount, 4000);
  assert.equal(partial.actualCash, 3000);
  assert.equal(partial.expectedCashIn, 4000);
  assert.equal(partial.outstandingCash, 1000);
  assert.equal(partial.remainingInventoryQty, 80);
  assert.equal(followup.classifyMatter(s09), 'followups');
  const purchase = preview.matters.find((item) => item.scenario_id === 'S07');
  const totals = followup.aggregateMatter(purchase);
  assert.equal(totals.expectedCashIn, null);
  assert.equal(totals.expectedCashOut, 2400);
  assert.equal(totals.actualCashOut, null);
});

test('未知和预计值不会变成已发生的 0，现金方向缺失时保持未知', () => {
  const matter = fixtureMatter({
    result: { expected_cash_amount: 4000 },
    events: [
      { kind: 'sale', quantity: 2, is_actual: true },
      { kind: 'sale', quantity: null, is_actual: true },
      { kind: 'cash_receipt', amount: 700, is_actual: false },
      { kind: 'receipt', quantity: 1 },
    ],
  });
  const totals = followup.aggregateMatter(matter);
  assert.equal(totals.soldQty, null);
  assert.equal(totals.actualCash, null);
  assert.equal(totals.outstandingCash, null);
  assert.equal(followup.money(null), '未知');
  assert.equal(followup.quantity(3, null), '3 单位未知');
  const unknownTimeline = followup.render({ snapshot: { matters: [{ ...matter, case_id: 'unknown-events' }] }, loading: false, view: 'cases', caseId: null });
  assert.match(unknownTimeline, /状态未知/);
});

test('总览只含四张核心卡，开发预览只读且显示预览标签', () => {
  const snapshot = followup.previewData();
  const html = followup.render({ snapshot, loading: false, error: '', notice: '', view: 'overview', group: 'followups', detailTabs: {}, api: null, preview: true });
  assert.equal((html.match(/class="hf-metric/g) || []).length, 4);
  assert.equal((html.match(/>未知<\/strong>/g) || []).length, 4);
  assert.match(html, /开发预览 · 只读/);
  assert.doesNotMatch(html, /缺货风险数量|7 天销售额|毛利率|库存周转天数卡片/);
  const wecom = snapshot.matters.find((item) => item.scenario_id === 'S06');
  const channelsHtml = followup.render({ snapshot: { ...snapshot, matters: [wecom] }, loading: false, error: '', view: 'workbench', selectedId: wecom.id, group: 'followups', detailTabs: { [wecom.id]: 'channels' }, api: null, preview: true });
  assert.match(channelsHtml, /预览数据只读，操作不会写入业务记录/);
  assert.match(channelsHtml, /data-hf-command="wecom_publish" disabled/);
});

test('内容转义并拒绝外部或可执行图片地址', () => {
  assert.equal(followup.escapeHTML('<img src=x onerror="x">'), '&lt;img src=x onerror=&quot;x&quot;&gt;');
  const matter = fixtureMatter({
    id: 'xss', title: '<script>alert(1)</script>', kind: 'promotion',
    channels: [{ type: 'wecom', status: 'draft_saved', content: { title: '活动', body: '<img onerror=x>', image_url: 'javascript:alert(1)' } }],
  });
  const html = followup.render({ snapshot: { matters: [matter] }, loading: false, error: '', view: 'workbench', group: 'followups', selectedId: 'xss', detailTabs: { xss: 'channels' }, api: { recordChannelAction() {} }, preview: false });
  assert.doesNotMatch(html, /<script>alert\(1\)<\/script>/);
  assert.doesNotMatch(html, /<img onerror=x>/);
  assert.doesNotMatch(html, /src="javascript:/);
});

class FakeContainer {
  constructor() { this.innerHTML = ''; this.listeners = new Map(); this.events = []; }
  addEventListener(name, handler) { this.listeners.set(name, handler); }
  removeEventListener(name) { this.listeners.delete(name); }
  contains() { return true; }
  dispatchEvent(event) { this.events.push(event); return true; }
  querySelector(selector) {
    if (selector === '[data-hf-notice]') return this.notice || null;
    if (selector === '[data-hf-form="email"]') return this.emailForm || null;
    const match = selector.match(/^\[data-hf-command="([^"]+)"\]$/);
    return match ? { disabled: false, setAttribute() {}, removeAttribute() {} } : null;
  }
  click(target) { this.listeners.get('click')({ target, preventDefault() {} }); }
}
function fakeTarget(attrs, form) {
  return {
    disabled: false,
    hasAttribute(name) { return Object.prototype.hasOwnProperty.call(attrs, name); },
    getAttribute(name) { return attrs[name]; },
    closest(selector) { return selector === 'form' ? form || null : this; },
    setAttribute() {}, removeAttribute() {},
  };
}
function form(values) {
  return { elements: { namedItem(name) { return values[name] ? { value: values[name] } : null; } } };
}
function apiFor(task, books, calls = {}) {
  return {
    mode: 'http',
    async listTasks(params) { calls.listParams = params; calls.listCount = (calls.listCount || 0) + 1; return { tasks: [{ task_id: task.task_id }], metadata: { source: 'backend', context: { scenario_id: params.scenario_id } } }; },
    async getTask(taskId) { calls.getTaskIds = [...(calls.getTaskIds || []), taskId]; return task; },
    async getAccounting(params) { calls.accountingParams = params; calls.accountingCount = (calls.accountingCount || 0) + 1; return books; },
    async getCase(caseId) { calls.caseIds = [...(calls.caseIds || []), caseId]; return { case: { case_id: caseId, title: '后端案例', events: [] } }; },
    async recordBusinessEvents(taskId, body, key) { calls.businessEvents = [...(calls.businessEvents || []), { taskId, body, key }]; task.version += 1; return { task_version: task.version }; },
    async recordChannelAction(taskId, body, key) { calls.channelActions = [...(calls.channelActions || []), { taskId, body, key }]; return { action_id: 'ACTION-1' }; },
    async confirmProposal(proposalId, body, key) { calls.confirm = { proposalId, body, key }; return { approval_id: 'APR-1', proposal_id: proposalId, proposal_version: body.expected_proposal_version, tasks: [{ task_id: 'TASK-NEW' }] }; },
  };
}

test('共享 API client 读取任务与核算；回执通过版本化业务事件保存并发出 task-updated', async () => {
  const container = new FakeContainer();
  const task = sampleTask();
  const calls = {};
  const mounted = followup.mount(container, {
    api: apiFor(task, accounting(), calls),
    context: { tenantId: 'demo', scenarioId: 'S01', branchId: 'transfer_80', snapshotId: 'SNAP-1', asOf: '2026-10-03T09:30:00+08:00', factVersion: 1, actorId: 'manager-test' },
    initialGroup: 'followups',
  });
  assert.equal(typeof mounted.destroy, 'function');
  assert.equal(typeof mounted.updateContext, 'function');
  await mounted.refresh();
  assert.equal(calls.listParams.scenario_id, 'S01');
  const state = mounted.getState();
  assert.equal(state.snapshot.matters[0].task_id, 'TASK-1');
  const receiptForm = form({ receipt_ref: 'R-123', event_type: 'receipt', quantity: '4', occurred_at: '2026-10-04T10:30' });
  container.click(fakeTarget({ 'data-hf-command': 'record_receipt' }, receiptForm));
  await new Promise((resolve) => setTimeout(resolve, 0));
  const saved = calls.businessEvents[0];
  assert.equal(saved.taskId, 'TASK-1');
  assert.equal(saved.body.task_version, 7);
  assert.equal(saved.body.proposal_version, 2);
  assert.equal(saved.body.event_type, 'receipt');
  assert.equal(saved.body.quantity, 4);
  assert.equal(saved.body.base_unit, '盒');
  assert.equal(saved.body.receipt_ref, 'R-123');
  assert.equal(saved.body.external_write, false);
  assert.ok(saved.body.event_id);
  assert.ok(saved.key);
  assert.ok(container.events.some((event) => event.type === 'hackathon:task-updated'));
  container.click(fakeTarget({ 'data-hf-view': 'cases' }));
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.ok(calls.caseIds.includes('CASE-1'));
  const contextSnapshot = await mounted.updateContext({ scenarioId: 'S09', branchId: 'partial_transfer' });
  assert.ok(contextSnapshot);
  assert.equal(mounted.getState().context.scenarioId, 'S09');
  assert.ok(container.events.some((event) => event.type === 'hackathon:context-change' && event.detail.patch.scenarioId === 'S09'));
  mounted.destroy();
  assert.equal(container.listeners.size, 0);
  assert.equal(container.innerHTML, '');
});

test('本地渠道 API 保留 demo 安全标记，并为重复提交复用幂等键', async () => {
  const container = new FakeContainer();
  const task = sampleTask({ action_type: 'promotion', channel_actions: [{ action_id: 'ACTION-OLD', channel: 'wecom', status: 'draft_saved', content_snapshot: { title: '促销内容', body: '已批准促销文案' } }] });
  const calls = {};
  const mounted = followup.mount(container, { api: apiFor(task, accounting(), calls), context: { tenantId: 'demo', scenarioId: 'S06', branchId: 'promotion', actorId: 'manager-test' }, initialGroup: 'followups' });
  await new Promise((resolve) => setTimeout(resolve, 0));
  container.click(fakeTarget({ 'data-hf-detail-tab': 'channels' }));
  container.click(fakeTarget({ 'data-hf-command': 'wecom_publish' }));
  await new Promise((resolve) => setTimeout(resolve, 0));
  container.click(fakeTarget({ 'data-hf-command': 'wecom_publish' }));
  await new Promise((resolve) => setTimeout(resolve, 0));
  container.click(fakeTarget({ 'data-hf-command': 'wecom_record_price_effective' }, form({ receipt_ref: 'PRICE-1', occurred_at: '2026-10-05T09:00', quantity: '40' })));
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(calls.channelActions.length, 2);
  assert.equal(calls.channelActions[0].body.channel, 'wecom');
  assert.equal(calls.channelActions[0].body.status, 'published');
  assert.equal(calls.channelActions[0].body.is_demo, true);
  assert.equal(calls.channelActions[0].body.external_write, false);
  assert.equal(calls.channelActions[0].body.source, 'local_channel_simulation');
  assert.equal(calls.channelActions[0].key, calls.channelActions[1].key);
  assert.equal(calls.businessEvents[0].body.event_type, 'price_effective');
  assert.equal(calls.businessEvents[0].body.receipt_ref, 'PRICE-1');
  assert.equal(calls.businessEvents[0].body.quantity, 40);
  assert.equal(calls.businessEvents[0].body.external_write, false);
  mounted.destroy();
});

test('确认只调用一次原子 confirmProposal 并发出 proposal-confirmed', async () => {
  const container = new FakeContainer();
  const pending = sampleTask({ status: 'pending_approval', proposal: { id: 'PROP-1', version: 2, status: 'pending_approval', candidate_id: 'CAND-1', task_assignments: [] } });
  const calls = {};
  const api = apiFor(pending, accounting(), calls);
  const mounted = followup.mount(container, { api, context: { tenantId: 'demo', scenarioId: 'S01', branchId: 'transfer_80', snapshotId: 'SNAP-1', factVersion: 5, actorId: 'manager-test' }, initialGroup: 'approvals' });
  await new Promise((resolve) => setTimeout(resolve, 0));
  container.click(fakeTarget({ 'data-hf-command': 'confirm_and_arrange' }));
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(calls.confirm.proposalId, 'PROP-1');
  assert.equal(calls.confirm.body.expected_proposal_version, 2);
  assert.equal(calls.confirm.body.expected_fact_version, 5);
  assert.equal(calls.confirm.body.expected_snapshot_id, 'SNAP-1');
  assert.ok(container.events.some((event) => event.type === 'hackathon:proposal-confirmed' && event.detail.taskIds[0] === 'TASK-NEW'));
  assert.equal(mounted.getState().group, 'followups');
  mounted.destroy();
});

test('真实 API 错误显示失败并派发错误事件，不回退到本地示例', async () => {
  const container = new FakeContainer();
  const api = {
    mode: 'http',
    async listTasks() { const error = new Error('service unavailable'); error.code = 'http_503'; error.status = 503; throw error; },
    async getTask() { throw new Error('must not be called'); },
    async getAccounting() { throw new Error('must not be called'); },
  };
  const mounted = followup.mount(container, { api, context: { scenarioId: 'S01' } });
  await mounted.refresh();
  assert.equal(mounted.getState().snapshot, null);
  assert.match(mounted.getState().error, /service unavailable/);
  assert.ok(container.events.some((event) => event.type === 'hackathon:error' && event.detail.retryable === true));
  assert.doesNotMatch(container.innerHTML, /古荡店坚果调往文三店/);
  mounted.destroy();
});

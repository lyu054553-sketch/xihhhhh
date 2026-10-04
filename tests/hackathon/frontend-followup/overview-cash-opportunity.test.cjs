const test = require('node:test');
const assert = require('node:assert/strict');
const cashOpportunity = require('../../../assets/hackathon/followup/overview-cash-opportunity.js');

const context = {
  tenantId: 'hackathon-demo', scenarioId: 'S01', branchId: 'transfer_80',
  snapshotId: 'SNAP-20261003-BASE', asOf: '2026-10-03T09:30:00+08:00',
  dataVersion: 'retail-v2.1', factVersion: 3, isDemo: true, storeId: 'all',
};

function responses({ tasks = [], proposals = [], metadata = {} } = {}) {
  const apiContext = {
    tenant_id: context.tenantId, scenario_id: context.scenarioId, branch_id: context.branchId,
    snapshot_id: context.snapshotId, as_of: context.asOf, data_version: context.dataVersion,
    fact_version: context.factVersion, is_demo: context.isDemo,
  };
  return [
    { context: apiContext, overview: { account: { balance: 900000 }, inventory: { cost: 1200000, risk_cost: 380000 }, purchase_commitments: { amount: 25000 }, stores: [] }, metadata: { source: 'versioned_retail_facts', is_demo: true, as_of: context.asOf, ...metadata } },
    { context: apiContext, tasks },
    { context: apiContext, proposals },
  ];
}

function task(overrides = {}) {
  const configuredAccounting = overrides.accounting || { expected_cash_cny: 6400, actual_cash_cny: null };
  const expected = configuredAccounting.expected_cash_cny ?? configuredAccounting.expected_cash_in_cny ?? 6400;
  return {
    task_id: 'TASK-1', proposal_id: 'PROP-1', proposal_version: 2,
    title: '古荡店库存处置', status: 'in_transit', display_status: 'following_up',
    next_action: '核对收货与到账回执', created_at: '2026-10-03T09:34:00+08:00',
    plan: { actions: [{ store_id: 'ST-001', target_store_id: 'ST-002' }] },
    candidate_calculation: { expected_cash_in_cny: expected, cash_flow: [{ direction: 'in', amount_cny: expected, expected_at: '2026-10-04', status: 'forecast', source_ref: 'test-flow' }] },
    accounting: configuredAccounting,
    ...overrides,
  };
}

function proposal(overrides = {}) {
  return { proposal_id: 'PROP-PENDING', proposal_version: 1, status: 'pending_approval', title: '确认退供方案', updated_at: '2026-10-03T09:00:00+08:00', ...overrides };
}

class FakeNode {
  constructor(ownerDocument) { this.ownerDocument = ownerDocument; this.listeners = new Map(); this.children = []; this.attributes = {}; this.parentNode = null; this.innerHTML = ''; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, handler) { this.listeners.set(name, handler); }
  removeEventListener(name) { this.listeners.delete(name); }
  appendChild(child) { this.children.push(child); child.parentNode = this; return child; }
  removeChild(child) { this.children = this.children.filter((item) => item !== child); child.parentNode = null; return child; }
  remove() { this.parentNode?.removeChild(this); }
  click() { this.clicked = true; }
  contains() { return true; }
  dispatchEvent(event) { this.events = [...(this.events || []), event]; return true; }
  clickAction(action, extra = {}) {
    const button = { getAttribute: (name) => name === 'data-hco-action' ? action : (extra[name] ?? extra[name.replace('data-hco-', '')]), closest: () => button };
    this.listeners.get('click')?.({ target: button });
  }
}

function fakeContainer() {
  const doc = { defaultView: { CustomEvent: class CustomEvent { constructor(type, options) { this.type = type; this.detail = options.detail; } } }, createElement: () => new FakeNode(doc) };
  const host = new FakeNode(doc);
  return { host, doc };
}

function apiFor(values, calls = {}) {
  return {
    async getOverview(query) { calls.overview = query; return values[0]; },
    async listTasks(query) { calls.tasks = query; return values[1]; },
    async listProposals(query) { calls.proposals = query; return values[2]; },
  };
}

test('uses the shared snapshot, sums only approved active cash inflows, and keeps proposal estimates separate', () => {
  const values = responses({
    tasks: [
      task(),
      task({ task_id: 'TASK-UNKNOWN', proposal_id: 'PROP-UNKNOWN', title: '金额或日期未提供事项', accounting: { expected_cash_cny: null, actual_cash_cny: null }, candidate_calculation: { expected_cash_in_cny: null, cash_flow: [] }, created_at: '2026-10-02T10:00:00+08:00' }),
      task({ task_id: 'TASK-DONE', proposal_id: 'PROP-DONE', title: '已核销历史事项', display_status: 'completed', status: 'completed', accounting: { expected_cash_cny: 9000, actual_cash_cny: 8700 }, created_at: '2026-10-01T10:00:00+08:00' }),
      task({ task_id: 'TASK-NEXT-WEEK', title: '下周才预计回款', accounting: { expected_cash_cny: 5000, actual_cash_cny: null }, candidate_calculation: { expected_cash_in_cny: 5000, cash_flow: [{ direction: 'in', amount_cny: 5000, expected_at: '2026-10-25', status: 'forecast' }] } }),
    ],
    proposals: [proposal({ calculation: { expected_cash_in_cny: 999999 } })],
  });
  const view = cashOpportunity.normalizeData(...values, context);
  const html = cashOpportunity.render(view);

  assert.equal(view.expectedTotal, 6400);
  assert.equal(view.unknownCount, 1);
  assert.equal(view.knownCount, 2);
  assert.equal(view.openTasks.length, 3);
  assert.equal(view.lastCashItem.task_id, 'TASK-DONE');
  assert.match(html, /已知预计回款/);
  assert.match(html, /金额或到账日期未知，未计入已知金额/);
  assert.match(html, /¥8,700\.00/);
  assert.match(html, /¥999,999\.00/);
  assert.match(html, /不计入已批准预测/);
});

test('unknown and absent amounts stay unknown rather than becoming zero', () => {
  const noExpected = cashOpportunity.normalizeData(...responses({ tasks: [task({ accounting: { expected_cash_cny: null, actual_cash_cny: null }, candidate_calculation: { expected_cash_in_cny: null, cash_flow: [] } })] }), context);
  const html = cashOpportunity.render(noExpected);
  assert.equal(noExpected.expectedTotal, null);
  assert.equal(noExpected.unknownCount, 1);
  assert.match(html, /已知预计回款/);
  assert.match(html, /金额或到账日期未知，未计入已知金额/);
});

test('store selection filters tasks by either the origin or destination store', () => {
  const selectedContext = { ...context, storeId: 'ST-002' };
  const view = cashOpportunity.normalizeData(...responses({ tasks: [task(), task({ task_id: 'TASK-OTHER', plan: { actions: [{ store_id: 'ST-003' }] } })] }), selectedContext);
  assert.equal(view.openTasks.length, 1);
  assert.equal(view.openTasks[0].task_id, 'TASK-1');
  assert.equal(view.expectedTotal, 6400);
});

test('weekly window ends at the next Monday and includes a forecast due on Sunday', () => {
  const sundayContext = { ...context, asOf: '2026-10-04T11:00:00+08:00' };
  const sundayTask = task({ candidate_calculation: { expected_cash_in_cny: 6400, cash_flow: [{ direction: 'in', amount_cny: 6400, expected_at: '2026-10-04', status: 'forecast' }] } });
  const view = cashOpportunity.normalizeData(...responses({ tasks: [sundayTask] }), sundayContext);
  assert.equal(view.week.start, '2026-10-04');
  assert.equal(view.week.end, '2026-10-05');
  assert.equal(view.expectedTotal, 6400);
});

test('mount reads overview, tasks, and pending proposals with the same pinned snapshot; navigation keeps item identity', async () => {
  const { host, doc } = fakeContainer();
  const calls = {};
  const destinations = [];
  const mounted = cashOpportunity.mount(host, {
    api: apiFor(responses({ tasks: [task()], proposals: [proposal()] }), calls),
    context,
    navigate: (route, nextContext) => destinations.push({ route, context: nextContext }),
  });
  await mounted.ready;

  assert.equal(calls.overview.snapshot_id, context.snapshotId);
  assert.equal(calls.tasks.as_of, context.asOf);
  assert.equal(calls.proposals.fact_version, context.factVersion);
  assert.equal(calls.proposals.status, 'pending_approval');
  assert.match(host.children[0].innerHTML, /本周预计可释放现金/);
  assert.match(host.children[0].innerHTML, /查看金额依据/);
  host.children[0].clickAction('open-next', { kind: 'proposal', id: 'PROP-PENDING' });
  assert.equal(destinations[0].route, 'execution-followup');
  assert.equal(destinations[0].context.proposalId, 'PROP-PENDING');
  mounted.destroy();
  assert.equal(host.children.length, 0);
});

test('a failed HTTP read renders an error and never falls back to example amounts', async () => {
  const { host } = fakeContainer();
  const mounted = cashOpportunity.mount(host, {
    context,
    api: {
      async getOverview() { throw Object.assign(new Error('服务不可用（503）'), { code: 'http_503' }); },
      async listTasks() { throw new Error('must not run'); },
      async listProposals() { throw new Error('must not run'); },
    },
  });
  await mounted.ready;

  assert.equal(mounted.getState().view, null);
  assert.match(host.children[0].innerHTML, /服务不可用（503）/);
  assert.doesNotMatch(host.children[0].innerHTML, /380,000|38\.00/);
  assert.ok(host.events.some((event) => event.type === 'hackathon:error' && event.detail.retryable));
  mounted.destroy();
});

test('rejects responses from a different snapshot instead of mixing values', async () => {
  const { host } = fakeContainer();
  const values = responses({ tasks: [task()] });
  values[1] = { ...values[1], context: { ...values[1].context, fact_version: 2 } };
  const mounted = cashOpportunity.mount(host, { api: apiFor(values), context });
  await mounted.ready;
  assert.equal(mounted.getState().view, null);
  assert.match(host.children[0].innerHTML, /执行任务返回的fact_version与当前场景不一致/);
  mounted.destroy();
});

test('details expand and export includes both approved and pending items with explicit inclusion status', async () => {
  const { host, doc } = fakeContainer();
  const downloads = {};
  doc.body = new FakeNode(doc);
  doc.defaultView.Blob = class Blob { constructor(parts, options) { downloads.content = parts.join(''); downloads.type = options.type; } };
  doc.defaultView.URL = { createObjectURL: () => 'blob:cash-list', revokeObjectURL: (value) => { downloads.revoked = value; } };
  const originalCreate = doc.createElement;
  doc.createElement = (tag) => {
    const node = originalCreate();
    if (tag === 'a') downloads.link = node;
    return node;
  };
  const values = responses({ tasks: [task()], proposals: [proposal()] });
  const mounted = cashOpportunity.mount(host, { api: apiFor(values), context, navigate() {} });
  await mounted.ready;
  const root = host.children[0];
  root.clickAction('details');
  assert.match(root.innerHTML, /预计回款如何汇总/);
  root.clickAction('export');
  assert.match(downloads.content, /已批准任务/);
  assert.match(downloads.content, /待确认方案/);
  assert.match(downloads.content, /否：尚未确认/);
  assert.equal(downloads.link.clicked, true);
  assert.equal(downloads.revoked, 'blob:cash-list');
  assert.match(root.innerHTML, /处置清单已导出/);
  mounted.destroy();
});

test('missing API methods or context are explicit errors, not default-scenario requests', async () => {
  const { host } = fakeContainer();
  const mounted = cashOpportunity.mount(host, { api: {}, context: { scenarioId: 'S01' } });
  await mounted.ready;
  assert.match(host.children[0].innerHTML, /场景上下文不完整/);
  assert.equal(mounted.getState().view, null);
  mounted.destroy();
});

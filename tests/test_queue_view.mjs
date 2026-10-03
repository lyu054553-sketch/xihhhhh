import test from 'node:test';
import assert from 'node:assert/strict';
import { taskContext, taskContextMarkup, filterQueue } from '../assets/js/queue-view.mjs';

function proposal(id = 'P-1', status = 'approved', version = 2) {
  return { id, status, current_version: version, tenant_id: 'demo', risk_id: 1,
    version: { proposal_id: id, version, payload: { proposal_type: 'transfer',
      input: { risk_id: 1, product: '每日坚果', sku: 'SKU-NUT', source_store: '文三店', target_store: '未来店', quantity: 20 },
      basis: { risk_id: 1, proposal_version: version } } } };
}
const task = (id = 'T-1', proposalId = 'P-1', status = 'in_transit', version = 2) =>
  ({ id, proposal_id: proposalId, proposal_version: version, tenant_id: 'demo', status });

test('business identity uses the exact proposal id and saved version', () => {
  const value = taskContext(task(), [proposal('another'), proposal()]);
  assert.equal(value.matched, true);
  assert.equal(value.reason, null);
  assert.equal(value.product, '每日坚果');
  assert.equal(value.store, '文三店');
  assert.equal(value.targetStore, '未来店');
  assert.equal(value.sku, 'SKU-NUT');
  assert.equal(value.moduleType, 'transfer');
  assert.equal(value.riskId, 1);
});

test('an old task never borrows identity from a newer proposal or similar product', () => {
  for (const proposals of [[proposal('P-1', 'approved', 3)], [proposal('P-2')]]) {
    const value = taskContext(task(), proposals);
    assert.equal(value.matched, false);
    for (const field of ['product', 'sku', 'store', 'targetStore', 'moduleType', 'riskId']) assert.equal(value[field], null);
    assert.equal(value.proposalId, 'P-1');
    assert.equal(value.proposalVersion, 2);
    assert.match(taskContextMarkup(value), /未提供／待核对/);
  }
});

test('duplicates and explicit cross-tenant links are ambiguous rather than first-match wins', () => {
  assert.equal(taskContext(task(), [proposal(), proposal()]).reason, 'duplicate_proposal');
  assert.equal(taskContext(task(), [{ ...proposal(), tenant_id: 'other' }]).reason, 'tenant_mismatch');
});

test('nested saved-version, risk and basis references must agree', () => {
  for (const change of [
    value => value.version.proposal_id = 'P-2',
    value => value.version.version = 1,
    value => value.version.payload.input.risk_id = 2,
    value => value.version.payload.basis.risk_id = 2,
    value => value.version.payload.basis.proposal_version = 1,
  ]) {
    const value = proposal(); change(value);
    assert.equal(taskContext(task(), [value]).matched, false);
  }
});

test('missing saved fields remain unknown instead of using live proposal summaries', () => {
  const value = proposal();
  value.product = '来自另一份当前事实';
  value.version.payload.input = null;
  const context = taskContext(task(), [value]);
  assert.equal(context.matched, true);
  assert.equal(context.reason, 'missing_details');
  assert.equal(context.product, null);
  assert.equal(context.store, null);
  assert.doesNotMatch(taskContextMarkup(context), /来自另一份当前事实/);
});

test('all workbench types retain their saved store fields without inventing a route', () => {
  for (const moduleType of ['expiry-rescue', 'procurement-brake', 'unknown']) {
    const value = proposal();
    value.version.payload.proposal_type = moduleType;
    value.version.payload.input.store = '批次所在店';
    const context = taskContext(task(), [value]);
    assert.equal(context.store, '批次所在店');
    assert.equal(context.targetStore, null);
    assert.equal(context.moduleType, moduleType === 'unknown' ? null : moduleType);
  }
});

test('empty inputs and invalid version identities remain explicitly unavailable', () => {
  assert.equal(taskContext(null, null).reason, 'missing_identity');
  for (const version of [null, 0, -1, '2', NaN]) {
    assert.equal(taskContext(task('T-1', 'P-1', 'in_transit', version), [proposal()]).matched, false);
  }
  assert.equal(taskContext(task(), []).reason, 'missing_proposal');
  assert.equal(taskContext(task(), [{ ...proposal(), version: null }]).reason, 'invalid_version');
  assert.deepEqual(filterQueue(null), { tab: 'pending', query: '', total: 0, shown: 0, work: [], proposals: [], tasks: [] });
  assert.throws(() => filterQueue({}, { tab: 'all' }), /未知待办分类/);
});

test('task business text is escaped exactly once', () => {
  const value = proposal();
  value.version.payload.input.product = '<img src=x onerror="alert(1)">';
  value.version.payload.input.source_store = '门店 & 仓库';
  const html = taskContextMarkup(taskContext(task(), [value]));
  assert.doesNotMatch(html, /<img|onerror="/);
  assert.match(html, /&lt;img/);
  assert.match(html, /门店 &amp; 仓库/);
  assert.doesNotMatch(html, /&amp;amp;/);
});

function queue() {
  return {
    work: [{ id: 'W-1', route: 'transfer', title: '文三店每日坚果' }, { id: 'W-2', route: 'approvals' }, { id: 'W-3', route: 'execution' }],
    proposals: [proposal('P-pending', 'pending_approval'), proposal('P-unassigned'), proposal('P-1'),
      ...['draft', 'needs_replan', 'replan_pending', 'invalidated'].map(status => proposal(`P-${status}`, status))],
    tasks: [task(), task('T-done', 'P-1', 'completed'), task('T-received', 'P-1', 'received'), task('T-error', 'P-1', 'exception')],
  };
}

test('each tab retains its existing status boundary and does not duplicate an assigned proposal', () => {
  const data = queue();
  assert.deepEqual(filterQueue(data, { tab: 'actions' }).work.map(item => item.id), ['W-1']);
  assert.deepEqual(filterQueue(data).proposals.map(item => item.id), ['P-pending']);
  const followup = filterQueue(data, { tab: 'followup' });
  assert.deepEqual(followup.proposals.map(item => item.id), ['P-unassigned']);
  assert.deepEqual(followup.tasks.map(item => item.id), ['T-1', 'T-error']);
  assert.equal(followup.total, 3);
  assert.deepEqual(filterQueue(data, { tab: 'completed' }).tasks.map(item => item.id), ['T-done', 'T-received']);
  assert.equal(filterQueue(data, { tab: 'drafts' }).proposals.length, 4);
});

test('search uses product, store, sku, proposal and task identities inside the selected tab', () => {
  const data = queue();
  for (const query of ['文三 坚果', 'sku-nut', '未来店']) {
    const result = filterQueue(data, { tab: 'completed', query });
    assert.equal(result.total, 2);
    assert.equal(result.shown, 2);
    assert.equal(result.proposals.length, 0);
  }
  assert.deepEqual(filterQueue(data, { tab: 'completed', query: 't-done' }).tasks.map(item => item.id), ['T-done']);
  assert.equal(filterQueue(data, { tab: 'pending', query: 'T-done' }).shown, 0);
  assert.equal(filterQueue(data, { tab: 'followup', query: 'P-1' }).tasks.length, 2);
  assert.equal(filterQueue(data, { tab: 'actions', query: '文三 坚果' }).shown, 1);
});

test('current proposal summaries stay searchable without leaking their identity into task history', () => {
  const seed = proposal('P-seed', 'pending_approval');
  delete seed.version.payload.input;
  seed.version.payload.actions = [{ type: 'transfer' }];
  seed.approval_summary = { title: '缺货补充方案' };
  seed.product = '海盐苏打饼干';
  seed.store = '钱江门店';
  const data = { proposals: [seed], tasks: [
    task('T-old', seed.id, 'in_transit', 1),
    task('T-current', seed.id, 'in_transit', seed.current_version),
  ] };
  for (const query of ['缺货补充', '海盐苏打', '钱江门店']) {
    assert.deepEqual(filterQueue(data, { tab: 'pending', query }).proposals, [seed]);
    assert.equal(filterQueue(data, { tab: 'followup', query }).tasks.length, 0);
  }
  assert.equal(filterQueue(data, { tab: 'followup', query: seed.id }).tasks.length, 2);
});

test('query is literal text, handles blank values, and never treats metacharacters as regex', () => {
  const data = queue();
  data.work[0].title = '<script>alert(1)</script> [门店]';
  assert.equal(filterQueue(data, { tab: 'actions', query: '<script>' }).shown, 1);
  assert.equal(filterQueue(data, { tab: 'actions', query: '.*' }).shown, 0);
  assert.equal(filterQueue(data, { tab: 'actions', query: '[门店]' }).shown, 1);
  assert.equal(filterQueue(data, { tab: 'actions', query: '  ' }).shown, 1);
  assert.equal(filterQueue(data, { tab: 'actions', query: null }).query, '');
});

test('old or ambiguous task versions are searchable by identifiers but not newer business facts', () => {
  for (const proposals of [[proposal('P-1', 'approved', 3)], [proposal(), proposal()]]) {
    const data = { proposals, tasks: [task()] };
    assert.equal(filterQueue(data, { tab: 'followup', query: '文三店' }).tasks.length, 0);
    assert.equal(filterQueue(data, { tab: 'followup', query: 'T-1' }).tasks.length, 1);
    assert.equal(filterQueue(data, { tab: 'followup', query: 'P-1' }).tasks.length, 1);
  }
});

test('completed tasks from older versions never hide a newly approved proposal', () => {
  const current = proposal('P-1', 'approved', 2);
  const data = { proposals: [current], tasks: [task('T-old', current.id, 'completed', 1)] };
  assert.deepEqual(filterQueue(data, { tab: 'followup' }).proposals, [current]);
  assert.deepEqual(filterQueue(data, { tab: 'completed' }).tasks, data.tasks);
  data.tasks.push(task('T-current', current.id, 'draft_pending_external_execution', 2));
  const result = filterQueue(data, { tab: 'followup' });
  assert.deepEqual(result.proposals, []);
  assert.deepEqual(result.tasks.map(item => item.id), ['T-current']);
});

test('a task for another tenant or proposal cannot hide an approved proposal', () => {
  const data = { proposals: [proposal()], tasks: [{ ...task(), tenant_id: 'other' }, task('T-2', 'P-2')] };
  const result = filterQueue(data, { tab: 'followup' });
  assert.equal(result.proposals.length, 1);
  assert.equal(result.tasks.length, 2, 'filtering must not silently discard returned task rows');
  assert.equal(result.total, 3);
});

test('filtering preserves response order, amounts, duplicates and input objects', () => {
  const data = queue();
  data.tasks.push(structuredClone(data.tasks[0]));
  data.proposals[0].amount = '999.99';
  const before = structuredClone(data);
  const result = filterQueue(data, { tab: 'followup', query: 'T-' });
  assert.deepEqual(result.tasks.map(item => item.id), ['T-1', 'T-error', 'T-1']);
  assert.equal(result.tasks[0], data.tasks[0]);
  assert.deepEqual(data, before);
  assert.equal(filterQueue(data, { tab: 'pending', query: '999.99' }).shown, 0);
});

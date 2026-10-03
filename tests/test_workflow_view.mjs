import test from 'node:test';
import assert from 'node:assert/strict';
import { calculationSummary, proposalSummary, workItemsMarkup, workflowStatus } from '../assets/js/workflow-view.mjs';

const calculation = () => ({
  valid: true,
  allocation: { quantity: 40 },
  before_after: {
    source: { store: '调出店', on_hand_before: 120, on_hand_after: 80, safety_stock: 20, coverage_after: 25 },
    target: { store: '接收店', on_hand_before: 10, on_hand_after: 50, safety_stock: 6, coverage_after: 10 },
  },
  cash: { inventory_cost: '3200.00', known_cash_effect: '-86.00', estimated_net_cash_improvement: null, note: '内部调拨不产生现金释放。' },
  economic: { transport_fee: '86.00', net_avoidable_loss: '3034.00', note: '估算避免报损，不是实际到账。' },
});
const item = (route, riskId = 1) => ({ id: 'W-001', route, risk_id: riskId, title: '门店需要核查', reason: '销量与库存待核对', owner: '负责人', priority: '高', due_date: '今天', impact: '库存占用由服务返回' });

test('transfer presents the returned yuan amounts without fen conversion or cash invention', () => {
  const html = calculationSummary('transfer', calculation(), { source_store: '调出店', target_store: '接收店', unit: '件' });
  assert.match(html, /¥3,200\.00/);
  assert.match(html, /¥86\.00/);
  assert.match(html, /¥3,034\.00/);
  assert.match(html, /¥-86\.00/);
  assert.match(html, /预计净现金改善<\/dt><dd>未接入／待补充/);
  assert.doesNotMatch(html, /¥32\.00|¥0\.86/);
});

test('missing transfer quantities and monetary fields remain unknown', () => {
  const html = calculationSummary('transfer', { valid: true }, {});
  assert.match(html, /未接入／待补充/);
  assert.match(html, /单位未提供/);
  assert.doesNotMatch(html, /¥0\.00|>0<|>0 件/);
});

test('expiry has distinct zero fees and unknown cash effects', () => {
  const html = calculationSummary('expiry-rescue', {
    valid: true,
    forecast: { normal_sale_qty: null, expected_remaining_qty: 0, latest_disposal_date: '2026-10-18' },
    alternatives: [{ type: '退供', quantity: null, fee: 0, cash_impact: null, assumption: '供应商条款未接入' }],
    cash: { known_cash_effect: null, estimated_net_cash_improvement: null },
  }, { store: '门店', unit: '袋' });
  assert.match(html, /预计正常售出<\/span><strong class="value">未接入／待补充 袋/);
  assert.match(html, /预计剩余数量<\/span><strong class="value">0 袋/);
  assert.match(html, /<td>¥0\.00<\/td><td>未接入／待补充<\/td>/);
  assert.match(html, /供应商条款未接入/);
});

test('procurement does not turn absent in-transit stock or deferred payments into zero', () => {
  const html = calculationSummary('procurement-brake', {
    valid: true, inventory_position: { current_inventory: 0, in_transit_qty: null },
    payment: { adjusted_amount: '2360.00', deferred_payment_pressure: null }, cash: {}, order: {},
  }, { unit: '瓶' });
  assert.match(html, /当前库存<\/span><strong class="value">0 瓶/);
  assert.match(html, /在途数量<\/span><strong class="value">未接入／待补充 瓶/);
  assert.match(html, /¥2,360\.00/);
  assert.match(html, /递延至后续的付款压力<\/dt><dd>未接入／待补充/);
});

test('all three summaries keep fully missing calculations unknown rather than zero-filled', () => {
  for (const type of ['transfer', 'expiry-rescue', 'procurement-brake']) {
    const html = calculationSummary(type, { valid: true, cash: { known_cash_effect: null, estimated_net_cash_improvement: null } }, {});
    assert.match(html, /未接入／待补充/, type);
    assert.doesNotMatch(html, /¥0\.00/, type);
  }
});

test('returned inventories and amounts are displayed without deriving replacements from inputs', () => {
  const value = calculation();
  value.before_after.source.on_hand_after = 77;
  value.economic.net_avoidable_loss = '123.45';
  value.cash.estimated_net_cash_improvement = null;
  const html = calculationSummary('transfer', value, { quantity: 40, source_on_hand: 120, unit_cost: 80, transport_fee: 86, unit: '件' });
  assert.match(html, /<td>77 件<\/td>/);
  assert.match(html, /¥123\.45/);
  assert.doesNotMatch(html, /<td>80 件<\/td>|¥3,034\.00/);
});

test('unpassed calculations never get a successful business summary', () => {
  assert.equal(calculationSummary('transfer', null), '');
  assert.equal(calculationSummary('transfer', { ...calculation(), valid: false }), '');
  assert.equal(calculationSummary('expiry-rescue', { valid: false, forecast: { normal_sale_qty: 100 } }), '');
});

test('server-provided text is escaped in calculations and proposal explanations', () => {
  const attack = '<img src=x onerror="alert(1)">';
  const value = calculation();
  value.before_after.source.store = attack;
  value.cash.note = attack;
  value.cash.assumptions = [attack];
  value.cash.missing_fields = [attack];
  value.economic.note = attack;
  const html = proposalSummary({ approval_summary: { detail: attack, boundary: attack }, version: { payload: { proposal_type: 'transfer', calculation: value, input: { source_store: attack, target_store: attack, unit: attack } } } });
  assert.doesNotMatch(html, /<img|<script/);
  assert.match(html, /&lt;img/);
  assert.match(html, /&quot;alert\(1\)&quot;/);
});

test('units are escaped once in both table cells and metric values', () => {
  const unit = '袋 & 瓶';
  const transfer = calculationSummary('transfer', calculation(), { unit });
  const expiry = calculationSummary('expiry-rescue', { valid: true, forecast: { normal_sale_qty: 2, expected_remaining_qty: 0 }, alternatives: [{ type: '调拨', quantity: 1, fee: 0, cash_impact: null }] }, { unit });
  const procurement = calculationSummary('procurement-brake', { valid: true, inventory_position: { current_inventory: 3 }, cash: {} }, { unit });
  for (const html of [transfer, expiry, procurement]) {
    assert.match(html, /袋 &amp; 瓶/);
    assert.doesNotMatch(html, /&amp;amp;/);
  }
});

test('proposal summary presents its saved version and explicit execution boundary', () => {
  const html = proposalSummary({ approval_summary: { detail: '确认当前方案数量', boundary: '生成任务不代表已经出库' }, version: { payload: { proposal_type: 'transfer', calculation: calculation(), input: { unit: '袋' } } } });
  assert.match(html, /确认当前方案数量/);
  assert.match(html, /生成任务不代表已经出库/);
  assert.match(html, /40 袋/);
});

test('dirty workbench status takes precedence over an old approved proposal', () => {
  const html = workflowStatus({ dirty: true, draft: { status: 'saved' }, proposal: { current_version: 9, status: 'approved' } });
  assert.match(html, /输入已变化，需要重新计算/);
  assert.doesNotMatch(html, /方案 V9|已审批 · 待生成任务/);
});

test('server dirty, blocked and calculated drafts cannot display an old approval as current progress', () => {
  const expected = { needs_recalculation: '需要重新计算', blocked: '约束未通过', calculated: '核对后保存方案版本' };
  for (const [status, label] of Object.entries(expected)) {
    const html = workflowStatus({ dirty: false, draft: { status }, proposal: { current_version: 9, status: 'approved' } });
    assert.ok(html.includes(label));
    assert.doesNotMatch(html, /方案 V9|已审批 · 待生成任务/);
  }
});

test('saved workflow can display the actual proposal version without upgrading its state', () => {
  const html = workflowStatus({ dirty: false, draft: { status: 'saved' }, proposal: { current_version: 2, status: 'pending_approval' } });
  assert.match(html, /方案 V2 · 待审批/);
  assert.doesNotMatch(html, /已审批 · 待生成任务|已生成待执行任务/);
});

test('work items only expose supported workbenches and diagnosis routes', () => {
  for (const route of ['transfer', 'expiry-rescue', 'procurement-brake']) {
    const html = workItemsMarkup([item(route)]);
    assert.match(html, /data-action="open-workbench"/);
    assert.ok(html.includes(`data-module="${route}"`));
    assert.match(html, /data-risk-id="1"/);
  }
  for (const route of ['slow-diagnosis', 'slow_moving']) assert.match(workItemsMarkup([item(route)]), /data-risk="1"/);
});

test('unsupported routes never invent an action or use route text as a URL', () => {
  for (const route of ['approvals', 'execution', 'unknown', 'javascript:alert(1)', 'transfer" onclick="alert(1)']) {
    const html = workItemsMarkup([item(route)]);
    assert.doesNotMatch(html, /<button|href=|onclick=/);
    assert.match(html, /对应记录/);
  }
});

test('invalid or absent risk identifiers cannot launch a workbench', () => {
  for (const riskId of [null, undefined, 0, -1, 1.5, '1', Number.MAX_SAFE_INTEGER + 1]) {
    const html = workItemsMarkup([{ ...item('transfer'), risk_id: riskId }]);
    assert.doesNotMatch(html, /<button/);
  }
  assert.match(workItemsMarkup([{ ...item('transfer', 1), workbench_risk_id: 8 }]), /data-risk-id="8"/);
});

test('work items retain backend order, escaped text and displayed impact', () => {
  const attack = '<svg onload="alert(1)">';
  const records = [{ ...item('transfer'), id: 'B', title: attack, owner: attack, reason: attack, impact: attack, action_label: attack }, { ...item('transfer', 2), id: 'A', title: 'second' }];
  const before = structuredClone(records);
  const html = workItemsMarkup(records);
  assert.ok(html.indexOf('data-work-id="B"') < html.indexOf('data-work-id="A"'));
  assert.doesNotMatch(html, /<svg|<script/);
  assert.match(html, /&lt;svg/);
  assert.deepEqual(records, before);
});

test('an empty work queue is an explicit empty state with no fabricated actions', () => {
  const html = workItemsMarkup([]);
  assert.match(html, /暂无待评估事项/);
  assert.doesNotMatch(html, /<button|data-risk=/);
});

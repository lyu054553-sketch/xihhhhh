import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync, readdirSync } from 'node:fs';
import {
  AGENT_TYPES, RUN_STATUSES, ContractError, buildRunRequest, validateRunResponse,
  validateDecisionResponse, formatFen, formatMetric,
} from '../assets/js/agent-contract.mjs';
import { AGENT_CONFIG, paramsFromValues, yuanToFen } from '../assets/js/agent-config.mjs';

const makeRequest = (extra = {}) => buildRunRequest({
  agentType: 'slow_moving', scope: { as_of: '2026-10-02', store_ids: ['STORE-HZ-001'] },
  params: {}, dataVersion: 'snack-demo-v1', policyVersion: 'snack-policy-v1', ...extra,
});
const makeItem = () => ({
  item_id: 'ITEM-001', entity: { store_id: 'STORE-HZ-001', sku_id: 'SNK-002', unit: 'bag' }, priority: 'high',
  metrics: [{ key: 'inventory_value_at_cost_fen', label: '库存成本', value: 22000, unit: 'fen' }],
  evidence: [{ source: 'skus', record_id: 'SNK-002', field: 'unit_cost_fen', value: 880, as_of: '2026-10-02' }],
  recommendations: [{ recommendation_id: 'REC-001', action_type: 'pause_replenishment', action_params: { sku_id: 'SNK-002' },
    rationale: '暂停补货并核查', evidence_ids: ['SNK-002'], approval_required: true,
    impact_estimate: { kind: 'avoid_future_purchase', amount_fen: null, period_days: 30, assumptions: ['待采购数据'] },
  }],
  details: { target_stock_qty: 8, excess_qty: 17 },
});
const makeResponse = (request, extra = {}) => ({
  request_id: request.request_id, run_id: 'run-001', agent_type: request.agent_type, status: 'succeeded',
  summary: '合成数据测算', session_id: request.session_id ?? null, assistant_message: '请核对证据', scenario_preview: null,
  steps: [{ step_id: 'step-1', name: 'query_inventory', label: '读取库存', status: 'succeeded', message: '已读取指定版本' }],
  items: [makeItem()], missing_fields: [], follow_up_questions: [], warnings: [], error: null,
  data_version: request.data_version, policy_version: request.policy_version ?? 'snack-policy-v1',
  created_at: '2026-10-02T10:00:00+08:00', completed_at: '2026-10-02T10:00:01+08:00', ...extra,
});
const makePreview = () => ({
  scenario_id: 'SCN-1', title: '少采购 6 袋', horizon_days: 30, store_ids: ['STORE-HZ-003'],
  adjustments: [{ action_type: 'reduce_open_purchase_order', action_params: { po_id: 'PO-003', sku_id: 'SNK-002', qty: 6, unit: 'bag' } }],
  assumptions: ['仅调整可取消的未到货数量'], confirmation_required: true,
});
const rejectsChange = (mutate, request = makeRequest()) => {
  const response = makeResponse(request);
  mutate(response);
  assert.throws(() => validateRunResponse(response, request), (error) => error instanceof ContractError && error.outcomeUnknown);
};

const fixtureRoot = new URL('./fixtures/v03/', import.meta.url);
for (const filename of readdirSync(fixtureRoot).filter((name) => /^response-.*\.json$/.test(name))) {
  test(`checked-in contract fixture conforms: ${filename}`, () => {
    const payload = JSON.parse(readFileSync(new URL(filename, fixtureRoot), 'utf8'));
    const params = payload.agent_type === 'cashflow_simulation'
      ? payload.status === 'awaiting_confirmation' ? { operation: 'preview' }
        : { operation: 'simulate', scenario_id: 'SCN-PO-003-REDUCE-6', confirmed: true, adjustments: [] }
      : {};
    const request = makeRequest({ requestId: payload.request_id, agentType: payload.agent_type, params,
      sessionId: payload.session_id, dataVersion: payload.data_version, policyVersion: payload.policy_version });
    assert.equal(validateRunResponse(payload, request), payload);
    assert.doesNotMatch(JSON.stringify(payload), /\?{3,}/, 'fixtures must preserve UTF-8 text');
  });
}

test('all five Agent types use the same UUID request and preserve explicit version scope', () => {
  assert.equal(AGENT_TYPES.length, 5);
  for (const agentType of AGENT_TYPES) {
    const request = makeRequest({ agentType, params: agentType === 'cashflow_simulation' ? { operation: 'preview' } : {} });
    assert.match(request.request_id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    assert.equal(request.agent_type, agentType);
    assert.equal(request.scope.as_of, '2026-10-02');
    assert.equal(request.policy_version, 'snack-policy-v1');
  }
});

test('request snapshots do not share mutable form objects and optional policy stays optional', () => {
  const scope = { as_of: '2026-10-02', store_ids: [] }, params = { sales_window_days: 14 };
  const request = makeRequest({ scope, params, policyVersion: undefined, userInput: '' });
  params.sales_window_days = 7;
  scope.store_ids.push('foreign-store');
  assert.equal(request.params.sales_window_days, 14);
  assert.deepEqual(request.scope.store_ids, []);
  assert.equal(Object.hasOwn(request, 'policy_version'), false);
  assert.equal(request.user_input, '');
});

test('request validation rejects invalid IDs, dates, arrays, amounts and unknown Agent types', () => {
  for (const invalid of [
    { requestId: 'turn-001' }, { agentType: 'transfer' }, { dataVersion: '' },
    { scope: { as_of: '2026-02-30' } }, { scope: { as_of: '2026-10-02', store_ids: 'STORE-HZ-001' } },
    { params: { min_inventory_value_fen: 1.25 } }, { params: { max_transfer_qty: '6' } },
    { params: new Date('2026-10-02') },
  ]) assert.throws(() => makeRequest(invalid), ContractError);
});

test('fen formatting retains exact pennies, zero, unknown and the safe integer boundary', () => {
  assert.equal(formatFen(22000), '¥220.00');
  assert.equal(formatFen(5280), '¥52.80');
  assert.equal(formatFen(0), '¥0.00');
  assert.equal(formatFen(-1), '-¥0.01');
  assert.equal(formatFen(null), '未知');
  assert.equal(formatFen(Number.MAX_SAFE_INTEGER), '¥90,071,992,547,409.91');
  for (const invalid of ['22000', 0.1, Infinity, NaN, Number.MAX_SAFE_INTEGER + 1]) assert.throws(() => formatFen(invalid), ContractError);
});

test('yuan form inputs become exact integer fen without floating-point multiplication', () => {
  assert.equal(yuanToFen('0.29'), 29);
  assert.equal(yuanToFen('220.00'), 22000);
  assert.equal(yuanToFen('0'), 0);
  assert.equal(yuanToFen('90071992547409.91'), Number.MAX_SAFE_INTEGER);
  for (const invalid of ['0.001', '1e2', '-1', '', '90071992547409.92', 'Infinity']) assert.throws(() => yuanToFen(invalid));
});

test('five Agent forms produce typed contract parameters and explicit preview operation', () => {
  for (const agentType of AGENT_TYPES) {
    const values = Object.fromEntries(AGENT_CONFIG[agentType].fields.map((field) => [field.key, structuredClone(field.value)]));
    const params = paramsFromValues(agentType, values);
    const request = makeRequest({ agentType, params });
    assert.deepEqual(request.params, params);
    if (agentType === 'slow_moving') {
      assert.equal(params.min_inventory_value_fen, 20000);
      assert.equal(Object.hasOwn(params, 'min_inventory_value_yuan'), false);
    }
    if (agentType === 'store_transfer') assert.deepEqual(params.source_store_ids, ['STORE-HZ-001']);
    if (agentType === 'procurement_brake') {
      assert.equal(params.include_open_orders, true);
      assert.equal(params.horizon_days, 14);
    }
    if (agentType === 'cashflow_simulation') assert.equal(params.operation, 'preview');
  }
});

test('metric formatting preserves fractional units and formats ratios without changing business values', () => {
  assert.equal(formatMetric({ key: 'qty', label: '数量', value: 1.25, unit: 'kg' }), '1.25 kg');
  assert.equal(formatMetric({ key: 'discount_ratio', label: '比例', value: 0.15, unit: 'ratio' }), '15%');
  assert.equal(formatMetric({ key: 'qty', label: '数量', value: null, unit: 'bag' }), '未知');
  for (const invalid of [
    { key: 'cost_fen', label: '成本', value: 22000, unit: 'yuan' },
    { key: 'cost', label: '成本', value: 22000, unit: 'fen' },
    { key: 'cost', label: '成本', value: 220, unit: 'CNY' },
    { key: 'qty', label: '数量', value: '1.25', unit: 'kg' },
    { key: 'days', label: '天数', value: Infinity, unit: 'day' },
    { key: 'ratio', label: '比例', value: 15, unit: '%' },
  ]) assert.throws(() => formatMetric(invalid), ContractError);
});

test('a complete unified response is returned unchanged; unspecified details remain extensible', () => {
  const request = makeRequest(), response = makeResponse(request);
  response.items[0].details = { additional_tool_result: { note: '新增字段', qty: 1.25, unit: 'kg', cost_fen: null } };
  assert.equal(validateRunResponse(response, request), response);
});

test('all six business statuses have explicit, valid envelopes', () => {
  assert.equal(RUN_STATUSES.length, 6);
  for (const status of RUN_STATUSES) {
    const request = status === 'awaiting_confirmation' ? makeRequest({ agentType: 'cashflow_simulation', params: { operation: 'preview' } }) : makeRequest();
    const response = makeResponse(request, { status });
    if (status === 'no_data') response.items = [];
    if (status === 'needs_input') { response.items = []; response.follow_up_questions = ['请补充成本']; response.missing_fields = ['unit_cost_fen']; }
    if (status === 'failed') { response.items = []; response.error = { code: 'AI_TIMEOUT', message: '模型超时', retryable: true, field_errors: [] }; }
    if (status === 'awaiting_confirmation') { response.items = []; response.scenario_preview = makePreview(); }
    assert.equal(validateRunResponse(response, request).status, status);
  }
});

test('responses cannot cross request, Agent, data, policy or session boundaries', () => {
  const request = makeRequest({ sessionId: 'session-1' });
  for (const key of ['request_id', 'agent_type', 'data_version', 'policy_version', 'session_id']) {
    rejectsChange((response) => { response[key] = key === 'agent_type' ? 'near_expiry' : 'foreign'; }, request);
  }
});

test('an omitted policy permits the actual default version but the response must still report it', () => {
  const request = makeRequest({ policyVersion: undefined }), response = makeResponse(request, { policy_version: 'default-v2' });
  assert.equal(validateRunResponse(response, request).policy_version, 'default-v2');
  delete response.policy_version;
  assert.throws(() => validateRunResponse(response, request), ContractError);
});

test('illegal monetary values cannot hide inside metrics, evidence, details, recommendations or previews', () => {
  for (const invalid of ['880', 880.1, Number.MAX_SAFE_INTEGER + 1]) {
    rejectsChange((response) => { response.items[0].metrics[0].value = invalid; });
    rejectsChange((response) => { response.items[0].evidence[0].value = invalid; });
    rejectsChange((response) => { response.items[0].details.cost_fen = invalid; });
    rejectsChange((response) => { response.items[0].recommendations[0].action_params.price_fen = invalid; });
    rejectsChange((response) => { response.items[0].recommendations[0].impact_estimate.amount_fen = invalid; });
  }
  const request = makeRequest({ agentType: 'cashflow_simulation', params: { operation: 'preview' } });
  const response = makeResponse(request, { status: 'awaiting_confirmation', items: [], scenario_preview: makePreview() });
  response.scenario_preview.adjustments[0].action_params.price_fen = 1.2;
  assert.throws(() => validateRunResponse(response, request), ContractError);
});

test('missing, malformed, unsupported and internally inconsistent responses are rejected', () => {
  for (const offset of ['+08:00', '+0800', 'Z']) {
    const request = makeRequest(), response = makeResponse(request);
    response.created_at = `2026-10-02T10:00:00${offset}`;
    response.completed_at = `2026-10-02T10:00:01${offset}`;
    assert.equal(validateRunResponse(response, request), response);
  }
  for (const mutate of [
    (r) => { delete r.items; }, (r) => { delete r.error; }, (r) => { r.status = 'feasible'; },
    (r) => { r.items = {}; }, (r) => { r.items[0].metrics[0].unit = 'yuan'; },
    (r) => { r.status = 'no_data'; }, (r) => { r.error = { code: 'AI_TIMEOUT', message: '超时', retryable: true, field_errors: [] }; },
    (r) => { r.status = 'failed'; }, (r) => { r.follow_up_questions = ['非 needs_input 不得带问题']; },
    (r) => { r.created_at = '2026-10-02T10:00:00'; }, (r) => { r.completed_at = '2026-02-31T00:00:00Z'; },
    (r) => { r.created_at = '2026-10-02T10:00:00+24:00'; }, (r) => { r.created_at = '2026-10-02T10:00:00+2500'; },
    (r) => { r.items[0].evidence[0].as_of = 'unknown'; },
    (r) => { r.items.push(structuredClone(r.items[0])); }, (r) => { r.items[0].details.qty = '6'; },
  ]) rejectsChange(mutate);
});

test('only completed backend steps are accepted; the UI cannot invent running steps', () => {
  rejectsChange((response) => { response.steps[0].status = 'running'; });
  rejectsChange((response) => { response.steps.push(structuredClone(response.steps[0])); });
});

test('results require source evidence and recommendation links cannot refer to another item', () => {
  rejectsChange((response) => { response.items[0].evidence = []; });
  rejectsChange((response) => { response.items[0].recommendations[0].evidence_ids = ['unrelated-record']; });
  rejectsChange((response) => { response.items[0].recommendations[0].impact_estimate = { kind: 'avoid_future_purchase', amount_fen: 5280, assumptions: [] }; });
});

test('preview cannot leak computed results or bypass the confirmation card', () => {
  const request = makeRequest({ agentType: 'cashflow_simulation', params: { operation: 'preview' } });
  for (const response of [
    makeResponse(request),
    makeResponse(request, { status: 'awaiting_confirmation', scenario_preview: makePreview() }),
    makeResponse(request, { status: 'awaiting_confirmation', items: [], scenario_preview: null }),
    makeResponse(request, { status: 'awaiting_confirmation', items: [], scenario_preview: { ...makePreview(), confirmation_required: false } }),
  ]) assert.throws(() => validateRunResponse(response, request), ContractError);
});

test('scenario adjustments require an allowed action, entity association and quantity unit', () => {
  const request = makeRequest({ agentType: 'cashflow_simulation', params: { operation: 'preview' } });
  for (const mutate of [
    (a) => { a.action_type = 'execute_erp'; }, (a) => { a.action_params = { qty: 6, unit: 'bag' }; },
    (a) => { delete a.action_params.unit; },
  ]) {
    const scenario = makePreview();
    mutate(scenario.adjustments[0]);
    assert.throws(() => validateRunResponse(makeResponse(request, { status: 'awaiting_confirmation', items: [], scenario_preview: scenario }), request), ContractError);
  }
});

test('simulation requests require the confirmed scenario and preserve its exact adjustments', () => {
  const preview = makePreview(), params = { operation: 'simulate', scenario_id: preview.scenario_id, confirmed: true, adjustments: preview.adjustments, assumptions: preview.assumptions };
  const request = makeRequest({ agentType: 'cashflow_simulation', params, sessionId: 'session-1' });
  assert.deepEqual(request.params.adjustments, preview.adjustments);
  assert.equal(request.session_id, 'session-1');
  for (const key of ['scenario_id', 'confirmed', 'adjustments']) {
    const incomplete = { ...params }; delete incomplete[key];
    assert.throws(() => makeRequest({ agentType: 'cashflow_simulation', params: incomplete }), ContractError);
  }
});

test('decision confirmation is scoped to the exact recommendation and only records simulation', () => {
  for (const decision of ['approve', 'reject']) {
    const expected = { run_id: 'run-1', item_id: 'item-1', recommendation_id: 'rec-1', decision };
    const response = { ...expected, decision_status: 'recorded', execution_mode: 'simulation' };
    assert.equal(validateDecisionResponse(response, expected), response);
    for (const key of ['run_id', 'item_id', 'recommendation_id', 'decision', 'decision_status', 'execution_mode']) {
      assert.throws(() => validateDecisionResponse({ ...response, [key]: 'foreign-or-executed' }, expected), (error) => error instanceof ContractError && error.outcomeUnknown);
    }
  }
});

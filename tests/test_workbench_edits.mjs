import test from 'node:test';
import assert from 'node:assert/strict';
import { createWorkbenchEdits, editableInput, sameEditableInput, resolveWorkbenchInput } from '../assets/js/workbench-edits.mjs';
import { RetailContractError, validateWorkbenchDraft } from '../assets/js/retail-contract.mjs';

function transfer(riskId = 1) {
  return {
    risk: { id: riskId },
    input: { risk_id: riskId, target_store_id: 'A', quantity: 10, source_on_hand: 100, unit_cost: '8.80', target_on_hand: 999 },
    transfer_network: [
      { store_id: 'A', name: '门店甲', on_hand: 12, capacity: 80, safety_stock: 6, daily_sales: 4, transport_fee: '20.00', eta_days: 1 },
      { store_id: 'B', name: '门店乙', on_hand: 30, capacity: 100, safety_stock: 10, daily_sales: 8, transport_fee: '36.00', eta_days: 2 },
    ],
  };
}

function expiry(riskId = 1) {
  return { risk: { id: riskId }, input: { risk_id: riskId, transfer_qty: 10, promo_qty: 20, promo_price: '5.50', return_qty: 0, stock_qty: 90 } };
}

function receipt() {
  return { draft: { id: 'DRAFT-1', module_type: 'transfer', risk_id: 1, input: { risk_id: 1, quantity: 12 }, status: 'needs_recalculation', version: 2 } };
}

test('edits are isolated by both risk and workbench module', () => {
  const edits = createWorkbenchEdits(), first = transfer(1), second = transfer(2), nearExpiry = expiry(1);
  edits.capture('transfer', 1, { ...first.input, quantity: 21 }, first.input);
  edits.capture('transfer', 2, { ...second.input, quantity: 32 }, second.input);
  edits.capture('expiry-rescue', 1, { ...nearExpiry.input, promo_qty: 43 }, nearExpiry.input);
  assert.equal(edits.restore('transfer', first).input.quantity, 21);
  assert.equal(edits.restore('transfer', second).input.quantity, 32);
  assert.equal(edits.restore('expiry-rescue', nearExpiry).input.promo_qty, 43);
  assert.equal(edits.has('procurement-brake', 1), false);
  assert.equal(edits.hasRisk(1), true);
  assert.equal(edits.hasRisk(3), false);
});

test('only fields actually changed locally override fresh server choices', () => {
  const edits = createWorkbenchEdits(), initial = transfer();
  edits.capture('transfer', 1, { ...initial.input, quantity: 24 }, initial.input);
  const latest = transfer();
  latest.input.target_store_id = 'B';
  const restored = edits.restore('transfer', latest);
  assert.equal(restored.input.quantity, 24);
  assert.equal(restored.input.target_store_id, 'B');
  assert.equal(restored.input.target_store, '门店乙');
  assert.deepEqual(restored.conflicts, []);
});

test('capturing stale readonly facts cannot overwrite a later GET', () => {
  const edits = createWorkbenchEdits(), initial = transfer();
  edits.capture('transfer', 1, { ...initial.input, quantity: 24, source_on_hand: 1, unit_cost: '0.01' }, initial.input);
  const latest = transfer();
  Object.assign(latest.input, { source_on_hand: 200, unit_cost: '9.90', server_only: 'fresh' });
  const restored = edits.restore('transfer', latest);
  assert.equal(restored.input.source_on_hand, 200);
  assert.equal(restored.input.unit_cost, '9.90');
  assert.equal(restored.input.server_only, 'fresh');
  assert.equal(restored.input.quantity, 24);
});

test('resolving input enforces the editable field boundary itself', () => {
  const latest = transfer();
  const restored = resolveWorkbenchInput('transfer', latest, { quantity: 15, source_on_hand: 1, risk_id: 99, unit_cost: '0.01' });
  assert.equal(restored.input.quantity, 15);
  assert.equal(restored.input.source_on_hand, latest.input.source_on_hand);
  assert.equal(restored.input.risk_id, 1);
  assert.equal(restored.input.unit_cost, latest.input.unit_cost);
  assert.equal(restored.input.target_store_id, 'A', 'partial edits must not erase an unchanged selector');
});

test('readonly-only changes do not create an unsaved edit', () => {
  const edits = createWorkbenchEdits(), data = transfer();
  edits.capture('transfer', 1, { ...data.input, source_on_hand: 999, unit_cost: '1.00' }, data.input);
  assert.equal(edits.hasAny(), false);
  assert.equal(edits.restore('transfer', data).hasEdits, false);
});

test('candidate-dependent facts come from the current network for the retained choice', () => {
  const edits = createWorkbenchEdits(), initial = transfer();
  edits.capture('transfer', 1, { ...initial.input, target_store_id: 'B' }, initial.input);
  const latest = transfer();
  Object.assign(latest.transfer_network[1], { name: '门店乙新名', on_hand: 42, capacity: 105, safety_stock: 11, daily_sales: 7, transport_fee: '44.00', eta_days: 3 });
  const restored = edits.restore('transfer', latest).input;
  assert.equal(restored.target_store, '门店乙新名');
  assert.equal(restored.target_on_hand, 42);
  assert.equal(restored.target_capacity, 105);
  assert.equal(restored.target_safety, 11);
  assert.equal(restored.target_daily_sales, 7);
  assert.equal(restored.transport_fee, '44.00');
  assert.equal(restored.eta_days, 3);
});

test('removed candidates retain the choice, report an issue and clear its obsolete facts', () => {
  const edits = createWorkbenchEdits(), initial = transfer();
  edits.capture('transfer', 1, { ...initial.input, target_store_id: 'B' }, initial.input);
  const latest = transfer();
  latest.transfer_network = latest.transfer_network.filter(item => item.store_id === 'A');
  const restored = edits.restore('transfer', latest);
  assert.equal(restored.input.target_store_id, 'B');
  assert.ok(restored.issues.length > 0);
  for (const field of ['target_store', 'target_on_hand', 'target_capacity', 'target_safety', 'target_daily_sales', 'transport_fee', 'eta_days']) {
    assert.equal(restored.input[field], null, field);
  }
  assert.equal(restored.hasEdits, true);
});

test('missing candidate facts stay unknown while measured zero survives', () => {
  const data = transfer();
  Object.assign(data.transfer_network[0], { on_hand: 0, transport_fee: 0, daily_sales: null });
  delete data.transfer_network[0].capacity;
  const restored = resolveWorkbenchInput('transfer', data).input;
  assert.equal(restored.target_on_hand, 0);
  assert.equal(restored.transport_fee, 0);
  assert.equal(restored.target_daily_sales, null);
  assert.equal(restored.target_capacity, null);
});

test('numeric transport strings compare equally but unknown is distinct from zero', () => {
  const data = expiry(), edits = createWorkbenchEdits();
  const strings = { ...data.input, transfer_qty: '10', promo_qty: '20.0', promo_price: 5.5, return_qty: '0' };
  assert.equal(sameEditableInput('expiry-rescue', strings, data.input), true);
  edits.capture('expiry-rescue', 1, strings, data.input);
  assert.equal(edits.hasAny(), false);
  assert.equal(sameEditableInput('expiry-rescue', { ...strings, return_qty: null }, data.input), false);
  edits.capture('expiry-rescue', 1, { ...strings, return_qty: null }, data.input);
  assert.equal(edits.restore('expiry-rescue', data).input.return_qty, null);
  assert.equal(editableInput('expiry-rescue', { ...strings, return_qty: '' }).return_qty, null);
});

test('reverting the editable values to the server baseline clears the local draft', () => {
  const data = transfer(), edits = createWorkbenchEdits();
  edits.capture('transfer', 1, { ...data.input, quantity: 24 }, data.input);
  assert.equal(edits.hasAny(), true);
  edits.capture('transfer', 1, { ...data.input, quantity: '10' }, data.input);
  assert.equal(edits.has('transfer', 1), false);
  assert.equal(edits.hasRisk(1), false);
  assert.equal(edits.hasAny(), false);
  assert.equal(edits.restore('transfer', data).hasEdits, false);
});

test('discard affects only the selected module and risk', () => {
  const edits = createWorkbenchEdits(), one = transfer(), two = transfer(2), nearExpiry = expiry();
  edits.capture('transfer', 1, { ...one.input, quantity: 11 }, one.input);
  edits.capture('transfer', 2, { ...two.input, quantity: 12 }, two.input);
  edits.capture('expiry-rescue', 1, { ...nearExpiry.input, promo_qty: 21 }, nearExpiry.input);
  edits.discard('transfer', 1);
  assert.equal(edits.has('transfer', 1), false);
  assert.equal(edits.has('transfer', 2), true);
  assert.equal(edits.has('expiry-rescue', 1), true);
  assert.equal(edits.hasRisk(1), true);
  edits.discard('expiry-rescue', 1);
  assert.equal(edits.hasRisk(1), false);
  assert.equal(edits.hasAny(), true);
});

test('concurrent changes are flagged only when the same field diverged on both sides', () => {
  const edits = createWorkbenchEdits(), data = transfer();
  edits.capture('transfer', 1, { ...data.input, quantity: 24 }, data.input);
  const latest = transfer();
  latest.input.quantity = 18;
  assert.deepEqual(edits.restore('transfer', latest).conflicts, ['quantity']);
  assert.equal(edits.restore('transfer', latest).input.quantity, 24);
  latest.input.quantity = '24';
  assert.deepEqual(edits.restore('transfer', latest).conflicts, []);
});

test('capture and restoration never mutate input data or depend on caller mutations', () => {
  const edits = createWorkbenchEdits(), data = transfer(), original = structuredClone(data);
  const changed = { ...data.input, quantity: 24 };
  edits.capture('transfer', 1, changed, data.input);
  changed.quantity = 99;
  const restored = edits.restore('transfer', data);
  assert.equal(restored.input.quantity, 24);
  restored.input.quantity = 77;
  assert.equal(edits.restore('transfer', data).input.quantity, 24);
  assert.deepEqual(data, original);
});

test('procurement edits preserve explicit action, date and quantity without changing facts', () => {
  const edits = createWorkbenchEdits();
  const data = { risk: { id: 3 }, input: { risk_id: 3, action: 'reduce', adjustment_qty: 4, new_payment_date: null, committed_amount: '88.00' } };
  edits.capture('procurement-brake', 3, { ...data.input, action: 'delay_payment', new_payment_date: '2026-10-30' }, data.input);
  data.input.adjustment_qty = 8;
  const restored = edits.restore('procurement-brake', data);
  assert.equal(restored.input.action, 'delay_payment');
  assert.equal(restored.input.new_payment_date, '2026-10-30');
  assert.equal(restored.input.adjustment_qty, 8);
  assert.equal(restored.input.committed_amount, '88.00');
});

test('invalid risk keys and unsupported workbenches cannot create entries', () => {
  const edits = createWorkbenchEdits(), data = transfer();
  for (const riskId of [0, -1, 1.5, '1', NaN, Number.MAX_SAFE_INTEGER + 1]) {
    assert.throws(() => edits.capture('transfer', riskId, data.input, data.input));
  }
  assert.throws(() => editableInput('unknown', data.input));
  assert.throws(() => edits.capture('unknown', 1, data.input, data.input));
  assert.equal(edits.hasAny(), false);
});

test('input-save receipts require a draft id and the requested module and risk', () => {
  const payload = receipt(), expected = { moduleType: 'transfer', riskId: 1 }, before = structuredClone(payload);
  assert.equal(validateWorkbenchDraft(payload, expected), payload);
  assert.deepEqual(payload, before);
  for (const changed of [{ id: '' }, { id: 1 }, { module_type: 'expiry-rescue' }, { risk_id: 2 }, { risk_id: '1' }]) {
    assert.throws(() => validateWorkbenchDraft({ draft: { ...payload.draft, ...changed } }, expected), RetailContractError);
  }
  for (const risk_id of [2, '1', undefined]) {
    const value = receipt();
    value.draft.input.risk_id = risk_id;
    assert.throws(() => validateWorkbenchDraft(value, expected), /draft.input.risk_id/);
  }
});

test('input-save receipts cannot masquerade as calculated, saved or approved proposals', () => {
  const expected = { moduleType: 'transfer', riskId: 1 };
  for (const status of ['calculated', 'saved', 'approved', 'blocked', 'not_saved']) {
    const value = receipt();
    value.draft.status = status;
    assert.throws(() => validateWorkbenchDraft(value, expected), /draft.status/);
  }
  for (const version of [-1, 1.5, '2', null]) {
    const value = receipt();
    value.draft.version = version;
    assert.throws(() => validateWorkbenchDraft(value, expected), /draft.version/);
  }
  assert.throws(() => validateWorkbenchDraft({ draft: null }, expected), RetailContractError);
  const value = receipt();
  value.draft.input = null;
  assert.throws(() => validateWorkbenchDraft(value, expected), /draft.input/);
});

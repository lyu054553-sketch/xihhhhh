// Only editable choices belong in the browser. Facts and calculations always
// come from the latest workbench response, including after returning to a risk.
export const WORKBENCH_FIELDS = {
  transfer: ['target_store_id', 'quantity'],
  'expiry-rescue': ['transfer_qty', 'promo_qty', 'promo_price', 'return_qty'],
  'procurement-brake': ['action', 'adjustment_qty', 'new_payment_date'],
};
const TEXT_FIELDS = new Set(['target_store_id', 'action', 'new_payment_date']);

export function editableInput(module, input) {
  if (!Object.hasOwn(WORKBENCH_FIELDS, module)) throw new Error('未知工作台');
  return Object.fromEntries(WORKBENCH_FIELDS[module].map(field => {
    const value = input[field];
    return [field, TEXT_FIELDS.has(field) ? String(value ?? '') : value == null || value === '' ? null : Number(value)];
  }));
}

export function sameEditableInput(module, left, right) {
  const a = editableInput(module, left), b = editableInput(module, right);
  return WORKBENCH_FIELDS[module].every(field => Object.is(a[field], b[field]));
}

export function resolveWorkbenchInput(module, data, edits = {}) {
  if (!Object.hasOwn(WORKBENCH_FIELDS, module)) throw new Error('未知工作台');
  const choices = Object.fromEntries(Object.entries(edits).filter(([field]) => WORKBENCH_FIELDS[module].includes(field)));
  const input = { ...data.input, ...choices }, issues = [];
  if (module === 'transfer') {
    const target = (data.transfer_network || []).find(item => item.store_id === input.target_store_id);
    if (!target) issues.push('原接收门店已不在当前候选范围，请重新选择接收门店。');
    const fields = { target_store:'name', target_on_hand:'on_hand', target_capacity:'capacity', target_safety:'safety_stock', target_daily_sales:'daily_sales', transport_fee:'transport_fee', eta_days:'eta_days' };
    for (const [field, source] of Object.entries(fields)) input[field] = target?.[source] ?? null;
  }
  return { input, issues };
}

export function createWorkbenchEdits() {
  const entries = new Map();
  function key(module, riskId) {
    if (!Object.hasOwn(WORKBENCH_FIELDS, module) || !Number.isSafeInteger(riskId) || riskId < 1) throw new Error('编辑记录缺少有效工作台或商品编号');
    return `${module}:${riskId}`;
  }
  return {
    capture(module, riskId, input, serverInput) {
      const id = key(module, riskId), values = editableInput(module, input), baseline = editableInput(module, serverInput);
      const changes = Object.fromEntries(WORKBENCH_FIELDS[module].filter(field => !Object.is(values[field], baseline[field])).map(field => [field, { value: values[field], baseline: baseline[field] }]));
      if (Object.keys(changes).length) entries.set(id, { module, riskId, changes });
      else entries.delete(id);
    },
    restore(module, data) {
      const entry = entries.get(key(module, data.risk.id)), baseline = editableInput(module, data.input);
      const changes = entry?.changes || {};
      const conflicts = Object.keys(changes).filter(field => !Object.is(changes[field].baseline, baseline[field]) && !Object.is(changes[field].value, baseline[field]));
      const resolved = resolveWorkbenchInput(module, data, Object.fromEntries(Object.entries(changes).map(([field, change]) => [field, change.value])));
      return { ...resolved, hasEdits: Boolean(entry), conflicts };
    },
    discard(module, riskId) { entries.delete(key(module, riskId)); },
    has(module, riskId) { return riskId != null && entries.has(key(module, riskId)); },
    hasRisk(riskId) { return [...entries.values()].some(entry => entry.riskId === Number(riskId)); },
    hasAny() { return entries.size > 0; },
  };
}

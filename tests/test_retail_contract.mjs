import test from "node:test";
import assert from "node:assert/strict";
import {
  RetailContractError, formatYuan, formatPercent, formatNumber,
  validateOverview, validateRisks, validateRiskDetail, validateWorkbench,
  validateCalculation, validateWorkbenchCalculation, validateWorkbenchSave,
  validateSimulationOptions, buildSimulationRequest, validateSimulation,
  validateProposal, validateProposalList, validateApproval, validateExecutionTask, validateTaskList,
} from "../assets/js/retail-contract.mjs";

const copy = (value) => structuredClone(value);
const source = { is_demo: true, source: "合成联调数据", as_of_date: "2026-10-03" };
const metadata = { missing: [], assumptions: [], currency: "CNY" };
const risk = { id: 1, sku: "SKU-1", product: "坚果", store: "测试门店", store_id: "STORE-001", inventory_qty: 120, sales_30: 12, days_to_sell: 300, unit_cost: 8.8, missing_fields: [] };
const proposal = { id: "P-1", status: "draft", current_version: 2, version: { version: 2, status: "draft", payload: { input: {} } } };
const calculation = { valid: true, errors: [], cash: { inventory_cost: "3200.00", estimated_net_cash_improvement: null, known_cash_effect: "-86.00" } };
const workbench = { module_type: "transfer", mode: "sample_replay", snapshot_id: "snapshot-demo-v1", risk, items: [risk], input: { risk_id: 1, quantity: 40, source_on_hand: 120 }, calculation, draft: { status: "calculated", version: 1 }, proposal, tasks: [] };
const options = { ...source, stores: [{ id: "STORE-001", name: "测试门店" }], categories: ["坚果炒货"] };
const request = { horizon_days: 14, reduction_pct: 20, store_id: "all", category: null, request_text: "减少采购 20%" };
const simulation = { ...source, status: "completed", scenario: { ...request, start_date: "2026-10-03", end_date: "2026-10-16" }, metrics: { purchase_outflow: { baseline: 1200.5, scenario: 1000, delta: -200.5 }, ending_inventory_cost: { baseline: 800, scenario: 600, delta: -200 }, stockout_risk_count: { baseline: 1, scenario: 2, delta: 1 } }, weekly: [{ label: "第1周", start_date: "2026-10-03", end_date: "2026-10-09", baseline: 600.25, scenario: 500 }], risks: [{ sku: "SKU-1", product: "坚果", store_id: "STORE-001", store_name: "测试门店", baseline_days: 10, scenario_days: 3, safety_days: 5, risk_level: "watch", shortage_qty: 0, is_new_risk: true }], metadata: { ...metadata, units: { money: "CNY", risk_count: "store_sku" } } };
const overview = { ...source, scope: { store_id: "all", store_count: 1, period: 7 }, account: { balance: 0, opening_balance: 100, cash_in: 0, cash_out: 100 }, sales: { amount: 0, gross_profit: 0, gross_margin_pct: null, change_pct: -100 }, inventory: { cost: 100, risk_cost: 0, risk_count: 0, turnover_days: null }, purchase_commitments: { amount: null }, pending_approvals: { amount: 0, known_amount: 0 }, trend: [], stores: [{ store_id: "STORE-001", store_name: "测试门店", inventory_cost: 100, risk_cost: 0, turnover_days: null, risk_types: [], risk_items: [] }], metadata };
const task = { id: "TASK-1", proposal_id: "P-1", proposal_version: 2, status: "draft_pending_external_execution", metadata_json: '{"external_write":false}' };

test("v1.2 yuan and percent display preserve units and zero", () => {
  assert.equal(formatYuan(220), "¥220.00");
  assert.equal(formatYuan(0), "¥0.00");
  assert.equal(formatYuan(-86), "¥-86.00");
  assert.equal(formatPercent(20), "20%");
  assert.equal(formatPercent(0.2), "0.2%");
  assert.equal(formatNumber(6, { unit: "袋" }), "6 袋");
});
test("unknown amounts, counts and rates never turn into zero", () => {
  for (const formatter of [formatYuan, formatNumber, formatPercent]) {
    assert.equal(formatter(null), "未接入／待补充");
    assert.equal(formatter(undefined), "未接入／待补充");
    assert.throws(() => formatter(""), RetailContractError);
    assert.throws(() => formatter(false), RetailContractError);
  }
});
test("workbench Decimal wire strings format without rescaling", () => {
  assert.equal(formatYuan("3200.00"), "¥3,200.00");
  assert.equal(formatYuan("-86.00"), "¥-86.00");
  assert.equal(formatYuan("0"), "¥0.00");
  assert.equal(formatPercent("20"), "20%");
  for (const value of [" 20 ", "1e3", "0x10", "1,000", "01.20", ".5", "1.234", "NaN", "Infinity", NaN, Infinity]) assert.throws(() => formatYuan(value), RetailContractError);
});
test("overview keeps null finance and zero inventory distinct", () => {
  const value = copy(overview);
  assert.equal(validateOverview(value, { storeId: "all", period: 7 }), value);
  assert.equal(value.purchase_commitments.amount, null);
  assert.equal(value.account.balance, 0);
});
test("overview correlates returned scope and rejects wrong currency", () => {
  assert.throws(() => validateOverview(overview, { storeId: "STORE-001" }), /scope.store_id/);
  assert.throws(() => validateOverview(overview, { period: 30 }), /scope.period/);
  const value = copy(overview);
  value.metadata.currency = "USD";
  assert.throws(() => validateOverview(value), /currency/);
});
test("overview rejects numeric strings or missing primary monetary fields", () => {
  for (const amount of ["100.00", undefined, 1.001, NaN, Infinity]) {
    const value = copy(overview);
    value.account.balance = amount;
    assert.throws(() => validateOverview(value), /account.balance/);
  }
});
test("real empty overview can carry null date and unknown financial data", () => {
  const value = copy(overview);
  Object.assign(value, { is_demo: false, as_of_date: null, stores: [] });
  value.account.balance = null;
  value.inventory.cost = null;
  value.inventory.risk_cost = null;
  value.scope.store_count = 0;
  assert.equal(validateOverview(value), value);
});
test("risk list and detail require stable identity while allowing null coverage", () => {
  const value = { items: [{ ...risk, unit_cost: "8.80", days_to_sell: null }], total: 1 };
  assert.equal(validateRisks(value), value);
  const detail = { risk: value.items[0], comparison: {}, diagnosis: {}, facts: [], factors: [], evidence: { missing_fields: ["sales"] } };
  assert.equal(validateRiskDetail(detail, { riskId: 1 }), detail);
  assert.throws(() => validateRiskDetail(detail, { riskId: 2 }), /risk.id/);
});
test("blocked calculations are valid API results and remain blocked", () => {
  const blocked = { valid: false, errors: ["超出调出门店可调数量"] };
  assert.equal(validateCalculation(blocked), blocked);
  assert.equal(validateWorkbenchCalculation({ input: {}, calculation: blocked, draft: { status: "blocked", version: 2 } }).calculation.valid, false);
  assert.throws(() => validateCalculation({ valid: "false", errors: [] }), /calculation.valid/);
});
test("workbench payload carries original inputs, persisted Decimal results and draft state", () => {
  const value = copy(workbench);
  assert.equal(validateWorkbench(value, { moduleType: "transfer", riskId: 1 }), value);
  assert.equal(value.calculation.cash.inventory_cost, "3200.00");
  value.draft.status = "needs_recalculation";
  value.calculation = null;
  assert.equal(validateWorkbench(value), value);
  assert.throws(() => validateWorkbench(value, { moduleType: "expiry-rescue" }), /module_type/);
});
test("save response validates its own shape rather than pretending to be a workbench", () => {
  const value = { proposal, calculation, message: "已保存草稿" };
  assert.equal(validateWorkbenchSave(value), value);
  assert.throws(() => validateWorkbenchSave({ ...value, calculation: { valid: false, errors: ["库存不足"] } }), /无效测算/);
});
test("simulation options allow a real empty tenant and reject duplicate IDs", () => {
  assert.equal(validateSimulationOptions(options), options);
  assert.doesNotThrow(() => validateSimulationOptions({ ...source, is_demo: false, as_of_date: null, stores: [], categories: [] }));
  assert.throws(() => validateSimulationOptions({ ...options, stores: [...options.stores, ...options.stores] }), /不能重复/);
});
test("simulation requests preserve explicit yuan-independent percentages", () => {
  assert.deepEqual(buildSimulationRequest(request, options), request);
  assert.deepEqual(buildSimulationRequest({ horizon_days: 1, reduction_pct: 0 }, options), { horizon_days: 1, reduction_pct: 0, store_id: "all", category: null, request_text: "" });
  assert.equal(buildSimulationRequest({ ...request, reduction_pct: 100 }, options).reduction_pct, 100);
});
test("simulation inputs reject unsupported horizon, percent and stale selectors", () => {
  for (const changed of [{ horizon_days: 0 }, { horizon_days: 91 }, { horizon_days: 14.5 }, { reduction_pct: -1 }, { reduction_pct: 101 }, { reduction_pct: "20" }, { store_id: "unknown" }, { category: "unknown" }]) {
    assert.throws(() => buildSimulationRequest({ ...request, ...changed }, options), (error) => error instanceof RetailContractError && error.code === "invalid_input" && error.outcomeUnknown === false);
  }
});
test("completed simulation validates baseline and scenario without recomputing results", () => {
  const value = copy(simulation);
  assert.equal(validateSimulation(value, request), value);
  assert.equal(value.metrics.purchase_outflow.delta, -200.5);
});
test("returned simulation must match the exact confirmed scenario", () => {
  for (const changed of [{ horizon_days: 30 }, { reduction_pct: 30 }, { store_id: "STORE-001" }, { category: "坚果炒货" }, { request_text: "另一条输入" }]) {
    const value = copy(simulation);
    Object.assign(value.scenario, changed);
    assert.throws(() => validateSimulation(value, request), /与已确认的请求不一致/);
  }
});
test("simulation monetary series cannot be confused with fen or missing metrics", () => {
  const value = copy(simulation);
  value.metadata.units.money = "fen";
  assert.throws(() => validateSimulation(value, request), /人民币元/);
  value.metadata.units.money = "CNY";
  value.metrics.purchase_outflow.baseline = "1200.50";
  assert.throws(() => validateSimulation(value, request), /purchase_outflow.baseline/);
  value.metrics.purchase_outflow.baseline = null;
  assert.throws(() => validateSimulation(value, request), /purchase_outflow.baseline/);
});
test("unavailable simulations preserve missing inputs and Pydantic Decimal echo", () => {
  const value = { ...copy(simulation), is_demo: false, status: "unavailable", scenario: { ...request, reduction_pct: "20" }, metrics: null, weekly: [], risks: [], metadata: { ...metadata, missing: ["forecast_demand"] } };
  assert.equal(validateSimulation(value, request), value);
  assert.equal(value.scenario.reduction_pct, "20");
  assert.equal(value.metrics, null);
  value.weekly = copy(simulation.weekly);
  assert.throws(() => validateSimulation(value, request), /不可用的模拟/);
});
test("unavailable malformed Decimal echoes are not coerced", () => {
  for (const reduction_pct of ["", " 20 ", "2e1", null, "0x14"]) {
    assert.throws(() => validateSimulation({ ...simulation, status: "unavailable", scenario: { ...request, reduction_pct }, metrics: null, weekly: [], risks: [] }, request), RetailContractError);
  }
});
test("proposal versions must describe the same current revision", () => {
  assert.equal(validateProposal(proposal, { proposalId: "P-1" }), proposal);
  assert.equal(validateProposalList({ items: [proposal] }).items[0], proposal);
  assert.throws(() => validateProposal(proposal, { proposalId: "P-2" }), /proposal.id/);
  assert.throws(() => validateProposal({ ...proposal, current_version: 3 }), /proposal.version.version/);
});
test("approval is a distinct receipt correlated with the approved proposal and version", () => {
  const receipt = { id: "APR-1", proposal_id: "P-1", proposal_version: 2, status: "approved", idempotency_key: "approve-P-1-2" };
  assert.equal(validateApproval(receipt, { proposalId: "P-1", version: 2 }), receipt);
  assert.throws(() => validateApproval(receipt, { version: 1 }), /proposal_version/);
  assert.throws(() => validateApproval(receipt, { proposalId: "P-2" }), /proposal_id/);
  assert.throws(() => validateApproval(task), /approved/);
});
test("execution creation remains a draft task rather than a completion receipt", () => {
  assert.equal(validateExecutionTask(task, { proposalId: "P-1", version: 2 }), task);
  assert.equal(task.status, "draft_pending_external_execution");
  assert.equal(validateTaskList({ items: [task] }).items[0], task);
  assert.throws(() => validateExecutionTask(task, { version: 3 }), /proposal_version/);
});

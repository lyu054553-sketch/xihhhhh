import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import {
  canConfirm,
  formatRmb,
  mapCandidate,
  mapComparison,
  mount,
  validateDecisionInput,
} from "../../../assets/hackathon/decision/decision-workbench.mjs";
import { createDecisionPreviewFixtures } from "../../../assets/hackathon/decision/preview-fixtures.mjs";

test("money formatting preserves unknown values and formats RMB cents", () => {
  assert.equal(formatRmb(null), "—");
  assert.match(formatRmb(1234.5), /1,234\.50/);
});

test("input validation catches required fields and bounds only", () => {
  const schema = [
    { name: "quantity", label: "调拨数量", type: "number", min: 1, max: 100, required: true, unit: "盒" },
    { name: "fee", label: "运费", type: "number", min: 0, required: true, unit: "元" },
  ];
  assert.deepEqual(validateDecisionInput(schema, { quantity: "", fee: "-2" }), {
    quantity: "请填写调拨数量",
    fee: "不能小于 0 元",
  });
  assert.deepEqual(validateDecisionInput(schema, { quantity: "80", fee: "24" }), {});
});

test("confirmation requires a fresh allowed comparison and feasible selected candidate", () => {
  const comparison = { comparison_id: "CMP-1", confirmation_allowed: true };
  const strategy = { id: "CAND-1", feasibility: "feasible", can_execute: true };
  assert.equal(canConfirm({ dirty: false, busy: false, comparison, selectedStrategy: strategy, status: "ready" }), true);
  assert.equal(canConfirm({ dirty: true, busy: false, comparison, selectedStrategy: strategy, status: "ready" }), false);
  assert.equal(canConfirm({ dirty: false, busy: false, comparison, selectedStrategy: strategy, status: "version_conflict" }), false);
  assert.equal(canConfirm({ dirty: false, busy: false, comparison, selectedStrategy: strategy, status: "missing_data" }), false);
  assert.equal(canConfirm({ dirty: false, busy: false, comparison, selectedStrategy: strategy, status: "confirmed" }), false);
  assert.equal(canConfirm({ dirty: false, busy: false, comparison: { ...comparison, confirmation_allowed: false }, selectedStrategy: strategy, status: "ready" }), false);
  assert.equal(canConfirm({ dirty: false, busy: false, comparison, selectedStrategy: { id: "CAND-2", feasibility: "needs_confirmation" }, status: "ready" }), false);
  assert.equal(canConfirm({ dirty: false, busy: false, comparison: { confirmation_allowed: true }, selectedStrategy: strategy, status: "ready" }), false);
});

test("comparison mapping displays service values without deriving net cash", () => {
  const mapped = mapComparison({
    comparison_id: "CMP-1",
    calculation_version: "calc-1",
    policy_version: "policy-1",
    baseline_id: "BASE-1",
    candidates: [{
      candidate_id: "CAND-1", action_type: "transfer", feasible: true, exclusion_reasons: [],
      store_id: "ST-1", target_store_id: "ST-2", sku_id: "SKU-1", lot_id: "LOT-1", quantity: 3, base_unit: "盒",
      calculation: { planned_qty: 3, expected_sold_qty: null, ending_qty: 3, execution_cost_cny: 5, gross_profit_cny: null, expected_cash_in_cny: null, actual_cash_in_cny: null, cash_flow: [], calculation_version: "calc-1", execution_plan: { actions: [{ type: "transfer" }] } },
      assumptions: [], missing_fields: [],
    }],
  });
  assert.equal(mapped.comparison_id, "CMP-1");
  assert.equal(mapped.baseline_id, "BASE-1");
  assert.equal(mapped.strategies[0].planned_quantity, 3);
  assert.equal(mapped.strategies[0].expected_cash_in, null);
  assert.equal(Object.hasOwn(mapped.strategies[0], "expected_net_cash"), false);
  assert.equal(mapped.confirmation_allowed, true);
});

test("candidate feasibility and unknown quantities follow the returned candidate", () => {
  const candidate = mapCandidate({
    candidate_id: "CAND-2", action_type: "return", feasible: false, exclusion_reasons: [],
    quantity: null, base_unit: "桶", missing_fields: ["return_terms.confirmed_at"], assumptions: [],
    calculation: { planned_qty: null, expected_cash_in_cny: null, actual_cash_in_cny: null, cash_flow: [] },
  });
  assert.equal(candidate.feasibility, "needs_confirmation");
  assert.equal(candidate.allocated_quantity, null);
  assert.equal(candidate.expected_cash_in, null);
});

test("preview uses the shared explicit fixture client and never falls back for missing routes", async () => {
  const apiSource = readFileSync(new URL("../../../assets/hackathon/shared/api-client.js", import.meta.url), "utf8");
  const apiWindow = { location: { protocol: "file:" }, structuredClone, fetch: () => { throw new Error("fixture mode must not fetch"); } };
  runInNewContext(apiSource, { window: apiWindow, URLSearchParams, FormData, structuredClone });
  const api = apiWindow.HackathonApiClient.createApiClient({ mode: "fixture", fixtures: createDecisionPreviewFixtures() });
  const context = { tenant_id: "demo", scenario_id: "S01", branch_id: "transfer_80", snapshot_id: "SNAP-20261003-BASE", as_of: "2026-10-03T09:30:00+08:00", data_version: "retail-v2.1", fact_version: 1, is_demo: true, source_refs: [], missing_fields: [] };
  const facts = await api.queryFacts({ context, store_ids: [], sku_ids: ["SKU-001"], lot_ids: [], include: ["inventory"], history_start: null, history_end: null });
  assert.equal(api.mode, "fixture");
  assert.equal(facts.fixture_only, true);
  assert.equal(facts.inventory.length, 2);
  const comparison = await api.compareProposals({ context, risk_keys: [], objective: "查看候选", horizon_start: "2026-10-03", horizon_end: "2026-10-25", assumption_ids: [] });
  assert.match(comparison.comparison_id, /^CMP-FIXTURE-/);
  assert.equal(comparison.candidates[1].calculation.expected_cash_in_cny, 6400);
  const repeat = await api.compareProposals({ context, risk_keys: [], objective: "查看候选", horizon_start: "2026-10-03", horizon_end: "2026-10-25", assumption_ids: [] });
  const changed = await api.compareProposals({ context, risk_keys: [], objective: "查看候选", horizon_start: "2026-10-03", horizon_end: "2026-10-26", assumption_ids: [] });
  assert.equal(repeat.comparison_id, comparison.comparison_id);
  assert.notEqual(changed.comparison_id, comparison.comparison_id);
  assert.equal(changed.candidates[1].calculation.cash_flow[0].expected_at, "2026-10-26");
  const previewHtml = readFileSync(new URL("../../../assets/hackathon/decision/preview.html", import.meta.url), "utf8");
  assert.match(previewHtml, /\.\.\/shared\/api-client\.js/);
  await assert.rejects(api.listTasks(), (error) => error.code === "fixture_missing");
});

test("public mount is exported and requires the host-injected shared API", () => {
  assert.equal(typeof mount, "function");
  assert.throws(() => mount({}), /injected API client/);
});

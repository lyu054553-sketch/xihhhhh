const FIXTURE_CONTEXT = {
  tenant_id: "demo",
  scenario_id: "S01",
  branch_id: "transfer_80",
  snapshot_id: "SNAP-20261003-BASE",
  as_of: "2026-10-03T09:30:00+08:00",
  data_version: "retail-v2.1",
  fact_version: 1,
  is_demo: true,
  source_refs: [{ source: "02_库存与90天经营事实.xlsx", record_id: "INV-001", known_at: "2026-10-03T00:00:00+08:00", is_demo: true }],
  missing_fields: [],
};

const INVENTORY = [
  { store_id: "ST-001", sku_id: "SKU-001", lot_id: "LOT-001-001", stock_state: "on_hand", quantity: 120, base_unit: "盒", unit_cost_cny: 80, blocked_qty: 0, reserved_qty: 0, sellable_until: "2026-12-15", source_ref: FIXTURE_CONTEXT.source_refs[0] },
  { store_id: "ST-002", sku_id: "SKU-001", lot_id: "LOT-002-004", stock_state: "on_hand", quantity: 10, base_unit: "盒", unit_cost_cny: 80, blocked_qty: 0, reserved_qty: 0, sellable_until: "2026-12-15", source_ref: { ...FIXTURE_CONTEXT.source_refs[0], record_id: "INV-002" } },
];

const RISK_ITEMS = [
  { risk_key: "S01:ST-001:SKU-001:LOT-001-001:slow_moving", risk_id: null, store_id: "ST-001", sku_id: "SKU-001", lot_id: "LOT-001-001", risk_type: "slow_moving", result: "risk", quantity: 120, base_unit: "盒", amount_cny: 9600, coverage_days: 120, remaining_sellable_days: 73, evidence_refs: FIXTURE_CONTEXT.source_refs, missing_fields: [], rule_version: "POL-001" },
  { risk_key: "S01:ST-001:SKU-001:LOT-001-001:near_expiry", risk_id: null, store_id: "ST-001", sku_id: "SKU-001", lot_id: "LOT-001-001", risk_type: "near_expiry", result: "normal", quantity: 120, base_unit: "盒", amount_cny: 9600, coverage_days: 120, remaining_sellable_days: 73, evidence_refs: FIXTURE_CONTEXT.source_refs, missing_fields: [], rule_version: "POL-001" },
];

const CANDIDATES = [
  {
    candidate_id: "CAND-FIXTURE-KEEP", action_type: "keep", feasible: true, exclusion_reasons: [],
    store_id: "ST-001", target_store_id: null, sku_id: "SKU-001", lot_id: "LOT-001-001", quantity: 120, base_unit: "盒",
    calculation: { planned_qty: 120, expected_sold_qty: 40, ending_qty: 80, execution_cost_cny: 0, gross_profit_cny: 800, expected_cash_in_cny: 4000, actual_cash_in_cny: null, cash_flow: [{ direction: "in", amount_cny: 4000, expected_at: "2026-10-25", status: "forecast", source_ref: "scenario-demand-base" }], calculation_version: "comparison-v1" },
    inventory_changes: [],
    assumptions: ["scenario-demand-base"], missing_fields: [],
  },
  {
    candidate_id: "CAND-FIXTURE-TRANSFER", action_type: "transfer", feasible: true, exclusion_reasons: [],
    store_id: "ST-001", target_store_id: "ST-002", sku_id: "SKU-001", lot_id: "LOT-001-001", quantity: 80, base_unit: "盒",
    calculation: { planned_qty: 80, expected_sold_qty: 64, ending_qty: 16, execution_cost_cny: 24, gross_profit_cny: 1280, expected_cash_in_cny: 6400, actual_cash_in_cny: null, cash_flow: [{ direction: "in", amount_cny: 6400, expected_at: "2026-10-25", status: "forecast", source_ref: "S01 demand range" }], calculation_version: "comparison-v1" },
    inventory_changes: [
      { store_id: "ST-001", sku_id: "SKU-001", lot_id: "LOT-001-001", quantity_before: 120, quantity_after: 40, quantity_delta: -80, base_unit: "盒", source_ref: FIXTURE_CONTEXT.source_refs[0] },
      { store_id: "ST-002", sku_id: "SKU-001", lot_id: "LOT-001-001", quantity_before: 10, quantity_after: 90, quantity_delta: 80, base_unit: "盒", source_ref: FIXTURE_CONTEXT.source_refs[0] },
    ],
    assumptions: ["S01 demand range"], missing_fields: [],
  },
  {
    candidate_id: "CAND-FIXTURE-RETURN", action_type: "return", feasible: false, exclusion_reasons: ["本场景未提供已确认退供条款"],
    store_id: "ST-001", target_store_id: null, sku_id: "SKU-001", lot_id: "LOT-001-001", quantity: null, base_unit: "盒",
    calculation: { planned_qty: null, expected_sold_qty: null, ending_qty: null, execution_cost_cny: null, gross_profit_cny: null, expected_cash_in_cny: null, actual_cash_in_cny: null, cash_flow: [], calculation_version: "comparison-v1" },
    inventory_changes: [],
    assumptions: [], missing_fields: ["return_terms.confirmed_at"],
  },
];

function selectedContext(context) {
  return { ...FIXTURE_CONTEXT, ...(context || {}), source_refs: [...(context?.source_refs || FIXTURE_CONTEXT.source_refs)], missing_fields: [...(context?.missing_fields || [])] };
}

function matches(row, body = {}) {
  const selectors = [
    [body.store_ids, "store_id"],
    [body.sku_ids, "sku_id"],
    [body.lot_ids, "lot_id"],
  ];
  return selectors.every(([ids, key]) => !ids?.length || ids.includes(row[key]));
}

export function createDecisionPreviewFixtures() {
  return {
    "POST /hackathon/facts/query": ({ body = {} } = {}) => ({
      fixture_only: true,
      contract_version: "hackathon.v1",
      query_id: "Q-FIXTURE-001",
      context: selectedContext(body.context),
      inventory: INVENTORY.filter((row) => matches(row, body)),
      sales_history: [{ date: "2026-10-02", store_id: "ST-001", sku_id: "SKU-001", lot_id: "LOT-001-001", sold_qty: 1, base_unit: "盒", sales_amount_cny: 100, known_at: "2026-10-03T00:00:00+08:00", source: "02_库存与90天经营事实.xlsx" }],
      availability_history: [],
      demand_forecasts: [],
      procurement: [],
      routes: [{ origin_store_id: "ST-001", target_store_id: "ST-002", distance_km: 5.2, route_fee_cny: 24, source: "演示路线事实", source_ref: FIXTURE_CONTEXT.source_refs[0] }],
      policies: [],
      payables: [],
      missing_fields: [],
      warnings: [],
    }),
    "POST /hackathon/risks/assess": ({ body = {} } = {}) => {
      const items = RISK_ITEMS.filter((row) => matches(row, body));
      const keys = new Set(items.filter((item) => item.result === "risk").map((item) => `${item.store_id}:${item.sku_id}:${item.lot_id}`));
      return {
        fixture_only: true,
        contract_version: "hackathon.v1",
        context: selectedContext(body.context),
        calculation_version: "risk-v1",
        items,
        attention_inventory_cost_cny: keys.size ? 9600 : 0,
        counted_inventory_keys: [...keys],
        missing_fields: [],
      };
    },
    "POST /hackathon/proposals/compare": ({ body = {} } = {}) => {
      const endDate = body.horizon_end || "2026-10-25";
      const comparisonSignature = encodeURIComponent([
        body.context?.scenario_id,
        body.context?.snapshot_id,
        body.horizon_start || "2026-10-03",
        endDate,
        body.objective || "default",
        JSON.stringify(body.business_inputs || {}),
        ...(body.assumption_ids || []),
      ].join("|"));
      const candidates = CANDIDATES.map((candidate) => ({
        ...candidate,
        candidate_id: `${candidate.candidate_id}-${comparisonSignature}`,
        calculation: {
          ...candidate.calculation,
          cash_flow: candidate.calculation.cash_flow.map((flow) => ({ ...flow, expected_at: endDate })),
        },
      }));
      return {
        fixture_only: true,
        contract_version: "hackathon.v1",
        calculation_version: "comparison-v1",
        policy_version: "retail-v2.1",
        comparison_id: `CMP-FIXTURE-${comparisonSignature}`,
        context: selectedContext(body.context),
        objective: body.objective || "在10月25日前降低同批库存占用并评估回款",
        horizon_start: body.horizon_start || "2026-10-03",
        horizon_end: endDate,
        baseline_id: `${body.context?.scenario_id || "S01"}:${body.context?.snapshot_id || FIXTURE_CONTEXT.snapshot_id}:${endDate}`,
        candidates,
        selected_candidate_id: null,
      };
    },
  };
}

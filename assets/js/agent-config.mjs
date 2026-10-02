export const AGENT_CONFIG = {
  slow_moving: {
    title: "滞销诊断", description: "从库存成本与真实销售记录识别低动销商品，再核对建议所引用的证据。",
    example: "找出滨江店近两周没有销售、库存占款较高的商品。",
    stores: ["STORE-HZ-001"], skus: ["SNK-002"],
    fields: [
      { key: "sales_window_days", label: "销售窗口（天）", value: "14", min: 1 },
      { key: "no_sale_days_gte", label: "无销售天数下限", value: "14", min: 0 },
      { key: "min_inventory_value_yuan", label: "最低库存成本（元）", value: "200.00", min: 0, step: "0.01" },
      { key: "limit", label: "最多展示条数", value: "10", min: 1 },
    ],
  },
  store_transfer: {
    title: "跨门店调拨", description: "比较门店需求与可用库存。调拨改善库存配置，不等于现金到账。",
    example: "将滨江店多余的海苔脆片调到文二路店，保证两边的库存覆盖。",
    stores: ["STORE-HZ-001", "STORE-HZ-002"], skus: ["SNK-001"],
    fields: [
      { key: "source_store_ids", label: "允许调出的门店", type: "stores", value: ["STORE-HZ-001"] },
      { key: "target_store_ids", label: "允许调入的门店", type: "stores", value: ["STORE-HZ-002"] },
      { key: "sales_window_days", label: "销售窗口（天）", value: "14", min: 1 },
      { key: "min_source_cover_days", label: "调出后最低覆盖天数", value: "14", min: 0, step: "any" },
      { key: "target_cover_days", label: "接收店目标覆盖天数", value: "14", min: 0, step: "any" },
      { key: "max_transfer_qty", label: "最多调拨数量（商品库存单位）", value: "50", min: 0, step: "any" },
    ],
  },
  near_expiry: {
    title: "近效期分析", description: "按批次与销售记录评估风险敞口，缺少到期日时明确展示数据缺项。",
    example: "分析文二路店香辣豆干的近效期批次和可核验的处置建议。",
    stores: ["STORE-HZ-002"], skus: ["SNK-004"],
    fields: [
      { key: "within_days", label: "关注未来多少天内到期", value: "30", min: 0 },
      { key: "sales_window_days", label: "销售窗口（天）", value: "14", min: 1 },
      { key: "limit", label: "最多展示批次数", value: "10", min: 1 },
    ],
  },
  procurement_brake: {
    title: "采购刹车", description: "核对未收货采购单、到货时间与缺货风险，采购减量只代表预计减少未来承诺。",
    example: "检查城西店每日坚果的 PO-003，评估采购量是否需要调整。",
    stores: ["STORE-HZ-003"], skus: ["SNK-002"],
    fields: [
      { key: "horizon_days", label: "评估周期（天）", value: "14", min: 1 },
      { key: "min_safety_stock_days", label: "最低安全库存天数", value: "5", min: 0, step: "any" },
      { key: "include_open_orders", label: "纳入未收货采购单", type: "checkbox", value: true },
    ],
  },
  cashflow_simulation: {
    title: "资金周转模拟", description: "先确认采购、调拨或促销情景，再比较基线与方案的库存资金占用和采购承诺。",
    example: "城西店每日坚果的 PO-003 少采购 6 袋，看看未来30天的资金占用和缺货风险。",
    stores: ["STORE-HZ-003"], skus: ["SNK-002"],
    fields: [{ key: "horizon_days", label: "模拟周期（天）", value: "30", min: 1 }],
  },
};

export function initialValues(manifest, type) {
  const config = AGENT_CONFIG[type];
  const options = manifest.scope_options;
  return {
    as_of: manifest.as_of, data_version: manifest.data_version, policy_version: manifest.policy_version,
    store_ids: config.stores.filter((id) => options.stores.some((store) => store.store_id === id)),
    sku_ids: config.skus.filter((id) => options.skus.some((sku) => sku.sku_id === id)),
    category_ids: [], user_input: "",
    ...Object.fromEntries(config.fields.map((field) => [field.key, structuredClone(field.value)])),
  };
}

// Convert a user-entered currency string at the boundary; business calculations
// remain on the server. Never use a floating-point multiplication for cents.
export function yuanToFen(value) {
  const text = String(value).trim();
  if (!/^\d+(?:\.\d{1,2})?$/.test(text)) throw new Error("金额必须为非负数，最多保留两位小数");
  const [whole, fraction = ""] = text.split(".");
  const fen = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0"));
  if (fen > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error("金额超出可精确传输的范围");
  return Number(fen);
}

export function paramsFromValues(type, values) {
  const params = {};
  for (const field of AGENT_CONFIG[type].fields) {
    const value = values[field.key];
    if (field.key === "min_inventory_value_yuan") params.min_inventory_value_fen = yuanToFen(value);
    else if (field.type === "stores") params[field.key] = [...value];
    else if (field.type === "checkbox") params[field.key] = Boolean(value);
    else {
      if (String(value).trim() === "") throw new Error(`请填写${field.label}`);
      const number = Number(value);
      if (!Number.isFinite(number) || number < field.min || (!field.step && !Number.isInteger(number))) throw new Error(`${field.label}不符合取值要求`);
      params[field.key] = number;
    }
  }
  if (type === "cashflow_simulation") params.operation = "preview";
  return params;
}

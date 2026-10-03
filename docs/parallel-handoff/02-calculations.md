# 任务框 2：确定性业务计算交接

本次按 `docs/parallel-prompts/02-calculations.md`、`PARALLEL_CONTRACT.md` 和 `backend/hackathon_shared.py` 开发。独占修改 `backend/hackathon_calculations/`、`tests/hackathon/test_calculations*.py` 和本文；不修改前端、公共路由、Store、共享 DTO、原始数据包。提交与总集成由主任务完成。

## 导出接口与调用

```python
from backend.hackathon_calculations import CalculationService

calculator = CalculationService()
facts = injected_fact_service.query({"context": current_context})
comparison_request = {
    "context": current_context,
    "risk_keys": ["S01:ST-001:SKU-001:LOT-001-001:slow_moving"],
    "objective": "比较同批库存处置与同周期现金影响",
    "horizon_start": "2026-10-03",
    "horizon_end": "2026-10-25",
    "assumption_ids": [],
    "inputs": {
        "sales_settlement_days": 0,
    },
    "business_inputs": {
        "transfer": {
            "origin_store_id": "ST-001", "target_store_id": "ST-002",
            "sku_id": "SKU-001", "lot_id": "LOT-001-001",
            "quantity": 80, "base_unit": "盒", "route_fee_cny": 24,
        },
    },
}
result = calculator.compare(facts, comparison_request)
```

`sales_settlement_days=0` 是调用者明确确认的当日结算假设，服务没有此默认值。缺少结算周期时保留销售推算，现金日期和金额不伪装成已知，方案返回缺项。80 是本例用户输入；自动推荐数量由事实计算，不引用验收答案。

`CalculationService.compare(FactQueryResult, request) -> ProposalComparison` 实现正式服务协议。其生产代码只依赖共享类型、`domain.py` 的日期／金额能力与自身纯函数，不调用具体 FactService、数据库、工作簿、模型或渠道。

内部纯函数仍导出于 `backend.hackathon_calculations.calculations`：`compare_options`、`calculate_purchase`、`calculate_promotion`、`calculate_return`、`calculate_combination`、`validate_combination`、`simulate_cash`。公共入口应使用 `CalculationService`，避免调用者另做字段映射。

## 确定性计算行为

- 库存按门店、SKU、批次与状态区分，扣除冻结和预占。在途表与库存快照使用同一个 `shipment_line_id` 去重，已支付在途只计供给，不再次计采购付款。未来到货按日期进入供给，过期和缺失效期不当作可售。
- 留店、调拨以逐日需求与 FEFO 模拟。调拨同时检查源店安全量、目标净需求、已知在途、容量、运输期、可售期、营业／收货日历、路线适用条件及运费。用户数量违反上限时返回不可行，不静默改量。
- 调拨比较会计入接收店原库存销售被替代的影响；比较增量是受影响门店同 SKU 的同周期“不行动”基线差，不能把调入商品全部销售额称为额外收益。
- 组合促销各阶段共享活动库存上限，按组件数量和批次分配；阶段日期、底价与毛利约束必须满足。低／中／高是已给定的需求假设，修改价格改变财务结果，但不杜撰价格弹性。促销期内不再叠加组件的正常销售需求。
- 退供区分退款、换货、抵款。检查有效期、可退数量／比例、剩余可售期、包装及供应商确认、验收日和费用；支持结构化 `refund_pct/freight_fee_cny/restocking_fee_cny/return_deadline`。缺字段返回 `needs_confirmation`，不会通过文本模板补造条款。换货价值、补款、关联应付、抵款生效日期分别校验；换货和抵款不生成现金流入。
- 采购按已有现货、在途、每天需求与期末安全库存求净需求，再按 MOQ／倍数取整；检查到货前缺货和容量。S07 原始输入推导建议 60 基础单位，原计划 4000 元、调整后 2400 元；少付 1600 元与延后付款分别展示，均不算实际到账。
- 组合中每个子候选先独立计算，再统一验证批次分配、接收需求、退供上限、重复采购／活动／应付占用；原店剩余销售只计算一次。重复库存、同接收需求和互斥退供分支不得叠加。
- 金额内部使用 Decimal，公共金额为人民币元、最多两位小数；非有限数值、负数、布尔数值与不允许的小数数量会被拒绝。现金观察期为 `[horizon_start, horizon_end)`。实际现金没有凭据始终为 null。

## 公共边界扩展，待总集成统一发布

没有擅自修改共享类型或前端。以下扩展经当前总集成任务协调，须随正式接线统一记录在公共契约。

### `FactQueryResult.reference_data`

用于补齐最初 DTO 未包含的主数据与业务条件：

```text
reference_data = {
  target: {store_id, sku_id, lot_id},
  evaluation_end: "YYYY-MM-DD",  // exclusive
  tables: {
    stores, products, suppliers, people, store_products, store_calendar, lots,
    promotion_stages, bundle_items, assumptions, materials, purchase_intents,
    risk_inputs, procurement_policy, transfer_policy, accounts, credit_notes
  }
}
```

`inventory` 等正式字段是事实唯一来源，禁止在补充 tables 中再次覆盖。`procurement[].record_type` 为 `purchase_order/in_transit`，`policies[].record_type` 为 `risk_policy/return_terms`。库存仍使用正式 `unit_cost_cny` 和 `base_unit`；可附 `inventory_id/shipment_line_id` 支持去重溯源。`credit_notes` 仅用于已发生业务事实，不可塞未来回放或验收答案。

每项计算检查自己的依赖。其他门店的数据质量提示保留在响应 `fact_notices[]`，不会阻断已完整的本地方案；目标库存、商品配置、日历缺失仍不可确认。需要比较多店时，查询应包含全部相关门店供给／需求，不应仅查询源店然后假定目标无库存。

### `request.business_inputs` 与兼容 `request.inputs`

已对齐最新 `00-integration-prep.md` 和公共契约：正式 `business_inputs.transfer/promotion/return/procurement` 直接进入各动作的计算参数，不写入事实、不污染留店基线，也不影响其他动作候选。`inputs` 保留既有内部调用协议与结算周期、组合等扩展：

```text
store_id, sku_id, lot_id, quantity, target_store_id, transport_fee, eta_days,
sales_settlement_days, promotion_id, stage_prices, settlement_mode, return_terms,
purchase_intent, recommended_quantity, new_payment_date, combination
```

- 同一动作不得同时使用新旧可变字段，即使值相同也明确拒绝。冲突范围：调拨的 `quantity/target_store_id/transport_fee/eta_days`；促销的 `quantity/promotion_id/stage_prices`；退供的 `quantity/settlement_mode/return_terms`；采购的 `purchase_intent/recommended_quantity/new_payment_date`。`sales_settlement_days` 仍可与所有动作输入共用。`business_inputs` 不与 `inputs.combination` 混用；组合子动作继续独立提供条件。
- 省略字段时使用已知事实；显式 `null` 不回退事实，返回该动作的精确 `missing_fields` 路径，数量／金额保留未知，不产生可执行动作或库存变化。其他候选正常计算。数量必须同时提供商品的 `base_unit`，所有门店、商品、批次、供应商、路线均校验事实范围，拒绝浏览器夹带的供应商确认或库存计算结果。
- 调拨 `route_fee_cny` 为本次用户报价；服务继续验证适用路线、单位、需求、安全量、容量、日历和效期。报价修改不是已支付费用，输入来源保留于候选 `details.input_source` 和假设。
- 促销 `products[]/price_stages[]` 对齐已知活动、组合和阶段后重算组数、组件库存、成本、底价及毛利约束；价格变化不杜撰需求弹性。改变组合成分／比例或阶段日期、删除阶段时，不能借用原组合需求或省掉活动费用，返回 `promotion.products.business_rules_and_demand` 或 `promotion.price_stages.business_rules_and_demand`，待发布相应规则和需求事实后计算。阶段结束不包含在区间内。
- 退供 `refund/exchange/offset` 分别映射退款、换货、抵款；`fee_cny` 是总执行报价，结合已知手续费拆出运费，不能低于手续费或违背供应商承担运费条款。用户输入不会生成 `supplier_confirmed/packaging_confirmed/acceptance_date`，这些条件缺失时仍不能确认执行。
- 采购 `quantity` 与最新前端文案一致，表示**原采购意向数量**，并非用户指定后的建议数量。建议数量仍根据现货、在途、时序需求和安全库存重算；例如意向 120、服务仍可建议 60。金额按基础单位处理，已有整箱意向会先转换，再应用局部修改，避免把每箱成本当作每件成本。`quantity=0` 不被当作省略；若需求仍要求补货，结果会说明仍有采购需求。既有 `inputs.recommended_quantity=0` 的明确不下单路径保留，并继续校验缺货约束。
- `purchase_order_id` 必须唯一匹配当前门店／商品的事实订单；已有订单变更仍列 `confirmed_order_change_permission_and_fee` 缺项，不能当作新的自由采购意向，也不会修改供应商确认或付款事实。无订单编号的采购输入仅是意向。

`stage_prices` 按阶段 ID 指定价格。`return_terms` 是人工已确认条件／明确情景输入，支持 `supplier_confirmed/packaging_confirmed/acceptance_date/refund_ratio_pct/freight_fee/restocking_fee`；换货还需 `replacement_sku_id/replacement_lot_id/replacement_qty/replacement_unit_cost/cash_difference`；抵款还需 `payable_id/credit_apply_date`。采购字段为已确认意向 `store_id/sku_id/quantity/unit/unit_cost/expected_arrival_date/payment_date/supplier_id`。

模型工具不得自己声称供应商／包装已确认；材料确认和权限由 Agent 与执行服务负责。事实更新应通过 FactService 发布，闭店等变化必须更新日历事实，不靠请求布尔量绕过。

材料确认新增采购意向后，使用 `inputs.purchase_intent={"intent_id": "已确认材料的 draft_id"}` 选择当前事实中的那条意向；金额、数量、供应商、单位和日期均从该事实读取。提供 intent_id 时禁止同时覆盖其他字段，未知／跨范围 ID 明确拒绝。同店同 SKU 存在多个意向且未指定 ID 时，仅采购候选返回 `missing_fields=["purchase_intent.intent_id"]` 和 null 数量／现金，留店、调拨等候选继续计算。Agent 由明确的已确认材料引用注入该 ID，不能让模型猜选最新意向或复制金额；只有单意向的人工情景计算继续支持原有显式条件修改。

`risk_keys` 采用正式 `scenario:store:sku:lot:risk_type`，当前一次比较必须属于同一目标批次。库存去重使用独立批次键。`horizon_start` 必须匹配事实 `as_of` 当地日期，改变起点须先查询相应时点事实。

### 候选和金额

正式枚举严格为 `keep/transfer/promotion/return/procurement`，只在服务边界将内部 `retain/purchase` 转换一次。返回全部正式必填字段、数量单位、现金时间表和版本。

所有候选必含 `inventory_changes[]`，组合组也提供联合库存变化。按 `store_id + sku_id + lot_id` 返回即时 `quantity_before/quantity_after/quantity_delta/base_unit/source_ref`；调拨移出、移入数量守恒，不使用需求周期末预测量。S01 调出批次 `LOT-001-001` 在 ST-001 为 120→40，在 ST-002 为 0→80；ST-002 原有 10 属于另一个批次，不能写成同批 10→90。事实缺少数量时 before/after 为 null。促销上线、保留原状和采购意向均未立即移动实物库存，返回空数组；退供列出计划移出数量，不把未来换入批次当作已收到。计算仍是候选模拟，不代表已经执行。计算版本升级为 `retail-comparison-v2.2`，新字段也参与内容标识。

候选 `calculation.execution_plan` 保存计算出的完整内部执行计划，包含 `type/strategy_id/feasibility/allocations/actions/allocated_qty` 等；供服务端重算比对后保存，绝不能信任浏览器回传的金额或行动。`feasibility` 为 `feasible/blocked/needs_confirmation`；公共 `feasible` 仅第一种为 true。

金额还分列 `planned_stock_cost_cny`、`expected_sales_cost_recovered_cny`、`inventory_cost_reduction_cny`、`transfer_movement_cost_cny`、`incremental_net_cash_cny`。调拨搬移成本不是库存消耗或现金释放；库存减少只计相应销售／退货／换入与新增采购的影响，并带 `inventory_effect_scope`，不可把互斥候选相加。采购公共售出／剩余量仅覆盖拟购批次，整个门店 SKU 的期末量另列 `store_sku_ending_qty`；少付／延后付款另列。

调拨 action：`type/store_id/source_store_id/target_store_id/sku_id/lot_id/quantity/unit_cost/route_id/arrival_date/transport_fee`。

退供 action：`type/store_id/sku_id/lot_id/quantity/unit_cost/supplier_id/term_id/settlement_mode/expected_settlement_amount/expected_acceptance_date/freight_fee/restocking_fee`，及对应换货／抵款字段。

采购 action：`type="purchase"/store_id/sku_id/quantity/unit/unit_cost/supplier_id/expected_arrival_date/payment_date/intent_id`。尚未收货不得编造 lot_id。

促销 action：`type/store_id/sku_id/lot_id/quantity/unit_cost/execution_fee/promotion_id/bundle_id/components/stages`。quantity 单位为组；components 分列实际 SKU／批次数量和基础单位；stages 包含阶段 ID、日期和组合价。

### `candidate_groups`：组合选择

```python
request = {"inputs": {"sales_settlement_days": 0, "combination": [
    {"type": "transfer", "target_store_id": "ST-002", "quantity": 40},
    {"type": "transfer", "target_store_id": "ST-004", "quantity": 10},
]}}
# public:
group = {
    "group_id": "GROUP-<content-hash>",
    "member_candidate_ids": ["CAND-...", "CAND-..."],
    "feasible": True, "exclusion_reasons": [], "missing_fields": [],
    "calculation": {"execution_plan": {"type": "combination", "children": [...]}, ...},
}
```

输入子动作使用正式 `transfer/promotion/return/procurement`。同类与混合组合均用 `candidate_groups`，不新增假 action_type。成员仍在 `candidates` 中并各自具备独立可行性与完整执行计划；组合整体可能不可行，不能把成员分别可行当作组合可行。组合数量分 SKU／单位列于 `quantity_lines`，不将袋、盒、瓶加成一个数量。

总集成保存请求的 `candidate_id` 可选择 `candidate_id` 或 `group_id`；原子验证组合后按 children 建多任务。单个成员可单独选择，其计算基于原事实，没有借用其他组成员执行后的库存。

### 稳定标识

`comparison_id/candidate_id/group_id/baseline_id` 均为稳定内容哈希，包含事实、上下文、请求、结果、计算与政策版本。`query_id` 只是追踪 ID，不进入哈希。同样输入重复执行得到相同 ID，事实版本、政策、假设或结果变化产生新 ID。这些 ID 不替代数据库的版本和幂等校验。比较输出不能直接作为未经重算的执行授权。

## 验证与未接线项

验证命令：

```text
python -m unittest tests.hackathon.test_calculations tests.hackathon.test_calculations_contract tests.hackathon.test_calculations_business_inputs -q
```

结果：49 项通过（35 项算法测试，14 项正式 DTO／实际 FactService 联测）。覆盖输入不变性、缺项、非法数值、边界日期、在途去重、运费变更、闭店、目标已有库存替代、阶段库存共享、结构化退供、换货／抵款、采购 60、延后付款、超额组合、稳定 ID、跨租户／版本／风险键拒绝，以及多采购意向明确选择、未选择的局部缺项、未知意向和覆盖已确认金额拒绝。真实 RetailFactService 在独立临时 SQLite 中生成 DTO，再由计算服务执行两次比较，验证正式模块一致性；未读取真实业务数据库。

本轮额外 14 项动作输入测试覆盖：新旧冲突、动作局部作用域、输入不变性与稳定标识、同批次库存守恒、显式 null、门店／批次／单位／路线校验、促销价格与变更后的需求缺项、退供报价不伪造供应商接受、采购意向与建议量分离、订单权限缺项、整箱转基础单位及零数量。上述命令完整运行 63 项全部通过（原有 49 项、新增 14 项）。

另以决策时点输入逐一调用 S01／S04／S05／S06／S07／S09／S10 的公共服务：全部正常返回候选；S10 缺需求预测时所有依赖候选不可确认并列缺项。S07 将观察期缩短为 `horizon_end="2026-10-10"` 会合法生成数量 0 的不下单建议；执行模块需支持明确的不下单确认，不能统一用正数量校验拒绝它。

尚由总集成负责：公共 DTO 扩展批准、路由注册、Agent 工具依赖注入、保存／确认时重算、执行与资金回执。本文不声称 HTTP 端到端、真实模型或前端已完成。

本算法明确边界：有限候选比较不声称全局最优；同 SKU 同时采购与处置、接收门店同时作为另一动作调出店等复杂流量组合会要求进一步统一规划，不会输出未经校验的成功组合。缺少供应商条款、结算周期或真实价格弹性时保持缺项／假设；不会引用 05 未来事件或 06 验收答案补齐。

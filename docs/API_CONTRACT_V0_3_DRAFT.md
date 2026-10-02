# 货不压钱｜连锁零售库存资金 Agent API Contract

版本：v0.3  
用途：黑客松 MVP 前后端联调  
范围：面向多业态连锁零售的库存资金运营；接口模型保持零售通用，联调示例使用虚构零食连锁数据。

## 1. 合同目标

前端朱负责按本文件消费接口、呈现加载与结果；后端魏负责实现统一接口、五个 Agent、工具计算和校验。双方以相同的字段名、单位、状态值和示例数据联调。演示门店、商品、供应商和交易数据均为虚构，不映射任何真实连锁企业。

五个 Agent：

| agent_type | 名称 | 主要输出 |
|---|---|---|
| slow_moving | 滞销诊断 Agent | 高占款、低动销商品及处理建议 |
| store_transfer | 跨门店调拨 Agent | 调出门店、调入门店、调拨量及调拨后库存 |
| near_expiry | 近效期 Agent | 临期批次、效期前预计销量、风险金额及建议 |
| procurement_brake | 采购刹车 Agent | 在途与未到货订单、建议调整量、缺货风险 |
| cashflow_simulation | 资金周转模拟 Agent | 基线与方案的库存资金占用、预计采购支出和缺货风险 |

本版本只生成建议和模拟结果，不直接修改库存、采购单或收银系统数据。

## 2. 通用约定

- JSON 编码为 UTF-8。
- 日期使用 YYYY-MM-DD；时间使用带时区的 ISO 8601 字符串，演示数据时区为 Asia/Shanghai。
- 所有金额字段以人民币分为单位，字段名以 _fen 结尾；不使用浮点数表示金额。
- 数量乘单位成本得到金额时，结果四舍五入到最近的整数分。
- 数量使用 JSON number，并提供单位，如 piece、box、kg。
- 比例字段统一使用 0 到 1 之间的小数，例如 15% 表示 0.15。
- 0 表示实际数值为零；未知或缺失使用 null，并在 warnings 或 missing_fields 中说明。
- 数组缺省或为空表示不按该字段筛选；具体 Agent 参数中的必填项除外。
- 每次运行携带 data_version 和 policy_version，方便复现演示结果。
- 请求 params 中明确提供的值优先于经营规则；未提供时使用匹配到的门店、品类或通用规则。仍缺少必需值时返回 needs_input，并说明缺少项。
- 业务指标和金额由后端工具计算；模型负责理解问题、组织工具调用和解释有证据支持的结果。
- 推荐说明必须引用返回的证据；没有数据支撑时返回 needs_input 或告警，不编造数字。

## 3. 共享数据模型

以下字段是五个 Agent 共用的最小数据契约。业务模型适用于一般连锁零售；本合同中的示例数据用零食门店、零食 SKU 和零食采购/销售/调拨展示。示例 ID 使用 `STORE-HZ-001`、`SNK-001`、`PO-001`、`LOT-001` 等格式。

### 3.1 门店 stores

| 字段 | 类型 | 必需 | 说明 |
|---|---|---:|---|
| store_id | string | 是 | 门店唯一 ID |
| store_name | string | 是 | 门店名称 |
| region_id | string | 是 | 区域 ID |
| status | string | 是 | active 或 inactive |

### 3.2 商品 skus

| 字段 | 类型 | 必需 | 说明 |
|---|---|---:|---|
| sku_id | string | 是 | 商品唯一 ID |
| sku_name | string | 是 | 商品名称 |
| category_id | string | 是 | 品类 ID |
| brand_name | string/null | 否 | 演示品牌或商品品牌 |
| barcode | string/null | 否 | 商品条码 |
| specification | string | 是 | 规格，如 80g/袋、500ml/瓶 |
| unit | string | 是 | 库存计量单位；MVP 建议统一用 piece、bag、bottle、box 等，不混用箱和单件 |
| shelf_life_days | integer/null | 否 | 保质期天数；未知时为 null，不据此推断批次到期日 |
| unit_cost_fen | integer | 是 | 默认单位成本，人民币分 |
| sale_price_fen | integer | 否 | 当前零售价，人民币分 |
| min_order_qty | number/null | 否 | 单次最低采购数量；未配置时为 null |
| case_pack_qty | number/null | 否 | 一箱对应的库存计量单位数量；未配置时为 null |

### 3.3 库存快照 inventory_snapshots

| 字段 | 类型 | 必需 | 说明 |
|---|---|---:|---|
| snapshot_id | string | 是 | 快照唯一 ID |
| store_id | string | 是 | 门店 ID |
| sku_id | string | 是 | 商品 ID |
| snapshot_at | string | 是 | 快照时间，ISO 8601 |
| on_hand_qty | number | 是 | 实物库存，包含已预留库存 |
| reserved_qty | number | 是 | 已预留数量，不能再次调拨或销售 |
| in_transit_qty | number | 是 | 在途数量，单独统计，不计入实物库存 |

计算口径：

- 可用库存 available_qty = max(on_hand_qty - reserved_qty, 0)。
- 滞销诊断、调拨和补货计算使用 available_qty；已预留库存不能视为可销售或可调拨库存。
- 当前库存成本金额 inventory_value_at_cost_fen = on_hand_qty × unit_cost_fen。
- 在途数量不计入当前实物库存金额；现金流模拟可单独考虑其采购支出。
- `in_transit_qty` 是库存快照中的汇总值；有 `purchase_orders` 明细时，采购预测以未收货采购单为准，不能把汇总在途数量再重复加一次。两者不一致时返回数据告警。
- 同一商品匹配多条经营规则时，优先使用门店规则，其次品类规则，最后通用规则。

### 3.4 日销售 sales_daily

| 字段 | 类型 | 必需 | 说明 |
|---|---|---:|---|
| business_date | string | 是 | 营业日期，YYYY-MM-DD |
| store_id | string | 是 | 门店 ID |
| sku_id | string | 是 | 商品 ID |
| net_sold_qty | number | 是 | 净销量，退货已在上游扣除 |
| sales_amount_fen | integer | 是 | 净销售额，人民币分 |
| is_promotion | boolean/null | 否 | 该商品当日是否处于促销；未知时为 null，仅用于解释/分层分析，不改变净销量 |
| unit_sale_price_fen | integer/null | 否 | 当日实际单位成交价，人民币分；促销日建议提供 |

销量窗口口径：演示数据为所选门店和 SKU 提供窗口内每日记录；当日无销售时写 `net_sold_qty: 0`。缺少日期记录代表数据不完整，不得直接当作零销量。

### 3.5 采购单 purchase_orders

| 字段 | 类型 | 必需 | 说明 |
|---|---|---:|---|
| po_id | string | 是 | 采购单 ID |
| store_id | string | 是 | 收货门店 ID |
| sku_id | string | 是 | 商品 ID |
| supplier_id | string/null | 否 | 供应商 ID；演示可使用虚构供应商编号 |
| ordered_qty | number | 是 | 下单总量 |
| received_qty | number | 是 | 已收货数量 |
| open_qty | number | 是 | 未收货数量 |
| expected_arrival_date | string | 否 | 预计到货日期 |
| lead_time_days | integer | 否 | 供应商交期天数 |
| cancellable_until | string | 否 | 可取消或修改采购单的截止日期 |

### 3.6 批次库存 inventory_lots

| 字段 | 类型 | 必需 | 说明 |
|---|---|---:|---|
| lot_id | string | 是 | 批次 ID |
| store_id | string | 是 | 门店 ID |
| sku_id | string | 是 | 商品 ID |
| qty | number | 是 | 批次剩余数量 |
| expiry_date | string/null | 是 | 到期日期，YYYY-MM-DD；未知时为 null，近效期 Agent 仅分析有有效到期日的批次 |
| unit_cost_fen | integer | 否 | 批次单位成本；缺省时使用商品默认成本 |

批次口径：同一门店、同一 SKU 的批次 `qty` 之和应等于库存快照 `on_hand_qty`。演示数据若无法提供批次明细，不要为满足接口而编造到期日；该商品应从近效期分析范围排除并返回缺失数据告警。

### 3.7 经营规则 policies

| 字段 | 类型 | 必需 | 说明 |
|---|---|---:|---|
| policy_id | string | 是 | 规则 ID |
| policy_version | string | 是 | 规则版本 |
| category_id | string | 否 | 适用品类；缺省表示通用规则 |
| store_id | string | 否 | 适用门店；缺省表示通用规则 |
| target_cover_days | number | 否 | 目标库存覆盖天数 |
| safety_stock_days | number | 否 | 安全库存天数；采购建议用于评估缺货风险 |
| min_display_qty | number | 否 | 最低陈列库存 |
| near_expiry_days | integer | 否 | 近效期关注天数 |
| markdown_floor_price_fen | integer/null | 否 | 促销最低价，人民币分；生成降价建议时不得低于该价格，未设置时为 null |
| transfer_enabled | boolean | 是 | 是否允许门店间调拨 |

### 3.8 零食连锁演示数据 snack-demo-v1

以下商品和门店只用于展示数据结构与 Agent 结果。产品接口仍使用通用的门店、SKU、库存、销售和采购字段，之后可以替换成其他零售业态的数据。

门店：

| store_id | store_name | region_id | status |
|---|---|---|---|
| STORE-HZ-001 | 滨江店 | HZ-BJ | active |
| STORE-HZ-002 | 文二路店 | HZ-XH | active |
| STORE-HZ-003 | 城西店 | HZ-XH | active |

商品（金额单位为人民币分；数量单位按 unit 列）：

| sku_id | sku_name | category_id | specification | unit | unit_cost_fen | sale_price_fen | shelf_life_days | min_order_qty | case_pack_qty |
|---|---|---|---|---|---:|---:|---:|---:|---:|
| SNK-001 | 椒盐海苔脆片 | SNACK-CHIPS | 45g/袋 | bag | 350 | 600 | 180 | 24 | 24 |
| SNK-002 | 每日坚果组合 | SNACK-NUTS | 120g/袋 | bag | 880 | 1290 | 120 | 6 | 6 |
| SNK-003 | 草莓牛奶 | SNACK-DRINK | 200ml/瓶 | bottle | 230 | 350 | 180 | 24 | 24 |
| SNK-004 | 香辣豆干 | SNACK-BEAN | 90g/袋 | bag | 270 | 450 | 90 | 12 | 12 |

示例经营规则（`policy_version=snack-policy-v1`）：

| policy_id | category_id | target_cover_days | safety_stock_days | min_display_qty | near_expiry_days | markdown_floor_price_fen | transfer_enabled |
|---|---|---:|---:|---:|---:|---:|---|
| POLICY-NUTS | SNACK-NUTS | 14 | 5 | 8 | 30 | null | true |
| POLICY-CHIPS | SNACK-CHIPS | 14 | 7 | 6 | 30 | 450 | true |
| POLICY-BEAN | SNACK-BEAN | 14 | 5 | 6 | 30 | 320 | true |

固定演示场景及预期计算：

| Agent | 输入数据摘要 | 预期结果 |
|---|---|---|
| slow_moving | 滨江店每日坚果 25 袋，近 14 天销量为 0，单位成本 880 分，最低陈列量 8 袋 | 库存成本金额 22,000 分；可用超额库存 17 袋；建议暂停补货并复核促销 |
| store_transfer | 椒盐海苔脆片：滨江店 90 袋、近 14 天售 28 袋；文二路店 6 袋、近 14 天售 56 袋；目标覆盖 14 天 | 滨江店日均 2 袋、文二路店日均 4 袋；建议最多调拨 50 袋，调拨前后覆盖天数需展示 |
| near_expiry | 文二路店香辣豆干批次 40 袋，2026-10-18 到期；近 14 天日均销量 1 袋 | 截至 2026-10-02 剩 16 天，预计售出 16 袋，风险数量估算 24 袋，成本风险敞口 6,480 分 |
| procurement_brake | 城西店每日坚果现货 10 袋，日均销量 2 袋；采购单 PO-003 未到货 30 袋，预计 2026-10-05 到货且可于 2026-10-04 前调整 | 预计到货时现货约 4 袋，叠加在途为 34 袋；按 14 天覆盖目标 28 袋，建议将采购量减少 6 袋（整箱 6 袋） |
| cashflow_simulation | 对 PO-003 采用采购刹车建议，减少每日坚果采购 6 袋，单位成本 880 分 | 预计减少未来采购承诺 5,280 分；这表示预计避免的采购支出，不表示银行账户余额已增加 |

代表性销售记录示例（完整演示数据应提供所需窗口内的每日记录）：

~~~json
[
  {
    "business_date": "2026-09-30",
    "store_id": "STORE-HZ-001",
    "sku_id": "SNK-001",
    "net_sold_qty": 2,
    "sales_amount_fen": 1200,
    "is_promotion": false,
    "unit_sale_price_fen": 600
  },
  {
    "business_date": "2026-09-30",
    "store_id": "STORE-HZ-002",
    "sku_id": "SNK-001",
    "net_sold_qty": 4,
    "sales_amount_fen": 2400,
    "is_promotion": false,
    "unit_sale_price_fen": 600
  }
]
~~~

代表性库存快照示例（调拨 Agent 使用同一口径比较两店现货与销量）：

~~~json
[
  {
    "snapshot_id": "INV-STORE-HZ-001-SNK-001-20261002",
    "store_id": "STORE-HZ-001",
    "sku_id": "SNK-001",
    "snapshot_at": "2026-10-02T08:00:00+08:00",
    "on_hand_qty": 90,
    "reserved_qty": 0,
    "in_transit_qty": 0
  },
  {
    "snapshot_id": "INV-STORE-HZ-002-SNK-001-20261002",
    "store_id": "STORE-HZ-002",
    "sku_id": "SNK-001",
    "snapshot_at": "2026-10-02T08:00:00+08:00",
    "on_hand_qty": 6,
    "reserved_qty": 0,
    "in_transit_qty": 0
  },
  {
    "snapshot_id": "INV-STORE-HZ-001-SNK-002-20261002",
    "store_id": "STORE-HZ-001",
    "sku_id": "SNK-002",
    "snapshot_at": "2026-10-02T08:00:00+08:00",
    "on_hand_qty": 25,
    "reserved_qty": 0,
    "in_transit_qty": 0
  },
  {
    "snapshot_id": "INV-STORE-HZ-002-SNK-004-20261002",
    "store_id": "STORE-HZ-002",
    "sku_id": "SNK-004",
    "snapshot_at": "2026-10-02T08:00:00+08:00",
    "on_hand_qty": 40,
    "reserved_qty": 0,
    "in_transit_qty": 0
  },
  {
    "snapshot_id": "INV-STORE-HZ-003-SNK-002-20261002",
    "store_id": "STORE-HZ-003",
    "sku_id": "SNK-002",
    "snapshot_at": "2026-10-02T08:00:00+08:00",
    "on_hand_qty": 10,
    "reserved_qty": 0,
    "in_transit_qty": 30
  }
]
~~~

代表性采购单示例：

~~~json
{
  "po_id": "PO-003",
  "store_id": "STORE-HZ-003",
  "sku_id": "SNK-002",
  "supplier_id": "SUP-001",
  "ordered_qty": 30,
  "received_qty": 0,
  "open_qty": 30,
  "expected_arrival_date": "2026-10-05",
  "lead_time_days": 3,
  "cancellable_until": "2026-10-04"
}
~~~

代表性临期批次：

~~~json
{
  "lot_id": "LOT-004-01",
  "store_id": "STORE-HZ-002",
  "sku_id": "SNK-004",
  "qty": 40,
  "expiry_date": "2026-10-18",
  "unit_cost_fen": 270
}
~~~

## 4. Agent 运行接口

### 4.1 运行 Agent

POST /api/v1/agent-runs

本版本使用同步请求。请求期间前端显示加载状态；响应的 steps 用于展示本次运行经历的查询和计算步骤。

请求字段：

| 字段 | 类型 | 必需 | 说明 |
|---|---|---:|---|
| request_id | string | 是 | 前端生成的 UUID，用于请求和日志关联 |
| agent_type | string | 是 | 五种 Agent 之一，见第 1 节 |
| user_input | string | 否 | 用户自然语言问题 |
| scope | object | 是 | 本次分析范围 |
| params | object | 是 | 对应 Agent 的结构化参数；无参数时传空对象 |
| data_version | string | 是 | 数据集版本，例如 snack-demo-v1 |
| session_id | string | 否 | 多轮会话 ID；会话内连续调整同一方案时复用。首次可由前端生成 UUID |
| policy_version | string | 否 | 规则版本；缺省时使用数据集默认版本 |

scope 字段：

| 字段 | 类型 | 必需 | 说明 |
|---|---|---:|---|
| as_of | string | 是 | 分析基准日期 |
| store_ids | string[] | 否 | 门店筛选 |
| sku_ids | string[] | 否 | 商品筛选 |
| category_ids | string[] | 否 | 品类筛选 |

如果自然语言问题与结构化参数冲突，后端以结构化参数为准，并返回 PARAM_CONFLICT 告警；涉及库存、采购或效期硬约束时，返回 needs_input，请用户确认。

请求示例：

~~~json
{
  "request_id": "c1fb0d72-4310-4a88-8a67-0824123147c2",
  "agent_type": "slow_moving",
  "user_input": "找出占款高且近两周没有销售的商品",
  "scope": {
    "as_of": "2026-10-02",
    "store_ids": ["STORE-HZ-001"],
    "sku_ids": [],
    "category_ids": ["SNACK-NUTS"]
  },
  "params": {
    "sales_window_days": 14,
    "no_sale_days_gte": 14,
    "min_inventory_value_fen": 20000,
    "limit": 10
  },
  "data_version": "snack-demo-v1",
  "policy_version": "snack-policy-v1"
}
~~~

调拨 Agent 请求示例：

~~~json
{
  "request_id": "transfer-001",
  "agent_type": "store_transfer",
  "user_input": "把滨江店多出的海苔脆片调一些到文二路店，尽量保证两边都有两周库存",
  "scope": {
    "as_of": "2026-10-02",
    "store_ids": ["STORE-HZ-001", "STORE-HZ-002"],
    "sku_ids": ["SNK-001"],
    "category_ids": ["SNACK-CHIPS"]
  },
  "params": {
    "source_store_ids": ["STORE-HZ-001"],
    "target_store_ids": ["STORE-HZ-002"],
    "sales_window_days": 14,
    "min_source_cover_days": 14,
    "target_cover_days": 14,
    "max_transfer_qty": 50
  },
  "data_version": "snack-demo-v1",
  "policy_version": "snack-policy-v1"
}
~~~

### 4.2 统一响应

成功处理、部分处理和业务性失败均返回统一 JSON 结构。HTTP 请求错误另按第 7 节返回对应状态码。

| 字段 | 类型 | 说明 |
|---|---|---|
| request_id | string | 回显请求 ID |
| run_id | string | 后端生成的运行 ID |
| agent_type | string | 回显 Agent 类型 |
| status | string | succeeded、partial、no_data、needs_input、awaiting_confirmation、failed |
| summary | string | 面向用户的简短结果摘要 |
| session_id | string/null | 回显会话 ID；非会话请求可为 null |
| assistant_message | string | 对话页展示的 Agent 回复 |
| scenario_preview | object/null | 等待确认的结构化情景；仅在 status 为 awaiting_confirmation 时有值 |
| steps | object[] | 查询、计算、模型等步骤的状态 |
| items | object[] | 排序后的结果项；无结果时为空数组 |
| missing_fields | string[] | 计算结果缺少的关键字段 |
| follow_up_questions | string[] | status 为 needs_input 时展示给用户的补充问题；其他状态为空数组 |
| warnings | object[] | 数据质量、口径或参数告警 |
| error | object/null | 失败信息；成功时为 null |
| data_version | string | 实际使用的数据版本 |
| policy_version | string | 实际使用的规则版本 |
| created_at | string | 运行创建时间，ISO 8601 |
| completed_at | string/null | 完成时间；未完成时为 null |

会话规则：

- `session_id` 用于关联同一会话的多轮输入；后端可复用已解析的门店范围、周期和方案参数。
- 当前请求明确传入的 `scope` 和 `params` 优先于会话上下文。
- 对话文字仅用于解析意图和生成解释；实际计算必须使用结构化的 `scope`、`params` 和演示数据。
- 资金方案确认前返回 `awaiting_confirmation`、情景卡片和空 `items`；确认后再运行计算并返回结果。
- `awaiting_confirmation` 状态不得提前返回或展示模拟结果数字。

`scenario_preview` 字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| scenario_id | string | 本次待确认方案 ID |
| title | string | 情景卡片标题 |
| horizon_days | integer | 模拟周期 |
| store_ids | string[] | 涉及门店 |
| adjustments | object[] | 拟调整的采购、调拨或促销动作 |
| assumptions | string[] | 明示给用户的计算假设 |
| confirmation_required | boolean | 本方案是否需要用户确认后计算 |

steps[]：

| 字段 | 类型 | 说明 |
|---|---|---|
| step_id | string | 步骤 ID |
| name | string | 稳定的步骤名，如 query_inventory |
| label | string | 前端展示文案 |
| status | string | succeeded、skipped、failed |
| message | string | 可展示给用户的状态说明 |

items[]：

| 字段 | 类型 | 说明 |
|---|---|---|
| item_id | string | 结果项唯一 ID |
| entity | object | 门店、商品、批次或场景的实体标识 |
| priority | string | high、medium、low |
| metrics | object[] | 计算指标，统一使用 key、label、value、unit |
| evidence | object[] | 支撑结果的源数据字段及记录 ID |
| recommendations | object[] | 建议动作；只建议，不直接执行 |
| details | object | Agent 专属的结构化结果 |

metrics[] 示例：

~~~json
{
  "key": "inventory_value_at_cost_fen",
  "label": "当前库存成本金额",
  "value": 22000,
  "unit": "fen"
}
~~~

evidence[] 示例：

~~~json
{
  "source": "inventory_snapshots",
  "record_id": "INV-STORE-HZ-001-SNK-002-20261002",
  "field": "on_hand_qty",
  "value": 25,
  "as_of": "2026-10-02"
}
~~~

recommendations[] 示例：

~~~json
{
  "recommendation_id": "REC-001",
  "action_type": "pause_replenishment",
  "action_params": {
    "store_id": "STORE-HZ-001",
    "sku_id": "SNK-002"
  },
  "rationale": "近 14 天无销售，且当前库存成本金额高于关注阈值。",
  "evidence_ids": ["INV-STORE-HZ-001-SNK-002-20261002"],
  "approval_required": true,
  "impact_estimate": {
    "kind": "avoid_future_purchase",
    "amount_fen": null,
    "period_days": 30,
    "assumptions": ["需要采购计划数据后才能测算金额"]
  }
}
~~~

允许的 action_type：

- pause_replenishment
- reduce_open_purchase_order
- transfer_stock
- markdown
- prioritize_sale
- review_data
- no_action

统一响应示例：

~~~json
{
  "request_id": "c1fb0d72-4310-4a88-8a67-0824123147c2",
  "run_id": "run-0001",
  "agent_type": "slow_moving",
  "status": "succeeded",
  "summary": "发现 1 个库存资金占用偏高且近 14 天无销售的商品：每日坚果组合。",
  "session_id": null,
  "assistant_message": "滨江店每日坚果组合近 14 天无销售，当前库存成本金额为 220 元。建议暂停补货并复核促销方案。",
  "scenario_preview": null,
  "steps": [
    {
      "step_id": "step-1",
      "name": "query_inventory",
      "label": "查询门店库存",
      "status": "succeeded",
      "message": "已读取 2026-10-02 库存快照"
    },
    {
      "step_id": "step-2",
      "name": "calculate_priority",
      "label": "计算占款与动销指标",
      "status": "succeeded",
      "message": "已按成本金额和无销售天数排序"
    }
  ],
  "items": [
    {
      "item_id": "ITEM-001",
      "entity": {
        "type": "store_sku",
        "id": "STORE-HZ-001:SNK-002",
        "store_id": "STORE-HZ-001",
        "store_name": "滨江店",
        "sku_id": "SNK-002",
        "sku_name": "每日坚果组合 120g"
      },
      "priority": "high",
      "metrics": [
        {
          "key": "inventory_value_at_cost_fen",
          "label": "当前库存成本金额",
          "value": 22000,
          "unit": "fen"
        },
        {
          "key": "days_since_last_sale",
          "label": "距最近销售天数",
          "value": 19,
          "unit": "day"
        }
      ],
      "evidence": [
        {
          "source": "inventory_snapshots",
          "record_id": "INV-STORE-HZ-001-SNK-002-20261002",
          "field": "on_hand_qty",
          "value": 25,
          "as_of": "2026-10-02"
        },
        {
          "source": "skus",
          "record_id": "SNK-002",
          "field": "unit_cost_fen",
          "value": 880,
          "as_of": "2026-10-02"
        }
      ],
      "recommendations": [
        {
          "recommendation_id": "REC-001",
          "action_type": "pause_replenishment",
          "action_params": {
            "store_id": "STORE-HZ-001",
            "sku_id": "SNK-002"
          },
          "rationale": "近 14 天无销售，且当前库存成本金额高于关注阈值。",
          "evidence_ids": ["INV-STORE-HZ-001-SNK-002-20261002", "SNK-002"],
          "approval_required": true,
          "impact_estimate": {
            "kind": "avoid_future_purchase",
            "amount_fen": null,
            "period_days": 30,
            "assumptions": ["需要采购计划数据后才能测算金额"]
          }
        }
      ],
      "details": {
        "avg_daily_sales_qty": 0,
        "days_since_last_sale": 19,
        "days_of_supply": null,
        "target_stock_qty": 8,
        "excess_qty": 17
      }
    }
  ],
  "missing_fields": [],
  "follow_up_questions": [],
  "warnings": [
    {
      "code": "NO_RECENT_SALES",
      "message": "平均日净销量为 0，库存覆盖天数无法计算。"
    }
  ],
  "error": null,
  "data_version": "snack-demo-v1",
  "policy_version": "snack-policy-v1",
  "created_at": "2026-10-02T10:00:00+08:00",
  "completed_at": "2026-10-02T10:00:03+08:00"
}
~~~

### 4.3 资金模拟的会话流程

资金周转模拟 Agent 支持“先整理情景、用户确认后计算”。未确认时前端只展示会话消息和内嵌情景卡；结果生成后再展示方案对比。

第一轮：解析用户意图并返回待确认情景，不返回计算结果。

~~~json
{
  "request_id": "turn-001",
  "session_id": "SIM-HZ-001",
  "agent_type": "cashflow_simulation",
  "user_input": "城西店每日坚果的 PO-003 少采购 6 袋，看看资金占用和缺货风险",
  "scope": {
    "as_of": "2026-10-02",
    "store_ids": ["STORE-HZ-003"],
    "sku_ids": ["SNK-002"],
    "category_ids": ["SNACK-NUTS"]
  },
  "params": {
    "operation": "preview",
    "horizon_days": 30
  },
  "data_version": "snack-demo-v1",
  "policy_version": "snack-policy-v1"
}
~~~

待确认响应：

~~~json
{
  "request_id": "turn-001",
  "run_id": "run-preview-001",
  "session_id": "SIM-HZ-001",
  "agent_type": "cashflow_simulation",
  "status": "awaiting_confirmation",
  "summary": "模拟情景已整理，等待确认。",
  "assistant_message": "我会按以下条件测算。请确认或调整后开始模拟。",
  "scenario_preview": {
    "scenario_id": "SCN-PO-003-REDUCE-6",
    "title": "调整城西店每日坚果采购",
    "horizon_days": 30,
    "store_ids": ["STORE-HZ-003"],
    "adjustments": [
      {
        "action_type": "reduce_open_purchase_order",
        "action_params": {
          "po_id": "PO-003",
          "sku_id": "SNK-002",
          "qty": 6,
          "unit": "bag"
        }
      }
    ],
    "assumptions": ["仅调整可取消的未到货数量", "按近14天日均销量估算未来需求"],
    "confirmation_required": true
  },
  "steps": [],
  "items": [],
  "missing_fields": [],
  "follow_up_questions": [],
  "warnings": [],
  "error": null,
  "data_version": "snack-demo-v1",
  "policy_version": "snack-policy-v1",
  "created_at": "2026-10-02T10:00:00+08:00",
  "completed_at": "2026-10-02T10:00:00+08:00"
}
~~~

用户点击“开始模拟”后，前端复用 `session_id` 和 `scenario_id`，发送 `operation=simulate`、`confirmed=true` 及已确认的结构化调整。后端才计算基线与方案；此确认只启动模拟，不执行真实采购变更。

## 5. 五种 Agent 参数和专属结果

每种 Agent 复用第 4 节的公共请求与响应结构。Agent 特有内容放在 params 和每个结果项的 details。

| agent_type | params 建议字段 | details 建议字段 |
|---|---|---|
| slow_moving | sales_window_days、no_sale_days_gte、min_inventory_value_fen、limit | avg_daily_sales_qty、days_since_last_sale、target_stock_qty、excess_qty、excess_value_at_cost_fen |
| store_transfer | source_store_ids、target_store_ids、sales_window_days、min_source_cover_days、target_cover_days、max_transfer_qty | source_available_qty、target_available_qty、recommended_transfer_qty、source_after_qty、target_after_qty |
| near_expiry | within_days、sales_window_days、limit | lot_id、expiry_date、days_to_expiry、qty、expected_sales_before_expiry_qty、risk_qty、risk_value_at_cost_fen |
| procurement_brake | horizon_days、min_safety_stock_days、include_open_orders | open_qty、projected_stock_qty、recommended_order_qty、suggested_reduction_qty、stockout_risk、case_pack_adjusted_qty |
| cashflow_simulation | operation、horizon_days、scenario_id、adjustments、assumptions、confirmed | baseline_inventory_capital_fen、scenario_inventory_capital_fen、baseline_purchase_commitment_fen、scenario_purchase_commitment_fen、estimated_avoided_purchase_commitment_fen、stockout_risks、inventory_capital_series |

`cashflow_simulation.details` 口径：所有金额为人民币分。`stockout_risks[]` 至少包含 `store_id`、`sku_id`、方案库存覆盖天数和风险等级；`inventory_capital_series[]` 按日或周返回 `date`、`baseline_capital_fen` 和 `scenario_capital_fen`。输出表示库存成本占用与预计采购承诺，不表示银行账户余额。

规则：

- 任何金额估算都要返回 impact_estimate.assumptions。
- `cashflow_simulation.operation=preview` 只返回待确认的 `scenario_preview`，`items` 必须为空；`operation=simulate` 必须携带 `scenario_id` 和 `confirmed=true`。
- `adjustments[]` 使用 `{ "action_type": string, "action_params": object }`；MVP 支持 `reduce_open_purchase_order`、`pause_replenishment`、`transfer_stock`、`markdown` 和 `prioritize_sale`，每项都必须关联门店、SKU 或采购单。
- 跨门店调拨本身不会降低全链路库存总额；影响标为库存配置改善或预计避免新增采购，不能直接表述为已释放现金。
- 采购金额变化属于预计避免的未来支出，不等于当前库存现金回收。
- 近效期金额按批次成本估算；缺批次成本时使用商品默认成本并返回告警。
- 现金流模拟必须同时返回基线和方案值，并列出模型假设。
- 资金金额用于估算被库存占用的成本和未来采购支出；除非接入真实银行余额及应收应付数据，不输出“老板账上现金余额”。
- `confirmed=true` 只表示用户确认运行模拟，不代表批准或执行采购、促销、调拨等真实业务动作。
- 本 MVP 不读取银行余额、应收应付、租金工资等完整财务数据，因此不得把库存资金占用或预计采购支出变化称为企业银行账户余额或完整现金流预测。

## 6. 人工确认接口

Agent 只输出建议。前端用户确认后，MVP 记录演示决策，不调用真实 ERP 或修改库存、采购数据。

POST /api/v1/agent-runs/{run_id}/decisions

请求：

~~~json
{
  "item_id": "ITEM-001",
  "recommendation_id": "REC-001",
  "decision": "approve",
  "note": "演示确认"
}
~~~

decision 允许 approve 或 reject。

响应：

~~~json
{
  "run_id": "run-0001",
  "item_id": "ITEM-001",
  "recommendation_id": "REC-001",
  "decision": "approve",
  "decision_status": "recorded",
  "execution_mode": "simulation"
}
~~~

不执行真实业务动作时，前端必须将按钮和结果标为模拟确认。

## 7. 状态与错误处理

### 7.1 Agent 运行状态

| status | 前端处理 |
|---|---|
| succeeded | 展示完整结果 |
| partial | 展示已有结果和告警 |
| no_data | 展示空状态及数据范围 |
| needs_input | 展示需要补充或确认的字段 |
| awaiting_confirmation | 只展示会话与待确认情景卡；不展示结果指标 |
| failed | 展示错误信息和重试入口 |

### 7.2 错误对象

~~~json
{
  "code": "AI_TIMEOUT",
  "message": "AI 分析超时，请重试。",
  "retryable": true,
  "field_errors": []
}
~~~

建议错误码：

| code | 含义 | retryable |
|---|---|---:|
| INVALID_REQUEST | 请求格式或参数非法 | false |
| MISSING_REQUIRED_DATA | 缺少必需业务数据 | false |
| DATA_VERSION_NOT_FOUND | 数据版本不存在 | false |
| POLICY_NOT_FOUND | 适用的经营规则缺失 | false |
| INVENTORY_CONFLICT | 输入数据存在库存冲突 | false |
| AI_UNAVAILABLE | 模型服务暂不可用 | true |
| AI_TIMEOUT | 模型调用超时 | true |
| MODEL_OUTPUT_INVALID | 模型输出不符合 JSON Schema | true |
| INTERNAL_ERROR | 未预期后端错误 | true |

HTTP 约定：

- 200：Agent 已执行，具体业务状态看响应体 status。
- 400：JSON 无法解析或缺少公共必需字段。
- 404：运行 ID、数据集或路由不存在。
- 422：参数类型或取值不合法。
- 503：模型服务暂不可用。
- 504：模型或工具调用超时。

后端对超时、429 和 5xx 可最多重试一次；输入校验错误不重试。日志中记录 request_id 和 run_id，不记录密钥。

## 8. 关键计算口径

这些公式由后端工具层计算，模型不得自行生成数值：

- 当前库存成本金额：on_hand_qty × unit_cost_fen。
- 可用库存：max(on_hand_qty - reserved_qty, 0)。
- 平均日净销量：所选销售窗口内 net_sold_qty 总和 ÷ 窗口天数。
- 销售窗口：从 as_of 往前数 sales_window_days 个营业日，包含 as_of 当日。
- 库存覆盖天数：available_qty ÷ 平均日净销量。平均日净销量为 0 时返回 null，并加 NO_RECENT_SALES 告警。
- 目标库存数量：max(min_display_qty, 平均日净销量 × target_cover_days)。MVP 未提供其中任一必需规则时，不计算超额库存数量。
- 超额库存数量：max(available_qty - target_stock_qty, 0)；缺少适用目标库存规则时不计算。
- 超额库存成本金额：excess_qty × unit_cost_fen。
- 近效期风险金额：预计无法在到期前售出的风险数量 × 批次单位成本；如 MVP 暂未实现销量分配，可先返回批次剩余成本作为“风险敞口估算”，并在 assumptions 中注明，不得称为确定损失。
- 同门店同 SKU 存在多个批次时，按先到期先出（FEFO）分配预计销量，避免对每个批次重复使用同一段销量预测。
- 降价建议不得低于适用规则中的 markdown_floor_price_fen；缺少该规则时，Agent 只能建议人工复核，不输出具体促销价格。
- 预计避免采购承诺金额：建议减少的可取消/未下单采购数量 × 单位成本；必须标注估算周期和假设，不等同银行余额变化。

## 9. MVP 联调验收清单

- [ ] 五种 agent_type 均使用统一请求和响应外壳。
- [ ] 朱生成的 snack-demo-v1 数据符合第 3 节字段定义，品牌、门店和商品均为合成演示数据。
- [ ] 每种 Agent 至少有一个固定场景和预期结果。
- [ ] 相同数据版本和参数可重复得到相同的工具计算结果。
- [ ] 每个结果项至少提供一条可核验的 evidence。
- [ ] 无销售、缺成本、缺规则、库存不足和模型超时都有明确状态或告警。
- [ ] AI 输出经过结构校验；结构错误不会展示为成功结果。
- [ ] 前端能展示加载中、步骤、结果、空状态、告警和失败重试。
- [ ] 确认按钮只记录 simulation 决策，不修改业务数据。
- [ ] README 说明数据为合成演示数据，并列出模型/API 调用方式。

## 10. 建议联调顺序

1. 先用 slow_moving 跑通一个端到端样例。
2. 朱按统一响应完成结果卡片、证据区域、状态和错误页面。
3. 魏将同一接口扩展到另外四种 Agent。
4. 对五种 Agent 使用固定数据和期望结果做接口验收。
5. 接入真实模型调用后，再验证模型失败、超时和 JSON 校验失败。

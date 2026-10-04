# 货不压钱｜并行开发公共契约

**状态：`integration_wired`（路由已注册，S01 本地主线已联调）**

**契约版本：`hackathon.v1`** · **发布：2026-10-04**

**前端状态：**任务 5、6 的方案决策与执行跟进模块已因功能重合从主应用及源码中移除。本文第 12 节仅保留原 API 适配器和组件挂载契约作为历史记录；后端接口仍然保留。

**数据时钟：2026-10-03 09:30（Asia/Shanghai，来自 `retail-v2.1` manifest）**

本文记录任务 1—6 开发时的数据形状、服务边界、事务约束和前端挂载方式。`/api/v1/hackathon/*` 已由 [`backend/hackathon_routes.py`](../backend/hackathon_routes.py) 注册到现有 FastAPI 应用；“已注册”只说明路由与服务图接通，不代表模型供应商已配置或业务数据自动接入。代码中可直接导入的 Python 类型和共享 SQLite 事务入口在 [`backend/hackathon_shared.py`](../backend/hackathon_shared.py) 与 [`backend/store.py`](../backend/store.py)。

本文 JSON 请求块是按契约字段编写的请求模板；JSON 响应块均带 `"fixture_only": true`，属于**开发 fixture**，只用于制作组件和服务夹具。将响应 fixture 复制到开发预览时，必须显式启用 fixture 模式并显示“开发预览”；不能把 fixture 放进生产响应、Agent 输入或真实 API 请求，也不能在 HTTP 失败后用 fixture 代答。所有金额示例均为人民币元；未知值必须为 `null`，不等于 0。

## 1. 现有实现与集成边界

截至发布时，仓库实际存在以下接口与能力：

- FastAPI 应用版本为 1.4.0，路径前缀为 `/api/v1`。已有风险、核查反馈、三个工作台计算、方案提交／审批／生成任务、手工执行状态、现金规划和旧 retail 演示接口；具体路径与字段以现有 [`API_CONTRACT.md`](../API_CONTRACT.md) 及运行中的 `/openapi.json` 为准。
- `backend/domain.py` 有确定性调拨、近效期处置、采购刹车、风险金额去重和现金规划函数。`backend/store.py` 是现有 SQLite 真相源，保存旧风险、事实反馈版本、方案版本、审批、任务、预留、现金事件、案例及库存导入快照。
- 当前 `/feedback` 仍产生 `manual_required` 草稿；`backend/model_config.py` 只读取 DeepSeek／千问／MiniMax 配置，没有真实模型运行编排和材料提取服务。
- 应用启动时在唯一 `Store` 上注册数据、AI、执行迁移并安装完整服务图；计算服务无迁移。演示模式把所有可用场景／分支导入独立租户 `hackathon-demo`，不污染旧版零售演示队列。`INVENTORY_AGENT_MODE=real` 下不自动导入合成事实。
- `backend/api.py` 已包含新版 router；`scripts/serve_frontend.py` 仅转发明确列出的读写路径，并允许 6 MiB 请求体以承载单张不超过 5 MiB 的 PNG/JPG 与 multipart 边界。

当前 API 的执行 `status` 值保留为 `draft_pending_external_execution`、`pending_dispatch`、`in_transit`、`awaiting_receipt`、`received`、`completed`、`exception`。现有确认／生成任务仍是两个旧端点；并行组件一律调用本契约的单次 `confirmProposal` 操作。D07 提议的三态展示并未作为持久化/API 枚举定稿：原状态、数量、异常和取消原因必须完整保留，三态只可作为可逆的展示映射。

## 2. 数据包核对与事实隔离

当前目录包含 `sample-data/retail-v2/xlsx/` 七个 XLSX；发布时根据 `manifest.json` 核对版本 `retail-v2.1`、种子 `20261003`、决策时点、每个文件的 SHA-256、字节数、工作表名及行数。完整门店为 6 家、名录为 50 家、商品为 12 个；只有 6 家门店具备完整经营事实。不能将其余 44 家按 0 补数或显示成已接入。

| 文件 | manifest 角色 | 行数要点 | 允许用途 |
|---|---|---:|---|
| `01_主数据与规则.xlsx` | `facts_or_assumptions` | 门店 50、商品 12、供应商 3、人员 5、门店商品 72、规则 2 | 主数据、规则和 ID 关联 |
| `02_库存与90天经营事实.xlsx` | `facts_or_assumptions` | 库存 74、批次 74、日销售 6,480、可售状态 6,480、变动 7,362、历史采购 936 | 截至决策时点已知的事实 |
| `03_需求路线采购与条款.xlsx` | `facts_or_assumptions` | 日需求 2,160、路线 30、收货日历 180，并含已确认采购、在途、账户、应付、退供条款、促销、组合及假设 | 已知事实和显式标注的假设，不能把预测当实际销售 |
| `04_场景输入与原始材料.xlsx` | `isolated_scenarios` | 场景 10、独立风险输入 7、覆盖 12、场景批次 3、材料 8、采购意向 2、抵款应付 1 | 按选定场景及分支隔离装载；标题、分支说明和验收线索不进入模型事实查询 |
| `05_未来执行与结算回放.xlsx` | `future_replay` | 任务 7、业务回执 24、渠道动作 6、批次销售 57、现金流水 56、核销 59、退供确认 3 | 仅由执行服务在回放时钟到达且批准版本匹配时读取 |
| `06_验收预期结果.xlsx` | `expected_answers` | 风险 7、进度 3、金额公式 16 | 仅开发验收；永不注册为 Agent 工具或事实查询源 |
| `07_当前库存导入.xlsx` | `current_import_projection` | 库存投影 72 | 仅兼容旧库存导入；与 02 同包加载时不得重复导入 |

事实可见条件同时满足：`known_at <= context.as_of`、记录属于当前 `tenant_id + scenario_id + branch_id`、快照和事实版本匹配。日期范围采用 ISO `YYYY-MM-DD`；时点用带时区 ISO 8601。`occurred_at` 与 `known_at` 不可互换。未来预测可以提前可见但必须保留 `source=forecast/assumption`；未来签收、销售和收款事件不得提前可见。

独立场景不能拼接 BASE 数据补空：S02/S10 风险输入是该风险读模型的独立输入；S05 的退款／换货／抵款是互斥分支；S07 是独立采购起点；S08 的“闭店”覆盖只在反馈确认后可见。S01 初始分支为 `transfer_80`，S09 为 `partial_transfer`。多批次按 `lot_id` 分开；在途快照与同一 `shipment_line_id` 的订单描述不得重复计库存。

## 3. 通用字段、版本与错误

- 新业务主键均用稳定字符串：`scenario_id`、`branch_id`、`store_id`、`sku_id`、`lot_id`、`proposal_id`、`task_id`、`event_id`、`material_id`、`run_id`。沿用旧 `/risks/{risk_id}` 的正整数 `risk_id`，不更改旧接口类型。
- 新数据的 `risk_id` 映射由模块 1 数据层维护，至少以 `(tenant_id, legacy_snapshot_id, risk_id)` 为键，映射到新场景风险键及 `store_id/sku_id/lot_id`。仅在有明确记录关联时写映射；不能按名称、数组顺序或数字相同猜映射。无唯一关联时保持 `risk_id=null`，新接口直接用字符串业务 ID。
- 模块 1 对外提供 `FactService.resolve_legacy_risk_id(context, risk_key)`。它可绑定已有、确有相同事实来源的旧数字 ID；新事实没有旧行时，可在导入阶段创建只供旧 FK 兼容的数字映射。该整数不是新业务主键，计算始终使用 `risk_key`。保存进现有方案表前必须能解析主风险的旧 FK；解析不到时返回 `missing_business_data`，不得猜 ID 或由模块 4 私自插入第二份风险事实。
- 数量必须与 `base_unit` 一同返回，且现货、在途、冻结、预留分列。金额以 CNY 元计、最多两位小数；百分比为 0—100；未观测到的量、成本、效期、现金及日期用 `null`。已知零才是 `0`。
- 每个写入请求带 `tenant_id`（实际 HTTP 使用 `X-Tenant-Id`）、`actor_id`、操作对应的 `expected_*_version` 和 `Idempotency-Key`。身份认证角色不在本轮新增；租户和操作者字段不能被描述成已验证身份。
- 所有新成功响应使用 `contract_version: "hackathon.v1"`，并携带上下文或业务 ID；旧 `/api/v1` 响应保持现状。冲突不自动重试写操作。
- 新接口沿用 FastAPI 常见响应：参数错误 `422`，不存在／无权访问 `404`，业务／版本／幂等冲突 `409`，模型不可用 `503`。冲突样例：

```json
{
  "detail": {
    "code": "version_conflict",
    "message": "事实版本已变化，请重新读取并确认",
    "current_version": 4
  }
}
```

```json
{
  "detail": {
    "code": "missing_business_data",
    "message": "当前场景缺少可用的供应商条款",
    "missing_fields": ["return_terms.confirmed_at"]
  }
}
```

未知不是错误时用 `missing_fields` 和 `null` 表示；不能把无法计算的响应改成 HTTP 200 “成功”且填入 fixture 数值。

## 4. 后端模块 1—4 的服务与注入协议

公共类型在 `backend.hackathon_shared`：`FactContext`、`FactQuery`、`FactQueryResult`、`RiskAssessment`、`ProposalComparison`、`ExtractionDraft`、`AgentRun`、`BusinessEvent`、`ApprovalTaskResult`、`ReplayResult`，以及 `FactService`、`CalculationService`、`AgentService`、`ExecutionService`、`TransactionProvider` 等 `Protocol`。这些类型不导入业务模块，避免相互循环导入。

```python
from backend.hackathon_shared import HackathonServices, install_services

services = HackathonServices(
    database=store,       # 唯一 backend.store.Store
    facts=facts_service,  # 模块 1
    calculations=calc,    # 模块 2
    agent=agent_service,  # 模块 3
    execution=execution,  # 模块 4
)
install_services(app, services)
```

实际实现应遵守以下最小调用协议（参数及返回 DTO 定义以同文件 Protocol 为准）：

| 模块 | 协议 | 责任 |
|---|---|---|
| 1 数据与风险 | `FactService.query(FactQuery) -> FactQueryResult`；`assess_risks(FactQuery) -> RiskAssessment`；`apply_business_events(tx, events, expected_fact_version)` | 唯一事实查询、逐批次风险规则、场景隔离、来源／缺项、ID 映射及受控事实写入；不把 05/06 暴露给 Agent |
| 2 业务计算 | `CalculationService.compare(facts, request) -> ProposalComparison` | 确定性、可复算、无模型／无数据库的处置候选与现金比较；复用 `backend/domain.py` 有效函数，不在计算层另读 XLSX |
| 3 AI 与材料 | `AgentService.run(request)`、`get_run(run_id, tenant_id, after_sequence)`、`extract_material(request)`、`confirm_material(draft_id, request, expected_fact_version)` | 模型理解、受控工具编排、运行事件、提取草稿及确认；不直接执行 SQL 或改库存；隐藏思维链、密钥和图片原文不得进普通日志 |
| 4 执行与资金 | `save_proposal(request)`、`confirm_and_schedule(request)`、`record_channel_action(request)`、`record_business_events(request)`、`advance_replay(request)`、`get_accounting(request)` | 保存可重算的候选草稿；一次确认建任务；本地渠道动作、业务回执／回放、现金事件与核销及结果聚合；由模块 1 的事实写接口更新库存 |

模块 4 依赖注入模块 1 的 `FactService`，调用模块 1 时只传当前活动事务 `tx`，不反向导入其具体实现。模块 3 通过 `FactService` 与 `CalculationService` 的协议注册工具；工具名、参数校验和响应都受限。不得让模型生成 SQL、库存变更或虚构工具完成状态。

## 5. 单一数据库、迁移与事务边界

**连接、锁与外层提交的唯一所有者是 `backend.store.Store`。** 第一阶段已提供 `Store.transaction()`，持有同一把 `RLock`，最外层使用 SQLite `BEGIN IMMEDIATE`；正常退出时提交，异常退出时回滚。内部 Store 方法在该上下文中作为嵌套调用，不提交外层事务。模块代码不得自行 `sqlite3.connect`、创建余额库、跨事务拆分同一动作，或在接收的 `tx` 上调用 `commit/rollback`。

一项业务事件必须能在一个 `with services.database.transaction() as tx:` 中同时写入：幂等／回放去重标记、任务进度、模块 1 库存业务事件、现金流水／核销分配和审计记录。任一校验或写入失败，整项回滚。任务确认和预留、批准版本也必须同事务写入。现金流水唯一事实在此同一 Store 内，模块不得建立第二套余额表；“核销分配”只链接既有现金流水，不得重复增加账户余额。

表和迁移归属：

| 所有者 | 数据库对象及约束 |
|---|---|
| `backend.store.Store`（公共） | 现有快照、旧风险／反馈、方案／版本、审批、任务、库存预留、现金事件、案例和导入表；它也是连接、锁和迁移入口唯一所有者 |
| 模块 1 `backend/hackathon_data/` | 新场景事实、manifest 导入批次、稳定 ID 映射、来源／版本、风险结果及写入业务事件的事实表。不得复制旧方案、任务、余额或 cash event 真相 |
| 模块 2 `backend/hackathon_calculations/` | 不拥有表；纯计算模块 |
| 模块 3 `backend/hackathon_ai/` | 材料原件引用、提取草稿／确认历史、Agent Run 及事件／用量表；不保存第二份业务事实 |
| 模块 4 `backend/hackathon_execution/` | 渠道动作、执行事件去重、回放进度、核销分配及计算结果引用；旧任务／方案／现金事件仍由公共 Store 提供，不复制账户余额 |

当前启动顺序为：① `Store` 建立现有公共 `SCHEMA`；② 在同一连接上依次注册模块 1 数据迁移、模块 3 AI 迁移、模块 4 执行迁移（模块 2 无迁移）；③ 安装完整服务实例；④ 演示模式下以租户 `hackathon-demo` 加载场景事实。迁移由各模块提供、自身拥有；不新建第二个数据库连接，不删改已有真实快照。

样例数据加载顺序：校验 manifest 与所有 XLSX 校验和 → 01 主数据与规则 → 02 当前库存／批次／历史 → 03 需求、线路、采购、收款与条款 → 单独建立所选 04 场景快照及经确认的覆盖 → 仅执行服务保留并在时钟推进时揭示 05 → 06 仅在独立验收读取器中加载。07 只作为 02 的兼容投影，不能同库重复入账。失败导入整体回滚，不覆盖用户已有真实库存库。

## 6. 事实查询请求与响应

`FactContext` 必填：`tenant_id`、`scenario_id`、`branch_id`（BASE 可 `null`）、`snapshot_id`、`as_of`、`data_version`、`fact_version`、`is_demo`、`source_refs[]`、`missing_fields[]`。事实查询必须提供完整 context；selector 可为空数组表示该范围内全部，`include[]` 只接受注册过的事实类目。

**POST `/api/v1/hackathon/facts/query`（已注册）**

```json
{
  "context": {
    "tenant_id": "demo",
    "scenario_id": "S01",
    "branch_id": "transfer_80",
    "snapshot_id": "SNAP-20261003-BASE",
    "as_of": "2026-10-03T09:30:00+08:00",
    "data_version": "retail-v2.1",
    "fact_version": 1,
    "is_demo": true,
    "source_refs": [],
    "missing_fields": []
  },
  "store_ids": ["ST-001", "ST-002"],
  "sku_ids": ["SKU-001"],
  "lot_ids": ["LOT-001-001"],
  "include": ["inventory", "sales_history", "availability_history", "demand_forecasts", "procurement", "routes", "policies"],
  "history_start": "2026-09-03",
  "history_end": "2026-10-02"
}
```

```json
{
  "fixture_only": true,
  "contract_version": "hackathon.v1",
  "query_id": "Q-FIXTURE-001",
  "context": {
    "tenant_id": "demo", "scenario_id": "S01", "branch_id": "transfer_80",
    "snapshot_id": "SNAP-20261003-BASE", "as_of": "2026-10-03T09:30:00+08:00",
    "data_version": "retail-v2.1", "fact_version": 1, "is_demo": true,
    "source_refs": [{"source": "02_库存与90天经营事实.xlsx", "record_id": "INV-001", "known_at": "2026-10-03T00:00:00+08:00", "is_demo": true}],
    "missing_fields": []
  },
  "inventory": [{
    "store_id": "ST-001", "sku_id": "SKU-001", "lot_id": "LOT-001-001",
    "stock_state": "on_hand", "quantity": 120, "base_unit": "盒",
    "unit_cost_cny": 80, "blocked_qty": 0, "reserved_qty": 0,
    "sellable_until": "2026-12-15",
    "source_ref": {"source": "02_库存与90天经营事实.xlsx", "record_id": "INV-001", "known_at": "2026-10-03T00:00:00+08:00", "is_demo": true}
  }],
  "sales_history": [{"date": "2026-10-02", "store_id": "ST-001", "sku_id": "SKU-001", "lot_id": "LOT-001-001", "sold_qty": 1, "base_unit": "盒", "sales_amount_cny": 100, "known_at": "2026-10-03T00:00:00+08:00", "source": "02_库存与90天经营事实.xlsx"}],
  "availability_history": [], "demand_forecasts": [], "procurement": [], "routes": [], "policies": [],
  "payables": [], "missing_fields": [], "warnings": []
}
```

返回完整的来源与版本；实际响应按 selectors 过滤，不必返回无关历史。历史、在途、假设分别放字段／类目，不因同一单据出现多次而重复累计。

## 7. 风险与方案候选协议

风险由模块 1 基于当前 facts 与规则产生；慢销、临期分别逐批次返回 `risk / normal / insufficient_data`。允许同一库存行同时出现两类风险，但 `attention_inventory_cost_cny` 依据 `counted_inventory_keys` 去重。风险字段必填 `risk_key/store_id/sku_id/lot_id/risk_type/result/base_unit/evidence_refs/missing_fields/rule_version`；`risk_id` 仅在可靠映射存在时为整数，否则 `null`。缺少销量时覆盖天数为 `null`；缺少效期时临期状态为 `insufficient_data`，不可填 0 天。

**POST `/api/v1/hackathon/risks/assess`（已注册）**输入与事实查询相同，由模块 1 的 `FactService.assess_risks` 返回 `RiskAssessment`。`calculation_version` 标识规则实现；每条风险另含其 `rule_version`。下例显示风险重叠及缺销量场景的字段边界：

```json
{
  "fixture_only": true,
  "contract_version": "hackathon.v1",
  "calculation_version": "risk-v1",
  "context": {"tenant_id": "demo", "scenario_id": "S02", "branch_id": "overlap", "snapshot_id": "SNAP-20261003-BASE", "as_of": "2026-10-03T09:30:00+08:00", "data_version": "retail-v2.1", "fact_version": 1, "is_demo": true, "source_refs": [], "missing_fields": []},
  "items": [
    {"risk_key": "S02:ST-001:SKU-001:SCLOT-S02:slow_moving", "risk_id": null, "store_id": "ST-001", "sku_id": "SKU-001", "lot_id": "SCLOT-S02", "risk_type": "slow_moving", "result": "risk", "quantity": 100, "base_unit": "盒", "amount_cny": 8000, "coverage_days": 100, "remaining_sellable_days": 10, "evidence_refs": [], "missing_fields": [], "rule_version": "POL-001"},
    {"risk_key": "S02:ST-001:SKU-001:SCLOT-S02:near_expiry", "risk_id": null, "store_id": "ST-001", "sku_id": "SKU-001", "lot_id": "SCLOT-S02", "risk_type": "near_expiry", "result": "risk", "quantity": 100, "base_unit": "盒", "amount_cny": 8000, "coverage_days": 100, "remaining_sellable_days": 10, "evidence_refs": [], "missing_fields": [], "rule_version": "POL-001"}
  ],
  "attention_inventory_cost_cny": 8000,
  "counted_inventory_keys": ["SNAP-20261003-BASE:ST-001:SKU-001:SCLOT-S02"],
  "missing_fields": []
}
```

S10 缺项属于不同快照／分支，不能混进 S02 响应。单独查询 S10 的 `missing_sales` 时，示例行应为：

```json
{
  "fixture_only": true,
  "contract_version": "hackathon.v1",
  "calculation_version": "risk-v1",
  "context": {"tenant_id": "demo", "scenario_id": "S10", "branch_id": "missing_sales", "snapshot_id": "SNAP-20261003-BASE", "as_of": "2026-10-03T09:30:00+08:00", "data_version": "retail-v2.1", "fact_version": 1, "is_demo": true, "source_refs": [], "missing_fields": ["sales_30", "valid_observed_days"]},
  "items": [{"risk_key": "S10:ST-004:SKU-004:SCLOT-S10:slow_moving", "risk_id": null, "store_id": "ST-004", "sku_id": "SKU-004", "lot_id": "SCLOT-S10", "risk_type": "slow_moving", "result": "insufficient_data", "quantity": 60, "base_unit": "袋", "amount_cny": 300, "coverage_days": null, "remaining_sellable_days": 120, "evidence_refs": [], "missing_fields": ["sales_30", "valid_observed_days"], "rule_version": "POL-001"}],
  "attention_inventory_cost_cny": null,
  "counted_inventory_keys": [],
  "missing_fields": ["sales_30", "valid_observed_days"]
}
```

四种处置及适用组合均在相同 `context + horizon + baseline_id` 下比较。候选必含 `candidate_id/action_type/feasible/exclusion_reasons/store_id/target_store_id/sku_id/lot_id/quantity/base_unit/calculation/assumptions/missing_fields/inventory_changes`。`action_type` 为 `keep/transfer/promotion/return/procurement`。计算至少报告计划量、预计售出／剩余、执行费用、毛利、预计和已知现金效果及日期；未知项为 `null`，预计流入不可并入已到账。组合候选共享库存、线路和费用占用，不得重复处置或重复记同一运费。比较响应始终包含 `candidate_groups[]` 和 `fact_notices[]`；没有组合时 `candidate_groups` 为空数组，`fact_notices` 列明事实查询层面的提示。

候选 `calculation` 必含 `planned_qty/expected_sold_qty/ending_qty/execution_cost_cny/gross_profit_cny/expected_cash_in_cny/actual_cash_in_cny/cash_flow[]/calculation_version`；各数量带 `base_unit`，现金行带 `direction/amount_cny/expected_at/status/source_ref`。实际值尚无凭据时为 `null`。比较响应另含 `calculation_version` 与 `policy_version`，每个候选的 `assumptions[]` 和 `missing_fields[]` 不可省略。`comparison_id` 和 `candidate_id` 是输入、上下文与计算版本的稳定内容 ID：同一 facts／请求的重复计算可复现 ID；事实、政策、假设或结果改变则 ID 改变。它们不是方案号，也不能代替写操作版本检查。

调拨和其他会改变库存位置的候选还必须返回 `inventory_changes[]`。每行按门店、商品、批次列出服务计算的 `quantity_before/quantity_after/quantity_delta/base_unit/source_ref`；`quantity_before` 与 `quantity_after` 描述执行该动作前后的即时库存，不代表预测周期末库存。前端不得自行用调拨量对库存加减；未知数量保留 `null`。没有位置变化的动作返回空数组。

**POST `/api/v1/hackathon/proposals/compare`（已注册）**请求：

```json
{
  "context": {"tenant_id": "demo", "scenario_id": "S01", "branch_id": "transfer_80", "snapshot_id": "SNAP-20261003-BASE", "as_of": "2026-10-03T09:30:00+08:00", "data_version": "retail-v2.1", "fact_version": 1, "is_demo": true, "source_refs": [], "missing_fields": []},
  "risk_keys": ["S01:ST-001:SKU-001:LOT-001-001:slow_moving"],
  "objective": "在10月25日前降低同批库存占用并评估回款",
  "horizon_start": "2026-10-03",
  "horizon_end": "2026-10-25",
  "assumption_ids": [],
  "business_inputs": {
    "transfer": {
      "origin_store_id": "ST-001", "target_store_id": "ST-002",
      "sku_id": "SKU-001", "lot_id": "LOT-001-001",
      "quantity": 80, "base_unit": "盒", "route_id": "ROUTE-ST001-ST002",
      "route_fee_cny": 24
    }
  }
}
```

`business_inputs` 是可选的动作级输入，只传用户当前确认或明确调整的值；服务仍须重新读取事实、校验约束并计算，不信任前端提交的金额或库存结果。未提供的动作输入由服务按已知事实处理，缺少必要事实时返回 `missing_fields`。允许的子结构如下：

| key | 输入字段 | 约束 |
|---|---|---|
| `transfer` | `origin_store_id`、`target_store_id`、`sku_id`、`lot_id`、`quantity`、`base_unit`、`route_id`、`route_fee_cny`、`eta_days`、`sales_settlement_days` | 数量和单位必须匹配同一事实；路线费用是报价／用户输入，服务需验证来源并决定是否可行，不是前端计算的执行结果。 |
| `promotion` | `promotion_id`、`products[] {sku_id, quantity_per_bundle, base_unit}`、`price_stages[] {stage_id?, label?, price_cny, start_date?, end_date_exclusive?}`、`quantity`、`sku_id`、`store_id`、`lot_id`、`base_unit`、`sales_settlement_days` | 每阶段日期为半开区间；阶段需唯一匹配当前事实中的 `stage_id`；价格、组合及底价约束由服务校验并重算。 |
| `return` | `supplier_id`、`sku_id`、`lot_id`、`quantity`、`base_unit`、`settlement_method`、`fee_cny`、`store_id`、`return_terms` | `settlement_method` 为 `refund/exchange/offset`；`return_terms` 仅表达待核对条件，用户输入不等于供应商接受或实际结算。 |
| `procurement` | `supplier_id`、`purchase_order_id`、`intent_id`、`sku_id`、`store_id`、`quantity`、`base_unit`、`unit_cost_cny`、`expected_arrival_date`、`payment_date`、`recommended_quantity`、`new_payment_date` | 未确认订单仍是意向；通过 `intent_id` 选择已知意向，服务结合现货、预留、在途、观察期和付款事实重算。 |

省略的字段与 `null` 含义不同：省略表示本次没有提供该输入；`null` 表示明确保留未知。数量必须带 `base_unit`。前端只能展示服务返回的可行性、库存变化和金额。

```json
{
  "fixture_only": true,
  "contract_version": "hackathon.v1",
  "calculation_version": "comparison-v1",
  "policy_version": "retail-v2.1",
  "comparison_id": "CMP-FIXTURE-001",
  "context": {"tenant_id": "demo", "scenario_id": "S01", "branch_id": "transfer_80", "snapshot_id": "SNAP-20261003-BASE", "as_of": "2026-10-03T09:30:00+08:00", "data_version": "retail-v2.1", "fact_version": 1, "is_demo": true, "source_refs": [], "missing_fields": []},
  "objective": "在10月25日前降低同批库存占用并评估回款",
  "horizon_start": "2026-10-03", "horizon_end": "2026-10-25", "baseline_id": "S01:SNAP-20261003-BASE:2026-10-25",
  "candidates": [
    {"candidate_id": "CAND-FIXTURE-KEEP", "action_type": "keep", "feasible": true, "exclusion_reasons": [], "store_id": "ST-001", "target_store_id": null, "sku_id": "SKU-001", "lot_id": "LOT-001-001", "quantity": 120, "base_unit": "盒", "calculation": {"planned_qty": 120, "expected_sold_qty": 40, "ending_qty": 80, "execution_cost_cny": 0, "gross_profit_cny": 800, "expected_cash_in_cny": 4000, "actual_cash_in_cny": null, "cash_flow": [{"direction": "in", "amount_cny": 4000, "expected_at": "2026-10-25", "status": "forecast", "source_ref": "scenario-demand-base"}], "calculation_version": "comparison-v1"}, "assumptions": ["scenario-demand-base"], "missing_fields": []},
    {"candidate_id": "CAND-FIXTURE-TRANSFER", "action_type": "transfer", "feasible": true, "exclusion_reasons": [], "store_id": "ST-001", "target_store_id": "ST-002", "sku_id": "SKU-001", "lot_id": "LOT-001-001", "quantity": 80, "base_unit": "盒", "calculation": {"planned_qty": 80, "expected_sold_qty": 64, "ending_qty": 16, "execution_cost_cny": 24, "gross_profit_cny": 1280, "expected_cash_in_cny": 6400, "actual_cash_in_cny": null, "cash_flow": [{"direction": "in", "amount_cny": 6400, "expected_at": "2026-10-25", "status": "forecast", "source_ref": "S01 demand range"}], "calculation_version": "comparison-v1"}, "inventory_changes": [{"store_id": "ST-001", "sku_id": "SKU-001", "lot_id": "LOT-001-001", "quantity_before": 120, "quantity_after": 40, "quantity_delta": -80, "base_unit": "盒", "source_ref": "02_库存与90天经营事实.xlsx#INV-001"}, {"store_id": "ST-002", "sku_id": "SKU-001", "lot_id": "LOT-001-001", "quantity_before": 10, "quantity_after": 90, "quantity_delta": 80, "base_unit": "盒", "source_ref": "02_库存与90天经营事实.xlsx#INV-002"}], "assumptions": ["S01 demand range"], "missing_fields": []},
    {"candidate_id": "CAND-FIXTURE-RETURN", "action_type": "return", "feasible": false, "exclusion_reasons": ["本场景未提供已确认退供条款"], "store_id": "ST-001", "target_store_id": null, "sku_id": "SKU-001", "lot_id": "LOT-001-001", "quantity": null, "base_unit": "盒", "calculation": {"planned_qty": null, "expected_sold_qty": null, "ending_qty": null, "execution_cost_cny": null, "gross_profit_cny": null, "expected_cash_in_cny": null, "actual_cash_in_cny": null, "cash_flow": [], "calculation_version": "comparison-v1"}, "assumptions": [], "missing_fields": ["return_terms.confirmed_at"]}
  ],
  "selected_candidate_id": null
}
```

该 fixture 仅展示字段，不预设线上计算值。服务必须由本次查询和输入计算；改数量、需求、价格、运费、效期或库存会产生新 `comparison_id` 和结果版本。

### 待确认方案列表

**GET `/api/v1/hackathon/proposals?scenario_id=...&branch_id=...&status=pending_approval`（已注册）**返回当前上下文中的方案记录，不把待审批草稿与已批准执行任务混在一起。列表响应为 `{contract_version, proposals[], metadata}`；每行至少含 `proposal_id/proposal_version/status/context/candidate_id/action_type/title/risk_keys/action_lines/created_at/updated_at/missing_fields`。筛选 `status=pending_approval` 时仅返回待确认项；空列表返回 `proposals: []`。可选 `proposal_id/proposal_version` 用于限定当前方案版本；快照、时点、数据版本或事实版本与当前上下文不一致时返回 409。金额和数量来自保存时经服务端校验的候选快照，列表读取不重算。

### 任务与案例读取

**GET `/api/v1/hackathon/tasks?scenario_id=...&branch_id=...`（已注册）**通过 `ExecutionService.list_tasks` 返回保存的执行任务，支持 `status/task_id/task_version/proposal_id/proposal_version` 过滤；空列表明确返回 `tasks: []`。**GET `/tasks/{task_id}`**返回限定到单任务的任务、核算、渠道和时间线，可带任务／方案版本查询参数。**GET `/cases/{case_id}`**中的 `case_id` 与稳定 `proposal_id` 相同；返回已保存的方案版本、确认历史、任务、回执时间线及该方案范围的核算。草稿也可读取案例，但不生成空任务或核算记录。上述读操作只读公共账表，不调用计算或模型；历史方案金额保留保存值，事实版本变化由 `requires_recalculation` 标出。

### 经营总览汇总

**GET `/api/v1/hackathon/overview?scenario_id=...&branch_id=...&snapshot_id=...&as_of=...`（已注册）**以当前同一业务快照返回首页四张指标卡和门店库存资金表。账户余额、库存／风险成本、30 日已确认采购承诺由 `RetailFactService.get_overview` 统一计算；执行服务只增加待确认方案成本、`task_links[]` 与各门店待办链接，路由不重复汇总经营事实。响应中 `metadata` 提供 `is_demo/source/as_of_date/as_of/data_version/fact_version/source_refs/missing_fields`；未知保持 `null`。

```json
{
  "account": {"balance": null, "status": "unknown", "source": "账户快照未接入"},
  "inventory": {"cost": null, "risk_cost": null, "source": "库存快照待聚合"},
  "purchase_commitments": {"amount": null, "count": null, "horizon_days": 30, "status": "unknown", "source": "付款计划未接入"},
  "pending_approvals": {"count": 0, "amount": null, "known_amount": null, "missing_count": 0},
  "task_links": [],
  "stores": [{
    "store_id": "ST-001", "store_name": "示例门店", "inventory_cost": null,
    "risk_cost": null, "turnover_days": null, "primary_risk": null, "risk_types": [],
    "work_item_id": null, "work_item_label": null, "pending_label": "未知",
    "missing_fields": ["inventory_cost", "risk_cost"]
  }]
}
```

`account.balance` 是可用资金；`inventory.cost` 是库存成本占用；`inventory.risk_cost` 是待关注库存成本；`purchase_commitments.amount` 只统计快照日后 30 天内已确认的付款计划。未知金额为 `null`，不得跨字段推算。待审批 `amount` 只在所有相关方案均有可用数量和成本时给出；否则给 `null` 并以 `known_amount/missing_count` 报告已知部分和缺项。门店表的 `turnover_days`、风险和待办链接均按服务返回值显示；缺项保留未知。该汇总使用与方案、任务列表相同的 tenant、场景和快照隔离边界。

### 持久化选定候选

**POST `/api/v1/hackathon/proposals`（已注册）**把一次比较里的所选候选保存为现有公共 proposal/version 草稿，方便刷新后继续。它不审批、不生成任务，也不发渠道动作。服务端根据 `context + risk_keys + objective + horizon + assumption_ids` 重新读取事实并重新比较；只有重算出的 `comparison_id/candidate_id` 与请求一致时才保存，不能信任浏览器提交的金额或数量。`expected_current_proposal_version=0` 表示为该场景风险新建 proposal；大于 0 表示基于当前草稿版本更新，陈旧版本返回 409。此步骤同样需要模块 1 可解析的主风险兼容 ID；proposal 的真实关联仍保存字符串 `risk_key`、场景、批次及版本快照。

```json
{
  "context": {"tenant_id": "demo", "scenario_id": "S01", "branch_id": "transfer_80", "snapshot_id": "SNAP-20261003-BASE", "as_of": "2026-10-03T09:30:00+08:00", "data_version": "retail-v2.1", "fact_version": 1, "is_demo": true, "source_refs": [], "missing_fields": []},
  "risk_keys": ["S01:ST-001:SKU-001:LOT-001-001:slow_moving"],
  "comparison_id": "CMP-FIXTURE-001",
  "candidate_id": "CAND-FIXTURE-TRANSFER",
  "objective": "在10月25日前降低同批库存占用并评估回款",
  "horizon_start": "2026-10-03", "horizon_end": "2026-10-25",
  "assumption_ids": ["scenario-demand-base"],
  "expected_current_proposal_version": 0,
  "actor_id": "manager-demo"
}
```

```json
{
  "fixture_only": true,
  "contract_version": "hackathon.v1",
  "proposal_id": "PROP-FIXTURE-001", "proposal_version": 1, "status": "draft",
  "comparison_id": "CMP-FIXTURE-001", "candidate_id": "CAND-FIXTURE-TRANSFER",
  "risk_key": "S01:ST-001:SKU-001:LOT-001-001:slow_moving",
  "snapshot_id": "SNAP-20261003-BASE", "fact_version": 1,
  "data_version": "retail-v2.1", "policy_version": "POL-001", "calculation_version": "comparison-v1",
  "action_lines": [{"action_line_id": "LINE-001", "action_type": "transfer", "store_id": "ST-001", "target_store_id": "ST-002", "sku_id": "SKU-001", "lot_id": "LOT-001-001", "quantity": 80, "base_unit": "盒"}],
  "idempotent_replay": false
}
```

## 8. 材料草稿与确认

**POST `/api/v1/hackathon/materials/extract`（已注册）**接受粘贴文字 JSON，或一个清晰 PNG/JPG multipart 文件（单张，建议不超过 5 MiB）；PDF 直接解析不在范围。返回草稿，不产生订单、库存或条款事实。每个字段携带值、单位、原文证据、置信度及 `needs_review/missing/unmatched`；未知 SKU／供应商和空字段必须留空并提示人工匹配。

```json
{
  "context": {"tenant_id": "demo", "scenario_id": "S07", "branch_id": null, "snapshot_id": "SNAP-20261003-BASE", "as_of": "2026-10-03T09:30:00+08:00", "data_version": "retail-v2.1", "fact_version": 1, "is_demo": true, "source_refs": [], "missing_fields": []},
  "kind": "purchase_intent",
  "text": "庆春店拟订酸奶夹心饼干100袋，单价5元/袋，预计10月10日到货。",
  "source_name": "负责人粘贴的采购意向"
}
```

图片请求使用 multipart，`context` 字段为上述完整上下文的 JSON 字符串，`kind/source_name/text` 与图片文件分别作为普通表单字段；上传请求同样携带 `Idempotency-Key`。共享客户端负责 JSON 和 multipart 两种编码，不由组件绕过客户端自行组装请求。

```json
{
  "fixture_only": true,
  "contract_version": "hackathon.v1",
  "context": {"tenant_id": "demo", "scenario_id": "S07", "branch_id": null, "snapshot_id": "SNAP-20261003-BASE", "as_of": "2026-10-03T09:30:00+08:00", "data_version": "retail-v2.1", "fact_version": 1, "is_demo": true, "source_refs": [], "missing_fields": []},
  "draft_id": "DRAFT-FIXTURE-001",
  "material_id": "MAT-FIXTURE-001",
  "kind": "purchase_intent",
  "status": "needs_review",
  "source": "manager_text",
  "is_demo": true,
  "external_write": false,
  "fields": {
    "store_id": {"value": "ST-004", "unit": null, "evidence_text": "庆春店", "page": null, "confidence": 0.91, "review_status": "needs_review"},
    "sku_id": {"value": "SKU-004", "unit": null, "evidence_text": "酸奶夹心饼干", "page": null, "confidence": 0.94, "review_status": "needs_review"},
    "quantity": {"value": 100, "unit": "袋", "evidence_text": "100袋", "page": null, "confidence": 0.98, "review_status": "needs_review"},
    "unit_cost_cny": {"value": 5, "unit": "CNY/袋", "evidence_text": "单价5元/袋", "page": null, "confidence": 0.99, "review_status": "needs_review"},
    "expected_arrival_date": {"value": "2026-10-10", "unit": "date", "evidence_text": "10月10日到货", "page": null, "confidence": 0.87, "review_status": "needs_review"},
    "payment_date": {"value": null, "unit": "date", "evidence_text": null, "page": null, "confidence": null, "review_status": "missing"},
    "supplier_id": {"value": null, "unit": null, "evidence_text": null, "page": null, "confidence": null, "review_status": "missing"}
  },
  "missing_fields": ["payment_date", "supplier_id"],
  "unmatched_entities": [],
  "created_at": "2026-10-04T10:00:00+08:00",
  "model_run_id": "RUN-FIXTURE-001"
}
```

人工确认 **POST `/api/v1/hackathon/materials/{draft_id}/confirm`（已注册）**需要 `expected_fact_version`、操作者和经人工修改的 `fields`，并携带 `Idempotency-Key`。采购意向确认只发布采购意向事实，不表示供应商已确认订单；退供合同条款确认不表示供应商接受本次退货。响应包含 `status="confirmed"`、`fact_version`、确认字段、原始 `material_id` 与证据引用。事实版本冲突返回 409，需重新读取后确认；同确认幂等键重放原结果。模型提取失败保留材料和可编辑人工入口，不能输出 `confirmed` 草稿。

```json
{
  "draft_id": "DRAFT-FIXTURE-001",
  "expected_fact_version": 1,
  "actor_id": "manager-demo",
  "fields": {"store_id": "ST-004", "sku_id": "SKU-004", "quantity": 100, "unit": "袋", "unit_cost_cny": 5, "expected_arrival_date": "2026-10-10", "payment_date": null, "supplier_id": null},
  "accepted_unresolved_fields": ["payment_date", "supplier_id"]
}
```

```json
{
  "fixture_only": true,
  "contract_version": "hackathon.v1",
  "draft_id": "DRAFT-FIXTURE-001", "material_id": "MAT-FIXTURE-001", "status": "confirmed",
  "fact_version": 2, "confirmed_by": "manager-demo", "confirmed_at": "2026-10-04T10:03:00+08:00",
  "confirmed_fields": {"store_id": "ST-004", "sku_id": "SKU-004", "quantity": 100, "unit": "袋", "unit_cost_cny": 5, "expected_arrival_date": "2026-10-10", "payment_date": null, "supplier_id": null},
  "evidence_refs": [{"material_id": "MAT-FIXTURE-001", "field": "quantity", "quoted_text": "100件"}],
  "missing_fields": ["payment_date", "supplier_id"], "is_demo": true, "external_write": false
}
```

## 9. Agent 运行记录

**POST `/api/v1/hackathon/agent-runs`（已注册）**输入 `context`、自然语言 `goal`、可选已确认反馈引用；Agent 只能使用注册事实与计算工具。**GET `/api/v1/hackathon/agent-runs/{run_id}?after_sequence=N`（已注册）**按事件序号读取新增事件。状态仅为 `queued/running/completed/failed/unavailable/needs_input`。事件只记录真实阶段、工具名、参数摘要、结果引用、错误及可选用量，不保存或输出隐藏思维链、完整敏感图像或密钥。模型不可用用 `unavailable`，不拿旧运行或开发 fixture 伪装本次成功。

```json
{
  "context": {"tenant_id": "demo", "scenario_id": "S01", "branch_id": "transfer_80", "snapshot_id": "SNAP-20261003-BASE", "as_of": "2026-10-03T09:30:00+08:00", "data_version": "retail-v2.1", "fact_version": 1, "is_demo": true, "source_refs": [], "missing_fields": []},
  "goal": "检查同批库存，比较适用处置方式并说明依据",
  "feedback_material_ids": []
}
```

```json
{
  "fixture_only": true,
  "contract_version": "hackathon.v1",
  "run_id": "RUN-FIXTURE-001",
  "status": "completed",
  "context": {"tenant_id": "demo", "scenario_id": "S01", "branch_id": "transfer_80", "snapshot_id": "SNAP-20261003-BASE", "as_of": "2026-10-03T09:30:00+08:00", "data_version": "retail-v2.1", "fact_version": 1, "is_demo": true, "source_refs": [], "missing_fields": []},
  "summary": "已读取当前批次事实并完成适用方案计算。",
  "events": [
    {"sequence": 1, "event_id": "EV-RUN-FIXTURE-001", "event_type": "run_started", "occurred_at": "2026-10-04T10:00:00+08:00", "tool_name": null, "input_summary": null, "result_ref": null, "error": null},
    {"sequence": 2, "event_id": "EV-RUN-FIXTURE-002", "event_type": "tool_started", "occurred_at": "2026-10-04T10:00:01+08:00", "tool_name": "facts.query", "input_summary": {"scenario_id": "S01", "store_count": 2, "sku_count": 1}, "result_ref": null, "error": null},
    {"sequence": 3, "event_id": "EV-RUN-FIXTURE-003", "event_type": "tool_succeeded", "occurred_at": "2026-10-04T10:00:01+08:00", "tool_name": "facts.query", "input_summary": null, "result_ref": "Q-FIXTURE-001", "error": null},
    {"sequence": 4, "event_id": "EV-RUN-FIXTURE-004", "event_type": "run_completed", "occurred_at": "2026-10-04T10:00:03+08:00", "tool_name": null, "input_summary": null, "result_ref": "CMP-FIXTURE-001", "error": null}
  ],
  "missing_fields": [], "proposal_comparison_id": "CMP-FIXTURE-001",
  "usage": {"input_tokens": 800, "output_tokens": 160, "cost_cny": null},
  "created_at": "2026-10-04T10:00:00+08:00", "finished_at": "2026-10-04T10:00:03+08:00"
}
```

真实 HTTP 错误样例（模型不可用）：

```json
{"detail": {"code": "model_unavailable", "message": "当前无法连接配置的模型服务", "retryable": true}}
```

如运行已建立后失联，服务仍返回可持久化的真实失败状态：

```json
{
  "fixture_only": true,
  "contract_version": "hackathon.v1", "run_id": "RUN-FIXTURE-UNAVAILABLE", "status": "unavailable",
  "context": {"tenant_id": "demo", "scenario_id": "S01", "branch_id": "transfer_80", "snapshot_id": "SNAP-20261003-BASE", "as_of": "2026-10-03T09:30:00+08:00", "data_version": "retail-v2.1", "fact_version": 1, "is_demo": true, "source_refs": [], "missing_fields": []},
  "summary": null,
  "events": [{"sequence": 1, "event_id": "EV-RUN-FIXTURE-UNAVAILABLE", "event_type": "run_unavailable", "occurred_at": "2026-10-04T10:00:02+08:00", "tool_name": null, "input_summary": null, "result_ref": null, "error": {"code": "model_unavailable", "message": "当前无法连接配置的模型服务"}}],
  "missing_fields": [], "proposal_comparison_id": null, "usage": null,
  "created_at": "2026-10-04T10:00:00+08:00", "finished_at": "2026-10-04T10:00:02+08:00"
}
```

重试次数和工具步数有限；API 总预算未设上限不代表无限重试。保留历史 Run 的时间与来源；展示“正在分析”必须对应 `running` 和真实事件。

## 10. 一次确认、任务和本地渠道

**POST `/api/v1/hackathon/proposals/{proposal_id}/confirm`（已注册）**将审批、资源预留及一个或多个执行任务放在一次外层事务内。请求必须绑定方案／事实／快照版本并带 `Idempotency-Key`。只有当前可执行候选允许确认；版本过期、缺业务字段、无效数量或共享库存冲突不创建审批／任务。相同租户、操作、方案及幂等键重试返回原批准与任务组；不同 payload 复用同键返回 `idempotency_conflict`。管理员只确认一次，无二次自审批循环。

```json
{
  "expected_proposal_version": 1,
  "expected_fact_version": 1,
  "expected_snapshot_id": "SNAP-20261003-BASE",
  "actor_id": "manager-demo",
  "candidate_id": "CAND-TRANSFER-001",
  "task_assignments": [{"action_line_id": "LINE-001", "assignee_id": "person-store-002", "due_at": "2026-10-04T18:00:00+08:00"}]
}
```

```json
{
  "fixture_only": true,
  "contract_version": "hackathon.v1",
  "approval_id": "APR-FIXTURE-001", "proposal_id": "PROP-FIXTURE-001", "proposal_version": 1,
  "approved_by": "manager-demo", "approved_at": "2026-10-04T10:05:00+08:00", "status": "approved",
  "task_group_id": "TG-FIXTURE-001", "idempotent_replay": false,
  "tasks": [{
    "task_id": "TASK-FIXTURE-001", "task_group_id": "TG-FIXTURE-001", "action_line_id": "LINE-001",
    "proposal_id": "PROP-FIXTURE-001", "proposal_version": 1, "status": "draft_pending_external_execution",
    "version": 1, "planned_qty": 80, "completed_qty": 0, "base_unit": "盒",
    "assignee_id": "person-store-002", "due_at": "2026-10-04T18:00:00+08:00",
    "exception": null, "closed_reason": null, "external_write": false, "is_demo": true,
    "accounting": {"expected_cash_cny": 6400, "actual_cash_cny": null, "unmatched_cash_cny": null, "cash_event_ids": [], "status_detail": "尚无到账流水"}
  }]
}
```

任务状态保留后端原始枚举与进度明细；`completed_qty < planned_qty` 时是部分完成而非完成，异常和取消原因独立保存。消息状态只描述渠道动作，不能更改任务状态、库存或现金。渠道动作记录需有 `action_id/task_id/proposal_id/proposal_version/channel/status/content_snapshot/target_ref/idempotency_key/receipt_ref/source/is_demo=true/external_write=false/created_at`。渠道枚举是 `feishu/wecom/email`；任何动作均为本地数据库记录，不调用真实发送平台。

```json
{
  "task_id": "TASK-FIXTURE-001",
  "proposal_id": "PROP-FIXTURE-001",
  "proposal_version": 1,
  "channel": "wecom",
  "action_type": "promotion_draft",
  "status": "draft_saved",
  "content_snapshot": {"title": "酸奶夹心饼干组合优惠", "approved_price_cny": 10, "start_date": "2026-10-03", "end_date_exclusive": "2026-10-13"},
  "target_ref": "ST-004",
  "actor_id": "manager-demo"
}
```

```json
{
  "fixture_only": true,
  "contract_version": "hackathon.v1",
  "action_id": "ACTION-FIXTURE-001", "task_id": "TASK-FIXTURE-001",
  "proposal_id": "PROP-FIXTURE-001", "proposal_version": 1,
  "channel": "wecom", "status": "draft_saved",
  "content_snapshot": {"title": "酸奶夹心饼干组合优惠", "approved_price_cny": 10, "start_date": "2026-10-03", "end_date_exclusive": "2026-10-13"},
  "target_ref": "ST-004", "idempotency_key": "demo:task-1:wecom:draft-v1",
  "receipt_ref": null, "source": "local_channel_simulation", "is_demo": true, "external_write": false,
  "created_at": "2026-10-04T10:10:00+08:00"
}
```

任务 6 在其组件内实现展示 helper `mapFollowupDisplay(task, accounting)`；这是 D07 的页面投影，不写回数据库、不替换原 API `status`。映射返回 `raw_execution_status`、`execution_display_status`、`accounting_display_status`、计划／已完成／未完成数量、`exception` 与 `closed_reason`。待派发归为“待执行”；执行／签收有进度但未达 `completion_criteria`（包括部分完成）归为“执行中”；只有数量及业务完成凭据满足条件才显示“已完成”。异常通过 `needs_attention` 单独突出；取消保留原始状态和原因，归档但不计为完成。核算展示遵循现金流水、核销／换货凭据及任务 `completion_criteria`；存在部分依据但未满足条件时保留“核算中”，未产生结果依据时“待核算”。此 helper 必须同时返回原始状态及进度数据，且不向服务端提交展示枚举。

已注册路由：`GET /hackathon/tasks`、`GET /hackathon/tasks/{task_id}`、`POST /hackathon/tasks/{task_id}/channel-actions`、`POST /hackathon/tasks/{task_id}/events`。任务事件输入需包含任务／方案版本、事件唯一 ID、来源回执、数量和单位、发生／获知时间；版本或数量不匹配返回 409。现有手工状态接口仍保持兼容，但不能将它串联成替代原子确认的新前端流程。

## 11. 回放与核算

**POST `/api/v1/hackathon/replays/advance`（已注册）**输入场景、分支、推进后的 `as_of`、已批准方案／版本及幂等键。时钟不能倒退；只选取 `occurred_at <= as_of` 且 `known_at <= as_of` 的 05 事件。分支、任务、批准 proposal/version、数量和单位必须与回放行匹配。方案修改、反馈重算或数量变化后拒绝旧回放；不得以场景名称直接触发预设答案。`event_id` 唯一去重；每条成功事件在同一事务更新业务事件、库存、执行进度、现金流水／核销、审计及事实版本。

现金定义：销售记录不等于到账，到账只由现金流水记录；签收只更新货物和执行证据；渠道“已发送”不影响业务状态。一个现金流水可分次核销，但核销合计不可超过流水金额。采购少付是相对冻结原计划的同周期现金流出差额，不是入账回款。退款须经退供验收并有到账流水；换货更新库存但不假造退款；抵款更新应付核销，不形成账户入账。共享运输费用只计一次。结果同时回传计划、实际、未知、部分完成及缺项，不把库存成本、毛利、预计回款和到账简单相加成“收益”。

```json
{
  "scenario_id": "S01", "branch_id": "transfer_80", "as_of": "2026-10-25T23:59:00+08:00",
  "proposal_id": "PROP-FIXTURE-001", "proposal_version": 1,
  "expected_fact_version": 1, "actor_id": "manager-demo"
}
```

```json
{
  "fixture_only": true, "contract_version": "hackathon.v1",
  "context": {"tenant_id": "demo", "scenario_id": "S01", "branch_id": "transfer_80", "snapshot_id": "SNAP-20261003-BASE", "as_of": "2026-10-25T23:59:00+08:00", "data_version": "retail-v2.1", "fact_version": 2, "is_demo": true, "source_refs": [], "missing_fields": []},
  "advanced_to": "2026-10-25T23:59:00+08:00",
  "applied_event_ids": ["RECEIPT-FIXTURE-001", "SALE-FIXTURE-001", "CASH-FIXTURE-001"],
  "duplicate_event_ids": [], "held_event_ids": [],
  "inventory_deltas": [{"store_id": "ST-001", "sku_id": "SKU-001", "lot_id": "LOT-001-001", "quantity_delta": -80, "base_unit": "盒", "event_id": "DISPATCH-FIXTURE-001"}, {"store_id": "ST-002", "sku_id": "SKU-001", "lot_id": "LOT-001-001", "quantity_delta": 80, "base_unit": "盒", "event_id": "RECEIPT-FIXTURE-001"}, {"store_id": "ST-002", "sku_id": "SKU-001", "lot_id": "LOT-001-001", "quantity_delta": -64, "base_unit": "盒", "event_id": "SALE-FIXTURE-001"}],
  "cash_event_ids": ["CASH-FIXTURE-001"],
  "accounting": {"planned_qty": 80, "shipped_qty": 80, "received_qty": 80, "sold_qty": 64, "sales_amount_cny": 6400, "sold_cost_cny": 5120, "transport_cost_cny": 24, "actual_cash_in_cny": 6400, "unmatched_cash_cny": 0, "ending_qty": 16, "execution_status": "completed", "accounting_note": "已发生回款流水并完成核销", "is_demo": true, "external_write": false}
}
```

示例进度／资金聚合（S09 的 fixture）：计划 80 盒、签收 60 盒、卖出 40 盒、到账 3,000 元时，回传 `received_qty=60`、`sold_qty=40`、`actual_cash_in_cny=3000`、剩余未执行 20、未到账预期金额 1,000（仅在确认本次计划回款金额 4,000 的条件下）；不得显示全部完成或全部到账。

**GET `/api/v1/hackathon/accounting`（已注册）**按 `scenario_id/branch_id/task_id/proposal_id` 聚合原始业务事件和账务依据，返回实际现金流水 ID、核销分配 ID、未匹配金额、费用、剩余量、计算版本、事件证据和 `missing_fields`。若尚无已记账流水，`actual_cash_in_cny=null`，不能将预计回款复制到实际字段。

```json
{
  "fixture_only": true, "contract_version": "hackathon.v1",
  "context": {"tenant_id": "demo", "scenario_id": "S09", "branch_id": "partial_transfer", "snapshot_id": "SNAP-20261003-BASE", "as_of": "2026-10-25T23:59:00+08:00", "data_version": "retail-v2.1", "fact_version": 3, "is_demo": true, "source_refs": [], "missing_fields": []},
  "task_id": "TASK-FIXTURE-PARTIAL", "proposal_id": "PROP-FIXTURE-PARTIAL", "proposal_version": 1,
  "planned_qty": 80, "shipped_qty": 60, "received_qty": 60, "remaining_unexecuted_qty": 20, "sold_qty": 40, "base_unit": "盒",
  "sales_amount_cny": 4000, "expected_cash_in_cny": 4000, "actual_cash_in_cny": 3000, "unmatched_cash_cny": 0, "uncollected_expected_cny": 1000,
  "inventory_cost_released_cny": 3200, "sold_cost_cny": 2560, "execution_cost_cny": 24,
  "cash_event_ids": ["CASH-FIXTURE-PARTIAL"], "allocation_ids": ["ALLOC-FIXTURE-PARTIAL"],
  "event_refs": ["DISPATCH-FIXTURE-PARTIAL", "RECEIPT-FIXTURE-PARTIAL", "SALE-FIXTURE-PARTIAL", "CASH-FIXTURE-PARTIAL"],
  "execution_status": "in_transit", "accounting_note": "已到账3000元，尚有1000元待到账", "missing_fields": [], "is_demo": true
}
```

## 12. 前端 API 与组件生命周期（历史契约）

本节描述的浏览器适配器与两个挂载组件已从源码删除，仅供追溯原并行实现，不代表当前应用入口或可运行代码。

共享适配器为 `window.HackathonApiClient.createApiClient({ baseUrl, tenantId })`，默认真实 HTTP 模式，base URL 为同源 `/api/v1`；可调用 `.queryFacts/.assessRisks/.compareProposals/.saveProposal/.extractMaterial/.confirmMaterial/.startAgentRun/.getAgentRun/.confirmProposal/.listProposals/.listTasks/.getOverview/.getTask/.recordChannelAction/.recordBusinessEvents/.advanceReplay/.getAccounting/.getCase`。`extractMaterial(input, idempotencyKey)` 对 JSON／multipart 共用完整 `context`；`confirmMaterial(draftId, body, idempotencyKey)` 附带幂等键。`listProposals(params)` 读取待确认方案，`getOverview(params)` 读取首页聚合。所有错误抛出 `ApiError(status, code, message, detail, payload)`。断网、409、422 不返回成功对象，不自动重试写操作。

开发 fixture 必须显式调用 `createApiClient({mode:"fixture", fixtures})` 或 `createFixtureClient(fixtures)`；按完整 `"METHOD /path?query"` 键逐项提供响应。缺 fixture 返回 `fixture_missing`；HTTP 实例不接受 fixtures，也不会错误回退。组件可通过 `api.mode === "fixture"` 显示开发预览态。当前两份模块预览禁用确认、材料写入、渠道动作和 Agent 启动；这些预览不以 fixture 响应模拟写入成功。

任务 5 导出 `window.HackathonDecision.mount(container, options)`；任务 6 导出 `window.HackathonFollowup.mount(container, options)`。`options` 统一为：

```js
{
  api, // 注入的真实 client 或明确的 fixture client
  navigate, // (route, context) => void
  context: {
    tenantId: "demo", scenarioId: "S01", branchId: "transfer_80",
    snapshotId: "SNAP-20261003-BASE", asOf: "2026-10-03T09:30:00+08:00",
    dataVersion: "retail-v2.1", factVersion: 1, isDemo: true,
    sourceRefs: [], missingFields: [], area: "transfer",
    horizonStart: "2026-10-03", horizonEnd: "2026-10-25", assumptionIds: [],
    riskId: null, storeId: "ST-001",
    skuId: "SKU-001", lotId: "LOT-001-001", actorId: "manager-demo",
    proposalId: null, proposalVersion: null, taskId: null,
    businessInputs: {}
  }
}
```

两个组件使用相同的 camelCase 宿主上下文和 `api/navigate/context` 挂载参数。API payload 继续使用 snake_case。可选的 `businessInputs` 使用第 7 节按动作分组的结构。宿主执行写操作时必须提供 `actorId`；继续已有方案时提供当前方案 ID／版本。这些值属于请求上下文，不是已认证身份。宿主还须提供 `dataVersion/isDemo`，组件不推断数据新鲜度或演示状态。

`mount` 返回 `{ destroy(), updateContext(nextContext) }`。容器由宿主页面拥有，组件只增删自己的子树；样式限定本组件根节点，卸载时移除全部监听器、定时器、AbortController 和订阅。组件不得直接访问全局 app 状态、另起 API 连接、用 `localStorage` 保存业务真相，或在确认后要求第二次审批。主页面由 `app.js/index.html` 接入；两个模块复用原版 hash 导航和页面外壳。

```js
const api = window.HackathonApiClient.createApiClient({ tenantId: "demo" });
const mounted = window.HackathonDecision.mount(document.querySelector("#decision-root"), {
  api,
  navigate: (route, context) => window.dispatchEvent(new CustomEvent("app:navigate", { detail: { route, context } })),
  context: { tenantId: "demo", scenarioId: "S01", branchId: "transfer_80", snapshotId: "SNAP-20261003-BASE", asOf: "2026-10-03T09:30:00+08:00", dataVersion: "retail-v2.1", factVersion: 1, isDemo: true, sourceRefs: [], missingFields: [], area: "transfer", horizonStart: "2026-10-03", horizonEnd: "2026-10-25", assumptionIds: [], riskId: null, storeId: "ST-001", skuId: "SKU-001", lotId: "LOT-001-001", actorId: "manager-demo", proposalId: null, proposalVersion: null, taskId: null, businessInputs: {} },
});
// On route change or when the host replaces this view:
mounted.destroy();
```

跟进组件使用 `listTasks(contextQuery) + listProposals({...contextQuery, status: "pending_approval"}) + getOverview(overviewQuery)` 加载任务、待确认方案与经营聚合；列表项互不替代。总览中的 `pending_approvals/task_links` 由执行读服务补充；经营事实只由数据服务聚合。`GET /hackathon/overview` 的未知值以 `null` 展示，不能从任务事件或 fixture 推算后端汇总。

组件在容器上 dispatch 以下可冒泡 `CustomEvent`，`detail` 至少带 `context`：

| 事件名 | `detail` 附加字段 | 宿主责任 |
|---|---|---|
| `hackathon:context-change` | `patch` | 更新当前场景／商品／批次上下文 |
| `hackathon:proposal-confirmed` | `approvalId`、`proposalId`、`proposalVersion`、`taskIds` | 切换审批后跟进事项 |
| `hackathon:task-updated` | `taskId`、`taskVersion` | 刷新任务详情 |
| `hackathon:run-updated` | `runId`、`status`、`lastSequence` | 更新真实运行过程 |
| `hackathon:error` | `code`、`message`、`retryable` | 展示可恢复错误，不以假数据替代 |

前端可以维护未提交的表单输入；服务端成功保存后刷新必须重新读取服务数据。改变计算输入即禁用旧 candidate 的确认按钮，直到对应版本的重算响应返回。金额和库存取后端响应；字段展示必须保留单位、来源、`is_demo`、预计／实际与时点口径。无视觉截图时，用户可上传当前页面截图供对照；这不替代接口测试。

## 13. 并行文件归属与总集成接线

任务 1—6 按 `docs/PARALLEL_DEVELOPMENT.md` 与各自提示词约定的独占路径工作。本契约与共享适配器由任务框 0 维护。若实现需要偏离字段、路径、事务或组件签名，先在自己的 `docs/parallel-handoff/` 记录原因与替代提议；不要悄悄建立第二套契约。

总集成已完成服务注册与迁移、唯一 `Store` 注入、`/api/v1/hackathon/*` 路由、静态代理 allowlist、原版绿色外壳组件挂载、计算服务内的动作级输入验证、按批次库存变化、执行读服务的待确认方案列表和首页聚合。总集成在合并分支先保存为 `cd3d180`，随后仅按序 cherry-pick 后端增量 `c62827e/a1bbad6/92e59d3/54d995b`（本地提交 `9b2b3fa/42ffc8d/0deab15/8a7ee8f`）；没有引入 `5deb452` 的另一套前端壳。HTTP 联测覆盖 S01 调拨、方案保存与确认、任务读取、回放核算；S07 采购、S06 促销和 S05 缺条件退供；经营总览复用数据服务，材料刷新恢复读取保存的确认上下文。模型 provider 未配置时，材料与 Agent 返回持久化不可用状态；预览 fixture 和 MockTransport 不作为真实接口／模型成功。CUA 截图环境仍异常，截图级视觉核验未完成。

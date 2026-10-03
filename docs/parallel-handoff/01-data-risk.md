# 任务 1：数据接入与风险识别交接

## 边界与实现

本模块只修改 `backend/hackathon_data/`、`scripts/hackathon_load_data.py`、`tests/hackathon/test_data*.py` 和本交接文件。未修改原始 Excel、manifest、公共 API、Store、前端和真实库存数据。已删除早期独立 workspace 的 `projection.py` 与其专属测试；当前事实由 `RetailFactService` 一处维护。

- `loader.py`：按 manifest 校验文件 SHA256、大小、工作表、列和行数，使用 data dictionary 规范字段类型；校验库存、批次、商品、门店、采购和在途关联。日期统一 ISO，时间必须带时区。加载 01—04，不使用 07 代替原数据包。
- `risk.py`：按有效观察日、净销量、覆盖天数和可售截止日期分别判断滞销与近效期；风险可重叠，批次成本只计一次。缺销量、观察天数或效期返回未知；停售批次保留不可售事实，FEFO 共用门店需求预算。
- `service.py`：在现有 `Store.transaction()` 内迁移、导入、查询、发布业务事件与事实版本。不建立第二个 SQLite 连接，不在调用方事务内提交。版本状态记录当前库存和发生变化的业务表，公共预约与现金表仍由执行模块维护。

50 家门店目录中 6 家具备完整事实，包含 12 个商品。目录占位门店若被明确查询，返回具体缺项；不报告为正常库存或可计算门店。

## 初始化与调用

```python
from backend.hackathon_data import RetailFactService, migrate

facts = RetailFactService(store)
with store.transaction() as tx:
    migrate(tx)
    report = facts.import_scenario("demo", "S01", "transfer_80", tx=tx)
context = report["context"]
current = facts.query({"context": context})
risks = facts.assess_risks({"context": context})
```

导出的入口：

```text
RetailFactService(store, root=None)
migrate(tx)
import_scenario(tenant_id, scenario_id, branch_id=None, *, as_of=None, actor_id="system", tx=None)
get_context(tenant_id, scenario_id, branch_id=None, *, tx=None) -> FactContext
read_facts(context, *, tx=None) -> 内部当前事实读模型
query(FactQuery) -> FactQueryResult
assess_risks(FactQuery) -> RiskAssessment
resolve_legacy_risk_id(context, risk_key) -> int | None
apply_business_events(tx, events, *, expected_fact_version) -> 发布报告
advance_clock(tx, context, as_of, *, confirmed_override_ids=()) -> {contract_version, context, advanced_to}
```

`read_facts` 供总集成诊断或执行适配使用；计算和 AI 使用公共 `query` DTO。`advance_clock` 可作为执行服务的 `clock_advancer` 注入。

- 导入同一租户、场景、规范分支和源版本为幂等操作。源文件或初始读取时点变化不能覆盖已导入事实，推进时间使用 `advance_clock`。
- `snapshot_id` 对导入工作范围稳定，事件批次通过 `fact_version` 递增。当前版本、snapshot、data_version 与 as_of 必须匹配，不能伪造未来 context 查询。
- `is_demo`、`source_refs` 和 `missing_fields` 必须与持久化上下文一致；布尔值与数字不视为同一类型。查询与风险响应只返回权威上下文，不回显客户端额外注记，不能把合成数据伪装成真实数据或隐藏缺项。
- `get_context` 省略分支时，仅在该租户场景只导入一个分支的情况下返回；多个分支明确报歧义。
- `query_id` 根据上下文与查询条件生成，同版本同查询稳定。

命令行必须显式选择目标数据库，无生产库默认值：

```powershell
.\.venv\Scripts\python.exe scripts/hackathon_load_data.py --db <专用测试库路径> --tenant demo --scenario S01 --branch transfer_80
```

## 隔离、回放与风险关联

- S02、S05、S07、S08、S10 按各自输入和覆盖规则读取。S10 缺项不从 BASE 补齐。S02 目录 `risk_overlap` 显式映射到实际 `overlap` 并给出告警；未知分支拒绝。
- S08 门店闭店等反馈必须在 known_at 到达后，通过 `confirmed_override_ids` 明确确认；确认后的日历事实在后续时间推进中保留。
- `advance_clock` 更新当前已知的批次、材料、门店日历；不自动改库存、订单、销售和现金，实际变化必须来自业务回执。
- `load_replay(scenario_id, branch_id=None, *, clock_at, root=None)` 单独读取 05，并按分支、known_at、occurred_at 过滤。该返回只能注入执行服务，不进入 `FactQueryResult`。06 不进入运行时加载。
- `risk_key` 遵循正式示例：`S01:ST-001:SKU-001:LOT-001-001:slow_moving`；近效期使用不同末段 `near_expiry`。`counted_inventory_keys` 使用 `store|sku|lot` 去重。
- 导入时每个批次建立明确的旧数字风险 FK 兼容行和映射；同一批次的两类风险映射同一兼容行。查询、计算仍以版本化事实为准。没有明确映射的新批次返回 `None`，不猜测旧风险 ID。

## 公共 DTO 补充项，待总集成同步共享声明

原 `FactQueryResult` 未包含计算与材料识别所需的全部主数据。按协调约定增加可选 `reference_data`，不在里面复制正式库存、销售、在途或应付表：

```text
reference_data = {
  target: {store_id, sku_id, lot_id},
  evaluation_end: "YYYY-MM-DD",             # 截止日不含当天
  tables: {
    stores, products, suppliers, people, store_products, store_calendar, lots,
    promotion_stages, bundle_items, assumptions, materials, purchase_intents,
    risk_inputs, procurement_policy, transfer_policy, accounts,
    credit_notes                           # 发生已确认抵款事件后出现
  }
}
```

- `inventory` 使用 `quantity/base_unit/unit_cost_cny`，另保留 `inventory_id/shipment_line_id/external_reserved_qty`。
- `reserved_qty` 是源数据预占与公共 `inventory_reservations` 之和；`external_reserved_qty` 只含源数据预占，执行校验可据此避免重复扣减。
- 公共预约资源键为 `store|sku|lot|on_hand`，按 `tenant_id + snapshot_id` 隔离。
- `procurement` 行的 `record_type` 为 `purchase_order` 或 `in_transit`；`policies` 行为 `risk_policy` 或 `return_terms`。其余业务列沿原始 English schema。
- `stock_state` 补充 `return_in_transit`，表示已发出但供应商尚未验收的退供库存，不能算作门店可卖库存或普通调入库存。
- `RiskItem.unsellable` 保留已过可售截止时间的事实。无适用规则时 `rule_version=null`，同时报告 `risk_policy` 缺项。
- 公共现金表的 `scenario_id` 使用该范围稳定的 `snapshot_id`。执行现金 `source="hackathon_execution:<account_id>"` 明确账户归属。旧无此标记流水只有在范围内恰好一个账户时可唯一归属，多账户时拒绝模糊归属，绝不加到每个账户。

## 业务事件发布约定

所有事件使用公共 `BusinessEvent` 头，原回执附加字段放 `details`。必须同一 tenant/scenario/branch、显式 `is_demo=true/external_write=false`，时间带时区且 known_at 不早于 occurred_at。事件编号与内容哈希用于幂等；相同编号内容不同拒绝，负数、布尔数值和非有限数值拒绝。

已支持：

| event_type | 事实变化 |
|---|---|
| transfer_shipped / transfer_received | 调出在手、调入在途及签收在手；同步发运明细，不重复计在途 |
| return_shipped / supplier_accepted | 在手转退供在途，再按实际验收移出 |
| purchase_received / exchange_received | 实际收货入库；采购关联订单和已有发运，更新 received_qty |
| sale | 实际批次库存减少，追加销售历史；销售金额不会自动变成到账 |
| order_confirmed | 新建已确认采购单与应付，移除明确关联的采购意向 |
| purchase_cancelled | 数量为 0 的采购取消确认；意向标 cancelled 并保存回执，不造零数量订单 |
| credit_issued / credit_applied | 保存抵款额度及余额，按同供应商已知应付应用；不会产生现金流入 |
| purchase_payment / payable_payment | 更新订单或应付的付款与未付金额；现金仍来自公共现金表 |
| material_confirmed | 发布人工确认后的采购意向或退供条件，不代表下单或供应商接受 |
| supplier_confirmed / promotion_price_effective / promotion_ended / execution_exception | 审计发布事实版本，无库存与现金变化 |
| execution_scheduled / execution_cancelled / execution_receipt_recorded | 公共预约或执行信息发生变化后发布版本，无重复库存变化 |

库存事件必须提供已知商品、批次、正确 `base_unit` 与正数量；`supplier_accepted` 须由执行层从已批准任务补齐归属。`transfer` 需要 task_id，发运标识为 `transfer:<task_id>`，预计到货时间来自 `details.expected_arrival_at`。同批次多个调拨任务的在途可有多行；执行临时 position 聚合应求和，不能覆盖前一行。

新收到的批次允许保存实际身份，但未知效期保留 null，不能据此默认允许销售。`purchase_received` 必须关联明确 po_line_id；若存在 shipment_line_id，订单、发运和库存三者均校验。

抵款以 `credit_id` 为内部列，明确兼容事件的 `credit_note_id`；二者同时提供且不同则拒绝。`purchase_cancelled` 需要真实 intent_id、数量 0 和 supplier confirmation receipt_ref。

材料事件 `details={material_kind,fields,accepted_unresolved_fields}`。缺少必填字段需要精确确认缺项清单后以 null 保存；未知门店、商品、批次、供应商和错误单位拒绝。百分比为 0—100，金额单位元。同供应商与 SKU 的退供条件保留 `supersedes_term_id`，不把两条同范围条件同时当作有效条款。采购意向保留 `draft_unconfirmed`，仍需后续方案批准与供应商回执。

## 验证与待接线

验证使用独立临时数据库，不读取实际库或 `.env`。单元覆盖包括文件校验、分支与未来隔离、风险重叠、未知字段、旧 FK 映射、共享事务回滚、幂等冲突、库存守恒、已收采购不重复成为在途/未发采购、材料确认、公共预占与现金仅计算一次、抵款非现金、采购取消、闭店确认的持续性，以及数据来源标记和缺项上下文篡改。

```powershell
.\.venv\Scripts\python.exe -m unittest tests.hackathon.test_data_loader tests.hackathon.test_data_risk tests.hackathon.test_data_service
```

本轮结果：39 项测试全部通过，耗时 45.364 秒；CLI `--help` 也已验证。公共路由注册、前端接线和正式共享类型文件由总集成管理，本模块未越界修改；真实 ERP 接入与多账户真实流水尚未验证。

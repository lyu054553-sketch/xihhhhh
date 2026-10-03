# 任务 4：确认、执行、渠道与资金

本模块按 `docs/PARALLEL_CONTRACT.md` 和现有 Store 实现。仅改 `backend/hackathon_execution/`、`tests/hackathon/test_execution*.py` 及本交接；公共路由、共享类型、Store、前端由任务 0 接线。本轮未运行真实外部发送或真实模型请求。

## 初始化和事务

```python
from backend.hackathon_data import RetailFactService, load_replay, migrate as migrate_data
from backend.hackathon_calculations import CalculationService
from backend.hackathon_execution import ExecutionService, migrate as migrate_execution

with database.transaction() as tx:
    migrate_data(tx)
    migrate_execution(tx)
facts = RetailFactService(database)
calculations = CalculationService()
execution = ExecutionService(database, facts, calculations,
    replay_reader=load_replay, clock_advancer=facts.advance_clock)
```

构造器不连接或迁移数据库，`migrate(tx)` 要求外层已开启事务，不自行 commit。运行时只调用注入的 FactService、CalculationService 和公共 transaction；没有独立 SQLite 连接或另一份 workspace 库存 JSON。

复用公共 `proposals/proposal_versions/approvals/execution_tasks/inventory_reservations/cash_events`。本模块仅新增 `hackathon_execution_commands`（命令幂等）、`hackathon_execution_receipts`（业务回执和现金引用、核销）和 `hackathon_channel_actions`（本地渠道历史）。任务进度／批准动作保存在既有 execution_tasks.metadata_json；内存 domain 投影在每个事务中从事实服务与既有账表重建，库存持久化只由数据服务负责。

现金金额只写公共 cash_events.amount，回执表只保存 cash_id 和事件元数据，不维护第二个现金余额。该表的历史 scenario_id 列使用本场景稳定 snapshot_id 隔离租户和分支；source 使用 `hackathon_execution:<account_id>` 明确账户归属，原始来源仍保留在回执。数据服务据此归入正确账户；集成方后续若增加正式 account_id 列，应统一迁移该约定。

## 服务输入输出

所有写操作带完整 `context`、非空 `actor_id/idempotency_key`。HTTP 层从授权身份和 Idempotency-Key 注入，不能把本服务的 actor_id 字段当作已经完成鉴权。所有成功响应使用 `contract_version=hackathon.v1`。不得从请求直接接收计算金额作为批准方案。

### 保存和一次确认

`save_proposal(request)` 使用正式比较字段：context、risk_keys、objective、horizon_start/end、assumption_ids、business_inputs，以及计算模块兼容 inputs；另带 comparison_id、candidate_id、expected_current_proposal_version。business_inputs 原样保存并在保存、确认时重新交由计算服务验证，不能在持久化边界丢掉动作输入。首次为 0；修订额外给 proposal_id 和当前版本。保存前重读事实、重新计算并核对内容 ID。首个 risk_key 必须由数据服务映射且属于实际比较批次。已执行方案不能覆盖，需创建新方案。

返回 proposal_id/version、draft 状态、comparison/candidate/risk ID、事实／计算／策略版本和稳定 action_lines。既有数据库保留 pending_approval 原始状态；draft 是保存响应的业务语义。纯保留原店可保存为比较基线，不生成执行任务。

`confirm_and_schedule(request)` 字段为：context、proposal_id、expected_proposal_version、expected_fact_version、expected_snapshot_id、candidate_id，以及 task_assignments：

```python
task_assignments = [
    {"action_line_id": saved["action_lines"][0]["action_line_id"],
     "assignee_id": "P-002", "due_at": "2026-10-04T18:00:00+08:00"}
]
```

组合必须每行恰好分配一位负责人和截止时间，允许各行不同负责人。复核版本、当前占用与计算结果之后，审批、预占、任务组和所有子任务在一次 Store 事务完成；失败不留半条记录。原样重试返回同 approval/task_group，idempotent_replay=true；同键不同内容拒绝。公共预占目前是整数基础单位，非整数数量不暗自取整。

任务响应包含 task_id/group/action_line/proposal/version、原始 status、planned/completed_qty、base_unit、assignee_id、due_at、exception、closed_reason、accounting，以及可追溯的 plan/progress/result。保留原始枚举；执行完成与核算完成分开。附加 display_status/next_action 只为展示，不能写回替换原枚举。

### 回执、撤销和渠道

`record_business_events(request)` 的 events 为 `[{kind, record}, ...]`；这是单据类型不同的服务入口扩展，由任务 0 的 `/tasks/{id}/events` schema 固定映射。

| kind | 唯一 ID | record 内容 |
|---|---|---|
| business | event_id | event_type、数量、商品批次、门店、发生／获知时间和单据引用 |
| sale | sale_id | date、sold_qty、unit_price、sales_amount、批次、获知时间 |
| cash | cash_event_id | account_id、direction、amount、occurred_at、known_at、business_ref、receipt_ref；关联支出用 category |
| cash_allocation | allocation_id | cash_event_id、business_ref、allocated_amount、known_at |
| return_confirmation | return_id | supplier/term、accepted_qty/mode/unit_price、return_fee 及换货／抵款条件 |

有 task_id 的回执必须绑定正确 proposal_id/version；单位必须与商品基础单位相同；供应商、采购意向、到货日不允许替换批准身份。租户、场景和版本从已验证 context 确定。每条回执同 ID 不同内容拒绝，重复同内容不重复扣库存或计现金。

业务类型：transfer_shipped/received、supplier_confirmed、return_shipped、supplier_accepted、exchange_received、credit_issued/applied、order_confirmed、purchase_received、purchase_cancelled、promotion_price_effective/ended、execution_exception。零采购是批准不下单后等待 purchase_cancelled 和供应商回执；不能用零数量假订单、假退款表示完成。

`cancel_task(request)` 扩展需要 task_id/reason：仅释放未执行的预占，保存撤销人／原因和历史。已发生的运输、签收、现金及未到账责任继续保留，不把撤销计为完成。接收店已确认不可收货时，尚未发出的调拨标记 replan_required。

`record_channel_action(request)` 使用 task_id、proposal_id/version、channel、action_type、status、content_snapshot、target_ref，可带 receipt_ref/receipt。返回正式 action 字段及持久化 history。飞书、企微、邮箱仅记录本地动作，始终 is_demo=true/external_write=false。draft_saved→sent→accepted→completed；邮箱可经 reply_received，failed 可重试。内容或接收人变化不能覆盖既有批准记录；渠道完成不自动产生业务回执或资金。

### 回放和核算

`advance_replay(request)`：context、proposal_id/version、expected_fact_version、as_of。固定 05 回放匹配明确的批准方案版本、任务类型、数量和单位；业务回执进一步核对门店／批次／供应商／费用和促销组合价格。改量、改运费、改阶段价不能套用旧结果。不能只传场景名生成预设成功。

时钟先经注入 clock_advancer 发布当前可知的批次／参考事实，再读取到时的 05 回执；06 验收答案永不读取。每条 occurred_at 和 known_at 均不得晚于时钟。版本推进、库存／在途／预占、任务进度、现金和核销都在同一事务内；后半条核销失败也回滚前面的时钟和出入库。当前 reader 只返回已到时事件，因此 held_event_ids 为空，不暴露未来事件身份。

`get_accounting({context})` 返回场景账户、库存、任务、渠道、timeline、payables 和 case_results；账户现金包含本场景其他批次，案例按实际任务和核销归属拆分。加 task_id 返回该任务的正式核算字段（actual_cash_in_cny、sold_cost_cny、ending_qty、cash_event_ids、allocation_ids 等）。加 proposal_id 时，任务、现金、回执时间线和渠道一起限定到该方案，移除场景全账户余额、其他库存和应付明细，cash_scope=selected_tasks；共享现金流水只暴露已核销给本次任务的分配额，不把其他任务的到账归进案例。共享流水尚未核销的余额没有明确案例归属时 unmatched_cash_cny=null，并列出缺项。

### 列表、经营总览、事项详情与案例

本轮新增读接口，只读取已保存的公共表，不重算草稿、不调用模型、不写新的案例／资金真相表：

| 方法 | 参数 | 返回要点 |
|---|---|---|
| `list_proposals(request)` | 完整 context，可选 status、proposal_id/proposal_version | proposals[] 与 metadata；当前保存版本的标题、风险键、action_lines、候选计算和输入、创建／更新时间、缺项与 requires_recalculation；空列表明确 [] |
| `list_tasks(request)` | 完整 context，可选原始 status、task_id/task_version、proposal_id/proposal_version | tasks[]、metadata；持久化执行进度、案例链接和保存方案，执行状态和资金状态分开 |
| `get_task(request)` | 完整 context、task_id，可选两类版本／proposal_id | task、单任务 accounting、channels、timeline，不夹带其他任务事件 |
| `get_case(request)` | 完整 context、case_id 或 proposal_id，可选版本／task_id | case 内保存版本历史、确认记录、渠道历史、业务／销售／现金／核销时间线、任务及方案内 accounting |
| `get_overview(request)` | 完整 context | contract_version/context/overview/metadata；数据服务的四项经营聚合，加 pending_approvals、门店待办链接与 task_links |

`case_id` 明确复用稳定 `proposal_id`，不是另外生成的案例号；HTTP `/cases/{case_id}` 由总集成映射为同一请求的 case_id。草稿也可读取案例历史，此时没有执行记录和核算结果。读取校验 tenant、scenario/branch、snapshot、as_of 和 fact_version；请求带任务或方案版本时也核对对应版本。返回方案中的 context 是保存时的上下文，顶层 context 是本次读取上下文，两者不混写。历史候选保持原值；事实变化标记 requires_recalculation，不偷偷替换方案金额。timeline 保留 record 原始核验字段，并提供标签、数量、金额、单位、来源、occurred_at/known_at、is_actual/is_demo/external_write 作为显示投影。撤销保存 cancelled_at 并进入时间线；旧数据缺少撤销时间时保持未知。

经营总览依赖新增 `FactService.get_overview(request, *, tx=None)`，通过注入的同一个 Store 活动事务读取。账户可用资金、库存成本、风险库存和未来 30 天已确认采购付款完全由模块 1 计算；执行层只聚合保存动作的数量×当时单位成本作为待确认库存成本。任一成本未知则 amount=null，以 known_amount/missing_count 展示已知部分；不使用预计回款冒充库存成本。待办金额不是新账户余额。任务链接来自公共执行任务，不维护第二份待办表。

销售不是现金。只有现金流水增加账户，核销只归属已有到账；单笔流水可分次核销但不超额，退供回执不同引用也不能重复核销同一应收。费用流水按唯一事件一次计入。未观察到到账时 actual_cash_in_cny=null。退款、换货、抵款独立：部分换货／抵款条件改变需要重算，不允许部分退货获得整笔换货或额度。促销组数和商品件数分别记录，多个批次按实际批次消耗恢复预占。

S01 验证：调拨批次到账 6400 元、成本 5120 元、费用 24 元；原目的店其他批次另到账 1000 元，账户总到账 7400 元。S09 签收 60/80 盒、到账 3000 元、已销售未到账 1000 元，仍保留执行和核算跟进。S05 三种结算、S06 两阶段组合促销、S07 已付在途与新采购均用真实合成工作簿测试。

## 验证与接线事项

```powershell
.venv\Scripts\python.exe -m unittest tests.hackathon.test_execution_domain tests.hackathon.test_execution_service tests.hackathon.test_execution_reads -q
```

验证使用 TemporaryDirectory 独立 SQLite，不启动正式服务、不写用户数据库。本轮先完成 46 项执行测试（16 项领域验证、21 项真实数据／计算／执行联测、9 项新增读服务验证，148.816 秒）。补齐撤销显示和账户余额未知处理后，10 项读验证加 1 项撤销回归全部通过（42.200 秒）；当前执行测试共 47 项。联测发现并由数据任务修复了公共 cash_events.event_date 为带时区时点时的读取问题。覆盖同键重试、双线程确认、租户隔离、刷新／分步与重复回放、部分完成、金额及回执身份、组合预占、发布失败和后半段核销失败的整事务回滚；新读验证包含历史版本、业务输入不丢失、保存读取不重算、真实经营总览与重开恢复、跨任务／其他批次事件过滤、共享到账按核销金额隔离、账户余额未知不阻断任务读取。上一轮原有 tests/backend 的 53 项通过；本次公共 API 未修改，最终整体回归由根任务统一执行。

任务 0 待接：统一注册 migrations 和 HackathonServices；为保存、确认、渠道、回执、回放、核算和新增五个读方法提供严格 HTTP schema；task_id／proposal_id／case_id 路径与完整 context 交叉核验。GET 路由的 query 需由适配层解析为完整且经过验证的 context，不能接受跨租户 ID 猜测或忽略客户端提供的快照／时点。公共 ExecutionService Protocol 需增加上述读方法，FactService Protocol 需增加 get_overview；公共文件本任务未修改。不得直接把旧两步批准／执行串接成新流程。

根任务最终回归：210 项 hackathon 服务测试全部通过（含本模块全部 47 项，262.336 秒）；原有后端 53 项全部通过（24.888 秒）。HTTP 注册及前端写入测试的剩余差异见 `01-data-risk.md`，这些服务测试结果不代表页面全流程已联通。

共享类型扩展统一见任务 1—3 交接：reference_data、BusinessEvent.details、无任务的账户／材料事件可空关联、退供在途 return_in_transit、组合 candidate_groups。本模块补充 clock_advancer 和回执 kind/record 服务边界，公共类型及 API 文档由任务 0 一次合并；当前没有宣称新增 HTTP 已上线或端到端页面已联调。

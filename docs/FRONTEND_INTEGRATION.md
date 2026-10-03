# v1.2 前后端联调与待处理事项

唯一当前接口依据是魏的 [API Contract v1.2](../API_CONTRACT.md)。后端来自 lanyangyang 分支，本轮对齐提交为 f25bbe1。旧 v0.3 统一运行草案不是现行接口。朱的代码、样例和演示在 zmj 分支维护。

## 当前调用链

~~~mermaid
flowchart LR
    UI["经营总览 / 风险 / 工作台 / 采购模拟"] --> CLIENT["请求与响应校验"]
    CLIENT --> PROXY["前端公开文件白名单代理"]
    PROXY --> API["魏的 FastAPI v1.2"]
    API --> DOMAIN["确定性领域计算"]
    API --> DB["本地 SQLite"]
    API --> DRAFT["本地待执行任务"]
~~~

浏览器联调运行实际后端计算和数据库，不以固定响应代替成功业务结果。模型和外部 ERP 仍未接入，人工记录的回执不能证明外部操作由本系统完成。

默认启动器使用网站目录外的本地数据库；外部 API 模式只转发到指定服务。公开代理限制静态文件和路由，保留查询、请求体、租户头及幂等键；不进行业务计算、金额转换或写请求重试。

## 五类能力

| 能力 | 当前 API 与顺序 |
| --- | --- |
| 滞销核查 | risks → risk detail → investigations → feedback → confirm → replan |
| 调拨 | workbenches/transfer → calculate → save → submit → approve → execute |
| 近效期 | workbenches/expiry-rescue，沿用相同方案状态流 |
| 采购刹车 | workbenches/procurement-brake，沿用相同方案状态流 |
| 采购情景模拟 | simulation-options → 用户核对参数 → retail/simulate |

工作台初值、数量约束和业务结果来自后端。当前资金模拟只支持周期内减少可调整采购数量；结构化参数才是计算依据，request_text 为备注。不能把当前模型能力描述为任意自然语言操作。

## 统一口径

金额使用人民币元，最多两位小数；reduction_pct=20 表示 20%。风险数量按门店商品组合计，不能当作不同商品种类数。每个商品按服务返回单位展示，包装名不构成自动单位换算依据。

实测工作台金额和风险 unit_cost 的 Decimal 值会序列化为十进制字符串，零售汇总金额则为 JSON 数字；unavailable 模拟中的 reduction_pct 也可能回显为字符串。前端只在这些明确边界接受规范十进制文本，不缩放金额、不把空值变成零。魏需将实际序列化类型同步到契约与 OpenAPI，避免其他客户端按纯 number 接入时失败。

account.balance、inventory.cost、purchase_commitments.amount 分别来自账户、库存成本和已确认付款计划。调拨只改变位置。模拟采购支出减少不是现金到账，期末库存变化不是利润。真实资料缺项保留 null 或 unavailable，不补合成数字。

方案必须使用实际返回的 ID、current_version 和状态。审批通过只允许进入后续任务步骤；execute 返回 draft_pending_external_execution。received/completed 是人工记录状态，不代表系统已经向 ERP 发出操作。

## 魏需要继续处理

1. **审批与执行并发前置条件。** 当前客户端可检查最新版本、回执关联并携带幂等键，但服务端请求尚无 expected_version 的原子比较。读取后、提交前另一操作者修改方案时，仍需在事务内拒绝过期操作，并返回可恢复的冲突状态。
2. **编辑与旧方案失效。** 用户已经改动或重新 calculate，但尚未 save 时，旧方案可能仍保持可审批状态。应由后端定义草稿、计算输入摘要、已保存版本和当前方案之间的关系，统一失效规则；前端禁用按钮不能替代该约束。
3. **身份与权限。** X-Tenant-Id 是分区参数，不是认证。actor_id 默认值也不是登录身份。正式接入需要服务端识别用户、租户及角色，校验读取、审批、任务状态修改的权限。
4. **反馈草稿可靠性。** 当前反馈处理包含规则/固定草稿，不能宣称模型理解了原文。前端已要求人工核对；后端需保留原文证据、结构校验、未知及冲突，明确后续真实模型接入和失败路径。
5. **真实数据与执行回执。** 当前内置种子可跑通本地流程；上传记录不等于经营数据更新。真实采购、在途、批次、付款计划和需求口径，以及 ERP 回执、重复任务和部分完成恢复，仍需明确和验证。
6. **接口维护。** 字段或语义改变先更新根契约。冻结各模块可编辑字段、来源与缺项、金额及日期口径；朱再同步表单、响应校验、样例、测试和演示。

上述是尚未解决的服务端边界，不通过前端补算或伪造成功状态规避。当前存在可以完成的本地流程，但下述并发缺陷仍阻止稳定验收，不能直接开放给生产租户。

## 当前联调阻塞：并发读取返回 HTTP 500

在 f25bbe1 的实际后端、Python 3.13.2 / SQLite 3.45.3 上，今日待办并发读取 `/proposals`、`/execution-tasks`、`/work-items` 时出现 HTTP 500。失败发生在读取方案或风险记录时；日志包括 `comparison_json` / `missing_fields_json` 读取为 null 后传给 `json.loads`，以及 `sqlite3.InterfaceError: bad parameter or other API misuse`。

独立复现使用全新临时数据库，初始化种子后没有任何写接口或 reset 调用，不运行浏览器。先串行读取 45 次全部成功，再以 9 个线程读取 150 次，本次记录有 85 次 HTTP 500。已排除浏览器测试切换用例时重置数据库这一原因。错误发生于后端共享连接的并发读取路径，具体连接、语句缓存与线程生命周期需要魏从数据访问层定位；尚未把某一个实现原因认定为最终根因。

在仓库根目录执行：

```powershell
.\.venv\Scripts\python.exe scripts\reproduce_backend_concurrency.py
```

脚本只启动并关闭自己的本地后端，动态分配端口，使用并清理独立临时库；不会访问用户日常数据库。输出串行/并发统计及错误摘要，存在失败时退出码为 1。失败次数可能随线程调度变化。前端和测试保留实际并发读取，不增加重试或固定成功响应来掩盖问题；浏览器验收目前保留失败记录。魏修复后应同时重跑该脚本、浏览器全量测试与审批版本冲突检查。

## 下一轮验收

### 朱已完成、可直接对接的前端能力

反馈确认已使用业务表单，提交仍为原有 `confirmed` 对象中的七个字段：factors、current_status、date_interpretation、raw_text、source、evidence_refs、remediation_status。未核实情况保留pending_confirmation/unknown，排除为rejected，明确采信为confirmed；causal_status仍为unknown。额外模型字段仅供查看，不会无审核地随确认提交。魏接入AI时需确认这些语义及日期结构是否继续沿用，变更先更新契约。

方案交接导出只读取已保存的input/calculation/basis，并核对方案ID、current_version、snapshot_id、fact_version及risk_id。旧种子方案只有actions，不足以形成完整交接表；前端会要求先到工作台计算保存。单位未返回时明确标为未提供，不从包装名猜测。下载不调用写接口，不改变审批或执行状态。

下一批请魏提供：模型请求与运行状态、错误/超时/限流、原文证据、输入输出token及费用/币种/计价依据、是否复用缓存、反馈历史查询，以及并发版本冲突响应。当前前端不编造这些字段，也不以规则输出或静态数字代替。反馈核对会话目前只在当前浏览器页面内按risk_id保留，刷新后的历史恢复需要查询接口。

朱新增的 `sample-data/evaluation/` 是离线评测资料，不是运行接口Schema；待AI契约冻结后双方确认映射与判分。真实访谈、成本及“人工＋GPT”对照结果目前未采集。

优先用一条“风险核对 → 调拨测算 → 保存 → 审批 → 任务 → 人工回执”复核版本失效与并发。真实数据、权限、模型和 ERP 逐项接入后分别记录证据，避免用页面测试通过数代替业务收益或模型效果。

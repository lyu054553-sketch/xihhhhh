# 任务框 3 交接：模型、材料、Agent 服务

本轮仅后端库服务实现，未改 API、Store、shared、requirements 或前端。未读取或打印 `.env`、密钥。本轮未调用真实模型服务；全部 HTTP 验证使用显式测试配置和 `httpx.MockTransport`，具体文本／图片模型仍待总集成配置确认。

## 文件与接口

- `backend/hackathon_ai/gateway.py`：现有 `ModelConfig` 的 chat/completions HTTP 适配，无第二套环境配置。支持 DeepSeek/Qwen/MiniMax 的协议路径，能力以已配置模型为准。
- `backend/hackathon_ai/materials.py`：文字／单图提取、严格字段、证据核对和人工字段校验。
- `backend/hackathon_ai/runner.py`：真实 function tool calls，有界只读／计算工具编排。
- `backend/hackathon_ai/service.py`、`__init__.py`：公共 AgentService 实现及同 Store 持久化。
- `tests/hackathon/test_ai_materials.py`、`test_ai_service.py`：低层、服务事务及真实数据／计算服务联测。
- `backend/model_config.py` 沿用原实现，未修改。

```python
from backend.hackathon_ai import AIService, ModelGateway, migrate

with database.transaction() as tx:
    migrate(tx)
agent = AIService(database, facts, calculations, gateway=ModelGateway(model_config))

agent.run(request: dict) -> AgentRun
agent.get_run(run_id: str, *, tenant_id: str, after_sequence: int = 0) -> AgentRun
agent.extract_material(request: dict) -> ExtractionDraft
agent.confirm_material(draft_id: str, request: dict, *, expected_fact_version: int) -> dict
agent.get_draft(draft_id: str, *, tenant_id: str) -> ExtractionDraft
agent.get_material(material_id: str, *, tenant_id: str) -> dict
agent.get_material_image(material_id: str, *, tenant_id: str) -> dict  # mime_type + bytes content
```

构造器无 I/O；`migrate(tx)` 只接受已激活的外层事务。使用原 Store 的 transaction，不另开连接、独立 commit，不复制库存／采购／现金账本。`ha_ai_materials/drafts/runs/events/commands` 仅保存材料、草稿、运行及幂等命令。

HTTP 层需把经过鉴权的 `actor_id`、`tenant_id` 和 `Idempotency-Key` 注入 request 的 `actor_id/idempotency_key`；所有三个写入口都需要它们。标准 request 使用完整 `context`；extract 可用 tenant_id/scenario_id/branch_id/fact_version，通过注入事实服务的 `get_context(tenant_id, scenario_id, branch_id=None, *, tx=None)` 扩展解析。多分支省略 branch_id 时由事实服务拒绝歧义。

材料请求为 `kind=purchase_intent|return_terms`、`text`、`source_name`、可选 `image_data_url`。公共单图只接受 PNG/JPEG base64 data URL，最大 5 MiB，检查解码、签名及尾部；禁止远程图片 URL。文字最多 20,000 字符。图片仍由配置的 vision 模型读取，不降级为假 OCR；无图片模型返回不可用记录，保留材料供人工填写。API multipart 转 data URL、原图鉴权响应由总集成接线。

## 字段及人工确认

`purchase_intent` 白名单：store_id、sku_id、lot_id、product_name、quantity、unit、unit_cost_cny、expected_arrival_date、payment_date、supplier_id。必填除 lot_id/product_name 外的八项。

`return_terms` 白名单：store_id、sku_id、lot_id、supplier_id、quantity、unit、unit_cost_cny、settlement_mode、return_deadline、refund_pct、max_return_qty、freight_fee_cny、restocking_fee_cny、settlement_days、contract_allows_return、requires_supplier_acceptance。必填 supplier_id/sku_id/settlement_mode/return_deadline。

金额为元、最多两位小数；退款比例 `refund_pct` 为 0—100；结算为 cash_refund/payable_credit/exchange，unknown 规范为 null。必填缺项必须在 `accepted_unresolved_fields` 精确列出，发布后仍是 null。未知 ID、不符主数据的单位、供应商与商品批次不匹配、额外字段和越界值直接拒绝。

提取后所有值仍待人工确认，置信度未获得供应商可信度量时为 null；原文位置与数字／ID／唯一主数据名称可核对才保留字段。日期无法逐字核对、营业状态、结算语义及合同布尔值等模型推断保留内部未核验建议，公共字段为 null，保留对应原文供人审，不用脆弱自然语言规则假装核验。

确认与事实发布在同一 Store 事务，失败全部回滚。按租户检查草稿，同一幂等键及内容重放原响应，内容变化报冲突，陈旧事实版本拒绝。调用注入的 `FactService.apply_business_events(tx, [event], expected_fact_version=...)`：

```python
event_type = "material_confirmed"
business_ref = draft_id
receipt_ref = material_id
details = {
    "material_kind": "purchase_intent" or "return_terms",
    "fields": confirmed_public_fields,
    "accepted_unresolved_fields": missing_fields,
}
# scope=tenant_id/scenario_id/branch_id，task_id/proposal_id/proposal_version=None
# known_at/occurred_at=context.as_of，is_demo=context.is_demo，external_write=False
```

事实服务已实现此事件：采购成为 draft_unconfirmed 意向，条款成为确认合同条款。两者均不是订单、实际供应商接受、库存变动或到账。事实版本推进及旧方案失效由事实／执行权威服务处理，AI 不另写业务表。

## Agent、日志与隔离

公共工具仅 `facts_query` 和 `compare_options`；固定请求 context，不允许模型改租户／分支／快照／版本。先真实查询后真实计算，计算服务通过 Protocol 注入，不 import 具体业务模块或复制公式。可调参数限量、目标店、运费、到货／结算天数等；不提供 SQL、代码执行、业务写入、supplier_confirmed 或 packaging_confirmed。

`feedback_material_ids` 仅接受当前租户／分支已经人工确认的材料。恰好一个采购意向反馈时，服务将该 draft_id 作为 `inputs.purchase_intent.intent_id` 固定传给计算服务，由后者从当前 facts 选择已发布意向；不让模型重写业务字段。多个采购意向引用拒绝歧义。确认后使用新 context 可重跑事实查询和计算，未确认材料不能进入工具事实。

事实 query DTO 的可选 `reference_data={tables,target,evaluation_end}` 提供主数据／日历等非 canonical 事实。本模块按注册业务表投影并隐藏 risk_inputs、场景／分支提示、warnings/notes、snapshot 及答案／回放元数据，来源路径转 opaque EVID 引用；不会读取 05/06 目录。合法 `expected_*` 计算字段及稳定业务 ID 保留。模型工具预览全局行内容 60,000 字符、每表 5,000 字符／60 行并注明 `row_coverage.truncated`；完整 FactQueryResult 仍原样传给计算服务。模型不能把部分预览当总量。

`run` 为同步有界执行，可由 HTTP 层放在线程／后台任务；模型 HTTP 调用期间不持数据库事务。默认 HTTP timeout 30 秒、最多一次重试；编排最多 4 步、8 次工具调用、120 秒检查时限。受控 Python handler 必须本身有界（运行时限不会强杀 Python handler）。不设置总费用预算上限。用量取实际 provider usage，费用未知为 null。

事件使用正式枚举 run_started/tool_started/tool_succeeded/tool_failed/needs_input/run_completed/run_failed/run_unavailable；按递增 sequence 保存，支持 after_sequence 轮询。阶段来自真实调用。运行 summary 明示模型草稿，金额以关联计算结果为准；没有程序计算不能标为完成建议，返回 needs_input。HTTP 断网、未配置、鉴权等保留不可用状态与历史，不换成旧答案。

provider reasoning_content/reasoning_details 只在内存内部续轮协议保留；展示文本的 think/thinking/analysis/reasoning 块和中断块、隐藏字段从落库／事件／响应剥离。密钥与 headers 不保存。原图只在材料 BLOB 专用字段及鉴权 getter，普通日志／run/draft 响应仅有材料引用。

## 验证与待集成

使用独立临时数据库与仓库 `.venv`：

```powershell
.venv\Scripts\python.exe -m unittest tests.hackathon.test_ai_materials tests.hackathon.test_ai_service -q
```

验证结果：49 tests，全部通过（仓库 `.venv`，15.979 秒）。覆盖 HTTP 协议／失败／重试上限、当次文本与图片变化、证据／未知商品、有限工具流、合法计算字段与业务 ID；同 Store 迁移回滚、确认原子性、重复确认、租户／版本、刷新和增量事件；真实 RetailFactService + CalculationService 的 S07 联测，确认只生成意向事实且不变库存／PO，确认后按新事实版本与明确意向编号重跑计算，未确认反馈拒绝进入模型事实，真实工具轮转保留 expected_cash_in_cny 等结果，完整事实计算与有限预览分开。

需要总集成：注册迁移和服务图；接四个公共路由、草稿／原图读取扩展；从已确认模型配置构造 Gateway；鉴权／幂等请求注入。共享契约扩展待任务 0 统一：FactQueryResult.reference_data 可选；BusinessEvent.details 可选及材料事件 task_id/proposal_id/proposal_version 可为 null。本模块未改 shared。

运行依赖交由任务 0 统一加入 requirements：`httpx>=0.27,<1`（目前 requirements-dev 已包含）。材料的业务时区严格限定当前 retail-v2 契约支持的 Asia/Shanghai，submitted_at 自身必须带 UTC 偏移；没有实际时区转换需求，不引入额外 IANA 时区数据库依赖，Windows 无需安装 tzdata。

尚未验证：三家实际账户／具体模型的在线文字、视觉、function calling 能力；HTTP／前端完整联调。配置未最终确认前不发起真实模型请求，也不将 MockTransport 测试称为模型连通验证。

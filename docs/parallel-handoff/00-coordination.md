# 任务框 0｜第一阶段交接

状态：`ready_for_parallel`（第一阶段完成；等待“开始总集成”）

日期：2026-10-04

## 修改文件

- `docs/PARALLEL_CONTRACT.md`：发布 `hackathon.v1` 公共契约，覆盖当前实现与计划边界、数据包与七份 XLSX manifest 摘要、事实／风险／候选／材料／运行／批准任务／回放核算结构、错误与版本规则、事务／迁移归属、服务协议、HTTP 路径、前端组件生命周期及事件名。
- `backend/hackathon_shared.py`：导出模块 1—4 可共同依赖的 DTO 类型、服务 `Protocol`、`HackathonServices` 注入容器，以及 `install_services` / `get_services`。
- `backend/api.py`：将唯一现有 Store 暴露为 `app.state.store`，并安装带共享数据库、等待各模块逐步填充服务的 `HackathonServices`。
- `backend/store.py`：新增 `Store.transaction()`，通过现有 `RLock` 和连接提供共享外层事务；嵌套 Store 操作加入当前事务，外层统一提交或回滚。
- `assets/hackathon/shared/api-client.js`：提供同源 `/api/v1` 真实 HTTP 适配器、结构化 `ApiError` 和显式 fixture client；HTTP 错误不会回退到 fixture。
- `docs/parallel-handoff/00-coordination.md`：本交接记录。

## 导出协议与已完成行为

- `backend.hackathon_shared` 的 `FactContext`、`FactQuery`、`FactQueryResult`、`RiskAssessment`、`ProposalComparison`、`ExtractionDraft`、`AgentRun`、`BusinessEvent`、`ApprovalTaskResult`、`ReplayResult` 等类型已提供。
- `FactService`、`CalculationService`、`AgentService`、`ExecutionService`、`TransactionProvider` 明确模块 1—4 边界；风险属于模块 1，处置比较属于模块 2；无业务模块之间的导入依赖。
- 服务容器安装位置为 `app.state.hackathon_services`。旧 `risk_id` 映射职责归模块 1，禁止按名称猜映射。
- 新 API 路由和整包加载仍标记为计划，未谎称已存在。`API_CONTRACT.md` 旧接口保持兼容，实际 `/api/v1` 接线在第二阶段处理。
- 前端 API client 默认 HTTP；只有显式 `mode: "fixture"` 才读开发样例。任务 5／6 的 mount、卸载、上下文注入和事件协议已在公共契约冻结。

## 验证命令与结果

- `python3 -m py_compile backend/hackathon_shared.py backend/store.py backend/api.py`：通过。
- `node --check assets/hackathon/shared/api-client.js`：通过。
- 内联 Python 读取 `manifest.json`，对七个 XLSX 核对 SHA-256、字节数和各 sheet 非空数据行数：全部通过。
- 从公共契约提取 25 个 `json` 代码块并用 `json.loads` 解析：全部通过；25 个响应样例均标明 `fixture_only`。
- 内存 SQLite 手工检查 `Store.transaction()` 正常提交、事务内嵌套 `Store.audit()`、异常时整组回滚：通过。
- Node 手工检查 HTTP client 同源路由和租户头、显式 fixture 缺项时返回 `fixture_missing`：通过。
- 未运行完整 pytest／浏览器验收；模块 1—6 和新路由尚未接线，故没有端到端结果可报告。

## 待总集成接线

- 目前 `backend.api` 仍按旧模块级方式创建 Store 并 seed；第二阶段需在首次加载新事实前按 `backend/store.Store` 单连接注册模块 1、3、4 迁移，再构造并调用 `install_services(app, services)`；模块 2 无迁移。
- 注册契约中 `/api/v1/hackathon/*` 计划路由，将服务方法注入 FastAPI；让模块 4 的批准／任务／回执与模块 1 库存更新处于同一事务。
- 在 `index.html` 加载共享 API client 和任务 5／6 组件，在旧页面入口挂载并接入导航事件；阶段一未更改旧 render、主页面或现有路由。
- 以真实模块交付和记录完成 S01，再联调 S07、S06、S05、S09；S08／S10 验证变更与缺项。

## 未验证／剩余条件

- 当前没有模块 1—6 的服务实现接线，未验证新端到端流程、模型调用、真实材料识别、数据库回放或浏览器页面。
- 尚未确认本机模型 Key 是否有效；公共契约不含 Key 或外部发送能力。
- `sample-data/retail-v2/xlsx/` 是本机被 `.gitignore` 排除的文件；在其他 checkout 并行前需确认整个数据包已同步。

# 任务框 5｜决策前端交接

日期：2026-10-04  
依据：`docs/PARALLEL_CONTRACT.md`（`hackathon.v1`，`ready_for_parallel`）

## 修改文件

- `assets/hackathon/decision/decision-workbench.mjs`
- `assets/hackathon/decision/decision-workbench.css`
- `assets/hackathon/decision/preview.html`
- `assets/hackathon/decision/preview-entry.mjs`
- `assets/hackathon/decision/preview-fixtures.mjs`
- `tests/hackathon/frontend-decision/decision-workbench.test.mjs`
- `docs/parallel-handoff/05-decision-frontend.md`

实现仅在任务分配的前端目录和本交接文件内；没有改主页面入口、共享样式或后端文件。

## 挂载接口与接线

模块导出 `mount(container, options)`，并在浏览器注册 `window.HackathonDecision.mount`。宿主先加载 `assets/hackathon/shared/api-client.js` 与本模块 CSS，再挂载：

```js
const api = window.HackathonApiClient.createApiClient({ baseUrl, tenantId });
const decision = window.HackathonDecision.mount(container, {
  api,
  navigate: (route, context) => { /* 由宿主处理导航 */ },
  context: {
    tenantId, scenarioId, branchId, snapshotId, asOf,
    dataVersion, factVersion, isDemo, sourceRefs, missingFields,
    area, horizonStart, horizonEnd, assumptionIds,
    storeId, skuId, lotId, actorId, proposalId, proposalVersion, taskId,
    businessInputs,
  },
});
// 宿主卸载：decision.destroy();
// 场景变化：decision.updateContext(nextContext);
```

返回对象提供 `destroy()` 与 `updateContext(nextContext)`。组件只在宿主容器内创建和移除自己的 `.d-root`，卸载时中止请求、移除事件监听、停止 Agent 轮询并释放图片预览 URL。输入与导航相关事件以冒泡 CustomEvent 发出：`hackathon:context-change`、`hackathon:proposal-confirmed`、`hackathon:run-updated`、`hackathon:error`。

方案确认成功后调用 `navigate("execution-followup", context)`；返回按钮调用 `navigate("decision-entry", context)`。宿主需将这两个 route 名映射到现有入口。预览页在本目录独立创建共享 API 客户端的显式 fixture 模式，页面标示开发预览；缺 fixture 会显示错误，不会回退到假数据。

## 已实现行为

- 风险区分别展示慢销与临期命中、风险库存成本去重和缺项；按商品、门店、批次切换事实范围。
- 调拨、采购、促销、退供、现金区展示服务返回的候选、不可用原因、金额、数量、单位、现金流时点与来源。候选按服务的可行状态显示；前端不推导金额或库存结果。现金区对照同次比较里的不行动基线与所选候选，并将预计流入、已知实收及执行费用分开。
- 文本或单张 PNG/JPG（最多 5 MB）材料提取显示原文/图片、字段证据、置信度、缺项及未匹配实体。字段可手改；缺项需补齐或明确接受保留未知，未匹配实体必须先处理；没有服务草稿时不能确认。没有提供 PDF 上传选项。
- Agent 过程由用户显式启动，展示服务返回的事件、失败、待补字段和依据，并按真实 `run_id` 轮询；没有运行事件时不生成模拟进度。
- 方案字段变化立即标为过期并锁定旧结果确认；确认要求最新比较、所选候选可行且页面非忙碌。确认先保存候选版本，再调用共享客户端的 `confirmProposal`，两个写请求分别带幂等键；成功后发事件并进入执行跟进。
- 加载、空结果、缺数据、接口错误、模型不可用、版本冲突及禁止确认状态均有对应提示。样式限定 `.d-root`，包含窄屏布局和键盘可操作的原生表单控件。

## 验证

- `node --check assets/hackathon/decision/decision-workbench.mjs`：通过。
- `node --check assets/hackathon/decision/preview-fixtures.mjs`：通过。
- `node --check assets/hackathon/decision/preview-entry.mjs`：通过。
- `node --test tests/hackathon/frontend-decision/decision-workbench.test.mjs`：7 项通过，0 失败。
- 静态 CSS 选择器扫描：所有普通规则均以 `.d-root` 开头（排除 `@media` 与 keyframes 帧选择器）；未发现未限定的全局选择器。
- 浏览器视觉验证未完成：本机回环 HTTP 服务在沙箱中以 `PermissionError: Operation not permitted` 失败；Chromium 与 Firefox headless 均在截图前退出（134），CUA 初始化报告 `sandbox-exec: unbound variable: TIOCSTI`。因此窄屏视觉效果尚未在真实浏览器截图中核验。
- 未做端到端真实 API 验证。公共契约明确标注 `/hackathon/*` 为计划路由；当前 `backend/api.py` 未注册这些路径，完整服务接线由集成阶段负责。

## 待集成处理与契约限制

1. 本次集成准备已把两模块挂载上下文统一为 camelCase，并补全 `dataVersion/isDemo/actorId/proposalVersion/sourceRefs/missingFields` 等字段。事实查询和写操作 body 仍按 snake_case。
2. `compareProposals` 现在传入 action-keyed `business_inputs`；宿主或组件输入可通过 `context.businessInputs` 或 `input.business_inputs` 提供，支持调拨数量／路线费用、促销组合与阶段价格、退供数量／结算和采购数量／交期等结构。公共字段及校验边界见 `docs/PARALLEL_CONTRACT.md` 第 7 节。
3. 候选映射现在读取 `inventory_changes[]` 并显示调出／调入门店的执行前后库存。该值必须由后端比较响应提供；前端不根据候选量计算库存。
4. 候选现金 DTO 未定义现金流出合计或净额。UI 保留未知，不由预计流入减费用来构造净现金。
5. 共享 API 客户端现支持带完整 `FactContext` 和幂等键的 `extractMaterial(input, key)`，以及 `confirmMaterial(draftId, body, key)`；组件统一调用 helper，不再绕开客户端自行发送 multipart。决策预览的写操作已禁用，fixture 不提供保存、确认、材料确认或 Agent 启动成功响应。
6. 服务端 `/hackathon/*` 路由尚未在 `backend/api.py` 注册；真实服务、模型可用性、版本冲突和材料存储流程仍未端到端核实。前端已接入主工作台 `decision-entry` 路由；通过模块切换页可在原版外壳中查看显式只读 fixture，后端到齐后再做真实联调。

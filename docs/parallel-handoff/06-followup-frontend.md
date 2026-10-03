# 任务框 6｜工作台、三渠道与经营结果前端交接

日期：2026-10-04

状态：前端按 `hackathon.v1` 接口实现；等待后端路由注册及总集成挂载。

## 修改文件

- `assets/hackathon/followup/followup.js`
- `assets/hackathon/followup/followup.css`
- `assets/hackathon/followup/preview.html`
- `tests/hackathon/frontend-followup/followup.test.cjs`
- `docs/parallel-handoff/06-followup-frontend.md`

未改动 `index.html`、旧工作台／导航文件、全局 CSS 或其他任务的归属文件。

## 导出组件与生命周期

脚本导出 `window.HackathonFollowup.mount(container, options)`，CommonJS 可通过 `require()` 使用同一组件。正式接线传入共享 API client、`navigate(route, context)` 和统一上下文：

```js
const mounted = window.HackathonFollowup.mount(container, {
  api: window.HackathonApiClient.createApiClient({ tenantId: 'demo' }),
  navigate: (route, context) => window.dispatchEvent(
    new CustomEvent('app:navigate', { detail: { route, context } }),
  ),
  context: {
    tenantId: 'demo', scenarioId: 'S01', branchId: 'transfer_80',
    snapshotId: 'SNAP-20261003-BASE', asOf: '2026-10-03T09:30:00+08:00',
    dataVersion: 'retail-v2.1', factVersion: 1, isDemo: true,
    sourceRefs: [], missingFields: [], area: 'transfer',
    horizonStart: '2026-10-03', horizonEnd: '2026-10-25', assumptionIds: [],
    riskId: null, storeId: 'ST-001',
    skuId: 'SKU-001', lotId: 'LOT-001-001', actorId: 'manager-demo',
    proposalId: null, proposalVersion: null, taskId: null,
  },
});

await mounted.updateContext({ scenarioId: 'S09', branchId: 'partial_transfer' });
mounted.destroy();
```

`mount()` 返回 `destroy()`、`updateContext(nextContext)`，并保留 `refresh()`、`getState()` 供宿主和开发预览使用。组件只操作自己创建的子树，监听器在 `destroy()` 时移除。样式和事件处理均限于组件根节点。

组件在容器上派发可冒泡事件：`hackathon:context-change`、`hackathon:proposal-confirmed`、`hackathon:task-updated`、`hackathon:error`；事件详情按公共契约携带当前 `context` 及对应字段。

## 公共 API 适配与已实现行为

- 读取调用共享 client 的 `listTasks()`、`listProposals()`、`getOverview()`、`getTask()`、`getAccounting()`；案例视图在可用 `case_id` 时调用 `getCase()`。待确认方案、执行任务和首页汇总独立读取；首页不再依赖任务列表内嵌 overview。任务和核算结果映射为只读视图模型，业务事件、来源和版本保留后端值。HTTP 错误显示错误／重试状态并派发 `hackathon:error`，不会回退到示例数据。
- 方案确认一次调用 `confirmProposal(proposalId, body, idempotencyKey)`，请求带方案版本、事实版本、快照 ID、候选项及任务分派；成功后进入跟进分组并派发确认事件。
- 回执、异常、价格生效及供应商回复／条款确认通过 `recordBusinessEvents()`，带任务／方案版本、事件 ID、凭据、数量单位、发生和获知时间。通知、接手、采购结果提交、促销发布、邮件草稿／发送通过 `recordChannelAction()`，带 `is_demo: true`、`external_write: false`，不触发外部消息发送。写入成功后重新读取服务端状态，不乐观修改业务结果。
- 导出 `mapFollowupDisplay(task, accounting)`：保留原始任务枚举、进度、异常和关闭原因，投影 `待执行／执行中／已完成` 与 `待核算／核算中／已核算`；部分数量不能显示为完成，取消事项进入独立归档分组。
- 工作台互斥展示待评估、待确认、审批后跟进、已完成及已归档。跟进保留签收、部分执行、销售、现金到账及未结款状态。S01/S09 示例由事件计算结果；总览读取账户、库存占用、待关注库存、未来 30 天已确认采购付款和门店库存资金表，缺值显示未知。
- 本地预览由 `preview: { enabled: true }` 明确启用，显示 S01/S09/S07/S06/S05 前端夹具并禁用写入。共享 client 的 `mode: 'fixture'` 会显示开发预览标识。生产 HTTP 请求失败时不会切入夹具。

## 验证

- `node --check assets/hackathon/followup/followup.js`：通过。
- `node --test tests/hackathon/frontend-followup/followup.test.cjs`：9 项通过，覆盖分组／状态映射、S01/S09 事件汇总、未知值、四张总览卡、只读预览、内容转义、共享 API 读取、版本化业务事件、渠道安全标记、原子确认、生命周期事件及 HTTP 错误不回退。
- CSS 选择器范围检查及括号平衡检查：通过；选择器都以 `[data-hackathon-followup]` 为范围。

## 总集成接线与待完成条件

- 公共契约已发布并标记 `ready_for_parallel`。`assets/hackathon/shared/api-client.js` 已有本组件使用的方法；但 `backend/api.py` 当前没有注册 `/hackathon/tasks`、`/hackathon/accounting`、`/hackathon/cases` 和确认／事件／渠道动作路由。契约标为计划的路由须由后端集成后才能真实联调；失败时组件明确显示错误。
- 本次集成准备新增共享 client 的 `listProposals()` 与 `getOverview()`，跟进模块已分别消费待确认方案与首页汇总。后端仍需实现公共契约中标为计划的对应路由。
- 前端现已接入主工作台 `execution-followup` 路由，复用原版导航、字体、绿色按钮与卡片间距；集成样式限定在此路由内。`assets/hackathon/preview.html` 可切换两个嵌入原版外壳的只读 fixture 预览。
- 服务端 `/hackathon/*` 路由尚待后端注册，因此未完成真实后端／数据库刷新恢复联调。当前环境的 CUA 初始化异常，无法提供截图级浏览器验证；可通过本地预览入口直接检查页面。不要给渠道动作接入真实消息平台。

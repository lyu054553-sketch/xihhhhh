# 任务框 6｜经营总览现金机会区块交接

日期：2026-10-04

状态：现金机会区块已完成并可由总集成挂载；当前尚未接入旧经营总览页面。

本轮按 `docs/parallel-prompts/06-followup-frontend.md` 的独占文件范围开发。此前工作台／跟进完整页面已从当前主应用删除；本次只交付用户要求加入经营总览的现金机会和到账核对区块，不恢复被移除的整套重复模块。

## 修改文件

- `assets/hackathon/followup/overview-cash-opportunity.js`
- `assets/hackathon/followup/overview-cash-opportunity.css`
- `assets/hackathon/followup/overview-cash-opportunity-preview.html`
- `tests/hackathon/frontend-followup/overview-cash-opportunity.test.cjs`
- `docs/parallel-handoff/06-followup-frontend.md`

未修改 `index.html`、`app.js`、`retail-app.js`、`retail-workbenches.js` 或全局 CSS。旧页面的正式挂载由总集成完成。

## 导出组件与接线方式

浏览器导出 `window.HackathonCashOpportunity.mount(container, options)`；Node 可用 CommonJS 导入。传入共享 API client、导航回调和与工作台相同的场景上下文：

```js
const mounted = window.HackathonCashOpportunity.mount(
  document.querySelector("#cash-opportunity-root"),
  {
    api, // getOverview / listTasks / listProposals
    navigate: (route, context) => { /* 接入宿主导航 */ },
    context: {
      tenantId: "hackathon-demo", scenarioId: "S01", branchId: "transfer_80",
      snapshotId: "SNAP-20261003-BASE", asOf: "2026-10-03T09:30:00+08:00",
      dataVersion: "retail-v2.1", factVersion: 1, isDemo: true,
      storeId: "all",
    },
  },
);

await mounted.updateContext({ storeId: "ST-001" });
await mounted.refresh();
mounted.destroy();
```

总集成需要：

1. 在旧经营总览 `#retail-overview` 内创建专用挂载点，位置放在现有四张核心卡之前；不要清空或替换原总览子树。
2. 在页面载入本组件 CSS 和 JS，再注入共享 API。接口使用 `getOverview`、`listTasks`、`listProposals`，查询固定同一 `scenario_id/branch_id/snapshot_id/as_of/data_version/fact_version`。门店筛选同步到 `storeId`。
3. 注入导航，将 `execution-followup` 路由映射到当前有效的方案／执行详情页面，并传入事项 ID、方案版本与任务 ID。
4. 总览筛选或场景时点变化时调用 `updateContext()`；路由销毁时调用 `destroy()`。

当前工作树中的 `assets/hackathon/shared/api-client.js` 已删除，历史契约里描述的适配器不在当前源码中。总集成需重新注入实现上述三个只读方法的共享 client，或将现有统一 API 调用封装成该接口；本组件不另起 HTTP 连接。

## 已实现行为与金额口径

- 从同一快照并行读取经营总览、执行任务及待审批方案；数据由接口失败时显示错误和重试，不切换为预览 fixture。
- “本周预计可释放现金”只聚合活跃、已批准任务中的 `candidate_calculation.cash_flow[]` 预计现金流入，且 `expected_at` 落在场景时点所在日历周的剩余时间内。现金方向、金额或日期缺失的任务不填 0，会在已知金额旁标明未计入项；没有任何已知值时显示“—”。
- 待审批方案单独显示，金额（若接口提供）明确标为未确认，不混入已批准预测。执行详情的预计回款使用服务端核算；实际到账只读取 `accounting.actual_cash_cny/actual_cash_in_cny`，保留 0 与 null 的区别。
- “查看金额依据”展开任务、方案版本、金额、状态和来源；“导出处置清单”下载 CSV；下方分别显示优先事项和最近一条有到账结果的预计／实际对比，可跳转到对应任务或方案。
- 组件只操作自己创建的 DOM 子树，事件监听器随 `destroy()` 移除。CSS 全部由 `[data-hackathon-cash-opportunity]` 限定，支持窄屏布局。
- `preview.html` 显示醒目的“开发预览 · 本地 fixture”提示。预览内 38 万／22 万仅用于复现截图的排版，不是经营数据，也不会作为接口故障的回退内容。

四张核心卡、经营图表、门店库存资金表及原有筛选仍由旧总览页面渲染；本组件不覆盖这些内容。截图级正式页面效果要等总集成挂载后才能验收。

## 验证

- `node --check assets/hackathon/followup/overview-cash-opportunity.js`：通过。
- `node --test tests/hackathon/frontend-followup/overview-cash-opportunity.test.cjs`：9 项通过，覆盖周区间计算口径、已批准与待审批分离、未知值、门店筛选、同快照 API 注入、导航上下文、CSV 导出以及接口失败／快照错位不回退。
- `git diff --check`：通过；CSS 选择器范围检查：通过，均限制在 `[data-hackathon-cash-opportunity]`。
- 未通过共享 API 和正式宿主页做 HTTP／数据库刷新联调；本轮没有改后端或使用项目共享数据库。已尝试 CUA 与 Playwright 截图验收：CUA 初始化因 `TIOCSTI` 环境错误退出，Playwright 内置 Chromium `SIGABRT`，所以桌面／窄屏截图未能目视确认；开发预览 HTML 已提供给集成者复查。

## 追加修复：工作台数量字段（2026-10-04）

根据用户明确授权，将本次修复范围扩展到 app.js、retail-workbenches.js 和 backend/store.py。浏览器 FormData 会把数字输入序列化成字符串，曾导致读取旧工作台草稿时数量整数字段校验失败。

- app.js 和 retail-workbenches.js 在暂存及发送表单数据前，把有效的 input[type=number] 值转为数字；日期、门店 ID、空值等继续保留原值。
- backend/store.py 保留旧草稿兼容：读取仅保存为 ASCII 数字字符串的数量字段时先转整数，再按原有范围校验；不放宽小数、负数、布尔值或超范围数量。
- 验证：node --check app.js、node --check retail-workbenches.js、git diff --check 通过；./.venv/bin/python -m unittest tests.test_workbenches 7 项通过；隔离临时数据库 API 检查确认字符串数量 41 写入后归一为整数，历史字符串 42 草稿仍可经 GET 工作台读取；Node 表单模拟确认输入和 API JSON 中的 quantity 均为 number。
- 当前共享服务只读复测：18765 代理的 /api/v1/health、三种 /api/v1/workbenches/* 和页面初始化所需主要接口均返回 200。未对共享服务或其数据库执行写操作。浏览器自动化测试未能运行：本地 .venv 未安装 Playwright；因此未做目视页面验收。

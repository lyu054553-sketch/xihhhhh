# v1.2 前端工作流验证记录

日期：2026-10-03。分支：zmj。接口及后端基准：魏 lanyangyang 的 f25bbe1，FastAPI 1.2.0。此记录对应在 1a729e0 之后新增的反馈核查、业务摘要、方案交接导出与评测工具。

## 本轮实际结果

| 验证 | 结果与范围 |
| --- | --- |
| JavaScript 全套 | **95/95通过**；请求、契约、样例、反馈核对、交接导出及业务摘要 |
| 样例与代理 | **27/27通过**：sample_data 14项、frontend_server 13项 |
| 对照评测工具 | **20/20通过**；配对、缺测、失败、成本精度、证据要求及24条反馈参考结构 |
| 真实后端浏览器全套 | **27项：26通过，1 error**；23.256秒，未通过全量验收 |
| 失败用例 | test_action_queue_opens_the_returned_workbench_and_risk |
| 实际HTTP错误 | 该用例读取 /proposals 与 /work-items 均返回500，今日待办标签因此未渲染 |
| 数据生成 | sample-data/generate.py --check通过，原输入包仍与后端种子一致 |
| 静态检查 | node --check app.js、git diff --check通过 |
| 页面检查 | 已保存调拨工作台及反馈表单截图目视检查；390px反馈表单无页面水平溢出 |

样例、代理和最初18项评测曾合并执行45项通过；评测补充2项后单独执行20项通过，上表不重复计数。最后仅将缺项名称归入共享中文标签表，导出与摘要相关31项已再次通过。

## 新增功能的验证方式

浏览器测试运行独立实际FastAPI进程、临时SQLite、随机本地端口及前端代理。成功业务结果来自后端，不用固定响应冒充计算。每例只重置自有临时数据库，不打开日常数据库。

- 反馈核查：原文只读，默认未知不变成已确认事实；人工更正/排除、日期范围及证据按既有字段提交。切换风险后不带入另一门店原文；返回时恢复该风险的核查输入。修改原文后必须先生成新版本，修改核查内容后需重新勾选确认。
- 业务摘要：三类工作台直接展示返回的库存变化、处置分配、付款压力与现金缺项；不根据输入重新计算结果，不从商品包装猜测单位。
- 方案交接：实际后端保存后下载CSV与JSON，核对方案编号、版本、数量、状态和说明。下载过程没有业务POST；未保存修改、计算未保存、不完整种子方案及过期版本不能导出。
- 读取期间版本变化：浏览器先读方案，测试暂停工作台GET；第二客户端向真实后端保存新版本，再放行真实GET。界面拒绝导出旧版本，没有替换成功响应。这是客户端核对，仍不等于服务端原子并发控制。
- 原有流程：计算、保存、提交、审批、待执行任务、人工回执、跨页写入锁、采购预览与模拟、错误和空租户边界继续回归。
- 离线评测：空CSV实际输出no_observations；缺测、未执行和失败保持可见。测试里的人工观测仅为工具校验，不是用户或模型实测成绩。

## 仍阻塞稳定验收的后端问题

本轮浏览器失败发生在第一例行动队列加载：当次reset已同步结束，尚未有前一例页面请求。并发GET记录到：

- /proposals：api.py:806 → api.py:555 → store.py:309，sqlite3.InterfaceError: bad parameter or other API misuse。
- /work-items：api.py:883，TypeError: 'NoneType' object is not subscriptable。

上一轮独立复现使用全新临时库，没有reset、写接口或浏览器：串行45/45成功，9线程并发150次中85次HTTP500。次数随调度变化。证据指向后端共享数据库连接的并发访问路径，最终根因及修复需魏确认；前端未串行化读取、自动重试或跳过用例来掩盖失败。

```powershell
.\.venv\Scripts\python.exe scripts\reproduce_backend_concurrency.py
```

魏修复后需重跑独立复现及浏览器全套。前端单元测试通过、部分操作链成功和截图均不能代替完整验收。backend/、根API_CONTRACT.md及requirements.txt保持与f25bbe1一致。

## 复现环境与证据边界

Windows、Python 3.13.2、SQLite 3.45.3、Node.js 24.14.0、Chromium 148。本轮临时通过PYTHONPATH使用本机全局Playwright；规范环境应按[测试说明](../tests/README.md)安装requirements-dev.txt和Chromium。测试只关闭自身启动的服务。

现有docs/demo-recording/live-flow.webm和PPT来自上一轮v1.2迁移，未冒充本轮新界面实录。录像使用实际后端、合成数据和合成人工回执，不表示真实模型、ERP操作或客户收益，也不是赛事要求的2—5分钟MP4成片。

本轮没有新增运行时依赖、模型请求或真实业务收益。真实AI结构、证据、token及费用记录、反馈历史、服务端expected_version、编辑与旧方案失效、权限及外部执行仍需魏提供并单独验收。详见[前后端对接说明](FRONTEND_INTEGRATION.md)、[用户验证](USER_VALIDATION.md)和[赛事检查表](COMPETITION_CHECKLIST.md)。

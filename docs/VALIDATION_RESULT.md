# v1.2 联调验证记录

日期：2026-10-03。分支：zmj。接口基准：魏 lanyangyang 的 f25bbe1，根目录 API_CONTRACT.md 与 FastAPI 1.2.0。此前 v0.3 夹具测试及录像不再作为本轮验证证据。

## 本轮证据范围

浏览器测试启动独立的实际 FastAPI 进程与临时 SQLite，再通过前端公开文件白名单代理访问。成功业务响应来自后端计算和数据库，测试没有使用旧统一运行接口夹具。模拟数据仍是合成种子，没有真实模型请求或外部 ERP 写入。

本轮测试包含：

- 经营总览、来源、元金额及门店数据。
- 三个工作台的真实计算、无效约束、保存与方案状态。
- 提交、人工审批、幂等键、待执行任务和人工回执。
- 反馈原文、人工核对、事实确认及旧方案重算。
- 模拟参数预览、确认后请求、修改失效、真实结果与 unavailable。
- 代理路由与文件范围、请求头和查询透传、422 等错误保持。
- 移动导航、合成输入哈希与数据库隔离。

## 已记录的单项结果

| 验证 | 实际结果 |
| --- | --- |
| JavaScript 请求、v1.2 契约与输入清单 | 44/44 通过 |
| 后端与样例测试（acceptance、workbenches、teacher_baseline、retail、sample_data） | 62/62 通过，22.975 秒；其中样例14项与下行是同一组，不重复计数 |
| tests.test_sample_data | 14 项通过，8.476 秒 |
| sample-data/generate.py --check | 通过，与当前后端输入种子一致 |
| 样例测试范围 | 50店输入引用、元/比例单位、CSV/JSON、哈希、重复生成、用户数据库隔离、零减量与全减量边界 |
| HTML / PowerPoint | 8页生成完成，PowerPoint形状边界与讲稿通过；HTML在1440/390像素逐页无横向溢出 |
| tests.test_frontend_server | 13/13 通过，9.844 秒 |
| tests.test_frontend_browser 最后一次全量执行 | **20 项：19 通过，1 失败**，17.394 秒；退出码 1 |
| 浏览器失败用例 | `test_calculated_but_unsaved_input_cannot_approve_the_older_proposal` 在今日待办读取阶段收到实际后端 HTTP 500，未获得可操作方案 |
| 独立后端并发复现 | 全新临时库，无 reset、无写接口；串行 45/45 成功；9 线程并发 150 次中 85 次 HTTP 500，退出码 1 |

启动器检查与实际启动均已验证：本地首页与实际经营接口返回200，数据库和后端源码不能从公开前端访问；外部API模式、端口占用退出、自有进程关闭及无副作用的 -Check 通过。node --check app.js、样例生成校验及 git diff --check 通过。

完整复现命令见[测试说明](../tests/README.md)。不能把单项通过或一次完整实录表述为本轮全量验收已通过。backend/ 和根 API_CONTRACT.md 保持与魏的 f25bbe1 完全一致；本轮没有在前端补算或改写后端规则来消除失败。

## 后端并发阻塞的独立证据

Python 3.13.2 / SQLite 3.45.3，FastAPI 版本 1.2.0。`/proposals`、`/work-items` 的日志包含风险 JSON 字段为 null 时的 TypeError，以及 `sqlite3.InterfaceError: bad parameter or other API misuse`。独立复现没有前一个浏览器测试、数据库重置或写请求，串行读取正常；问题仍需魏从数据库连接和线程访问层定位与修复。

```powershell
.\.venv\Scripts\python.exe scripts\reproduce_backend_concurrency.py
```

前端保留并发读取并明确展示服务错误，没有通过串行化客户端、自动重试、跳过用例或静态业务结果让验收转绿。最小复现及处理建议见[前后端对接说明](FRONTEND_INTEGRATION.md#当前联调阻塞并发读取返回-http-500)。

## 环境与复现

使用 Windows、Python 3.13.2、Node.js 24.14.0 与 Chromium 148。规范复现方式是在项目虚拟环境安装 requirements-dev.txt 和 Playwright Chromium。本轮浏览器测试临时通过 PYTHONPATH 使用本机全局 Python 3.13 的 Playwright；幻灯片使用全局 python-pptx 和已有 Chromium。不声称项目虚拟环境已经独立安装这些工具。

测试使用临时数据库与随机本地端口；只关闭自己启动的进程。样例导出为读取后端种子而单独创建并关闭临时数据库，不访问日常库存数据库。

## 演示证据与限制

本轮录像为 live-flow：真实浏览器 → 前端代理 → 本地实际后端 → 临时数据库。它记录了一次成功完成的流程；最后一次全量运行仍有上述并发失败。数据和人工回执均为合成；不能证明客户收益、模型理解、外部出库或采购调整。

仍需单独验证：审批 expected_version 并发前置条件、编辑/计算未保存时旧方案失效、身份与权限、真实数据更新、模型质量/成本、真实执行与部分完成恢复。详见[对接说明](FRONTEND_INTEGRATION.md)。前端和本地流程通过不消除这些限制。

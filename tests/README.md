# 验证前端交付

在仓库根目录执行（Node.js 18+、Python 3.10+）：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m playwright install chromium
node --test tests/test_frontend_api.mjs tests/test_data_center.mjs
.\.venv\Scripts\python -m unittest discover -s tests -v
```

客户端测试验证错误归一化、写入失败不重试、超时和请求版本隔离。每个浏览器用例单独启动真实 FastAPI、临时 SQLite 数据库与随机本地端口，避免前一用例未结束的服务端请求影响下一用例；共享浏览器进程但不共享页面、存储或 API。不会打开、清除或覆盖日常运行的数据库。测试结束自动关闭自身进程并清理临时文件。

浏览器验收覆盖五个 Agent 入口、反馈人工确认、处置测算与审批到执行草稿、请求竞态、草稿写入顺序、断网/空数据、重置权限与移动端。模拟网络失败、空数组和延迟响应的用例仅在浏览器拦截对应请求，其余流程由真实 API 返回结果。

这些测试不证明模型已接入或 ERP 已执行；当前服务提供规则计算和执行草稿，模型调用记录、外部回执与数据库并发保证需要后端另行实现和验证。

如需保留审批到执行草稿的自动化实录：

```powershell
$env:FRONTEND_TEST_ARTIFACTS = "docs/demo-recording"
.\.venv\Scripts\python -m unittest tests.test_frontend_browser.FrontendBrowserTests.test_transfer_approval_creates_execution_draft_without_external_completion -v
Remove-Item Env:FRONTEND_TEST_ARTIFACTS
```

成功后得到 `docs/demo-recording/demo-flow.webm` 和最后一屏 `demo-flow.png`。视频是合成数据的自动化操作实录，无旁白；5 分钟讲解请按演示分镜进行。常规测试不生成视频。

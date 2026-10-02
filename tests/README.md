# 验证前端交付

在仓库根目录执行（Node.js 20+、Python 3.10+）：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m playwright install chromium
node --test tests/test_frontend_api.mjs tests/test_agent_contract.mjs tests/test_dataset.mjs
.\.venv\Scripts\python -m unittest tests.test_frontend_browser tests.test_frontend_server tests.test_sample_data -v
```

Node 测试验证 HTTP 错误、POST 不自动重试、请求隔离、v0.3 六种业务状态、整数分与金额显示、九份响应夹具、明确版本回显、情景确认和模拟决策边界。数据测试检查真实输入文件、摘要和独立固定预期；不会将参考预期载入运行页面。

浏览器测试启动真实的前端静态预览服务，监听随机本地端口，共享 Chromium 进程；每个用例使用全新的浏览器上下文。Playwright 只对契约的两个 POST 路由提供 `tests/fixtures/v03` 中的固定响应。未配置后端的 503 用例直接使用预览服务响应。测试不加载旧业务后端，不打开或清除用户数据库。

浏览器验收覆盖五个 Agent、六种业务状态、整数分显示、缺项/错误/非法响应、迟到运行和决策的归属、取消/超时、模拟预览与独立决策、防重复提交、输入修改失效、下载合成数据、移动端长内容和导航。资金模拟的预览、确认计算、记录决策是三个独立步骤。任何生产页面读取 `reference/`、`fixtures/` 或预期结果文件都会导致测试失败。

这些属于**前端契约夹具验收，不是真实后端或模型联调**。独立代理测试验证 HTTP 转发，不证明魏的 Agent、业务公式或模型已运行。旧 `test_acceptance.py`、`test_workbenches.py`、`test_teacher_baseline.py` 测试仅用于既有后端回归；不得作为 v0.3 后端验收证据。

如需保留带明确标识的自动化契约演示：

```powershell
$env:FRONTEND_TEST_ARTIFACTS = "docs/demo-recording"
.\.venv\Scripts\python -m unittest tests.test_frontend_browser.FrontendBrowserTests.test_contract_preview_and_simulation_decision_flow -v
Remove-Item Env:FRONTEND_TEST_ARTIFACTS
```

成功后得到 `docs/demo-recording/contract-flow.webm` 和 `contract-flow.png`。录像全程显示“契约夹具演示 · 非真实后端 / 非模型调用”，无旁白；它演示前端交互与固定契约响应，不表示真实模型、后端计算或 ERP 执行。常规测试不生成录像。

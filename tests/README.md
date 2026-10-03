# v1.2 前端与实际后端验证

在仓库根目录执行，需要 Python 3.10+、Node.js 20+：

~~~powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m playwright install chromium
.\.venv\Scripts\python scripts/run_acceptance.py
~~~

统一入口也适用于Linux/macOS，使用已安装依赖的Python解释器执行；原 `bash scripts/run_acceptance.sh` 调用同一入口。它展开文件参数，不依赖Windows shell通配符。检查顺序是后端语法、前端语法、全部Node测试、样例生成校验、全部unittest discover、独立后端并发复现。失败不重试、不跳过，后续步骤继续执行，最终任一步失败即退出1；配置/记录异常退出2，中断退出130。

每次输出到 `output/acceptance/<UTC时间戳-PID>/`，包含逐步日志、状态/退出码/耗时汇总和实际浏览器主流程实录。文件夹已被Git忽略，保留失败和未执行状态，不覆盖前次结果。浏览器录像成功与否分别命名，不能替代全套结果。

GitHub Actions在zmj提交、相关PR及zmj手动运行时使用Python 3.13、Node 22，在Windows和Ubuntu运行同一入口；矩阵不因另一系统失败提前结束，最后上传结果，保留14天。测试失败仍让任务失败。环境安装失败时保留Action安装日志，尽可能执行其余验收以记录缺失项。不能把工作流文件已添加写成两个系统已通过。

需要定位单项时可运行：

~~~powershell
node --test tests/*.mjs
.\.venv\Scripts\python -m unittest tests.test_frontend_browser tests.test_frontend_server tests.test_sample_data tests.test_workflow_evaluation -v
~~~

Node 验证通用请求、错误、v1.2 响应关联和金额、采购参数与输入包。当前协议为元金额、0—100百分比；没有 agent-runs、整数分或旧模拟决策接口。

新增反馈表单测试覆盖否定、未知、人工更正、日期范围、原文关联和转义；导出测试覆盖版本/快照/事实关联、金额原值、缺项、CSV公式防护和三类工作台；业务摘要测试确保不在前端推算缺失结果。评测工具测试使用临时人工记录，验证配对、失败与放弃、成本缺测、证据要求及空模板，不代表真实用户实测或模型评测。

工作台编辑测试覆盖模块与商品隔离、只保存变化字段、最新事实/候选重建、未保存提示、保存回执关联、读写失败恢复及单商品放弃。启动器测试用真实临时后端验证演示会话恢复初值、父环境日常库保持不变、普通真实模式、外部模式、端口冲突及关闭清理；验收入口测试验证失败传播、后续步骤执行、参数空格和证据目录保留。

队列与回执测试覆盖当前分类身份搜索、保存版本关联、未知/重复编号、任务间编辑隔离、显式执行进度、并行状态变化、提交失败及保存回执不匹配。移动导航在实际浏览器验证Tab/Shift+Tab、Escape归还、路由焦点与跨断点恢复。Windows临时库使用文件身份检查，兼容同一文件的长路径和8.3短路径；仍验证日常库内容与修改时间，不放宽隔离要求。

test_frontend_browser 启动实际 FastAPI、独立临时数据库与本地前端代理，使用随机端口和新的浏览器上下文。主流程访问真实业务接口，覆盖工作台计算、保存、提交、审批、待执行任务、反馈核对、采购预览和模拟；不存在用响应夹具替代成功业务计算的步骤。测试每例重置的只是自己的临时数据库。

test_frontend_server 使用本地传输服务验证代理和公开范围；这种 HTTP 传输夹具只验证基础设施，不冒充领域计算或模型。test_sample_data 验证种子导出、引用、单位、哈希和隔离，并实际调用当前采购计算检查零减量/全减量边界。

保留的后端领域与接口回归可单独执行。test_retail 与 test_workbenches 通过 tests/backend_fixture.py 在临时数据库中导入 backend.api，随后恢复调用者环境变量，进程退出时关闭自有连接并清理目录；模块调用与 unittest discover 均使用同一隔离入口。测试不会打开日常数据库。

## 录像

~~~powershell
$env:FRONTEND_TEST_ARTIFACTS = "docs/demo-recording"
.\.venv\Scripts\python -m unittest tests.test_frontend_browser.FrontendBrowserTests.test_live_transfer_workflow -v
Remove-Item Env:FRONTEND_TEST_ARTIFACTS
~~~

成功后得到 live-flow.webm 与 live-flow.png。录像使用实际本地后端、合成数据和合成的人工回执，记录一次成功操作链；魏的共享连接并发修复已合入并复验，完整成绩以对应提交的验证记录为准，录像不能替代全套结果。没有模型或外部 ERP 调用，也不是五分钟旁白成片。普通测试不生成录像。

本轮实际成绩以[验证记录](../docs/VALIDATION_RESULT.md)为准，不沿用旧版本的测试数量。并发控制、生产认证、真实模型和真实执行需要单独验收。

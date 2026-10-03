# v1.2 前端与实际后端验证

在仓库根目录执行，需要 Python 3.10+、Node.js 20+：

~~~powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m playwright install chromium
node --test tests/*.mjs
.\.venv\Scripts\python -m unittest tests.test_frontend_browser tests.test_frontend_server tests.test_sample_data tests.test_workflow_evaluation -v
~~~

Node 验证通用请求、错误、v1.2 响应关联和金额、采购参数与输入包。当前协议为元金额、0—100百分比；没有 agent-runs、整数分或旧模拟决策接口。

新增反馈表单测试覆盖否定、未知、人工更正、日期范围、原文关联和转义；导出测试覆盖版本/快照/事实关联、金额原值、缺项、CSV公式防护和三类工作台；业务摘要测试确保不在前端推算缺失结果。评测工具测试使用临时人工记录，验证配对、失败与放弃、成本缺测、证据要求及空模板，不代表真实用户实测或模型评测。

test_frontend_browser 启动实际 FastAPI、独立临时数据库与本地前端代理，使用随机端口和新的浏览器上下文。主流程访问真实业务接口，覆盖工作台计算、保存、提交、审批、待执行任务、反馈核对、采购预览和模拟；不存在用响应夹具替代成功业务计算的步骤。测试每例重置的只是自己的临时数据库。

test_frontend_server 使用本地传输服务验证代理和公开范围；这种 HTTP 传输夹具只验证基础设施，不冒充领域计算或模型。test_sample_data 验证种子导出、引用、单位、哈希和隔离，并实际调用当前采购计算检查零减量/全减量边界。

保留的后端领域与接口回归可单独执行。test_retail 与 test_workbenches 通过 tests/backend_fixture.py 在临时数据库中导入 backend.api，随后恢复调用者环境变量，进程退出时关闭自有连接并清理目录；模块调用与 unittest discover 均使用同一隔离入口。测试不会打开日常数据库。

## 录像

~~~powershell
$env:FRONTEND_TEST_ARTIFACTS = "docs/demo-recording"
.\.venv\Scripts\python -m unittest tests.test_frontend_browser.FrontendBrowserTests.test_live_transfer_workflow -v
Remove-Item Env:FRONTEND_TEST_ARTIFACTS
~~~

成功后得到 live-flow.webm 与 live-flow.png。录像使用实际本地后端、合成数据和合成的人工回执，记录一次成功操作链；当前全量验收仍存在后端并发读取失败，录像不能替代失败记录。没有模型或外部 ERP 调用，也不是五分钟旁白成片。普通测试不生成录像。

本轮实际成绩以[验证记录](../docs/VALIDATION_RESULT.md)为准，不沿用旧版本的测试数量。并发控制、生产认证、真实模型和真实执行需要单独验收。

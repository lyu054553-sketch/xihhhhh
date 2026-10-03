# 货不压钱 · 连锁零售库存决策工作台

[项目仓库](https://github.com/lyu054553-sketch/xihhhhh) · 朱的开发分支：zmj · 当前接口依据：[魏的 API Contract v1.2](API_CONTRACT.md)。

前端已按魏的 lanyangyang 分支接入实际 FastAPI 后端。经营总览、滞销核查、调拨、近效期、采购刹车、采购情景模拟和审批任务使用真实 HTTP 请求及确定性业务计算；页面不读取测试响应生成业务结果。数据来自虚构零食门店的内置种子，当前没有接入真实大模型或外部 ERP。

主线是：今日待办／经营总览 → 风险证据与门店反馈核对 → 工作台计算 → 保存方案 → 人工审批 → 执行跟进与回执。已保存的方案可导出交接表，交给现有流程处理。采购情景先核对周期、门店、品类与减量比例，确认后才请求模拟。

## 启动

需要 Python 3.10+。首次安装后端依赖：

~~~powershell
git clone https://github.com/lyu054553-sketch/xihhhhh.git
cd xihhhhh
git switch zmj
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\start.ps1
~~~

也可运行 start.bat，或使用 python scripts/run_local.py。默认前端地址为 http://127.0.0.1:8000。启动器运行本地后端与公开文件白名单代理；Windows 默认数据库位于 %LOCALAPPDATA%\huobuyaqian\retail-demo-v1.2.db，避免在静态网站目录保存数据库。已有数据库会保留，本次启动不会自动重置历史方案。按 Ctrl+C 关闭本次启动的服务，不影响其他服务。

连接已有后端时，传入包含 /api/v1 的完整地址：

~~~powershell
.\start.ps1 -ApiBase http://127.0.0.1:9000/api/v1 -Port 8000
.\start.ps1 -Check
~~~

-ApiBase 或 AGENT_API_BASE 配置后使用外部服务；-Check 只校验配置，不启动服务。可用 -Database 或 INVENTORY_AGENT_DB 指定仓库外的数据库文件；INVENTORY_AGENT_MODE=real 时保持真实模式，不自动加入合成种子。不要双击 index.html。scripts/serve_frontend.py 是前端静态与代理服务；它自身不做业务计算。后端私有端口由启动器分配，以输出为准。

## 使用与边界

- 经营总览区分账户余额、库存成本、待关注库存成本和未来采购付款；缺少真实资料时保留 null，显示“未接入／待补充”。
- 工作台初值来自后端；输入变化后需重新计算、保存新方案。无效计算不能保存或审批。
- 门店反馈保存原文，用业务表单更正、采信、排除或保留待核实情况；支持补充现况与证据，不需要编辑 JSON。当前生成的是规则草稿，未核实的原因、日期和处理情况不会自动确认为事实。
- 今日待办按待评估、审批、跟进、完成及草稿展示。三个工作台先呈现库存变化、处置分配或付款压力，再展开完整依据；计算仍来自后端。
- 已保存且有效的方案可下载 CSV 交接表或 JSON 结构化资料，附方案版本、快照、事实与计算版本。下载前重新读取核对；编辑未保存或版本过期时禁止导出。资料仅供执行准备，不自动写入 ERP。
- 审批成功只代表方案已审批；执行接口只创建本地待执行任务。人工填写回执也不代表系统向外部 ERP 写入。
- 模拟仅支持减少可调整采购数量。备注文字不自动转换成任意业务动作；参数确认后才发送模拟请求。
- 金额单位为人民币元，百分比使用 0—100。调拨改变库存位置；库存成本减少、少采购与现金到账不能混为一谈。

当前服务用于本地联调和演示。已复现后端在并发读取时返回 500，完整联调尚未通过；需魏修复数据库连接与并发访问后复验。租户请求头不是身份认证；审批请求还缺少服务端 expected_version 并发前置条件；只编辑或计算、尚未保存时，后端旧方案失效机制仍需完善。具体复现与待魏处理事项见[对接说明](docs/FRONTEND_INTEGRATION.md)。

## 数据与交付

[合成数据包](sample-data/README.md)从后端内置种子导出输入，含 50 个门店、313 个库存输入和独立付款计划。文件带 SHA-256；下载不会自动导入或重置后端。24 条语言参考标为未运行模型评估。

- [朱的交付与魏的待办](docs/ZHU_DELIVERY.md)
- [前端结构](docs/FRONTEND_BLUEPRINT.md) · [接口对接](docs/FRONTEND_INTEGRATION.md)
- [五分钟演示脚本](docs/DEMO_RUNBOOK.md)
- [HTML 演示稿](docs/DEMO_SLIDES.html) · [PowerPoint](docs/DEMO_SLIDES.pptx)
- [实际后端联调录像](docs/demo-recording/live-flow.webm) · [截图](docs/demo-recording/live-flow.png)
- [验证记录](docs/VALIDATION_RESULT.md)
- [用户访谈与人工＋GPT对照评测](docs/USER_VALIDATION.md) · [赛事交付检查表](docs/COMPETITION_CHECKLIST.md)

现有录像记录上一轮 v1.2 界面，使用本地真实后端和合成数据，不表示模型调用或真实业务执行，也不是赛事要求的 2—5 分钟 MP4 成片。旧 v0.3 草案仅用于历史查阅，不再指导当前页面或 API。

新增 24 条门店反馈人工参考语料与既有 24 条采购参考独立存放，均未运行真实模型评测。对照 CSV 只有表头；`python scripts/evaluate_workflow.py --input sample-data/evaluation/workflow-comparison.csv` 输出未采集状态。真实模型的准确率、token 成本及商业收益仍待实测。

## 开发验证

~~~powershell
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m playwright install chromium
.\.venv\Scripts\python sample-data/generate.py --check
.\.venv\Scripts\python -m unittest tests.test_sample_data tests.test_frontend_server tests.test_workflow_evaluation tests.test_frontend_browser -v
node --test tests/*.mjs
node --check app.js
git diff --check
~~~

测试使用临时数据库与随机本地端口，具体结果和限制见[测试说明](tests/README.md)及[验证记录](docs/VALIDATION_RESULT.md)。演示稿由 python scripts/build_demo_slides.py 生成，需要 python-pptx。

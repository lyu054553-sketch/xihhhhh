# 货不压钱 · 连锁零售库存资金 Agent

[项目仓库](https://github.com/lyu054553-sketch/xihhhhh) · 朱的开发分支：`zmj` · 唯一联调依据：[魏的 API Contract v0.3](docs/API_CONTRACT.md)。

面向连锁零售的库存决策工作台，提供滞销诊断、跨门店调拨、近效期处置、采购刹车和资金周转模拟五个入口。本次使用虚构零食门店、商品与交易数据；界面展示后端返回的步骤、指标、证据、告警和建议，并记录模拟确认。

**当前完成的是 v0.3 前端与契约验证。本轮检查的 `main`（`d27f959`）仍是旧后端，尚无 `/api/v1/agent-runs`；真实 v0.3 后端、模型与工具未完成联调。** 浏览器测试中的响应是明确标记的契约夹具，不能作为模型效果或真实业务计算的证明。旧药品工作台不再是本前端的接口来源。

## 启动前端

仅需 Python 3.10+，基础启动只使用标准库，无需安装 FastAPI、数据库或前端构建工具。

```powershell
git clone https://github.com/lyu054553-sketch/xihhhhh.git
cd xihhhhh
git switch zmj
.\start.ps1
```

也可运行 `start.bat`，或跨平台执行 `python scripts/serve_frontend.py`。打开 <http://127.0.0.1:8000>。脚本优先使用项目 `.venv`，没有时使用系统 Python；不会安装依赖、启动旧后端、修改数据库或终止其他进程。

不配置 API 时，可查看表单、合成输入包和版本说明；运行 Agent 会明确返回 `503 API_NOT_CONFIGURED`，不会填充样例结果。不要双击 `index.html`。

魏提供 v0.3 服务后，配置完整的 API 基础 URL（包含 `/api/v1`）：

```powershell
.\start.ps1 -ApiBase http://127.0.0.1:9000/api/v1 -Port 8000
# 只检查配置，不启动服务或请求后端
.\start.ps1 -ApiBase http://127.0.0.1:9000/api/v1 -Check
```

上面的 `9000` 是配置示例，不表示本仓库已提供该服务。也可设置环境变量 `AGENT_API_BASE`，或使用 `python scripts/serve_frontend.py --api-base http://127.0.0.1:9000/api/v1`。端口冲突时更换 `-Port`；按 `Ctrl+C` 停止本次服务。

开发服务只公开页面、资源、指定文档和合成数据文件，并且只转发：

- `POST /api/v1/agent-runs`
- `POST /api/v1/agent-runs/{run_id}/decisions`

请求体最大 2 MiB，原样传递到明确配置的 HTTP(S) 上游。服务不计算业务结果、不访问 SQLite、不重试写入，也不提供旧导入、审批、执行或重置接口。

## 本次流程

普通 Agent：填写范围与参数 → 运行 → 核对服务返回的步骤、结果和证据 → 模拟确认或拒绝建议。

资金周转模拟：描述调整 → `operation=preview` → 展示待确认情景卡 → 人工核对 → 携带同一 `session_id`、`scenario_id`、`confirmed=true` 请求 `operation=simulate` → 展示基线、方案、假设与缺货风险。预览阶段不展示结果指标；输入改变后旧结果与确认失效。

`confirmed=true` 只允许开始模拟。建议的“模拟确认”只记录 `execution_mode=simulation` 决策，不修改库存、采购单或收银数据。金额传输采用整数分；库存成本占用和预计避免采购支出都不等于银行余额或真实客户收益。

## 合成数据与交付材料

[数据说明](sample-data/README.md)与 `sample-data/manifest.json` 记录固定版本、分析日、种子和文件校验值。七类共享模型覆盖门店、商品、库存快照、日销售、采购单、批次和经营规则。参考场景与预期独立保存，网页不会读取预期值来生成运行结果；下载也不会自动导入后端。

- [朱负责的交付清单与魏的对接事项](docs/ZHU_DELIVERY.md)
- [前端实现说明](docs/FRONTEND_BLUEPRINT.md) · [接口对接与待确认口径](docs/FRONTEND_INTEGRATION.md)
- [五分钟演示脚本与答辩](docs/DEMO_RUNBOOK.md)
- [HTML 演示稿](docs/DEMO_SLIDES.html) · [可编辑 PowerPoint](docs/DEMO_SLIDES.pptx)
- [契约夹具录像（非真实后端／模型）](docs/demo-recording/contract-flow.webm) · [截图](docs/demo-recording/contract-flow.png)
- [本次验证记录](docs/VALIDATION_RESULT.md)

演示材料以 v0.3 为准。旧版审批到执行草稿录像已移除；新录像标注“契约夹具演示”，仅说明界面在这些响应下的行为，不能称为真实后端联调录像。

## 开发验证

Node.js 20+ 用于模块测试；Playwright 和 python-pptx 分别用于浏览器验收与演示稿生成。

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m playwright install chromium
.\.venv\Scripts\python sample-data/generate.py --check
.\.venv\Scripts\python -m unittest tests.test_sample_data tests.test_frontend_server tests.test_frontend_browser -v
node --test tests/test_frontend_api.mjs tests/test_agent_contract.mjs tests/test_dataset.mjs
node --check app.js
git diff --check
```

准确范围、环境和结果见[测试说明](tests/README.md)与[验证记录](docs/VALIDATION_RESULT.md)。测试成功不替代魏的工具计算、模型调用、并发控制及正式集成验收。`python scripts/build_demo_slides.py` 从同一内容重新生成 HTML 和 PowerPoint。

## 下一步联调

魏提供真实 v0.3 服务、加载 `snack-demo-v1` 与 `snack-policy-v1`，先验证滞销样例，再覆盖五个 Agent、会话预览、模拟决策和错误恢复。双方还需明确库存资金指标的计算时点、日内到货顺序、近效期预测日期、箱规适用范围，以及 30 天模拟中的后续补货假设。未确认部分详见对接文档，前端不自行补算。

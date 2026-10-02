# 库存现金智能体 · Inventory Cash Agent

[GitHub 仓库](https://github.com/lyu054553-sketch/xihhhhh) · 开发分支：`zmj` · 本分支负责：朱的前端、合成场景、测试与演示材料。

面向多门店企业的库存决策工作台：从库存风险和门店反馈出发，核对证据，调用后端计算调拨、近效期处置和采购调整方案，经过人工审批生成执行草稿，再记录人工回执。库存成本、预计避免报损、模拟净现金改善和实际回款分别展示。

**当前是本地规则计算版本。五个业务入口已有后端接口；真实大模型、生产 ERP 写回和模型运行日志仍待魏接入。** 页面上的工具结果来自后端确定性计算，不能称为真实 AI 推理结果。所有内置示例均为合成演示数据，模拟金额不代表真实客户收益。

## 本地启动

需要 Python 3.10+。运行时使用 Python、FastAPI、SQLite 和原生 HTML/CSS/JavaScript；Node.js 用于可选的前端检查。先安装依赖，再启动；启动脚本不会自行联网安装、重置数据库或终止其他进程。

```powershell
git clone https://github.com/lyu054553-sketch/xihhhhh.git
cd xihhhhh
git switch zmj
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\start.ps1
```

打开 <http://127.0.0.1:8000>。Windows 也可运行 `start.bat`。端口冲突时使用 `.\start.ps1 -Port 8765`，在运行窗口按 `Ctrl+C` 停止服务。`.\start.ps1 -Check` 仅检查环境并打印配置，不启动服务或创建数据库。

默认演示库位于 `%LOCALAPPDATA%\InventoryCashAgent\zmj\demo\inventory.db`，独立于原项目数据库和真实数据，重启会保留演示记录。不要直接双击 `index.html`：页面需要本地 API，文件模式不会生成计算结果或写入成功提示。安装依赖及浏览器后，规则演示本身无需连接外网。

其他系统可显式指定项目目录外的演示库：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
mkdir -p "$HOME/.local/share/inventory-cash-agent/zmj-demo"
INVENTORY_AGENT_MODE=demo INVENTORY_AGENT_DB="$HOME/.local/share/inventory-cash-agent/zmj-demo/inventory.db" .venv/bin/python server.py
```

## 演示与数据

主线是 **门店反馈 → 滞销诊断 → 调拨测算 → 人工确认 → 执行草稿**。另有近效期、采购刹车和现金流模拟入口。输入修改后需重算，失效或错误状态不得提交旧结果；API 失败应展示错误，不能自动替换成样例数据。

- [五分钟演示、故障演示与视频分镜](docs/DEMO_RUNBOOK.md)
- [可打印演示稿](docs/DEMO_SLIDES.html) · [PowerPoint 演示稿](docs/DEMO_SLIDES.pptx)
- [自动化流程录像（无旁白）](docs/demo-recording/demo-flow.webm) · [执行草稿截图](docs/demo-recording/demo-flow.png)
- [合成数据说明](sample-data/README.md) · [前端集成说明与后端待办](docs/FRONTEND_INTEGRATION.md)

安装下方开发依赖后，可执行 `.\.venv\Scripts\python.exe scripts/build_demo_slides.py` 从同一份内容重新生成 HTML 和可编辑的 PowerPoint（含逐页讲稿）。

`sample-data/` 的生成场景用于确定性测试和导入验证；它与后端内置的 `snapshot-demo-v1` 是两个明确标记的数据来源。生成文件不会自动改写数据库。数据中心导入目前校验字段并保存导入批次，**不会自动把文件变成分析快照**。

另提供 [24 条中文门店反馈评测语料](sample-data/feedback-evaluation.json)和[字段参考标注说明](sample-data/README.md#中文门店反馈评测集)，覆盖日期、数量、缺项、冲突与人工复核。它们是待业务复核的评测参考，真实模型尚未运行，模型指标保持未测；语料检查通过不代表模型评分。

仅在独立演示实例中使用演示重置入口，该操作会清除演示反馈、方案及执行记录。页面须同时确认健康接口 `sample_data=true` 和数据中心 `mode=sample_replay` 后才允许重置，不能单凭数据中心模式判断。当前后端对真实模式的重置保护仍是集成待办，禁止向真实实例调用 `/api/v1/demo/reset`。

## 真实库存快照

真实文件、数据库及凭证保存在项目目录外，不进入版本库。先用现有导入工具生成快照，再显式选择真实模式：

```powershell
$realDatabase = Join-Path $env:LOCALAPPDATA 'InventoryCashAgent\real\inventory.db'
New-Item -ItemType Directory -Path (Split-Path -Parent $realDatabase) -Force | Out-Null
.\.venv\Scripts\python.exe scripts/import_real_inventory.py 'D:\private-data\inventory.xlsx' --database $realDatabase
.\start.ps1 -Mode real -Database $realDatabase -Port 8765
```

启动脚本要求真实库已存在、包含导入快照，且不在项目静态目录或演示库目录内。真实模式提供库存、30/90 天销量、成本、采购状态以及 `teacher-v1` 候选分析；批次效期、采购订单、在途和执行连接器按实际缺项显示。真实数据的完整操作链仍需后端集成，不能用演示工作台补齐。

## 架构与职责

当前采用模块化单体：原生浏览器前端 → FastAPI → `backend/domain.py` 确定性计算 → SQLite 事实、方案版本与审批记录。网页和 API 由同一进程提供，无需第二套后端。生产化遵循[架构基线](docs/ARCHITECTURE.md)；其中 LangGraph、PostgreSQL、ERP Connector 等为规划，不能作为本版本已实现能力介绍。

| 范围 | 负责人 | 本分支边界 |
| --- | --- | --- |
| `backend/`、模型适配、数据库、工具计算、正式 API 契约 | 魏 | 朱消费现有 API；缺失能力记入集成说明 |
| `index.html`、`styles.css`、`app.js`、`assets/` | 朱 | 五个入口、表单、过程、状态、人工确认 |
| `sample-data/`、`tests/`、README 与演示材料 | 朱 | 合成场景、回归与演示交付 |

`docs/FRONTEND_INTEGRATION.md` 是朱对现有代码的消费说明，不能替代魏负责冻结的 `docs/agent-api-contract.md`。接口变化先更新正式契约，再修改消费者。朱的开发和提交在 `zmj` 完成，之后由双方在集成分支验证。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe sample-data/generate.py --check
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --test tests/test_frontend_api.mjs tests/test_data_center.mjs
node --check app.js
git diff --check
```

浏览器回归使用隔离临时数据库与随机端口，完整命令见[测试说明](tests/README.md)。通过数量以本次实际输出为准，不能复用历史 PASS 声明。人工演示按 runbook 核对数量约束、输入变更失效、反馈确认、审批与执行草稿、API 失败、空数据及移动端。

本次已执行的结果、录像证据和未覆盖边界见[验收记录](docs/VALIDATION_RESULT.md)。

## 仍待集成

- 真实模型调用、结构化校验、请求编号、超时/限流/重试与证据由魏负责；前端只展示已收到的事实和工具结果。
- 后端真实模式重置防护、单据版本并发控制、事务、鉴权和受控静态资源服务仍需验收；前端锁定按钮不能替代这些保证。
- 真实 ERP 执行、外部回执核验与财务归因未接入。生成执行任务或记录人工回执不等于外部系统已经执行。

既有资料：[前端蓝图](docs/FRONTEND_BLUEPRINT.md)、[实施路线](docs/IMPLEMENTATION_ROADMAP.md)、[历史实施记录](docs/IMPLEMENTATION_RESULT.md)。历史版本结果不代表本次验证结果。

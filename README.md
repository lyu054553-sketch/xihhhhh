# 货不压钱 · 连锁零售库存决策工作台

[项目仓库](https://github.com/lyu054553-sketch/xihhhhh) · 朱的开发分支：zmj · 当前接口依据：[魏的 API Contract v1.2](API_CONTRACT.md)。

前端已按魏的 lanyangyang 分支接入实际 FastAPI 后端。经营总览、滞销核查、调拨、近效期、采购刹车、采购情景模拟和审批任务使用真实 HTTP 请求及确定性业务计算；页面不读取测试响应生成业务结果。数据来自虚构零食门店的内置种子，当前没有接入真实大模型或外部 ERP。

主线是：今日待办／经营总览 → 风险证据与门店反馈核对 → 工作台计算 → 保存方案 → 提交审批 → 人工审批 → 执行跟进与回执。已保存的方案可导出交接表，交给现有流程处理。采购情景先核对周期、门店、品类与减量比例，确认后才请求模拟。

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

彩排或现场演示可使用独立会话：

~~~powershell
.\start.ps1 -DemoSession
.\start.ps1 -DemoSession -Check
~~~

跨平台入口为 `python scripts/run_local.py --demo-session`。每次启动创建独立临时合成库；在启动终端按 Ctrl+C 正常关闭后清理，重新运行即恢复种子状态。演示期间需要保留的交接资料应先下载，关闭浏览器本身不会停止服务。该模式忽略父环境的日常数据库路径，只给自己的后端进程指定合成模式；不能与显式 `-Database`、外部 `-ApiBase` 或有效 `AGENT_API_BASE` 同用。普通启动继续保留日常数据库。`-Check` 不创建数据库或启动服务。

连接已有后端时，传入包含 /api/v1 的完整地址：

~~~powershell
.\start.ps1 -ApiBase http://127.0.0.1:9000/api/v1 -Port 8000
.\start.ps1 -Check
~~~

-ApiBase 或 AGENT_API_BASE 配置后使用外部服务；-Check 只校验配置，不启动服务。可用 -Database 或 INVENTORY_AGENT_DB 指定仓库外的数据库文件；INVENTORY_AGENT_MODE=real 时保持真实模式，不自动加入合成种子。不要双击 index.html。scripts/serve_frontend.py 是前端静态与代理服务；它自身不做业务计算。后端私有端口由启动器分配，以输出为准。

## 模型 API 配置入口

已预留 DeepSeek、千问、MiniMax 三组后端配置，模板见 [.env.example](./.env.example)。本机已有 `.env` 时直接编辑；首次从仓库获取项目且尚无该文件时，可复制模板：

```bash
cp -n .env.example .env
```

在 `.env` 中填写所需服务的配置，修改后重启后端。API Key、模型名称允许暂时留空，不影响本地规则计算。

| 服务 | 密钥字段 | 其他配置 |
|---|---|---|
| DeepSeek | `DEEPSEEK_API_KEY` | `DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`、`DEEPSEEK_VISION_MODEL` |
| 千问／阿里云百炼 | `QWEN_API_KEY` | `QWEN_BASE_URL`、`QWEN_MODEL`、`QWEN_VISION_MODEL` |
| MiniMax | `MINIMAX_API_KEY` | `MINIMAX_BASE_URL`、`MINIMAX_MODEL`、`MINIMAX_VISION_MODEL` |

`AGENT_MODEL_PROVIDER` 和 `AGENT_VISION_PROVIDER` 分别预留文本分析、图片识别的服务选择，可填 `deepseek`、`qwen`、`minimax`，未决定时留空。模型名称按账号实际可用模型填写；图片入口需对应支持图片输入的模型。千问默认地址为北京地域，其他地域或专属工作空间需要替换成与密钥匹配的地址。接口地址依据 [DeepSeek 文档](https://api-docs.deepseek.com/)、[百炼地域与接口说明](https://help.aliyun.com/en/model-studio/base-url)、[MiniMax 文档](https://platform.minimax.cn/docs/api-reference/text-openai-api) 预留，可自行修改。

后端从项目根目录 `.env` 读取，已有环境变量优先；密钥使用 `SecretStr` 保存，配置不通过前端接口返回，`.env` 已被 Git 忽略。本次开发与比赛不设 API 总费用上限，配置中的 `api_budget_limit_cny=None` 表示不限，后续接入仍保留请求超时、有限重试与用量记录。

**目前完成的是配置读取入口；尚未接入模型请求、图片识别或自动切换。** 填写配置不会触发付费调用。新增依赖 `python-dotenv`，更新后先按上面的命令安装 `requirements.txt`。

## 数据与协作

## 使用与边界

- 经营总览区分账户余额、库存成本、待关注库存成本和未来采购付款；缺少真实资料时保留 null，显示“未接入／待补充”。
- 工作台初值来自后端；输入变化后需重新计算、保存新方案。无效计算不能保存或审批。
- 工作台编辑按商品与模块保留在当前页面内存。切换商品后重新读取服务事实，只恢复改动过的可编辑字段；候选门店失效时要求重新选择。可保存编辑输入，或放弃当前商品的本地编辑。刷新／关闭时对未保存工作台、门店反馈编辑及进行中的操作请求浏览器离开提示；真正持久保存以服务回执为准。编辑输入保存与方案保存是两个状态。
- 门店反馈保存原文，用业务表单更正、采信、排除或保留待核实情况；支持补充现况与证据，不需要编辑 JSON。当前生成的是规则草稿，未核实的原因、日期和处理情况不会自动确认为事实。
- 今日待办按待评估、审批、跟进、完成及草稿展示，可在当前分类按门店、商品或编号搜索。任务卡仅从关联一致的已保存方案版本展示门店商品，旧版或缺项明确待核对。三个工作台先呈现库存变化、处置分配或付款压力，再展开完整依据；计算仍来自后端。
- 人工回执按任务保留当前页面内的编辑，切页、分类、搜索或请求失败不会清空。新任务须明确选择实际进度；保存前读取最新记录核对，服务状态或回执变化时阻止本次覆盖，仅在取得匹配回执后清理对应编辑。刷新或关闭会对未保存回执提示，仍不替代后端原子版本校验。
- 移动导航支持键盘进入、Tab范围、Escape关闭及焦点归还；选择页面后焦点移到主内容。
- 已保存且有效的方案可下载 CSV 交接表或 JSON 结构化资料，附方案版本、快照、事实与计算版本。下载前重新读取核对；编辑未保存或版本过期时禁止导出。资料仅供执行准备，不自动写入 ERP。
- 审批成功只代表方案已审批；执行接口只创建本地待执行任务。人工填写回执也不代表系统向外部 ERP 写入。
- 模拟仅支持减少可调整采购数量。备注文字不自动转换成任意业务动作；参数确认后才发送模拟请求。
- 金额单位为人民币元，百分比使用 0—100。调拨改变库存位置；库存成本减少、少采购与现金到账不能混为一谈。

当前服务用于本地联调和演示。后端仍为魏 lanyangyang 的 19794ca（并发修复 3cc6c4a）；2026-10-03 本地统一验收六步全部通过，JavaScript 138/138、Python 163/163（含浏览器 43/43）。独立临时库的45次串行和9线程150次并发读取均为HTTP 200，返回内容与串行基准一致，原并发读取500未再现。完整证据见[验证记录](docs/VALIDATION_RESULT.md)。

此次修复保护同一个 Store 的共享连接，不提供跨进程事务或整份HTTP响应的统一快照。租户请求头不是身份认证；审批请求还缺少服务端 expected_version 原子比较；只编辑或计算、尚未保存时，后端旧方案失效机制仍需完善。剩余边界见[对接说明](docs/FRONTEND_INTEGRATION.md)。

## 数据与交付

[合成数据包](sample-data/README.md)从后端内置种子导出输入，含 50 个门店、313 个库存输入和独立付款计划。文件带 SHA-256；下载不会自动导入或重置后端。24 条语言参考标为未运行模型评估。

- [朱的交付与魏的待办](docs/ZHU_DELIVERY.md)
- [下一轮功能、优先级与分工](docs/ZHU_NEXT_ITERATION.md)
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
.\.venv\Scripts\python scripts/run_acceptance.py
git diff --check
~~~

统一入口执行语法检查、全部JavaScript测试、样例校验、全部Python测试及后端并发回归。各步骤失败后仍收集其余结果，最终有失败即返回非零；每次的日志、汇总与浏览器实录保存在 `output/acceptance/` 独立目录。GitHub Actions使用同一入口运行Windows／Ubuntu检查并上传证据；远端结果以[对应提交的运行记录](https://github.com/lyu054553-sketch/xihhhhh/actions/workflows/acceptance.yml?query=branch%3Azmj)为准，本地通过不替代远端结果。上一提交Windows长短路径误判已定位并改为文件身份校验，详见验证记录；并发检查继续执行，不跳过历史故障的回归。

测试使用临时数据库与随机本地端口，具体结果和限制见[测试说明](tests/README.md)及[验证记录](docs/VALIDATION_RESULT.md)。演示稿由 python scripts/build_demo_slides.py 生成，需要 python-pptx。

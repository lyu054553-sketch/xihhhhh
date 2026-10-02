# 库存现金智能体（Inventory Cash Agent）

仓库：`xikesong`

面向多门店企业的库存资金决策与执行平台：发现库存异常与关注库存成本，组织人工核查，生成可统一测算的调拨、促销、退供和采购调整方案，并在负责人确认后记录执行任务与结果。当前以连锁药房真实库存表作为首个落地数据源，后续可扩展到商超、便利店、母婴、服装、3C、餐饮和汽配等业态。未获证据的原因会显示为“待核查”，不把库存金额冒充现金改善。

当前根目录中的 `index.html`、`styles.css` 和 `app.js` 是同一个产品入口，已经接入 `backend/` 的 FastAPI + SQLite 最小闭环；不需要再启动第二套 Demo。生产化时可把 SQLite 替换为 PostgreSQL，把静态页面替换为 Next.js，但领域对象和 API 语义保持不变。

## 架构结论

- **产品底座：自研 Agent-native 独立平台**，不是 Odoo/ERPNext 二次开发。
- **参考 Odoo：** 库位、批次、库存移动、调拨、补货规则等库存物流模型。
- **参考 ERPNext：** 单据状态机、审批流、角色权限、操作时间线和列表/表单式交互。
- **参考 ERPNext 前端气质：** 清晰、克制、高信息密度，但不复制源码、商标或界面素材。
- **自研核心：** 风险识别、原因诊断、多方案生成、约束优化、现金释放模拟、人工审批与效果归因。

## 当前已实现（V1.2）

- 真实库存成本、关注库存成本、净现金改善、避免报损四种金额口径分离；未知值持久化为 `null`。
- SQLite 迁移和可重复合成样例；风险、方案版本、核查反馈、审批、执行任务、现金事件、案例和审计事件可持久化。
- AC01—AC26 自动验收测试已执行并全部 PASS。
- 风险详情显示比较事实、证据等级、缺项；核查原文先生成待确认草稿，确认后推进事实版本并使受影响旧方案失效。
- 审批绑定具体方案版本；执行只生成“待原系统执行”草稿，当前不写入 ERP、不自动改价、不自动停采、不群发消息。
- 当前样例使用确定性计算，未接入真实 ERP、客户数据或模型凭证；页面明确标注“合成样例回放”。
- 前端导航已按经营总览、今日工作台、五大 Agent、协同执行、数据与知识重新分组；五个 Agent 入口复用同一风险案件与 API，不复制业务状态。
- 三个可计算工作台已形成输入→重算→保存方案→提交审批→人工执行回执的闭环：调拨会阻止超出可调量、接收能力和效期的数量；近效期按批次数量守恒比较处置方式；采购将库存、在途、未执行采购和付款压力分列。
- 滞销诊断页同时展示已知事实、原因假设、证据等级和缺项，复用原有核查反馈与事实版本机制；修改输入会立即将旧测算标为“待重新计算”。
- 现金流模拟只组合当前已计算的工作台草稿，内部调拨和没有回款依据的近效期动作不冒充现金释放；组合会按草稿 ID 去重并校验共享批次占用。
- 今日工作台读取统一待办而非截取风险列表；审批、执行、导入记录均从 SQLite 读取。数据中心的 CSV 入口只做字段校验并留存导入记录，不覆写业务快照。

## 本地运行

依赖：Python 3.8+、Node.js 20+；Python 依赖见 [`requirements.txt`](./requirements.txt)。

```bash
cd inventory-cash-agent
python3 -m pip install -r requirements.txt
python3 server.py
```

浏览器打开 `http://127.0.0.1:8000`。端口冲突时可用 `PORT=8765 python3 server.py`。数据库默认为 `inventory_cash_agent.db`，可通过 `INVENTORY_AGENT_DB` 指定路径；重置隔离样例使用 `POST /api/v1/demo/reset`。

### 真实库存数据模式

真实库存模式读取本地 ERP 库存快照。数据库和原始进销存文件仅保存在本地，不随代码仓库提交；导入行数、门店数及金额以各自数据快照为准。启动真实数据模式：

```bash
INVENTORY_AGENT_MODE=real INVENTORY_AGENT_DB=inventory_cash_agent_real.db python3 server.py
```

也可以重新导入同格式文件：

```bash
python3 scripts/import_real_inventory.py \
  "/path/to/your/inventory.xlsx" \
  --database inventory_cash_agent_real.db
```

当前真实模式可展示库存、30/90 天销量、30 天成本、采购状态、统计标记类及老师口径候选。批次有效期、采购订单、在途、陈列和补货日志尚未接入，因此近效期、调拨路径和实际现金到账不会用演示数据补齐。

当前已接入老师口径（计算版本 `teacher-v1`）基线层：老师口径存销比按库存数量、30/90 天销量重算；降库存存销比按库存金额÷三十天成本计算。目标库存金额、建议压降金额与 P1/P2/P3 候选均由同一快照计算。调拨、促销、退供和采购刹车仍作为后续人工确认动作，审批与执行边界不变。

测试：

```bash
bash scripts/run_acceptance.sh
python3 -m unittest discover -s tests -v
```

### 浏览器验收路径

1. 打开“跨门店智能调拨”，将建议数量改为 `100` 并点击“重新计算”，确认出现可调量与接收能力拦截；改回 `40`，重算、保存方案、提交审批。
2. 打开“方案审批”，确认审批后生成执行任务；在“执行追踪”依次选择状态并在“已收货／已完成”时填写回执号。
3. 在“近效期现金抢救”修改促销、调拨或退供数量后重算，确认正常销售与处置数量超出批次库存会被拦截，且促销销量提升仍显示为待确认假设。
4. 在“采购刹车”切换减少采购／延期付款，确认库存、在途、未执行采购与付款压力分列显示。
5. 在“现金流模拟”先完成任一可计算工作台草稿，再输入目标、周期和约束；勾除动作后确认组合整体重算。无可计算候选时应显示缺项而非样例结果。
6. 在“数据中心”粘贴缺少 `sku`、`store` 或 `inventory_qty` 的 CSV，确认失败原因被留存；补齐字段后只显示“字段校验通过，未覆写快照”。

## 本地设计文档

1. [系统开发架构](./docs/ARCHITECTURE.md)
2. [前端产品与设计蓝图](./docs/FRONTEND_BLUEPRINT.md)
3. [实施路线与验收标准](./docs/IMPLEMENTATION_ROADMAP.md)
4. [本轮实施结果与 AC 报告](./docs/IMPLEMENTATION_RESULT.md)

## 推荐技术栈

| 层级 | 第一阶段选择 | 用途 |
|---|---|---|
| Web | Next.js + TypeScript + Tailwind CSS + shadcn/ui | 工作台、单据、审批和 Agent 运行过程 |
| API | Python 3.12 + FastAPI + Pydantic | 统一业务 API、权限和数据契约 |
| Agent | LangGraph | 有状态编排、人工确认、失败恢复 |
| 计算 | Polars + OR-Tools | 指标计算、调拨与采购约束优化 |
| 数据 | SQLite（本地 V1.1）/ PostgreSQL（产品化） | 业务真相源、审计与任务状态 |
| 异步 | Redis + Celery（首期） | 导入、日批分析和长任务 |
| 对象存储 | S3/MinIO | 导入文件、报表和执行附件 |
| AI | 模型适配层 | 首期接一个模型，保留替换和私有化能力 |

## 规划中的产品化目录

```text
inventory-cash-agent/
├── apps/
│   ├── web/                  # Next.js 产品前端
│   └── api/                  # FastAPI 接口与鉴权
├── services/
│   ├── agent/                # LangGraph 编排与工具注册
│   ├── scheduler/            # 每日扫描、重试和通知
│   └── worker/               # 导入、计算和报表任务
├── packages/
│   ├── domain/               # 统一领域模型与状态机
│   ├── connectors/           # Excel/ERP/API 数据适配器
│   ├── analytics/            # 周转、效期、现金占用算法
│   ├── optimization/         # 调拨与采购优化模型
│   ├── ui/                   # 设计系统和业务组件
│   └── evaluation/           # Agent 回放与评测集
├── infra/                    # Docker、数据库迁移和部署配置
├── sample-data/              # 脱敏演示数据和数据字典
├── backend/                  # 当前 FastAPI、SQLite 领域逻辑和迁移
├── tests/                    # AC01—AC26 自动验收测试
├── scripts/                  # 可重复测试命令
├── docs/                     # 架构、前端和实施文档
├── index.html                # 当前黑客松静态 Demo
├── styles.css
└── app.js
```

> 不建议现在一次性创建所有服务。第一阶段只建立 `apps/web`、`apps/api`、`services/agent` 和一个 PostgreSQL；其余模块在需要时从同一代码库中拆出。

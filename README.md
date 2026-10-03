# 货不压钱｜连锁零售库存资金 Agent

面向连锁零售企业的库存资金决策系统。系统把门店库存、销售、采购和账户数据放在一起，回答老板最关心的三个问题：钱现在在哪里、哪些货压住了钱、下一步该处理什么。

产品适用于不同零售业态；本仓库使用虚构的 **零食仓** 连锁零食门店作为演示案例。演示数据不是任何真实企业的经营数据。

## 已有页面

- **经营总览**：账户可用资金、销售额、毛利、库存占用资金、资金趋势、库存健康和门店表现。
- **今日工作台**：分开展示待审批方案与待评估建议；审批通过后进入「审批后跟进」，继续生成待执行任务、记录进度与回执，完成后进入「已完成」。
- **滞销诊断**：按库存成本排列待关注商品，可逐件切换，查看库存资金占用、销量对照、待核查原因和数据依据。
- **跨店调拨**：在杭州门店示意地图上比较优先接收门店，查看调出、调入库存变化，调整数量并提交审批。
- **近效期处理、采购刹车**：分别核算可售时间、处置数量、采购数量、缺货风险和付款压力。
- **现金流模拟**：先用会话确认条件，再展示基线与方案对比、逐周资金变化及缺货风险。

页面统一使用清新绿风格。账户资金与库存成本分开计算；跨店调拨只改变库存位置，不能算作即时回款。所有方案均需人工确认，审批通过后仍需负责人执行。

右上角“管理员”是本地演示身份标签；当前版本尚未接入账号登录与权限管理。

## 本地运行

需要 Python 3.10+，依赖见 `requirements.txt`。在本目录执行：

```bash
python3 -m pip install -r requirements.txt
python3 server.py
```

然后打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。如需更换端口：

```bash
PORT=8765 python3 server.py
```

首次启动会创建本地 SQLite 演示数据库。想恢复演示初始状态时，可调用 `POST /api/v1/demo/reset`。静态页面和 API 由同一个服务提供。

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

- 演示模式使用确定性的零食门店库存、采购、销售和独立账户流水样例；界面会标明“演示数据”。
- 真实库存模式可读取本地导入的库存快照。未接入的账户、销售和批次事实显示为未知，不用演示数补齐。
- 前后端字段、接口、错误和状态约定见 [API_CONTRACT.md](./API_CONTRACT.md)。
- 后端入口见 `backend/api.py`；前端入口为 `index.html`、`app.js` 及 `retail-*.js` / `retail-*.css`。

这是可本地运行的比赛演示版本。地图中的门店位置与路线为演示估算，不是实际配送导航。

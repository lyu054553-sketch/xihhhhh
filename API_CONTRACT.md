# 货不压钱｜连锁零售库存资金 Agent API Contract

版本：v1.2（与当前 FastAPI 原型对齐）  
日期：2026-10-03  
前端负责人：朱；后端及计算负责人：魏  
仓库：lyu054553-sketch/xihhhhh，协作分支：lanyangyang

本文件是当前可运行版本的联调契约。早期统一 Agent Run 的构想保存在 docs/API_CONTRACT_V0_3_DRAFT.md；其中的 /agent-runs、金额分字段和示例 ID 均未在当前原型实现，前端联调以本文件及 /openapi.json 为准。

## 1. 双方先冻结的约定

- API 前缀为 /api/v1，JSON 使用 UTF-8。前端以同域路径调用；本地开发用 python3 server.py 启动。
- 所有当前 API 金额字段使用人民币“元”，JSON number，最多保留两位小数。字段名无 _fen 后缀。展示层自行加 ¥、万元缩写，不改变请求金额。
- 百分比字段使用 0 到 100 的数值：reduction_pct: 20 表示减少 20%；gross_margin_pct: 34.2 表示 34.2%。
- 数量按响应中的商品单位展示。风险列表演示数据多以“件”为单位；不得把件、袋、箱混算。
- 未知值为 null，零为 0。前端对 null 显示“未接入／待补充”，不得显示为 0 或虚构的现金回款。
- 日期为 YYYY-MM-DD，完整时间使用带时区 ISO 8601。演示快照日期为 2026-10-03。
- 每次展示标出 is_demo、source、as_of_date。真实库存模式不会拼接演示销售额、账户余额或采购预测。
- 所有库存占用金额按成本计；采购少支出是预计避免的现金流出；调拨只改变库存位置；这三者不得统称“已回款”。
- 可选请求头 X-Tenant-Id 用于租户隔离；省略时为 demo。审批操作支持 Idempotency-Key。

## 2. 五个入口与接口

| 页面／能力 | 读取 | 操作 |
|---|---|---|
| 经营总览 | GET /retail/overview | 门店与周期筛选 |
| 今日工作台 | GET /work-items、GET /proposals、GET /execution-tasks | 进入方案、审批及执行 |
| 滞销诊断 Agent | GET /risks、GET /risks/{risk_id} | 建立核查、反馈、确认与重算 |
| 跨店调拨 Agent | GET /workbenches/transfer | /draft、/calculate、/save，然后方案审批 |
| 近效期 Agent | GET /workbenches/expiry-rescue | 同上 |
| 采购刹车 Agent | GET /workbenches/procurement-brake | 同上 |
| 现金流模拟 Agent | GET /retail/simulation-options | POST /retail/simulate |

表内路径均省略 /api/v1 前缀。当前会话模拟用确定性计算处理“周期内减少采购百分比”的情景；自然语言识别属于前端引导层，模型适配层另行接入。原有 POST /scenarios/simulate 是基于已保存工作台草稿的目标求解接口，和会话模拟不同，不能交叉使用结果字段。

## 3. 经营总览

GET /api/v1/retail/overview?period=7&store_id=all

- period 只能是 7 或 30；store_id 为 all 或 simulation-options 返回的门店 ID。
- 返回 account、sales、inventory、purchase_commitments、pending_approvals、trend、stores 和 metadata。
- account.balance 是账户可用资金；inventory.cost 是库存成本占用；二者不能互推。
- 首页四项主指标依次是 account.balance、inventory.cost、inventory.risk_cost、purchase_commitments.amount。purchase_commitments 仅统计快照日后 30 天内到期且已确认的采购付款；演示模式使用独立合成确认计划，真实模式未接入付款计划时为 null，不用历史采购付款或采购预测填充。
- 接口仍返回 inventory.turnover_days、sales.amount_7d、sales.gross_margin_7d_pct、pending_approvals.amount 与 inventory.stockout_risk_count，以保持接口兼容；经营总览首页不展示这五项次级指标卡片。近 7 天销售和毛利率固定为 7 天口径，不随 period 改变。pending_approvals.amount 是当前待审批方案涉及的商品成本，不是预计回款或确定支出；若任一方案缺少数量或成本则为 null，并提供 known_amount、missing_count。演示缺货风险数按未来 7 天预计需求超过现货与在途的门店商品记录计数；真实模式使用导入快照的缺货／临缺标记，缺少所需字段时为 null。
- inventory.risk_store_count 是有待关注商品的门店数；inventory.risk_count 是门店商品记录数，不能当成不同 SKU 的数量。
- inventory.turnover_days 与 stores[].turnover_days 按当前库存成本 ÷ 所选周期日均销售成本估算，单位为天；缺少销售成本时返回 null。stores[].risk_cost 是该门店的风险库存成本。
- stores 默认按 risk_cost 从高到低排序，缺少风险判定数据的门店排在后面；前端初始沿用这一优先级，并允许按门店名称、库存占用成本、待关注库存成本、库存周转天数切换排序。stores[].risk_count 是该店待关注商品总数，primary_risk 是金额最高的待关注商品的主要风险。risk_types 是该店全部待关注商品涉及的风险类型数组，用于前端多选筛选；多选时匹配任一所选类型，不依赖仅展示前 5 项的 risk_items。
- stores[].risk_items 只列出该店按库存成本排序的前 5 项，包含 risk_id、sku、product、inventory_cost、risk_label、reason；真实库存候选还可能带 priority。risk_items 的金额不能加总后冒充全店 risk_cost。
- 真实数据缺少账户／销售时，对应字段为 null，trend 为空数组，metadata.missing 标明缺项。

关键响应结构：

    {
      "is_demo": true,
      "source": "零食仓 · 合成零售经营样例 v1",
      "as_of_date": "2026-10-03",
      "scope": {"store_id": "all", "store_count": 50, "period": 7},
      "account": {"balance": 858900.00, "opening_balance": 833200.00,
                  "cash_in": 126100.00, "cash_out": 100400.00,
                  "is_demo": true, "source": "独立模拟账户流水 demo_account_ledger_v1",
                  "status": "available"},
      "sales": {"amount": 126100.00, "gross_profit": 43100.00,
                "gross_margin_pct": 34.2, "amount_7d": 126100.00,
                "gross_margin_7d_pct": 34.2, "change_pct": 0.0},
      "inventory": {"cost": 155300.00, "risk_cost": 55600.00,
                    "risk_count": 13, "risk_store_count": 8,
                    "stockout_risk_count": 5, "turnover_days": 13.1,
                    "sku_count": 19, "store_sku_count": 313},
      "purchase_commitments": {"amount": 54600.00, "count": 100,
                               "horizon_days": 30, "status": "available",
                               "source": "独立合成的已确认采购付款计划"},
      "pending_approvals": {"amount": 3200.00, "known_amount": 3200.00,
                            "count": 1, "missing_count": 0,
                            "basis": "当前待审批方案涉及的商品成本；不是预计回款或确定支出"},
      "trend": [{"date": "2026-09-27", "sales": 18000.00,
                 "gross_profit": 6100.00, "cash_balance": 838000.00,
                 "cash_in": 18000.00, "purchase_outflow": 12000.00,
                 "operating_outflow": 3200.00}],
      "stores": [{"store_id": "STORE-005", "store_name": "临平东湖店",
                  "sales": 3512.00, "gross_profit": 1159.00,
                  "gross_margin_pct": 33.0, "inventory_cost": 6474.00,
                  "risk_cost": 3850.00, "turnover_days": 19.3,
                  "risk_count": 1, "primary_risk": "门店错配", "risk_types": ["门店错配"],
                  "risk_items": [{"risk_id": 5, "sku": "SKU-79033", "product": "山楂果脯礼盒 1kg",
                                  "inventory_cost": 3850.00, "risk_label": "门店错配",
                                  "reason": "门店间销量差异需进一步核查"}]}],
      "metadata": {"is_demo": true, "source": "零食仓 · 合成零售经营样例 v1",
                   "currency": "CNY", "missing": [], "assumptions": []}
    }

以上数字只是展示字段格式的示意值，联调时必须读取接口返回值，不能把示意值写死在页面。

## 4. 滞销诊断

GET /api/v1/risks 返回 {"items": Risk[], "total": number}。真实库存模式还返回 filtered_total、display_limit 与 calculation_version，支持 priority=P1|P2|P3。

Risk 的当前核心字段：id、sku、product、store、store_id、sales_30、inventory_qty、unit_cost、days_to_sell、risk_type、priority、observation、evidence_level、missing_fields、teacher_baseline。当前演示可按门店商品维度在客户端排序和筛选；详情必须调用 GET /api/v1/risks/{risk_id}。

详情返回 risk、comparison、facts、diagnosis、factors、evidence。展示证据与缺项时以详情响应为准。库存覆盖天数表示按近 30 天销量推算的周转，不表示商品保质期；近 30 天销量为 0 时不能显示“0 天”。

核查闭环：
1. POST /risks/{risk_id}/investigations，body 为 {"actor_id":"demo-user"}。
2. POST /investigations/{investigation_id}/feedback，body 包含 raw_text、timezone、actor_id。
3. POST /feedback/{feedback_id}/confirm，body 包含 confirmed 与 actor_id。
4. 新事实使旧方案失效时，按后端状态提示重新计算；必要时 POST /risks/{risk_id}/replan。

## 5. 三个可计算工作台

module_type 的合法值：transfer、expiry-rescue、procurement-brake。

GET /api/v1/workbenches/{module_type}?risk_id=1 返回：

    {
      "module_type": "transfer",
      "mode": "sample_replay",
      "snapshot_id": "snapshot-demo-v1",
      "items": [],
      "risk": {},
      "input": {},
      "calculation": {"valid": true, "errors": []},
      "draft": {"status": "not_saved", "version": 0},
      "proposal": null,
      "tasks": []
    }

transfer 额外提供 transfer_network；expiry-rescue 额外提供 expiry_queue。input 由后端返回并作为编辑表单初值，前端只修改用户选择的字段，其余字段原样带回。三种工作台当前可编辑字段如下：

| module_type | 用户可编辑字段 | 关键展示 |
|---|---|---|
| transfer | target_store_id、quantity | 调出与调入库存前后、可售天数、运费、候选门店路线 |
| expiry-rescue | transfer_qty、promo_qty、promo_price、return_qty | 正常预计销售、批次剩余、处置数量守恒 |
| procurement-brake | action、adjustment_qty、new_payment_date | 原计划与调整后采购、在途、库存位、付款压力 |

统一操作顺序：
1. 输入变更后可 POST /workbenches/{module_type}/draft，body 为 {"input":{...}}；旧 calculation 应标记为待重新计算。
2. POST /workbenches/{module_type}/calculate，body 同上；读 calculation.valid 和 calculation.errors，校验失败不能保存或审批。
3. POST /workbenches/{module_type}/save，body 同上；成功返回 proposal、calculation。此时只是草稿。
4. POST /proposals/{proposal_id}/submit；成功后进入待审批。
5. POST /proposals/{proposal_id}/approve；仅审批当前版本。事实或输入变更后旧版本不可沿用。
6. POST /proposals/{proposal_id}/execute 只生成待执行任务；实际出库、改价、采购单调整仍需人工或外部系统回执。

状态展示和操作按钮必须以最新响应为准，不可仅靠前端乐观修改。相关列表可由 GET /proposals 和 GET /execution-tasks 刷新。

今日工作台的「待我审批」只展示 pending_approval。审批成功后切换到「审批后跟进」：approved 方案显示「已审批 · 待生成任务」，提供生成待执行任务入口；生成后由 execution-tasks 中的任务继续展示，避免重复显示。received／completed 任务进入「已完成」。审批通过不代表已派给门店，生成任务也不代表已经实际执行；历史 approved 方案同样必须可见。

## 6. 会话式现金流模拟

先 GET /api/v1/retail/simulation-options 获取：

    {
      "stores": [{"id": "STORE-001", "name": "西湖文三店"}],
      "categories": ["坚果炒货", "饮料乳品"],
      "is_demo": true,
      "source": "零食仓 · 合成零售经营样例 v1",
      "as_of_date": "2026-10-03"
    }

用户输入自然语言后，页面先呈现会话和待确认的场景卡；确认后才调用 POST /api/v1/retail/simulate。结果未生成前只显示会话页，生成后右侧展开结果。

请求：

    {
      "horizon_days": 14,
      "reduction_pct": 20,
      "store_id": "all",
      "category": null,
      "request_text": "未来两周少采购 20%，会不会缺货？"
    }

约束：horizon_days 为 1—90 的整数；reduction_pct 为 0—100 的数；store_id 来自 options，all 表示所有门店；category 为 options 中的品类或 null。当前版本只计算“减少可调整采购数量”情景，不计算任意自然语言动作。识别不出的条件应提示用户补充，不应复用上一个场景直接运行。

成功响应核心结构：

    {
      "status": "completed",
      "is_demo": true,
      "source": "零食仓 · 合成零售经营样例 v1",
      "scenario": {"horizon_days": 14, "reduction_pct": 20,
                   "store_id": "all", "store_name": "全部门店",
                   "category": null, "request_text": "未来两周少采购 20%，会不会缺货？",
                   "start_date": "2026-10-03", "end_date": "2026-10-16"},
      "metrics": {
        "purchase_outflow": {"baseline": 128000, "scenario": 115200, "delta": -12800},
        "ending_inventory_cost": {"baseline": 860000, "scenario": 842000, "delta": -18000},
        "stockout_risk_count": {"baseline": 4, "scenario": 6, "delta": 2}
      },
      "weekly": [{"label": "第1周", "start_date": "2026-10-03",
                  "end_date": "2026-10-09", "baseline": 64000, "scenario": 57600}],
      "risks": [{"sku": "SN-001", "product": "香辣薯片 110g",
                 "store_id": "STORE-001", "store_name": "西湖文三店",
                 "baseline_days": 7, "scenario_days": 3,
                 "safety_days": 5, "risk_level": "watch",
                 "shortage_qty": 0, "is_new_risk": true}],
      "metadata": {"is_demo": true,
                   "units": {"money": "CNY", "coverage": "days",
                             "risk_count": "store_sku"},
                   "missing": [], "assumptions": []}
    }

以上数值仅为结构示意。delta = scenario - baseline，负值代表对应金额减少；风险数为门店 × 商品组合数，不是“商品种类数”。weekly 是分周采购现金流出，不是账户余额。真实库存模式若缺少采购、在途、需求和付款计划，返回 status=unavailable、metrics=null、weekly=[]、metadata.missing，前端展示缺项提示，不显示演示数字。

## 7. 错误、联调和交接

- 参数非法、门店或品类无效：HTTP 422，body 中的 detail 为用户可读原因。
- 资源不存在或无权限：HTTP 404。
- 方案状态冲突：HTTP 400 或 409；前端保留输入并提示重取最新方案。
- 网络错误、超时：前端保留当前编辑内容，展示重试入口；审批和执行按钮避免重复提交。
- 对于后端尚未实现的字段，以 null、空数组和 metadata.missing 表达，不在前端硬填演示值。

魏交给朱的开工包：
1. 把本文件及代码提交并推送到 lanyangyang 分支；通知朱使用该分支的最新提交。
2. 共同确认字段名、单位、状态值以及以上三类示例响应；有改动先更新本文件再改代码。
3. 朱启动本地服务后访问 /docs 或 /openapi.json 查看实时接口，并按本文件先做页面、加载、空状态和错误状态；魏继续实现计算和数据接入。
4. 联调顺序：经营总览 → 滞销诊断 → 调拨 → 近效期 → 采购刹车 → 会话模拟 → 审批与执行。
5. 验收至少覆盖：演示/真实数据来源、金额与百分比单位、输入变更后旧测算失效、无数据与 422 错误、模拟前后的页面状态、审批版本和重复点击。

仓库权限与分支是独立条件：朱必须能访问仓库，并从 lanyangyang 分支拉取。若朱在其他分支开发，需先约定如何合并契约变更。

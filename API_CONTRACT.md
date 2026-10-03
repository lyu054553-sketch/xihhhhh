# 货不压钱｜连锁零售库存资金 Agent API Contract

版本：v1.3（版本检查、库存文件接入与人工回执）
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
- X-Tenant-Id 与 actor_id 当前仍是原型参数，不构成可信身份；认证和角色授权另批交付。
- 写操作必须携带读到的版本号，详见第 5、8 节；缺失返回 422，陈旧版本返回 409。前端不能自动改用新版本再次审批，必须让用户重新查看并确认内容。

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
4. 新事实使旧方案失效时，POST /risks/{risk_id}/replan，body 为 {"expected_version": 当前方案版本}。

当前没有模型接入。反馈草稿返回 extraction_status=manual_required、factors=[]、current_status=unknown，并保留原文和日期解释。人工确认数值时，confirmed 可包含 observed_values（仅 inventory_qty、sales_30、unit_cost）及非空 evidence_ref；确认的数量必须为非负整数，金额必须非负且有限。人工证据不视为外部系统独立核验。重复确认相同内容不递增事实版本；相同反馈 ID 的不同确认内容返回 confirmation_conflict，需新增反馈版本。

确认、纠正或撤回会更新事实版本，失效未生成执行任务的旧方案并清除旧草稿计算结果。已生成任务的历史方案保持留档，继续生成任务时仍会检查当前事实。纠正／撤回入口为 POST /feedback/{feedback_id}/revisions，body 为 {"status":"corrected"} 或 {"status":"withdrawn"}；对应案例退出有效案例集，数值事实按仍有效的确认记录恢复。原始文件快照保持不变，真实诊断详情显示 source_inventory_qty、current_fact_version 和 fact_source 以区分文件原值与人工确认值。

重算会实际调用原业务计算器，用当前事实重算原动作；调拨量会按库存与接收容量缩减。生成新 pending_approval 版本，diff.calculation_recomputed=true，旧版仍不可审批。原动作不可行时返回 409 并保持 replan_pending；不会把计算失败记为成功。跨动作自动选择及自然语言原因理解待模型批次实现。

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
1. 输入变更后可 POST /workbenches/{module_type}/draft，body 为 {"expected_version": draft.version, "input":{...}}；未建草稿时版本为 0，旧 calculation 标记为待重新计算。
2. POST /workbenches/{module_type}/calculate，body 同上；读 calculation.valid 和 calculation.errors，校验失败不能保存或审批。
3. POST /workbenches/{module_type}/save，body 为 {"expected_version": draft.version, "expected_proposal_version": proposal.current_version, "input":{...}}；尚无方案时 expected_proposal_version=0。成功返回 proposal、calculation、draft，此时只是草稿；草稿与方案一起保存或一起回滚。
4. POST /proposals/{proposal_id}/submit，body 为 {"expected_version": proposal.current_version}；成功后进入待审批。
5. POST /proposals/{proposal_id}/approve，body 同第 4 步；仅审批明确读到的当前版本。事实或输入变更后旧版本不可沿用。
6. POST /proposals/{proposal_id}/execute，body 同第 4 步，只生成待执行任务；实际出库、改价、采购单调整仍需人工或外部系统回执。

版本号必须为 JSON 整数，不能使用字符串或布尔值。每次 draft／calculate／save 都会推进草稿版本，下一步使用本次响应的新版本。输入中只允许修改表格列出的可编辑字段；库存、成本、销量、安全库存、批次、路线容量和费用从服务端取值。允许回传完整 input，但只读字段必须与服务端一致。缺少真实订单、批次和配送规则时返回 missing_business_data，不能以演示参数补全真实工作台。

approve 与 execute 会在数据库事务内检查同一批次库存、收货容量及采购行剩余数量，并保存占用；多个方案合计不能超过同一资源容量。已生成任务的占用不会因编辑或人工完成记录被释放，需新的库存快照才能重新核算。修改未执行方案会释放其旧占用并失效旧审批。幂等键按租户、操作、方案隔离；同键重试原版本返回原记录，用于不同版本返回 idempotency_conflict。

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

## 8. 真实库存文件接入

POST /api/v1/data-center/imports 使用 filename、data_kind="inventory"、content（CSV/TSV 文本）或 file_base64（XLSX），可带 sheet_name、as_of_date、actor_id。格式限制为 .csv/.tsv/.xlsx，上传内容上限 5MB；指定工作表不存在时失败，不改用第一张表。

冻结的库存格式：

| 字段 | 要求 |
|---|---|
| sku、store、unit | 必填非空字符串；单位不自动换算 |
| inventory_qty | 必填，0 至 2147483647 的整数 |
| unit_cost | 必填，非负有限金额，人民币元，按分四舍五入；零与未知不同 |
| store_id、product | 可选，分别以 store、sku 作为默认标识／展示名 |
| sales_30、sales_90 | 可选，同数量范围；留空为未知 |
| sales_cost_30 | 可选，30 天销售成本，人民币元；留空为未知 |
| stat_class、purchase_status | 可选，原始分类／采购状态；老师分类为 A/B/C/D/Z/H |
| cost_amount | 可选；必须等于库存数量 × 四舍五入后的单位成本 |

可直接验证的 CSV：

```csv
sku,store,store_id,product,unit,inventory_qty,unit_cost,sales_30,sales_90,sales_cost_30,stat_class,purchase_status
SKU-001,门店一,S-001,示例商品,箱,100,12.50,10,30,125,C,在采
```

库存键为门店 ID＋SKU，同键完全一致的行去重；同键内容冲突或同 SKU 单位冲突，整个文件失败，保留已有快照。返回 errors[].row 与 message，数据行从第 2 行起计。格式／行校验失败返回 HTTP 200、status=failed，前端不能只看 HTTP 状态判断导入成功。成功为 status=imported，summary 含 snapshot_id、content_sha256、rows、deduplicated_rows、replayed。

成功导入在一个事务里保存正式快照、明细、可核查风险、批次和审计；同租户、日期、规范化行内容的重复文件复用原快照，不重复库存。新快照取代旧快照参与库存总览与老师口径计算，旧未执行方案失效；历史快照不被覆写，重复旧文件不会自动恢复它为当前快照。源文件时点未指定时保持 as_of_date=null，不以上传时间冒充业务时点。

老师口径缺少 sales_30、sales_90、sales_cost_30、stat_class 中任何输入时，teacher_baseline.status=blocked，缺项可查；已有确定库存金额仍能展示。真实队列优先使用已导入数据；核查中的人工数值覆盖只影响当前事实与详情计算，库存总览与候选选取仍以原始快照为依据，需新文件更新总览。账户、付款计划、效期、配送规则不在本次格式中，保持未知；不生成虚构调拨、采购或现金预测。真实 work-items 显示候选核查事项，负责人和截止时间未接入时为 null。

sales／purchase／expiry 类型本批仅格式校验，返回 status=validated_only；不能称为已进入业务计算。

## 9. 导出、执行草稿与人工回执

GET /api/v1/proposals/{proposal_id}/export?version=2 下载指定历史版本的 JSON 建议单。响应带 Content-Disposition: attachment；包含 proposal_id、proposal_version、snapshot_id、status、created_at、payload、external_write=false。历史内容不可覆写，后续失效状态会显示在导出文件里。

POST /api/v1/proposals/{proposal_id}/execute 返回任务，初始 status=draft_pending_external_execution、version=1、metadata.external_write=false，不会修改外部库存、价格或采购单。

POST /api/v1/execution-tasks/{task_id}/status 示例：

```json
{"expected_version":1,"status":"completed","receipt_ref":"人工回执-001","actual_cash":1400,"confirmation_method":"manual"}
```

通常顺序为 draft_pending_external_execution → pending_dispatch → in_transit → awaiting_receipt → received → completed，可记录 exception 后转回 pending_dispatch。显式人工确认允许直接 received／completed，但必须有非空 receipt_ref；confirmation_method 目前只支持 manual，响应保存 confirmed_by 和 timeline，不冒充外部系统确认。actual_cash 为可选非负金额，按分四舍五入；未知保持 null。金额是人工登记的观察回款，不视为系统因果归因后的收益。

每次更新推进任务 version；陈旧回执返回 409。已完成任务不能回退或覆盖最终回执，相同最终回执重试不再更新版本。未接入原系统对账和回执校验接口。

## 10. 冲突及演示边界

HTTP 409 的业务冲突格式为：

```json
{"detail":{"code":"version_conflict","message":"版本已更新，请重新读取后确认","current_version":3}}
```

其他 code 包括 inventory_conflict、facts_changed、stale_snapshot、missing_business_data、no_feasible_plan、invalid_transition、confirmation_conflict、idempotency_conflict。仅版本冲突带 current_version。普通业务输入错误为 HTTP 400、detail 字符串；请求结构错误为 HTTP 422。

GET /health 仅返回状态和 API 版本，不返回数据库路径。静态服务仅开放产品页面／脚本／样式及 assets；源码、数据库、配置、Git 目录和交付压缩包不可从网页下载。

POST /demo/reset 默认返回 403，仅当 INVENTORY_AGENT_MODE=demo 且 INVENTORY_AGENT_ALLOW_DEMO_RESET=1 时启用；已有真实库存快照时仍返回 409，其他租户数据不会被删除。此开关仅用于独立演示数据库。

v1.3 是接口变更。朱需按新版版本字段、导入状态、手工确认状态和冲突结构更新前端，并完成浏览器验收。后端交付和复验说明见 docs/backend/DELIVERY_20261003.md。

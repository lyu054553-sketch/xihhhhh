# 总集成准备｜交给后端队友

日期：2026-10-04  
范围：补齐公共 HTTP 契约与共享客户端，并将任务框 5、6 接入现有工作台导航；未实现后端路由，也未进行真实 API 联调。

## 需要后端实现的契约变更

### 1. 方案比较接收动作级业务输入

`POST /api/v1/hackathon/proposals/compare` 请求新增可选 `business_inputs`。只传本次用户提供或确认的动作输入；计算服务须重新读取事实、验证约束并计算，不接受浏览器提交的金额或库存结果。数量必须带 `base_unit`。

```json
{
  "business_inputs": {
    "transfer": {
      "origin_store_id": "ST-001", "target_store_id": "ST-002",
      "sku_id": "SKU-001", "lot_id": "LOT-001-001",
      "quantity": 80, "base_unit": "盒", "route_id": "ROUTE-ST001-ST002",
      "route_fee_cny": 24
    },
    "promotion": {
      "products": [{"sku_id": "SKU-001", "quantity_per_bundle": 1, "base_unit": "盒"}],
      "price_stages": [{"label": "第一阶段", "price_cny": 11, "start_date": "2026-10-05", "end_date_exclusive": "2026-10-12"}]
    },
    "return": {
      "supplier_id": "SUP-002", "sku_id": "SKU-006", "lot_id": "LOT-006-001",
      "quantity": 100, "base_unit": "桶", "settlement_method": "refund", "fee_cny": null
    },
    "procurement": {
      "supplier_id": "SUP-001", "purchase_order_id": "PO-001", "sku_id": "SKU-004",
      "quantity": 60, "base_unit": "袋", "unit_cost_cny": 5,
      "expected_arrival_date": "2026-10-10", "payment_date": null
    }
  }
}
```

完整字段与语义以 [`PARALLEL_CONTRACT.md`](../PARALLEL_CONTRACT.md) 第 7 节为准。用户未提供的值可以省略；显式 `null` 表示保留未知。未确认的采购意向、退供条款或供应商接受状态不能被提升为已确认事实。

### 2. 候选返回逐门店的调拨库存前后值

比较响应的候选新增必填 `inventory_changes[]`；没有库存位置变化时为空数组。每行格式：

```json
{
  "store_id": "ST-001", "sku_id": "SKU-001", "lot_id": "LOT-001-001",
  "quantity_before": 120, "quantity_after": 40, "quantity_delta": -80,
  "base_unit": "盒", "source_ref": "02_库存与90天经营事实.xlsx#INV-001"
}
```

数值由计算服务返回。前端只投影，不按调拨数量加减。这里的 before/after 是动作即时前后库存，不是预测周期末数量；`calculation.ending_qty` 仍表示候选批次在比较周期的计算结果。

### 3. 提供待确认方案列表

新增 **GET `/api/v1/hackathon/proposals?scenario_id=...&branch_id=...&status=pending_approval`**。返回 `{contract_version, proposals[], metadata}`；方案至少含 `proposal_id/proposal_version/status/context/candidate_id/action_type/title/risk_keys/action_lines/created_at/updated_at/missing_fields`。筛选待确认状态时返回空数组而非省略字段。它与同路径的方案保存 POST 共存。

### 4. 提供首页经营总览聚合

新增 **GET `/api/v1/hackathon/overview?scenario_id=...&branch_id=...&snapshot_id=...&as_of=...`**。前端需要四项首页数值：

- `account.balance`
- `inventory.cost` 与 `inventory.risk_cost`
- `purchase_commitments.amount`（快照日后 30 天内已确认付款）
- `stores[]`：`store_id/store_name/inventory_cost/risk_cost/turnover_days/primary_risk/work_item_id/work_item_label/pending_label/missing_fields`

另返回 `pending_approvals {count, amount, known_amount, missing_count}` 和 `metadata {is_demo, source, as_of_date, as_of, data_version, fact_version, source_refs, missing_fields}`。未知金额用 `null`；不能通过前端事件汇总推算账户余额、库存成本或待付金额。首页原型固定四张指标卡，待审批指标可供其他宿主入口使用。

### 5. 材料接口采用完整事实上下文和幂等键

- **POST `/api/v1/hackathon/materials/extract`** 的 JSON body 使用 `context: FactContext`、`kind/text/source_name`。multipart 以 JSON 字符串字段 `context` 传同一完整上下文，其他文本／文件字段保持独立；请求带 `Idempotency-Key`。
- **POST `/api/v1/hackathon/materials/{draft_id}/confirm`** 继续要求 `expected_fact_version/actor_id/fields`，并要求 `Idempotency-Key`。
- 共享客户端签名已统一为 `extractMaterial(input, idempotencyKey)` 和 `confirmMaterial(draftId, body, idempotencyKey)`。响应与错误遵守 `hackathon.v1`，不在失败时回退 fixture。

## 宿主挂载参数

任务 5 和任务 6 均使用 `mount(container, { api, navigate, context })`，context 使用 camelCase：

```js
{
  tenantId, scenarioId, branchId, snapshotId, asOf,
  dataVersion, factVersion, isDemo, sourceRefs, missingFields,
  area, horizonStart, horizonEnd, assumptionIds,
  riskId, storeId, skuId, lotId, actorId,
  proposalId, proposalVersion, taskId, businessInputs
}
```

组件返回 `{destroy(), updateContext(nextContext)}`，事件和路由见公共契约第 12 节。写请求的 HTTP body 使用 snake_case。`actorId` 只是原型请求参数，不代表身份已认证。

## 修改文件与当前状态

- `docs/PARALLEL_CONTRACT.md`：补齐请求／响应字段、计划路由、预览边界与挂载上下文。
- `assets/hackathon/shared/api-client.js`：新增 `listProposals/getOverview`；材料 helper 携带完整上下文和幂等键。
- `assets/hackathon/decision/decision-workbench.mjs`：透传动作输入、映射库存变化、统一材料 helper；fixture 模式禁用确认、材料写入和 Agent 启动。
- `assets/hackathon/followup/followup.js`：独立读取待确认方案、任务与首页总览；接受统一 camelCase context。
- `index.html`、`app.js`：增加 `decision-entry`、`execution-followup` 页面和原版左侧导航入口；页面路由事件驱动组件挂载和卸载。
- `assets/hackathon/integration.js`、`integration.css`：注入统一 camelCase context、共享 API client 与宿主导航；样式仅作用于两个新模块根节点，颜色、字体、标签页和留白向原版绿色工作台对齐。
- `assets/hackathon/preview.html`：切换到原版工作台外壳中的两个只读 fixture 预览；也可在主应用显式加 `?hackathonPreview=1` 查看。
- 主应用普通路由使用 HTTP client；主应用只有显式预览参数才启用 fixture。独立组件预览页也保持显式只读 fixture。任何模拟写操作都不会标成真实接口成功。

上述 `/hackathon/*` 服务端路由仍未在 `backend/api.py` 注册。后端到齐后再按公共契约注册路由并进行真实联调；当前前端预览不能用于证明后端成功。

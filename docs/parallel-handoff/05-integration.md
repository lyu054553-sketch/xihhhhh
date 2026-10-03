# 总集成变更说明

日期：2026-10-04

分支：`integration/backend-merge-01`
合并基线：`a4a7058`

## 接线范围

- 在现有 `backend.store.Store` 上注册事实与风险、确定性计算、Agent／材料、执行／现金四个模块。启动时执行模块迁移、安装共享服务图，并只向隔离演示租户 `hackathon-demo` 装载合成场景。
- 新增 `backend/hackathon_routes.py`，由 `backend/api.py` 注册 `/api/v1/hackathon/*`：事实／风险、比较／保存／待审批列表／确认、首页总览、任务／案例／核算、渠道动作／业务事件、回放、Agent Run、材料上传与草稿确认。旧零售 API 和旧首页入口保留。
- 在本地静态代理逐条放行新模块所用 HTTP 路径及 multipart 请求；代理请求上限为 6 MiB，材料图片本身上限为 5 MiB。

## 公共 DTO 与业务语义

- 比较请求使用公共 `business_inputs.transfer/promotion/return/procurement` 字段；适配器验证声明字段与基础单位，再转换为计算服务内部输入。观察期沿用 `horizon_start/horizon_end`，起点必须等于当前事实日期，结束日为半开区间边界。
- `promotion.sales_settlement_days` 可用于提供阶段现金日期所需的结算周期；阶段价格通过事实中的 `stage_id` 匹配，组合定义仍由服务端事实负责。
- 比较响应统一包含 `candidate_groups`（无组合时为空列表）和候选 `inventory_changes`。调拨行返回按批次划分的执行前后数量、增量、单位与来源；不代表预测期末数量。
- 首页总览返回账户、库存、已确认采购承诺、待确认方案及门店数据。未知保持 `null`，采购意向不会计为已确认应付。方案确认必须提供负责人和截止日期。
- 供应商回复与条款复核事件写为 `supplier_reply_recorded`／`supplier_terms_reviewed`；文字记录不会转成供应商接受事实。重复事件先按幂等键查重，再检查版本，避免成功重试被旧版本拒绝。
- 写操作须携带 `actor_id` 和 `Idempotency-Key`。`actor_id` 仅作当前原型审计字段，不代表身份认证；本地渠道写入明确 `is_demo=true/external_write=false`。

## 前端与预览

- 两个模块在原版 `app.js` 外壳内统一使用 `{ api, navigate, context }` 挂载参数和 camelCase 宿主上下文；共享 API 客户端负责 snake_case 传输。原版 `styles.css`、导航、卡片、颜色、字体和间距保持为基础，新增样式限定在组件根节点。
- 正式挂载使用 HTTP client；开发预览使用显式只读 fixture，HTTP 失败不会降级成 fixture。预览入口：`assets/hackathon/preview.html`，以及原版 hash `#decision-entry` / `#execution-followup`。
- 图片上传会存档原图和提取草稿。测试配置未提供 vision provider，故状态保持 `failed`／人工复核，可继续人工编辑；不将上传成功说成识别成功。Agent Run 也以持久化的 `unavailable` 状态返回，不触发外部模型。

## 联调与验证

- S01 经已注册 HTTP 路由串过事实查询、风险、比较、保存、待审批列表、原子确认、任务详情／列表、时钟回放和核算。确认重试复用原结果。调拨源批次从 120 到 40，目标批次从 0 到 80；金额由服务返回。
- S07 采购输入按 10 月 17 日观察期算出 60 件及计划付款差额；S06 促销输入覆盖两阶段价格及结算周期；S05 退款路径保留供应商接受、包装和验收缺项，不允许确认。
- 图片 multipart 路由验证原图可读回、不可用模型配置不伪报识别；Agent Run 同样验证不可用状态。
- 已通过 177 项后端模块回归、3 项 HTTP 集成测试、16 项前端模块 Node 测试及 19 项本地 TCP 代理测试。完整模块回归首次发现 `candidate_groups` 无组合时未返回，已改成始终返回空列表并将该字段纳入必需 DTO；重跑全套后通过。

## 已知验收边界

- S05 在缺供应商本次接受、包装确认、验收日期时保持不可确认；只有拿到这些真实输入后才适合继续走执行／到账流程。
- CUA 截图捕获环境异常，本轮没有宣称完成截图级 UI 核验。两个预览仍可查看；需要像素对照时可上传决策台和跟进页截图，按原版绿色主页面人工比对。
- provider 未配置，所以本轮验证的是上传、持久化、失败标记和人工复核入口，不是 OCR／视觉模型识别质量或真实模型输出。

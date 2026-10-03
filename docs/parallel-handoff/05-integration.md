# 总集成变更说明

日期：2026-10-04

分支：`integration/backend-merge-01`
总集成保存提交：`cd3d180`（基于 `a4a7058`）
后端增量：`9b2b3fa` ← `c62827e`、`42ffc8d` ← `a1bbad6`、`0deab15` ← `92e59d3`、`8a7ee8f` ← `54d995b`

## 接线范围

- 在现有 `backend.store.Store` 上注册事实与风险、确定性计算、Agent／材料、执行／现金四个模块。启动时执行模块迁移、安装共享服务图，并只向隔离演示租户 `hackathon-demo` 装载合成场景。
- 新增 `backend/hackathon_routes.py`，由 `backend/api.py` 注册 `/api/v1/hackathon/*`：事实／风险、比较／保存／待审批列表／确认、首页总览、任务／案例／核算、渠道动作／业务事件、回放、Agent Run、材料上传与草稿确认。旧零售 API 和旧首页入口保留。
- 在本地静态代理逐条放行新模块所用 HTTP 路径及 multipart 请求；代理请求上限为 6 MiB，材料图片本身上限为 5 MiB。

## 公共 DTO 与业务语义

- 比较请求使用公共 `business_inputs.transfer/promotion/return/procurement` 字段；`CalculationService` 是唯一输入校验和动作映射边界，HTTP 路由不再自行复制转换逻辑。保存与确认会原样保留并重算同一业务输入。观察期沿用 `horizon_start/horizon_end`，起点必须等于当前事实日期，结束日为半开区间边界。
- 兼容前端传入的公共 `sales_settlement_days`、促销阶段 `stage_id`、采购 `intent_id/new_payment_date`，仍按事实版本校验；调拨源批次、目标批次和退供移动由服务返回即时库存差。省略批次时仅在门店商品事实列表证明范围完整时推导同批次为零；未知数量保留 null。
- 比较响应统一包含 `candidate_groups`（无组合时为空列表）和候选 `inventory_changes`。调拨行返回按批次划分的执行前后数量、增量、单位与来源；不代表预测期末数量。
- 首页总览返回账户、库存、已确认采购承诺、待确认方案及门店数据。未知保持 `null`，采购意向不会计为已确认应付。方案确认必须提供负责人和截止日期。
- 经营总览调用 `FactService.get_overview`；执行读服务只追加待确认方案成本、门店任务链接与 `task_links[]`。`GET /proposals`、`/tasks`、`/tasks/{id}`、`/cases/{id}` 改为调用新增的执行读取服务，读取不重算、不调用模型、不写业务记录；`case_id` 映射稳定 `proposal_id`。
- 公共 `FactService` / `ExecutionService` Protocol 已声明总览及列表、详情读取方法。HTTP GET 接受上下文版本核对与方案／任务版本筛选；共享 API 客户端 `getTask/getCase` 现在接受 query 参数。
- 供应商回复与条款复核事件写为 `supplier_reply_recorded`／`supplier_terms_reviewed`；文字记录不会转成供应商接受事实。重复事件先按幂等键查重，再检查版本，避免成功重试被旧版本拒绝。
- 写操作须携带 `actor_id` 和 `Idempotency-Key`。`actor_id` 仅作当前原型审计字段，不代表身份认证；本地渠道写入明确 `is_demo=true/external_write=false`。

## 前端与预览

- 两个模块在原版 `app.js` 外壳内统一使用 `{ api, navigate, context }` 挂载参数和 camelCase 宿主上下文；共享 API 客户端负责 snake_case 传输。原版 `styles.css`、导航、卡片、颜色、字体和间距保持为基础，新增样式限定在组件根节点。
- 正式挂载使用 HTTP client；开发预览使用显式只读 fixture，HTTP 失败不会降级成 fixture。预览入口：`assets/hackathon/preview.html`，以及原版 hash `#decision-entry` / `#execution-followup`。
- 图片上传会存档原图和提取草稿。测试配置未提供 vision provider，故状态保持 `failed`／人工复核，可继续人工编辑；不将上传成功说成识别成功。Agent Run 也以持久化的 `unavailable` 状态返回，不触发外部模型。

## 联调与验证

- S01 经已注册 HTTP 路由串过事实查询、风险、比较、保存、待审批列表、原子确认、任务详情／列表、时钟回放和核算。确认重试复用原结果。调拨源批次从 120 到 40，目标批次从 0 到 80；金额由服务返回。HTTP 读路径返回新执行服务 DTO，首页经营金额来自数据服务，不再使用路由内的重复计算。
- S07 采购输入按 10 月 17 日观察期算出 60 件及计划付款差额；S06 促销输入覆盖两阶段价格及结算周期；S05 退款路径保留供应商接受、包装和验收缺项，不允许确认。
- 图片 multipart 路由验证原图可读回、不可用模型配置不伪报识别；Agent Run 同样验证不可用状态。
- 本轮完整回归通过：214 项 hackathon 后端测试、53 项外围后端测试、3 项 HTTP 主线／材料刷新集成测试、16 项前端模块 Node 测试；本地 TCP 代理 19 项此前已通过。新增覆盖公共促销输入映射、版本化列表读取、草稿案例、调拨任务核算以及材料确认后刷新恢复。`.venv` 编译检查和 `git diff --check` 通过。

## 已知验收边界

- S05 在缺供应商本次接受、包装确认、验收日期时保持不可确认；只有拿到这些真实输入后才适合继续走执行／到账流程。
- CUA 截图捕获环境异常，本轮没有宣称完成截图级 UI 核验。两个预览仍可查看；需要像素对照时可上传决策台和跟进页截图，按原版绿色主页面人工比对。
- provider 未配置，所以本轮验证的是上传、持久化、失败标记和人工复核入口，不是 OCR／视觉模型识别质量或真实模型输出。

## 2026-10-04：后端增量合入说明

- `c62827e` 加入动作级输入校验及批次库存前后量；总集成将旧 HTTP 转换器删除，输入冲突、`null` 缺项、供应商／路线／单位和意向 ID 校验统一由 `CalculationService` 处理。`business_inputs` 在保存、确认重算时保持原样，解决了业务输入丢失导致候选 ID 不一致的问题。
- `a1bbad6` 修复材料草稿确认上下文与刷新恢复。确认响应和已确认草稿都保留发布后的完整上下文；旧记录若没有可验证确认上下文，返回 `context=null`，不伪造历史。
- `92e59d3` 引入版本化事实总览；HTTP 层移除临时账户、库存、风险和采购付款重算，调用事实层提供的唯一投影。
- `54d995b` 增加 proposal/task/case/overview 读服务；HTTP 路由和共享 Protocol 已接线，禁止读取时隐式比较或写入。四个上游提交为线性依赖，未 cherry-pick `5deb452` 合并提交；清新绿原版 `app.js/index.html/styles.css` 与两模块挂载没有被后端增量覆盖。
- 上游映射：`origin/zmj` 的 `c62827e/a1bbad6/92e59d3/54d995b` 对应本分支 `9b2b3fa/42ffc8d/0deab15/8a7ee8f`。如后端模块继续修改这些边界，先更新 `02-calculations.md`、`03-ai-materials.md`、`01-data-risk.md` 或 `04-execution-cash.md`，再同步 `PARALLEL_CONTRACT.md`、`backend/hackathon_shared.py` 与该 API 路由。

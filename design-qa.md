# 滞销库存诊断 · 设计核对

## 对比对象

- Source visual truth: locally supplied diagnostic-workbench reference image (not included in this repository).
- Rendered implementation: in-app browser `http://127.0.0.1:8000/#slow-diagnosis`，2026-09-20 采集的浏览器渲染截图（1280 × 720 CSS px，device scale factor 1）。
- Source pixels: 1536 × 1024. The browser viewport is shorter than the reference, so comparison is limited to the shared header, KPI, and analytical-card region rather than vertical crop extent.
- State: 真实库存快照、老师口径 `teacher-v1`、默认候选清单；另验证 P2 筛选状态。

## 对比证据

- Full view: 在同一轮核对中打开源图和浏览器渲染，核对了侧栏、页头、四个 KPI、三栏分析区和清单入口的层级。
- Focused checks: 切换“门店分布”“数据覆盖”；搜索“阿胶”；选择 P2 后显示 `300 / 3,026 条`，且 300 行均为 P2；打开一条“查看计算”后显示 7 条计算依据和 6 条待核查原因。

## Findings

- No P0/P1/P2 findings.
- Expected content deviations: reference uses演示性的原因占比、趋势曲线和商品缩略图；implementation replaces them with真实的优先级结构、门店候选库存金额和数据边界。这样避免把当前未接入的原因、趋势或图片数据伪装成事实。
- Expected brand deviation: implementation retains the existing product identity rather than copying the reference product identity.

## Required fidelity surfaces

- Fonts and typography: uses the existing system `PingFang SC` fallback stack and Material Symbols; page title, KPI numbers, labels and dense table hierarchy are visibly separated without truncating the critical KPI values.
- Spacing and layout rhythm: source-inspired header → 4 KPI → 3 analytical panels → tabbed list hierarchy is present; cards use the existing 8 px surface rhythm and responsive table scroll instead of clipping columns.
- Colors and visual tokens: keeps the existing white/blue business dashboard palette; P1/P2/P3 and missing-data states use distinct red/amber/blue/green semantic colors.
- Image quality and asset fidelity: no reference-specific product images are synthesized or substituted. The current data has no verified SKU image asset, so the data table intentionally starts with product name/SKU rather than a fake thumbnail.
- Copy and content: all main values come from the current `teacher-v1` snapshot. “建议压降库存金额” explicitly states that it is not recovered cash; unverified causal explanations remain “待核查”.
- Affordances and interaction: view tabs, search, priority filter, refresh, and per-item calculation detail are functional.
- Accessibility and responsiveness: filter controls have labels, tabs have `role=tab` and selected state, and wide tables scroll horizontally at constrained widths.

## Implementation checklist

- [x] Use actual teacher-baseline aggregation for KPI, priority, and store ranking.
- [x] Use the four requested business cards; expiry and replenishment metrics stay marked as “待接入” until their source fields are connected.
- [x] Keep causal diagnosis as evidence-gated rather than an asserted conclusion.
- [x] Make P1/P2/P3 filter fetch the corresponding real candidate set from the backend.
- [x] Verify default, tab, search, P2 filter, and calculation-detail states in the browser.

## Follow-up polish

- [P3] When verified SKU image assets are supplied by the master-data system, add them to the candidate rows; do not infer images from product names.

final result: passed

---

# 滞销诊断工作台 · 五页签核对

## 对比对象

- Source visual truth: four locally supplied diagnostic-workbench reference images (2160px wide; not included in this repository), plus the trend-card, title, and tab references supplied for that iteration.
- Rendered implementation: in-app browser `http://127.0.0.1:8000/#slow-diagnosis`，2026-09-20 浏览器渲染（1280 × 720 CSS px，device scale factor 1）。
- State: 当前真实库存快照；默认清单、原因分析、处置建议、门店分布、供应商分布均已实际切换核对。源图更高、更宽，因此比较聚焦相同内容区域和字段层级，而非整页像素等比。

## 对比证据

- Full view: 标题已移除“库存诊断”眉标和 `teacher-v1` 徽标；蓝色诊断图标紧跟在黑色标题之后。总览第三张分析卡已替换为“滞销商品趋势”。
- Focused checks: 五个页签均可切换；原因分析显示 8 条候选及全量“待核查”原因槽位；处置建议显示 8 条候选、处置字段为“—”；门店分布显示 31 家门店的真实库存成本、候选成本与占比；供应商分布明确显示字段未导入及 6 个“—”占位。
- Interaction checks: 页签切换、候选清单固定高度滚动、优先级筛选和“查看计算／发起核查”入口可用。

## Findings

- No P0/P1/P2 findings.
- Expected content deviation: 源图的原因、动作、供应商、退换条件和执行状态属于演示数据。实现仅展示当前快照可确认的库存、销量、成本与门店汇总；其余字段显示“—”或“待接入”。
- Expected trend deviation: 当前只有 1 期库存快照，不能画出真实 6 个月曲线；趋势卡显示本期真实候选数与库存金额，并明确标注“趋势待形成”。

## Required fidelity surfaces

- Fonts and typography: 保持现有中文业务台字体、蓝黑标题层级和紧凑表格字号；页签和卡片标题均避免关键字段截断。
- Spacing and layout rhythm: 采用参考图的“页签 → 标题指标 → 双栏分析卡 → 明细表”阅读顺序；所有明细表保留受控高度与滚动。
- Colors and visual tokens: 延续系统的蓝白背景与浅蓝信息面；未知值使用中性灰“—”，不误用红、黄、绿状态色。
- Image quality and asset fidelity: 未复用截图中的演示产品、供应商或图表素材；当前没有可验证 SKU 图片或供应商主数据，因此不生成替代资产。
- Copy and content: 标题、字段名和空态均对齐参考图语义，真实数值来自当前库存快照。
- Affordances and interaction: 五页签、明细表滚动、优先级筛选和计算入口均在浏览器实际验证。

## Implementation checklist

- [x] 移除 `老师口径 · 计算版本 teacher-v1` 徽标与“库存诊断”眉标。
- [x] 在标题文字后放置诊断图标。
- [x] 以“滞销商品趋势”替换数据边界卡，并标注单期快照限制。
- [x] 增加原因分析、处置建议、门店分布、供应商分布四个页签。
- [x] 将未接入的原因、处置与供应商字段标记为“—”或“待接入”。

## Follow-up polish

- [P3] 累积至少两期月度快照后，将趋势待形成状态替换为真实环比折线。

final result: passed

---

# 滞销候选清单 · 字段设计核对

## 对比对象

- Source visual truth: locally supplied five-tab diagnostic-workbench reference image (2256 × 790 px; not included in this repository).
- Rendered implementation: in-app browser `http://127.0.0.1:8000/#slow-diagnosis`，同一默认候选清单状态（1280 × 720 CSS px，device scale factor 1）。
- Focused comparison: 表格页签、筛选栏、表头和首屏候选行；源图更宽，因此以横向滚动表格的可见字段顺序为准。

## Findings

- No P0/P1/P2 findings.
- Expected content deviation: 源图中的商品缩略图、主要原因、建议动作和处理状态是演示数据。实现保留真实商品、门店、库存数量／金额、近90天销量和库存天数；其余三项显示“—”，不伪造诊断结论或执行状态。
- Expected interaction deviation: 当前系统保留“查看计算”这一真实入口，未复制无数据支撑的批量勾选、导出及演示性状态筛选。

## Required fidelity surfaces

- Fonts and typography: 与现有业务台一致，表头、商品名、SKU 和数值保持可读的层级。
- Spacing and layout rhythm: 使用固定 500px 高的表格框，表头置顶，字段按源图顺序排布；超出宽度时在框内横向滚动。
- Colors and visual tokens: 保持系统蓝白表格体系；无数据字段以中性灰色“—”呈现，不产生误导性的状态色。
- Image quality and asset fidelity: 当前没有经过验证的 SKU 图片素材，因此不以商品名称生成或猜测缩略图。
- Copy and content: 真实字段来自当前快照；缺失的原因、动作、状态清晰标为占位。
- Affordances and interaction: 搜索、优先级筛选、固定高度滚动和“查看计算”均保持可用。

## Implementation checklist

- [x] 更新为商品信息、门店、库存数量、库存金额、近90天销量、库存天数、主要原因、建议动作、处理状态、操作。
- [x] 为当前无证据字段使用“—”占位。
- [x] 保留表内固定高度滚动和置顶表头。
- [x] 在浏览器中核对 10 个表头、首行真实值／占位值及 300 条清单的可滚动范围。

final result: passed

import { formatYuan, formatNumber } from './retail-contract.mjs';

export const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const LABELS = {
  source:'数据来源',source_detail:'来源说明',as_of:'数据时点',as_of_date:'数据日期',snapshot_id:'库存快照',fact_version:'事实版本',current_fact_version:'事实版本',calculation_version:'计算版本',
  inventory_qty:'库存数量',sales_30:'近30天销量',unit_cost:'单位成本',days_to_sell:'库存覆盖天数',missing_fields:'缺少字段',assumptions:'计算假设',note:'说明',errors:'约束问题',
  source_store:'调出门店',target_store:'接收门店',target_store_id:'接收门店编号',quantity:'数量',unit:'库存单位',lot_id:'批次',sku:'商品编号',product:'商品',store:'门店',store_id:'门店编号',
  valid:'约束通过',allocation:'库存占用',limits:'数量约束',available_to_transfer:'最多可调出',receiving_capacity:'接收容量',before_after:'调拨前后',
  on_hand_before:'调整前库存',on_hand_after:'调整后库存',safety_stock:'安全库存',coverage_before:'调整前覆盖天数',coverage_after:'调整后覆盖天数',expiry_risk:'效期提示',
  economic:'预计避免报损',potential_loss_without_transfer:'不调拨的潜在报损成本',source_surplus_at_deadline_qty:'到期预计剩余',target_sale_before_expiry_qty:'接收店到期前预计销售',
  transport_fee:'运输费用',net_avoidable_loss:'扣除运费的预计避免报损',avoided_loss:'预计避免报损成本',cash:'现金口径',inventory_cost:'库存成本',estimated_net_cash_improvement:'预计净现金改善',known_cash_effect:'已知现金影响',completeness:'口径完整性',
  forecast:'数量分配',normal_sale_qty:'正常预计销量',transfer_qty:'调拨数量',promo_qty:'促销投放量',return_qty:'退供数量',expected_remaining_qty:'预计剩余数量',latest_disposal_date:'最晚处置日期',sellable_days:'剩余可售天数',alternatives:'处置比较',type:'方式',fee:'费用',cash_impact:'现金影响',remaining_risk:'剩余风险数量',assumption:'前提',
  inventory_position:'采购库存位',current_inventory:'当前库存',in_transit_qty:'在途数量',unexecuted_purchase_qty:'未执行采购量',adjusted_purchase_qty:'调整数量',remaining_purchase_qty:'调整后采购量',projected_after_adjustment:'调整后预计库存',
  payment:'付款压力',baseline_payment_date:'原付款日',scenario_payment_date:'调整后付款日',adjusted_amount:'调整涉及金额',baseline_in_window:'原付款在评估期内',scenario_in_window:'调整后付款在评估期内',deferred_payment_pressure:'后续付款压力',order:'采购单',po_number:'采购单号',line_number:'行号',arrival_date:'到货日期',payment_date:'付款日期',status:'状态',
  conclusion:'判断',observation:'观察事实',hypothesis:'待核查原因',evidence_level:'证据程度',supporting_refs:'证据引用',conflicts:'冲突',factors:'原因假设',causal_status:'因果关系',confirmation_status:'确认状态',date_interpretation:'日期解释',raw_text:'原始反馈',current_status:'当前情况',
  purchase_outflow:'预计采购支出',ending_inventory_cost:'期末库存成本',stockout_risk_count:'缺货风险门店商品数',baseline:'基线',scenario:'方案',delta:'方案减基线',baseline_days:'基线覆盖天数',scenario_days:'方案覆盖天数',safety_days:'安全库存天数',risk_level:'风险级别',shortage_qty:'缺货数量',is_new_risk:'新增风险',
  metadata:'来源与假设',basis:'方案依据',proposal_version:'方案版本',receipt_ref:'人工回执号',actual_cash:'人工填报现金',external_write:'已写入外部系统',timeline:'人工状态记录',
};
const MONEY = new Set(['unit_cost','inventory_cost','cost','risk_cost','balance','amount','known_amount','cash_in','cash_out','opening_balance','gross_profit','sales','risk_value','inventory_value','potential_loss_without_transfer','transport_fee','net_avoidable_loss','avoided_loss','estimated_net_cash_improvement','known_cash_effect','fee','cash_impact','adjusted_amount','deferred_payment_pressure','actual_cash','promo_price','purchase_outflow','ending_inventory_cost']);
export const labelFor = (key) => LABELS[key] || key;
export const STATUS_LABELS = {draft:'方案草稿',pending_approval:'待审批',approved:'已审批 · 待生成任务',execution_task_created:'已生成待执行任务',invalidated:'版本已失效',needs_replan:'需要重新计算',replan_pending:'重算待处理',draft_pending_external_execution:'执行草稿 · 待外部执行',pending_dispatch:'待发出',in_transit:'运输中',awaiting_receipt:'待回执',received:'人工记录已收货',completed:'人工记录已完成',exception:'执行异常',needs_recalculation:'输入变化 · 需重算',calculated:'已计算',saved:'已保存',not_saved:'未保存',blocked:'约束不通过',unavailable:'未接入／待补充'};
export function details(value, key='') {
  if(value == null) return '<span class="muted">未接入／待补充</span>';
  if(Array.isArray(value)) return value.length ? `<ul class="detail-list">${value.map(v=>`<li>${details(v)}</li>`).join('')}</ul>` : '<span class="muted">无记录</span>';
  if(typeof value==='object') return `<dl class="details-grid">${Object.entries(value).map(([k,v])=>`<div><dt>${escapeHtml(labelFor(k))}</dt><dd>${details(v,k)}</dd></div>`).join('')}</dl>`;
  if(typeof value==='boolean') return value ? '是' : '否';
  if(MONEY.has(key)) return escapeHtml(formatYuan(value));
  if(typeof value==='number') return escapeHtml(formatNumber(value));
  return escapeHtml(key==='status' ? (STATUS_LABELS[value] || value) : value);
}
export const panel = (title, body, tone='') => `<section class="status-panel ${tone}"><h2>${escapeHtml(title)}</h2>${body}</section>`;
export const list = (values=[]) => `<ul class="warning-list">${values.map(v=>`<li>${escapeHtml(typeof v==='string' ? (LABELS[v] || v) : JSON.stringify(v))}</li>`).join('')}</ul>`;
export const button = (action,text,disabled=false,extra='') => `<button type="button" class="secondary-button" data-action="${action}" ${disabled?'disabled':''} ${extra}>${escapeHtml(text)}</button>`;
export const metric = (title,value) => `<div class="metric"><span>${escapeHtml(title)}</span><strong class="value">${escapeHtml(value)}</strong></div>`;
export const source = (value) => `<p class="source-note">${value.is_demo===true?'合成演示数据':value.is_demo===false?'真实数据／未接入部分保留未知':'以返回的快照为准'} · ${escapeHtml(value.source || '')} · ${escapeHtml(value.as_of_date || '')}</p>`;
export function select(name,title,choices,value,extra='') {
  return `<label class="field"><span>${escapeHtml(title)}</span><select name="${name}" ${extra}>${choices.map(([id,label])=>`<option value="${escapeHtml(id)}" ${String(id)===String(value)?'selected':''}>${escapeHtml(label)}</option>`).join('')}</select></label>`;
}
export function input(name,title,value,{type='number',min=0,max,step='any',required=true}={}) {
  return `<label class="field"><span>${escapeHtml(title)}</span><input name="${name}" type="${type}" value="${escapeHtml(value)}" ${required?'required':''} ${type==='number'?`min="${min}" step="${step}" ${max===undefined?'':`max="${max}"`}`:''}></label>`;
}

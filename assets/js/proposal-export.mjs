import { validateProposal, validateExecutionTask } from './retail-contract.mjs';
import { LABELS } from './retail-view.mjs';

export const EXPORT_NOTICE = '执行准备资料；本次导出未自动写入 ERP，不代表审批或执行完成。';
const UNKNOWN = '未知（源数据未提供）';
const TYPES = { transfer: '跨店调拨', 'expiry-rescue': '近效期处置', 'procurement-brake': '采购调整' };
const STATUSES = { draft:'方案草稿', pending_approval:'待审批', approved:'已审批，待生成任务', execution_task_created:'已生成待执行任务', draft_pending_external_execution:'执行草稿，待外部执行', pending_dispatch:'人工记录待发出', in_transit:'人工记录运输中', awaiting_receipt:'人工记录待回执', received:'人工记录已收货', completed:'人工记录已完成', exception:'人工记录执行异常' };
const ACTIONS = { reduce:'减少采购量', cancel:'取消采购量', delay_arrival:'推迟到货', delay_payment:'推迟付款' };
const COMPLETENESS = { complete:'完整', partial:'部分数据', unavailable:'不可计算' };

// These are presentation schemas, not calculation rules. Every row is copied
// from its named API field; unknown fields are not added to business documents.
const COMMON_INPUT = [['product','商品'], ['sku','商品编号'], ['unit','库存单位'], ['unit_cost','单位成本','money']];
const INPUT = {
  transfer: [['lot_id','库存批次编号'],['batch','批次标识或日期'],['source_store','调出门店'],['source_store_id','调出门店编号'],['target_store','接收门店'],['target_store_id','接收门店编号'],['quantity','调拨数量','quantity'],['source_on_hand','调出门店库存','quantity'],['source_safety','调出门店安全库存','quantity'],['source_daily_sales','调出门店日均销量','daily'],['target_on_hand','接收门店库存','quantity'],['target_capacity','接收门店容量','quantity'],['target_safety','接收门店安全库存','quantity'],['target_daily_sales','接收门店日均销量','daily'],['sellable_days','剩余可售天数','days'],['eta_days','预计运输天数','days'],['eta_at','预计到达日期'],['transport_fee','运输费用','money']],
  'expiry-rescue': [['lot_id','库存批次编号'],['batch','批次标识或日期'],['store','门店'],['store_id','门店编号'],['inventory_qty','本批次库存','quantity'],['sales_30','近30天销量','quantity'],['sellable_days','剩余可售天数','days'],['latest_disposal_date','最晚处置日期'],['transfer_qty','调拨数量','quantity'],['transfer_fee','调拨费用','money'],['promo_qty','促销投放量','quantity'],['promo_price','促销单价','money'],['promo_fee','促销费用','money'],['return_qty','退供数量','quantity']],
  'procurement-brake': [['store','门店'],['store_id','门店编号'],['po_number','采购单号'],['line_number','采购单行号'],['action','采购调整方式','action'],['current_inventory','当前库存','quantity'],['in_transit_qty','在途数量','quantity'],['open_purchase_qty','未执行采购量','quantity'],['adjustment_qty','调整数量','quantity'],['safety_stock','安全库存','quantity'],['arrival_date','原到货日期'],['payment_date','原付款日期'],['new_payment_date','调整后付款日期'],['cutoff_date','评估截止日期'],['order_status','采购单状态']],
};
const CASH = [['inventory_cost','涉及库存成本','money'],['estimated_net_cash_improvement','预计净现金改善','money'],['known_cash_effect','已知现金影响','money'],['avoided_loss','预计避免报损','money'],['completeness','数据完整性','completeness'],['note','现金口径说明']];
const CALCULATION = {
  transfer: {
    '库存占用': ['allocation', [['lot_id','库存批次编号'],['quantity','占用数量','quantity']]],
    '数量约束': ['limits', [['available_to_transfer','最多可调出数量','quantity'],['receiving_capacity','接收容量余量','quantity']]],
    '调出门店变化': ['before_after.source', [['store','门店'],['on_hand_before','调整前库存','quantity'],['on_hand_after','调整后库存','quantity'],['safety_stock','安全库存','quantity'],['coverage_before','调整前覆盖天数','days'],['coverage_after','调整后覆盖天数','days'],['expiry_risk','效期提示']]],
    '接收门店变化': ['before_after.target', [['store','门店'],['on_hand_before','调整前库存','quantity'],['on_hand_after','调整后库存','quantity'],['safety_stock','安全库存','quantity'],['coverage_before','调整前覆盖天数','days'],['coverage_after','调整后覆盖天数','days'],['expiry_risk','效期提示']]],
    '报损估计': ['economic', [['potential_loss_without_transfer','不调拨的潜在报损成本','money'],['source_surplus_at_deadline_qty','到期预计剩余数量','quantity'],['target_sale_before_expiry_qty','接收门店到期前预计销量','quantity'],['avoided_loss','预计避免报损','money'],['transport_fee','运输费用','money'],['net_avoidable_loss','扣除运输费用后预计避免报损','money'],['note','估计说明']]],
  },
  'expiry-rescue': {
    '库存占用': ['allocation', [['lot_id','库存批次编号'],['quantity','占用数量','quantity']]],
    '处置数量': ['forecast', [['normal_sale_qty','正常预计销量','quantity'],['transfer_qty','调拨数量','quantity'],['promo_qty','促销投放量','quantity'],['return_qty','退供数量','quantity'],['expected_remaining_qty','预计剩余数量','quantity'],['latest_disposal_date','最晚处置日期'],['sellable_days','剩余可售天数','days']]],
  },
  'procurement-brake': {
    '采购库存位': ['inventory_position', [['current_inventory','当前库存','quantity'],['in_transit_qty','在途数量','quantity'],['unexecuted_purchase_qty','未执行采购量','quantity'],['adjusted_purchase_qty','调整数量','quantity'],['remaining_purchase_qty','调整后采购量','quantity'],['projected_after_adjustment','调整后预计库存','quantity'],['safety_stock','安全库存','quantity']]],
    '付款压力': ['payment', [['baseline_payment_date','原付款日期'],['scenario_payment_date','方案付款日期'],['adjusted_amount','调整涉及金额','money'],['baseline_in_window','原付款在评估期内','boolean'],['scenario_in_window','方案付款在评估期内','boolean'],['deferred_payment_pressure','评估期后的付款压力','money']]],
    '采购单': ['order', [['po_number','采购单号'],['line_number','采购单行号'],['arrival_date','到货日期'],['payment_date','付款日期'],['status','采购单状态']]],
  },
};

export class ProposalExportError extends Error {
  constructor(message) { super(message); this.name = 'ProposalExportError'; this.code = 'proposal_export_invalid'; }
}
const fail = message => { throw new ProposalExportError(message); };
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const at = (value, path) => path.split('.').reduce((current,key)=>current?.[key],value);
const positiveInteger = value => Number.isSafeInteger(value) && value > 0;
function requireText(value, label) { if(typeof value !== 'string' || !value.trim()) fail(`${label}缺失或无效，不能导出。`); }
function check(proposal, task) {
  try { validateProposal(proposal); } catch { fail('方案编号或版本无效，不能导出。'); }
  const version = proposal.version, payload = version?.payload;
  if(!object(payload?.input) || !object(payload?.calculation) || !object(payload?.basis)) fail('当前方案缺少已保存的输入、计算或依据；请先到工作台计算并保存当前版本。');
  if(!Object.hasOwn(TYPES,payload.proposal_type)) fail('此方案类型尚不支持执行准备资料导出。');
  const versionStatus = {draft:'draft',pending_approval:'pending_approval',approved:'approved',execution_task_created:'approved'}[proposal.status];
  if(!versionStatus || version.status!==versionStatus) fail('方案已失效、待重算或状态不一致；请重新核对当前版本。');
  const basis = payload.basis;
  if(version.proposal_id!==proposal.id || basis.proposal_version!==proposal.current_version) fail('方案及其保存版本不一致，不能导出。');
  requireText(proposal.snapshot_id,'库存快照');
  requireText(basis.calculation_version,'计算版本');
  if(basis.snapshot_id!==proposal.snapshot_id || !positiveInteger(proposal.fact_version) || basis.fact_version!==proposal.fact_version) fail('方案快照或事实版本不一致，不能导出。');
  if(!positiveInteger(proposal.risk_id) || basis.risk_id!==proposal.risk_id || payload.input.risk_id!==proposal.risk_id) fail('方案与输入的风险记录不一致，不能导出。');
  if(payload.calculation.valid!==true || !Array.isArray(payload.calculation.errors) || payload.calculation.errors.length) fail('当前方案没有通过计算约束，不能作为执行准备资料。');
  if(task!=null) {
    try { validateExecutionTask(task,{proposalId:proposal.id,version:proposal.current_version}); } catch { fail('执行任务与当前方案编号或版本不一致，不能合并导出。'); }
    if(proposal.status!=='execution_task_created') fail('当前方案尚未记录生成执行任务，不能合并任务记录。');
    if(!Object.hasOwn(STATUSES,task.status) || ['draft','pending_approval','approved','execution_task_created'].includes(task.status)) fail('执行任务状态尚不支持导出。');
    if(task.tenant_id!=null && proposal.tenant_id!=null && task.tenant_id!==proposal.tenant_id) fail('执行任务与方案所属数据范围不一致。');
  }
  return payload;
}

export function canExportProposal(proposal) {
  try { buildProposalExport(proposal); return true; } catch { return false; }
}

function csvCell(value, numeric=false) {
  let text = value === null ? UNKNOWN : String(value);
  if(!numeric && (/^[\s\u0000-\u001f\u007f\uFEFF]*[=+\-@]/u.test(text) || /^[\u0000-\u001f\u007f]/.test(text))) text = "'" + text;
  return `"${text.replaceAll('"','""')}"`;
}

export function buildProposalExport(proposal, {task=null,exportedAt=new Date().toISOString()}={}) {
  const payload = check(proposal,task), type=payload.proposal_type;
  if(typeof exportedAt!=='string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(exportedAt) || !Number.isFinite(Date.parse(exportedAt))) fail('导出时点必须是包含时区的有效时间。');
  if(new Date(exportedAt.slice(0,10)).toISOString().slice(0,10)!==exportedAt.slice(0,10) || Number(exportedAt.slice(11,13))>23) fail('导出时点必须是有效日历日期和时间。');
  const rows=[], numericRows=new Set(), quantityUnit=payload.input.unit ?? null;
  if(quantityUnit!==null) requireText(quantityUnit,'库存单位');
  function add(category, field, value, kind='text') {
    value = value ?? null;
    let unit='', display=value;
    const numeric=['money','quantity','daily','days','integer'].includes(kind);
    if(numeric && value!==null) {
      const pattern=kind==='money'?/^-?(?:0|[1-9]\d*)(?:\.\d{1,2})?$/:/^-?(?:0|[1-9]\d*)(?:\.\d+)?$/;
      if(!['string','number'].includes(typeof value) || (typeof value==='string' && !pattern.test(value)) || !Number.isFinite(Number(value)) || Math.abs(Number(value))>Number.MAX_SAFE_INTEGER) fail(`${field}不是有效数值，不能导出。`);
      if(kind==='money' && (Math.abs(Number(value))>Number.MAX_SAFE_INTEGER/100 || Math.abs(Number(value)*100-Math.round(Number(value)*100))>1e-6)) fail(`${field}不是有效的人民币元金额。`);
    } else if(value!==null && kind==='boolean') {
      if(typeof value!=='boolean') fail(`${field}不是有效的是/否记录。`);
      display=value?'是':'否';
    } else if(value!==null) {
      if(typeof value!=='string') fail(`${field}不是有效文本。`);
      const dictionary=({action:ACTIONS,completeness:COMPLETENESS,status:STATUSES,missing:LABELS})[kind];
      if(dictionary) { if(!Object.hasOwn(dictionary,value)) fail(`${field}包含尚未支持的值，请更新导出模板。`); display=dictionary[value]; }
    }
    if(kind==='money')unit='元';
    if(kind==='quantity')unit=quantityUnit || UNKNOWN;
    if(kind==='daily')unit=quantityUnit?`${quantityUnit}/天`:'库存单位/天（单位未知）';
    if(kind==='days')unit='天';
    if(numeric)numericRows.add(rows.length);
    rows.push({category,field,value,unit,...(display!==value?{displayValue:display}:{})});
  }
  function group(category, source, fields) {
    if(source!==null && source!==undefined && !object(source)) fail(`${category}结构无效，不能导出。`);
    for(const [key,label,kind] of fields)add(category,label,source?.[key],kind);
  }
  function lines(category, label, values, kind='text') {
    if(values==null) { add(category,label,null);return; }
    if(!Array.isArray(values))fail(`${label}应为列表。`);
    if(!values.length) { add(category,label,'源记录未列出');return; }
    values.forEach((value,index)=>add(category,`${label} ${index+1}`,value,kind));
  }
  const metadata = { proposal_id:proposal.id,proposal_type:type,proposal_status:proposal.status,proposal_version:proposal.current_version,version_status:proposal.version.status,snapshot_id:proposal.snapshot_id,fact_version:proposal.fact_version,calculation_version:payload.basis.calculation_version,risk_id:proposal.risk_id,quantity_unit:quantityUnit,exported_at:exportedAt,task_id:task?.id ?? null,task_status:task?.status ?? null };
  add('资料说明','使用边界',EXPORT_NOTICE);
  add('资料说明','业务类型',TYPES[type]);
  add('版本追溯','方案编号',proposal.id);
  add('版本追溯','方案版本',proposal.current_version,'integer');
  add('版本追溯','方案状态',proposal.status,'status');
  add('版本追溯','库存快照',proposal.snapshot_id);
  add('版本追溯','事实版本',proposal.fact_version,'integer');
  add('版本追溯','计算版本',payload.basis.calculation_version);
  add('版本追溯','导出时点',exportedAt);
  group('已保存输入',payload.input,[...COMMON_INPUT,...INPUT[type]]);
  add('计算校验','约束已通过',payload.calculation.valid,'boolean');
  for(const [category,[path,fields]] of Object.entries(CALCULATION[type]))group(category,at(payload.calculation,path),fields);
  if(type==='expiry-rescue') {
    const alternatives=payload.calculation.alternatives;
    if(alternatives!=null && !Array.isArray(alternatives))fail('处置比较应为列表。');
    (alternatives || []).forEach((item,index)=>group(`处置比较 ${index+1}`,item,[['type','处置方式'],['quantity','数量','quantity'],['fee','费用','money'],['cash_impact','现金影响','money'],['remaining_risk','剩余风险数量','quantity'],['assumption','处置前提']]));
  }
  group('现金口径',payload.calculation.cash,CASH);
  lines('现金口径','缺少数据',payload.calculation.cash?.missing_fields,'missing');
  lines('现金口径','计算假设',payload.calculation.cash?.assumptions);
  if(task) {
    add('人工执行记录','任务编号',task.id);
    add('人工执行记录','关联方案版本',task.proposal_version,'integer');
    add('人工执行记录','任务状态',task.status,'status');
    add('人工执行记录','任务创建时间',task.created_at);
    let taskMetadata=task.metadata;
    if(taskMetadata==null && task.metadata_json!=null) { try {taskMetadata=JSON.parse(task.metadata_json);}catch{fail('任务记录格式无效。');} }
    group('人工执行记录',taskMetadata,[['receipt_ref','人工回执号'],['actual_cash','人工填报现金','money'],['external_write','源记录是否标记外部写入','boolean']]);
  }
  const document = {document_type:'execution_preparation',notice:EXPORT_NOTICE,metadata,rows};
  const csv='\uFEFF'+[['分类','字段','值','单位'].map(value=>csvCell(value)).join(','),...rows.map((row,index)=>[csvCell(row.category),csvCell(row.field),csvCell(row.displayValue ?? row.value,numericRows.has(index)),csvCell(row.unit)].join(','))].join('\r\n')+'\r\n';
  const id=proposal.id.replace(/[^A-Za-z0-9_-]/g,'_').slice(0,100) || 'proposal';
  return {fileStem:`execution-preparation-${id}-v${proposal.current_version}`,json:JSON.stringify(document,null,2)+'\n',csv,summary:{title:`${TYPES[type]}执行准备资料`,proposalId:proposal.id,version:proposal.current_version,status:proposal.status,notice:EXPORT_NOTICE,rowCount:rows.length}};
}

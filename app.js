import { createApiClient } from './assets/js/api-client.mjs';
import * as contract from './assets/js/retail-contract.mjs';
import { escapeHtml as e, details, panel, list, metric, source, select, input, button, STATUS_LABELS } from './assets/js/retail-view.mjs';
import { validateManifest, sampleDownloadTarget } from './assets/js/dataset.mjs';
import { createFeedbackReview, buildFeedbackConfirmation, renderFeedbackReview } from './assets/js/feedback-review.mjs';
import { buildProposalExport, canExportProposal, EXPORT_NOTICE } from './assets/js/proposal-export.mjs';
import { calculationSummary, proposalSummary, workItemsMarkup, workflowStatus } from './assets/js/workflow-view.mjs';
import { createWorkbenchEdits, editableInput, sameEditableInput, resolveWorkbenchInput } from './assets/js/workbench-edits.mjs';
import { createTaskReceipts, RECEIPT_STATUSES } from './assets/js/task-receipts.mjs';
import { createNavigation } from './assets/js/navigation.mjs';
import { filterQueue, taskContext, taskContextMarkup } from './assets/js/queue-view.mjs';

const $ = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => [...root.querySelectorAll(s)];
const navigation = createNavigation({sidebar:$('#app-sidebar'),toggle:$('#nav-toggle'),backdrop:$('#nav-backdrop'),main:$('.app-main'),workspace:$('#workspace')});
const api = createApiClient({baseUrl:location.protocol==='file:'?null:$('meta[name="api-base"]').content,timeoutMs:60000});
const post = (path,body={},headers={}) => api(path,{method:'POST',body:JSON.stringify(body),headers});
const money = contract.formatYuan;
const number = contract.formatNumber;
const TITLES = {overview:'经营总览',today:'今日待办',slow_moving:'滞销诊断',transfer:'跨店调拨','expiry-rescue':'近效期处置','procurement-brake':'采购刹车',cashflow_simulation:'采购情景模拟',data:'数据与接口'};
const WORKBENCHES = new Set(['transfer','expiry-rescue','procurement-brake']);
const RISK_WORKBENCH = {'调拨':'transfer','促销':'expiry-rescue','采购刹车':'procurement-brake'};
const DESCRIPTIONS = {overview:'先看需要关注的门店，再进入具体商品核对证据。',today:'待审批、审批后跟进与已完成分开呈现，状态以最新服务响应为准。',slow_moving:'销售差异是观察事实，原因假设需要门店反馈和人工核对。',transfer:'核对门店库存、运输费用和可售时间；内部调拨不产生现金到账。','expiry-rescue':'核对批次剩余数量与处置分配，促销投放量不代表确定销量。','procurement-brake':'库存、在途、未执行采购和付款压力分开核对。',cashflow_simulation:'当前仅测算减少可调整采购数量；确认范围与比例后再计算。',data:'样例可复现，版本、数据来源和缺项均可核对。'};
const views = new Map(Object.keys(TITLES).map(route=>[route,{route,data:null,error:null,pending:false,busy:false,sequence:0,notice:'',riskId:null,dirty:false,input:null,preview:null,proposal:null,tab:'pending',filter:{period:'7',store_id:'all'},simulation:{horizon_days:'14',reduction_pct:'20',store_id:'all',category:'',request_text:''}}]));
const feedbackSessions = new Map();
const workbenchEdits = createWorkbenchEdits();
const taskReceipts = createTaskReceipts();
function feedbackSession(riskId) {
  const key=String(riskId);
  if(!feedbackSessions.has(key)) feedbackSessions.set(key,{text:'',feedback:null,review:null,reviewDirty:false,investigationId:null});
  return feedbackSessions.get(key);
}
let active='overview';
let mutation=null;

function notify(message) { $('#toast').textContent=message; $('#toast').hidden=false; clearTimeout(notify.timer); notify.timer=setTimeout(()=>{$('#toast').hidden=true;},5000); }
function nav(open) { navigation.setOpen(open); }
function current(view) { return active===view.route; }
function hasUnsavedEdits() {
  return workbenchEdits.hasAny() || taskReceipts.hasAny() || [...feedbackSessions.values()].some(session=>session.text!==(session.feedback?.raw_text || '') || session.reviewDirty);
}
function restoreWorkbench(view, data) {
  const restored=workbenchEdits.restore(view.route,data);
  view.data=data;view.riskId=data.risk.id;view.input=restored.input;view.inputIssues=restored.issues;view.editConflicts=restored.conflicts;
  view.dirty=restored.hasEdits || restored.issues.length>0 || data.draft?.status==='needs_recalculation';
  view.proposal=data.proposal;
}
function errorMarkup(error) {
  return `<p>${e(error.message || '请求失败')}</p>${error.code?`<small>${e(error.code)}</small>`:''}${error.outcomeUnknown?'<p>等待已结束，服务端是否完成未知。请先刷新核对记录，勿反复提交。</p>':''}${error.fieldErrors?.length?list(error.fieldErrors):''}`;
}
function provenance(view) {
  if(view.route==='data') return '输入包只用于复现，不代表已导入当前服务。';
  if(view.data?.metadata || Object.hasOwn(view.data || {},'is_demo')) return source(view.data);
  if(WORKBENCHES.has(view.route) && view.data) return `<p>${view.data.mode==='sample_replay'?'合成样例回放':'服务端数据'} · ${e(view.data.snapshot_id || '快照未提供')} · ${e(STATUS_LABELS[view.data.draft?.status] || view.data.draft?.status || '')}</p>`;
  return '当前使用 v1.2 规则工具，尚未接入真实大模型。数据缺项由服务明确返回。';
}
function render(view=views.get(active)) {
  if(!current(view)) return;
  $('#page-title').textContent=TITLES[active]; $('#page-description').textContent=DESCRIPTIONS[active];
  $$('#app-nav a').forEach(a=>{if(a.hash===`#${active}`) a.setAttribute('aria-current','page'); else a.removeAttribute('aria-current');});
  $('#connection-status').innerHTML=provenance(view);
  $('#page-status').innerHTML=view.error?panel('请求未完成',errorMarkup(view.error)+button('reload','刷新核对当前状态',view.busy),'is-error'):view.pending?panel('正在读取服务数据','<p>保持当前范围，等待实际返回结果。</p>','is-loading'):view.busy?panel('正在提交','<p>等待服务确认；离开页面不会撤销已提交的请求。</p>','is-loading'):view.notice?panel('当前状态',`<p>${e(view.notice)}</p>`):'';
  const content=$('#page-content');
  if(!view.data) { content.innerHTML=view.pending?'':panel('暂无可用数据',`${WORKBENCHES.has(view.route) && workbenchEdits.has(view.route,view.riskId)?'<p>此商品尚未保存的编辑仍保留在当前页面中，重新读取后可继续。</p>':''}${view.route==='today' && taskReceipts.hasAny()?'<p>尚未保存的人工回执仍保留在当前页面中，重新读取后可继续。</p>':''}${button('reload','重新读取')}`); return; }
  content.innerHTML=active==='overview'?overviewMarkup(view):active==='today'?todayMarkup(view):active==='slow_moving'?diagnosisMarkup(view):WORKBENCHES.has(active)?workbenchMarkup(view):active==='cashflow_simulation'?simulationMarkup(view):dataMarkup(view);
  if(mutation && mutation!==view) $('#page-status').innerHTML=panel('另一项操作正在提交',`<p>${e(TITLES[mutation.route])}正在等待服务确认。可继续浏览，完成后恢复编辑。</p>`,'is-loading');
  if(mutation || view.pending) $$('fieldset, button, #queue-search',content).forEach(el=>{el.disabled=true;});
}
async function loadView(view) {
  if(view.busy) return;
  view.controller?.abort(); const controller=new AbortController(); view.controller=controller;
  const sequence=++view.sequence; view.pending=true; view.error=null; render(view);
  const get=path=>api(path,{signal:controller.signal});
  try {
    let data;
    if(view.route==='overview') data=contract.validateOverview(await get(`/retail/overview?period=${view.filter.period}&store_id=${encodeURIComponent(view.filter.store_id)}`),{storeId:view.filter.store_id,period:Number(view.filter.period)});
    else if(view.route==='today') { const [proposals,tasks,work]=await Promise.all([get('/proposals'),get('/execution-tasks'),get('/work-items')]); data={proposals:contract.validateProposalList(proposals).items,tasks:contract.validateTaskList(tasks).items,work:work.items || []}; }
    else if(view.route==='slow_moving') {
      const risks=contract.validateRisks(await get('/risks'));
      const risk=risks.items.find(item=>String(item.id)===String(view.riskId)) || risks.items[0];
      const detail=risk?contract.validateRiskDetail(await get(`/risks/${risk.id}`),{riskId:risk.id}):null;
      data={...risks,detail};
    } else if(WORKBENCHES.has(view.route)) data=contract.validateWorkbench(await get(`/workbenches/${view.route}${view.riskId?`?risk_id=${encodeURIComponent(view.riskId)}`:''}`),{moduleType:view.route,riskId:view.riskId || undefined});
    else if(view.route==='cashflow_simulation') data=contract.validateSimulationOptions(await get('/retail/simulation-options'));
    else { const [manifest,center]=await Promise.all([fetch('/sample-data/manifest.json').then(r=>{if(!r.ok) throw new Error('合成输入包读取失败'); return r.json();}),get('/data-center')]); data={manifest:validateManifest(manifest),center}; }
    if(sequence!==view.sequence) return;
    view.data=data;
    if(view.route==='slow_moving') view.riskId=data.detail?.risk.id || null;
    if(WORKBENCHES.has(view.route)) restoreWorkbench(view,data);
    if(view.route==='cashflow_simulation') { view.preview=null; view.result=null; if(!data.stores.some(s=>s.id===view.simulation.store_id)) view.simulation.store_id='all'; if(!data.categories.includes(view.simulation.category)) view.simulation.category=''; }
  } catch(error) { if(sequence===view.sequence && error.code!=='aborted') {view.error=error; view.data=null;} }
  finally { if(sequence===view.sequence) {view.pending=false; render(view);} }
}
async function act(view,work) {
  if(mutation || view.pending) return;
  mutation=view; view.busy=true; view.error=null; view.notice=''; render(view);
  try { await work(); }
  catch(error) {view.error=error;}
  finally {
    mutation=null; view.busy=false;
    const visible=views.get(active); render(visible);
    if(!visible.data && !visible.pending && !visible.error) void loadView(visible);
  }
}
function navigate() {
  const route=location.hash.slice(1).split('?')[0]; active=Object.hasOwn(TITLES,route)?route:'overview'; nav(false);
  const view=views.get(active); render(view); if(!view.data && !view.pending) void loadView(view);
}

function overviewMarkup(view) {
  const data=view.data;
  const stores=data.stores || [];
  const sorted=[...stores].sort((a,b)=>{const key=view.sort || 'risk_cost'; if(key==='store_name') return a.store_name.localeCompare(b.store_name,'zh-CN'); if(a[key]==null)return 1;if(b[key]==null)return -1;return b[key]-a[key];});
  const selected=(view.riskTypes || []), shown=sorted.filter(s=>!selected.length || (s.risk_types || []).some(t=>selected.includes(t)));
  return `<form class="workspace-form" id="overview-form"><fieldset><div class="form-grid">${select('period','观察周期',[['7','最近7天'],['30','最近30天']],view.filter.period)}${select('store_id','门店范围',[['all','全部门店'],...stores.map(s=>[s.store_id,s.store_name])],view.filter.store_id)}</div><div class="form-actions"><button class="primary-button">更新范围</button>${button('reload','刷新数据')}</div></fieldset></form>
    <div class="metric-grid">${metric('账户可用资金',money(data.account.balance))}${metric('库存成本占用',money(data.inventory.cost))}${metric('待关注库存成本',money(data.inventory.risk_cost))}${metric('未来30天已确认采购付款',money(data.purchase_commitments.amount))}</div>
    ${data.metadata.missing?.length?panel('数据缺项',list(data.metadata.missing),'is-warning'):''}
    <section class="result-card"><h2>门店待关注事项</h2><div class="form-grid">${select('store_sort','排序',[['risk_cost','待关注成本从高到低'],['inventory_cost','库存占用从高到低'],['turnover_days','周转天数从高到低'],['store_name','门店名称']],view.sort || 'risk_cost')}<label class="field"><span>风险类型（可多选）</span><select name="risk_types" multiple size="4">${['滞销','近效期','采购过量','门店错配'].map(t=>`<option ${selected.includes(t)?'selected':''}>${t}</option>`).join('')}</select></label></div>
    <div class="table-wrap"><table class="data-table"><thead><tr><th>门店</th><th>库存占用</th><th>待关注成本</th><th>周转天数</th><th>待关注商品</th></tr></thead><tbody>${shown.map(s=>`<tr><th>${e(s.store_name)}</th><td>${money(s.inventory_cost)}</td><td>${money(s.risk_cost)}</td><td>${number(s.turnover_days)}</td><td>${(s.risk_items || []).map(r=>`<button type="button" class="text-button" ${Number.isSafeInteger(r.risk_id) && r.risk_id>0?`data-risk="${r.risk_id}"`:'disabled'}>${e(r.product)} · ${money(r.inventory_cost)}</button>`).join('<br>') || '无记录'}</td></tr>`).join('')}</tbody></table></div><p class="form-hint">每店仅展示服务返回的前五项。库存成本、账户余额与预计采购付款各自独立。</p></section>
    <details class="result-card"><summary>指标来源与完整假设</summary>${details({account:data.account,purchase_commitments:data.purchase_commitments,metadata:data.metadata})}</details>`;
}

function diagnosisMarkup(view) {
  const data=view.data, detail=data.detail;
  if(!detail) return panel('当前没有待关注商品','<p>请核对已导入的库存范围和缺失字段。</p>');
  const risk=detail.risk;
  const session=feedbackSession(risk.id), fb=session.feedback;
  return `<form class="workspace-form" id="risk-form"><fieldset>${select('risk_id','选择门店商品',data.items.map(r=>[r.id,`${r.product} · ${r.store}`]),view.riskId)}</fieldset></form>
    <section class="result-card"><h2>${e(risk.product)} · ${e(risk.store)}</h2><div class="metric-grid">${metric('库存数量',`${number(risk.inventory_qty)} ${risk.unit || '（单位未提供）'}`)}${metric('近30天销量',`${number(risk.sales_30)} ${risk.unit || '（单位未提供）'}`)}${metric('库存覆盖',risk.sales_30===0?'近30天未售':`${number(risk.days_to_sell)} 天`)}</div><p>${e(risk.observation || '')}</p>${details(detail.diagnosis)}
    <details open><summary>数据依据与缺项</summary>${details({facts:detail.facts,evidence:detail.evidence})}</details><details><summary>待核查原因</summary>${details(detail.factors)}</details><div class="form-actions">${RISK_WORKBENCH[risk.risk_type]?button('open-workbench',TITLES[RISK_WORKBENCH[risk.risk_type]],false,`data-module="${RISK_WORKBENCH[risk.risk_type]}"`):''}</div></section>
    <section class="result-card feedback-review"><h2>门店反馈 · 人工核查</h2><p>粘贴已有门店反馈，再核对情况、日期与证据。当前规则草稿尚未接入真实大模型，所有情况默认待核实。</p><form id="feedback-form"><fieldset><label class="field"><span>原始反馈</span><textarea name="raw_text" required rows="3">${e(session.text)}</textarea></label><div class="form-actions"><button class="secondary-button">保存原文并生成待核对草稿</button></div></fieldset></form>
    <div id="feedback-review-content">${fb && session.text===fb.raw_text?`<p>反馈编号 ${e(fb.id)} · ${fb.confirmation_status==='confirmed'?'已人工确认':'待人工核查'}</p>${renderFeedbackReview(fb,session.review)}`:fb?panel('原文已修改','<p>请先保存当前原文，生成对应版本后再核对。</p>','is-warning'):''}</div>
    ${button('replan','按已确认事实重新计算')}</section>`;
}

function workbenchMarkup(view) {
  const data=view.data, i=view.input, proposal=view.proposal;
  const unit=data.risk.unit || i.unit || '单位未提供';
  const hasEdits=workbenchEdits.has(view.route,view.riskId), issues=view.inputIssues || [];
  let fields='';
  if(view.route==='transfer') fields=select('target_store_id','接收门店',[...(issues.length?[[i.target_store_id,'原接收门店已不可用，请重新选择']]:[]),...(data.transfer_network || []).map(s=>[s.store_id,`${s.name} · 运费${money(s.transport_fee)}`])],i.target_store_id)+input('quantity',`调拨数量（${unit}）`,i.quantity,{min:1,step:1});
  else if(view.route==='expiry-rescue') fields=input('transfer_qty',`调拨数量（${unit}）`,i.transfer_qty,{step:1})+input('promo_qty',`促销投放量（${unit}）`,i.promo_qty,{step:1})+input('promo_price','促销价格（元）',i.promo_price,{step:0.01})+input('return_qty',`退供数量（${unit}）`,i.return_qty,{step:1});
  else fields=select('action','调整方式',[['reduce','减少采购量'],['cancel','取消采购量'],['delay_arrival','推迟到货'],['delay_payment','推迟付款']],i.action)+input('adjustment_qty',`调整数量（${unit}）`,i.adjustment_qty,{min:1,step:1})+input('new_payment_date','调整后付款日',i.new_payment_date || '',{type:'date',required:i.action==='delay_payment'});
  const canSave=!view.dirty && !issues.length && data.calculation?.valid;
  return `${workflowStatus({dirty:view.dirty,draft:data.draft,proposal})}<form class="workspace-form" id="workbench-form"><fieldset>${select('risk_id','选择门店商品',(data.items || []).map(r=>[r.id,`${r.product} · ${r.store}`]),view.riskId)}<div class="form-grid form-section">${fields}</div><div class="form-actions"><button class="primary-button" data-action="calculate" type="submit" ${issues.length?'disabled':''}>重新计算</button>${button('save-draft','保存编辑输入',Boolean(issues.length))}${button('save','保存方案草稿',!canSave)}${button('discard-edits','放弃本地编辑',!hasEdits)}</div><p class="form-hint" id="local-edits-status">${hasEdits?'此商品的编辑尚未保存到服务。切换商品会在当前页面中保留，刷新或关闭前请保存。':'当前没有尚未保存到服务的本地编辑。输入保存不等于方案已保存或审批。'}</p></fieldset></form>
    ${issues.length?panel('接收门店需要重新选择',list(issues),'is-warning'):''}${view.editConflicts?.length?panel('服务端输入也已变化',`<p>已保留你的本地选择，并读取最新库存事实。请核对以下字段后重新计算：</p>${list(view.editConflicts)}`,'is-warning'):''}
    ${view.dirty?panel('输入已修改','<p>旧测算与本地确认已失效。请保存或重新计算当前输入。</p>','is-warning'):''}
    ${!view.dirty && data.calculation?`<section class="result-card" id="calculation-result"><h2>${data.calculation.valid?'工具计算结果':'约束未通过'}</h2>${data.calculation.errors?.length?panel('需要调整',list(data.calculation.errors),'is-error'):''}${calculationSummary(view.route,data.calculation,i)}<details><summary>完整计算依据与返回字段</summary>${details(data.calculation)}</details></section>`:''}
    <details class="result-card"><summary>当前输入事实与来源</summary>${details(i)}<p>候选门店事实、单位成本与约束均由接口提供。编辑仅改变上方允许调整的字段。</p></details>
    ${proposal?`<section class="result-card" id="workbench-proposal"><h2>方案 ${e(proposal.id)}</h2><p>${e(STATUS_LABELS[proposal.status] || proposal.status)} · V${proposal.current_version}</p><div class="form-actions">${proposalButton(proposal,'submit','提交审批',unsavedWorkbench(view) || !canSave || proposal.status!=='draft')}<a href="#today">查看审批与执行跟进</a></div>${exportControls(proposal,unsavedWorkbench(view))}</section>`:''}`;
}
function exportControls(proposal,dirty=false) {
  const available=canExportProposal(proposal), disabled=dirty || !available;
  return `<div class="export-controls"><h3>交接给现有工作流程</h3><p>${e(EXPORT_NOTICE)}</p>${disabled?`<p class="form-hint">${dirty?'当前输入尚未保存为方案版本，请先重新计算并保存。':'当前记录缺少完整保存依据或版本已失效，请到对应工作台重新计算并保存。'}</p>`:''}<div class="form-actions">${['csv','json'].map(format=>button('export-proposal',format==='csv'?'下载交接表 CSV':'下载结构化资料 JSON',disabled,`data-format="${format}" data-id="${e(proposal.id)}" data-version="${proposal.current_version}"`)).join('')}</div></div>`;
}
function proposalButton(proposal,action,label,disabled=false) {return `<button type="button" class="secondary-button" data-proposal-action="${action}" data-id="${e(proposal.id)}" data-version="${proposal.current_version}" ${disabled?'disabled':''}>${label}</button>`;}
function unsavedWorkbench(view) {return view.dirty || ['needs_recalculation','blocked','calculated'].includes(view.data?.draft?.status);}
function dirtyRisk(riskId) {return workbenchEdits.hasRisk(riskId) || [...views.values()].some(v=>WORKBENCHES.has(v.route) && Number(v.riskId)===Number(riskId) && unsavedWorkbench(v));}
function todayMarkup(view) {
  const data=view.data;
  return `<div class="form-actions">${[['actions',`待评估事项 ${filterQueue(data,{tab:'actions'}).total}`],['pending',`待我审批 ${filterQueue(data,{tab:'pending'}).total}`],['followup','审批后跟进'],['completed','已完成'],['drafts','草稿与待重算']].map(([key,label])=>button('tab',label,false,`data-tab="${key}" aria-pressed="${view.tab===key}"`)).join('')}${button('reload','刷新最新状态')}</div>
    <label class="field"><span>查找当前分类的门店、商品或编号</span><input type="search" id="queue-search" value="${e(view.query || '')}" aria-controls="queue-results" placeholder="门店、商品、方案号或任务号"></label>
    <div id="receipt-drafts">${receiptDraftsMarkup(view)}</div><div id="queue-results">${todayResultsMarkup(view)}</div>`;
}
function todayResultsMarkup(view) {
  const {work,proposals,tasks,total,shown}=filterQueue(view.data,{tab:view.tab,query:view.query || ''});
  return `<p role="status">当前分类共 ${total} 项，显示 ${shown} 项。</p>
    ${!shown?panel(total?'没有匹配记录':'此分类暂无记录',total?'<p>请修改搜索词，或切换其他分类。</p>':'<p>可到待评估事项中选择门店问题，再计算并保存方案。</p>'):view.tab==='actions'?workItemsMarkup(work):''}
    ${proposals.map(p=>`<article class="result-card" data-proposal-id="${e(p.id)}"><h2>${e(p.approval_summary?.title || p.product || p.id)}</h2><p>${e(p.id)} · V${p.current_version} · ${e(STATUS_LABELS[p.status] || p.status)}</p>${dirtyRisk(p.risk_id)?panel('存在未完成的编辑','<p>请先到对应工作台重新计算并保存版本。</p>','is-warning'):''}${proposalSummary(p)}<details><summary>审核当前版本的输入、计算与证据</summary>${details(p.version?.payload || {})}</details><div class="form-actions">${p.status==='pending_approval'?proposalButton(p,'approve','批准当前版本',dirtyRisk(p.risk_id)):p.status==='approved'?proposalButton(p,'execute','生成待执行任务',dirtyRisk(p.risk_id)):p.status==='draft'?proposalButton(p,'submit','提交审批',dirtyRisk(p.risk_id)):''}</div>${exportControls(p,dirtyRisk(p.risk_id))}</article>`).join('')}
    ${tasks.map(t=>taskMarkup(t,view.data.proposals)).join('')}`;
}
function receiptMessage(draft) {
  return draft.conflict?'服务端记录已变化，本地输入仍保留。请核对最新状态和回执，放弃本地编辑后再填写。':draft.dirty?'此任务的人工回执尚未保存。切换分类或页面会保留，刷新或关闭前请保存。':'请按实际执行情况填写；保存前须明确选择执行进度。';
}
function taskMarkup(task,proposals) {
  const draft=taskReceipts.restore(task), context=taskContext(task,proposals);
  return `<article class="result-card" data-task-id="${e(task.id)}"><h2>${e(task.id)}</h2><p>方案 ${e(task.proposal_id)} · V${task.proposal_version} · ${e(STATUS_LABELS[task.status] || task.status)}</p>${taskContextMarkup(context)}<p>本系统未向外部 ERP 写入；以下状态和回执由人员记录。</p><details><summary>服务端已记录的执行信息</summary>${details(task.metadata || {})}</details>
    <form class="task-form" data-task-id="${e(task.id)}"><fieldset><div class="form-grid">${select('status','人工记录执行进度',[['','请选择实际执行进度'],...RECEIPT_STATUSES],draft.input.status,'required')}${input('receipt_ref','执行回执号',draft.input.receipt_ref,{type:'text',required:false})}</div><p class="form-hint" data-receipt-message>${e(receiptMessage(draft))}</p><div class="form-actions"><button type="submit" class="secondary-button" ${!draft.dirty || draft.conflict?'disabled':''}>保存人工回执</button></div></fieldset></form>
    <div class="form-actions">${button('discard-receipt','放弃此任务的本地编辑',!draft.dirty,`data-task-id="${e(task.id)}"`)}${context.matched && WORKBENCHES.has(context.moduleType) && Number.isSafeInteger(context.riskId)?button('open-workbench','查看当前商品工作台',false,`data-module="${e(context.moduleType)}" data-risk-id="${context.riskId}"`):''}</div></article>`;
}
function receiptDraftsMarkup(view) {
  const drafts=taskReceipts.list();
  return drafts.length?panel(`有 ${drafts.length} 项人工回执尚未保存`,drafts.map(d=>`<p>${e(d.id)} · ${e(STATUS_LABELS[d.input.status] || '尚未选择进度')} · ${e(d.input.receipt_ref || '未填写回执号')}</p>${view.data.tasks.some(t=>t.id===d.id)?button('resume-receipt','继续填写',false,`data-task-id="${e(d.id)}"`):`<p>当前服务列表未返回此任务，输入仍保留，请刷新核对。</p>${button('discard-receipt','放弃此任务的本地编辑',false,`data-task-id="${e(d.id)}"`)}`}`).join(''),'is-warning'):'';
}
function editTaskReceipt(view,form) {
  const task=view.data.tasks.find(t=>t.id===form.dataset.taskId);
  if(!task)return;
  taskReceipts.capture(task,Object.fromEntries(new FormData(form)));
  const draft=taskReceipts.restore(task);
  $('[data-receipt-message]',form).textContent=receiptMessage(draft);
  $('button[type="submit"]',form).disabled=!draft.dirty || draft.conflict;
  $('[data-action="discard-receipt"]',form.closest('article')).disabled=!draft.dirty;
  $('#receipt-drafts').innerHTML=receiptDraftsMarkup(view);
}
async function saveTaskReceipt(view,form) {
  const taskId=form.dataset.taskId;
  editTaskReceipt(view,form);
  try {taskReceipts.prepare(view.data.tasks.find(t=>t.id===taskId));}
  catch(error){notify(error.message);return;}
  await act(view,async()=>{
    view.data.tasks=contract.validateTaskList(await api('/execution-tasks')).items;
    const latest=view.data.tasks.find(t=>t.id===taskId);
    if(!latest) throw new Error('最新服务列表未返回此任务，本地输入继续保留，请核对任务记录。');
    const submission=taskReceipts.prepare(latest);
    const result=taskReceipts.accept(await post(`/execution-tasks/${encodeURIComponent(taskId)}/status`,submission.input),submission);
    view.data.tasks=view.data.tasks.map(t=>t.id===taskId?result:t);
    view.tab=['received','completed'].includes(result.status)?'completed':'followup';
    view.notice='已取得匹配的人工回执保存结果；本系统未向外部 ERP 发出操作。';
  });
}

function simulationMarkup(view) {
  const s=view.simulation, options=view.data;
  const preview=view.preview, result=view.result;
  return `<form class="workspace-form" id="simulation-form"><fieldset><div class="form-grid">${select('store_id','门店',[['all','全部门店'],...options.stores.map(s=>[s.id,s.name])],s.store_id)}${select('category','品类',[['','全部品类'],...options.categories.map(c=>[c,c])],s.category)}${input('horizon_days','模拟天数',s.horizon_days,{min:1,max:90,step:1})}${input('reduction_pct','减少可调整采购量（%）',s.reduction_pct,{min:0,max:100,step:'any'})}<label class="field field-wide"><span>补充说明（原文留存）</span><textarea name="request_text" rows="3" maxlength="2000">${e(s.request_text)}</textarea></label></div><p class="form-hint">请直接填写周期和减采比例。当前规则服务不解析任意自然语言动作；说明文本不会自动改变表单参数。</p><div class="form-actions"><button class="primary-button">核对模拟条件</button>${button('reload','重新读取可用范围')}</div></fieldset></form>
    ${preview?`<section id="scenario-preview" class="scenario-card"><h2>待确认的采购情景</h2><p>${e(options.stores.find(s=>s.id===preview.store_id)?.name || '全部门店')} · ${e(preview.category || '全部品类')} · ${preview.horizon_days} 天 · 减采 ${contract.formatPercent(preview.reduction_pct)}</p><p>确认后才请求后端计算；不会修改真实采购单或批准业务动作。</p>${button('confirm-simulation','确认并计算')}${button('revise-simulation','返回修改')}</section>`:''}
    ${result?simulationResult(result):''}`;
}
function simulationResult(result) {
  if(result.status==='unavailable') return `<div id="simulation-result">${panel('当前资料不足以模拟',list(result.metadata.missing),'is-warning')}</div>`;
  const titles={purchase_outflow:'预计采购现金流出',ending_inventory_cost:'期末库存成本',stockout_risk_count:'缺货风险门店商品数'};
  return `<section class="result-card" id="simulation-result"><h2>基线与方案</h2>${source(result)}<div class="table-wrap"><table class="data-table"><thead><tr><th>指标</th><th>基线</th><th>方案</th><th>方案减基线</th></tr></thead><tbody>${Object.entries(titles).map(([key,title])=>{const m=result.metrics[key], f=key==='stockout_risk_count'?number:money;return `<tr><th>${title}</th><td>${f(m.baseline)}</td><td>${f(m.scenario)}</td><td>${f(m.delta)}</td></tr>`;}).join('')}</tbody></table></div><p>减少采购支出不是利润或到账回款，请同时核对缺货风险和后续补货压力。</p>${list(result.metadata.assumptions || [])}${result.metadata.missing?.length?panel('缺少数据',list(result.metadata.missing),'is-warning'):''}
    <details open><summary>分周采购流出（非账户余额）</summary><div class="table-wrap"><table class="data-table"><thead><tr><th>周期</th><th>基线</th><th>方案</th></tr></thead><tbody>${result.weekly.map(w=>`<tr><th>${e(w.label)} · ${e(w.start_date)}—${e(w.end_date)}</th><td>${money(w.baseline)}</td><td>${money(w.scenario)}</td></tr>`).join('')}</tbody></table></div></details><details open><summary>缺货与安全库存风险（${result.risks.length}）</summary>${details(result.risks)}</details><details><summary>逐项计算与原始条件</summary>${details({scenario:result.scenario,lines:result.lines})}</details></section>`;
}
function dataMarkup(view) {
  const manifest=view.data.manifest;
  return `<section class="result-card"><h2>当前服务的数据来源</h2>${details(view.data.center)}<p>当前导入接口仅记录校验回执，不能把回执等同分析数据已加载。本轮不提供会误导用户的导入按钮。</p></section><section class="result-card"><h2>可复现的合成输入</h2><p>v1.2 · ${e(manifest.source)} · ${e(manifest.as_of_date)}</p><p>所有输入均为合成；生成与下载不会替换正在运行的数据库。</p><ul>${Object.keys(manifest.files).map(key=>`<li><a href="${sampleDownloadTarget(manifest,key)}" download>${e(key)}</a> <code>${e(manifest.files[key].sha256)}</code></li>`).join('')}</ul><a href="API_CONTRACT.md">魏的当前 v1.2 契约</a> · <a href="docs/FRONTEND_INTEGRATION.md">联调边界</a> · <a href="sample-data/README.md">样例说明</a></section>`;
}

function editWorkbench(view,form) {
  const values=editableInput(view.route,Object.fromEntries(new FormData(form)));
  const resolved=resolveWorkbenchInput(view.route,view.data,values);
  if(sameEditableInput(view.route,resolved.input,view.input)) return;
  view.input=resolved.input;view.inputIssues=resolved.issues;view.dirty=true;view.error=null;
  workbenchEdits.capture(view.route,view.riskId,view.input,view.data.input);
  const hasEdits=workbenchEdits.has(view.route,view.riskId);
  view.notice='输入已变化，旧测算不可用于保存、审批或导出。';
  $('#calculation-result')?.remove();
  $$('#page-content [data-action="save"],#page-content [data-proposal-action],#page-content [data-action="export-proposal"]').forEach(b=>b.disabled=true);
  $('[data-action="discard-edits"]').disabled=!hasEdits;
  $('[data-action="calculate"]').disabled=resolved.issues.length>0;
  $('[data-action="save-draft"]').disabled=resolved.issues.length>0;
  $('#local-edits-status').textContent=hasEdits?'此商品的编辑尚未保存到服务。切换商品会在当前页面中保留，刷新或关闭前请保存。':'当前输入与服务端已保存值一致；旧测算仍需重新核对。';
  const progress=$('.workflow-status');if(progress)progress.outerHTML=workflowStatus({dirty:true});
  $('#page-status').innerHTML=panel('需重新计算',`<p>${e(view.notice)}</p>${list(resolved.issues)}`,'is-warning');
}
async function persistWorkbenchInput(view, payload) {
  const {draft}=contract.validateWorkbenchDraft(await post(`/workbenches/${view.route}/draft`,{input:payload}),{moduleType:view.route,riskId:view.riskId});
  if(!sameEditableInput(view.route,draft.input,payload)) throw new Error('保存回执与当前编辑不一致，本地编辑继续保留，请刷新核对。');
  workbenchEdits.discard(view.route,view.riskId);
  view.input=structuredClone(draft.input);
  Object.assign(view.data,{input:structuredClone(draft.input),draft,calculation:null});
  view.inputIssues=[];view.editConflicts=[];view.dirty=true;
  view.notice='编辑输入已保存到服务，仍需重新计算并保存方案版本。';
}
async function calculate(view) {
  if(view.inputIssues?.length) return;
  const payload=structuredClone(view.input);
  await act(view,async()=>{
    await persistWorkbenchInput(view,payload);
    const result=contract.validateWorkbenchCalculation(await post(`/workbenches/${view.route}/calculate`,{input:payload}));
    if(result.input.risk_id!==view.riskId || !sameEditableInput(view.route,result.input,payload)) throw new Error('计算回执与当前输入不一致，请刷新核对已保存输入。');
    view.input=structuredClone(result.input); Object.assign(view.data,result); view.dirty=false;
    view.notice=result.calculation.valid?'本次输入已由后端计算；可核对后保存草稿。':'约束未通过，请修改输入。';
  });
}
async function save(view) {
  if(view.dirty || !view.data.calculation?.valid) return;
  await act(view,async()=>{
    const result=contract.validateWorkbenchSave(await post(`/workbenches/${view.route}/save`,{input:structuredClone(view.input)}));
    view.proposal=result.proposal;
    restoreWorkbench(view,contract.validateWorkbench(await api(`/workbenches/${view.route}?risk_id=${view.riskId}`),{moduleType:view.route,riskId:view.riskId}));
    view.notice='草稿已保存，尚未提交审批。'; views.get('today').data=null;
  });
}
async function currentProposal(id,version) {
  const latest=contract.validateProposalList(await api('/proposals')).items.find(p=>p.id===id);
  if(!latest || latest.current_version!==version || dirtyRisk(latest.risk_id)) throw new Error('方案或输入已经变化，请重新读取并核对当前版本。');
  const module=latest.version?.payload?.proposal_type;
  if(WORKBENCHES.has(module)) {
    const wb=contract.validateWorkbench(await api(`/workbenches/${module}?risk_id=${latest.risk_id}`),{moduleType:module,riskId:latest.risk_id});
    if(unsavedWorkbench({data:wb})) throw new Error('服务端输入尚未保存为方案版本，请先重新计算并保存，再核对当前方案。');
    if(wb.proposal?.id!==latest.id || wb.proposal.current_version!==latest.current_version || wb.proposal.status!==latest.status) throw new Error('核对期间方案版本或状态已变化，请刷新后重新核对。');
  }
  return latest;
}
async function exportProposal(view,element) {
  const id=element.dataset.id, version=Number(element.dataset.version), format=element.dataset.format;
  if(!['csv','json'].includes(format)) return;
  await act(view,async()=>{
    const proposal=await currentProposal(id,version);
    const files=buildProposalExport(proposal);
    const url=URL.createObjectURL(new Blob([files[format]],{type:format==='csv'?'text/csv;charset=utf-8':'application/json;charset=utf-8'}));
    const anchor=document.createElement('a');anchor.href=url;anchor.download=`${files.fileStem}.${format}`;document.body.append(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
    view.notice=`已导出 ${id} · V${version}。${EXPORT_NOTICE}`;
  });
}
async function proposalAction(view,element) {
  const id=element.dataset.id,version=Number(element.dataset.version),action=element.dataset.proposalAction;
  await act(view,async()=>{
    const latest=await currentProposal(id,version);
    const allowed={submit:'draft',approve:'pending_approval',execute:'approved'};
    if(latest.status!==allowed[action]) throw new Error('方案状态已改变，请刷新后操作。');
    const headers=['approve','execute'].includes(action)?{'Idempotency-Key':`ui-v1.2|demo|${action}|${id}|${version}`}:{ };
    const result=await post(`/proposals/${encodeURIComponent(id)}/${action}`,{},headers);
    if(action==='approve') contract.validateApproval(result,{proposalId:id,version});
    else if(action==='execute') contract.validateExecutionTask(result,{proposalId:id,version});
    else contract.validateProposal(result,{proposalId:id});
    const [proposals,tasks]=await Promise.all([api('/proposals'),api('/execution-tasks')]);
    const currentProposals=contract.validateProposalList(proposals).items;
    view.proposal=currentProposals.find(p=>p.id===id) || null;
    const today=views.get('today');today.data={proposals:currentProposals,tasks:contract.validateTaskList(tasks).items,work:today.data?.work || []};
    today.tab=action==='approve' || action==='execute'?'followup':'pending';
    view.notice=action==='approve'?'当前版本已审批，仍需单独生成待执行任务。':action==='execute'?'执行草稿已生成，未向外部系统写入。':'当前版本已提交审批。';
  });
}

document.addEventListener('submit',event=>{
  const form=event.target;if(!(form instanceof HTMLFormElement))return;event.preventDefault();
  const view=views.get(active);if(mutation || view.pending || !form.reportValidity())return;
  const values=Object.fromEntries(new FormData(form));
  if(form.id==='overview-form'){view.filter=values;void loadView(view);}
  if(form.id==='workbench-form'){editWorkbench(view,form);void calculate(view);}
  if(form.id==='simulation-form'){
    view.simulation=values;
    try{view.preview=contract.buildSimulationRequest({...values,horizon_days:Number(values.horizon_days),reduction_pct:Number(values.reduction_pct),category:values.category || null},view.data);view.result=null;view.error=null;render(view);$('#scenario-preview')?.scrollIntoView({block:'center'});}catch(error){view.error=error;render(view);}
  }
  if(form.id==='feedback-form'){
    const riskId=view.riskId, session=feedbackSession(riskId);session.text=values.raw_text;
    void act(view,async()=>{
      if(!session.investigationId){const investigation=await post(`/risks/${riskId}/investigations`);if(!investigation.id)throw new Error('核查接口未返回编号');session.investigationId=investigation.id;}
      const fb=await post(`/investigations/${session.investigationId}/feedback`,{raw_text:session.text,timezone:'Asia/Shanghai'});
      if(!fb.id || !fb.draft || fb.raw_text!==session.text || fb.investigation_id!==session.investigationId)throw new Error('反馈响应与本次核查不一致');
      session.feedback=fb;session.review=createFeedbackReview(fb);session.reviewDirty=false;view.notice='原文已保存。请逐条核查，尚不确定的情况保留为待核实。';
    });
  }
  if(form.id==='feedback-confirm-form'){
    const riskId=view.riskId, session=feedbackSession(riskId), fb=session.feedback;
    let confirmed;
    try{if(!fb || fb.confirmation_status==='confirmed' || session.text!==fb.raw_text || !form.elements.reviewed.checked)throw new Error('请先保存并核对当前原文，再确认本次核查。');confirmed=buildFeedbackConfirmation(values,fb);}catch(error){notify(error.message);return;}
    void act(view,async()=>{const result=await post(`/feedback/${fb.id}/confirm`,{confirmed});if(result.id!==fb.id || result.investigation_id!==fb.investigation_id || result.raw_text!==fb.raw_text || result.confirmation_status!=='confirmed')throw new Error('反馈确认没有取得对应回执');session.feedback=result;session.review=createFeedbackReview(result);session.reviewDirty=false;view.notice='人工反馈版本已确认；请刷新方案检查是否需要重算。';views.get('today').data=null; for(const wb of views.values()) if(WORKBENCHES.has(wb.route) && Number(wb.riskId)===Number(riskId)){wb.dirty=true;wb.data=null;}});
  }
  if(form.classList.contains('task-form')){
    void saveTaskReceipt(view,form);
  }
});
document.addEventListener('input',event=>{
  const view=views.get(active);if(mutation || view.pending)return;
  const form=event.target.closest('form');
  if(event.target.id==='queue-search'){view.query=event.target.value;$('#queue-results').innerHTML=todayResultsMarkup(view);}
  if(form?.classList.contains('task-form'))editTaskReceipt(view,form);
  if(form?.id==='workbench-form' && event.target.name!=='risk_id') editWorkbench(view,form);
  if(form?.id==='simulation-form') {view.simulation=Object.fromEntries(new FormData(form));view.preview=null;view.result=null;view.error=null;$('#scenario-preview')?.remove();$('#simulation-result')?.remove();$('#page-status').innerHTML=panel('条件已变化','<p>请重新核对情景，旧确认与结果已失效。</p>');}
  if(form?.id==='feedback-form') {
    const session=feedbackSession(view.riskId);session.text=form.elements.raw_text.value;
    const review=$('#feedback-review-content');
    if(review && session.feedback) review.innerHTML=session.text===session.feedback.raw_text?renderFeedbackReview(session.feedback,session.review):panel('原文已修改','<p>请先保存当前原文，再核对对应版本。</p>','is-warning');
  }
  if(form?.id==='feedback-confirm-form') {
    if(event.target.name!=='reviewed') form.elements.reviewed.checked=false;
    const session=feedbackSession(view.riskId);
    session.review={...Object.fromEntries(new FormData(form)),reviewed:form.elements.reviewed.checked};
    if(event.target.name!=='reviewed')session.reviewDirty=true;
  }
});
document.addEventListener('change',event=>{
  const view=views.get(active);if(mutation || view.pending)return;
  if(event.target.name==='risk_id'){view.riskId=Number(event.target.value);view.data=null;view.notice='';void loadView(view);}
  if(event.target.name==='store_sort'){view.sort=event.target.value;render(view);}
  if(event.target.name==='risk_types'){view.riskTypes=[...event.target.selectedOptions].map(x=>x.value);render(view);}
  if(event.target.name==='action' && WORKBENCHES.has(active))render(view);
});
document.addEventListener('click',event=>{
  const target=event.target.closest('button');if(!target || target.disabled)return;
  const view=views.get(active);if(target.dataset.proposalAction){void proposalAction(view,target);return;}
  if(target.dataset.risk){const diagnosis=views.get('slow_moving');diagnosis.riskId=Number(target.dataset.risk);diagnosis.data=null;location.hash='slow_moving';return;}
  const action=target.dataset.action;
  if(action==='reload')void loadView(view);
  if(action==='tab'){view.tab=target.dataset.tab;render(view);}
  if(action==='save')void save(view);
  if(action==='export-proposal')void exportProposal(view,target);
  if(action==='save-draft' && !view.inputIssues?.length){const payload=structuredClone(view.input);void act(view,()=>persistWorkbenchInput(view,payload));}
  if(action==='discard-edits'){
    workbenchEdits.discard(view.route,view.riskId);view.notice='已放弃此商品在本页尚未保存的编辑；正在重新读取服务端输入。';void loadView(view);
  }
  if(action==='discard-receipt'){
    taskReceipts.discard(target.dataset.taskId);view.notice='已放弃此任务的本地编辑，正在读取服务端记录。';void loadView(view);
  }
  if(action==='resume-receipt'){
    const task=view.data.tasks.find(t=>t.id===target.dataset.taskId);
    if(task){view.tab=['received','completed'].includes(task.status)?'completed':'followup';view.query=task.id;render(view);$(`form[data-task-id="${CSS.escape(task.id)}"] [name="status"]`)?.focus();}
  }
  if(action==='open-workbench'){
    const wb=views.get(target.dataset.module);wb.riskId=Number(target.dataset.riskId || view.riskId);wb.data=null;location.hash=wb.route;
  }
  if(action==='replan')void act(view,async()=>{contract.validateProposal(await post(`/risks/${view.riskId}/replan`));view.notice='后端已按确认事实重算，新的方案仍需审批。';views.get('today').data=null;});
  if(action==='revise-simulation'){view.preview=null;render(view);$('#simulation-form [name="reduction_pct"]').focus();}
  if(action==='confirm-simulation' && view.preview){const request=structuredClone(view.preview);view.preview=null;void act(view,async()=>{view.result=contract.validateSimulation(await post('/retail/simulate',request),request);view.notice=view.result.status==='completed'?'后端计算完成；请核对两种方案的采购、库存和风险。':'当前资料不足以计算，未生成演示结果。';});}
});
$('.skip-link').addEventListener('click',event=>{event.preventDefault();$('#workspace').focus();});
window.addEventListener('hashchange',navigate);
window.addEventListener('beforeunload',event=>{
  if(mutation || hasUnsavedEdits()){event.preventDefault();event.returnValue='';}
});
navigate();

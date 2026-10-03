import test from 'node:test';
import assert from 'node:assert/strict';
import { buildProposalExport, canExportProposal, ProposalExportError, EXPORT_NOTICE } from '../assets/js/proposal-export.mjs';

const exportedAt = '2026-10-03T15:00:00+08:00';
function proposal(type='transfer') {
  return {
    id:'PROP-TEST-1',tenant_id:'demo',risk_id:1,current_version:2,status:'draft',snapshot_id:'snapshot-demo-v1',fact_version:1,
    version:{proposal_id:'PROP-TEST-1',version:2,status:'draft',payload:{
      proposal_type:type,
      input:{risk_id:1,product:'坚果礼盒 750g',lot_id:'LOT-1',source_store:'文三店',target_store:'未来店',quantity:40,unit_cost:'80.00',action:'delay_payment'},
      calculation:{valid:true,errors:[],allocation:{lot_id:'LOT-1',quantity:40},cash:{inventory_cost:'3200.00',estimated_net_cash_improvement:null,known_cash_effect:'-86.00',avoided_loss:null,completeness:'unavailable',missing_fields:['target_store_future_sales_receipts'],assumptions:[]}},
      basis:{snapshot_id:'snapshot-demo-v1',fact_version:1,calculation_version:'teacher-v1',proposal_version:2,risk_id:1},
    }},
  };
}
function taskFor(value=proposal()) {
  return {id:'TASK-1',tenant_id:value.tenant_id,proposal_id:value.id,proposal_version:value.current_version,status:'draft_pending_external_execution',metadata:{external_write:false,receipt_ref:null,actual_cash:null}};
}
const build = (value=proposal(), options={}) => buildProposalExport(value,{exportedAt,...options});
const documentFor = (value, options) => JSON.parse(build(value,options).json);
const rowFor = (document,category,field) => document.rows.find(row=>row.category===category && row.field===field);

// Parse actual CSV cells, including embedded CRLF and doubled quotes. Assertions
// verify spreadsheet structure rather than matching one escaped string.
function parseCsv(csv) {
  const rows=[]; let row=[],value='',quoted=false;
  csv=csv.replace(/^\uFEFF/,'');
  for(let i=0;i<csv.length;i++) {
    const c=csv[i];
    if(c==='"') { if(quoted && csv[i+1]==='"'){value+='"';i++;}else quoted=!quoted; }
    else if(c===',' && !quoted){row.push(value);value='';}
    else if(c==='\r' && csv[i+1]==='\n' && !quoted){row.push(value);rows.push(row);row=[];value='';i++;}
    else value+=c;
  }
  assert.equal(quoted,false);
  assert.deepEqual(row,[]);
  return rows;
}

test('saved proposals produce traceable JSON and Excel CSV with an explicit preparation-only notice',()=>{
  const value=proposal(),before=structuredClone(value),result=build(value),doc=JSON.parse(result.json);
  assert.equal(canExportProposal(value),true);
  assert.equal(result.fileStem,'execution-preparation-PROP-TEST-1-v2');
  assert.equal(result.summary.proposalId,value.id);
  assert.equal(result.summary.version,2);
  assert.equal(result.summary.notice,EXPORT_NOTICE);
  assert.equal(doc.metadata.snapshot_id,value.snapshot_id);
  assert.equal(doc.metadata.fact_version,1);
  assert.equal(doc.metadata.calculation_version,'teacher-v1');
  assert.equal(doc.metadata.exported_at,exportedAt);
  assert.equal(doc.notice,EXPORT_NOTICE);
  assert.ok(result.csv.startsWith('\uFEFF'));
  const rows=parseCsv(result.csv);
  assert.deepEqual(rows[0],['分类','字段','值','单位']);
  assert.ok(rows.every(row=>row.length===4));
  assert.equal(result.summary.rowCount,rows.length-1);
  assert.deepEqual(value,before,'export must not modify current API state');
});

test('all three supported workbenches retain their saved action and calculation fields',()=>{
  const expiry=proposal('expiry-rescue');
  expiry.version.payload.input.promo_qty=12;
  expiry.version.payload.calculation.forecast={normal_sale_qty:11,expected_remaining_qty:39};
  expiry.version.payload.calculation.alternatives=[{type:'促销',quantity:12,fee:'120.00',cash_impact:null,remaining_risk:39,assumption:'投放量不代表确定销量'}];
  assert.equal(rowFor(documentFor(expiry),'处置数量','预计剩余数量').value,39);
  assert.equal(rowFor(documentFor(expiry),'处置比较 1','现金影响').value,null);
  const procurement=proposal('procurement-brake');
  procurement.version.payload.calculation.payment={adjusted_amount:'2360.00',baseline_in_window:true,scenario_in_window:false,deferred_payment_pressure:'2360.00'};
  const doc=documentFor(procurement);
  assert.equal(rowFor(doc,'已保存输入','采购调整方式').value,'delay_payment');
  assert.equal(rowFor(doc,'已保存输入','采购调整方式').displayValue,'推迟付款');
  assert.equal(rowFor(doc,'付款压力','评估期后的付款压力').value,'2360.00');
  assert.equal(rowFor(doc,'付款压力','方案付款在评估期内').displayValue,'否');
});

test('money is copied from the API without deriving or rescaling it and null remains unknown',()=>{
  const value=proposal();
  value.version.payload.calculation.cash.inventory_cost='9999.25';
  value.version.payload.calculation.cash.known_cash_effect=0;
  const result=build(value),doc=JSON.parse(result.json),rows=parseCsv(result.csv);
  assert.equal(rowFor(doc,'现金口径','涉及库存成本').value,'9999.25');
  assert.equal(rowFor(doc,'现金口径','已知现金影响').value,0);
  assert.equal(rowFor(doc,'现金口径','预计净现金改善').value,null);
  assert.deepEqual(rows.find(row=>row[1]==='预计净现金改善'),['现金口径','预计净现金改善','未知（源数据未提供）','元']);
  assert.deepEqual(rows.find(row=>row[1]==='已知现金影响'),['现金口径','已知现金影响','0','元']);
  assert.equal(parseCsv(build().csv).find(row=>row[1]==='已知现金影响')[2],'-86.00');
});

test('missing units are not inferred from package names and unsupported API additions stay outside the document',()=>{
  const value=proposal();
  value.version.payload.input.product='纯牛奶整箱 250ml×24';
  value.version.payload.input.private_internal_field='not-business-data';
  value.version.payload.calculation.unreviewed_new_total='12345.00';
  const result=build(value),doc=JSON.parse(result.json);
  assert.equal(doc.metadata.quantity_unit,null);
  assert.equal(rowFor(doc,'已保存输入','库存单位').value,null);
  assert.equal(rowFor(doc,'已保存输入','调拨数量').unit,'未知（源数据未提供）');
  assert.ok(!result.json.includes('private_internal_field'));
  assert.ok(!result.json.includes('12345.00'));
  value.version.payload.input.unit='袋';
  assert.equal(rowFor(documentFor(value),'已保存输入','调拨数量').unit,'袋');
});

test('seed action-only proposals and unsupported types are explicitly rejected',()=>{
  const value=proposal();
  value.version.payload={proposal_type:'transfer',actions:[{type:'transfer',quantity:40}],cash:{},basis:{}};
  assert.equal(canExportProposal(value),false);
  assert.throws(()=>build(value),/工作台计算并保存当前版本/);
  for(const type of ['cashflow_simulation','slow_moving','constructor']) {
    const value=proposal(type);
    assert.equal(canExportProposal(value),false);
    assert.throws(()=>build(value),ProposalExportError);
  }
});

test('identity, version, snapshot, facts and calculation validity must agree',()=>{
  const changes=[
    value=>value.version.version=3,
    value=>value.version.proposal_id='OTHER',
    value=>value.version.payload.basis.proposal_version=1,
    value=>value.version.payload.basis.snapshot_id='other-snapshot',
    value=>value.version.payload.basis.fact_version=2,
    value=>value.version.payload.basis.risk_id=2,
    value=>value.version.payload.input.risk_id=2,
    value=>value.version.payload.calculation.valid=false,
    value=>value.version.payload.calculation.errors=['库存已被另一方案占用'],
    value=>delete value.version.payload.basis.calculation_version,
  ];
  for(const change of changes) {const value=proposal();change(value);assert.throws(()=>build(value),ProposalExportError);assert.equal(canExportProposal(value),false);}
});

test('invalidated or recalculation states never become execution preparation documents',()=>{
  for(const status of ['invalidated','needs_replan','replan_pending','completed','unknown']) {
    const value=proposal();value.status=status;
    assert.throws(()=>build(value),/失效|待重算|状态/);
  }
  const value=proposal();value.version.status='approved';
  assert.throws(()=>build(value),/状态不一致/);
});

test('malformed monetary and quantity values are rejected instead of becoming zero or rounded figures',()=>{
  for(const invalid of ['',false,[],{},NaN,Infinity,Number.MAX_SAFE_INTEGER,'1e3','01.20','1.234','NaN','=1+1']) {
    const value=proposal();value.version.payload.calculation.cash.known_cash_effect=invalid;
    assert.throws(()=>build(value),ProposalExportError,String(invalid));
    assert.equal(canExportProposal(value),false);
  }
  const value=proposal();value.version.payload.input.quantity='forty';
  assert.throws(()=>build(value),/调拨数量/);
});

test('CSV formula prefixes are neutralized while exact source text is retained in JSON',()=>{
  for(const text of ['=HYPERLINK("https://example.invalid","x")','+SUM(1,2)','-SUM(1,2)','@SUM(1,2)',' \t=1+1','\tordinary text','\r\n=1+1','\uFEFF=1+1','\u0000=1+1','\u001b=1+1']) {
    const value=proposal();value.version.payload.input.product=text;
    const result=build(value),row=parseCsv(result.csv).find(row=>row[1]==='商品');
    assert.equal(row[2],"'"+text);
    assert.equal(rowFor(JSON.parse(result.json),'已保存输入','商品').value,text);
  }
});

test('commas, quotes and embedded newlines remain one spreadsheet field',()=>{
  const value=proposal();value.version.payload.input.product='坚果,"礼盒"\r\n750g';
  const rows=parseCsv(build(value).csv);
  assert.ok(rows.every(row=>row.length===4));
  assert.equal(rows.find(row=>row[1]==='商品')[2],value.version.payload.input.product);
});

test('task association rejects another proposal, another version or another tenant',()=>{
  const value=proposal();
  assert.throws(()=>build(value,{task:taskFor(value)}),/尚未记录生成执行任务/);
  value.status='execution_task_created';value.version.status='approved';
  for(const change of [task=>task.proposal_id='OTHER',task=>task.proposal_version=1,task=>task.tenant_id='other']) {
    const task=taskFor(value);change(task);
    assert.throws(()=>build(value,{task}),ProposalExportError);
  }
});

test('current manual task receipts preserve unknown money and do not claim external execution',()=>{
  const value=proposal();value.status='execution_task_created';value.version.status='approved';
  const task=taskFor(value);task.status='completed';task.metadata={external_write:false,receipt_ref:'=unsafe-receipt',actual_cash:null};
  const result=build(value,{task}),doc=JSON.parse(result.json);
  assert.equal(doc.metadata.task_status,'completed');
  assert.equal(rowFor(doc,'人工执行记录','任务状态').displayValue,'人工记录已完成');
  assert.equal(rowFor(doc,'人工执行记录','人工填报现金').value,null);
  assert.equal(rowFor(doc,'人工执行记录','源记录是否标记外部写入').value,false);
  assert.equal(parseCsv(result.csv).find(row=>row[1]==='人工回执号')[2],"'=unsafe-receipt");
  task.metadata_json=JSON.stringify(task.metadata);delete task.metadata;
  assert.equal(rowFor(documentFor(value,{task}),'人工执行记录','人工回执号').value,'=unsafe-receipt');
  task.metadata_json='{bad';assert.throws(()=>build(value,{task}),/任务记录格式/);
});

test('timestamps require a timezone and generated file names cannot escape a directory',()=>{
  for(const time of ['yesterday','2026-10-03','2026-10-03T15:00:00','2026-99-03T15:00:00Z','2026-02-30T12:00:00Z','2026-10-03T24:00:00Z',null])assert.throws(()=>build(proposal(),{exportedAt:time}),/导出时点/);
  const value=proposal();value.id='../x:"name\r\n';value.version.proposal_id=value.id;
  const result=build(value);
  assert.match(result.fileStem,/^[A-Za-z0-9_-]+$/);
  assert.equal(JSON.parse(result.json).metadata.proposal_id,value.id);
});

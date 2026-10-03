import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

// Synthetic fixtures only. Never connects to the application's database.
const root = process.argv[2];
if (!root) throw new Error('Pass the retail-v2 output directory');
const out = path.join(root, 'xlsx');
const previews = '/private/tmp/retail-xlsx-20261003/previews';
await fs.mkdir(out, { recursive: true });
await fs.mkdir(previews, { recursive: true });
const SEED = 20261003;
let rng = SEED;
const random = () => { rng = (Math.imul(1664525, rng) + 1013904223) >>> 0; return rng / 4294967296; };
const pad = n => String(n).padStart(3, '0');
const money = n => Math.round((n + Number.EPSILON) * 100) / 100;
const date = (start, offset) => new Date(Date.parse(start + 'T00:00:00Z') + offset * 86400000).toISOString().slice(0, 10);
const known = '2026-10-03T00:00:00+08:00';
const decision = '2026-10-03T09:30:00+08:00';
const snap = 'SNAP-20261003-BASE';
const meta = { source: 'synthetic_seed_20261003', is_demo: true, data_version: 'retail-v2.1', known_at: known };
const rec = (r, at = known) => ({ ...r, ...meta, known_at: at });
const stores = Array.from({ length: 50 }, (_, i) => rec({
  store_id: `ST-${pad(i + 1)}`,
  store_name: ['西湖古荡店','西湖文三店','余杭未来店','上城庆春店','拱墅运河店','滨江长河店'][i] || `杭州名录门店${pad(i+1)}`,
  region: '杭州市', store_type: '社区零食店', latitude: money(30.25 + (i % 10)*.008), longitude: money(120.10 + Math.floor(i/10)*.015),
  coordinate_system: 'WGS84', open_date: '2025-01-01', status: 'open', data_scope: i < 6 ? 'complete_fixture' : 'directory_only',
  include_in_summary: i < 6,
}));
// Fictional coordinates: schematic route inputs, not real store locations.
const productDefs = [
 ['每日坚果礼盒 750g','坚果','750g','盒',80,100,365],
 ['炭烤腰果礼盒 600g','坚果','600g','盒',60,88,365],
 ['海盐薯片分享装 80g×8','膨化','80g×8','件',40,60,180],
 ['酸奶夹心饼干 100g','饼干','100g','袋',5,8,365],
 ['芝士威化 500g','饼干','500g','盒',20,30,365],
 ['水果软糖 500g','糖果','500g','袋',8,12,365],
 ['山楂果脯礼盒 1kg','果脯','1kg','盒',35,50,365],
 ['气泡果汁 330ml','饮料','330ml','瓶',3,5,365],
 ['混合坚果 1kg','坚果','1kg','袋',50,70,365],
 ['牛肉干 100g','肉脯','100g','袋',12,18,365],
 ['水果果冻桶 1kg','糖果','1kg','桶',10,15,365],
 ['全麦苏打饼干 250g','饼干','250g','袋',6,9,365],
];
const products = productDefs.map((p, i) => rec({sku_id:`SKU-${pad(i+1)}`, product_name:p[0],category_id:p[1],specification:p[2],base_unit:p[3],purchase_unit:'箱',units_per_purchase_unit: i===2?4:12,shelf_life_days:p[6],storage_condition:'ambient_dry',default_unit_cost:p[4],regular_unit_price:p[5],gross_weight_kg:[.85,.7,.8,.12,.55,.55,1.1,.36,1.1,.12,1.1,.28][i],volume_m3:.003,supplier_id:`SUP-${pad(i%3+1)}`}));
const suppliers = [1,2,3].map(i => rec({supplier_id:`SUP-${pad(i)}`,supplier_name:`零食仓合成供应商${i}`,confirmation_contact_role:'供应商业务专员',confirmation_channel:'email',contact_email:`supplier${i}@example.invalid`}));
const people = ['管理员','古荡店店长','文三店店长','李采购','陈财务'].map((name,i)=>rec({person_id:`P-${pad(i+1)}`,display_name:name,role:['administrator','store_manager','store_manager','purchaser','finance'][i],store_id:i===1?'ST-001':i===2?'ST-002':null,channel_target:`local-person-${i+1}`}));
const policies = [rec({policy_id:'POL-001',scope:'all_complete_stores',valid_from:'2026-07-05',valid_to:'2027-01-01',slow_coverage_days_threshold:60,min_observed_days:21,expiry_alert_days:21,stop_sale_days_before_expiry:1,safety_stock_qty:10,target_coverage_days:21,rule_version:1}),rec({policy_id:'POL-002',scope:'S07:ST-004:SKU-003',valid_from:'2026-10-03',valid_to:'2026-11-02',slow_coverage_days_threshold:60,min_observed_days:21,expiry_alert_days:21,stop_sale_days_before_expiry:1,safety_stock_qty:70,target_coverage_days:14,rule_version:1})];
const configs=[], inventory=[], lots=[], sales=[], availability=[], movements=[], historicalOrders=[];
const totals = new Map();
for(let s=0;s<6;s++) for(let k=0;k<12;k++) {
  const st=stores[s], p=products[k], key=`${st.store_id}:${p.sku_id}`, lot=`LOT-${pad(s+1)}-${pad(k+1)}`;
  const qty = s===0&&k===0?120:s===1&&k===0?10:s===2&&k===0?200:s===2&&k===1?90:s===0&&k===2?60:s===3&&(k===3||k===7)?60:30+Math.floor(random()*71);
  const daily = Array.from({length:90},(_,d)=>s===0&&k===0?([0,3,5,8,10,13,15,18,20,23,25,28].includes(d%30)?1:0):s===1&&k===0?4:s===2&&k===0?8:s===2&&k===1?1:s===0&&k===2?10:s===3&&k===3?6:1+Math.floor(random()*5));
  const replenishments=new Map();
  for(let d=7;d<90;d+=7) replenishments.set(d,daily.slice(d-7,d).reduce((a,b)=>a+b,0));
  const total=daily.reduce((a,b)=>a+b,0), opening=qty+total-[...replenishments.values()].reduce((a,b)=>a+b,0);
  const production='2026-06-01', expiry=s===0&&k===2?'2026-10-14':date(production,p.shelf_life_days);
  const initialPO=`PO-OPEN-${pad(s+1)}-${pad(k+1)}`;
  lots.push(rec({lot_id:lot,sku_id:p.sku_id,supplier_id:p.supplier_id,supplier_batch_no:`BATCH-${lot}`,production_date:production,expiry_date:expiry,purchase_order_line_id:initialPO}));
  historicalOrders.push(rec({po_id:initialPO,po_line_id:initialPO,supplier_id:p.supplier_id,store_id:st.store_id,sku_id:p.sku_id,lot_id:lot,ordered_qty:opening,unit_cost:p.default_unit_cost,received_qty:opening,paid_amount:money(opening*p.default_unit_cost),payment_status:'paid',ordered_at:'2026-07-04',original_document_ref:initialPO},'2026-07-04T18:00:00+08:00'));
  movements.push(rec({movement_id:`OPEN-${key}`,date:'2026-07-05',store_id:st.store_id,sku_id:p.sku_id,lot_id:lot,event_type:'opening_balance',quantity_delta:opening,document_ref:initialPO},'2026-07-05T00:00:00+08:00'));
  let balance=opening;
  for(let d=0;d<90;d++) {
    const day=date('2026-07-05',d), start=balance, receipt=replenishments.get(d)||0, n=daily[d];
    if(receipt) {
      const po=`PO-${pad(s+1)}-${pad(k+1)}-${pad(d)}`;
      historicalOrders.push(rec({po_id:po,po_line_id:po,supplier_id:p.supplier_id,store_id:st.store_id,sku_id:p.sku_id,lot_id:lot,ordered_qty:receipt,unit_cost:p.default_unit_cost,received_qty:receipt,paid_amount:money(receipt*p.default_unit_cost),payment_status:'paid',ordered_at:date(day,-1),original_document_ref:po},`${date(day,-1)}T18:00:00+08:00`));
      movements.push(rec({movement_id:`IN-${key}-${d}`,date:day,store_id:st.store_id,sku_id:p.sku_id,lot_id:lot,event_type:'purchase_receipt',quantity_delta:receipt,document_ref:po},`${day}T08:00:00+08:00`));
    }
    const id=`SALE-${pad(s+1)}-${pad(k+1)}-${pad(d)}`;
    balance += receipt-n;
    sales.push(rec({sales_day_id:id,date:day,store_id:st.store_id,sku_id:p.sku_id,lot_id:lot,sold_qty:n,customer_return_qty:0,sales_amount:money(n*p.regular_unit_price),refund_amount:0,sold_cost:money(n*p.default_unit_cost),returned_cost:0,regular_unit_price:p.regular_unit_price,actual_unit_price:p.regular_unit_price,promotion_id:null},`${day}T23:00:00+08:00`));
    availability.push(rec({date:day,store_id:st.store_id,sku_id:p.sku_id,opening_qty:start,received_qty:receipt,closing_qty:balance,open_hours:12,on_shelf_hours:12,in_stock_hours:12,listing_status:'listed',stockout_flag:false},`${day}T23:00:00+08:00`));
    if(n) movements.push(rec({movement_id:`OUT-${id}`,date:day,store_id:st.store_id,sku_id:p.sku_id,lot_id:lot,event_type:'sale',quantity_delta:-n,document_ref:id},`${day}T23:00:00+08:00`));
  }
  inventory.push(rec({inventory_id:`INV-${pad(s+1)}-${pad(k+1)}`,snapshot_id:snap,snapshot_at:known,store_id:st.store_id,sku_id:p.sku_id,lot_id:lot,stock_state:'on_hand',quantity:qty,shipment_line_id:null,blocked_qty:0,reserved_qty:0,unit_cost:p.default_unit_cost,sellable_until:date(expiry,-1)}));
  configs.push(rec({store_id:st.store_id,sku_id:p.sku_id,is_listed:true,can_receive_transfer:true,capacity_qty:500,safety_stock_qty:k===0?10:20,target_coverage_days:21,min_receive_sellable_days:7,storage_condition:'ambient_dry'}));
  totals.set(key,{s30:daily.slice(-30).reduce((a,b)=>a+b,0),s90:total,ending:balance});
}

const forecasts=[],routes=[],calendar=[];
for(let s=0;s<6;s++) {
  for(let d=0;d<30;d++) calendar.push(rec({store_id:stores[s].store_id,date:date('2026-10-03',d),is_open:true,can_receive:true,receive_window:'09:00-17:00',capacity_override:null}));
  for(let k=0;k<12;k++) for(let d=0;d<30;d++) {
    const p=products[k], st=stores[s], base=s===0&&k===0?.4:s===1&&k===0?4:s===2&&k===0?8:s===0&&k===2?10:money(totals.get(`${st.store_id}:${p.sku_id}`).s30/30);
    forecasts.push(rec({forecast_id:`FC-${pad(s+1)}-${pad(k+1)}-${pad(d)}`,store_id:st.store_id,sku_id:p.sku_id,date:date('2026-10-03',d),demand_low:money(base*.7),demand_base:base,demand_high:money(base*1.3),method:'synthetic_scenario_assumption',assumption_id:'ASSUMPTION-DEMAND-001',generated_at:decision},decision));
  }
  for(let t=0;t<6;t++) if(s!==t) routes.push(rec({route_id:`RT-${pad(s+1)}-${pad(t+1)}`,from_store_id:stores[s].store_id,to_store_id:stores[t].store_id,route_label:`${stores[s].store_name} → ${stores[t].store_name}`,route_points:JSON.stringify([[stores[s].longitude,stores[s].latitude],[stores[t].longitude,stores[t].latitude]]),distance_km:s===0&&t===1?3.6:money(5+Math.abs(s-t)*3.4),travel_minutes:s===0&&t===1?12:20+Math.abs(s-t)*9,dispatch_rule:'次日09:00发车；预约次日收货窗口',handling_minutes:45,eta_days:1,fee_amount:s===0&&t===1?24:30+Math.abs(s-t)*12,fee_basis:'每趟新增现金支出；固定价',max_qty_per_trip:100,quantity_unit:'盒',applicable_sku_id:'SKU-001',storage_condition:'ambient_dry',valid_from:'2026-10-03',valid_to:'2026-11-02',version:1}));
}
const plannedOrders = [rec({po_id:'PO-FUT-001',po_line_id:'POL-FUT-001',supplier_id:'SUP-001',store_id:'ST-003',sku_id:'SKU-001',lot_id:'LOT-INBOUND-001',ordered_qty:100,received_qty:0,unit_cost:80,paid_amount:0,payment_status:'unpaid',order_status:'confirmed',due_at:'2026-10-10',original_document_ref:'MAT-PO-001'}),rec({po_id:'PO-FUT-002',po_line_id:'POL-FUT-002',supplier_id:'SUP-003',store_id:'ST-004',sku_id:'SKU-003',lot_id:'LOT-INBOUND-002',ordered_qty:30,received_qty:0,unit_cost:40,paid_amount:1200,payment_status:'paid',order_status:'confirmed',due_at:'2026-10-02',original_document_ref:'MAT-PO-002'})];
const inbound=plannedOrders.map((p,i)=>rec({shipment_line_id:`SHIP-${pad(i+1)}`,purchase_order_line_id:p.po_line_id,transfer_order_line_id:null,store_id:p.store_id,sku_id:p.sku_id,lot_id:p.lot_id,shipped_qty:p.ordered_qty,received_qty:0,expected_arrival_at:'2026-10-04T12:00:00+08:00',status:'in_transit',ownership:'enterprise',unit_cost:p.unit_cost}));
for(let i=0;i<2;i++) {
  const p=plannedOrders[i];
  lots.push(rec({lot_id:p.lot_id,sku_id:p.sku_id,supplier_id:p.supplier_id,supplier_batch_no:`BATCH-IN-${i+1}`,production_date:'2026-09-01',expiry_date:'2027-02-28',purchase_order_line_id:p.po_line_id}));
  inventory.push(rec({inventory_id:`INV-IN-${i+1}`,snapshot_id:snap,snapshot_at:known,store_id:p.store_id,sku_id:p.sku_id,lot_id:p.lot_id,stock_state:'in_transit',quantity:p.ordered_qty,shipment_line_id:`SHIP-${pad(i+1)}`,blocked_qty:0,reserved_qty:0,unit_cost:p.unit_cost,sellable_until:'2027-02-27'}));
}
const accounts=[rec({account_id:'ACC-001',account_name:'零食仓合成经营账户',currency:'CNY',snapshot_at:known,available_balance:858900,source_document:'ACCOUNT-SNAPSHOT-001',scope:'BASE;各独立场景从此余额起算'})];
const payables=plannedOrders.map(p=>rec({payable_id:`AP-${p.po_id}`,supplier_id:p.supplier_id,po_id:p.po_id,original_amount:p.ordered_qty*p.unit_cost,due_at:p.due_at,paid_amount:p.paid_amount,applied_credit_amount:0,outstanding_amount:p.ordered_qty*p.unit_cost-p.paid_amount,status:p.payment_status}));
const terms=[rec({term_id:'TERM-001',supplier_id:'SUP-002',sku_scope:'SKU-011',effective_from:'2026-07-01',effective_to:'2026-12-31',allowed_settlement_modes:'cash_refund;exchange;payable_credit',return_deadline_rule:'申请时剩余保质期至少30天',min_remaining_shelf_life_days:30,packaging_requirements:'未拆封、外箱完整',max_return_qty:100,max_return_ratio:100,refund_price_rule:'原进货价的90%',restocking_fee_rule:'0',freight_payer:'retailer',settlement_trigger:'supplier_acceptance',settlement_days:7,source_ref:'MAT-TERM-001',confirmed_by:'P-004',confirmed_at:'2026-10-02T15:00:00+08:00'})];
const promo=[rec({promotion_id:'PROMO-S06',stage_id:'PROMO-S06-1',scenario_id:'S06',store_id:'ST-004',bundle_id:'BUNDLE-001',start_date:'2026-10-03',end_date_exclusive:'2026-10-08',bundle_price:11,floor_price:10,min_margin_pct:20,available_bundle_qty:40,execution_fee:20,forecast_unit:'组/整个阶段',demand_low:10,demand_base:20,demand_high:25,assumption_id:'ASSUMPTION-PROMO-001'}),rec({promotion_id:'PROMO-S06',stage_id:'PROMO-S06-2',scenario_id:'S06',store_id:'ST-004',bundle_id:'BUNDLE-001',start_date:'2026-10-08',end_date_exclusive:'2026-10-13',bundle_price:10,floor_price:10,min_margin_pct:20,available_bundle_qty:40,execution_fee:0,forecast_unit:'组/整个阶段',demand_low:10,demand_base:20,demand_high:25,assumption_id:'ASSUMPTION-PROMO-001'})];
const bundle=[rec({bundle_id:'BUNDLE-001',sku_id:'SKU-004',qty_per_bundle:1,base_unit:'袋',unit_cost:5,regular_unit_price:8}),rec({bundle_id:'BUNDLE-001',sku_id:'SKU-008',qty_per_bundle:1,base_unit:'瓶',unit_cost:3,regular_unit_price:5})];
const assumptions=[rec({assumption_id:'ASSUMPTION-DEMAND-001',kind:'daily_demand',description:'根据合成90天销量建立的演示需求情景；不宣称训练出的销量预测',low_factor:.7,base_factor:1,high_factor:1.3}),rec({assumption_id:'ASSUMPTION-PROMO-001',kind:'promotion_demand',description:'阶段销量是该活动下总销量；替代同期间正常销量，不另行累加。组合需求须扣除组成商品占用。',low_factor:null,base_factor:null,high_factor:null})];

const materials=[
 ['MAT-TERM-001','contract','SUP-002','条款第2条','SKU-011未拆封且余保质期不少于30天，可申请退供最多100桶。结算方式另行书面确认：现金退款、换货或货款抵扣三选一。按采购价90%结算，运费由门店承担；验收后7日内结算。','2026-10-02T15:00:00+08:00'],
 ['MAT-PO-001','purchase_order','SUP-001','订单行1','ST-003订购每日坚果礼盒750g 100盒，单价80元；已发货，预计10月4日到货，10月10日支付8000元。',known],
 ['MAT-PO-002','purchase_order','SUP-003','订单行1','ST-004海盐薯片分享装30件，单价40元，已付1200元；预计10月4日到货。',known],
 ['MAT-INTENT-001','purchase_intent','SUP-003','正文','准备给庆春店订海盐薯片分享装80g×8共100件，每件40元，10月5日到货，10月16日付款。还没联系供应商确认。',decision],
 ['MAT-INTENT-002','purchase_intent','SUP-003','正文','薯片再来两箱，价格照旧。',decision],
 ['MAT-FEEDBACK-001','manager_feedback','ST-001','店长反馈','这批坚果过去30天只有5天上架，其余25天在库未上架；请先核查陈列原因。',decision],
 ['MAT-RETURN-PO','purchase_order','SUP-002','订单行1','ST-003水果果冻桶SKU-011采购100桶，单价10元，已付1000元。未拆封。',known],
].map(([material_id,type,party_id,source_location,text,known_at])=>rec({material_id,type,party_id,source_location,text,evidence_uri:`local-material://${material_id}`},known_at));
const intents=[rec({intent_id:'INTENT-S07-001',scenario_id:'S07',source_ref:'MAT-INTENT-001',channel:'wechat_text',intent_status:'draft_unconfirmed',store_id:'ST-004',sku_id:'SKU-003',quantity:100,unit:'件',unit_cost:40,expected_arrival_date:'2026-10-05',payment_date:'2026-10-16',supplier_id:'SUP-003',confirmation_required:true},decision),rec({intent_id:'INTENT-S07-002',scenario_id:'S07_MISSING',source_ref:'MAT-INTENT-002',channel:'phone_note',intent_status:'draft_unconfirmed',store_id:null,sku_id:null,quantity:2,unit:'箱',unit_cost:null,expected_arrival_date:null,payment_date:null,supplier_id:null,confirmation_required:true},decision)];
const scenarioDefs=[
 ['S01','跨店调拨完整主线','transfer_80','BASE','ST-001','SKU-001','LOT-001-001','2026-10-25','80盒仅为候选；计算工具还需比较原店、其他门店、促销和退供条件'],
 ['S02','滞销与临期重叠','risk_overlap','isolated_risk','ST-001','SKU-001','SCLOT-S02','2026-10-13','独立风险输入；禁止混入BASE库存'],
 ['S03','临期但正常销售可清完','leave_in_store','BASE','ST-001','SKU-003','LOT-001-003','2026-10-13','当前60件、近30天售300件；不机械促销'],
 ['S04','高销量门店已有足够现货与在途','net_demand','BASE','ST-003','SKU-001','LOT-003-001','2026-10-24','现货200与在途100共同消耗需求；10月4日到货'],
 ['S05','退供结算三选一','cash_refund|exchange|payable_credit','isolated_return','ST-003','SKU-011','SCLOT-S05','2026-10-18','同一批100桶；三分支必须使用独立场景ID'],
 ['S06','组合优惠与阶段降价','promotion','BASE','ST-004','SKU-004','LOT-004-004','2026-10-13','饼干+果汁；按组成SKU数量扣减；阶段总需求含正常销售'],
 ['S07','采购意向前置检查','reduce_to_60','isolated_purchase','ST-004','SKU-003','LOT-004-003','2026-10-17','100件意向未下单；场景元信息仅给加载器，不提供给模型'],
 ['S08','反馈核查与闭店后重算','unlisted|closed_target','isolated_feedback','ST-001','SKU-001','LOT-001-001','2026-10-24','事实确认后生成v2；保留v1；目的地变更需重新确认'],
 ['S09','部分执行与部分到账','partial_transfer','BASE','ST-001','SKU-001','LOT-001-001','2026-10-25','计划80，仅收60，20未发；销售40而到账3000'],
 ['S10','正常与缺数据分别返回','normal|missing_sales|missing_expiry','isolated_risk','ST-004','SKU-004','SCLOT-S10','2026-11-02','缺项为空，不能当0或正常'],
];
const scenarios=scenarioDefs.map(([scenario_id,title,branches,input_scope,store_id,sku_id,lot_id,evaluation_end,notes])=>rec({scenario_id,title,branches,input_scope,store_id,sku_id,lot_id,base_snapshot_id:snap,decision_at:decision,evaluation_end,notes}));
const riskInputs=[
 ['S02','overlap','SKU-001',100,30,30,'2026-10-13',80],
 ['S10','only_slow','SKU-002',90,30,30,'2027-01-31',60],
 ['S03','only_expiry','SKU-003',60,300,30,'2026-10-13',40],
 ['S10','normal','SKU-004',60,180,30,'2027-01-31',5],
 ['S10','missing_sales','SKU-004',60,null,null,'2027-01-31',5],
 ['S10','missing_expiry','SKU-004',60,180,30,null,5],
 ['S08','unlisted','SKU-001',120,12,5,'2027-05-31',80],
].map(([scenario_id,branch_id,sku_id,quantity,sales_30,valid_observed_days,sellable_until,unit_cost])=>rec({scenario_id,branch_id,sku_id,quantity,sales_30,valid_observed_days,sellable_until,unit_cost,policy_id:'POL-001',input_scope:'isolated_risk_inputs_replace_full_risk_read_model'}));
const overrides=[
 ['S05','*','inventory','ST-003:SKU-011','quantity',100],['S05','*','inventory','ST-003:SKU-011','lot_id','SCLOT-S05'],['S05','*','inventory','ST-003:SKU-011','unit_cost',10],['S05','*','inventory','ST-003:SKU-011','sellable_until','2027-01-31'],
 ['S07','reduce_to_60','inventory','ST-004:SKU-003','quantity',120],['S07','reduce_to_60','demand_forecasts','ST-004:SKU-003:2026-10-03..2026-10-16','demand_base',10],['S07','reduce_to_60','store_products','ST-004:SKU-003','safety_stock_qty',70],['S07','reduce_to_60','procurement_policy','ST-004:SKU-003','min_order_qty',10],['S07','reduce_to_60','procurement_policy','ST-004:SKU-003','order_multiple',10],['S07','reduce_to_60','transfer_policy','ST-004:SKU-003','available_alternative_transfer_qty',0],
 ['S08','closed_target','store_calendar','ST-002:2026-10-04..2026-10-24','is_open',false],['S08','closed_target','store_calendar','ST-002:2026-10-04..2026-10-24','can_receive',false],
].map(([scenario_id,branch_id,table_name,record_key,field,value],i)=>rec({override_id:`OV-${pad(i+1)}`,scenario_id,branch_id,table_name,record_key,field,value_json:JSON.stringify(value),reason:scenario_id==='S08'?'闭店反馈须管理员确认后生效':'独立场景初始条件；须隔离加载'},scenario_id==='S08'?'2026-10-03T10:05:00+08:00':known));
const scenarioLots=[rec({lot_id:'SCLOT-S05',sku_id:'SKU-011',supplier_id:'SUP-002',production_date:'2026-06-01',expiry_date:'2027-02-01',po_line_id:'MAT-RETURN-PO',scenario_id:'S05'}),rec({lot_id:'SCLOT-S05-REPLACEMENT',sku_id:'SKU-006',supplier_id:'SUP-002',production_date:'2026-09-01',expiry_date:'2027-09-01',po_line_id:null,scenario_id:'S05',input_role:'conditional_replacement_offer'})];

// Future records are deliberately stored in another workbook, never BASE facts.
const events=[],replaySales=[],cash=[],allocations=[],channelActions=[],returnRecords=[];
const event=(scenario_id,branch_id,event_id,occurred_at,event_type,detail)=>events.push(rec({scenario_id,branch_id,event_id,occurred_at,event_type,...detail},occurred_at));
const payment=(scenario_id,branch_id,cash_event_id,occurred_at,direction,amount,business_ref)=>cash.push(rec({scenario_id,branch_id,cash_event_id,account_id:'ACC-001',occurred_at,direction,amount,business_ref,receipt_ref:`BANK-${cash_event_id}`},occurred_at));
const taskDefs=[
 ['TASK-S01','S01','transfer_80','transfer','P-002',80,'盒'],['TASK-S09','S09','partial_transfer','transfer','P-002',80,'盒'],
 ['TASK-S05-CASH','S05','cash_refund','return','P-004',100,'桶'],['TASK-S05-EXCHANGE','S05','exchange','return','P-004',100,'桶'],['TASK-S05-CREDIT','S05','payable_credit','return','P-004',100,'桶'],
 ['TASK-S06','S06','promotion','promotion','P-003',40,'组'],['TASK-S07','S07','reduce_to_60','purchase_change','P-004',60,'件'],
];
const tasks=taskDefs.map(([task_id,scenario_id,branch_id,type,owner_id,planned_qty,unit])=>rec({task_id,scenario_id,branch_id,type,owner_id,planned_qty,unit,proposal_id:`PLAN-${task_id}`,proposal_version:1,approved_by:'P-001',approved_at:'2026-10-03T10:00:00+08:00',due_at:'2026-10-04T17:00:00+08:00',initial_execution_status:'pending',initial_result_status:'pending',completion_criteria:type==='transfer'?'发货及签收量核对；缺量继续跟进':type==='return'?'供应商验收及对应结算凭据核对':type==='purchase_change'?'供应商订单确认与付款计划核对':'活动生效、结束及销售核对',external_write:false},'2026-10-03T10:00:00+08:00'));
const stockReplay=(scenario,branch,prefix,qty,at)=>{
 event(scenario,branch,`${prefix}-OUT`,at,'transfer_shipped',{task_id:scenario==='S01'?'TASK-S01':'TASK-S09',store_id:'ST-001',to_store_id:'ST-002',sku_id:'SKU-001',lot_id:'LOT-001-001',quantity:qty,from_state:'on_hand',to_state:'in_transit',receipt_ref:`DOC-${prefix}-OUT`});
 event(scenario,branch,`${prefix}-IN`,'2026-10-04T12:00:00+08:00','transfer_received',{task_id:scenario==='S01'?'TASK-S01':'TASK-S09',store_id:'ST-002',from_store_id:'ST-001',sku_id:'SKU-001',lot_id:'LOT-001-001',quantity:qty,from_state:'in_transit',to_state:'on_hand',receipt_ref:`DOC-${prefix}-IN`});
};
stockReplay('S01','transfer_80','TRANSFER-S01',80,'2026-10-04T09:00:00+08:00');
payment('S01','transfer_80','CASH-S01-FEE','2026-10-04T09:00:00+08:00','out',24,'RT-001-002');
for(let d=0;d<21;d++) {
 const day=date('2026-10-04',d), qty=d===20?4:3,id=`RS-S01-${pad(d+1)}`;
 replaySales.push(rec({scenario_id:'S01',branch_id:'transfer_80',sale_id:id,date:day,store_id:'ST-002',sku_id:'SKU-001',lot_id:'LOT-001-001',sold_qty:qty,unit_price:100,sales_amount:qty*100,sold_cost:qty*80,attribution:'transferred_lot',task_id:'TASK-S01'},`${day}T20:00:00+08:00`));
 payment('S01','transfer_80',`CASH-${id}`,`${day}T22:00:00+08:00`,'in',qty*100,id);
 allocations.push(rec({scenario_id:'S01',branch_id:'transfer_80',allocation_id:`MATCH-${id}`,cash_event_id:`CASH-${id}`,business_ref:id,allocated_amount:qty*100},`${day}T22:10:00+08:00`));
}
replaySales.push(rec({scenario_id:'S01',branch_id:'transfer_80',sale_id:'RS-S01-EXISTING',date:'2026-10-04',store_id:'ST-002',sku_id:'SKU-001',lot_id:'LOT-002-001',sold_qty:10,unit_price:100,sales_amount:1000,sold_cost:800,attribution:'existing_destination_lot',task_id:null},'2026-10-04T19:00:00+08:00'));
payment('S01','transfer_80','CASH-S01-EXISTING','2026-10-04T22:00:00+08:00','in',1000,'RS-S01-EXISTING');
allocations.push(rec({scenario_id:'S01',branch_id:'transfer_80',allocation_id:'MATCH-S01-EXISTING',cash_event_id:'CASH-S01-EXISTING',business_ref:'RS-S01-EXISTING',allocated_amount:1000},'2026-10-04T22:10:00+08:00'));
stockReplay('S09','partial_transfer','TRANSFER-S09',60,'2026-10-04T09:00:00+08:00');
event('S09','partial_transfer','EXCEPTION-S09','2026-10-04T09:05:00+08:00','execution_exception',{task_id:'TASK-S09',affected_qty:20,reason:'余下20盒未交承运人；等待总部安排第二趟',resolved:false});
replaySales.push(rec({scenario_id:'S09',branch_id:'partial_transfer',sale_id:'RS-S09',date:'2026-10-18',store_id:'ST-002',sku_id:'SKU-001',lot_id:'LOT-001-001',sold_qty:40,unit_price:100,sales_amount:4000,sold_cost:3200,attribution:'transferred_lot',task_id:'TASK-S09'},'2026-10-18T20:00:00+08:00'));
payment('S09','partial_transfer','CASH-S09','2026-10-19T09:00:00+08:00','in',3000,'RS-S09');
payment('S09','partial_transfer','CASH-S09-FEE','2026-10-04T09:00:00+08:00','out',24,'RT-001-002');
allocations.push(rec({scenario_id:'S09',branch_id:'partial_transfer',allocation_id:'MATCH-S09',cash_event_id:'CASH-S09',business_ref:'RS-S09',allocated_amount:3000},'2026-10-19T09:10:00+08:00'));
for(const mode of ['cash_refund','exchange','payable_credit']) {
 const suffix=mode==='cash_refund'?'CASH':mode==='exchange'?'EXCHANGE':'CREDIT',task=`TASK-S05-${suffix}`,ret=`RETURN-${suffix}`;
 returnRecords.push(rec({scenario_id:'S05',branch_id:mode,return_id:ret,task_id:task,term_id:'TERM-001',sku_id:'SKU-011',lot_id:'SCLOT-S05',po_line_id:'MAT-RETURN-PO',requested_qty:100,accepted_qty:100,accepted_mode:mode,accepted_unit_price:9,return_fee:30,confirmation_ref:`REPLY-${suffix}`,expected_settlement_date:'2026-10-12',replacement_sku_id:mode==='exchange'?'SKU-006':null,replacement_lot_id:mode==='exchange'?'SCLOT-S05-REPLACEMENT':null,replacement_qty:mode==='exchange'?100:null,replacement_unit_cost:mode==='exchange'?9:null,credit_amount:mode==='payable_credit'?900:null,payable_id:mode==='payable_credit'?'AP-S05-001':null},'2026-10-04T10:00:00+08:00'));
 event('S05',mode,`CONFIRM-${suffix}`,'2026-10-04T10:00:00+08:00','supplier_confirmed',{task_id:task,quantity:100,accepted_mode:mode,receipt_ref:`REPLY-${suffix}`});
 event('S05',mode,`RET-SHIP-${suffix}`,'2026-10-05T09:00:00+08:00','return_shipped',{task_id:task,store_id:'ST-003',sku_id:'SKU-011',lot_id:'SCLOT-S05',quantity:100,from_state:'on_hand',to_state:'return_in_transit',receipt_ref:`RET-OUT-${suffix}`});
 event('S05',mode,`RET-ACCEPT-${suffix}`,'2026-10-05T14:00:00+08:00','supplier_accepted',{task_id:task,quantity:100,rejected_qty:0,receipt_ref:`RET-ACCEPT-DOC-${suffix}`});
 payment('S05',mode,`CASH-RET-FEE-${suffix}`,'2026-10-05T09:00:00+08:00','out',30,ret);
 if(mode==='cash_refund') {
  payment('S05',mode,'CASH-REFUND-001','2026-10-12T09:00:00+08:00','in',900,ret);
  allocations.push(rec({scenario_id:'S05',branch_id:mode,allocation_id:'MATCH-REFUND-001',cash_event_id:'CASH-REFUND-001',business_ref:ret,allocated_amount:900},'2026-10-12T09:30:00+08:00'));
 } else if(mode==='exchange') event('S05',mode,'EXCHANGE-RECEIPT','2026-10-12T09:00:00+08:00','exchange_received',{task_id:task,store_id:'ST-003',sku_id:'SKU-006',lot_id:'SCLOT-S05-REPLACEMENT',quantity:100,unit_cost:9,cash_difference:0,receipt_ref:'EXCHANGE-IN-001'});
 else {
  event('S05',mode,'CREDIT-ISSUED','2026-10-12T09:00:00+08:00','credit_issued',{task_id:task,credit_note_id:'CN-001',amount:900,supplier_id:'SUP-002',expires_at:'2026-12-31'});
  event('S05',mode,'CREDIT-APPLIED','2026-10-16T09:00:00+08:00','credit_applied',{task_id:task,credit_note_id:'CN-001',payable_id:'AP-S05-001',amount:900});
  payment('S05',mode,'CASH-S05-PAYABLE','2026-10-16T10:00:00+08:00','out',1100,'AP-S05-001');
 }
}
for(const [scenario,branch,task,channel,body] of [
 ['S05','cash_refund','TASK-S05-CASH','email','申请退回水果果冻100桶，结算方式拟为现金退款；请确认验收数量、金额及退款日期。'],
 ['S06','promotion','TASK-S06','wecom','庆春店：酸奶饼干+气泡果汁组合，10月3日至7日11元/组，10月8日至12日10元/组。'],
 ['S07','reduce_to_60','TASK-S07','feishu','海盐薯片由100件调整为60件，请李采购于16:00前确认供应商订单并回填。'],
]) {
 for(const [n,status,at] of [[1,'draft_saved','10:01'],[2,'sent','10:02']]) channelActions.push(rec({action_id:`ACTION-${task}`,action_event_id:`ACTION-${task}-${n}`,scenario_id:scenario,branch_id:branch,task_id:task,proposal_id:`PLAN-${task}`,proposal_version:1,channel,status,content_snapshot:body,target_ref:channel==='email'?'supplier2@example.invalid':channel==='wecom'?'local-group-ST004':'local-person-4',idempotency_key:`SEND-${task}`,external_write:false,receipt_ref:n===2?`LOCAL-RECEIPT-${task}`:null},`2026-10-03T${at}:00+08:00`));
}
event('S07','reduce_to_60','PURCHASE-ACCEPT','2026-10-03T15:00:00+08:00','order_confirmed',{task_id:'TASK-S07',po_line_id:'POL-S07-NEW',store_id:'ST-004',sku_id:'SKU-003',quantity:60,unit_cost:40,payment_due:'2026-10-16',receipt_ref:'SUPPLIER-ORDER-S07'});
event('S07','reduce_to_60','PURCHASE-RECEIVE','2026-10-05T12:00:00+08:00','purchase_received',{task_id:'TASK-S07',po_line_id:'POL-S07-NEW',store_id:'ST-004',sku_id:'SKU-003',lot_id:'SCLOT-S07-NEW',quantity:60,unit_cost:40,receipt_ref:'IN-S07'});
event('S07','reduce_to_60','INBOUND-RECEIVE-S07','2026-10-04T12:00:00+08:00','purchase_received',{task_id:null,po_line_id:'POL-FUT-002',shipment_line_id:'SHIP-002',store_id:'ST-004',sku_id:'SKU-003',lot_id:'LOT-INBOUND-002',quantity:30,unit_cost:40,from_state:'in_transit',to_state:'on_hand',receipt_ref:'IN-S07-EXISTING'});
for(let d=0;d<14;d++) {
 const day=date('2026-10-03',d),id=`RS-S07-${pad(d+1)}`;
 // FEFO: consume the original 120-piece lot before the later-expiring arrivals.
 const lot=d<12?'LOT-004-003':'LOT-INBOUND-002';
 replaySales.push(rec({scenario_id:'S07',branch_id:'reduce_to_60',sale_id:id,date:day,store_id:'ST-004',sku_id:'SKU-003',lot_id:lot,sold_qty:10,unit_price:60,sales_amount:600,sold_cost:400,attribution:'scenario_demand_realization',task_id:null},`${day}T20:00:00+08:00`));
 payment('S07','reduce_to_60',`CASH-${id}`,`${day}T22:00:00+08:00`,'in',600,id);
 allocations.push(rec({scenario_id:'S07',branch_id:'reduce_to_60',allocation_id:`MATCH-${id}`,cash_event_id:`CASH-${id}`,business_ref:id,allocated_amount:600},`${day}T22:10:00+08:00`));
}
payment('S07','reduce_to_60','CASH-S07-PURCHASE','2026-10-16T10:00:00+08:00','out',2400,'POL-S07-NEW');
allocations.push(rec({scenario_id:'S07',branch_id:'reduce_to_60',allocation_id:'MATCH-S07-PURCHASE',cash_event_id:'CASH-S07-PURCHASE',business_ref:'POL-S07-NEW',allocated_amount:2400},'2026-10-16T10:05:00+08:00'));
event('S06','promotion','PROMO-LIVE','2026-10-03T10:10:00+08:00','promotion_price_effective',{task_id:'TASK-S06',promotion_id:'PROMO-S06',receipt_ref:'STORE-PRICE-S06'});
for(let stage=0;stage<2;stage++) for(let d=0;d<5;d++) {
 const day=date(stage?'2026-10-08':'2026-10-03',d),price=stage?10:11,id=`RS-S06-${stage}-${d}`;
 for(const [sku,lot,unitprice,cost] of [['SKU-004','LOT-004-004',price-4,5],['SKU-008','LOT-004-008',4,3]]) replaySales.push(rec({scenario_id:'S06',branch_id:'promotion',sale_id:`${id}-${sku}`,bundle_sale_id:id,date:day,store_id:'ST-004',sku_id:sku,lot_id:lot,sold_qty:4,unit_price:unitprice,sales_amount:4*unitprice,sold_cost:4*cost,attribution:'promotion_bundle',task_id:'TASK-S06'},`${day}T20:00:00+08:00`));
 payment('S06','promotion',`CASH-${id}`,`${day}T22:00:00+08:00`,'in',4*price,id);
 for(const [sku,allocatedUnitPrice] of [['SKU-004',price-4],['SKU-008',4]]) allocations.push(rec({scenario_id:'S06',branch_id:'promotion',allocation_id:`MATCH-${id}-${sku}`,cash_event_id:`CASH-${id}`,business_ref:`${id}-${sku}`,allocated_amount:4*allocatedUnitPrice},`${day}T22:10:00+08:00`));
}
payment('S06','promotion','CASH-S06-FEE','2026-10-03T10:10:00+08:00','out',20,'PROMO-S06');
event('S06','promotion','PROMO-END','2026-10-13T00:00:00+08:00','promotion_ended',{task_id:'TASK-S06',promotion_id:'PROMO-S06',receipt_ref:'ACTIVITY-END-S06'});
const extraPayables=[rec({scenario_id:'S05',branch_id:'payable_credit',payable_id:'AP-S05-001',supplier_id:'SUP-002',po_id:'PO-S05-EXISTING',original_amount:2000,due_at:'2026-10-16',paid_amount:0,applied_credit_amount:0,outstanding_amount:2000,status:'unpaid',source_ref:'MAT-AP-S05'})];
materials.push(rec({material_id:'MAT-AP-S05',type:'payable_statement',party_id:'SUP-002',source_location:'对账单行1',text:'S05抵款独立场景：既有已验收入库订单PO-S05-EXISTING，尚欠供应商2000元，10月16日到期。',evidence_uri:'local-material://MAT-AP-S05'}));
scenarioLots.push(rec({lot_id:'SCLOT-S07-NEW',sku_id:'SKU-003',supplier_id:'SUP-003',production_date:'2026-09-01',expiry_date:'2027-02-28',po_line_id:'POL-S07-NEW',scenario_id:'S07',input_role:'future_received_batch'},'2026-10-05T12:00:00+08:00'));
event('S08','closed_target','FEEDBACK-S08','2026-10-03T10:05:00+08:00','confirmed_fact',{reported_by:'P-003',confirmed_by:'P-001',store_id:'ST-002',reason:'10月4日至24日装修闭店，期间不可收货',old_data_version:1,new_data_version:2,receipt_ref:'STORE-CLOSURE-S08'});
event('S08','closed_target','REPLAN-S08','2026-10-03T10:06:00+08:00','replan_required',{proposal_id:'PLAN-S08',old_proposal_version:1,new_proposal_version:null,reason:'待工具重新计算并由管理员确认；不预置新方案答案'});

const compatible=inventory.filter(r=>r.stock_state==='on_hand').map(r=>({sku:r.sku_id,store:stores.find(s=>s.store_id===r.store_id).store_name,store_id:r.store_id,product:products.find(p=>p.sku_id===r.sku_id).product_name,unit:products.find(p=>p.sku_id===r.sku_id).base_unit,inventory_qty:r.quantity,unit_cost:r.unit_cost,sales_30:totals.get(`${r.store_id}:${r.sku_id}`).s30,sales_90:totals.get(`${r.store_id}:${r.sku_id}`).s90,sales_cost_30:totals.get(`${r.store_id}:${r.sku_id}`).s30*r.unit_cost}));
const expectedRisk=riskInputs.map(r=>{const covered=r.sales_30>0&&r.valid_observed_days>=21?money(r.quantity/(r.sales_30/r.valid_observed_days)):null;const days=r.sellable_until?Math.round((Date.parse(r.sellable_until)-Date.parse('2026-10-03'))/86400000):null;return {scenario_id:r.scenario_id,branch_id:r.branch_id,coverage_days:covered,remaining_sellable_days:days,slow_result:covered===null?'unknown':covered>60?'risk':'normal',expiry_result:days===null?'unknown':days<=0?'unsellable':days<=21?'risk':'normal',risk_cost_once:covered>60||(days!==null&&days<=21)?r.quantity*r.unit_cost:covered===null||days===null?null:0,missing_or_check:covered===null?'sales_or_effective_observation':days===null?'sellable_until':null};});
const expectedProgress=[
 {scenario_id:'S01',branch_id:'transfer_80',as_of:'2026-10-04T12:00:00+08:00',execution_status:'completed',result_status:'pending',shipped_qty:80,received_qty:80,sold_transferred_qty:0,collected_amount:0,unmatched_amount:0,remaining_unexecuted_qty:0,attention_reason:'等待观察期结束及销售结算'},
 {scenario_id:'S09',branch_id:'partial_transfer',as_of:'2026-10-19T10:00:00+08:00',execution_status:'in_progress',result_status:'in_progress',shipped_qty:60,received_qty:60,sold_transferred_qty:40,collected_amount:3000,unmatched_amount:1000,remaining_unexecuted_qty:20,attention_reason:'20盒未发；1000元销售款未到账'},
 {scenario_id:'S05',branch_id:'exchange',as_of:'2026-10-12T10:00:00+08:00',execution_status:'completed',result_status:'completed',shipped_qty:100,received_qty:100,sold_transferred_qty:0,collected_amount:0,unmatched_amount:0,remaining_unexecuted_qty:0,attention_reason:'换入商品凭据已核对；不产生900元退款'},
];

const specs=[
 ['01_主数据与规则.xlsx',[['门店',stores],['商品',products],['供应商',suppliers],['人员',people],['门店商品',configs],['风险规则',policies]]],
 ['02_库存与90天经营事实.xlsx',[['库存快照',inventory],['商品批次',lots],['逐日销售',sales],['逐日可售状态',availability],['库存变动',movements],['历史采购',historicalOrders]]],
 ['03_需求路线采购与条款.xlsx',[['逐日需求假设',forecasts],['路线与运费',routes],['收货日历',calendar],['已确认采购',plannedOrders],['采购在途',inbound],['账户快照',accounts],['应付款',payables],['退供条款',terms],['阶段促销',promo],['组合商品',bundle],['假设说明',assumptions]]],
 ['04_场景输入与原始材料.xlsx',[['场景目录',scenarios],['独立风险输入',riskInputs],['隔离场景覆盖',overrides],['场景批次',scenarioLots],['原始材料',materials],['采购意向',intents],['抵款场景应付',extraPayables]]],
 ['05_未来执行与结算回放.xlsx',[['方案及任务',tasks],['业务回执',events],['渠道动作记录',channelActions],['批次销售',replaySales],['现金流水',cash],['核销分配',allocations],['退供确认',returnRecords]]],
 ['06_验收预期结果.xlsx',[['风险预期',expectedRisk],['进度预期',expectedProgress]]],
 ['07_当前库存导入.xlsx',[['库存导入',compatible]]],
];

// Short machine-readable provenance and schema are emitted alongside the files.
const manifest={dataset_id:'retail-v2.1',seed:SEED,decision_at:decision,snapshot_id:snap,history_start:'2026-07-05',history_end:'2026-10-02',replay_start:'2026-10-03',replay_end:'2026-11-01',complete_store_count:6,directory_store_count:50,sku_count:12,currency:'CNY',amount_unit:'yuan',ratio_unit:'percent_0_100',is_demo:true,files:[]};
const dictionaries=[];
const col = n => {let x=n+1,s='';while(x){s=String.fromCharCode(65+(x-1)%26)+s;x=Math.floor((x-1)/26);}return s;};
const typed = v => {
 if(typeof v !== 'string') return v;
 if(/^\d{4}-\d{2}-\d{2}$/.test(v)) return new Date(`${v}T00:00:00Z`);
 // Prevent spreadsheet auto-conversion from dropping the ISO timezone.
 if(/^\d{4}-\d{2}-\d{2}T/.test(v)) return "'"+v;
 return v;
};
let tableN=0;
for(const [file,sheetDefs] of specs) {
 const wb=Workbook.create();
 const fileEntry={file,role:file.startsWith('05')?'future_replay':file.startsWith('06')?'expected_answers':file.startsWith('07')?'current_import_projection':file.startsWith('04')?'isolated_scenarios':'facts_or_assumptions',sheets:[]};
 for(const [name,rows] of sheetDefs) {
  const sh=wb.worksheets.add(name),keys=[...new Set(rows.flatMap(Object.keys))],last=col(keys.length-1),end=rows.length+1;
  const vals=[keys,...rows.map(r=>keys.map(k=>typed(r[k]??null)))];
  sh.getRange(`A1:${last}${end}`).values=vals;
  sh.showGridLines=false;
  sh.getRange(`A1:${last}${end}`).format.font={name:'Arial',size:10,color:'#183C32'};
  sh.getRange(`A1:${last}${end}`).format.rowHeight=21;
  sh.getRange(`A1:${last}${end}`).format.verticalAlignment='center';
  sh.getRange(`A1:${last}1`).format.fill='#176A52';
  sh.getRange(`A1:${last}1`).format.font={bold:true,color:'#FFFFFF',name:'Arial',size:10};
  sh.getRange(`A1:${last}1`).format.rowHeight=30;
  sh.getRange(`A1:${last}1`).format.horizontalAlignment='center';
  for(let c=0;c<keys.length;c++) {
   const k=keys[c],range=sh.getRange(`${col(c)}1:${col(c)}${end}`);
   const max=Math.max(k.length,...rows.slice(0,30).map(r=>String(r[k]??'').replace(/[^\x00-\xff]/g,'xx').length));
   range.format.columnWidth=Math.min(58,Math.max(15,max+2));
   const first=rows.map(r=>r[k]).find(v=>v!==null&&v!==undefined);
   if(typeof first==='number'){sh.getRange(`${col(c)}2:${col(c)}${end}`).setNumberFormat(/amount|cost|price|balance|fee|factor/.test(k)?'#,##0.00':'0.##');sh.getRange(`${col(c)}2:${col(c)}${end}`).format.horizontalAlignment='right';}
   if(typeof first==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(first))sh.getRange(`${col(c)}2:${col(c)}${end}`).setNumberFormat('yyyy-mm-dd');
   dictionaries.push({file,sheet:name,field:k,type:typeof first==='number'?'number':typeof first==='boolean'?'boolean':typeof first==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(first)?'date':'text',nullable:rows.some(r=>r[k]===null||r[k]===undefined)});
  }
  sh.freezePanes.freezeRows(1);
  sh.freezePanes.freezeColumns(1);
  const table=sh.tables.add(`A1:${last}${end}`,true,`Data_${++tableN}`);
  table.style='TableStyleMedium4';
  table.showFilterButton=true;
  for(let c=0;c<keys.length;c++) if(['text','notes','description','completion_criteria','reason'].includes(keys[c])) {
   sh.getRange(`${col(c)}2:${col(c)}${end}`).format.wrapText=true;
   for(let r=0;r<rows.length;r++) {
    const lines=Math.ceil(String(rows[r][keys[c]]??'').replace(/[^\x00-\xff]/g,'xx').length/55);
    if(lines>1) sh.getRange(`A${r+2}:${last}${r+2}`).format.rowHeight=Math.max(32,lines*16);
   }
  }
  // Small neutral alternating bands, with consistent custom header colors.
  sh.tabColor=fileEntry.role==='expected_answers'?'#AC7B34':'#176A52';
  fileEntry.sheets.push({name,row_count:rows.length,columns:keys});
 }
 if(file.startsWith('06')) {
  const sh=wb.worksheets.add('金额复算');
  const matrix=[['场景','指标','输入1','输入2','输入3','结果','口径'],
   ['S01','已调拨批次销售回款',64,100,null,null,'64盒×100元；仅已匹配现金'],
   ['S01','已售成本',64,80,null,null,'不能与回款累加为收益'],
   ['S01','商品毛利',null,null,null,null,'收入减已售成本'],
   ['S01','扣运费贡献',24,null,null,null,'未扣房租人工；不是增量利润'],
   ['S01','原批次剩余库存成本',40,16,80,null,'原店40+目标店16；排除目标店原有批次'],
   ['S01','所列回放流水净额',1000,null,null,null,'含原有批次回款1000；不含其他采购等背景流水'],
   ['S07','评估期需求',10,14,null,null,'10月3日至16日；到货日须逐日复算'],
   ['S07','建议采购数量',120,30,70,null,'需求+期末安全量-现货-已确认在途；步长10'],
   ['S07','原意向付款',100,40,null,null,'原意向尚未下单；作为冻结比较基线'],
   ['S07','调整后付款',40,null,null,null,'需实际订单确认及付款回执'],
   ['S07','预计少付采购款',null,null,null,null,'同周期计划差额；不是销售收入'],
   ['S05退款','实际净现金',900,30,null,null,'退款到账900减运费30'],
   ['S05抵款','使用信用后付款',2000,900,null,null,'额度不算现金收入；仍需支付1100'],
   ['S06','两阶段销售收入',20,11,10,null,'每阶段20组；活动总销量含正常销售'],
   ['S06','组合已售成本',40,8,null,null,'每组饼干5+果汁3'],
   ['S06','扣活动费用贡献',20,null,null,null,'假设回放不证明因果增益'],
  ];
  sh.getRange('A1:G17').values=matrix;
  const formulas=['=C2*D2','=C3*D3','=F2-F3','=F4-C5','=(C6+D6)*E6','=F2-C5+C7','=C8*D8','=MAX(0,F8+E9-C9-D9)','=C10*D10','=F9*C11','=F10-F11','=C13-D13','=C14-D14','=C15*D15+C15*E15','=C16*D16','=F15-F16-C17'];
  sh.getRange('F2:F17').formulas=formulas.map(f=>[f]);
  sh.showGridLines=false;sh.getRange('A1:G17').format.font={name:'Arial',size:11,color:'#183C32'};sh.getRange('A1:G17').format.rowHeight=28;sh.getRange('A1:G1').format.fill='#176A52';sh.getRange('A1:G1').format.font={bold:true,color:'#FFFFFF'};sh.getRange('A1:A17').format.columnWidth=14;sh.getRange('B1:B17').format.columnWidth=27;sh.getRange('C1:F17').format.columnWidth=15;sh.getRange('G1:G17').format.columnWidth=64;sh.getRange('F2:F17').setNumberFormat('#,##0.00');sh.getRange('C2:E17').format.font={color:'#245FA4'};sh.freezePanes.freezeRows(1);
  fileEntry.sheets.push({name:'金额复算',row_count:16,columns:matrix[0]});
 }
 wb.recalculate();
 console.log(JSON.stringify({file,inspect:(await wb.inspect({kind:'sheet',include:'id,name',maxChars:1500})).ndjson}));
 const output=await SpreadsheetFile.exportXlsx(wb);await output.save(path.join(out,file));
 // The artifact runtime coerces raw ISO text into timezone-less Excel numbers;
 // remove only the literal-text escape marker in the exported string cells.
 execFileSync('/Users/lanyangyang/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3',[fileURLToPath(new URL('./preserve-iso-text.py',import.meta.url)),path.join(out,file)]);
 for(const s of fileEntry.sheets) {
  try {const preview=await wb.render({sheetName:s.name,range:`A1:${col(Math.min(s.columns.length,5)-1)}${Math.min(s.row_count+1,6)}`,scale:1,format:'png'});await fs.writeFile(path.join(previews,`${file.slice(0,2)}-${s.name}.png`),new Uint8Array(await preview.arrayBuffer()));}
  catch(e){console.log(`PREVIEW ${file}/${s.name}: ${e.message}`);}
 }
 const bytes=await fs.readFile(path.join(out,file));fileEntry.sha256=crypto.createHash('sha256').update(bytes).digest('hex');fileEntry.bytes=bytes.length;
 await fs.rename(path.join(out,file+'.inspect.ndjson'),path.join(previews,file+'.inspect.ndjson')).catch(()=>{});
 manifest.files.push(fileEntry);
 console.log(JSON.stringify({exported:file,bytes:bytes.length,sheets:fileEntry.sheets.length}));
}
await fs.writeFile(path.join(root,'manifest.json'),JSON.stringify(manifest,null,2)+'\n');
await fs.writeFile(path.join(root,'data_dictionary.json'),JSON.stringify(dictionaries,null,2)+'\n');
await fs.mkdir(path.join(root,'generator'),{recursive:true});
await fs.copyFile(new URL(import.meta.url),path.join(root,'generator','build-data.mjs'));
await fs.copyFile(new URL('./preserve-iso-text.py',import.meta.url),path.join(root,'generator','preserve-iso-text.py'));
console.log(JSON.stringify({output:out,files:manifest.files.length,sales:sales.length,availability:availability.length,movements:movements.length,forecasts:forecasts.length}));

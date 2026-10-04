/* Retail workbenches keep every approval tied to the latest validated inputs. */
(() => {
  'use strict';
  const ui = new Map();
  const labels = { transfer: '调拨', 'expiry-rescue': '处置', 'procurement-brake': '采购调整' };
  const actionNames = { reduce: '减少采购量', cancel: '取消未执行量', delay_arrival: '协商延期到货', delay_payment: '协商延期付款' };
  const icon = (name) => `<span class="material-symbols-rounded" aria-hidden="true">${name}</span>`;
  const number = (value) => value == null || value === '' ? '—' : Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 1 });
  const getUI = (route) => { if (!ui.has(route)) ui.set(route, { busy: false, dirty: false, error: '', notice: '', editing: false }); return ui.get(route); };
  const escape = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const input = (title, name, value, options = '') => `<label class="retail-wb-field"><span>${title}</span><input name="${name}" value="${escape(value)}" ${options || 'type="number" min="0" step="1"'}></label>`;
  const qty = (value) => `${number(value)} <small>件</small>`;
  const productVisual = (name, fallback) => {
    const file = /坚果|礼盒/.test(name || '') ? 'retail-nuts.png' : /饼|曲奇/.test(name || '') ? 'retail-cookies.png' : /气泡|饮料|水|茶|汁/.test(name || '') ? 'retail-drink.png' : null;
    return file ? `<img src="assets/${file}" alt="${escape(name)}示意">` : icon(fallback);
  };
  const currentProposal = (data) => {
    const saved = data.proposal?.version?.payload?.input;
    if (!saved) return null;
    return Object.keys({ ...saved, ...data.input }).every((key) => String(saved[key] ?? '') === String(data.input?.[key] ?? '')) ? data.proposal : null;
  };
  const statusText = (data, view) => view.dirty ? '参数已修改，需重新计算' : currentProposal(data)?.status === 'pending_approval' ? '已提交 · 等待审批' : currentProposal(data)?.status === 'approved' ? '已审批 · 待生成任务' : currentProposal(data)?.status === 'execution_task_created' ? '已生成任务 · 查看执行进度' : data.calculation?.valid ? '测算有效 · 待确认' : '请调整方案';
  function toolbar(data, route, view) {
    const e = escape;
    const entries = route === 'expiry-rescue' ? (data.expiry_queue || []).map((item) => ({ id: item.risk?.id, product: item.input?.product, store: item.input?.store })) : data.items || [];
    const targetLabel = route === 'expiry-rescue' ? '当前处理批次' : route === 'transfer' ? '当前评估商品' : '当前采购商品';
    const countLabel = route === 'expiry-rescue' ? `${entries.length} 个待处理批次` : `${entries.length} 项待评估建议`;
    return `<div class="retail-wb-toolbar"><div class="retail-wb-selection"><div class="retail-wb-selection-heading"><span>${targetLabel}</span><small>${countLabel}</small></div><label class="retail-wb-picker">${icon(route === 'expiry-rescue' ? 'inventory_2' : 'category')}<span class="retail-wb-sr">${route === 'expiry-rescue' ? '选择商品批次' : '选择商品与门店'}</span><select data-retail-wb-risk ${view.busy ? 'disabled' : ''}>${entries.map((item) => `<option value="${e(item.id)}" ${Number(item.id) === Number(data.risk?.id) ? 'selected' : ''}>${e(item.product)} · ${e(item.store)}</option>`).join('')}</select></label></div><span class="retail-wb-status ${view.dirty ? 'is-dirty' : !data.calculation?.valid ? 'is-warning' : ''}" data-retail-wb-status>${statusText(data, view)}</span></div>`;
  }
  function notice(data, view) {
    const errors = view.error || (!data.calculation?.valid && (data.calculation?.errors || []).join('；'));
    return `<div class="retail-wb-notice ${errors ? 'is-error' : view.dirty ? 'is-dirty' : ''}" data-retail-wb-notice ${errors || view.notice || view.dirty ? '' : 'hidden'} role="status">${escape(errors || (view.dirty ? '参数已修改，当前展示的是上次测算；重新计算后才能保存或提交。' : view.notice))}</div>`;
  }
  function actions(data, route, view, money) {
    const submitted = currentProposal(data)?.status === 'pending_approval';
    const disabled = view.busy || view.dirty || !data.calculation?.valid || submitted;
    return `<div class="retail-wb-actions"><button type="button" class="retail-wb-primary" data-retail-wb-submit ${disabled ? 'disabled' : ''}>${view.busy ? '正在处理…' : submitted ? '已提交，等待审批' : `提交${labels[route]}审批`}${icon(submitted ? 'check' : 'arrow_forward')}</button><button type="button" class="retail-wb-link" data-retail-wb-edit ${view.busy ? 'disabled' : ''}>调整方案</button></div>`;
  }
  function editor(data, route, view, fields, note = '') {
    return `<details class="retail-wb-details retail-wb-editor" ${view.editing ? 'open' : ''}><summary>${icon('tune')}调整参数与重新计算${icon('expand_more')}</summary><form data-retail-wb-form><fieldset ${view.busy ? 'disabled' : ''}><div class="retail-wb-fields">${fields}</div>${note ? `<p class="retail-wb-quiet">${note}</p>` : ''}<div class="retail-wb-editor-actions"><button type="submit" class="retail-wb-primary">重新计算${icon('refresh')}</button><button type="button" class="retail-wb-secondary" data-retail-wb-save ${view.dirty || !data.calculation?.valid || currentProposal(data)?.status === 'pending_approval' ? 'disabled' : ''}>保存方案草稿</button></div></fieldset></form></details>`;
  }
  function stockChange(label, name, info, fallback) {
    return `<div class="retail-wb-stock-row"><div><span>${label}</span><strong>${escape(name)}</strong></div><div><p>${number(info.on_hand_before ?? fallback)} ${icon('arrow_right_alt')} <b>${number(info.on_hand_after)}</b><small>件</small></p><span>库存覆盖 ${number(info.coverage_before)} → ${number(info.coverage_after)} 天</span></div></div>`;
  }
  function pageHeader(title, subtitle, aside = '') {
    const back = window.RetailApp?.backTarget?.() || { route: 'overview', label: '返回经营总览' };
    return `<header class="retail-wb-page-header"><div><div class="retail-wb-heading-line"><h1>${escape(title)}</h1>${aside ? `<span class="retail-wb-scope">${escape(aside)}</span>` : ''}</div><p>${escape(subtitle)}</p></div><a class="retail-wb-page-back" href="#${escape(back.route)}">${icon('arrow_back')}${escape(back.label)}</a></header>`;
  }
  function transfer(data, view, money) {
    const i = data.input || {}, c = data.calculation || {}, source = c.before_after?.source || {}, target = c.before_after?.target || {};
    const network = (data.transfer_network || []).filter((item) => item.store_id !== i.source_store_id);
    const selected = network.find((item) => item.store_id === i.target_store_id);
    const recommended = network.filter((item) => item.calculation?.valid).slice(0, 3);
    const shown = recommended.length ? [...recommended] : network.slice(0, 3);
    if (selected && !shown.some((item) => item.store_id === selected.store_id)) shown.push(selected);
    const points = [[75, 25], [51, 20], [79, 63], [52, 57]];
    const markers = shown.map((item, index) => ({ ...item, x: points[index][0], y: points[index][1] }));
    const selectedPoint = markers.find((item) => item.store_id === i.target_store_id) || { x: 75, y: 25 };
    const limit = c.limits || {};
    return `<div class="retail-wb retail-wb-transfer">${pageHeader('跨店调拨', '看清门店位置，让每次调拨都有依据', '杭州 · 同城门店')}${toolbar(data, 'transfer', view)}${notice(data, view)}<div class="retail-wb-transfer-grid"><div class="retail-wb-map-column"><section class="retail-wb-map" aria-label="调拨门店和路线示意"><img src="assets/today-transfer-route-map.png" alt="杭州同城配送路线示意底图" class="retail-wb-map-image"><canvas data-retail-wb-route data-target-x="${selectedPoint.x}" data-target-y="${selectedPoint.y}" aria-hidden="true"></canvas><span class="retail-wb-map-count">${icon('storefront')}${recommended.length} 家优先可接收门店</span><div class="retail-wb-map-source">${icon('location_on')}<span><b>${escape(i.source_store)} · 调出</b><small>库存 ${number(i.source_on_hand)} 件 · 日销 ${number(i.source_daily_sales)} 件</small></span></div>${markers.map((item) => `<button type="button" class="retail-wb-map-marker ${item.x > 65 ? 'is-east' : ''} ${item.store_id === i.target_store_id ? 'is-selected' : ''}" style="left:${item.x}%;top:${item.y}%" data-retail-wb-target="${escape(item.store_id)}" ${view.busy ? 'disabled' : ''} aria-label="选择 ${escape(item.name)} 为调入门店" aria-pressed="${item.store_id === i.target_store_id}">${icon('location_on')}<span><b>${escape(item.name)}${item.store_id === i.target_store_id ? ' · 调入' : ''}</b><small>库存 ${number(item.on_hand)} 件 · 日销 ${number(item.daily_sales)} 件</small></span></button>`).join('')}<div class="retail-wb-map-caption"><span>门店位置与路线：示意 · 估算</span><strong>${selected ? `${number(selected.distance_km)} 公里 · 约 ${number(selected.travel_minutes)} 分钟` : `预计 ${number(i.eta_days)} 天到店`}</strong></div></section><div class="retail-wb-candidate-title"><h3>优先接收门店</h3><label class="retail-wb-sr" for="retail-wb-target-picker">所有候选门店</label><select id="retail-wb-target-picker" data-retail-wb-target-picker ${view.busy ? 'disabled' : ''}><option value="">查看其他 ${network.length} 家门店</option>${network.map((item) => `<option value="${escape(item.store_id)}" ${item.store_id === i.target_store_id ? 'selected' : ''}>${escape(item.name)} · 可接收 ${Math.max(0, Number(item.capacity) - Number(item.on_hand))} 件</option>`).join('')}</select></div><div class="retail-wb-candidates">${shown.map((item) => `<button type="button" class="retail-wb-candidate ${item.store_id === i.target_store_id ? 'is-selected' : ''}" data-retail-wb-target="${escape(item.store_id)}" ${view.busy ? 'disabled' : ''} aria-pressed="${item.store_id === i.target_store_id}">${icon('storefront')}<span><b>${escape(item.name)}</b><small>可接收 ${number(Math.max(0, Number(item.capacity) - Number(item.on_hand)))} 件</small><small>${number(item.distance_km)} km · 运费 ${money(item.transport_fee)}</small></span>${icon(item.store_id === i.target_store_id ? 'check_circle' : 'chevron_right')}</button>`).join('')}</div></div><section class="retail-wb-transfer-plan"><div class="retail-wb-plan-heading"><h3>当前调拨方案</h3><span class="retail-wb-pill">${c.valid ? '待确认' : '待调整'}</span></div><p class="retail-wb-route-name">${escape(i.source_store)} ${icon('arrow_forward')} ${escape(i.target_store)}</p><div class="retail-wb-transfer-quantity"><strong>${number(i.quantity)}<small>件</small></strong><span>计划调拨<br><small>调入后预计覆盖 ${number(target.coverage_after)} 天</small></span></div>${stockChange('调出', i.source_store, source, i.source_on_hand)}${stockChange('调入', i.target_store, target, i.target_on_hand)}<div class="retail-wb-plan-money"><div><span>调拨库存成本</span><b>${money(c.cash?.inventory_cost)}</b></div><div><span>预计运费</span><b>${money(i.transport_fee)}</b></div></div>${Number(source.coverage_after) > 60 ? `<p class="retail-wb-warning">${icon('info')}调出店仍有较长库存覆盖，可继续比较其他接收门店。</p>` : ''}${actions(data, 'transfer', view, money)}<p class="retail-wb-footnote">${icon('info')}调拨改变库存位置，售出后才形成回款。</p></section></div>${editor(data, 'transfer', view, input('本次调拨数量（件）', 'quantity', i.quantity, `type="number" min="1" max="${Math.min(Number(limit.available_to_transfer || 0), Number(limit.receiving_capacity || 0))}" step="1" required`), `调出店最多可调 ${number(limit.available_to_transfer)} 件；接收店最多可接收 ${number(limit.receiving_capacity)} 件。切换门店后自动重新测算。`)}<details class="retail-wb-details"><summary>${icon('fact_check')}查看计算依据与运输条件${icon('expand_more')}</summary><div class="retail-wb-evidence-grid"><p>调出安全库存<strong>${number(i.source_safety)} 件</strong></p><p>调入安全库存<strong>${number(i.target_safety)} 件</strong></p><p>本批次可售时间<strong>${number(i.sellable_days)} 天</strong></p><p>预计配送时间<strong>${number(i.eta_days)} 天</strong></p><p>预计可消化<strong>${number(c.economic?.target_sale_before_expiry_qty)} 件</strong></p><p>预计避免报损<strong>${money(c.economic?.avoided_loss)}</strong></p></div><p class="retail-wb-footnote">按当前销量与可售天数估算，未计入未来销量变化；避免报损不等于已实现利润或现金回款。</p></details></div>`;
  }
  function expiry(data, view, money) {
    const i = data.input || {}, c = data.calculation || {}, f = c.forecast || {};
    const inventory = Number(i.inventory_qty || 0), normal = Number(f.normal_sale_qty || 0), baselineRemaining = Math.max(0, inventory - normal);
    const allocated = Number(i.transfer_qty || 0) + Number(i.promo_qty || 0) + Number(i.return_qty || 0);
    const normalWidth = inventory ? Math.min(100, normal / inventory * 100) : 0;
    return `<div class="retail-wb retail-wb-expiry">${pageHeader('近效期处理', '先看可售时间，再决定调拨、促销或退供')}${toolbar(data, 'expiry-rescue', view)}${notice(data, view)}<section class="retail-wb-expiry-card"><div class="retail-wb-product-label"><div class="retail-wb-product-icon">${productVisual(i.product, 'bakery_dining')}</div><div><h2>${escape(i.product)}</h2><p>${escape(i.store)} · 批次 ${escape(i.lot_id || i.batch)}</p></div><div class="retail-wb-expiry-days">${icon('schedule')}<div><span>剩余可售</span><strong>${number(i.sellable_days)}<small>天</small></strong></div></div></div><div class="retail-wb-expiry-stock"><div><strong>当前库存 ${qty(inventory)}</strong><span>最晚处置 ${escape(i.latest_disposal_date)}</span></div><div class="retail-wb-inventory-bar" role="img" aria-label="按当前销量，正常预计销售 ${normal} 件，预计剩余 ${baselineRemaining} 件"><span style="width:${normalWidth}%">${normalWidth > 12 ? `${number(normal)} 件` : ''}</span><span style="width:${100 - normalWidth}%">${100 - normalWidth > 12 ? `${number(baselineRemaining)} 件` : ''}</span></div><div class="retail-wb-bar-legend"><span><i></i>预计正常售出 ${number(normal)} 件</span><span><i></i>未采取处置时预计剩余 ${number(baselineRemaining)} 件</span></div><div class="retail-wb-expiry-cost"><span>预计剩余库存成本</span><strong>${money(baselineRemaining * Number(i.unit_cost || 0))}</strong><small>按 ${money(i.unit_cost)} / 件计算</small></div></div></section><section class="retail-wb-expiry-suggestion"><div class="retail-wb-plan-heading"><div><h3>分配这批货的处置方案</h3><p>将正常销售与额外处置分开计算，避免重复分配。</p></div><span class="retail-wb-pill">${allocated} 件待确认处置</span></div><div class="retail-wb-dispositions"><div>${icon('swap_horiz')}<span>跨店调拨</span><strong>${qty(i.transfer_qty)}</strong><small>运费 ${money(i.transfer_fee)}</small></div><div>${icon('sell')}<span>促销投放</span><strong>${qty(i.promo_qty)}</strong><small>试算价 ${money(i.promo_price)} / 件</small></div><div>${icon('assignment_return')}<span>协商退供</span><strong>${qty(i.return_qty)}</strong><small>待供应商确认条款</small></div></div><div class="retail-wb-expiry-result"><span>按当前分配仍待处理 <b>${number(f.expected_remaining_qty)} 件</b></span><span>对应库存成本 <b>${money(Number(f.expected_remaining_qty || 0) * Number(i.unit_cost || 0))}</b></span></div>${actions(data, 'expiry-rescue', view, money)}<p class="retail-wb-footnote">促销投放与调拨不代表已售出；未接入销量弹性和退供条款，回款金额暂不估算。</p></section>${editor(data, 'expiry-rescue', view, [input('调拨数量（件）', 'transfer_qty', i.transfer_qty), input('促销投放数量（件）', 'promo_qty', i.promo_qty), input('审核促销价（元 / 件）', 'promo_price', i.promo_price, 'type="number" min="0" step="0.01"'), input('退供数量（件）', 'return_qty', i.return_qty)].join(''), `正常预计销售 ${number(normal)} 件，加上调拨、促销、退供后不得超过库存 ${number(inventory)} 件。`)}<details class="retail-wb-details"><summary>${icon('fact_check')}查看批次、销售与成本依据${icon('expand_more')}</summary><div class="retail-wb-evidence-grid"><p>本批次库存<strong>${number(inventory)} 件</strong></p><p>近 30 天销量<strong>${number(i.sales_30)} 件</strong></p><p>预计正常销售<strong>${number(normal)} 件</strong></p><p>库存总成本<strong>${money(c.cash?.inventory_cost)}</strong></p><p>促销费用预算<strong>${money(i.promo_fee)}</strong></p><p>批次参考日期<strong>${escape(i.batch)}</strong></p></div><p class="retail-wb-footnote">正常可售量 = 剩余可售天数 × 近 30 天日均销量，且不超过当前库存。调拨、促销与退供数量是待审批的方案分配。</p></details></div>`;
  }
  function procurement(data, view, money) {
    const i = data.input || {}, c = data.calculation || {}, inv = c.inventory_position || {}, payment = c.payment || {}, cash = c.cash || {};
    const reducing = ['reduce', 'cancel'].includes(i.action), delayingPayment = i.action === 'delay_payment';
    const open = Number(i.open_purchase_qty || 0), remaining = inv.remaining_purchase_qty, cost = Number(i.unit_cost || 0);
    const baselineMoney = open * cost, scenarioMoney = Number(remaining ?? open) * cost;
    const fields = `<label class="retail-wb-field"><span>调整方式</span><select name="action">${Object.entries(actionNames).map(([value, label]) => `<option value="${value}" ${value === i.action ? 'selected' : ''}>${label}</option>`).join('')}</select></label>${input('调整数量（件）', 'adjustment_qty', i.adjustment_qty, `type="number" min="1" max="${open}" step="1" required`)}${input('协商的新付款日', 'new_payment_date', i.new_payment_date, 'type="date"')}`;
    return `<div class="retail-wb retail-wb-procurement">${pageHeader('采购刹车', '先算少买多少，再核对缺货风险和付款压力')}${toolbar(data, 'procurement-brake', view)}${notice(data, view)}<div class="retail-wb-purchase-product"><div class="retail-wb-product-icon">${productVisual(i.product, 'local_drink')}</div><div><h2>${escape(i.product)}</h2><p>采购单 ${escape(i.po_number)} · 第 ${escape(i.line_number)} 行 · ${escape(i.order_status)} · 单价 ${money(i.unit_cost)} / 件</p></div><span class="retail-wb-pill">${escape(actionNames[i.action] || '调整采购')}</span></div><section class="retail-wb-purchase-comparison"><div class="retail-wb-purchase-before"><span>原计划采购</span><strong>${qty(open)}</strong><div><span>订单采购金额</span><b>${money(baselineMoney)}</b><small>原付款日 ${escape(i.payment_date)}</small></div></div>${icon('arrow_forward')}<div class="retail-wb-purchase-after"><span>${reducing ? '建议保留采购' : '调整后采购量'}</span><strong>${qty(remaining)}</strong><div><span>订单采购金额</span><b>${money(scenarioMoney)}</b><small>${delayingPayment ? `协商付款日 ${escape(payment.scenario_payment_date)}` : `计划到货 ${escape(i.arrival_date)}`}</small></div></div></section><div class="retail-wb-purchase-impact"><p>${reducing ? '订单采购金额减少' : delayingPayment ? '观察期内推迟付款' : '当前方案不减少采购金额'}<strong>${money(reducing ? baselineMoney - scenarioMoney : delayingPayment ? cash.known_cash_effect : 0)}</strong></p><span>${reducing ? `减少 ${number(i.adjustment_qty)} 件，需供应商确认后执行` : delayingPayment ? `后续仍需支付 ${money(payment.deferred_payment_pressure ?? 0)}，不是采购节省` : '延期到货需另行协商到货日，付款安排按原计划计算'}</span></div><section class="retail-wb-purchase-stock"><div><span>当前库存</span><b>${qty(i.current_inventory)}</b></div><span>＋</span><div><span>已确认在途</span><b>${qty(i.in_transit_qty)}</b></div><span>＋</span><div><span>保留采购</span><b>${qty(remaining)}</b></div><span>＝</span><div><span>预计库存位</span><b>${qty(inv.projected_after_adjustment)}</b></div><p class="${c.valid ? 'retail-wb-ok' : 'retail-wb-warning'}">${icon(c.valid ? 'check_circle' : 'error')}安全库存 ${number(inv.safety_stock)} 件</p></section>${actions(data, 'procurement-brake', view, money)}${editor(data, 'procurement-brake', view, fields, '仅调整未执行采购量；减量后保留安全库存。延期付款单独计算后续付款压力。')}<details class="retail-wb-details"><summary>${icon('fact_check')}查看采购规则与付款影响${icon('expand_more')}</summary><div class="retail-wb-evidence-grid"><p>调整方式<strong>${escape(actionNames[i.action] || i.action)}</strong></p><p>观察期截止<strong>${escape(i.cutoff_date)}</strong></p><p>原付款日<strong>${escape(payment.baseline_payment_date)}</strong></p><p>调整后付款日<strong>${escape(payment.scenario_payment_date)}</strong></p><p>观察期内少支出<strong>${money(reducing ? cash.known_cash_effect : 0)}</strong></p><p>观察期内推迟付款<strong>${money(delayingPayment ? cash.known_cash_effect : 0)}</strong></p></div><p class="retail-wb-footnote">库存位包含未来到货，不代表当前可售现货。观察期内少支出与延期付款分别计算；合同最小起订量、取消费及供应商确认仍需人工核查。</p></details><p class="retail-wb-footnote">建议通过审批后执行，预计少支出不等于已回款。</p></div>`;
  }
  function render(route, data, ctx) {
    const view = getUI(route);
    const riskId = data.risk?.id;
    if (view.riskId !== riskId) Object.assign(view, { riskId, dirty: false, error: '', notice: '', editing: false });
    const money = (value) => value == null || value === '' ? '待确认' : ctx.money(value);
    return route === 'transfer' ? transfer(data, view, money) : route === 'expiry-rescue' ? expiry(data, view, money) : procurement(data, view, money);
  }
  function formValues(form) {
    const values = {};
    new FormData(form).forEach((value, key) => {
      const control = Array.from(form.elements || []).find((element) => element.name === key);
      const numericValue = control?.type === 'number' && value !== '' ? control.valueAsNumber : null;
      values[key] = Number.isFinite(numericValue) ? numericValue : value;
    });
    return values;
  }
  function readInput(route, target, ctx) {
    const base = ctx.state.workbenches[route]?.input || {}, form = target.querySelector('[data-retail-wb-form]');
    if (form && !form.reportValidity()) return null;
    const next = { ...base };
    if (form) Object.assign(next, formValues(form));
    return next;
  }
  function setDirty(route, target, ctx) {
    const view = getUI(route);
    view.dirty = true; view.error = ''; view.notice = '';
    const form = target.querySelector('[data-retail-wb-form]');
    if (form) Object.assign(ctx.state.workbenches[route].input, formValues(form));
    const status = target.querySelector('[data-retail-wb-status]');
    if (status) { status.textContent = '参数已修改，需重新计算'; status.classList.remove('is-warning'); status.classList.add('is-dirty'); }
    const alert = target.querySelector('[data-retail-wb-notice]');
    if (alert) { alert.hidden = false; alert.className = 'retail-wb-notice is-dirty'; alert.textContent = '参数已修改，当前展示的是上次测算；重新计算后才能保存或提交。'; }
    target.querySelectorAll('[data-retail-wb-submit], [data-retail-wb-save]').forEach((button) => { button.disabled = true; });
  }
  async function calculate(route, next, ctx) {
    const result = await ctx.api(`/workbenches/${route}/calculate`, { method: 'POST', body: JSON.stringify({ input: next }) });
    ctx.state.workbenches[route] = { ...ctx.state.workbenches[route], input: result.input, calculation: result.calculation, draft: result.draft };
    return result;
  }
  async function perform(route, target, ctx, operation, overrides = null) {
    const view = getUI(route);
    if (view.busy) return;
    const current = readInput(route, target, ctx);
    if (!current) return;
    const next = { ...current, ...(overrides || {}) };
    view.busy = true; view.dirty = true; view.error = ''; view.notice = '';
    // Preserve draft fields while controls are disabled and the latest input is calculated.
    ctx.state.workbenches[route].input = next;
    ctx.renderWorkbench(route);
    try {
      const result = await calculate(route, next, ctx);
      view.dirty = false;
      if (!result.calculation?.valid) { view.editing = true; throw new Error((result.calculation?.errors || ['方案未通过约束校验']).join('；')); }
      if (operation === 'calculate') {
        view.notice = '测算已更新，约束校验通过。';
        return;
      }
      const saved = await ctx.api(`/workbenches/${route}/save`, { method: 'POST', body: JSON.stringify({ input: result.input }) });
      if (!saved.calculation?.valid || !saved.proposal?.id) throw new Error('方案未成功保存，请重新计算后再试。');
      ctx.state.workbenches[route] = { ...ctx.state.workbenches[route], calculation: saved.calculation, proposal: saved.proposal, draft: { ...result.draft, status: 'saved' } };
      if (operation === 'submit') {
        const proposal = await ctx.api(`/proposals/${encodeURIComponent(saved.proposal.id)}/submit`, { method: 'POST' });
        ctx.state.workbenches[route].proposal = proposal;
        view.notice = '已提交负责人审批；审批通过后再执行。';
      } else view.notice = '方案草稿已保存，可继续提交审批。';
      await ctx.refreshCommonRecords();
      ctx.showToast(view.notice);
    } catch (error) {
      view.error = error.message || '操作失败，请重试';
      ctx.showToast(view.error, 'error');
    } finally {
      view.busy = false;
      ctx.renderWorkbench(route);
    }
  }
  function drawMap(target) {
    const canvas = target.querySelector('[data-retail-wb-route]');
    if (!canvas) return;
    const width = canvas.clientWidth, height = canvas.clientHeight;
    if (!width || !height) return;
    const scale = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = width * scale; canvas.height = height * scale;
    const drawing = canvas.getContext('2d');
    if (!drawing) return;
    drawing.scale(scale, scale);
    const sx = width * .23, sy = height * .7, tx = width * Number(canvas.dataset.targetX) / 100, ty = height * Number(canvas.dataset.targetY) / 100;
    const path = () => { drawing.beginPath(); drawing.moveTo(sx, sy); drawing.bezierCurveTo(width * .45, height * .83, width * .50, height * .18, tx, ty); };
    path(); drawing.strokeStyle = 'rgba(255,255,255,.96)'; drawing.lineWidth = 9; drawing.stroke();
    path(); drawing.strokeStyle = getComputedStyle(document.body).getPropertyValue('--retail-accent').trim() || '#116349'; drawing.lineWidth = 4; drawing.setLineDash([10, 5]); drawing.stroke();
  }
  function bind(route, target, ctx) {
    const view = getUI(route);
    target.querySelector('[data-retail-wb-form]')?.addEventListener('submit', (event) => { event.preventDefault(); perform(route, target, ctx, 'calculate'); });
    target.querySelector('[data-retail-wb-form]')?.addEventListener('input', () => setDirty(route, target, ctx));
    target.querySelector('[data-retail-wb-form]')?.addEventListener('change', () => setDirty(route, target, ctx));
    target.querySelector('.retail-wb-editor')?.addEventListener('toggle', (event) => { view.editing = event.currentTarget.open; });
    target.querySelector('[data-retail-wb-edit]')?.addEventListener('click', () => { const editor = target.querySelector('.retail-wb-editor'); if (editor) { editor.open = true; editor.scrollIntoView({ block: 'nearest', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' }); editor.querySelector('input,select')?.focus({ preventScroll: true }); } });
    target.querySelector('[data-retail-wb-save]')?.addEventListener('click', () => perform(route, target, ctx, 'save'));
    target.querySelector('[data-retail-wb-submit]')?.addEventListener('click', () => perform(route, target, ctx, 'submit'));
    target.querySelector('[data-retail-wb-risk]')?.addEventListener('change', async (event) => {
      if (view.busy) return;
      view.busy = true; view.dirty = false; view.error = ''; view.notice = '';
      try { await ctx.loadWorkbench(route, event.target.value); }
      finally { view.busy = false; ctx.renderWorkbench(route); }
    });
    const selectTarget = (storeId) => {
      const data = ctx.state.workbenches[route], candidate = (data?.transfer_network || []).find((item) => item.store_id === storeId);
      if (!candidate || view.busy) return;
      perform(route, target, ctx, 'calculate', { target_store: candidate.name, target_store_id: candidate.store_id, target_on_hand: candidate.on_hand, target_capacity: candidate.capacity, target_safety: candidate.safety_stock, target_daily_sales: candidate.daily_sales, transport_fee: candidate.transport_fee, eta_days: candidate.eta_days });
    };
    target.querySelectorAll('[data-retail-wb-target]').forEach((button) => button.addEventListener('click', () => selectTarget(button.dataset.retailWbTarget)));
    target.querySelector('[data-retail-wb-target-picker]')?.addEventListener('change', (event) => selectTarget(event.target.value));
    if (route === 'transfer') {
      requestAnimationFrame(() => drawMap(target));
      const map = target.querySelector('.retail-wb-map');
      if (map && typeof ResizeObserver !== 'undefined') {
        if (view.observer) view.observer.disconnect();
        view.observer = new ResizeObserver(() => drawMap(target));
        view.observer.observe(map);
      }
    }
  }
  window.RetailWorkbenches = { render, bind };
})();

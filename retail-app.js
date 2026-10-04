/* Retail presentation layer. All business amounts come from the API. */
window.RetailApp = (() => {
  let ctx, overview = null, overviewError = '', overviewLoading = false, requestVersion = 0;
  let stores = [], period = 7, storeId = 'all', showAllStores = false;
  let storeSort = 'risk_cost', storeSortDesc = true, storeRiskFilterOpen = false;
  const selectedStoreRisks = new Set();
  let diagnosis = { selectedId: null, detail: null, loading: false, error: '', requestVersion: 0 };
  let todayTab = 'pending', todayLimit = 3, todaySelectedKey = null, dialogTrigger = null;
  let workbenchReturn = null, plannedRoute = null;
  const $ = (s, r = document) => r.querySelector(s);
  const e = (s) => ctx.escapeHtml(s);
  const icon = (name) => `<span class="material-symbols-rounded" aria-hidden="true">${name}</span>`;
  const currency = (n) => n == null ? '—' : ctx.money(n);
  const compact = (n) => n == null ? '—' : Math.abs(Number(n)) >= 10000 ? `¥${(Number(n) / 10000).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}万` : currency(n);
  const pct = (n) => n == null ? '—' : `${Number(n).toFixed(1)}%`;
  const photo = (p) => /坚果|腰果/.test(p) ? 'assets/retail-nuts.png' : /果汁|乌龙|牛奶/.test(p) ? 'assets/retail-drink.png' : 'assets/retail-cookies.png';
  const amount = (r) => Number(r.inventory_value ?? Number(r.inventory_qty || 0) * Number(r.unit_cost || 0));
  const coverage = (r) => r.sales_30 == null ? null : Number(r.sales_30) > 0 ? Math.ceil(Number(r.inventory_qty || 0) * 30 / Number(r.sales_30)) : Infinity;
  const daysLabel = (n) => n == null ? '未知' : Number.isFinite(n) ? `${n} 天` : '近30天未售';
  const empty = (title, copy) => `<div class="retail-empty">${icon('inbox')}<h3>${e(title)}</h3><p>${e(copy || '')}</p></div>`;
  const selectOptions = (list, current, label) => `<option value="all">${e(label)}</option>${list.map((x) => `<option value="${e(x.id)}" ${current === x.id ? 'selected' : ''}>${e(x.name)}</option>`).join('')}`;
  const riskNames = { near_expiry: '近效期', slow: '滞销', overpurchase: '采购过量', mismatch: '门店错配' };
  const storeRiskOptions = ['滞销', '近效期', '采购过量', '门店错配'];
  function storeRiskItems(shop) {
    if (Array.isArray(shop.risk_items)) return shop.risk_items;
    if (!overview?.is_demo) return [];
    return (ctx.state.risks || []).filter((risk) => risk.store_id === shop.store_id || risk.store === shop.store_name)
      .map((risk) => ({ risk_id: risk.id, sku: risk.sku, product: risk.product,
        inventory_cost: amount(risk), risk_label: (risk.tags || []).map((tag) => riskNames[tag]).filter(Boolean).join('、') || risk.risk_type || '待核查',
        reason: risk.observation || '需核查库存与销量差异' }))
      .sort((a, b) => b.inventory_cost - a.inventory_cost);
  }
  function storeRiskCost(shop) {
    if (shop.risk_cost != null) return Number(shop.risk_cost);
    if (!overview?.is_demo || !ctx.state.riskTotal) return null;
    return storeRiskItems(shop).reduce((total, risk) => total + Number(risk.inventory_cost || 0), 0);
  }
  function storeTurnover(shop) {
    if (shop.turnover_days != null) return Number(shop.turnover_days);
    if (!overview?.is_demo || shop.inventory_cost == null || shop.sales == null || shop.gross_profit == null) return null;
    const salesCost = Number(shop.sales) - Number(shop.gross_profit);
    return salesCost > 0 ? Number(shop.inventory_cost) / salesCost * period : null;
  }
  function storeRiskCount(shop) {
    return shop.risk_count ?? (overview?.is_demo && ctx.state.riskTotal ? storeRiskItems(shop).length : null);
  }
  function storeRiskLabels(shop) {
    const labels = Array.isArray(shop.risk_types) ? shop.risk_types : [shop.primary_risk, ...storeRiskItems(shop).map((risk) => risk.risk_label)];
    return storeRiskOptions.filter((option) => labels.some((label) => String(label || '').includes(option)));
  }
  function storeSortValue(shop) {
    if (storeSort === 'store_name') return shop.store_name || '';
    if (storeSort === 'inventory_cost') return shop.inventory_cost == null ? null : Number(shop.inventory_cost);
    if (storeSort === 'turnover_days') return storeTurnover(shop);
    return storeRiskCost(shop);
  }
  function storeSortHeader(label, key, help = '') {
    const active = storeSort === key;
    const direction = active ? (storeSortDesc ? 'descending' : 'ascending') : 'none';
    return `<th scope="col" aria-sort="${direction}"><button type="button" class="retail-store-sort ${active ? 'is-active' : ''}" data-store-sort="${key}" aria-label="按${label}排序${active ? `，当前${storeSortDesc ? '降序' : '升序'}` : ''}" ${help ? `title="${e(help)}" aria-describedby="retail-turnover-note"` : ''}>${label}<span aria-hidden="true">${active ? (storeSortDesc ? '↓' : '↑') : '↕'}</span></button></th>`;
  }

  function init(context) {
    ctx = context;
    document.addEventListener('click', onClick);
    document.addEventListener('change', onChange);
    document.addEventListener('toggle', (event) => {
      if (event.target.id === 'retail-store-risk-filter') storeRiskFilterOpen = event.target.open;
    }, true);
    document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeDetail(); });
    $('#retail-detail')?.addEventListener('click', (event) => { if (event.target === event.currentTarget) closeDetail(); });
    $('#retail-detail')?.addEventListener('cancel', (event) => { event.preventDefault(); closeDetail(); });
    window.addEventListener('resize', () => { if (ctx.currentRoute() === 'overview') drawCharts(); });
  }

  async function fetchOverview() {
    const version = ++requestVersion;
    overviewLoading = true; overviewError = ''; renderOverview();
    try {
      const data = await ctx.api(`/retail/overview?period=${period}&store_id=${encodeURIComponent(storeId)}`);
      if (version !== requestVersion) return;
      overview = data;
      if (storeId === 'all') stores = (data.stores || []).map((s) => ({ id: s.store_id, name: s.store_name }));
    } catch (error) { if (version === requestVersion) overviewError = error.message; }
    finally { if (version === requestVersion) { overviewLoading = false; renderOverview(); updateSource(); } }
  }

  function updateSource() {
    const source = $('#retail-source');
    const real = overview?.is_demo === false || ctx.state.dataCenter?.mode === 'real_inventory_snapshot';
    if (source) source.textContent = `${real ? '当前库存快照' : '零食仓 · 演示数据'}${overview?.as_of_date ? ` · ${overview.as_of_date.replaceAll('-', '/')}` : ''}`;
    const topDate = $('#retail-top-date');
    if (topDate) {
      const [year, month, day] = (overview?.as_of_date || '2026-10-03').split('-');
      topDate.textContent = `${year}年${Number(month)}月${Number(day)}日 · ${real ? '库存快照' : '演示数据'}`;
    }
  }

  function renderOverview() {
    if (!ctx) return;
    const root = $('#retail-overview'); if (!root) return;
    if (!overview && !overviewLoading && !overviewError) { fetchOverview(); return; }
    const d = overview, a = d?.account || {}, inv = d?.inventory || {};
    const filters = `<div class="retail-filters"><select aria-label="经营总览门店" id="retail-overview-store">${selectOptions(stores, storeId, `全部 ${stores.length || d?.scope?.store_count || ''} 家门店`)}</select><select aria-label="经营总览周期" id="retail-overview-period"><option value="7" ${period === 7 ? 'selected' : ''}>近7天</option><option value="30" ${period === 30 ? 'selected' : ''}>近30天</option></select></div>`;
    root.innerHTML = `<header class="retail-page-header"><div><h1>经营总览</h1><p>资金够不够，生意好不好，库存转得快不快</p></div>${filters}</header>`;
    if (overviewLoading) { root.insertAdjacentHTML('beforeend', '<div class="retail-loading" role="status">正在汇总经营数据…</div>'); return; }
    if (overviewError || !d) { root.insertAdjacentHTML('beforeend', `${empty('经营数据暂不可用', overviewError)}<button class="primary-action" data-retail="refresh-overview">重新读取</button>`); return; }
    const riskRate = Number(inv.cost) > 0 && inv.risk_cost != null ? Number(inv.risk_cost) / Number(inv.cost) * 100 : null;
    const commitments = d.purchase_commitments || {};
    const attentionScope = inv.risk_store_count == null || inv.risk_count == null
      ? '风险判定数据待补充' : `涉及 ${inv.risk_store_count} 家店 · ${inv.risk_count} 项商品`;
    const rankedStores = (d.stores || []).filter((shop) => !selectedStoreRisks.size || storeRiskLabels(shop).some((label) => selectedStoreRisks.has(label)))
      .sort((left, right) => {
        const a = storeSortValue(left), b = storeSortValue(right);
        const missingA = a == null || typeof a === 'number' && !Number.isFinite(a);
        const missingB = b == null || typeof b === 'number' && !Number.isFinite(b);
        if (missingA || missingB) return missingA === missingB ? 0 : missingA ? 1 : -1;
        const compared = storeSort === 'store_name' ? String(a).localeCompare(String(b), 'zh-CN') : Number(a) - Number(b);
        return (storeSortDesc ? -compared : compared) || String(left.store_name || '').localeCompare(String(right.store_name || ''), 'zh-CN');
      });
    const performance = showAllStores ? rankedStores : rankedStores.slice(0, 5);
    const storeRows = performance.map((shop) => {
      const riskCost = storeRiskCost(shop), riskCount = storeRiskCount(shop), turnover = storeTurnover(shop);
      const mainRisk = storeRiskItems(shop)[0]?.risk_label || shop.primary_risk || (riskCount === 0 ? '暂无重点风险' : '待补风险数据');
      const riskLabels = storeRiskLabels(shop);
      const visibleRisks = [...riskLabels.filter((label) => selectedStoreRisks.has(label)), ...riskLabels.filter((label) => !selectedStoreRisks.has(label))].slice(0, 2);
      return `<tr><td>${e(shop.store_name)}</td><td>${currency(shop.inventory_cost)}</td>
        <td class="retail-store-risk-cost">${currency(riskCost)}<small>${riskCount == null ? '缺少风险判定数据' : `${riskCount} 项待关注商品`}</small></td>
        <td>${turnover == null ? '待补销售成本' : `${Math.round(turnover)} 天`}</td>
        <td><div class="retail-store-risk-tags">${visibleRisks.length ? visibleRisks.map((label) => `<span class="retail-store-risk-tag">${e(label)}</span>`).join('') : `<span class="retail-store-risk-tag ${riskCount === 0 ? 'is-clear' : ''}">${e(mainRisk)}</span>`}${riskLabels.length > 2 ? `<small title="${e(riskLabels.join('、'))}">+${riskLabels.length - 2}</small>` : ''}</div></td>
        <td><button class="retail-link" data-store-detail="${e(shop.store_id)}">${riskCount ? '查看重点商品' : '查看门店详情'} ${icon('chevron_right')}</button></td></tr>`;
    }).join('');
    const riskFilter = `<details class="retail-store-risk-filter" id="retail-store-risk-filter" ${storeRiskFilterOpen ? 'open' : ''}><summary>${icon('filter_alt')}风险类型${selectedStoreRisks.size ? ` · 已选${selectedStoreRisks.size}项` : ' · 全部'}${icon('expand_more')}</summary><div class="retail-store-risk-options"><p>可多选，匹配任一所选风险</p>${storeRiskOptions.map((label) => `<label><input type="checkbox" data-store-risk-filter="${e(label)}" ${selectedStoreRisks.has(label) ? 'checked' : ''}><span>${e(label)}</span></label>`).join('')}<button type="button" data-store-risk-clear ${selectedStoreRisks.size ? '' : 'disabled'}>清除筛选</button></div></details>`;
    root.insertAdjacentHTML('beforeend', `
      <section class="retail-capital-cards" aria-label="老板最关心的四项资金数据">
        <article class="retail-capital-card is-cash"><span>账户可用资金</span><strong>${compact(a.balance)}</strong><small>${a.balance == null ? '尚未接入账户流水' : a.is_demo ? '当前可动用 · 演示账户' : '当前可动用 · 账户流水'}</small></article>
        <article class="retail-capital-card is-inventory"><span>库存占用资金</span><strong>${compact(inv.cost)}</strong><small>${inv.cost == null ? '尚未接入库存数据' : '当前货品 · 按进货成本'}</small></article>
        <article class="retail-capital-card is-attention"><span>待关注库存成本</span><strong>${compact(inv.risk_cost)}</strong><small>${attentionScope}</small></article>
        <article class="retail-capital-card is-commitment"><span>未来30天已确认采购付款</span><strong>${compact(commitments.amount)}</strong><small>${commitments.amount == null ? '未接入已确认采购付款计划' : `${commitments.count ?? '—'} 笔已确认付款${d.is_demo ? ' · 演示计划' : ''}`}</small></article>
      </section>
      <div class="retail-overview-grid">
        <section class="retail-surface retail-trend"><header><h2>资金变化 <small>近${period}天 · 万元</small></h2><button class="retail-link" data-retail="ledger">查看收支依据 ${icon('arrow_forward')}</button></header>
          ${a.balance == null ? empty('账户数据尚未接入', '库存成本与账户余额分别展示') : '<div class="retail-chart-label"><i></i>账户可用资金</div><canvas id="retail-cash-chart" role="img" aria-label="账户可用资金趋势"></canvas>'}
          <div class="retail-cash-totals"><div><small>销售回款</small><strong>${compact(a.cash_in)}</strong></div><div><small>实际流出（采购与经营费用）</small><strong>${compact(a.cash_out)}</strong></div></div>
        </section>
        <section class="retail-surface retail-stock-health"><header><h2>库存健康</h2></header><div class="retail-stock-content"><div class="retail-donut"><canvas id="retail-stock-chart" role="img" aria-label="待关注库存占比"></canvas><div><strong>${pct(riskRate)}</strong><small>待关注占比</small></div></div><dl><div><dt><i></i>其他库存</dt><dd>${inv.risk_cost == null ? '—' : compact(Math.max(0, Number(inv.cost || 0) - Number(inv.risk_cost || 0)))}</dd></div><div><dt><i class="risk"></i>待关注库存</dt><dd class="retail-amber">${compact(inv.risk_cost)}</dd></div><div><dt>库存合计</dt><dd>${compact(inv.cost)}</dd></div></dl></div><div class="retail-health-note">${icon('inventory_2')}<span>优先处理高占用门店</span><b>${inv.risk_store_count == null ? '待补数据' : `${inv.risk_store_count} 家`}</b></div><p class="retail-footnote">${inv.risk_count ?? '—'} 项门店商品需关注；待关注金额属于库存成本</p></section>
      </div>
      <section class="retail-surface retail-store-performance"><header><div><h2>门店库存资金状况</h2><p>比较各店库存资金占用，再查看需要关注的商品</p></div>${storeId !== 'all' || rankedStores.length > 5 ? `<button class="retail-link" data-retail="more-stores">${storeId !== 'all' ? '返回全部门店' : showAllStores ? '收起列表' : '查看全部门店'} ${icon(storeId === 'all' && showAllStores ? 'expand_less' : 'arrow_forward')}</button>` : ''}</header>
        <div class="retail-store-toolbar">${riskFilter}<span>当前匹配 ${rankedStores.length} 家门店${showAllStores || rankedStores.length <= 5 ? '' : ' · 先显示前 5 家'}</span></div>
        <div class="retail-table-scroll"><table><thead><tr>${storeSortHeader('门店', 'store_name')}${storeSortHeader('库存占用成本', 'inventory_cost')}${storeSortHeader('待关注库存成本', 'risk_cost')}${storeSortHeader('库存周转天数', 'turnover_days', '当前库存成本 ÷ 所选周期日均销售成本；越高说明库存转得越慢，不是剩余效期')}<th scope="col">主要风险</th><th scope="col">商品明细</th></tr></thead><tbody>${storeRows || `<tr><td colspan="6" class="retail-store-empty">${selectedStoreRisks.size ? '没有匹配所选风险的门店，可调整筛选条件。' : '当前没有门店数据'}</td></tr>`}</tbody></table></div>
        <p class="retail-footnote" id="retail-turnover-note">库存周转天数 = 当前库存成本 ÷ 所选周期日均销售成本；天数越高，库存转得越慢，不代表商品剩余效期。</p>
        <p class="retail-footnote retail-store-source">${e(d.source)} · 金额按进货成本计算；待关注库存成本不等于可立即回收的现金</p></section>`);
    requestAnimationFrame(drawCharts);
  }

  function canvasContext(id) {
    const canvas = $(id); if (!canvas) return null;
    const width = canvas.clientWidth, height = canvas.clientHeight;
    if (!width || !height) return null;
    const scale = window.devicePixelRatio || 1;
    canvas.width = width * scale; canvas.height = height * scale;
    const c = canvas.getContext('2d'); c.scale(scale, scale);
    c.font = '12px system-ui, sans-serif';
    return { c, width, height };
  }

  function drawCharts() {
    if (!overview) return;
    const palette = getComputedStyle(document.body);
    const accent = palette.getPropertyValue('--retail-accent').trim() || '#176b50';
    const muted = palette.getPropertyValue('--retail-muted').trim() || '#758078';
    const soft = palette.getPropertyValue('--retail-accent-soft').trim() || '#eaf4ec';
    const chart = canvasContext('#retail-cash-chart');
    const points = (overview.trend || []).filter((d) => d.cash_balance != null);
    if (chart && points.length) {
      const { c, width: w, height: h } = chart, left = 54, right = w - 28, top = 22, bottom = h - 32;
      const values = points.map((d) => Number(d.cash_balance) / 10000);
      let min = Math.min(...values), max = Math.max(...values);
      const margin = Math.max((max - min) * .2, .2); min -= margin; max += margin;
      const x = (i) => left + i / Math.max(1, points.length - 1) * (right - left);
      const y = (v) => bottom - (v - min) / (max - min) * (bottom - top);
      c.strokeStyle = '#e9ece8'; c.fillStyle = muted; c.lineWidth = 1;
      for (let j = 0; j < 4; j++) { const val = min + (max - min) * j / 3; const yy = y(val); c.beginPath(); c.moveTo(left, yy); c.lineTo(right, yy); c.stroke(); c.fillText(val.toFixed(1), 4, yy + 4); }
      c.beginPath(); c.moveTo(x(0), bottom); values.forEach((v, i) => c.lineTo(x(i), y(v))); c.lineTo(x(values.length - 1), bottom); c.closePath(); c.fillStyle = soft; c.fill();
      c.beginPath(); values.forEach((v, i) => i ? c.lineTo(x(i), y(v)) : c.moveTo(x(i), y(v))); c.strokeStyle = accent; c.lineWidth = 2.3; c.stroke();
      const ticks = [0, Math.floor((points.length - 1) / 2), points.length - 1];
      ticks.forEach((i) => { c.fillStyle = accent; c.beginPath(); c.arc(x(i), y(values[i]), 3.5, 0, Math.PI * 2); c.fill(); c.fillStyle = muted; c.textAlign = 'center'; c.fillText(points[i].date.slice(5).replace('-', '/'), x(i), h - 9); });
      c.fillStyle = accent; c.textAlign = 'right'; c.fillText(values.at(-1).toFixed(2), right, y(values.at(-1)) - 10);
    }
    const ring = canvasContext('#retail-stock-chart');
    if (ring) { const { c, width, height } = ring, r = Math.min(width, height) / 2 - 17, ratio = Math.max(0, Math.min(1, Number(overview.inventory.risk_cost || 0) / Math.max(1, Number(overview.inventory.cost || 0)))); c.lineWidth = 24; c.strokeStyle = soft; c.beginPath(); c.arc(width / 2, height / 2, r, 0, Math.PI * 2); c.stroke(); c.strokeStyle = '#f5b879'; c.beginPath(); c.arc(width / 2, height / 2, r, -Math.PI / 2, -Math.PI / 2 + ratio * Math.PI * 2); c.stroke(); }
  }

  function renderToday() {
    if (!ctx) return; const root = $('#retail-today'); if (!root) return;
    const s = ctx.state;
    const pending = s.proposals.filter((p) => p.status === 'pending_approval');
    const approved = s.proposals.filter((p) => p.status === 'approved');
    const delegated = s.executionTasks.filter((t) => !['received', 'completed'].includes(t.status));
    const completed = s.executionTasks.filter((t) => ['received', 'completed'].includes(t.status));
    const followUps = [...approved.map((item) => ({ item, kind: 'approved' })), ...delegated.map((item) => ({ item, kind: 'delegated' }))];
    const followUpTitle = ({ item, kind }) => {
      const proposal = kind === 'approved' ? item : s.proposals.find((p) => p.id === item.proposal_id);
      return proposal?.approval_summary?.title?.replace(/^审批/, '') || `方案 ${proposal?.id || item.proposal_id || item.id}`;
    };
    const proposedRisks = new Set(s.proposals.filter((p) => ['pending_approval', 'approved', 'execution_task_created'].includes(p.status)).map((p) => Number(p.risk_id)));
    const dueMinutes = (item) => { const label = item.due_date || ''; const match = label.match(/(\d{1,2}):(\d{2})/); return match ? (label.includes('明天') ? 1440 : 0) + Number(match[1]) * 60 + Number(match[2]) : Infinity; };
    const suggestions = s.workItems.filter((w) => w.status === '待处理' && !proposedRisks.has(Number(w.risk_id))).sort((a, b) => {
      const first = s.risks.find((r) => Number(r.id) === Number(a.risk_id));
      const second = s.risks.find((r) => Number(r.id) === Number(b.risk_id));
      return dueMinutes(a) - dueMinutes(b) || Number(a.rank || 999) - Number(b.rank || 999) || amount(second || {}) - amount(first || {});
    });
    const todayCount = $('#today-nav-count'); if (todayCount) todayCount.textContent = String(pending.length + suggestions.length);
    const items = todayTab === 'pending' ? pending.map((item) => ({ item, kind: 'approval' })) : todayTab === 'suggestions' ? suggestions.map((item) => ({ item, kind: 'suggestion' })) : todayTab === 'delegated' ? followUps : completed.map((item) => ({ item, kind: 'completed' }));
    const tabs = [['pending', `待我审批（${pending.length}）`], ['suggestions', `待评估建议（${suggestions.length}）`], ['delegated', '审批后跟进', followUps.length], ['completed', '已完成', completed.length]];
    const visibleItems = items.slice(0, todayLimit);
    const itemKey = ({ item, kind }) => `${kind}:${item.id}`;
    if (!visibleItems.some((entry) => itemKey(entry) === todaySelectedKey)) todaySelectedKey = visibleItems.length ? itemKey(visibleItems[0]) : null;
    root.innerHTML = `<header class="retail-page-header retail-today-heading"><div><h1>今日工作台</h1><p>共 <b class="retail-green">${pending.length + suggestions.length}</b> 件值得关注</p></div><button class="secondary-action" data-retail="refresh-today">${icon('refresh')}刷新待办</button></header>
      <nav class="retail-tabs" aria-label="个人事项分类">${tabs.map(([key, label, count]) => `<button type="button" data-owner-tab="${key}" class="${todayTab === key ? 'active' : ''}" aria-pressed="${todayTab === key}">${label}${count == null ? '' : `<span>${count}</span>`}</button>`).join('')}</nav>
      ${todayTab === 'delegated' ? `<p class="retail-footnote" role="status">${approved.length} 项已审批待生成任务，${delegated.length} 项待执行或待反馈。生成任务后仍需安排负责人执行并记录回执。</p>` : ''}
      <div class="retail-agenda">${visibleItems.map(({ item, kind }) => {
        const proposal = kind === 'approval' || kind === 'approved' ? item : s.proposals.find((p) => p.id === item.proposal_id);
        const risk = s.risks.find((r) => Number(r.id) === Number(item.risk_id ?? proposal?.risk_id));
        const work = s.workItems.find((w) => Number(w.risk_id) === Number(item.risk_id) && w.status === '待审批');
        const isProposal = kind === 'approval', isApproved = kind === 'approved', isSuggestion = kind === 'suggestion';
        const key = itemKey({ item, kind }), selected = key === todaySelectedKey;
        const title = isProposal ? item.approval_summary?.title || `${risk?.product || '处置方案'} · 待审批` : isSuggestion ? item.title : followUpTitle({ item, kind });
        const due = isProposal ? work?.due_date : isSuggestion ? item.due_date : null;
        const time = due?.match(/\d{1,2}:\d{2}/)?.[0];
        const dueContext = due?.startsWith('明天') ? '明天 · ' : due?.startsWith('今天') ? '今天 · ' : '';
        const timeCaption = due && !time ? due : `${dueContext}${isProposal ? '方案审批' : isSuggestion ? '经营建议' : taskLabel(item.status)}`;
        return `<article class="retail-agenda-item ${selected ? 'is-selected' : ''} ${isProposal ? 'is-approval' : ''}" data-owner-item="${e(key)}"><div class="retail-agenda-time"><i></i><b>${e(time || (isProposal ? '待审批' : isSuggestion ? '待评估' : isApproved ? '已审批' : '跟进中'))}</b><small>${e(timeCaption)}</small></div><div class="retail-agenda-body"><button type="button" class="retail-agenda-select" aria-pressed="${selected}" aria-label="选中${e(title)}"><span class="retail-task-icon">${icon(isProposal ? 'fact_check' : isSuggestion ? 'troubleshoot' : 'local_shipping')}</span><span class="retail-agenda-copy"><span class="retail-agenda-title"><strong class="retail-agenda-name">${e(title)}</strong><span class="retail-agenda-tag">${isProposal ? '待你拍板' : isSuggestion ? '建议评估' : taskLabel(item.status)}</span></span><span class="retail-agenda-subtitle">${e(isSuggestion ? risk?.store || item.owner || '负责人待安排' : proposal?.approval_summary?.detail || risk?.store || '负责人待安排')}</span><span class="retail-task-facts">${isProposal || isApproved ? `<span>方案版本 <b>V${item.current_version}</b></span><span>${isApproved ? '尚未生成任务，需继续安排执行' : '审批前可查看计算依据'}</span>` : isSuggestion ? `<span>库存占用 <b>${currency(risk ? amount(risk) : null)}</b></span><span>${e(item.type)}</span>` : `<span>方案版本 <b>V${item.proposal_version}</b></span><span>${e(item.metadata?.receipt_ref || '等待负责人执行并记录回执')}</span>`}</span></span></button><button type="button" class="retail-agenda-action ${selected ? 'primary-action' : 'secondary-action'}" ${isProposal || isApproved ? `data-owner-proposal="${e(item.id)}"` : isSuggestion ? `data-owner-suggestion="${e(item.id)}"` : 'data-go="execution"'}>${isProposal ? '查看并审核' : isApproved ? '安排执行' : isSuggestion ? '查看建议' : '查看进度'} ${icon('arrow_forward')}</button></div></article>`;
      }).join('') || empty(todayTab === 'pending' ? '待审批事项已处理完' : '当前没有这类事项', todayTab === 'pending' ? 'Agent 建议确认并提交后，会出现在这里。' : '后续事项会根据业务状态自动更新。')}</div>
      ${items.length > todayLimit ? `<button class="retail-load-more" data-retail="more-today">查看其余 ${items.length - todayLimit} 项 ${icon('expand_more')}</button>` : ''}
      ${todayTab === 'pending' ? `<section class="retail-surface retail-delegated"><header><h2>审批后跟进 <small>${followUps.length}</small></h2><button class="retail-link" data-owner-tab="delegated">查看全部 ${icon('arrow_forward')}</button></header>${followUps.slice(0, 2).map((entry) => `<div class="retail-delegated-row">${icon('assignment_turned_in')}<strong>${e(followUpTitle(entry))}</strong><span>${taskLabel(entry.item.status)}</span><button class="retail-link" ${entry.kind === 'approved' ? `data-owner-proposal="${e(entry.item.id)}"` : 'data-go="execution"'}>${entry.kind === 'approved' ? '安排执行' : '查看进度'}</button></div>`).join('') || '<p class="retail-footnote">暂无已审批事项。审批通过的方案会在这里持续跟进。</p>'}</section>` : ''}
      <p class="retail-footnote">审批通过 → 审批后跟进 → 生成待执行任务 → 负责人执行并回填回执 → 已完成。当前系统不会自动派单到门店或 ERP。</p>`;
  }

  function selectTodayItem(key) {
    todaySelectedKey = key;
    document.querySelectorAll('#retail-today .retail-agenda-item').forEach((row) => {
      const selected = row.dataset.ownerItem === key;
      row.classList.toggle('is-selected', selected);
      row.querySelector('.retail-agenda-select')?.setAttribute('aria-pressed', String(selected));
      const action = row.querySelector('.retail-agenda-action');
      action?.classList.toggle('primary-action', selected);
      action?.classList.toggle('secondary-action', !selected);
    });
  }

  function taskLabel(status) { return ({ pending_approval: '待审批', approved: '已审批 · 待生成任务', draft_pending_external_execution: '待安排执行', execution_task_created: '已生成任务', pending_dispatch: '待出库', in_transit: '在途', awaiting_receipt: '待收货', received: '已收货', completed: '已完成', exception: '异常待处理', needs_replan: '待重新测算' })[status] || status || '待处理'; }

  function showApprovalFollowUp(id) {
    todayTab = 'delegated';
    todayLimit = Math.max(3, ctx.state.proposals.filter((p) => p.status === 'approved').length);
    todaySelectedKey = `approved:${id}`;
    renderToday();
  }

  function slowCandidates() {
    return (ctx.state.diagnosisRisks || ctx.state.risks)
      .filter((risk) => risk.teacher_baseline?.candidate || coverage(risk) >= 120 || (risk.tags || []).includes('slow'))
      .sort((a, b) => amount(b) - amount(a));
  }

  function selectDiagnosisRisk(id) {
    if (Number(diagnosis.selectedId) === Number(id)) return;
    diagnosis.requestVersion += 1;
    diagnosis.selectedId = Number(id);
    diagnosis.detail = null;
    diagnosis.loading = false;
    diagnosis.error = '';
    renderDiagnosis();
  }

  async function loadDiagnosisDetail(id) {
    const version = ++diagnosis.requestVersion;
    diagnosis.loading = true;
    diagnosis.error = '';
    renderDiagnosis();
    try {
      const detail = await ctx.api(`/risks/${id}`);
      if (version === diagnosis.requestVersion) diagnosis.detail = detail;
    } catch (error) {
      if (version === diagnosis.requestVersion) diagnosis.error = error.message;
    } finally {
      if (version === diagnosis.requestVersion) {
        diagnosis.loading = false;
        renderDiagnosis();
      }
    }
  }

  function renderDiagnosis() {
    if (!ctx) return;
    const root = $('#slow-list');
    if (!root) return;
    const all = slowCandidates();
    const slowCount = $('#slow-nav-count');
    if (slowCount) slowCount.textContent = String(all.length);
    if (!all.length) {
      diagnosis.selectedId = null;
      diagnosis.detail = null;
      root.innerHTML = empty('暂无需要关注的滞销商品', '导入库存和销售数据后，再查看诊断结果。');
      return;
    }
    if (!all.some((risk) => Number(risk.id) === Number(diagnosis.selectedId))) {
      diagnosis.requestVersion += 1;
      diagnosis.selectedId = Number(all[0].id);
      diagnosis.detail = null;
      diagnosis.loading = false;
      diagnosis.error = '';
    }
    const index = all.findIndex((risk) => Number(risk.id) === Number(diagnosis.selectedId));
    const candidate = all[index];
    const detail = Number(diagnosis.detail?.risk?.id) === Number(candidate.id) ? diagnosis.detail : null;
    const risk = detail?.risk || candidate;
    const cover = coverage(risk);
    const unit = e(risk.unit || '件');
    const onHand = risk.inventory_qty == null ? null : Number(risk.inventory_qty);
    const sold = risk.sales_30 == null ? null : Number(risk.sales_30);
    const scale = Math.max(onHand || 0, sold || 0, 1);
    const stockWidth = Math.max(0, Math.min(100, (onHand || 0) / scale * 100));
    const salesWidth = Math.max(0, Math.min(100, (sold || 0) / scale * 100));
    const peers = detail?.comparison?.comparison_median;
    const peerMedian = peers == null ? null : Number(peers);
    const gap = peerMedian > 0 && sold != null ? Math.round((1 - sold / peerMedian) * 100) : null;
    const route = ctx.agentRouteForRisk(risk);
    const recommendation = ({
      '调拨': '核对接收店需求与运输费用，再评估跨店调拨。',
      '促销': '核对批次可售天数与促销价格，再评估处置。',
      '采购刹车': '核对未执行采购单与在途数量，再测算减采。',
      '退供': '核对供应商退换条款，再决定是否申请退供。',
    })[risk.risk_type] || '先补充经营记录，再决定处理方式。';
    const actionLabel = ({ transfer: '测算跨店调拨', 'expiry-rescue': '评估近效期处置', 'procurement-brake': '测算采购调整' })[route];
    const factors = detail?.factors || [];
    const checks = ['门店客群不匹配', '陈列或推荐不足', '采购量过大']
      .map((label) => factors.find((factor) => factor.label === label))
      .filter(Boolean);
    const missing = (detail?.evidence?.missing_fields || risk.missing_fields || []).map(ctx.missingLabel);
    const realData = overview?.is_demo === false || ctx.state.dataCenter?.mode === 'real_inventory_snapshot';
    const totalCost = all.reduce((sum, item) => sum + amount(item), 0);
    const storeCount = new Set(all.map((item) => item.store)).size;
    const focusedPicker = document.activeElement?.id === 'retail-slow-risk';
    const focusedStep = document.activeElement?.dataset?.slowStep;
    const sourceOpen = root.querySelector('.retail-slow-source')?.open;
    root.innerHTML = `
      <div class="retail-slow-summary" aria-label="滞销诊断范围">
        <span>待关注 <strong>${all.length}</strong> 项</span><i></i>
        <span>涉及 <strong>${storeCount}</strong> 家门店</span><i></i>
        <span>库存占用 <strong>${compact(totalCost)}</strong></span>
      </div>
      <div class="retail-slow-toolbar">
        <label class="retail-slow-picker">${icon('inventory_2')}<span class="retail-slow-sr">切换诊断商品</span><select id="retail-slow-risk" aria-label="切换诊断商品">${all.map((item) => `<option value="${e(item.id)}" ${Number(item.id) === Number(candidate.id) ? 'selected' : ''}>${e(item.product)} · ${e(item.store)}</option>`).join('')}</select></label>
        <span class="retail-slow-position">按库存成本排序 · ${index + 1} / ${all.length}</span>
        <div class="retail-slow-arrows"><button type="button" data-slow-step="-1" aria-label="上一件商品" ${index === 0 ? 'disabled' : ''}>${icon('chevron_left')}</button><button type="button" data-slow-step="1" aria-label="下一件商品" ${index === all.length - 1 ? 'disabled' : ''}>${icon('chevron_right')}</button></div>
      </div>
      <section class="retail-slow-focus" aria-label="当前商品诊断">
        <div class="retail-slow-product">
          <div class="retail-slow-visual">${realData ? icon('inventory_2') : `<img src="${photo(risk.product)}" alt="零食品类示意图">`}</div>
          <div class="retail-slow-product-copy"><span class="retail-slow-label">当前查看的门店商品</span><h2>${e(risk.product)}</h2><p>${icon('storefront')}${e(risk.store)} <span>SKU ${e(risk.sku || '未提供')}</span></p></div>
          <div class="retail-slow-money"><span>当前库存占用资金</span><strong>${currency(amount(risk))}</strong><small>按进货成本计算，并非可回收现金</small></div>
        </div>
        <div class="retail-slow-metrics">
          <div><span>当前库存</span><strong>${onHand == null ? '—' : onHand.toLocaleString('zh-CN')} <small>${unit}</small></strong></div>
          <div><span>近30天售出</span><strong>${sold == null ? '—' : sold.toLocaleString('zh-CN')} <small>${unit}</small></strong></div>
          <div><span>按当前销量估算覆盖</span><strong class="retail-slow-coverage">${daysLabel(cover)}</strong></div>
        </div>
        <div class="retail-slow-bars" aria-label="库存与近30天销量对比">
          <div><span>库存</span><div class="retail-slow-track"><i style="width:${stockWidth}%"></i></div><b>${onHand == null ? '—' : onHand.toLocaleString('zh-CN')} ${unit}</b></div>
          <div><span>已售</span><div class="retail-slow-track"><i style="width:${salesWidth}%"></i></div><b>${sold == null ? '—' : sold.toLocaleString('zh-CN')} ${unit}</b></div>
        </div>
        <p class="retail-slow-caption">两条横条使用相同数量刻度。覆盖天数按近30天日均销量估算，不代表商品保质期。</p>
      </section>
      <div class="retail-slow-detail-grid">
        <section class="retail-slow-finding"><h3>为什么需要关注</h3>
          <p>当前库存 ${onHand == null ? '未知' : onHand.toLocaleString('zh-CN')} ${unit}，近30天售出 ${sold == null ? '未知' : sold.toLocaleString('zh-CN')} ${unit}。${cover == null ? '缺少销量数据，暂不能估算库存覆盖天数。' : cover === Infinity ? '近30天没有销售记录，需要核查是否未上架或数据缺失。' : `按当前销量估算，库存可覆盖约 ${daysLabel(cover)}。`}</p>
          <div class="retail-slow-peer"><span>同规格门店近30天销量中位数</span><strong>${peerMedian == null || !Number.isFinite(peerMedian) ? diagnosis.loading ? '正在读取' : '暂无可比门店' : `${peerMedian.toLocaleString('zh-CN')} ${unit}`}</strong><small>${gap == null ? '门店对照仅用于发现差异' : gap > 0 ? `本店比对照中位数低 ${gap}%` : gap < 0 ? `本店比对照中位数高 ${Math.abs(gap)}%` : '本店与对照中位数持平'}</small></div>
          <p class="retail-slow-caution">现有数据可以看到库存与销量的差距，不能据此断定是客群、陈列、价格或采购造成。</p>
        </section>
        <section class="retail-slow-next"><div class="retail-slow-next-heading">${icon('fact_check')}<h3>下一步怎么处理</h3></div><p>${e(recommendation)}</p>
          ${diagnosis.loading ? '<div class="retail-slow-evidence-status" role="status">正在读取这件商品的对照数据与核查线索…</div>' : diagnosis.error ? `<div class="retail-slow-evidence-status" role="alert">证据读取失败：${e(diagnosis.error)} <button type="button" data-slow-retry="1">重试</button></div>` : checks.length ? `<div class="retail-slow-checks">${checks.map((factor) => `<div><b>${e(factor.label)}</b><small>${e(factor.next_check)}</small></div>`).join('')}</div>` : '<div class="retail-slow-evidence-status">当前没有更多可展示的原因线索。</div>'}
          <div class="retail-slow-actions"><button type="button" class="secondary-action" data-retail-full-risk="${e(risk.id)}">查看完整证据</button>${actionLabel ? `<button type="button" class="primary-action" data-retail-plan="${route}" data-risk-id="${e(risk.id)}">${actionLabel} ${icon('arrow_forward')}</button>` : ''}</div>
        </section>
      </div>
      <details class="retail-slow-source"><summary>查看数据来源与计算口径 ${icon('expand_more')}</summary><div>${(detail?.facts || []).filter((fact) => fact.label !== '库存覆盖天数').map((fact) => `<p><span>${e(fact.label)}</span><strong>${e(fact.value)}</strong><small>${e(fact.source)}</small></p>`).join('') || '<p>详情读取后展示库存与销售数据来源。</p>'}<p><span>覆盖天数</span><strong>库存数量 ÷（近30天销量 ÷ 30）</strong><small>销量为 0 时显示“近30天未售”</small></p>${missing.length ? `<p class="retail-slow-missing">仍需核查：${missing.map(e).join('、')}</p>` : ''}</div></details>`;
    if (sourceOpen) root.querySelector('.retail-slow-source').open = true;
    if (focusedPicker) root.querySelector('#retail-slow-risk')?.focus();
    else if (focusedStep) root.querySelector(`[data-slow-step="${focusedStep}"]:not(:disabled)`)?.focus();
    if (!detail && !diagnosis.loading && !diagnosis.error) void loadDiagnosisDetail(candidate.id);
  }

  function openDetail(title, content) {
    const dialog = $('#retail-detail'); dialogTrigger = document.activeElement;
    $('#retail-detail-title').textContent = title; $('#retail-detail-content').innerHTML = content;
    if (!dialog.open) dialog.showModal(); $('#retail-detail-close').focus();
  }
  function closeDetail() { const d = $('#retail-detail'); if (d?.open) { d.close(); dialogTrigger?.focus(); } }

  function showStoreDetail(id) {
    const shop = (overview?.stores || []).find((item) => item.store_id === id);
    if (!shop) return;
    const items = storeRiskItems(shop), count = storeRiskCount(shop), riskCost = storeRiskCost(shop), turnover = storeTurnover(shop);
    const rows = items.slice(0, 5).map((item) => `<article class="retail-store-attention-item"><div><strong>${e(item.product || '未命名商品')}</strong><span class="retail-store-risk-tag">${e(item.risk_label || '待核查')}</span><small>${e(item.reason || '需核查库存与销量差异')}</small></div><b>${currency(item.inventory_cost)}</b></article>`).join('');
    openDetail(`${shop.store_name} · 库存资金`, `
      <p class="retail-store-detail-intro">${count == null ? '风险判定数据待补充。' : count ? `当前有 ${count} 项商品需要关注，先看占用金额最高的商品。` : '当前没有被标记为待关注的商品。'}</p>
      <div class="retail-store-detail-metrics"><div><small>库存占用成本</small><strong>${currency(shop.inventory_cost)}</strong></div><div><small>待关注库存成本</small><strong>${currency(riskCost)}</strong></div><div><small>库存周转天数</small><strong>${turnover == null ? '待补数据' : `${Math.round(turnover)} 天`}</strong></div></div>
      <h3>重点关注商品</h3><div class="retail-store-attention-list">${rows || `<p class="retail-store-detail-empty">${count == null ? '当前数据不足，无法判断哪些商品需要优先处理。' : '暂无待关注商品。'}</p>`}</div>
      ${count > items.slice(0, 5).length ? `<p class="retail-footnote">仅展示库存占用最高的 5 项，实际共 ${count} 项。</p>` : ''}
      <h3>销售背景</h3><div class="retail-store-sales-context"><div><span>近${period}天销售额</span><b>${shop.sales == null ? '未接入' : currency(shop.sales)}</b></div><div><span>毛利率</span><b>${shop.gross_margin_pct == null ? '未接入' : pct(shop.gross_margin_pct)}</b></div></div>
      <p class="retail-footnote">销售和毛利用于辅助判断调拨、促销；待关注库存成本不是已回款金额。</p>
      <footer class="retail-detail-actions"><button type="button" class="secondary-action" data-store-filter="${e(shop.store_id)}">只看这家门店</button></footer>`);
  }

  async function diagnose(id) {
    openDetail('商品诊断', '<p class="retail-loading">正在读取计算依据…</p>');
    try {
      const data = await ctx.api(`/risks/${id}`), r = data.risk;
      const destination = ctx.agentRouteForRisk(r);
      const missing = data.evidence?.missing_fields || [];
      if (!$('#retail-detail').open) return;
      $('#retail-detail-title').textContent = `${r.product} · ${r.store}`;
      $('#retail-detail-content').innerHTML = `<div class="retail-detail-metrics"><div><small>库存成本</small><strong>${currency(amount(r))}</strong></div><div><small>库存覆盖天数</small><strong>${daysLabel(coverage(r))}</strong></div></div><h3>已经知道的事实</h3><p>当前库存 ${r.inventory_qty} ${e(r.unit || '件')}，近30天售出 ${r.sales_30} ${e(r.unit || '件')}。${e(r.observation || '')}</p><div class="retail-detail-facts">${(data.facts || []).slice(0, 3).map((f) => `<div><span>${e(f.label)}</span><b>${e(f.value)}</b><small>${e(f.source)}</small></div>`).join('')}</div><h3>哪些原因还需核查</h3>${(data.factors || []).slice(0, 3).map((f) => `<p><b>${e(f.label)}</b><span class="retail-chip">${e(f.evidence_label)}</span><br><small>${e(f.next_check)}</small></p>`).join('')}<details><summary>查看缺失数据与证据口径</summary><p>${missing.map(ctx.missingLabel).map(e).join('、') || '已有数据已按当前快照校验'}</p><p>库存成本不代表可回收现金；处置数量需在相应工作台再次计算。</p></details><footer class="retail-detail-actions"><button class="secondary-action" data-retail-full-risk="${id}">查看完整证据</button>${destination !== 'slow-diagnosis' ? `<button class="primary-action" data-retail-plan="${destination}" data-risk-id="${id}">评估${({ transfer: '调拨', 'expiry-rescue': '近效期处置', 'procurement-brake': '采购调整' })[destination]}方案 ${icon('arrow_forward')}</button>` : ''}</footer>`;
    } catch (error) { $('#retail-detail-content').innerHTML = empty('读取失败', error.message); }
  }

  function showProposal(id) {
    const p = ctx.state.proposals.find((p) => p.id === id); if (!p) return;
    const s = p.approval_summary || {};
    const approved = p.status === 'approved';
    openDetail(approved ? (s.title || '已审批方案').replace(/^审批/, '') : s.title || '审核方案', `<p>${e(s.detail || '请先核对方案的金额与计算条件。')}</p><p class="retail-footnote">${e(s.boundary || '审批只绑定当前事实与方案版本。')}</p><div class="retail-detail-metrics"><div><small>当前方案版本</small><strong>V${p.current_version}</strong></div><div><small>当前状态</small><strong class="retail-text-value">${e(taskLabel(p.status))}</strong></div></div><p>${approved ? '下一步：生成待执行任务，再由负责人安排实际执行并记录回执。当前尚未派给门店。' : '审批通过后，事项会移入「审批后跟进」，继续安排执行。'}</p><footer class="retail-detail-actions"><button class="secondary-action" data-go="approvals" data-retail="close-detail">查看全部方案</button>${p.status === 'pending_approval' ? `<button class="primary-action" data-owner-confirm="${e(id)}">确认并审批 ${icon('check')}</button>` : approved ? `<button class="primary-action" data-owner-execute="${e(id)}">生成待执行任务 ${icon('arrow_forward')}</button>` : '<button class="primary-action" data-go="approvals" data-retail="close-detail">查看方案状态</button>'}</footer>`);
  }

  function onClick(event) {
    const selectedRow = event.target.closest('#retail-today .retail-agenda-item');
    if (selectedRow) selectTodayItem(selectedRow.dataset.ownerItem);
    const b = event.target.closest('button, a'); if (!b || !ctx) return;
    if (b.dataset.retailRisk) { diagnose(b.dataset.retailRisk); return; }
    if (b.dataset.slowStep) { const all = slowCandidates(); const index = all.findIndex((risk) => Number(risk.id) === Number(diagnosis.selectedId)); const next = all[index + Number(b.dataset.slowStep)]; if (next) selectDiagnosisRisk(next.id); return; }
    if (b.dataset.slowRetry) { diagnosis.error = ''; void loadDiagnosisDetail(diagnosis.selectedId); return; }
    if (b.dataset.ownerTab) { todayTab = b.dataset.ownerTab; todayLimit = 3; todaySelectedKey = null; renderToday(); return; }
    if (b.dataset.ownerProposal) { showProposal(b.dataset.ownerProposal); return; }
    if (b.dataset.ownerConfirm) { b.disabled = true; ctx.approveProposal(b.dataset.ownerConfirm).then((ok) => { if (ok) closeDetail(); else b.disabled = false; renderToday(); }); return; }
    if (b.dataset.ownerExecute) { b.disabled = true; ctx.executeProposal(b.dataset.ownerExecute).then((task) => { if (task) { closeDetail(); todayTab = 'delegated'; todaySelectedKey = `delegated:${task.id}`; todayLimit = Math.max(3, ctx.state.proposals.filter((p) => p.status === 'approved').length + 1); } else b.disabled = false; renderToday(); }); return; }
    if (b.dataset.ownerSuggestion) { const w = ctx.state.workItems.find((w) => w.id === b.dataset.ownerSuggestion); if (w) openPlan(w.route, w.risk_id); return; }
    if (b.dataset.retailPlan) { openPlan(b.dataset.retailPlan, b.dataset.riskId); return; }
    if (b.dataset.retailFullRisk) { closeDetail(); ctx.state.selectedId = Number(b.dataset.retailFullRisk); ctx.state.parentRoute = 'slow-diagnosis'; location.hash = 'risks'; ctx.renderRiskList(); ctx.loadSelectedDetail(); return; }
    if (b.dataset.storeSort) { storeSortDesc = storeSort === b.dataset.storeSort ? !storeSortDesc : b.dataset.storeSort !== 'store_name'; storeSort = b.dataset.storeSort; renderOverview(); return; }
    if (b.hasAttribute('data-store-risk-clear')) { selectedStoreRisks.clear(); storeRiskFilterOpen = true; showAllStores = false; renderOverview(); return; }
    if (b.dataset.storeDetail) { showStoreDetail(b.dataset.storeDetail); return; }
    if (b.dataset.storeFilter) { closeDetail(); storeId = b.dataset.storeFilter; fetchOverview(); return; }
    switch (b.dataset.retail) {
      case 'close-detail': closeDetail(); break;
      case 'refresh-overview': fetchOverview(); break;
      case 'refresh-today': ctx.refreshCommonRecords(); break;
      case 'more-stores': if (storeId !== 'all') { storeId = 'all'; showAllStores = true; fetchOverview(); } else { showAllStores = !showAllStores; renderOverview(); } break;
      case 'more-today': todayLimit += 5; renderToday(); break;
      case 'ledger': openDetail('账户收支依据', `<p>${e(overview?.account?.source || '尚未接入账户数据')}</p>${(overview?.metadata?.assumptions || []).map((x) => `<p>${e(x)}</p>`).join('')}<div class="retail-detail-facts"><div><span>期初余额</span><b>${currency(overview?.account?.opening_balance)}</b></div><div><span>期间收款</span><b>${currency(overview?.account?.cash_in)}</b></div><div><span>期间支出</span><b>${currency(overview?.account?.cash_out)}</b></div><div><span>期末余额</span><b>${currency(overview?.account?.balance)}</b></div></div>`); break;
      case 'search': document.body.classList.toggle('retail-search-open'); if (document.body.classList.contains('retail-search-open')) $('#global-search').focus(); break;
    }
  }
  function openPlan(route, id) {
    const origin = ctx.currentRoute();
    workbenchReturn = origin === 'today' ? { route: 'today', label: '返回今日工作台' }
      : origin === 'slow-diagnosis' ? { route: 'slow-diagnosis', label: '返回滞销诊断' }
      : null;
    plannedRoute = route;
    closeDetail();
    if (route === 'slow-diagnosis') {
      selectDiagnosisRisk(id);
      if (origin !== route) location.hash = route;
      return;
    }
    location.hash = route;
    ctx.loadWorkbench(route, id);
  }
  function backTarget() { return workbenchReturn || { route: 'overview', label: '返回经营总览' }; }
  function onChange(event) {
    const t = event.target;
    if (t.dataset.storeRiskFilter) { if (t.checked) selectedStoreRisks.add(t.dataset.storeRiskFilter); else selectedStoreRisks.delete(t.dataset.storeRiskFilter); storeRiskFilterOpen = true; showAllStores = false; renderOverview(); return; }
    if (t.id === 'retail-overview-store') { storeId = t.value; fetchOverview(); }
    if (t.id === 'retail-overview-period') { period = Number(t.value); fetchOverview(); }
    if (t.id === 'retail-slow-risk') selectDiagnosisRisk(t.value);
  }
  function routeChanged(route) {
    if (route !== plannedRoute) workbenchReturn = null;
    plannedRoute = null;
    document.body.dataset.route = route; updateSource();
    if (route === 'slow-diagnosis') {
      const back = backTarget(), link = $('#retail-slow-back');
      if (link) { link.href = `#${back.route}`; link.querySelector('span:last-child').textContent = back.label; }
    }
    if (route === 'overview') { renderOverview(); requestAnimationFrame(drawCharts); }
    if (route === 'today') renderToday();
    if (route === 'slow-diagnosis') renderDiagnosis();
    if (route === 'simulation') window.RetailSimulation?.mount($('[data-view="simulation"]'), ctx);
    closeDetail();
  }
  function refresh() { diagnosis.requestVersion += 1; diagnosis.detail = null; diagnosis.loading = false; diagnosis.error = ''; fetchOverview(); renderToday(); renderDiagnosis(); updateSource(); }
  return { init, renderOverview, renderToday, renderDiagnosis, routeChanged, refresh, photo, backTarget, showApprovalFollowUp, taskLabel };
})();

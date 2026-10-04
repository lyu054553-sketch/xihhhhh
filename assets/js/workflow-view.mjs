import { escapeHtml as e, metric, list, panel, STATUS_LABELS } from './retail-view.mjs';
import { formatYuan as money, formatNumber as number } from './retail-contract.mjs';

const MODULES = new Set(['transfer', 'expiry-rescue', 'procurement-brake']);
const text = value => e(value ?? '未提供');
const quantity = (value, unit) => `${number(value)} ${unit || '（单位未提供）'}`;
const row = (label, value) => `<div><dt>${e(label)}</dt><dd>${value}</dd></div>`;

/** Display returned calculations only; no inventory or cash arithmetic belongs here. */
export function calculationSummary(type, calculation, input = {}) {
  if (!calculation?.valid) return '';
  const c = calculation, cash = c.cash || {}, unit = input.unit;
  let body = '';
  if (type === 'transfer') {
    const beforeAfter = c.before_after || {};
    body = `<p class="decision-line">${text(input.source_store)} → ${text(input.target_store)} · ${e(quantity(c.allocation?.quantity, unit))}</p>
      <div class="table-wrap"><table class="data-table"><thead><tr><th>门店</th><th>调拨前库存</th><th>调拨后库存</th><th>安全库存</th><th>调拨后覆盖天数</th></tr></thead><tbody>${['source', 'target'].map(key => {
        const s = beforeAfter[key] || {};
        return `<tr><th>${text(s.store)}</th><td>${e(quantity(s.on_hand_before, unit))}</td><td>${e(quantity(s.on_hand_after, unit))}</td><td>${e(quantity(s.safety_stock, unit))}</td><td>${number(s.coverage_after)}</td></tr>`;
      }).join('')}</tbody></table></div><div class="metric-grid">${metric('调拨库存成本', money(cash.inventory_cost))}${metric('运输费用', money(c.economic?.transport_fee))}${metric('估算净避免报损', money(c.economic?.net_avoidable_loss))}</div><p>${text(c.economic?.note)}</p>`;
  } else if (type === 'expiry-rescue') {
    body = `<p class="decision-line">${text(input.store)} · 最晚处置日 ${text(c.forecast?.latest_disposal_date)}</p><div class="metric-grid">${metric('预计正常售出', quantity(c.forecast?.normal_sale_qty, unit))}${metric('预计剩余数量', quantity(c.forecast?.expected_remaining_qty, unit))}</div>
      <div class="table-wrap"><table class="data-table"><thead><tr><th>处置方式</th><th>计划数量</th><th>费用</th><th>现金影响</th><th>待核实条件</th></tr></thead><tbody>${(c.alternatives || []).map(a => `<tr><th>${text(a.type)}</th><td>${e(quantity(a.quantity, unit))}</td><td>${money(a.fee)}</td><td>${money(a.cash_impact)}</td><td>${text(a.assumption)}</td></tr>`).join('')}</tbody></table></div>`;
  } else if (type === 'procurement-brake') {
    const p = c.payment || {}, stock = c.inventory_position || {};
    body = `<p class="decision-line">采购单 ${text(c.order?.po_number)} · 明细 ${text(c.order?.line_number)}</p><div class="metric-grid">${metric('当前库存', quantity(stock.current_inventory, unit))}${metric('在途数量', quantity(stock.in_transit_qty, unit))}${metric('调整后预计库存', quantity(stock.projected_after_adjustment, unit))}${metric('安全库存', quantity(stock.safety_stock, unit))}</div>
      <dl class="details-grid">${row('原付款日', text(p.baseline_payment_date))}${row('方案付款日', text(p.scenario_payment_date))}${row('本次调整对应金额', money(p.adjusted_amount))}${row('递延至后续的付款压力', money(p.deferred_payment_pressure))}</dl>`;
  }
  return `${body}<div class="cash-summary"><h3>现金影响单独核对</h3><dl class="details-grid">${row('已知现金影响', money(cash.known_cash_effect))}${row('预计净现金改善', money(cash.estimated_net_cash_improvement))}</dl>${cash.note ? `<p>${e(cash.note)}</p>` : ''}${cash.assumptions?.length ? list(cash.assumptions) : ''}${cash.missing_fields?.length ? panel('仍缺少计算依据', list(cash.missing_fields), 'is-warning') : ''}<p class="form-hint">未提供的金额保留为未提供。估算避免报损、库存成本与实际到账分别记录。</p></div>`;
}

export function proposalSummary(proposal) {
  const summary = proposal.approval_summary, payload = proposal.version?.payload;
  return `${summary?.detail ? `<p>${e(summary.detail)}</p>` : ''}${summary?.boundary ? `<p class="form-hint">${e(summary.boundary)}</p>` : ''}${payload?.calculation ? calculationSummary(payload.proposal_type, payload.calculation, payload.input) : ''}`;
}

export function workItemsMarkup(items) {
  if (!items.length) return panel('暂无待评估事项', '<p>当前服务未返回待评估建议，可刷新核对最新范围。</p>');
  return `<section class="result-card"><h2>需要评估的门店事项</h2><p class="form-hint">按服务返回顺序展示。先核对依据与约束，再保存方案。</p><div class="work-list">${items.map(w => {
    const riskId = w.workbench_risk_id ?? w.risk_id;
    const hasRisk = Number.isSafeInteger(riskId) && riskId > 0;
    const action = hasRisk && MODULES.has(w.route) ? `<button type="button" class="secondary-button" data-action="open-workbench" data-module="${e(w.route)}" data-risk-id="${riskId}">${e(w.action_label || '评估方案')}</button>` : hasRisk && ['slow-diagnosis', 'slow_moving'].includes(w.route) ? `<button type="button" class="secondary-button" data-risk="${riskId}">核查门店情况</button>` : '<span class="form-hint">请在审批或执行分类中查看对应记录</span>';
    return `<article class="work-item" data-work-id="${e(w.id)}"><div><div class="work-item-meta"><span>${text(w.priority)}</span><span>${text(w.owner)}</span><span>${text(w.due_date)}</span></div><h3>${e(w.title || w.label || w.id)}</h3>${w.reason ? `<p>${e(w.reason)}</p>` : ''}${w.impact ? `<p class="form-hint">${e(w.impact)}</p>` : ''}</div><div>${action}</div></article>`;
  }).join('')}</div></section>`;
}

export function workflowStatus({dirty, draft, proposal}) {
  let label = '核对输入，计算可行方案';
  if (dirty || draft?.status === 'needs_recalculation') label = '输入已变化，需要重新计算';
  else if (draft?.status === 'blocked') label = '约束未通过，先调整输入';
  else if (draft?.status === 'calculated') label = '计算已完成，核对后保存方案版本';
  else if (proposal) label = `方案 V${proposal.current_version} · ${STATUS_LABELS[proposal.status] || proposal.status}`;
  return `<div class="workflow-status" role="status"><span>当前进度</span><strong>${e(label)}</strong><small>计算 → 保存版本 → 人工审批 → 执行跟进与回执</small></div>`;
}

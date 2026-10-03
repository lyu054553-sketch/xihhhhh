import { escapeHtml as e } from './retail-view.mjs';

const MODULE_LABELS = { transfer: '跨店调拨', 'expiry-rescue': '近效期处置', 'procurement-brake': '采购刹车' };
const TABS = new Set(['actions', 'pending', 'followup', 'completed', 'drafts']);
const COMPLETED = new Set(['received', 'completed']);
const DRAFTS = new Set(['draft', 'needs_replan', 'replan_pending', 'invalidated']);
const REASONS = {
  missing_identity: '任务缺少有效的方案编号或版本，业务身份未知。',
  missing_proposal: '当前列表没有对应方案，业务身份未知。',
  duplicate_proposal: '对应方案编号重复，无法确定任务的业务身份。',
  tenant_mismatch: '任务与方案的租户不一致，无法关联业务身份。',
  version_mismatch: '任务关联旧版或其他版本，当前方案资料不能代替任务原版本。',
  invalid_version: '保存版本的关联不完整或不一致，业务身份未知。',
  risk_mismatch: '保存输入与方案的商品风险不一致，业务身份未知。',
  missing_details: '已关联对应版本，部分门店、商品或工作台资料未提供。',
};
const record = value => value != null && typeof value === 'object' && !Array.isArray(value);
const rows = value => Array.isArray(value) ? value.filter(record) : [];
const text = value => typeof value === 'string' && value.trim() ? value : null;
const positiveInteger = value => Number.isSafeInteger(value) && value > 0;
const sameTenant = (left, right) => left.tenant_id == null || right.tenant_id == null || left.tenant_id === right.tenant_id;

/** Business names come only from the task's exact saved version, never a newer proposal. */
export function taskContext(task, proposals) {
  task = record(task) ? task : {};
  const context = {
    matched: false, reason: null, taskId: text(task.id), proposalId: text(task.proposal_id),
    proposalVersion: positiveInteger(task.proposal_version) ? task.proposal_version : null,
    product: null, sku: null, store: null, targetStore: null, moduleType: null, riskId: null,
  };
  const unavailable = reason => ({ ...context, reason });
  if (!context.proposalId || context.proposalVersion == null) return unavailable('missing_identity');
  const candidates = rows(proposals).filter(proposal => proposal.id === context.proposalId);
  if (!candidates.length) return unavailable('missing_proposal');
  if (candidates.length !== 1) return unavailable('duplicate_proposal');
  const proposal = candidates[0], version = proposal.version;
  if (!sameTenant(task, proposal)) return unavailable('tenant_mismatch');
  if (proposal.current_version !== context.proposalVersion) return unavailable('version_mismatch');
  if (!record(version) || version.version !== context.proposalVersion ||
      (version.proposal_id != null && version.proposal_id !== context.proposalId) || !record(version.payload)) {
    return unavailable('invalid_version');
  }
  const payload = version.payload, input = record(payload.input) ? payload.input : {};
  const basis = record(payload.basis) ? payload.basis : {};
  if ([input.risk_id, basis.risk_id].some(id => id != null && id !== proposal.risk_id)) return unavailable('risk_mismatch');
  if (basis.proposal_version != null && basis.proposal_version !== context.proposalVersion) return unavailable('invalid_version');
  const moduleType = Object.hasOwn(MODULE_LABELS, payload.proposal_type) ? payload.proposal_type : null;
  const result = {
    ...context, matched: true, product: text(input.product), sku: text(input.sku),
    store: text(input.store) || text(input.source_store),
    targetStore: moduleType === 'transfer' ? text(input.target_store) : null,
    moduleType, riskId: positiveInteger(proposal.risk_id) ? proposal.risk_id : null,
  };
  if (!result.product || !result.store || !result.moduleType) result.reason = 'missing_details';
  return result;
}

export function taskContextMarkup(context) {
  const fields = [['商品', context.product], ['门店', context.store], ['工作台', MODULE_LABELS[context.moduleType]]];
  if (context.targetStore) fields.push(['接收门店', context.targetStore]);
  return `<dl class="details-grid">${fields.map(([label, value]) => `<div><dt>${label}</dt><dd>${e(value || '未提供／待核对')}</dd></div>`).join('')}</dl>` +
    (context.reason ? `<p class="form-hint">${e(REASONS[context.reason] || '业务身份未能核对。')}</p>` : '');
}

function identityTerms(context) {
  return [context.product, context.sku, context.store, context.targetStore, context.proposalId, context.taskId];
}

/** Narrow the current tab locally; retain response ordering, statuses and amounts. */
export function filterQueue(data, { tab = 'pending', query = '' } = {}) {
  if (!TABS.has(tab)) throw new Error('未知待办分类');
  data = record(data) ? data : {};
  const allProposals = rows(data.proposals), allTasks = rows(data.tasks);
  const queryText = typeof query === 'string' ? query.trim() : '';
  const normalize = value => value.normalize('NFKC').toLocaleLowerCase();
  const tokens = normalize(queryText).split(/\s+/).filter(Boolean);
  const matches = values => {
    const haystack = normalize(values.filter(value => typeof value === 'string').join('\n'));
    return tokens.every(token => haystack.includes(token));
  };
  let work = [], proposals = [], tasks = [];
  if (tab === 'actions') work = rows(data.work).filter(item => !['approvals', 'execution'].includes(item.route));
  if (tab === 'pending') proposals = allProposals.filter(item => item.status === 'pending_approval');
  if (tab === 'followup') {
    // Only a task for this approved version replaces its task-creation entry.
    // Tasks for earlier versions do not represent a newly approved plan.
    proposals = allProposals.filter(item => item.status === 'approved' &&
      !allTasks.some(task => text(item.id) && task.proposal_id === item.id &&
        task.proposal_version === item.current_version && sameTenant(task, item)));
    tasks = allTasks.filter(item => !COMPLETED.has(item.status));
  }
  if (tab === 'completed') tasks = allTasks.filter(item => COMPLETED.has(item.status));
  if (tab === 'drafts') proposals = allProposals.filter(item => DRAFTS.has(item.status));
  const total = work.length + proposals.length + tasks.length;
  work = work.filter(item => matches([item.id, item.title, item.product, item.sku, item.store, item.store_name]));
  // Current proposal cards may display server summaries even when seed data has
  // no saved input. Keep those searchable without borrowing them for task history.
  proposals = proposals.filter(item => matches([
    item.id, item.approval_summary?.title, item.product, item.store, item.store_name,
    ...identityTerms(taskContext(
      { proposal_id: item.id, proposal_version: item.current_version, tenant_id: item.tenant_id }, allProposals)),
  ]));
  tasks = tasks.filter(item => matches(identityTerms(taskContext(item, allProposals))));
  return { tab, query: queryText, total, shown: work.length + proposals.length + tasks.length, work, proposals, tasks };
}

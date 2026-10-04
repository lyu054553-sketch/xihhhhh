import { escapeHtml as e, input, select, panel, labelFor } from './retail-view.mjs';

const DECISIONS = [['unknown', '待核实'], ['accepted', '采信这条情况'], ['excluded', '排除这条情况']];
const FACT_STATUS = { unknown: 'pending_confirmation', accepted: 'confirmed', excluded: 'rejected' };
const ROOT_FIELDS = new Set(['factors', 'current_status', 'date_interpretation', 'raw_text', 'source', 'evidence_refs', 'remediation_status']);
const DATE_FIELDS = new Set(['relative_date', 'relative_date_resolved', 'uncertain_ranges', 'needs_confirmation']);
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const text = value => typeof value === 'string' ? value : '';
const lines = value => [...new Set(text(value).split(/\r?\n/).map(line => line.trim()).filter(Boolean))];
const unknownFields = (value, known) => Object.fromEntries(Object.entries(value).filter(([key]) => !known.has(key)));

function context(feedback) {
  if (!object(feedback) || !text(feedback.id).trim()) throw new Error('反馈缺少有效编号，请重新读取。');
  if (typeof feedback.raw_text !== 'string') throw new Error('反馈缺少已留存的原文，请重新读取。');
  const confirmed = feedback.confirmation_status === 'confirmed';
  const document = confirmed && object(feedback.confirmed) ? feedback.confirmed : object(feedback.draft) ? feedback.draft : {};
  const factors = Array.isArray(document.factors) ? document.factors.flatMap((factor, index) => object(factor) && text(factor.label).trim() ? [{ factor, index }] : []) : [];
  const dates = object(document.date_interpretation) ? document.date_interpretation : {};
  const ranges = Array.isArray(dates.uncertain_ranges) ? dates.uncertain_ranges.flatMap((range, index) => object(range) ? [{ range, index }] : []) : [];
  const hasRelative = Boolean(text(dates.relative_date).trim() || text(dates.relative_date_resolved).trim());
  return { document, factors, dates, ranges, hasRelative, confirmed };
}

function decision(value, label) {
  if (!Object.hasOwn(FACT_STATUS, value)) throw new Error(`请选择${label}的处理方式。`);
  return value;
}

function date(value, label) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) || Number(value.slice(0, 4)) < 1) throw new Error(`${label}需要有效日期。`);
  const parsed = new Date(`${value}T00:00:00Z`);
  if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value) throw new Error(`${label}需要有效日期。`);
  return value;
}

/** Flat values match FormData names so the page can retain edits without JSON editing. */
export function createFeedbackReview(feedback) {
  const { document, factors, dates, ranges, hasRelative, confirmed } = context(feedback);
  const review = {
    feedback_id: feedback.id,
    current_status: confirmed ? text(document.current_status) : '',
    remediation_status: confirmed && document.remediation_status === 'done' ? 'done' : 'unknown',
    evidence_refs: confirmed && Array.isArray(document.evidence_refs) ? document.evidence_refs.filter(value => typeof value === 'string').join('\n') : '',
    additional_factors: '',
    date_status: confirmed && dates.needs_confirmation === false ? (hasRelative || ranges.length ? 'accepted' : 'excluded') : 'unknown',
    relative_date_resolved: text(dates.relative_date_resolved),
  };
  for (const { factor, index } of factors) {
    review[`factor_${index}_label`] = factor.label;
    review[`factor_${index}_status`] = confirmed && factor.confirmation_status === 'confirmed' ? 'accepted' : confirmed && factor.confirmation_status === 'rejected' ? 'excluded' : 'unknown';
  }
  for (const { range, index } of ranges) {
    review[`range_${index}_start`] = text(range.start);
    review[`range_${index}_end`] = text(range.end);
  }
  return review;
}

/** Return only v1.2's existing confirmation fields; approval is checked by the form owner. */
export function buildFeedbackConfirmation(review, feedback) {
  const { factors, dates, ranges, hasRelative } = context(feedback);
  if (!object(review) || review.feedback_id !== feedback.id) throw new Error('核对内容不属于当前反馈，请重新读取。');
  const outputFactors = factors.map(({ index }) => {
    const label = text(review[`factor_${index}_label`]).trim();
    if (!label) throw new Error(`第 ${index + 1} 条情况不能为空；不采信时请选择排除。`);
    const status = decision(review[`factor_${index}_status`], `第 ${index + 1} 条情况`);
    return { label, causal_status: 'unknown', confirmation_status: FACT_STATUS[status] };
  });
  for (const label of lines(review.additional_factors)) {
    if (outputFactors.some(factor => factor.label === label)) throw new Error('补充情况与上方核对项重复，请直接修改上方处理方式。');
    outputFactors.push({ label, causal_status: 'unknown', confirmation_status: 'confirmed' });
  }

  const dateStatus = decision(review.date_status, '日期');
  const dateInterpretation = {
    relative_date: dateStatus === 'excluded' ? null : text(dates.relative_date) || null,
    relative_date_resolved: null,
    uncertain_ranges: [],
    needs_confirmation: dateStatus === 'unknown',
  };
  if (dateStatus === 'accepted') {
    if (!hasRelative && !ranges.length) throw new Error('草稿没有可核对的日期，请保留待核实并在现况中补充说明。');
    if (hasRelative) dateInterpretation.relative_date_resolved = date(review.relative_date_resolved, '相对日期对应的日期');
    dateInterpretation.uncertain_ranges = ranges.map(({ range, index }) => {
      const start = date(review[`range_${index}_start`], `第 ${index + 1} 个日期范围的开始日期`);
      const end = date(review[`range_${index}_end`], `第 ${index + 1} 个日期范围的结束日期`);
      if (start > end) throw new Error(`第 ${index + 1} 个日期范围的开始日期不能晚于结束日期。`);
      return { label: text(range.label), start, end };
    });
  }
  if (!['unknown', 'done'].includes(review.remediation_status)) throw new Error('请选择处理情况是否已核实。');
  return {
    factors: outputFactors,
    current_status: text(review.current_status).trim() || null,
    date_interpretation: dateInterpretation,
    raw_text: feedback.raw_text,
    source: '负责人输入',
    evidence_refs: lines(review.evidence_refs),
    remediation_status: review.remediation_status,
  };
}

function readonly(value) {
  if (value == null) return '<span class="muted">未提供</span>';
  if (Array.isArray(value)) return `<ul class="detail-list">${value.map(item => `<li>${readonly(item)}</li>`).join('')}</ul>`;
  if (object(value)) return `<dl class="details-grid">${Object.entries(value).map(([key, item]) => `<div><dt>${e(labelFor(key))}</dt><dd>${readonly(item)}</dd></div>`).join('')}</dl>`;
  return e(value);
}

function unreviewedDetails(document) {
  const other = unknownFields(document, ROOT_FIELDS);
  if (Array.isArray(document.factors)) {
    const extras = document.factors.flatMap((factor, index) => {
      if (!object(factor) || !text(factor.label).trim()) return [{ item: index + 1, value: factor }];
      const fields = unknownFields(factor, new Set(['label', 'causal_status', 'confirmation_status']));
      return Object.keys(fields).length ? [{ item: index + 1, ...fields }] : [];
    });
    if (extras.length) other.factors = extras;
  } else if (document.factors != null) other.factors = document.factors;
  if (object(document.date_interpretation)) {
    const fields = unknownFields(document.date_interpretation, DATE_FIELDS);
    const extraRanges = Array.isArray(document.date_interpretation.uncertain_ranges) ? document.date_interpretation.uncertain_ranges.flatMap((range, index) => {
      if (!object(range)) return [{ item: index + 1, value: range }];
      const extra = unknownFields(range, new Set(['label', 'start', 'end']));
      return Object.keys(extra).length ? [{ item: index + 1, ...extra }] : [];
    }) : [];
    if (extraRanges.length) fields.uncertain_ranges = extraRanges;
    if (Object.keys(fields).length) other.date_interpretation = fields;
  }
  return Object.keys(other).length ? `<details><summary>其他返回信息（仅供查看，不随本次确认提交）</summary>${readonly(other)}</details>` : '';
}

export function renderFeedbackReview(feedback, review = createFeedbackReview(feedback)) {
  const { document, factors, dates, ranges, hasRelative, confirmed } = context(feedback);
  const hasDates = hasRelative || ranges.length > 0;
  const originalFactors = Array.isArray(feedback.draft?.factors) ? feedback.draft.factors : [];
  const factorFields = factors.map(({ factor, index }) => `<div class="form-section"><p class="form-hint">原草稿：${e(text(originalFactors[index]?.label) || factor.label)}</p><div class="form-grid">${input(`factor_${index}_label`, `第 ${index + 1} 条情况（可更正）`, review[`factor_${index}_label`], { type: 'text' })}${select(`factor_${index}_status`, '人工核对结论', DECISIONS, review[`factor_${index}_status`])}</div></div>`).join('');
  const dateFields = hasDates ? `${select('date_status', '日期核对结论', [['unknown', '待核实，暂不采用草稿日期'], ['accepted', '采信下列日期或范围'], ['excluded', '排除草稿日期']], review.date_status)}<p class="form-hint">只核对后端已给出的日期；“上个月”等模糊范围仍保留为范围，不改成某一天。</p>${hasRelative ? `<p>原文日期表达：${e(text(dates.relative_date) || '未提供')}</p>${input('relative_date_resolved', '对应日期（仅采信时提交）', review.relative_date_resolved, { type: 'date', required: false })}` : ''}${ranges.map(({ range, index }) => `<p>日期范围：${e(text(range.label) || `第 ${index + 1} 项`)}</p><div class="form-grid">${input(`range_${index}_start`, '开始日期（仅采信时提交）', review[`range_${index}_start`], { type: 'date', required: false })}${input(`range_${index}_end`, '结束日期（仅采信时提交）', review[`range_${index}_end`], { type: 'date', required: false })}</div>`).join('')}` : '<p class="form-hint">草稿没有可核对的日期。保留待核实，不推断发生时间。</p><input type="hidden" name="date_status" value="unknown">';
  return `<form id="feedback-confirm-form"><fieldset ${confirmed ? 'disabled' : ''}><input type="hidden" name="feedback_id" value="${e(feedback.id)}"><h3>留存原文</h3><p class="form-hint">草稿标注来源：${e(text(document.source) || '未标注')}。以下操作由人员核对，不表示已完成模型分析。</p><label class="field"><span>原始反馈（只读）</span><textarea rows="3" readonly>${e(feedback.raw_text)}</textarea></label>
    ${feedback.draft?.raw_text != null && feedback.draft.raw_text !== feedback.raw_text ? panel('草稿原文与留存记录不一致', '<p>请以此处留存原文为准；确认不会改写原始反馈。</p>', 'is-warning') : ''}
    <h3>逐条核对情况</h3><p>采信一条情况不代表已证明它造成滞销。草稿未核实的内容默认保留为待核实。</p>${factorFields || '<p class="form-hint">没有可逐条核对的草稿情况，可在下方补充已核实事实。</p>'}
    <label class="field"><span>其他已核实情况（一行一条，不代表因果）</span><textarea name="additional_factors" rows="3">${e(review.additional_factors)}</textarea></label>
    <h3>现况与处理</h3>${document.current_status ? `<p class="form-hint">返回的现况描述（请自行核实）：${e(document.current_status)}</p>` : ''}<label class="field"><span>核实后的现况与补充说明</span><textarea name="current_status" rows="3" placeholder="未核实可留空；不要把草稿猜测当作事实。">${e(review.current_status)}</textarea></label>${select('remediation_status', '处理情况', [['unknown', '尚未核实是否处理'], ['done', '已核实完成处理，仍需观察效果']], review.remediation_status)}
    <h3>发生时间</h3>${dateFields}
    <h3>证据来源</h3>${Array.isArray(document.evidence_refs) && document.evidence_refs.length ? `<details><summary>草稿提供的证据引用（仅供核对）</summary>${readonly(document.evidence_refs)}</details>` : '<p class="form-hint">草稿未提供证据引用。</p>'}<label class="field"><span>已核对的证据引用或来源（一行一条）</span><textarea name="evidence_refs" rows="3" placeholder="例如门店记录编号、照片编号或相关负责人说明。">${e(review.evidence_refs)}</textarea></label>
    ${unreviewedDetails(document)}${confirmed ? '<p>这份反馈已经确认；以下内容为已保存记录。</p>' : '<label class="checkbox-field"><input name="reviewed" type="checkbox" required>我已核对原文、情况、日期与证据；保留了尚不确定的信息</label><div class="form-actions"><button class="primary-button">确认人工核查结果</button></div>'}</fieldset></form>`;
}

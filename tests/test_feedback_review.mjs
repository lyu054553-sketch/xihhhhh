import test from 'node:test';
import assert from 'node:assert/strict';
import { createFeedbackReview, buildFeedbackConfirmation, renderFeedbackReview } from '../assets/js/feedback-review.mjs';

function feedback(raw = '不是没上架。昨天盘点仍有库存，上个月销量不清楚。') {
  return {
    id: 'FB-001', investigation_id: 'INV-001', raw_text: raw,
    confirmation_status: 'pending_confirmation', confirmed: null,
    draft: {
      factors: [{ label: '发生过未上架', causal_status: 'unknown', confirmation_status: '待确认' }],
      current_status: '已补上（待确认）', remediation_status: 'unknown',
      raw_text: raw, source: '负责人输入', evidence_refs: [],
      date_interpretation: { relative_date: '昨天', relative_date_resolved: '2026-10-02', uncertain_ranges: [{ label: '上个月', start: '2026-09-01', end: '2026-09-30' }], needs_confirmation: true },
    },
  };
}

test('fixed draft statements start untrusted, including negated source text', () => {
  const fb = feedback();
  const review = createFeedbackReview(fb);
  assert.equal(review.factor_0_status, 'unknown');
  assert.equal(review.current_status, '');
  assert.equal(review.remediation_status, 'unknown');
  assert.equal(review.date_status, 'unknown');
  const result = buildFeedbackConfirmation(review, fb);
  assert.equal(result.factors[0].confirmation_status, 'pending_confirmation');
  assert.equal(result.factors[0].causal_status, 'unknown');
  assert.equal(result.current_status, null);
  assert.equal(result.date_interpretation.relative_date_resolved, null);
  assert.deepEqual(result.date_interpretation.uncertain_ranges, []);
});

test('explicit exclusion preserves the rejected statement without turning it into a fact', () => {
  const fb = feedback();
  const result = buildFeedbackConfirmation({ ...createFeedbackReview(fb), factor_0_status: 'excluded' }, fb);
  assert.deepEqual(result.factors, [{ label: '发生过未上架', confirmation_status: 'rejected', causal_status: 'unknown' }]);
});

test('corrected and accepted observations do not assert causation', () => {
  const fb = feedback();
  const result = buildFeedbackConfirmation({ ...createFeedbackReview(fb), factor_0_label: '商品已上架，盘点仍有库存', factor_0_status: 'accepted' }, fb);
  assert.deepEqual(result.factors[0], { label: '商品已上架，盘点仍有库存', confirmation_status: 'confirmed', causal_status: 'unknown' });
});

test('additional human facts are separate confirmed observations, never model conclusions', () => {
  const fb = feedback();
  const result = buildFeedbackConfirmation({ ...createFeedbackReview(fb), additional_factors: '\n门店已核对货架照片\r\n销量记录尚缺 3 天\n门店已核对货架照片\n' }, fb);
  assert.deepEqual(result.factors.slice(1), [
    { label: '门店已核对货架照片', confirmation_status: 'confirmed', causal_status: 'unknown' },
    { label: '销量记录尚缺 3 天', confirmation_status: 'confirmed', causal_status: 'unknown' },
  ]);
  assert.equal(result.source, '负责人输入');
});

test('duplicate additions do not override an existing unknown or rejected decision', () => {
  const fb = feedback();
  const review = { ...createFeedbackReview(fb), factor_0_status: 'excluded', additional_factors: '发生过未上架' };
  assert.throws(() => buildFeedbackConfirmation(review, fb), /重复/);
});

test('source text comes only from the saved feedback, including exact spacing', () => {
  const fb = feedback('  原始反馈\n不是缺货。  ');
  fb.draft.raw_text = '被草稿改写的原文';
  const review = { ...createFeedbackReview(fb), raw_text: '被表单改写', source: '模型断言' };
  const result = buildFeedbackConfirmation(review, fb);
  assert.equal(result.raw_text, '  原始反馈\n不是缺货。  ');
  assert.equal(result.source, '负责人输入');
  assert.match(renderFeedbackReview(fb, review), /草稿原文与留存记录不一致/);
});

test('human status and notes stay separate from the untouched original', () => {
  const fb = feedback();
  const result = buildFeedbackConfirmation({ ...createFeedbackReview(fb), current_status: '  已核对货架；补充说明：需观察下周销量。  ', remediation_status: 'done' }, fb);
  assert.equal(result.current_status, '已核对货架；补充说明：需观察下周销量。');
  assert.equal(result.remediation_status, 'done');
  assert.equal(result.raw_text, fb.raw_text);
});

test('unverified current conditions and evidence stay unknown or empty', () => {
  const fb = feedback();
  fb.draft.evidence_refs = ['尚未核对的图片'];
  const review = createFeedbackReview(fb);
  assert.equal(review.evidence_refs, '');
  const result = buildFeedbackConfirmation(review, fb);
  assert.equal(result.current_status, null);
  assert.deepEqual(result.evidence_refs, []);
  assert.equal(result.remediation_status, 'unknown');
});

test('explicitly supplied evidence is retained as references, without inventing attachments', () => {
  const fb = feedback();
  const result = buildFeedbackConfirmation({ ...createFeedbackReview(fb), evidence_refs: ' 图片编号 P-001\n负责人说明 R-002\r\n图片编号 P-001\n' }, fb);
  assert.deepEqual(result.evidence_refs, ['图片编号 P-001', '负责人说明 R-002']);
});

test('date acceptance validates dates while preserving uncertain month ranges', () => {
  const fb = feedback();
  const review = { ...createFeedbackReview(fb), date_status: 'accepted' };
  assert.deepEqual(buildFeedbackConfirmation(review, fb).date_interpretation, {
    relative_date: '昨天', relative_date_resolved: '2026-10-02',
    uncertain_ranges: [{ label: '上个月', start: '2026-09-01', end: '2026-09-30' }], needs_confirmation: false,
  });
  review.relative_date_resolved = '2026-10-01';
  assert.equal(buildFeedbackConfirmation(review, fb).date_interpretation.relative_date_resolved, '2026-10-01');
});

test('unknown and excluded dates do not transmit a proposed exact time', () => {
  const fb = feedback();
  const review = { ...createFeedbackReview(fb), relative_date_resolved: 'invalid' };
  const unknown = buildFeedbackConfirmation(review, fb).date_interpretation;
  assert.equal(unknown.relative_date_resolved, null);
  assert.equal(unknown.needs_confirmation, true);
  assert.deepEqual(buildFeedbackConfirmation({ ...review, date_status: 'excluded' }, fb).date_interpretation, {
    relative_date: null, relative_date_resolved: null, uncertain_ranges: [], needs_confirmation: false,
  });
});

test('accepted malformed dates and reversed ranges fail before submission', () => {
  const fb = feedback();
  const base = { ...createFeedbackReview(fb), date_status: 'accepted' };
  for (const value of ['', '昨天', '2026-02-29', '2026-13-01', '2026-09-31', '2026-10-02T08:00:00Z', '0000-01-01', null, 0]) {
    assert.throws(() => buildFeedbackConfirmation({ ...base, relative_date_resolved: value }, fb), /有效日期/);
  }
  assert.throws(() => buildFeedbackConfirmation({ ...base, range_0_start: '2026-10-01', range_0_end: '2026-09-30' }, fb), /不能晚于/);
});

test('dates absent from the draft are not synthesized from the client clock or form extras', () => {
  const fb = feedback('时间不清楚。');
  fb.draft.date_interpretation = { relative_date: null, relative_date_resolved: null, uncertain_ranges: [], needs_confirmation: true };
  const review = createFeedbackReview(fb);
  assert.equal(buildFeedbackConfirmation({ ...review, relative_date_resolved: '2026-10-02' }, fb).date_interpretation.relative_date_resolved, null);
  assert.throws(() => buildFeedbackConfirmation({ ...review, date_status: 'accepted', relative_date_resolved: '2026-10-02' }, fb), /没有可核对的日期/);
});

test('feedback identity guards against confirming another row after navigation', () => {
  const fb = feedback();
  assert.throws(() => buildFeedbackConfirmation({ ...createFeedbackReview(fb), feedback_id: 'FB-other' }, fb), /不属于当前反馈/);
  assert.throws(() => createFeedbackReview({ ...fb, raw_text: null }), /留存的原文/);
  assert.throws(() => createFeedbackReview({ ...fb, id: '' }), /有效编号/);
});

test('incomplete edits and unsupported decisions cannot silently become confirmation', () => {
  const fb = feedback();
  const base = createFeedbackReview(fb);
  for (const change of [{ factor_0_label: '' }, { factor_0_status: 'yes' }, { date_status: 'yes' }, { remediation_status: 'fixed' }]) {
    assert.throws(() => buildFeedbackConfirmation({ ...base, ...change }, fb));
  }
});

test('unknown extra fields are visible read-only and never blindly confirmed', () => {
  const fb = feedback();
  fb.draft.ai_guess = { amount: '<script>alert(1)</script>', quantity: 0 };
  fb.draft.factors[0].model_reasoning = '未经核实的推断';
  fb.draft.date_interpretation.confidence = 0.8;
  fb.draft.date_interpretation.uncertain_ranges[0].estimated_days = 20;
  const review = { ...createFeedbackReview(fb), date_status: 'accepted', ai_guess: { malicious: true } };
  const result = buildFeedbackConfirmation(review, fb);
  assert.deepEqual(Object.keys(result).sort(), ['factors', 'current_status', 'date_interpretation', 'raw_text', 'source', 'evidence_refs', 'remediation_status'].sort());
  assert.equal(result.factors[0].model_reasoning, undefined);
  assert.equal(result.date_interpretation.confidence, undefined);
  assert.equal(result.date_interpretation.uncertain_ranges[0].estimated_days, undefined);
  const html = renderFeedbackReview(fb, review);
  assert.match(html, /其他返回信息/);
  assert.match(html, /未经核实的推断/);
  assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /<dd>0<\/dd>/);
});

test('all user and server text is escaped at form and read-only boundaries', () => {
  const attack = '</textarea><img src=x onerror="alert(1)"><script>alert(1)</script>';
  const fb = feedback(attack);
  fb.draft.factors[0].label = attack;
  fb.draft.source = attack;
  const review = { ...createFeedbackReview(fb), current_status: attack, additional_factors: attack, evidence_refs: attack };
  const html = renderFeedbackReview(fb, review);
  assert.doesNotMatch(html, /<img|<script|value="[^"<>]*<|<textarea[^>]*>[^<]*<img/);
  assert.match(html, /&lt;\/textarea&gt;/);
  assert.match(html, /&quot;alert\(1\)&quot;/);
});

test('business form supplies editable labels, explicit review checkbox and no JSON editor', () => {
  const fb = feedback();
  const html = renderFeedbackReview(fb, createFeedbackReview(fb));
  assert.match(html, /<form id="feedback-confirm-form">/);
  assert.match(html, /name="factor_0_label"/);
  assert.match(html, /name="factor_0_status"/);
  assert.match(html, /name="additional_factors"/);
  assert.match(html, /name="reviewed" type="checkbox" required/);
  assert.doesNotMatch(html, /confirmed_json|name="raw_text"|\bchecked\b/);
  assert.match(html, /<textarea rows="3" readonly>/);
});

test('confirmed records hydrate their saved human decisions and render disabled', () => {
  const fb = feedback();
  fb.confirmed = buildFeedbackConfirmation({ ...createFeedbackReview(fb), factor_0_status: 'excluded', current_status: '已核对', additional_factors: '陈列正常', date_status: 'excluded', evidence_refs: 'P-001', remediation_status: 'done' }, fb);
  fb.confirmation_status = 'confirmed';
  const review = createFeedbackReview(fb);
  assert.equal(review.factor_0_status, 'excluded');
  assert.equal(review.factor_1_status, 'accepted');
  assert.equal(review.current_status, '已核对');
  assert.equal(review.remediation_status, 'done');
  assert.equal(review.date_status, 'excluded');
  const html = renderFeedbackReview(fb, review);
  assert.match(html, /<fieldset disabled>/);
  assert.doesNotMatch(html, /name="reviewed"|确认人工核查结果/);
});

test('confirmation builders do not mutate source responses or retained review values', () => {
  const fb = feedback();
  const review = createFeedbackReview(fb);
  const before = structuredClone({ fb, review });
  buildFeedbackConfirmation(review, fb);
  renderFeedbackReview(fb, review);
  assert.deepEqual({ fb, review }, before);
});

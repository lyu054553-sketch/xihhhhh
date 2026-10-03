import assert from 'node:assert/strict';
import test from 'node:test';
import { createTaskReceipts } from '../assets/js/task-receipts.mjs';

const task = (changes = {}) => ({ id: 'TASK-1', proposal_id: 'PROP-1', proposal_version: 1, status: 'draft_pending_external_execution', metadata: {}, ...changes });

test('new execution drafts require an explicit human progress choice', () => {
  const drafts = createTaskReceipts(), original = task();
  assert.deepEqual(drafts.restore(original), { input: { status: '', receipt_ref: '' }, dirty: false, conflict: false });
  drafts.capture(original, { status: '', receipt_ref: 'REF' });
  assert.throws(() => drafts.prepare(original), /明确选择/);
});

test('task edits are isolated and retain only the two editable receipt fields', () => {
  const drafts = createTaskReceipts(), first = task(), second = task({ id: 'TASK-2' });
  drafts.capture(first, { status: 'in_transit', receipt_ref: 'R-1', proposal_id: 'WRONG', actual_cash: 999 });
  drafts.capture(second, { status: 'exception', receipt_ref: 'R-2' });
  assert.deepEqual(drafts.restore(first).input, { status: 'in_transit', receipt_ref: 'R-1' });
  drafts.discard(second.id);
  assert.equal(drafts.restore(first).dirty, true);
  assert.equal(drafts.restore(second).dirty, false);
  assert.equal(drafts.hasAny(), true);
  assert.deepEqual(first, task());
});

test('reverting to the saved values removes the unsaved edit', () => {
  const drafts = createTaskReceipts(), original = task({ status: 'in_transit', metadata: { receipt_ref: 'OLD' } });
  drafts.capture(original, { status: 'completed', receipt_ref: 'NEW' });
  drafts.capture(original, { status: 'in_transit', receipt_ref: 'OLD' });
  assert.equal(drafts.hasAny(), false);
});

test('status, receipt and proposal version changes require explicit reconciliation', () => {
  for (const change of [{ status: 'exception' }, { metadata: { receipt_ref: 'REMOTE' } }, { proposal_id: 'OTHER' }, { proposal_version: 2 }]) {
    const drafts = createTaskReceipts(), original = task();
    drafts.capture(original, { status: 'completed', receipt_ref: 'LOCAL' });
    const latest = { ...original, ...change };
    assert.equal(drafts.restore(latest).conflict, true);
    assert.equal(drafts.restore(latest).input.receipt_ref, 'LOCAL');
    assert.throws(() => drafts.prepare(latest), /已变化/);
    drafts.capture(latest, { status: 'completed', receipt_ref: 'LOCAL-EDITED' });
    assert.equal(drafts.restore(latest).conflict, true, 'typing must not silently rebase the old draft');
  }
});

test('unrelated server metadata updates do not overwrite editable values', () => {
  const drafts = createTaskReceipts(), original = task();
  drafts.capture(original, { status: 'exception', receipt_ref: 'LOCAL' });
  const latest = task({ metadata: { external_write: false, note: 'new server fact' } });
  assert.equal(drafts.restore(latest).conflict, false);
  assert.deepEqual(drafts.prepare(latest).input, { status: 'exception', receipt_ref: 'LOCAL' });
});

test('received and completed require nonblank references; existing references cannot be cleared', () => {
  const drafts = createTaskReceipts();
  for (const status of ['received', 'completed']) {
    drafts.capture(task(), { status, receipt_ref: '   ' });
    assert.throws(() => drafts.prepare(task()), /回执号/);
    drafts.discard('TASK-1');
  }
  const original = task({ status: 'in_transit', metadata: { receipt_ref: 'EXISTING' } });
  drafts.capture(original, { status: 'exception', receipt_ref: '' });
  assert.throws(() => drafts.prepare(original), /不支持清空/);
});

test('a matched acknowledgement clears only the acknowledged task, with normalized reference', () => {
  const drafts = createTaskReceipts(), original = task();
  drafts.capture(original, { status: 'completed', receipt_ref: '  RECEIPT-1  ' });
  drafts.capture(task({ id: 'TASK-2' }), { status: 'exception', receipt_ref: '' });
  const submission = drafts.prepare(original);
  assert.equal(submission.input.receipt_ref, 'RECEIPT-1');
  drafts.accept(task({ status: 'completed', metadata: { receipt_ref: 'RECEIPT-1' } }), submission);
  assert.equal(drafts.restore(original).dirty, false);
  assert.equal(drafts.list()[0].id, 'TASK-2');
});

test('mismatched acknowledgement never discards the local draft', () => {
  for (const change of [{ id: 'OTHER' }, { proposal_id: 'OTHER' }, { proposal_version: 2 }, { status: 'exception' }, { metadata: { receipt_ref: 'OTHER' } }]) {
    const drafts = createTaskReceipts(), original = task();
    drafts.capture(original, { status: 'completed', receipt_ref: 'R' });
    const submission = drafts.prepare(original);
    assert.throws(() => drafts.accept(task({ status: 'completed', metadata: { receipt_ref: 'R' }, ...change }), submission));
    assert.equal(drafts.restore(original).input.receipt_ref, 'R');
    assert.equal(drafts.hasAny(), true);
  }
});

test('an acknowledgement cannot clear edits made after submission', () => {
  const drafts = createTaskReceipts(), original = task();
  drafts.capture(original, { status: 'completed', receipt_ref: 'FIRST' });
  const submission = drafts.prepare(original);
  drafts.capture(original, { status: 'exception', receipt_ref: 'SECOND' });
  drafts.accept(task({ status: 'completed', metadata: { receipt_ref: 'FIRST' } }), submission);
  assert.equal(drafts.restore(original).input.receipt_ref, 'SECOND');
});

test('returned draft values do not expose mutable cache objects', () => {
  const drafts = createTaskReceipts(), original = task();
  drafts.capture(original, { status: 'exception', receipt_ref: 'R' });
  drafts.list()[0].input.receipt_ref = 'MUTATED';
  drafts.restore(original).input.status = 'completed';
  assert.deepEqual(drafts.restore(original).input, { status: 'exception', receipt_ref: 'R' });
});

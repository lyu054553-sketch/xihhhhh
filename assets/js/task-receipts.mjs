import { validateExecutionTask } from './retail-contract.mjs';

export const RECEIPT_STATUSES = [
  ['pending_dispatch', '待发出'], ['in_transit', '运输中'],
  ['awaiting_receipt', '待回执'], ['received', '已收货'],
  ['completed', '已完成'], ['exception', '异常'],
];
const writable = new Set(RECEIPT_STATUSES.map(([value]) => value));

function identity(task) {
  validateExecutionTask(task);
  return { id: task.id, proposal_id: task.proposal_id, proposal_version: task.proposal_version };
}
function snapshot(task) {
  return { ...identity(task), status: task.status, receipt_ref: task.metadata?.receipt_ref ?? null };
}
function savedInput(task) {
  return { status: writable.has(task.status) ? task.status : '', receipt_ref: task.metadata?.receipt_ref ?? '' };
}
function input(values) {
  return { status: String(values.status ?? ''), receipt_ref: String(values.receipt_ref ?? '') };
}
const same = (left, right) => Object.keys(left).every(key => left[key] === right[key]);

export function createTaskReceipts() {
  const edits = new Map();
  return {
    capture(task, values) {
      const baseline = snapshot(task), value = input(values);
      if (same(value, savedInput(task))) edits.delete(task.id);
      else edits.set(task.id, { baseline: edits.get(task.id)?.baseline || baseline, input: value });
    },
    restore(task) {
      const latest = snapshot(task), entry = edits.get(task.id);
      return {
        input: { ...(entry?.input || savedInput(task)) },
        dirty: Boolean(entry),
        conflict: Boolean(entry && !same(entry.baseline, latest)),
      };
    },
    prepare(task) {
      const draft = this.restore(task);
      if (draft.conflict) throw new Error('此任务的服务端状态、回执或关联版本已变化。请核对最新记录，放弃本地编辑后再填写。');
      if (!draft.dirty) throw new Error('当前没有需要保存的人工回执编辑。');
      if (!writable.has(draft.input.status)) throw new Error('请明确选择实际执行进度。');
      const receipt = draft.input.receipt_ref.trim();
      if (['received', 'completed'].includes(draft.input.status) && !receipt) throw new Error('已收货或已完成必须填写实际执行回执号。');
      if (task.metadata?.receipt_ref && !receipt) throw new Error('当前接口不支持清空已保存的回执号，请保留或更正编号。');
      return { baseline: snapshot(task), input: { status: draft.input.status, receipt_ref: receipt || null } };
    },
    accept(task, submission) {
      const expected = submission.baseline;
      validateExecutionTask(task, { proposalId: expected.proposal_id, version: expected.proposal_version });
      if (task.id !== expected.id || task.status !== submission.input.status ||
          (task.metadata?.receipt_ref ?? null) !== submission.input.receipt_ref) {
        throw new Error('保存回执与本次任务或输入不一致，本地编辑继续保留，请刷新核对。');
      }
      const entry = edits.get(task.id);
      if (entry && entry.input.status === submission.input.status &&
          (entry.input.receipt_ref.trim() || null) === submission.input.receipt_ref && same(entry.baseline, expected)) {
        edits.delete(task.id);
      }
      return task;
    },
    discard(taskId) { edits.delete(taskId); },
    hasAny() { return edits.size > 0; },
    list() { return [...edits].map(([id, entry]) => ({ id, input: { ...entry.input } })); },
  };
}

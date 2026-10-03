import assert from 'node:assert/strict';
import test from 'node:test';
import { createApiClient, ApiError } from '../assets/js/api-client.mjs';

const json = (body, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json' },
});

test('JSON responses preserve empty arrays and unknown amounts', async () => {
  const api = createApiClient({ fetchImpl: async () => json({ items: [], cash: null }) });
  assert.deepEqual(await api('/retail/simulate', { method: 'POST' }), { items: [], cash: null });
});

test('write requests preserve caller headers, body and method', async () => {
  let captured;
  const api = createApiClient({ baseUrl: '/api/v1', fetchImpl: async (url, options) => {
    captured = { url, options };
    return json({ decision_status: 'recorded' });
  } });
  const body = JSON.stringify({ item_id: 'ITEM-1', recommendation_id: 'REC-1', decision: 'approve' });
  await api('/proposals/PROP-1/approve', {
    method: 'POST', body, headers: { 'Idempotency-Key': 'proposal-v1-approve', 'X-Tenant-ID': 'demo' },
  });
  assert.equal(captured.url, '/api/v1/proposals/PROP-1/approve');
  assert.equal(captured.options.method, 'POST');
  assert.equal(captured.options.body, body);
  const headers = new Headers(captured.options.headers);
  assert.equal(headers.get('Idempotency-Key'), 'proposal-v1-approve');
  assert.equal(headers.get('X-Tenant-ID'), 'demo');
  assert.match(headers.get('Content-Type'), /application\/json/);
});

test('HTTP rejection retains actionable server detail', async () => {
  const api = createApiClient({ fetchImpl: async () => json({ detail: '数据版本不存在，不能计算' }, 400) });
  await assert.rejects(api('/retail/simulate', { method: 'POST' }), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 400);
    assert.match(error.message, /数据版本不存在/);
    assert.equal(error.outcomeUnknown, false);
    return true;
  });
});

test('Pydantic validation arrays render field errors rather than object strings', async () => {
  const api = createApiClient({ fetchImpl: async () => json({ detail: [
    { loc: ['body', 'horizon_days'], msg: 'Input should be greater than or equal to 1' },
    { loc: ['body', 'target'], msg: 'Field required' },
  ] }, 422) });
  await assert.rejects(api('/retail/simulate', { method: 'POST' }), (error) => {
    assert.equal(error.status, 422);
    assert.match(error.message, /greater than or equal to 1/);
    assert.match(error.message, /Field required/);
    assert.doesNotMatch(error.message, /\[object Object\]/);
    return true;
  });
});

test('malformed success JSON rejects and never fabricates a response', async () => {
  const api = createApiClient({ fetchImpl: async () => new Response('<html>proxy failure</html>', { status: 200 }) });
  await assert.rejects(api('/retail/simulate', { method: 'POST' }), ApiError);
});

test('malformed validation details retain their HTTP error instead of becoming network errors', async () => {
  const api = createApiClient({ fetchImpl: async () => json({ detail: [null, { loc: 'bad-location' }] }, 422) });
  await assert.rejects(api('/retail/simulate', { method: 'POST' }), (error) => error.status === 422 && error.code === 'http_error');
});

test('unexpected JSON envelopes cannot be treated as empty successful data', async () => {
  for (const payload of [null, [], 'ok', 0]) {
    const api = createApiClient({ fetchImpl: async () => json(payload) });
    await assert.rejects(api('/retail/simulate', { method: 'POST' }), ApiError);
  }
});

test('file preview without a service never attempts a write or invents success', async () => {
  let calls = 0;
  const api = createApiClient({ baseUrl: null, fetchImpl: async () => { calls++; return json({ ok: true }); } });
  await assert.rejects(api('/proposals/PROP-1/approve', { method: 'POST' }), ApiError);
  assert.equal(calls, 0);
});

test('network failure has one attempt and write outcome remains unknown', async () => {
  let calls = 0;
  const api = createApiClient({ fetchImpl: async () => { calls++; throw new TypeError('network disconnected'); } });
  await assert.rejects(api('/proposals/PROP-1/approve', { method: 'POST' }), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.outcomeUnknown, true);
    return true;
  });
  assert.equal(calls, 1, 'a write may already have committed: do not retry automatically');
});

test('read network failure does not imply an uncertain mutation', async () => {
  const api = createApiClient({ fetchImpl: async () => { throw new TypeError('offline'); } });
  await assert.rejects(api('/data-center'), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.outcomeUnknown, false);
    return true;
  });
});

test('timeout aborts request and a timed out write is not retried', async () => {
  let calls = 0;
  let capturedSignal;
  const api = createApiClient({ timeoutMs: 15, fetchImpl: (_url, { signal }) => {
    calls++;
    capturedSignal = signal;
    return new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
    });
  } });
  await assert.rejects(api('/retail/simulate', { method: 'POST' }), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.outcomeUnknown, true);
    return true;
  });
  assert.equal(capturedSignal.aborted, true);
  assert.equal(calls, 1);
});

test('server failure cannot turn a possibly committed write into safe retry', async () => {
  let calls = 0;
  const api = createApiClient({ fetchImpl: async () => { calls++; return json({ detail: 'Internal Server Error' }, 500); } });
  await assert.rejects(api('/proposals/PROP-1/approve', { method: 'POST' }), (error) => {
    assert.equal(error.status, 500);
    assert.equal(error.outcomeUnknown, true);
    return true;
  });
  assert.equal(calls, 1);
});

test('nested HTTP errors preserve code, retryability and field errors', async () => {
  const fieldErrors = [{ field: 'params.horizon_days', message: '周期无效' }];
  const api = createApiClient({ fetchImpl: async () => json({ error: {
    code: 'INVALID_REQUEST', message: '请修正模拟周期', retryable: false, field_errors: fieldErrors,
  } }, 422) });
  await assert.rejects(api('/retail/simulate', { method: 'POST' }), (error) => {
    assert.equal(error.code, 'INVALID_REQUEST');
    assert.equal(error.message, '请修正模拟周期');
    assert.equal(error.retryable, false);
    assert.deepEqual(error.fieldErrors, fieldErrors);
    assert.equal(error.outcomeUnknown, false);
    return true;
  });
});

test('standalone HTTP error objects are supported without automatic retry', async () => {
  let calls = 0;
  const api = createApiClient({ fetchImpl: async () => {
    calls++;
    return json({ code: 'AI_TIMEOUT', message: 'AI 分析超时', retryable: true, field_errors: [] }, 504);
  } });
  await assert.rejects(api('/retail/simulate', { method: 'POST' }), (error) => {
    assert.equal(error.code, 'AI_TIMEOUT');
    assert.equal(error.retryable, true);
    assert.equal(error.outcomeUnknown, true);
    return true;
  });
  assert.equal(calls, 1);
});

test('HTTP 200 business failure is returned for contract-aware state handling', async () => {
  const payload = { status: 'failed', error: { code: 'MODEL_OUTPUT_INVALID', message: '结构无效', retryable: true, field_errors: [] } };
  const api = createApiClient({ fetchImpl: async () => json(payload) });
  assert.deepEqual(await api('/retail/simulate', { method: 'POST' }), payload);
});

test('a server retry prohibition survives HTTP 500 normalization', async () => {
  const api = createApiClient({ fetchImpl: async () => json({ error: {
    code: 'INTERNAL_ERROR', message: '请人工检查', retryable: false, field_errors: [],
  } }, 500) });
  await assert.rejects(api('/proposals/PROP-1/approve', { method: 'POST' }), (error) => {
    assert.equal(error.retryable, false);
    assert.equal(error.outcomeUnknown, true);
    return true;
  });
});

test('caller cancellation aborts exactly one pending request', async () => {
  const controller = new AbortController();
  let calls = 0;
  const api = createApiClient({ fetchImpl: (_url, { signal }) => {
    calls++;
    return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true }));
  } });
  const pending = api('/retail/simulate', { method: 'POST', signal: controller.signal });
  controller.abort();
  await assert.rejects(pending, (error) => error.code === 'aborted' && error.outcomeUnknown && !error.retryable);
  assert.equal(calls, 1);
});

import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { buildDataCenterView, csvTemplate, sampleDownloadTarget, downloadSample, downloadTemplate } from '../assets/js/data-center.mjs';

const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' })[character]);
const money = (value) => `¥${value}`;
const view = (data, options = {}) => buildDataCenterView({ data, escapeHtml, money, ...options });
const schema = { label: '库存表', required: ['sku', 'store', 'inventory_qty'], description: '每行一条库存记录。' };
const receipt = (overrides = {}) => ({
  id: 'IMP-1', filename: '库存.csv', mode: 'erp_file', status: 'validated', created_at: '2026-10-02T08:00:00Z',
  summary: { data_kind: 'inventory', rows: 2, fields: ['sku', 'store', 'inventory_qty'], next_step: '当前快照不会被自动覆写。' }, errors: [], ...overrides,
});

test('empty responses never invent source dates, records, schemas or completed analysis', () => {
  for (const data of [null, {}, { sources: [], imports: [] }]) {
    const result = view(data);
    assert.equal(result.count, 0);
    assert.match(result.sourcesHtml, /尚无可展示的数据源/);
    assert.match(result.requirementsHtml, /字段契约尚未取得/);
    assert.match(result.historyHtml, /暂无导入记录/);
    assert.doesNotMatch(JSON.stringify(result), /2026|第二季度|已完成|上传成功|<code>/);
  }
});

test('real sources preserve actual zero totals and missing fields without creating history', () => {
  const result = view({ mode: 'real_inventory_snapshot', snapshot_id: 'snapshot-1', sources: [
    { name: '本地库存', status: '真实库存快照', last_snapshot: '2026-09-30', fields: ['库存数量'], missing_fields: ['销售历史'], summary: { rows: 0, stores: 0, skus: 0, cost_total: 0 } },
    { name: '第二数据源', fields: ['采购状态'] },
  ], imports: [] });
  assert.match(result.sourcesHtml, /本地库存/);
  assert.match(result.sourcesHtml, /第二数据源/);
  assert.match(result.sourcesHtml, /明细行：0/);
  assert.match(result.sourcesHtml, /库存成本：¥0/);
  assert.match(result.sourcesHtml, /缺少字段：销售历史/);
  assert.match(result.sourcesHtml, /snapshot-1/);
  assert.equal(result.count, 0);
});

test('sample source says synthetic replay and does not invent a business date', () => {
  const result = view({ mode: 'sample_replay', sources: [{ name: '当前分析快照（演示）', last_snapshot: 'snapshot-demo-v1', fields: ['库存'] }] });
  assert.match(result.sourcesHtml, /合成样例回放/);
  assert.match(result.sourcesHtml, /snapshot-demo-v1/);
  assert.doesNotMatch(result.sourcesHtml, /2026|已完成|50家/);
});

test('validated imports remain field checks and are shown even with a real snapshot', () => {
  const result = view({ mode: 'real_inventory_snapshot', sources: [{ name: '真实库存' }], import_schemas: { inventory: schema }, imports: [receipt()] });
  assert.equal(result.count, 1);
  assert.match(result.historyHtml, /库存\.csv/);
  assert.match(result.historyHtml, /仅字段校验通过/);
  assert.match(result.historyHtml, /不代表分析完成/);
  assert.match(result.historyHtml, /当前快照不会被自动覆写/);
  assert.doesNotMatch(result.historyHtml, /已完成|查看结果|真实库存/);
  assert.match(result.requirementsHtml, /<code>inventory_qty<\/code>/);
});

test('failed imports expose actual file and row errors', () => {
  const result = view({ imports: [receipt({ status: 'failed', errors: [{ row: 0, message: '缺少字段：store' }, { row: 4, message: '数量格式错误' }] })] });
  assert.match(result.historyHtml, /校验失败/);
  assert.match(result.historyHtml, /文件：缺少字段：store/);
  assert.match(result.historyHtml, /第 4 行：数量格式错误/);
  assert.match(result.historyHtml, /<details open>/);
  assert.doesNotMatch(result.historyHtml, /仅字段校验通过|analysis-status done/);
});

test('missing and unknown import statuses stay visible without success claims', () => {
  const result = view({ imports: [receipt({ filename: 'unknown.csv', status: 'processing', created_at: null, summary: {}, errors: [] })] });
  assert.match(result.historyHtml, /processing/);
  assert.match(result.historyHtml, /时间未提供/);
  assert.doesNotMatch(result.historyHtml, /刚刚|已完成|analysis-status done/);
});

test('search, filters and timestamp sort use only receipt data and keep input unchanged', () => {
  const items = [receipt({ id: 'older', filename: 'a.csv', created_at: '2026-10-02T10:00:00+08:00' }), receipt({ id: 'newer', filename: 'b.csv', status: 'failed', created_at: '2026-10-02T03:00:00Z' })];
  const before = JSON.stringify(items);
  const result = view({ imports: items });
  assert.ok(result.historyHtml.indexOf('b.csv') < result.historyHtml.indexOf('a.csv'));
  assert.equal(view({ imports: items }, { status: '校验失败' }).count, 1);
  assert.equal(view({ imports: items }, { status: 'validated' }).count, 1);
  assert.equal(view({ imports: items }, { search: 'B.CSV' }).count, 1);
  assert.match(view({ imports: items }, { search: 'absent' }).historyHtml, /没有匹配的导入记录/);
  assert.equal(JSON.stringify(items), before);
});

test('API strings are escaped in text, attributes and import errors', () => {
  const attack = '<img src=x onerror="alert(1)">';
  const data = {
    snapshot_id: attack,
    sources: [{ name: attack, status: attack, last_snapshot: attack, fields: [attack], missing_fields: [attack], summary: { rows: attack } }],
    import_schemas: { inventory: { label: attack, required: [attack], description: attack } },
    imports: [receipt({ id: attack, filename: attack, status: attack, created_at: attack, mode: attack, summary: { data_kind_label: attack, fields: [attack], rows: attack, next_step: attack, sheet_name: attack }, errors: [{ row: attack, message: attack }] })],
  };
  const result = view(data);
  for (const html of [result.sourcesHtml, result.requirementsHtml, result.historyHtml]) {
    assert.doesNotMatch(html, /<img/);
    assert.match(html, /&lt;img/);
    assert.doesNotMatch(html, /="alert\(1\)"/);
  }
});

test('CSV templates contain the exact server headers and BOM without a fake row', () => {
  assert.equal(csvTemplate(schema), '\uFEFFsku,store,inventory_qty\r\n');
  assert.equal(csvTemplate({ required: ['a,b', 'quote"field', 'line\nfield'] }), '\uFEFF"a,b","quote""field","line\nfield"\r\n');
  for (const invalid of [undefined, {}, { required: [] }, { required: [''] }, { required: [null] }]) {
    assert.throws(() => csvTemplate(invalid), /必填字段契约/);
  }
});

test('sample links use real manifest paths and reject traversal or remote paths', async () => {
  const manifest = JSON.parse(await readFile(new URL('../sample-data/manifest.json', import.meta.url), 'utf8'));
  assert.deepEqual(sampleDownloadTarget(manifest, 'inventory'), { href: 'sample-data/generated/inventory.csv', filename: 'inventory.csv' });
  for (const path of ['../app.js', '/app.js', '//evil.test/file', 'https://evil.test/file', 'generated/../../app.js', 'generated/.. /app.js', 'generated/%2e%2e/app.js', 'generated\\..\\app.js', 'generated/file.csv?redirect=x', 'generated/file.csv#x', 'generated/./file.csv', 'generated//file.csv', 'generated/file\u0000.csv']) {
    assert.throws(() => sampleDownloadTarget({ metadata: { is_sample: true }, files: { bad: { path } } }, 'bad'), /sample-data/);
  }
  assert.throws(() => sampleDownloadTarget({ metadata: { is_sample: false }, files: { inventory: { path: 'inventory.csv' } } }, 'inventory'), /合成数据文件清单/);
  assert.throws(() => sampleDownloadTarget(manifest, '__proto__'), /合成数据文件清单/);
});

test('downloads create real anchors and template URLs are released', async (t) => {
  const links = [];
  const originalDocument = globalThis.document;
  globalThis.document = { createElement: () => ({ click() { links.push({ href: this.href, download: this.download }); }, remove() {} }), body: { append() {} } };
  t.after(() => { if (originalDocument === undefined) delete globalThis.document; else globalThis.document = originalDocument; });
  let blob;
  const released = [];
  t.mock.method(URL, 'createObjectURL', (value) => { blob = value; return 'blob:template-test'; });
  t.mock.method(URL, 'revokeObjectURL', (href) => released.push(href));
  t.mock.method(globalThis, 'setTimeout', (callback) => { callback(); return 1; });
  downloadTemplate('inventory', schema);
  assert.equal(await blob.text(), 'sku,store,inventory_qty\r\n');
  assert.deepEqual(links[0], { href: 'blob:template-test', download: 'inventory-template.csv' });
  assert.deepEqual(released, ['blob:template-test']);
  downloadSample({ metadata: { is_sample: true }, files: { inventory: { path: 'generated/inventory.csv' } } }, 'inventory');
  assert.deepEqual(links[1], { href: 'sample-data/generated/inventory.csv', download: 'inventory.csv' });
});

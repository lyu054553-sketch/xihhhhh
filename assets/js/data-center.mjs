const IMPORT_STATUS = {
  validated: { label: '仅字段校验通过', className: 'done' },
  failed: { label: '校验失败', className: 'fix' },
  pending: { label: '待处理', className: 'fix' },
};

const list = (value) => Array.isArray(value) ? value : [];
const provided = (value) => value !== undefined && value !== null && value !== '';
const own = (object, key) => object && Object.hasOwn(object, key) ? object[key] : undefined;
const importStatus = (value) => own(IMPORT_STATUS, value) || { label: value || '状态未提供', className: 'fix' };
const timestamp = (value) => Number.isFinite(Date.parse(value)) ? Date.parse(value) : -Infinity;

/** Render source facts and import receipts; an import is never an analysis result. */
export function buildDataCenterView({
  data, search = '', status = '全部状态', sort = '按创建时间', kind = 'inventory', escapeHtml, money,
}) {
  const sources = list(data?.sources);
  const schemas = data?.import_schemas || {};
  const schema = own(schemas, kind);
  const sourcesHtml = sources.map((source) => {
    const summary = source.summary || {};
    const facts = [];
    if (provided(source.last_snapshot)) facts.push(`快照：${source.last_snapshot}`);
    if (provided(data?.snapshot_id) && data.snapshot_id !== source.last_snapshot) facts.push(`快照编号：${data.snapshot_id}`);
    if (provided(summary.stores)) facts.push(`门店数：${summary.stores}`);
    if (provided(summary.rows)) facts.push(`明细行：${summary.rows}`);
    if (provided(summary.skus)) facts.push(`SKU 数：${summary.skus}`);
    if (provided(summary.cost_total)) facts.push(`库存成本：${money(summary.cost_total)}`);
    const fields = list(source.fields);
    const missing = list(source.missing_fields);
    const sample = data?.mode === 'sample_replay';
    return `<section class="data-current-analysis">
      <div class="data-current-icon"><span class="material-symbols-rounded" aria-hidden="true">database</span></div>
      <div class="data-current-copy">
        <div class="data-current-title"><strong>${escapeHtml(source.name || '未命名数据源')}</strong><span class="status-pill">${escapeHtml(sample ? '合成样例回放' : source.status || '状态未提供')}</span></div>
        <p>${facts.length ? facts.map(escapeHtml).join(' <i></i> ') : '接口未提供快照时点与汇总信息。'}</p>
        <p>已提供字段：${fields.length ? escapeHtml(fields.join('、')) : '未提供'}</p>
        ${missing.length ? `<p>缺少字段：${escapeHtml(missing.join('、'))}</p>` : ''}
      </div>
      <div class="data-current-actions"><button class="secondary-action" type="button" data-go="overview">查看当前分析</button></div>
    </section>`;
  }).join('') || '<div class="empty-state">尚无可展示的数据源，请读取数据或检查接口状态。</div>';

  const requirementsHtml = schema
    ? `<strong>${escapeHtml(schema.label || kind)}需要的字段</strong><span>${list(schema.required).map((field) => `<code>${escapeHtml(field)}</code>`).join('') || '接口未提供必填字段'}</span><small>${escapeHtml(schema.description || '')}</small>`
    : '<strong>字段契约尚未取得</strong><small>请先读取数据来源，取得当前数据类型的导入字段要求。</small>';

  const query = String(search).trim().toLowerCase();
  const rows = list(data?.imports).filter((item) => {
    const matchesSearch = !query || [item.filename, item.id, item.summary?.data_kind_label]
      .some((value) => String(value || '').toLowerCase().includes(query));
    return matchesSearch && (status === '全部状态' || status === item.status || status === importStatus(item.status).label);
  });
  if (sort === '按创建时间') rows.sort((a, b) => timestamp(b.created_at) - timestamp(a.created_at));
  if (sort === '按文件名') rows.sort((a, b) => String(a.filename || '').localeCompare(String(b.filename || ''), 'zh-CN'));

  const historyHtml = rows.map((item) => {
    const summary = item.summary || {};
    const fields = list(summary.fields);
    const errors = list(item.errors);
    const state = importStatus(item.status);
    const kindLabel = summary.data_kind_label || own(schemas, summary.data_kind)?.label || summary.data_kind || '未提供';
    const errorHtml = errors.map((error) => `<li>${escapeHtml(provided(error.row) ? (Number(error.row) === 0 ? '文件' : `第 ${error.row} 行`) : '校验错误')}：${escapeHtml(error.message || '接口未提供错误详情')}</li>`).join('');
    return `<div class="analysis-history-row">
      <strong>${escapeHtml(item.filename || item.id || '未命名文件')}</strong>
      <span>${escapeHtml(kindLabel)}</span>
      <span title="${escapeHtml(fields.join('、'))}">${fields.length ? `${fields.length} 个字段` : '未提供'}</span>
      <span>${escapeHtml(provided(summary.rows) ? summary.rows : '未提供')}</span>
      <span>${escapeHtml(item.mode === 'erp_file' ? '文件导入' : item.mode || '未提供')}</span>
      <b class="analysis-status ${state.className}">${escapeHtml(state.label)}</b>
      <time>${escapeHtml(item.created_at || '时间未提供')}</time>
      <div class="analysis-history-actions"><details${errors.length ? ' open' : ''}><summary>校验详情</summary>
        ${provided(item.id) ? `<p>记录：${escapeHtml(item.id)}</p>` : ''}
        ${provided(summary.sheet_name) ? `<p>工作表：${escapeHtml(summary.sheet_name)}</p>` : ''}
        ${errorHtml ? `<ul>${errorHtml}</ul>` : ''}
        ${item.status === 'failed' && !errors.length ? '<p>接口未提供具体失败原因，请核对文件后重新校验。</p>' : ''}
        ${provided(summary.next_step) ? `<p>${escapeHtml(summary.next_step)}</p>` : ''}
        ${item.status === 'validated' ? '<p>字段校验不代表业务数据完整，也不代表分析完成。</p>' : ''}
      </details></div>
    </div>`;
  }).join('') || `<div class="empty-state">${list(data?.imports).length ? '没有匹配的导入记录。' : '暂无导入记录，选择文件后可校验字段并保存记录。'}</div>`;

  return { sourcesHtml, requirementsHtml, historyHtml, count: rows.length };
}

/** The server contract is the only source of CSV headers. No sample rows. */
export function csvTemplate(schema) {
  if (!Array.isArray(schema?.required) || !schema.required.length || schema.required.some((field) => typeof field !== 'string' || !field.trim())) {
    throw new Error('未取得有效的必填字段契约，无法下载模板');
  }
  const quote = (field) => /[",\r\n]/.test(field) ? `"${field.replaceAll('"', '""')}"` : field;
  return '\uFEFF' + schema.required.map(quote).join(',') + '\r\n';
}

function startDownload(href, filename) {
  const link = document.createElement('a');
  link.href = href;
  link.download = filename;
  link.hidden = true;
  document.body.append(link);
  try {
    link.click();
  } finally {
    link.remove();
  }
}

export function downloadTemplate(kind, schema) {
  if (typeof kind !== 'string' || !/^[a-z][a-z0-9_-]*$/.test(kind)) throw new Error('无效的数据类型');
  const href = URL.createObjectURL(new Blob([csvTemplate(schema)], { type: 'text/csv;charset=utf-8' }));
  try {
    startDownload(href, `${kind}-template.csv`);
  } finally {
    // Let the browser start reading the Blob before releasing its URL.
    setTimeout(() => URL.revokeObjectURL(href), 1000);
  }
}

export function sampleDownloadTarget(manifest, fileKey) {
  const entry = own(manifest?.files, fileKey);
  const path = entry?.path;
  if (manifest?.metadata?.is_sample !== true || typeof path !== 'string') throw new Error('未取得合成数据文件清单');
  const segments = path.split('/');
  if (/[\\:%?#\u0000-\u001f\u007f]/.test(path) || segments.some((segment) => !segment || segment !== segment.trim() || segment.endsWith('.'))) {
    throw new Error('合成数据路径必须位于 sample-data 目录内');
  }
  return { href: `sample-data/${segments.map(encodeURIComponent).join('/')}`, filename: segments.at(-1) };
}

export function downloadSample(manifest, fileKey) {
  const { href, filename } = sampleDownloadTarget(manifest, fileKey);
  startDownload(href, filename);
}

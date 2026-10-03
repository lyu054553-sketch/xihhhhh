const SAFE_PATH = /^generated\/[a-z0-9_-]+\.(json|csv)$/i;
const INPUT_FILES = ['dataset', 'stores', 'inventory_inputs', 'confirmed_payments', 'risk_inputs', 'workbench_inputs', 'scenario_requests'];

function fail(message) { throw new Error(`合成数据包格式错误：${message}`); }
const nonempty = (value) => typeof value === "string" && value.trim().length > 0;

export function validateManifest(manifest) {
  if (!manifest || manifest.contract_version !== 'v1.2' || manifest.synthetic !== true || manifest.is_demo !== true) fail('需要标明 v1.2 的合成输入包');
  for (const key of ['snapshot_id', 'as_of_date', 'timezone', 'source']) if (!nonempty(manifest[key])) fail(`缺少 ${key}`);
  const date = new Date(`${manifest.as_of_date}T00:00:00Z`);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(manifest.as_of_date) || !Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== manifest.as_of_date) fail('数据日期无效');
  if (manifest.units?.money !== 'CNY' || manifest.units?.percentage !== '0..100') fail('金额必须为元、比例必须为百分数');
  for (const key of INPUT_FILES) sampleDownloadTarget(manifest, key);
  for (const key of Object.keys(manifest.files)) sampleDownloadTarget(manifest, key);
  return manifest;
}

export function sampleDownloadTarget(manifest, key) {
  if (!manifest || manifest.synthetic !== true || !Object.hasOwn(manifest.files || {}, key)) fail("文件未包含在合成数据清单中");
  const entry = manifest.files[key];
  if (!entry || !SAFE_PATH.test(entry.path) || !/^[a-f0-9]{64}$/i.test(entry.sha256)) fail("下载路径或校验值无效");
  return `/sample-data/${entry.path}`;
}

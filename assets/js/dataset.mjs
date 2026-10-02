const SAFE_PATH = /^generated\/[a-z0-9_-]+\.(json|csv)$/i;
const DATA_MODELS = ["stores", "skus", "inventory_snapshots", "sales_daily", "purchase_orders", "inventory_lots", "policies"];

function fail(message) { throw new Error(`合成数据包格式错误：${message}`); }
const nonempty = (value) => typeof value === "string" && value.trim().length > 0;
const records = (value) => Array.isArray(value) && value.length > 0;

export function validateManifest(manifest) {
  if (!manifest || manifest.contract_version !== "v0.3" || manifest.synthetic !== true) fail("需要标明 v0.3 的合成数据包");
  for (const key of ["data_version", "policy_version", "as_of", "timezone", "source_label"]) if (!nonempty(manifest[key])) fail(`缺少 ${key}`);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(manifest.as_of) || new Date(manifest.as_of + "T00:00:00Z").toISOString().slice(0, 10) !== manifest.as_of) fail("分析基准日期无效");
  if (!Number.isSafeInteger(manifest.seed)) fail("固定种子必须为整数");
  const options = manifest.scope_options;
  for (const [key, id, name] of [["stores", "store_id", "store_name"], ["skus", "sku_id", "sku_name"], ["categories", "category_id", "category_name"]]) {
    if (!records(options?.[key])) fail(`缺少 ${key} 筛选清单`);
    const ids = new Set();
    for (const item of options[key]) {
      if (!nonempty(item?.[id]) || !nonempty(item?.[name]) || ids.has(item[id])) fail(`${key} 的编号或名称无效`);
      ids.add(item[id]);
      if (key === "skus" && !nonempty(item.unit)) fail("商品缺少计量单位");
    }
  }
  for (const key of ["dataset", ...DATA_MODELS]) sampleDownloadTarget(manifest, key);
  return manifest;
}

export function sampleDownloadTarget(manifest, key) {
  if (!manifest || manifest.synthetic !== true || !Object.hasOwn(manifest.files || {}, key)) fail("文件未包含在合成数据清单中");
  const entry = manifest.files[key];
  if (!entry || !SAFE_PATH.test(entry.path) || !/^[a-f0-9]{64}$/i.test(entry.sha256)) fail("下载路径或校验值无效");
  return `/sample-data/${entry.path}`;
}

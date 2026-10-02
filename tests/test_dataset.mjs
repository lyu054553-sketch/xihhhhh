import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { validateManifest, sampleDownloadTarget } from "../assets/js/dataset.mjs";

const manifest = () => JSON.parse(readFileSync(new URL("../sample-data/manifest.json", import.meta.url), "utf8"));
test("the checked-in v0.3 input package provides the scopes and versions used by forms", () => {
  const value = manifest();
  assert.equal(validateManifest(value), value);
  assert.equal(value.data_version, "snack-demo-v1");
  assert.equal(sampleDownloadTarget(value, "dataset"), "/sample-data/generated/dataset.json");
});
test("unknown or non-synthetic sources cannot be presented as the demo package", () => {
  for (const mutation of [{ synthetic: false }, { contract_version: "v0.2" }, { data_version: "" }]) {
    assert.throws(() => validateManifest({ ...manifest(), ...mutation }));
  }
});
test("scope IDs must be unique and every SKU carries its actual inventory unit", () => {
  const value = manifest();
  value.scope_options.stores.push(value.scope_options.stores[0]);
  assert.throws(() => validateManifest(value));
  const other = manifest();
  delete other.scope_options.skus[0].unit;
  assert.throws(() => validateManifest(other));
});
test("download paths cannot traverse, use remote hosts or expose undeclared files", () => {
  for (const path of ["../backend/api.py", "generated/../../.env", "https://example.com/data.json", "generated/%2e%2e/data.json"]) {
    const value = manifest();
    value.files.dataset.path = path;
    assert.throws(() => sampleDownloadTarget(value, "dataset"));
  }
  assert.throws(() => sampleDownloadTarget(manifest(), "__proto__"));
  assert.throws(() => sampleDownloadTarget(manifest(), "missing"));
});
test("missing tables and invalid checksums fail visibly instead of creating fallback data", () => {
  const value = manifest();
  delete value.files.sales_daily;
  assert.throws(() => validateManifest(value));
  const other = manifest();
  other.files.dataset.sha256 = "unknown";
  assert.throws(() => validateManifest(other));
});

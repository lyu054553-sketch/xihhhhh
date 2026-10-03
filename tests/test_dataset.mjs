import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { validateManifest, sampleDownloadTarget } from '../assets/js/dataset.mjs';
const manifest = () => JSON.parse(readFileSync(new URL('../sample-data/manifest.json', import.meta.url), 'utf8'));
test('current inputs use v1.2 yuan and a reproducible backend snapshot', () => {
  const value=manifest();
  assert.equal(validateManifest(value),value);
  assert.equal(value.snapshot_id,'snapshot-demo-v1');
  assert.equal(sampleDownloadTarget(value,'dataset'),'/sample-data/generated/dataset.json');
});
test('non-synthetic, unversioned and differently scaled inputs fail visibly', () => {
  for(const mutation of [{synthetic:false},{is_demo:false},{contract_version:'v0.3'},{snapshot_id:''},{units:{money:'fen',percentage:'0..1'}}]) assert.throws(()=>validateManifest({...manifest(),...mutation}));
});
test('invalid and impossible dates are rejected', () => {
  for(const as_of_date of ['tomorrow','2026-02-30','2026-13-01']) assert.throws(()=>validateManifest({...manifest(),as_of_date}));
});
test('download paths cannot traverse or expose undeclared files', () => {
  for(const path of ['../backend/api.py','generated/../../.env','https://example.com/data.json','generated/%2e%2e/data.json']) {
    const value=manifest(); value.files.dataset.path=path;
    assert.throws(()=>sampleDownloadTarget(value,'dataset'));
  }
  assert.throws(()=>sampleDownloadTarget(manifest(),'__proto__'));
  assert.throws(()=>sampleDownloadTarget(manifest(),'missing'));
});
test('missing inputs and invalid checksums fail without fallback data', () => {
  const value=manifest();delete value.files.inventory_inputs;
  assert.throws(()=>validateManifest(value));
  const other=manifest();other.files.dataset.sha256='unknown';
  assert.throws(()=>validateManifest(other));
});
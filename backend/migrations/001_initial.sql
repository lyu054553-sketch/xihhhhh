-- 001_initial.sql
-- 与 backend/store.py 的 SQLite 初始迁移保持同语义；开发启动时由 Store 自动执行。
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS snapshots (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, kind TEXT NOT NULL,
  created_at TEXT NOT NULL, source TEXT NOT NULL, is_sample INTEGER NOT NULL DEFAULT 1,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS risks (
  id INTEGER PRIMARY KEY, tenant_id TEXT NOT NULL, snapshot_id TEXT NOT NULL,
  sku TEXT NOT NULL, product TEXT NOT NULL, store TEXT NOT NULL, store_id TEXT NOT NULL,
  sales_30 INTEGER, comparison_json TEXT NOT NULL DEFAULT '[]', inventory_qty INTEGER,
  unit_cost TEXT, tags_json TEXT NOT NULL DEFAULT '[]', days_to_sell INTEGER,
  risk_type TEXT NOT NULL, priority TEXT NOT NULL, observation TEXT NOT NULL,
  evidence_level TEXT NOT NULL, missing_fields_json TEXT NOT NULL DEFAULT '[]',
  investigation_status TEXT NOT NULL DEFAULT 'not_started', current_fact_version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS investigations (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, risk_id INTEGER NOT NULL,
  status TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback_versions (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, investigation_id TEXT NOT NULL,
  version INTEGER NOT NULL, raw_text TEXT NOT NULL, draft_json TEXT NOT NULL,
  confirmed_json TEXT, confirmation_status TEXT NOT NULL, submitted_at TEXT NOT NULL,
  confirmed_at TEXT, actor_id TEXT NOT NULL, source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS proposals (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, risk_id INTEGER NOT NULL,
  current_version INTEGER NOT NULL, status TEXT NOT NULL, snapshot_id TEXT NOT NULL,
  fact_version INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS proposal_versions (
  id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, version INTEGER NOT NULL,
  payload_json TEXT NOT NULL, status TEXT NOT NULL, invalid_reason TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, proposal_id TEXT NOT NULL,
  proposal_version INTEGER NOT NULL, actor_id TEXT NOT NULL, status TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS execution_tasks (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, proposal_id TEXT NOT NULL,
  proposal_version INTEGER NOT NULL, status TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS cash_events (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, scenario_id TEXT NOT NULL,
  event_type TEXT NOT NULL, amount TEXT, direction TEXT NOT NULL, event_date TEXT,
  business_ref TEXT, source TEXT NOT NULL, evidence_ref TEXT
);
CREATE TABLE IF NOT EXISTS cases (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, risk_id INTEGER, stage TEXT NOT NULL,
  status TEXT NOT NULL, content_json TEXT NOT NULL, actor_id TEXT NOT NULL,
  created_at TEXT NOT NULL, revised_at TEXT
);
CREATE TABLE IF NOT EXISTS audit_events (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL, event_type TEXT NOT NULL, payload_json TEXT NOT NULL,
  actor_id TEXT NOT NULL, created_at TEXT NOT NULL
);


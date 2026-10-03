"""SQLite 持久化：开发和黑客松交付阶段的最小真相源。"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Iterable, Iterator, List, Optional

from .domain import (TEACHER_BASELINE_VERSION, evidence_label, evidence_level, money,
                     calculate_transfer, calculate_expiry_rescue, calculate_procurement_brake, teacher_baseline)
from .demo_data import TRANSFER_NETWORK_STORES
from .errors import BusinessConflict
from .serialization import dumps
from .imports import MAX_QUANTITY, inventory_fingerprint, inventory_rows


SCHEMA = """
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
  status TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL,
  FOREIGN KEY(risk_id) REFERENCES risks(id)
);
CREATE TABLE IF NOT EXISTS feedback_versions (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, investigation_id TEXT NOT NULL,
  version INTEGER NOT NULL, raw_text TEXT NOT NULL, draft_json TEXT NOT NULL,
  confirmed_json TEXT, confirmation_status TEXT NOT NULL, submitted_at TEXT NOT NULL,
  confirmed_at TEXT, actor_id TEXT NOT NULL, source TEXT NOT NULL,
  FOREIGN KEY(investigation_id) REFERENCES investigations(id)
);
CREATE TABLE IF NOT EXISTS proposals (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, risk_id INTEGER NOT NULL,
  current_version INTEGER NOT NULL, status TEXT NOT NULL, snapshot_id TEXT NOT NULL,
  fact_version INTEGER NOT NULL, created_at TEXT NOT NULL,
  FOREIGN KEY(risk_id) REFERENCES risks(id)
);
CREATE TABLE IF NOT EXISTS proposal_versions (
  id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, version INTEGER NOT NULL,
  payload_json TEXT NOT NULL, status TEXT NOT NULL, invalid_reason TEXT,
  created_at TEXT NOT NULL, FOREIGN KEY(proposal_id) REFERENCES proposals(id)
);
CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, proposal_id TEXT NOT NULL,
  proposal_version INTEGER NOT NULL, actor_id TEXT NOT NULL, status TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL,
  FOREIGN KEY(proposal_id) REFERENCES proposals(id)
);
CREATE TABLE IF NOT EXISTS execution_tasks (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, proposal_id TEXT NOT NULL,
  proposal_version INTEGER NOT NULL, status TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}', version INTEGER NOT NULL DEFAULT 1,
  FOREIGN KEY(proposal_id) REFERENCES proposals(id)
);
CREATE TABLE IF NOT EXISTS inventory_reservations (
  tenant_id TEXT NOT NULL, snapshot_id TEXT NOT NULL, resource_key TEXT NOT NULL,
  proposal_id TEXT NOT NULL, proposal_version INTEGER NOT NULL, quantity INTEGER NOT NULL,
  PRIMARY KEY(tenant_id, proposal_id, proposal_version, resource_key),
  FOREIGN KEY(proposal_id) REFERENCES proposals(id)
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
CREATE TABLE IF NOT EXISTS workbench_drafts (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, module_type TEXT NOT NULL, risk_id INTEGER NOT NULL,
  version INTEGER NOT NULL, status TEXT NOT NULL, input_json TEXT NOT NULL, calculation_json TEXT,
  proposal_id TEXT, updated_by TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(tenant_id, module_type, risk_id), FOREIGN KEY(risk_id) REFERENCES risks(id)
);
CREATE TABLE IF NOT EXISTS data_imports (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, filename TEXT NOT NULL, mode TEXT NOT NULL,
  status TEXT NOT NULL, summary_json TEXT NOT NULL, errors_json TEXT NOT NULL,
  created_at TEXT NOT NULL, actor_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS real_inventory_snapshots (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, source TEXT NOT NULL, as_of_date TEXT,
  created_at TEXT NOT NULL, record_count INTEGER NOT NULL, org_count INTEGER NOT NULL,
  sku_count INTEGER NOT NULL, cost_total TEXT, untaxed_cost_total TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS real_inventory_lines (
  snapshot_id TEXT NOT NULL, tenant_id TEXT NOT NULL, org_code TEXT NOT NULL,
  org_name TEXT NOT NULL, sku TEXT NOT NULL, product_name TEXT NOT NULL,
  generic_name TEXT, spec TEXT, manufacturer TEXT, origin TEXT, unit TEXT,
  inventory_qty REAL, pending_qty REAL, available_qty REAL, latest_cost REAL,
  cost_amount REAL, untaxed_cost_amount REAL, tax_amount REAL, lot_count REAL,
  sku_lot_count REAL, amount_share REAL, company_focus TEXT, store_focus TEXT,
  barcode TEXT, purchase_status TEXT, store_price REAL, ecommerce_price REAL,
  member_price REAL, product_status TEXT, stat_class TEXT,
  sales_30 REAL, sales_90 REAL, sales_cost_30 REAL,
  source_monthly_sales REAL, source_sales_ratio REAL,
  teacher_monthly_sales REAL, teacher_ratio REAL, reduction_ratio REAL,
  teacher_target_inventory_amount REAL, teacher_suggested_reduction_amount REAL,
  teacher_reference_reduction_qty REAL, teacher_priority TEXT, teacher_trigger_reason TEXT,
  teacher_candidate INTEGER NOT NULL DEFAULT 0, teacher_eligible INTEGER NOT NULL DEFAULT 0,
  teacher_stockout INTEGER, teacher_near_stockout INTEGER,
  PRIMARY KEY(snapshot_id, org_code, sku),
  FOREIGN KEY(snapshot_id) REFERENCES real_inventory_snapshots(id)
);
CREATE INDEX IF NOT EXISTS idx_real_inventory_lines_snapshot_org
  ON real_inventory_lines(snapshot_id, org_code);
CREATE INDEX IF NOT EXISTS idx_real_inventory_lines_snapshot_sku
  ON real_inventory_lines(snapshot_id, sku);
"""


WORKBENCH_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "transfer": {
        "risk_id": 1, "lot_id": "LOT-A-001", "source_store": "西湖文三店", "source_store_id": "STORE-001",
        "target_store": "余杭未来店", "target_store_id": "STORE-002", "product": "每日坚果礼盒 750g",
        "batch": "2026-12-15", "quantity": 40, "source_on_hand": 120, "source_safety": 30, "source_daily_sales": "0.71",
        "target_on_hand": 15, "target_capacity": 65, "target_safety": 12, "target_daily_sales": "1.20",
        "sellable_days": 73, "eta_days": 1, "transport_fee": "86", "unit_cost": "80", "eta_at": "2026-10-04",
    },
    "expiry-rescue": {
        "risk_id": 3, "lot_id": "LOT-EXP-003", "store": "拱墅运河店", "store_id": "STORE-003", "product": "纯牛奶整箱 250ml×24",
        "batch": "2026-10-25", "inventory_qty": 90, "unit_cost": "76", "sales_30": 16, "sellable_days": 22,
        "latest_disposal_date": "2026-10-21", "transfer_qty": 18, "transfer_fee": "42", "promo_qty": 12,
        "promo_price": "52", "promo_fee": "120", "return_qty": 10,
    },
    "procurement-brake": {
        "risk_id": 4, "po_number": "PO-202609-048", "line_number": "2", "product": "酸奶夹心饼干整箱 100g×12", "store": "上城庆春店",
        "current_inventory": 80, "in_transit_qty": 40, "open_purchase_qty": 60, "adjustment_qty": 40, "unit_cost": "59",
        "safety_stock": 50, "arrival_date": "2026-10-09", "payment_date": "2026-10-13", "new_payment_date": "2026-11-12",
        "cutoff_date": "2026-11-02", "order_status": "待供应商确认", "action": "delay_payment",
    },
    "slow-diagnosis": {"risk_id": 1},
}

EXPIRY_WORKBENCH_DEFAULTS: Dict[int, Dict[str, Any]] = {
    3: WORKBENCH_DEFAULTS["expiry-rescue"],
    6: {"risk_id": 6, "lot_id": "LOT-EXP-006", "store": "西湖古荡店", "store_id": "STORE-006", "product": "海盐薯片分享装 80g×8", "batch": "2026-10-17", "inventory_qty": 64, "unit_cost": "38", "sales_30": 10, "sellable_days": 14, "latest_disposal_date": "2026-10-15", "transfer_qty": 20, "transfer_fee": "35", "promo_qty": 12, "promo_price": "29", "promo_fee": "80", "return_qty": 8},
    7: {"risk_id": 7, "lot_id": "LOT-EXP-007", "store": "上城湖滨店", "store_id": "STORE-007", "product": "气泡果汁整箱 330ml×12", "batch": "2026-10-21", "inventory_qty": 48, "unit_cost": "42", "sales_30": 9, "sellable_days": 18, "latest_disposal_date": "2026-10-18", "transfer_qty": 10, "transfer_fee": "28", "promo_qty": 16, "promo_price": "35", "promo_fee": "75", "return_qty": 6},
    8: {"risk_id": 8, "lot_id": "LOT-EXP-008", "store": "拱墅大关店", "store_id": "STORE-008", "product": "水果果冻分享桶 1kg", "batch": "2026-10-27", "inventory_qty": 72, "unit_cost": "31", "sales_30": 12, "sellable_days": 24, "latest_disposal_date": "2026-10-23", "transfer_qty": 18, "transfer_fee": "41", "promo_qty": 18, "promo_price": "25", "promo_fee": "90", "return_qty": 10},
    9: {"risk_id": 9, "lot_id": "LOT-EXP-009", "store": "余杭仓前店", "store_id": "STORE-009", "product": "乌龙茶整箱 500ml×15", "batch": "2026-10-31", "inventory_qty": 56, "unit_cost": "68", "sales_30": 8, "sellable_days": 28, "latest_disposal_date": "2026-10-27", "transfer_qty": 16, "transfer_fee": "46", "promo_qty": 12, "promo_price": "48", "promo_fee": "95", "return_qty": 8},
    10: {"risk_id": 10, "lot_id": "LOT-EXP-010", "store": "临平星桥店", "store_id": "STORE-010", "product": "奶香蛋卷礼盒 400g", "batch": "2026-11-06", "inventory_qty": 84, "unit_cost": "27", "sales_30": 11, "sellable_days": 34, "latest_disposal_date": "2026-11-02", "transfer_qty": 20, "transfer_fee": "52", "promo_qty": 18, "promo_price": "20", "promo_fee": "110", "return_qty": 12},
    11: {"risk_id": 11, "lot_id": "LOT-EXP-011", "store": "西湖学院路店", "store_id": "STORE-052", "product": "芝士威化组合装 500g", "batch": "2026-10-23", "inventory_qty": 58, "unit_cost": "34", "sales_30": 6, "sellable_days": 20, "latest_disposal_date": "2026-10-19", "transfer_qty": 14, "transfer_fee": "32", "promo_qty": 16, "promo_price": "25", "promo_fee": "65", "return_qty": 8},
}

TRANSFER_WORKBENCH_DEFAULTS: Dict[int, Dict[str, Any]] = {
    1: WORKBENCH_DEFAULTS["transfer"],
    5: {"risk_id": 5, "lot_id": "LOT-A-005", "source_store": "临平东湖店", "source_store_id": "STORE-005", "target_store": "西湖古荡店", "target_store_id": "STORE-006", "product": "山楂果脯礼盒 1kg", "batch": "2027-04-15", "quantity": 35, "source_on_hand": 70, "source_safety": 20, "source_daily_sales": "0.67", "target_on_hand": 10, "target_capacity": 58, "target_safety": 12, "target_daily_sales": "1.10", "sellable_days": 120, "eta_days": 1, "transport_fee": "98", "unit_cost": "55", "eta_at": "2026-10-04"},
}

PROCUREMENT_WORKBENCH_DEFAULTS: Dict[int, Dict[str, Any]] = {
    4: WORKBENCH_DEFAULTS["procurement-brake"],
    12: {"risk_id": 12, "po_number": "PO-202609-062", "line_number": "1", "product": "黑巧燕麦棒整盒 30g×20", "store": "西湖蒋村店", "current_inventory": 66, "in_transit_qty": 24, "open_purchase_qty": 48, "adjustment_qty": 30, "unit_cost": "46", "safety_stock": 36, "arrival_date": "2026-10-10", "payment_date": "2026-10-14", "new_payment_date": "2026-11-13", "cutoff_date": "2026-11-02", "order_status": "待供应商确认", "action": "reduce"},
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialized(method):
    """Keep a shared connection exclusive until a whole Store operation finishes."""
    @wraps(method)
    def locked(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return locked


def _transactional(method):
    @wraps(method)
    def atomic(self, *args, **kwargs):
        with self._lock:
            outer = self._transaction_depth == 0
            if outer:
                self.conn.execute("BEGIN IMMEDIATE")
            self._transaction_depth += 1
            try:
                result = method(self, *args, **kwargs)
                if outer:
                    self.conn.commit()
                return result
            except BaseException:
                if outer:
                    self.conn.rollback()
                raise
            finally:
                self._transaction_depth -= 1
    return atomic


class Store:
    def __init__(self, path: str = "inventory_cash_agent.db") -> None:
        self.path = path
        # check_same_thread=False permits cross-thread use; it does not serialize
        # execute/fetch, statement-cache access or multi-statement mutations.
        # Nested Store calls need a reentrant lock on the same connection.
        self._lock = RLock()
        self._transaction_depth = 0
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate_schema()

    @_transactional
    def _migrate_schema(self):
        """Serialize additive migrations across separate application processes."""
        self._migrate_real_inventory_lines()
        if "version" not in {row[1] for row in self.conn.execute("PRAGMA table_info(execution_tasks)")}:
            self.conn.execute("ALTER TABLE execution_tasks ADD COLUMN version INTEGER NOT NULL DEFAULT 1")
        self._commit()

    def _commit(self):
        if self._transaction_depth == 0:
            self.conn.commit()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Expose the shared SQLite transaction boundary to feature services.

        The reentrant lock remains held for the whole context. Nested Store
        methods join this transaction because ``_transaction_depth`` is
        nonzero; only the outermost scope commits or rolls back.
        """
        with self._lock:
            outer = self._transaction_depth == 0
            if outer:
                self.conn.execute("BEGIN IMMEDIATE")
            self._transaction_depth += 1
            try:
                yield self.conn
                if outer:
                    self.conn.commit()
            except BaseException:
                if outer:
                    self.conn.rollback()
                raise
            finally:
                self._transaction_depth -= 1

    @_serialized
    def _migrate_real_inventory_lines(self) -> None:
        """为已导入的库存快照补齐老师口径字段，不重建或删除历史快照。"""
        columns = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(real_inventory_lines)").fetchall()
        }
        additions = {
            "risk_id": "INTEGER",
            "product_status": "TEXT",
            "stat_class": "TEXT",
            "sales_30": "REAL",
            "sales_90": "REAL",
            "sales_cost_30": "REAL",
            "source_monthly_sales": "REAL",
            "source_sales_ratio": "REAL",
            "teacher_monthly_sales": "REAL",
            "teacher_ratio": "REAL",
            "reduction_ratio": "REAL",
            "teacher_target_inventory_amount": "REAL",
            "teacher_suggested_reduction_amount": "REAL",
            "teacher_reference_reduction_qty": "REAL",
            "teacher_priority": "TEXT",
            "teacher_trigger_reason": "TEXT",
            "teacher_candidate": "INTEGER NOT NULL DEFAULT 0",
            "teacher_eligible": "INTEGER NOT NULL DEFAULT 0",
            "teacher_stockout": "INTEGER",
            "teacher_near_stockout": "INTEGER",
        }
        for name, definition in additions.items():
            if name not in columns:
                self.conn.execute(f"ALTER TABLE real_inventory_lines ADD COLUMN {name} {definition}")
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_real_inventory_lines_teacher "
            "ON real_inventory_lines(snapshot_id, teacher_candidate, teacher_priority)"
        )

    @_serialized
    def close(self) -> None:
        self.conn.close()

    @_transactional
    def reset_demo(self) -> None:
        if self.real_inventory_snapshot("demo"):
            raise BusinessConflict("real_data_present", "已有真实库存快照，不能重置该数据库；请使用独立演示数据库")
        for table in [
            "inventory_reservations", "audit_events", "cases", "cash_events", "execution_tasks", "approvals",
            "proposal_versions", "proposals", "feedback_versions", "investigations", "workbench_drafts", "data_imports", "risks", "snapshots"
        ]:
            if table == "proposal_versions":
                self.conn.execute("DELETE FROM proposal_versions WHERE proposal_id IN (SELECT id FROM proposals WHERE tenant_id='demo')")
            else:
                self.conn.execute("DELETE FROM " + table + " WHERE tenant_id='demo'")
        self._commit()
        self.seed_demo()

    @_transactional
    def seed_demo(self) -> None:
        # 用户已导入真实库存时，不新增或迁移任何演示商品。
        if self.real_inventory_snapshot("demo"):
            return
        created = now_iso()
        self.conn.execute(
            "INSERT OR IGNORE INTO snapshots(id, tenant_id, kind, created_at, source, is_sample, metadata_json) VALUES(?,?,?,?,?,?,?)",
            ("snapshot-demo-v1", "demo", "sample_replay", created, "sample-data/ac01", 1, json.dumps({"label": "合成样例回放", "as_of_date": "2026-10-03", "is_demo": True}, ensure_ascii=False)),
        )
        risks = [
            (1, "SKU-88310", "每日坚果礼盒 750g", "西湖文三店", "STORE-001", 12, [18, 22, 26, 30, 30, 34, 38, 42], 120, "80", ["slow", "near_expiry"], 168, "调拨", "紧急", "近30天销量低于同规格对照门店中位数 60%；原因待核查。", "partial", ["shelf_availability", "stockout_records"]),
            (2, "SKU-10428", "炭烤腰果礼盒 600g", "余杭未来店", "STORE-002", 8, [12, 18, 20, 25], 110, "80", ["slow"], 214, "退供", "高", "库存覆盖天数偏高；采购量与退换条件待核查。", "insufficient", ["supplier_return_terms"]),
            (3, "SKU-34106", "纯牛奶整箱 250ml×24", "拱墅运河店", "STORE-003", 16, [18, 22, 25], 90, "76", ["near_expiry"], 146, "促销", "紧急", "近效期批次预计无法在当前速度下售完；需求与效期证据部分支持。", "partial", ["sellable_days"]),
            (4, "SKU-55091", "酸奶夹心饼干整箱 100g×12", "上城庆春店", "STORE-004", 14, [19, 20, 23], 80, "59", ["overpurchase"], 137, "采购刹车", "高", "销量下降但在途采购状态待核查。", "insufficient", ["purchase_order_status"]),
            (5, "SKU-79033", "山楂果脯礼盒 1kg", "临平东湖店", "STORE-005", 20, [24, 28, 30], 70, "55", ["mismatch"], 119, "调拨", "中", "门店间销量差异需结合规模和可售天数核查。", "insufficient", ["store_scale", "sellable_days"]),
            (6, "SKU-22016", "海盐薯片分享装 80g×8", "西湖古荡店", "STORE-006", 10, [14, 16, 18], 64, "38", ["near_expiry"], 192, "促销", "紧急", "批次剩余可售时间仅14天，按当前销量预计无法售完。", "partial", ["price_sales_elasticity"]),
            (7, "SKU-33718", "气泡果汁整箱 330ml×12", "上城湖滨店", "STORE-007", 9, [12, 15, 17], 48, "42", ["near_expiry"], 160, "促销", "高", "批次可售时间不足，需比较调拨、促销和退供。", "partial", ["supplier_return_terms"]),
            (8, "SKU-44107", "水果果冻分享桶 1kg", "拱墅大关店", "STORE-008", 12, [16, 18, 21], 72, "31", ["near_expiry"], 180, "促销", "高", "批次接近处置窗口，当前销量无法覆盖库存。", "partial", ["price_sales_elasticity"]),
            (9, "SKU-56126", "乌龙茶整箱 500ml×15", "余杭仓前店", "STORE-009", 8, [13, 15, 17], 56, "68", ["near_expiry"], 210, "促销", "高", "季节性商品接近效期，需优先确认门店与退供路径。", "partial", ["supplier_return_terms"]),
            (10, "SKU-65031", "奶香蛋卷礼盒 400g", "临平星桥店", "STORE-010", 11, [14, 16, 18], 84, "27", ["near_expiry"], 229, "促销", "中", "预计可售量低于批次库存，存在后续报损风险。", "partial", ["price_sales_elasticity"]),
            (11, "SKU-71008", "芝士威化组合装 500g", "西湖学院路店", "STORE-052", 6, [10, 12, 14], 58, "34", ["near_expiry"], 290, "促销", "紧急", "批次剩余可售时间不足，按当前销量预计无法售完。", "partial", ["price_sales_elasticity"]),
            (12, "SKU-81016", "黑巧燕麦棒整盒 30g×20", "西湖蒋村店", "STORE-014", 9, [15, 17, 19], 66, "46", ["overpurchase"], 220, "采购刹车", "高", "当前库存和在途采购叠加后偏高，需确认未执行采购是否减量。", "partial", ["purchase_order_status"]),
            (13, "SKU-91021", "混合坚果礼盒 1kg", "西湖转塘店", "STORE-026", 5, [9, 11, 13], 46, "88", ["slow"], 276, "退供", "高", "库存周转偏慢，建议优先核对供应商退换条件。", "insufficient", ["supplier_return_terms"]),
        ]
        for row in risks:
            (risk_id, sku, product, store, store_id, sales, comparison, inventory, unit_cost, tags, days, risk_type, priority, observation, level, missing) = row
            self.conn.execute(
                """INSERT OR IGNORE INTO risks
                (id, tenant_id, snapshot_id, sku, product, store, store_id, sales_30, comparison_json,
                 inventory_qty, unit_cost, tags_json, days_to_sell, risk_type, priority, observation,
                 evidence_level, missing_fields_json, created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (risk_id, "demo", "snapshot-demo-v1", sku, product, store, store_id, sales, json.dumps(comparison), inventory, unit_cost, json.dumps(tags), days, risk_type, priority, observation, level, json.dumps(missing, ensure_ascii=False), created),
            )
        # 仅迁移旧版本的明确样例记录；不匹配用户修改后的名称。
        sample = self.one("SELECT id, metadata_json FROM snapshots WHERE id='snapshot-demo-v1' AND tenant_id='demo' AND is_sample=1 AND source='sample-data/ac01'")
        if sample:
            metadata = json.loads(sample["metadata_json"])
            metadata.update({"as_of_date": "2026-10-03", "is_demo": True})
            self.conn.execute("UPDATE snapshots SET metadata_json=? WHERE id=?", (dumps(metadata), sample["id"]))
            self.conn.execute("UPDATE risks SET observation=? WHERE id=6 AND tenant_id='demo' AND snapshot_id='snapshot-demo-v1' AND observation=?", ("批次剩余可售时间仅14天，按当前销量预计无法售完。", "批次距最晚处置日仅14天，按当前销量预计无法售完。"))
            snack_names = {'钙维生素D软胶囊': '每日坚果礼盒 750g', '阿胶块 250g': '炭烤腰果礼盒 600g', '藿香正气口服液': '纯牛奶整箱 250ml×24', '乳酸菌素片 32片': '酸奶夹心饼干整箱 100g×12', '血糖试纸 50片': '山楂果脯礼盒 1kg', '复方氨酚烷胺胶囊': '海盐薯片分享装 80g×8', '维生素C泡腾片': '气泡果汁整箱 330ml×12', '健胃消食片': '水果果冻分享桶 1kg', '藿香正气水': '乌龙茶整箱 500ml×15', '医用退热贴': '奶香蛋卷礼盒 400g', '蒙脱石散': '芝士威化组合装 500g', '益生菌粉 30袋': '黑巧燕麦棒整盒 30g×20', '阿胶糕 10块': '混合坚果礼盒 1kg'}
            for previous, current in snack_names.items():
                self.conn.execute("UPDATE risks SET product=? WHERE tenant_id='demo' AND snapshot_id='snapshot-demo-v1' AND product=?", (current, previous))
            for draft in self.rows("SELECT id, input_json FROM workbench_drafts WHERE tenant_id='demo' AND risk_id IN (SELECT id FROM risks WHERE snapshot_id='snapshot-demo-v1' AND tenant_id='demo')"):
                data = json.loads(draft["input_json"])
                if data.get("product") in snack_names:
                    data["product"] = snack_names[data["product"]]
                    self.conn.execute("UPDATE workbench_drafts SET input_json=? WHERE id=?", (dumps(data), draft["id"]))
        self._seed_proposal(1, 1, "transfer", created)
        self._seed_cash_events()
        self._commit()

    @_serialized
    def _seed_proposal(self, risk_id: int, version: int, action_type: str, created: str) -> str:
        proposal_id = "PROP-AC10-001"
        payload = {
            "proposal_type": action_type,
            "actions": [{"type": "transfer", "lot_id": "LOT-A-001", "source_store_id": "STORE-001", "target_store_id": "STORE-002", "quantity": 40, "unit_cost": 80}],
            "cash": {"estimated_net_cash_improvement": None, "known_cash_effect": -86, "completeness": "unavailable", "missing_fields": ["future_sales_receipts", "supplier_payment_schedule"]},
            "basis": {"snapshot_id": "snapshot-demo-v1", "fact_version": 1, "evidence_level": "partial"},
        }
        self.conn.execute("INSERT OR IGNORE INTO proposals(id, tenant_id, risk_id, current_version, status, snapshot_id, fact_version, created_at) VALUES(?,?,?,?,?,?,?,?)", (proposal_id, "demo", risk_id, version, "pending_approval", "snapshot-demo-v1", 1, created))
        self.conn.execute("INSERT OR IGNORE INTO proposal_versions(id, proposal_id, version, payload_json, status, invalid_reason, created_at) VALUES(?,?,?,?,?,?,?)", ("PV-AC10-V1", proposal_id, version, dumps(payload), "pending_approval", None, created))
        return proposal_id

    @_serialized
    def _seed_cash_events(self) -> None:
        events = [
            ("ev-b-r1", "baseline-r1", "sales_receipt", "1000", "in", "2026-09-30", "sale-baseline", "sample", "AC04"),
            ("ev-b-p1", "baseline-r1", "purchase_payment", "800", "out", "2026-09-30", "po-baseline", "sample", "AC04"),
            ("ev-s-r1", "scenario-r1", "sales_receipt", "1400", "in", "2026-09-30", "sale-scenario", "sample", "AC04"),
            ("ev-s-p1", "scenario-r1", "purchase_payment", "500", "out", "2026-09-30", "po-scenario", "sample", "AC04"),
            ("ev-s-t1", "scenario-r1", "transfer_cost", "80", "out", "2026-09-30", "transfer-001", "sample", "AC04"),
        ]
        for event in events:
            self.conn.execute("INSERT OR IGNORE INTO cash_events(id, tenant_id, scenario_id, event_type, amount, direction, event_date, business_ref, source, evidence_ref) VALUES(?,?,?,?,?,?,?,?,?,?)", (event[0], "demo", *event[1:]))

    @_serialized
    def rows(self, sql: str, args: Iterable[Any] = ()) -> List[Dict[str, Any]]:
        return [dict(row) for row in self.conn.execute(sql, tuple(args)).fetchall()]

    @_serialized
    def one(self, sql: str, args: Iterable[Any] = ()) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(sql, tuple(args)).fetchone()
        return dict(row) if row else None

    @_transactional
    def audit(self, entity_type: str, entity_id: str, event_type: str, payload: Dict[str, Any], tenant_id: str = "demo", actor_id: str = "demo-user") -> None:
        self.conn.execute("INSERT INTO audit_events(id, tenant_id, entity_type, entity_id, event_type, payload_json, actor_id, created_at) VALUES(?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), tenant_id, entity_type, entity_id, event_type, dumps(payload), actor_id, now_iso()))
        self._commit()

    @_serialized
    def risk(self, risk_id: int, tenant_id: str = "demo") -> Optional[Dict[str, Any]]:
        row = self.one("SELECT * FROM risks WHERE id=? AND tenant_id=?", (risk_id, tenant_id))
        if not row:
            return None
        row["comparison"] = json.loads(row.pop("comparison_json"))
        row["tags"] = json.loads(row.pop("tags_json"))
        row["missing_fields"] = json.loads(row.pop("missing_fields_json"))
        row["evidence_label"] = evidence_label(row["evidence_level"])
        row["unit_cost"] = money(row["unit_cost"])
        proposal = self.one("SELECT id, status, current_version FROM proposals WHERE risk_id=? AND tenant_id=? ORDER BY created_at DESC LIMIT 1", (risk_id, tenant_id))
        row["proposal_id"] = proposal["id"] if proposal else None
        row["proposal_status"] = proposal["status"] if proposal else None
        row["proposal_version"] = proposal["current_version"] if proposal else None
        return row

    @_serialized
    def risks(self, tenant_id: str = "demo") -> List[Dict[str, Any]]:
        snapshot = self.real_inventory_snapshot(tenant_id)
        if snapshot:
            rows = self.rows("SELECT id FROM risks WHERE tenant_id=? AND snapshot_id=? ORDER BY id", (tenant_id, snapshot["id"]))
        else:
            rows = self.rows("SELECT id FROM risks WHERE tenant_id=? ORDER BY priority='紧急' DESC, id", (tenant_id,))
        return [self.risk(row["id"], tenant_id) for row in rows]

    @_transactional
    def create_investigation(self, risk_id: int, actor_id: str = "demo-user", tenant_id: str = "demo") -> Dict[str, Any]:
        if not self.risk(risk_id, tenant_id):
            raise ValueError("风险不存在或无权访问")
        existing = self.one("SELECT * FROM investigations WHERE risk_id=? AND tenant_id=? AND status NOT IN ('confirmed','unable_to_verify') ORDER BY created_at DESC LIMIT 1", (risk_id, tenant_id))
        if existing:
            return existing
        investigation_id = "INV-" + uuid.uuid4().hex[:10]
        self.conn.execute("INSERT INTO investigations(id, tenant_id, risk_id, status, created_by, created_at) VALUES(?,?,?,?,?,?)", (investigation_id, tenant_id, risk_id, "pending", actor_id, now_iso()))
        self.conn.execute("UPDATE risks SET investigation_status='pending' WHERE id=? AND tenant_id=?", (risk_id, tenant_id))
        self._commit()
        self.audit("investigation", investigation_id, "created", {"risk_id": risk_id}, tenant_id, actor_id)
        return self.one("SELECT * FROM investigations WHERE id=?", (investigation_id,)) or {}

    @_transactional
    def add_feedback(self, investigation_id: str, raw_text: str, submitted_at: str, draft: Dict[str, Any], actor_id: str = "demo-user", tenant_id: str = "demo") -> Dict[str, Any]:
        investigation = self.one("SELECT * FROM investigations WHERE id=? AND tenant_id=?", (investigation_id, tenant_id))
        if not investigation:
            raise ValueError("核查任务不存在或无权访问")
        version = self.one("SELECT COALESCE(MAX(version),0)+1 AS v FROM feedback_versions WHERE investigation_id=?", (investigation_id,))["v"]
        feedback_id = "FB-" + uuid.uuid4().hex[:10]
        self.conn.execute("INSERT INTO feedback_versions(id, tenant_id, investigation_id, version, raw_text, draft_json, confirmed_json, confirmation_status, submitted_at, confirmed_at, actor_id, source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (feedback_id, tenant_id, investigation_id, version, raw_text, dumps(draft), None, "pending_confirmation", submitted_at, None, actor_id, "customer_input"))
        self.conn.execute("UPDATE investigations SET status='feedback_pending' WHERE id=?", (investigation_id,))
        self._commit()
        self.audit("feedback", feedback_id, "draft_created", {"investigation_id": investigation_id, "version": version}, tenant_id, actor_id)
        return self.feedback(feedback_id, tenant_id) or {}

    @_serialized
    def feedback(self, feedback_id: str, tenant_id: str = "demo") -> Optional[Dict[str, Any]]:
        row = self.one("SELECT * FROM feedback_versions WHERE id=? AND tenant_id=?", (feedback_id, tenant_id))
        if row:
            row["draft"] = json.loads(row.pop("draft_json"))
            row["confirmed"] = json.loads(row.pop("confirmed_json")) if row.get("confirmed_json") else None
        return row

    def _invalidate_risk_proposals(self, risk_id, tenant_id):
        self.conn.execute("DELETE FROM inventory_reservations WHERE tenant_id=? AND proposal_id IN (SELECT id FROM proposals WHERE risk_id=? AND tenant_id=? AND status!='execution_task_created')", (tenant_id, risk_id, tenant_id))
        self.conn.execute("UPDATE proposal_versions SET status='invalidated', invalid_reason='核查事实发生变化' WHERE proposal_id IN (SELECT id FROM proposals WHERE risk_id=? AND tenant_id=? AND status!='execution_task_created') AND status IN ('draft','pending_approval','approved')", (risk_id, tenant_id))
        self.conn.execute("UPDATE proposals SET status='needs_replan' WHERE risk_id=? AND tenant_id=? AND status IN ('draft','pending_approval','approved')", (risk_id, tenant_id))

    @_transactional
    def confirm_feedback(self, feedback_id: str, confirmed: Dict[str, Any], actor_id: str = "demo-user", tenant_id: str = "demo") -> Dict[str, Any]:
        existing = self.feedback(feedback_id, tenant_id)
        if not existing:
            raise ValueError("反馈不存在或无权访问")
        if existing["confirmation_status"] == "confirmed":
            original = dict(existing["confirmed"])
            original.pop("_previous_observed_values", None)
            if dumps(original) != dumps(confirmed):
                raise BusinessConflict("confirmation_conflict", "已确认内容不同，请提交新的反馈版本")
            return existing
        if existing["confirmation_status"] in {"withdrawn", "corrected"}:
            raise BusinessConflict("invalid_state", "已撤回或纠正的反馈不能重新确认，请新增反馈")
        confirmed = dict(confirmed)
        confirmed.pop("_previous_observed_values", None)
        observations = confirmed.get("observed_values") or {}
        if not isinstance(observations, dict):
            raise ValueError("observed_values 必须为字段对象")
        if observations and not str(confirmed.get("evidence_ref") or "").strip():
            raise ValueError("确认数值事实需要填写证据引用；人工反馈不视为系统独立核验")
        for field, value in observations.items():
            if field not in {"inventory_qty", "sales_30", "unit_cost"}:
                raise ValueError("不支持确认该数值字段：" + field)
            try:
                amount = Decimal(str(value))
            except (InvalidOperation, ValueError):
                raise ValueError("确认的数量或金额不合法")
            if not amount.is_finite() or amount < 0 or (field != "unit_cost" and (amount > MAX_QUANTITY or amount != amount.to_integral_value())) or (field == "unit_cost" and money(value) is None):
                raise ValueError("确认的数量或金额不合法")
        investigation = self.one("SELECT * FROM investigations WHERE id=? AND tenant_id=?", (existing["investigation_id"], tenant_id))
        before = self.risk(investigation["risk_id"], tenant_id)
        if observations:
            confirmed["_previous_observed_values"] = {field: before[field] for field in observations}
        now = now_iso()
        self.conn.execute("UPDATE feedback_versions SET confirmed_json=?, confirmation_status='confirmed', confirmed_at=? WHERE id=? AND tenant_id=?", (dumps(confirmed), now, feedback_id, tenant_id))
        for field, value in observations.items():
            self.conn.execute("UPDATE risks SET " + field + "=? WHERE id=? AND tenant_id=?", (str(money(value)) if field == "unit_cost" else int(value), investigation["risk_id"], tenant_id))
        risk = self.risk(investigation["risk_id"], tenant_id)
        new_fact_version = int(risk["current_fact_version"]) + 1
        self._invalidate_risk_proposals(investigation["risk_id"], tenant_id)
        self.conn.execute("UPDATE risks SET investigation_status='confirmed', current_fact_version=?, evidence_level='partial' WHERE id=? AND tenant_id=?", (new_fact_version, investigation["risk_id"], tenant_id))
        self.conn.execute("UPDATE investigations SET status='confirmed' WHERE id=?", (existing["investigation_id"],))
        self.conn.execute("UPDATE workbench_drafts SET status='needs_recalculation', calculation_json=NULL, version=version+1 WHERE risk_id=? AND tenant_id=?", (investigation["risk_id"], tenant_id))
        case_content = {
            "risk_type": risk["risk_type"],
            "sku": risk["sku"],
            "store": risk["store"],
            "fact_version": new_fact_version,
            "feedback_id": feedback_id,
            "raw_feedback": existing["raw_text"],
            "confirmed": confirmed,
            "suggested_check": "核对确认字段与原始证据，并跟踪后续业务结果",
            "evidence_level": "partial",
            "outcome_status": "待观察",
        }
        self.conn.execute("INSERT INTO cases(id, tenant_id, risk_id, stage, status, content_json, actor_id, created_at) VALUES(?,?,?,?,?,?,?,?)", ("CASE-" + uuid.uuid4().hex[:10], tenant_id, investigation["risk_id"], "confirmed_investigation", "active", dumps(case_content), actor_id, now))
        self._commit()
        self.audit("feedback", feedback_id, "confirmed", {"fact_version": new_fact_version}, tenant_id, actor_id)
        return self.feedback(feedback_id, tenant_id) or {}

    @_transactional
    def revise_feedback(self, feedback_id: str, status: str, actor_id: str = "demo-user", tenant_id: str = "demo") -> Dict[str, Any]:
        """保存纠正/撤回，不删除原始反馈和历史版本。"""
        existing = self.feedback(feedback_id, tenant_id)
        if not existing:
            raise ValueError("反馈不存在或无权访问")
        if status not in ("corrected", "withdrawn"):
            raise ValueError("只允许 corrected 或 withdrawn")
        if existing["confirmation_status"] == status:
            return existing
        confirmed = dict(existing.get("confirmed") or existing.get("draft") or {})
        confirmed["revision_status"] = status
        self.conn.execute("UPDATE feedback_versions SET confirmed_json=?, confirmation_status=? WHERE id=? AND tenant_id=?", (dumps(confirmed), status, feedback_id, tenant_id))
        self.conn.execute("UPDATE cases SET status='withdrawn', revised_at=? WHERE tenant_id=? AND json_extract(content_json,'$.feedback_id')=?", (now_iso(), tenant_id, feedback_id))
        investigation = self.one("SELECT risk_id FROM investigations WHERE id=? AND tenant_id=?", (existing["investigation_id"], tenant_id))
        # Older confirmed cases had no feedback_id. Match the preserved source
        # text and confirmed content before retiring them; leave other cases alone.
        for case in self.rows("SELECT id,content_json FROM cases WHERE tenant_id=? AND risk_id=? AND stage='confirmed_investigation' AND json_extract(content_json,'$.feedback_id') IS NULL", (tenant_id, investigation["risk_id"])):
            content = json.loads(case["content_json"])
            if content.get("raw_feedback") == existing["raw_text"] and content.get("confirmed") == existing.get("confirmed"):
                self.conn.execute("UPDATE cases SET status='withdrawn', revised_at=? WHERE id=? AND tenant_id=?", (now_iso(), case["id"], tenant_id))
        history = self.rows("SELECT f.confirmed_json,f.confirmation_status FROM feedback_versions f JOIN investigations i ON i.id=f.investigation_id WHERE i.risk_id=? AND f.tenant_id=? AND f.confirmed_at IS NOT NULL ORDER BY f.confirmed_at,f.id", (investigation["risk_id"], tenant_id))
        restored = {}
        for row in history:
            facts = json.loads(row["confirmed_json"] or "{}")
            for field, value in facts.get("_previous_observed_values", {}).items():
                restored.setdefault(field, value)
        for row in history:
            if row["confirmation_status"] == "confirmed":
                restored.update(json.loads(row["confirmed_json"] or "{}").get("observed_values") or {})
        for field, value in restored.items():
            self.conn.execute("UPDATE risks SET " + field + "=? WHERE id=? AND tenant_id=?", (value, investigation["risk_id"], tenant_id))
        self.conn.execute("UPDATE risks SET current_fact_version=current_fact_version+1 WHERE id=? AND tenant_id=?", (investigation["risk_id"], tenant_id))
        active = self.one("SELECT COUNT(*) AS n FROM feedback_versions f JOIN investigations i ON i.id=f.investigation_id WHERE i.risk_id=? AND f.tenant_id=? AND f.confirmation_status='confirmed'", (investigation["risk_id"], tenant_id))["n"]
        self.conn.execute("UPDATE risks SET investigation_status=? WHERE id=? AND tenant_id=?", ("confirmed" if active else "pending", investigation["risk_id"], tenant_id))
        self.conn.execute("UPDATE investigations SET status=? WHERE id=? AND tenant_id=?", (status, existing["investigation_id"], tenant_id))
        self._invalidate_risk_proposals(investigation["risk_id"], tenant_id)
        self.conn.execute("UPDATE workbench_drafts SET status='needs_recalculation', calculation_json=NULL, version=version+1 WHERE risk_id=? AND tenant_id=?", (investigation["risk_id"], tenant_id))
        self._commit()
        self.audit("feedback", feedback_id, status, {"previous_confirmed": existing.get("confirmed")}, tenant_id, actor_id)
        return self.feedback(feedback_id, tenant_id) or {}

    @_transactional
    def mark_replan_pending(self, risk_id: int, tenant_id: str = "demo", reason: str = "重算工具失败", expected_version: Optional[int] = None) -> Dict[str, Any]:
        """事实已保存但计算失败时，让旧方案保持不可执行。"""
        proposal = self.one("SELECT current_version FROM proposals WHERE risk_id=? AND tenant_id=? ORDER BY created_at DESC LIMIT 1", (risk_id, tenant_id))
        if not proposal:
            raise ValueError("方案不存在")
        self._check_version(expected_version, proposal["current_version"])
        self.conn.execute("UPDATE proposals SET status='replan_pending' WHERE risk_id=? AND tenant_id=? AND status IN ('needs_replan','replan_pending')", (risk_id, tenant_id))
        self._commit()
        return {"status": "replan_pending", "risk_id": risk_id, "reason": reason, "fact_saved": True}

    @_transactional
    def replan(self, risk_id: int, tenant_id: str = "demo", actor_id: str = "demo-user", expected_version: Optional[int] = None) -> Dict[str, Any]:
        """根据当前事实版本创建可重新审批的方案版本，不覆写旧版。"""
        proposal = self.one("SELECT * FROM proposals WHERE risk_id=? AND tenant_id=? ORDER BY created_at DESC LIMIT 1", (risk_id, tenant_id))
        risk = self.risk(risk_id, tenant_id)
        if not proposal or not risk:
            raise ValueError("风险或方案不存在")
        self._check_version(expected_version, proposal["current_version"])
        if proposal["status"] not in ("needs_replan", "replan_pending"):
            raise BusinessConflict("invalid_state", "方案不在待重算状态")
        old = self.one("SELECT * FROM proposal_versions WHERE proposal_id=? AND version=?", (proposal["id"], proposal["current_version"]))
        if not old:
            raise ValueError("缺少当前方案版本")
        old_payload = json.loads(old["payload_json"])
        module = old_payload.get("proposal_type") or (old_payload.get("actions") or [{}])[0].get("type")
        if module not in {"transfer", "expiry-rescue", "procurement-brake"}:
            raise BusinessConflict("missing_business_data", "当前方案缺少可重算的业务类型")
        editable = {"transfer": {"quantity", "target_store_id"}, "expiry-rescue": {"transfer_qty", "promo_qty", "promo_price", "return_qty"}, "procurement-brake": {"action", "adjustment_qty", "new_payment_date"}}[module]
        updates = {k: v for k, v in (old_payload.get("input") or {}).items() if k in editable}
        if module == "transfer" and not old_payload.get("input"):
            updates["quantity"] = old_payload["actions"][0]["quantity"]
        data = self.workbench_input(module, risk_id, updates, tenant_id)
        if module == "transfer":
            data["quantity"] = min(data["quantity"], max(0, data["source_on_hand"]-data["source_safety"]), max(0, data["target_capacity"]-data["target_on_hand"]))
        calculator = {"transfer": calculate_transfer, "expiry-rescue": calculate_expiry_rescue, "procurement-brake": calculate_procurement_brake}[module]
        calculation = calculator(data)
        if not calculation["valid"]:
            raise BusinessConflict("no_feasible_plan", "当前事实下原动作不可行：" + "；".join(calculation["errors"]))
        payload = {"proposal_type": module, "input": data, "calculation": calculation,
                   "cash": calculation["cash"], "basis": {"snapshot_id": risk["snapshot_id"], "fact_version": risk["current_fact_version"], "calculation_version": TEACHER_BASELINE_VERSION, "replan_reason": "人工确认事实后实际重新计算"},
                   "diff": {"previous_version": proposal["current_version"], "previous_input": old_payload.get("input") or old_payload.get("actions"), "previous_fact_version": (old_payload.get("basis") or {}).get("fact_version"), "calculation_recomputed": True}}
        new_version = int(proposal["current_version"]) + 1
        version_id = "PV-%s-V%s" % (proposal["id"], new_version)
        self.conn.execute("INSERT INTO proposal_versions(id, proposal_id, version, payload_json, status, invalid_reason, created_at) VALUES(?,?,?,?,?,?,?)", (version_id, proposal["id"], new_version, dumps(payload), "pending_approval", None, now_iso()))
        self.conn.execute("UPDATE proposals SET current_version=?, status='pending_approval', fact_version=? WHERE id=? AND tenant_id=?", (new_version, risk["current_fact_version"], proposal["id"], tenant_id))
        self._commit()
        self.audit("proposal", proposal["id"], "replanned", {"from_version": proposal["current_version"], "to_version": new_version, "fact_version": risk["current_fact_version"]}, tenant_id, actor_id)
        return self.proposal(proposal["id"], tenant_id) or {}

    @_serialized
    def proposal(self, proposal_id: str, tenant_id: str = "demo") -> Optional[Dict[str, Any]]:
        proposal = self.one("SELECT * FROM proposals WHERE id=? AND tenant_id=?", (proposal_id, tenant_id))
        if not proposal:
            return None
        version = self.one("SELECT * FROM proposal_versions WHERE proposal_id=? AND version=?", (proposal_id, proposal["current_version"]))
        if version:
            version["payload"] = json.loads(version.pop("payload_json"))
        proposal["version"] = version
        return proposal

    @_serialized
    def proposal_versions(self, proposal_id: str, tenant_id: str = "demo") -> List[Dict[str, Any]]:
        return self.rows("SELECT pv.* FROM proposal_versions pv JOIN proposals p ON p.id=pv.proposal_id WHERE p.id=? AND p.tenant_id=? ORDER BY pv.version", (proposal_id, tenant_id))

    @staticmethod
    def _scoped_idem(tenant_id: str, operation: str, proposal_id: str, key: str) -> str:
        # 幂等键由客户端提供，表上的 UNIQUE 约束又是全局的；落库前绑定租户、操作与方案，
        # 避免一个租户的键命中或占用另一个租户（或另一个方案）的记录。
        # tenant 与客户端键是自由文本，用 JSON 数组编码保证字段边界无歧义。
        return json.dumps([tenant_id, operation, proposal_id, key], ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _check_version(expected, current):
        if expected is not None and expected != current:
            raise BusinessConflict("version_conflict", "版本已更新，请重新读取后确认", current)

    def _replay(self, row, proposal, actor_id):
        if proposal["status"] in {"needs_replan", "replan_pending", "invalidated"}:
            raise BusinessConflict("facts_changed", "此操作对应的方案已失效，请重新计算")
        if row["proposal_version"] != proposal["current_version"]:
            raise BusinessConflict("idempotency_conflict", "此幂等键已用于另一方案版本", proposal["current_version"])
        owner = row.get("actor_id") or json.loads(row.get("metadata_json") or "{}").get("created_by")
        if owner is not None and owner != actor_id:
            raise BusinessConflict("idempotency_actor_conflict", "此幂等键属于另一操作者")
        return row

    @_serialized
    def workbench_input(self, module_type, risk_id, updates, tenant_id="demo"):
        risk = self.risk(risk_id, tenant_id)
        if not risk:
            raise ValueError("风险不存在或无权访问")
        latest = self.real_inventory_snapshot(tenant_id)
        if latest and latest["id"] != risk["snapshot_id"]:
            raise BusinessConflict("stale_snapshot", "此商品不属于最新库存快照，请重新选择")
        snapshot = self.one("SELECT is_sample FROM snapshots WHERE id=? AND tenant_id=?", (risk["snapshot_id"], tenant_id))
        if not snapshot or not snapshot["is_sample"]:
            raise BusinessConflict("missing_business_data", "真实工作台需要订单、效期或配送规则，不能套用演示参数")
        base = self.default_workbench_input(module_type, risk_id)
        if not base or len(base) == 1:
            raise BusinessConflict("missing_business_data", "当前商品缺少该工作台所需事实")
        allowed = {"transfer": {"target_store_id", "quantity"},
                   "expiry-rescue": {"transfer_qty", "promo_qty", "promo_price", "return_qty"},
                   "procurement-brake": {"action", "adjustment_qty", "new_payment_date"}}[module_type]
        draft = self.workbench_draft(module_type, risk_id, tenant_id)
        for field in allowed:
            if draft and field in draft["input"]:
                base[field] = draft["input"][field]
            if field in updates:
                base[field] = updates[field]
        base["unit_cost"] = risk["unit_cost"]
        if module_type == "transfer":
            base["source_on_hand"] = risk["inventory_qty"]
            base["source_daily_sales"] = str((risk["sales_30"] or 0) / 30)
            target = next((row for row in TRANSFER_NETWORK_STORES if row[2] == base["target_store_id"]), None)
            if not target or target[2] == risk["store_id"]:
                raise ValueError("接收门店不在可用演示路线中")
            _, name, sid, stock, capacity, safety, daily, _, _, fee, eta, _ = target
            base.update(target_store=name, target_store_id=sid, target_on_hand=stock,
                        target_capacity=capacity, target_safety=safety, target_daily_sales=daily,
                        transport_fee=fee, eta_days=eta)
        elif module_type == "expiry-rescue":
            base.update(inventory_qty=risk["inventory_qty"], sales_30=risk["sales_30"])
        else:
            base["current_inventory"] = risk["inventory_qty"]
        for field in {"unit_cost", "transport_fee", "transfer_fee", "promo_fee", "promo_price"} & base.keys():
            raw = base[field]
            if raw is None and field in {"unit_cost", "promo_price"}:
                continue
            amount = money(raw)
            if amount is None or not amount.is_finite() or amount < 0:
                raise ValueError(field + "必须为非负有限金额")
            base[field] = amount
        # A full server input may be echoed, but read-only facts cannot be changed.
        for field, value in updates.items():
            if field in allowed:
                continue
            if field not in base or str(value) != str(base[field]):
                try:
                    same_number = not isinstance(value, bool) and Decimal(str(value)).is_finite() and Decimal(str(value)) == Decimal(str(base.get(field)))
                except Exception:
                    same_number = False
                if not same_number:
                    raise ValueError("不能修改服务端事实字段：" + field)
        for field in allowed:
            if field.endswith("qty") or field in ("quantity", "adjustment_qty"):
                value = base.get(field)
                if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_QUANTITY:
                    raise ValueError(field + "必须为 0 至 2147483647 的整数")
        if base["unit_cost"] is None or risk["inventory_qty"] is None or risk["sales_30"] is None:
            raise BusinessConflict("missing_business_data", "库存、销量或成本未知，请补充数据")
        return base

    def _reservation_allocations(self, proposal):
        payload = proposal["version"]["payload"]
        module = payload.get("proposal_type")
        if not module and payload.get("actions"):
            module = payload["actions"][0].get("type")
        if module not in ("transfer", "expiry-rescue", "procurement-brake"):
            return []  # Legacy non-inventory records have no inventory allocation.
        risk = self.risk(proposal["risk_id"], proposal["tenant_id"])
        if not risk:
            raise BusinessConflict("missing_business_data", "占用记录缺少商品事实")
        base = self.default_workbench_input(module, risk["id"])
        if not base or len(base) == 1 or risk["inventory_qty"] is None:
            raise BusinessConflict("missing_business_data", "缺少可核验的库存或规则")
        data = payload.get("input") or base
        if module == "transfer":
            qty = int(data.get("quantity") if payload.get("input") else payload["actions"][0]["quantity"])
            maximum = max(0, risk["inventory_qty"] - base["source_safety"])
            allocations = [("lot:" + base["lot_id"], qty, maximum)]
            target = next((row for row in TRANSFER_NETWORK_STORES if row[2] == data["target_store_id"]), None)
            if not target:
                raise BusinessConflict("invalid_route", "接收门店路线已不可用")
            allocations.append(("capacity:" + target[2] + ":" + risk["sku"], qty, target[4] - target[3]))
        elif module == "expiry-rescue":
            qty = sum(int(data.get(k) or 0) for k in ("transfer_qty", "promo_qty", "return_qty"))
            if risk["sales_30"] is None:
                raise BusinessConflict("missing_business_data", "缺少本批次销量，不能核算共同占用")
            normal_sale = min(risk["inventory_qty"], int(Decimal(base["sellable_days"]) * risk["sales_30"] / 30))
            allocations = [("lot:" + base["lot_id"], qty, risk["inventory_qty"]-normal_sale)]
        else:
            allocations = [("po:" + base["po_number"] + ":" + base["line_number"], int(data["adjustment_qty"]), int(base["open_purchase_qty"]))]
        return allocations

    def _reserve_inventory(self, proposal):
        risk = self.risk(proposal["risk_id"], proposal["tenant_id"])
        if not risk or risk["current_fact_version"] != proposal["fact_version"]:
            raise BusinessConflict("facts_changed", "事实已变化，请重新计算")
        latest = self.real_inventory_snapshot(proposal["tenant_id"])
        if latest and latest["id"] != proposal["snapshot_id"]:
            raise BusinessConflict("stale_snapshot", "方案不属于最新库存快照，不能继续执行")
        # Preserve allocations of approved/tasks created before this schema existed.
        legacy = self.rows("SELECT p.id FROM proposals p WHERE p.tenant_id=? AND p.snapshot_id=? AND p.id!=? AND p.status IN ('approved','execution_task_created') AND NOT EXISTS (SELECT 1 FROM inventory_reservations r WHERE r.proposal_id=p.id AND r.proposal_version=p.current_version)", (proposal["tenant_id"], proposal["snapshot_id"], proposal["id"]))
        for row in legacy:
            previous = self.proposal(row["id"], proposal["tenant_id"])
            for key, qty, _ in self._reservation_allocations(previous):
                self.conn.execute("INSERT INTO inventory_reservations VALUES(?,?,?,?,?,?)", (previous["tenant_id"], previous["snapshot_id"], key, previous["id"], previous["current_version"], qty))
        allocations = self._reservation_allocations(proposal)
        for key, qty, maximum in allocations:
            reserved = self.one("SELECT COALESCE(SUM(quantity),0) AS qty FROM inventory_reservations WHERE tenant_id=? AND snapshot_id=? AND resource_key=? AND NOT (proposal_id=? AND proposal_version=?)", (proposal["tenant_id"], proposal["snapshot_id"], key, proposal["id"], proposal["current_version"]))["qty"]
            if qty + reserved > maximum:
                raise BusinessConflict("inventory_conflict", "库存、收货容量或采购数量已被其他方案占用，请重新计算")
            self.conn.execute("INSERT INTO inventory_reservations VALUES(?,?,?,?,?,?) ON CONFLICT(tenant_id,proposal_id,proposal_version,resource_key) DO UPDATE SET quantity=excluded.quantity", (proposal["tenant_id"], proposal["snapshot_id"], key, proposal["id"], proposal["current_version"], qty))

    @_transactional
    def approve(self, proposal_id: str, actor_id: str = "demo-user", tenant_id: str = "demo", idem: Optional[str] = None, expected_version: Optional[int] = None) -> Dict[str, Any]:
        proposal = self.proposal(proposal_id, tenant_id)
        if not proposal:
            raise ValueError("方案不存在或无权访问")
        self._check_version(expected_version, proposal["current_version"])
        key = self._scoped_idem(tenant_id, "approve", proposal_id, idem or "approve|%s|%s" % (proposal_id, proposal["current_version"]))
        existing = self.one("SELECT * FROM approvals WHERE idempotency_key=? AND tenant_id=?", (key, tenant_id))
        if existing:
            return self._replay(existing, proposal, actor_id)
        if proposal["status"] in ("needs_replan", "invalidated", "replan_pending"):
            raise ValueError("方案版本已失效，不能审批")
        if proposal["status"] != "pending_approval":
            raise ValueError("方案尚未提交审批，或已不在待审批状态")
        self._reserve_inventory(proposal)
        approval_id = "APR-" + uuid.uuid4().hex[:10]
        version = proposal["current_version"]
        self.conn.execute("INSERT INTO approvals(id, tenant_id, proposal_id, proposal_version, actor_id, status, idempotency_key, created_at) VALUES(?,?,?,?,?,?,?,?)", (approval_id, tenant_id, proposal_id, version, actor_id, "approved", key, now_iso()))
        self.conn.execute("UPDATE proposals SET status='approved' WHERE id=? AND tenant_id=?", (proposal_id, tenant_id))
        self.conn.execute("UPDATE proposal_versions SET status='approved' WHERE proposal_id=? AND version=?", (proposal_id, version))
        self._commit()
        self.audit("proposal", proposal_id, "approved", {"version": version}, tenant_id, actor_id)
        return self.one("SELECT * FROM approvals WHERE id=?", (approval_id,)) or {}

    @_transactional
    def execute(self, proposal_id: str, actor_id: str = "demo-user", tenant_id: str = "demo", idem: Optional[str] = None, expected_version: Optional[int] = None) -> Dict[str, Any]:
        proposal = self.proposal(proposal_id, tenant_id)
        if not proposal:
            raise ValueError("方案不存在或无权访问")
        self._check_version(expected_version, proposal["current_version"])
        key = self._scoped_idem(tenant_id, "execute", proposal_id, idem or "execute|%s|%s" % (proposal_id, proposal["current_version"]))
        existing = self.one("SELECT * FROM execution_tasks WHERE idempotency_key=? AND tenant_id=?", (key, tenant_id))
        if existing:
            return self._replay(existing, proposal, actor_id)
        if proposal["status"] != "approved":
            raise ValueError("只有已批准的具体版本可以生成执行任务")
        self._reserve_inventory(proposal)
        task_id = "TASK-" + uuid.uuid4().hex[:10]
        self.conn.execute("INSERT INTO execution_tasks(id, tenant_id, proposal_id, proposal_version, status, idempotency_key, created_at, metadata_json) VALUES(?,?,?,?,?,?,?,?)", (task_id, tenant_id, proposal_id, proposal["current_version"], "draft_pending_external_execution", key, now_iso(), dumps({"external_write": False, "created_by": actor_id, "source": "manual_task_generation"})))
        self.conn.execute("UPDATE proposals SET status='execution_task_created' WHERE id=? AND tenant_id=?", (proposal_id, tenant_id))
        self._commit()
        self.audit("execution_task", task_id, "created", {"proposal_id": proposal_id, "external_write": False}, tenant_id, actor_id)
        return self.one("SELECT * FROM execution_tasks WHERE id=?", (task_id,)) or {}

    # 工作台草稿与方案沿用现有 proposal/proposal_version 作为唯一方案真相源。
    # 草稿只保存尚未提交审批的编辑输入和其计算版本，避免另起一套业务对象。
    @_serialized
    def workbench_draft(self, module_type: str, risk_id: int, tenant_id: str = "demo") -> Optional[Dict[str, Any]]:
        row = self.one("SELECT * FROM workbench_drafts WHERE tenant_id=? AND module_type=? AND risk_id=?", (tenant_id, module_type, risk_id))
        if row:
            row["input"] = json.loads(row.pop("input_json"))
            row["calculation"] = json.loads(row.pop("calculation_json")) if row.get("calculation_json") else None
        return row

    @_transactional
    def planning_drafts(self, tenant_id: str, expected_snapshot_id=None):
        """Consistent advisory view of fresh actions and remaining resources.

        Approval still rechecks every reservation inside its own transaction.
        Committed actions are excluded, but their allocations remain occupied.
        """
        latest = self.real_inventory_snapshot(tenant_id)
        if expected_snapshot_id:
            active = latest or self.one("SELECT id FROM snapshots WHERE tenant_id=? ORDER BY created_at DESC LIMIT 1", (tenant_id,))
            if not active or active["id"] != expected_snapshot_id:
                raise BusinessConflict("stale_snapshot", "规划期间快照已变化，请重新模拟")
        reservations = self.rows("SELECT * FROM inventory_reservations WHERE tenant_id=?", (tenant_id,))
        occupied = {}
        for reservation in reservations:
            key = (reservation["snapshot_id"], reservation["resource_key"])
            occupied[key] = occupied.get(key, 0) + reservation["quantity"]
        legacy = self.rows("SELECT p.id FROM proposals p WHERE p.tenant_id=? AND p.status IN ('approved','execution_task_created') AND NOT EXISTS (SELECT 1 FROM inventory_reservations r WHERE r.tenant_id=p.tenant_id AND r.proposal_id=p.id AND r.proposal_version=p.current_version)", (tenant_id,))
        for row in legacy:
            proposal = self.proposal(row["id"], tenant_id)
            for resource, quantity, _ in self._reservation_allocations(proposal):
                key = (proposal["snapshot_id"], resource)
                occupied[key] = occupied.get(key, 0) + quantity
        eligible = []
        for row in self.rows("SELECT * FROM workbench_drafts WHERE tenant_id=? AND status IN ('calculated','saved')", (tenant_id,)):
            risk = self.risk(row["risk_id"], tenant_id)
            if not risk or (latest and risk["snapshot_id"] != latest["id"]):
                continue
            data = json.loads(row["input_json"])
            calculation = json.loads(row["calculation_json"]) if row["calculation_json"] else None
            if not calculation or not calculation.get("valid"):
                continue
            proposal = self.proposal(row["proposal_id"], tenant_id) if row["proposal_id"] else None
            if row["proposal_id"]:
                if (not proposal or not proposal["version"]
                        or proposal["status"] not in ("draft", "pending_approval")
                        or proposal["version"]["status"] not in ("draft", "pending_approval")
                        or self.one("SELECT id FROM execution_tasks WHERE tenant_id=? AND proposal_id=? AND proposal_version=?", (tenant_id, proposal["id"], proposal["current_version"]))):
                    continue
                payload = proposal["version"]["payload"]
                basis = payload.get("basis") or {}
                if (proposal["fact_version"] != risk["current_fact_version"]
                        or proposal["snapshot_id"] != risk["snapshot_id"]
                        or basis.get("proposal_version") != proposal["current_version"]
                        or basis.get("fact_version") != risk["current_fact_version"]
                        or basis.get("snapshot_id") != risk["snapshot_id"]
                        or basis.get("risk_id") != risk["id"]
                        or payload.get("input") != data
                        or payload.get("calculation") != calculation):
                    continue
            try:
                canonical = self.workbench_input(row["module_type"], risk["id"], data, tenant_id)
                if json.loads(dumps(canonical)) != data:
                    continue
                allocation_source = proposal or {
                    "risk_id": risk["id"], "tenant_id": tenant_id,
                    "version": {"payload": {"proposal_type": row["module_type"], "input": data}},
                }
                resources = []
                for resource, quantity, maximum in self._reservation_allocations(allocation_source):
                    remaining = max(0, maximum - occupied.get((risk["snapshot_id"], resource), 0))
                    resources.append({"key": resource, "quantity": quantity, "remaining": remaining})
                if any(item["quantity"] > item["remaining"] for item in resources):
                    continue
            except ValueError:
                continue
            row.update(resources=resources, snapshot_id=risk["snapshot_id"],
                       fact_version=risk["current_fact_version"],
                       proposal_version=proposal["current_version"] if proposal else None)
            eligible.append(row)
        return eligible

    def default_workbench_input(self, module_type: str, risk_id: Optional[int] = None) -> Dict[str, Any]:
        if module_type == "expiry-rescue":
            value = dict(EXPIRY_WORKBENCH_DEFAULTS.get(risk_id) or {})
        elif module_type == "transfer":
            value = dict(TRANSFER_WORKBENCH_DEFAULTS.get(risk_id) or {})
        elif module_type == "procurement-brake":
            value = dict(PROCUREMENT_WORKBENCH_DEFAULTS.get(risk_id) or {})
        else:
            value = dict(WORKBENCH_DEFAULTS.get(module_type) or {})
        if risk_id is not None:
            value["risk_id"] = risk_id
        return value

    @_transactional
    def save_workbench_draft(
        self,
        module_type: str,
        risk_id: int,
        input_data: Dict[str, Any],
        calculation: Optional[Dict[str, Any]],
        status: str,
        actor_id: str = "demo-user",
        tenant_id: str = "demo",
        expected_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        existing = self.workbench_draft(module_type, risk_id, tenant_id)
        self._check_version(expected_version, existing["version"] if existing else 0)
        now = now_iso()
        if existing:
            version = int(existing["version"]) + 1
            self.conn.execute(
                "UPDATE workbench_drafts SET version=?, status=?, input_json=?, calculation_json=?, updated_by=?, updated_at=? WHERE id=?",
                (version, status, dumps(input_data), dumps(calculation) if calculation is not None else None, actor_id, now, existing["id"]),
            )
            draft_id = existing["id"]
        else:
            draft_id = "WBD-" + uuid.uuid4().hex[:10]
            version = 1
            self.conn.execute(
                "INSERT INTO workbench_drafts(id, tenant_id, module_type, risk_id, version, status, input_json, calculation_json, proposal_id, updated_by, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (draft_id, tenant_id, module_type, risk_id, version, status, dumps(input_data), dumps(calculation) if calculation is not None else None, None, actor_id, now),
            )
        self._commit()
        self.audit("workbench_draft", draft_id, "calculated" if calculation else "input_changed", {"module_type": module_type, "risk_id": risk_id, "version": version, "status": status}, tenant_id, actor_id)
        return self.workbench_draft(module_type, risk_id, tenant_id) or {}

    @_transactional
    def mark_workbench_dirty(self, module_type: str, risk_id: int, input_data: Dict[str, Any], actor_id: str = "demo-user", tenant_id: str = "demo", expected_version: Optional[int] = None) -> Dict[str, Any]:
        return self.save_workbench_draft(module_type, risk_id, input_data, None, "needs_recalculation", actor_id, tenant_id, expected_version)

    @_transactional
    def save_workbench_proposal(
        self,
        module_type: str,
        risk_id: int,
        input_data: Dict[str, Any],
        calculation: Dict[str, Any],
        actor_id: str = "demo-user",
        tenant_id: str = "demo",
        expected_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        if not calculation.get("valid"):
            raise ValueError("存在约束错误，不能保存方案")
        risk = self.risk(risk_id, tenant_id)
        if not risk:
            raise ValueError("风险不存在或无权访问")
        previous = self.one("SELECT * FROM proposals WHERE tenant_id=? AND risk_id=? ORDER BY created_at DESC LIMIT 1", (tenant_id, risk_id))
        self._check_version(expected_version, previous["current_version"] if previous else 0)
        # 已生成执行任务的版本保持不可变，编辑后另建一张待审批方案。
        if previous and previous["status"] != "execution_task_created":
            proposal_id = previous["id"]
            self.conn.execute("DELETE FROM inventory_reservations WHERE tenant_id=? AND proposal_id=?", (tenant_id, proposal_id))
            old_version = int(previous["current_version"])
            new_version = old_version + 1
            self.conn.execute("UPDATE proposal_versions SET status='invalidated', invalid_reason='工作台输入已修改，需要重新审批' WHERE proposal_id=? AND version=?", (proposal_id, old_version))
        else:
            proposal_id = "PROP-" + uuid.uuid4().hex[:10].upper()
            new_version = 1
            self.conn.execute("INSERT INTO proposals(id, tenant_id, risk_id, current_version, status, snapshot_id, fact_version, created_at) VALUES(?,?,?,?,?,?,?,?)", (proposal_id, tenant_id, risk_id, new_version, "draft", risk["snapshot_id"], risk["current_fact_version"], now_iso()))
        payload = {
            "proposal_type": module_type,
            "input": input_data,
            "calculation": calculation,
            "cash": calculation.get("cash") or {},
            "basis": {"snapshot_id": risk["snapshot_id"], "fact_version": risk["current_fact_version"], "calculation_version": TEACHER_BASELINE_VERSION, "proposal_version": new_version, "risk_id": risk_id},
        }
        self.conn.execute("INSERT INTO proposal_versions(id, proposal_id, version, payload_json, status, invalid_reason, created_at) VALUES(?,?,?,?,?,?,?)", ("PV-%s-V%s" % (proposal_id, new_version), proposal_id, new_version, dumps(payload), "draft", None, now_iso()))
        self.conn.execute("UPDATE proposals SET current_version=?, status='draft', snapshot_id=?, fact_version=? WHERE id=? AND tenant_id=?", (new_version, risk["snapshot_id"], risk["current_fact_version"], proposal_id, tenant_id))
        self.conn.execute("UPDATE workbench_drafts SET proposal_id=?, status='saved', calculation_json=? WHERE tenant_id=? AND module_type=? AND risk_id=?", (proposal_id, dumps(calculation), tenant_id, module_type, risk_id))
        self._commit()
        self.audit("proposal", proposal_id, "workbench_saved", {"module_type": module_type, "version": new_version, "risk_id": risk_id}, tenant_id, actor_id)
        return self.proposal(proposal_id, tenant_id) or {}

    @_transactional
    def prepare_workbench(self, module_type, risk_id, updates, expected_version, actor_id="demo-user", tenant_id="demo", calculate=False):
        data = self.workbench_input(module_type, risk_id, updates, tenant_id)
        calculation = None
        status = "needs_recalculation"
        if calculate:
            calculator = {"transfer": calculate_transfer, "expiry-rescue": calculate_expiry_rescue, "procurement-brake": calculate_procurement_brake}[module_type]
            calculation = calculator(data)
            status = "calculated" if calculation["valid"] else "blocked"
        draft = self.save_workbench_draft(module_type, risk_id, data, calculation, status, actor_id, tenant_id, expected_version)
        return {"input": data, "calculation": calculation, "draft": draft}

    @_transactional
    def save_workbench(self, module_type, risk_id, updates, expected_version, expected_proposal_version, actor_id="demo-user", tenant_id="demo"):
        data = self.workbench_input(module_type, risk_id, updates, tenant_id)
        calculator = {"transfer": calculate_transfer, "expiry-rescue": calculate_expiry_rescue, "procurement-brake": calculate_procurement_brake}[module_type]
        calculation = calculator(data)
        if not calculation["valid"]:
            raise ValueError("；".join(calculation["errors"]))
        self.save_workbench_draft(module_type, risk_id, data, calculation, "calculated", actor_id, tenant_id, expected_version)
        proposal = self.save_workbench_proposal(module_type, risk_id, data, calculation, actor_id, tenant_id, expected_proposal_version)
        return {"proposal": proposal, "calculation": calculation, "draft": self.workbench_draft(module_type, risk_id, tenant_id)}

    @_transactional
    def submit_proposal(self, proposal_id: str, actor_id: str = "demo-user", tenant_id: str = "demo", expected_version: Optional[int] = None) -> Dict[str, Any]:
        proposal = self.proposal(proposal_id, tenant_id)
        if not proposal:
            raise ValueError("方案不存在或无权访问")
        self._check_version(expected_version, proposal["current_version"])
        if proposal["status"] == "pending_approval":
            return proposal
        if proposal["status"] != "draft" or not proposal.get("version") or proposal["version"].get("status") != "draft":
            raise ValueError("只有已保存且未失效的草稿方案可以提交审批")
        self.conn.execute("UPDATE proposals SET status='pending_approval' WHERE id=? AND tenant_id=?", (proposal_id, tenant_id))
        self.conn.execute("UPDATE proposal_versions SET status='pending_approval' WHERE proposal_id=? AND version=?", (proposal_id, proposal["current_version"]))
        self._commit()
        self.audit("proposal", proposal_id, "submitted_for_approval", {"version": proposal["current_version"]}, tenant_id, actor_id)
        return self.proposal(proposal_id, tenant_id) or {}

    @_serialized
    def execution_tasks(self, tenant_id: str = "demo") -> List[Dict[str, Any]]:
        rows = self.rows("SELECT * FROM execution_tasks WHERE tenant_id=? ORDER BY created_at DESC", (tenant_id,))
        for row in rows:
            row["metadata"] = json.loads(row.pop("metadata_json"))
        return rows

    @_transactional
    def update_execution_status(
        self,
        task_id: str,
        status: str,
        receipt_ref: Optional[str] = None,
        actual_cash: Optional[Any] = None,
        actor_id: str = "demo-user",
        tenant_id: str = "demo",
        expected_version: Optional[int] = None,
        confirmation_method: str = "manual",
    ) -> Dict[str, Any]:
        task = self.one("SELECT * FROM execution_tasks WHERE id=? AND tenant_id=?", (task_id, tenant_id))
        if not task:
            raise ValueError("执行任务不存在或无权访问")
        self._check_version(expected_version, task["version"])
        if task["status"] == "completed":
            metadata = json.loads(task.get("metadata_json") or "{}")
            if status != "completed" or receipt_ref != metadata.get("receipt_ref") or (actual_cash is not None and money(actual_cash) != money(metadata.get("actual_cash"))):
                raise BusinessConflict("invalid_transition", "已完成的任务不能回退状态或覆盖最终回执")
            task["metadata"] = metadata
            task.pop("metadata_json")
            return task
        transitions = {"draft_pending_external_execution": {"pending_dispatch", "exception"}, "pending_dispatch": {"in_transit", "exception"}, "in_transit": {"awaiting_receipt", "exception"}, "awaiting_receipt": {"received", "exception"}, "received": {"completed", "exception"}, "exception": {"pending_dispatch"}, "completed": set()}
        manual_completion = confirmation_method == "manual" and status in {"received", "completed"}
        if status != task["status"] and status not in transitions.get(task["status"], set()) and not manual_completion:
            raise BusinessConflict("invalid_transition", "执行状态转换不合法")
        if confirmation_method != "manual":
            raise ValueError("未接入外部系统回执，仅支持明确的人工确认")
        if actual_cash is not None and (money(actual_cash) is None or not money(actual_cash).is_finite() or money(actual_cash) < 0):
            raise ValueError("实际回款必须是非负有限金额")
        actual_cash = money(actual_cash)
        if actual_cash is not None and not (receipt_ref and receipt_ref.strip()):
            raise ValueError("实际回款需要填写人工回执号")
        allowed = {"pending_dispatch", "in_transit", "awaiting_receipt", "received", "completed", "exception"}
        if status not in allowed:
            raise ValueError("不支持的执行状态")
        if status in ("received", "completed") and not (receipt_ref and receipt_ref.strip()):
            raise ValueError("收货或完成需要填写执行回执号")
        metadata = json.loads(task.get("metadata_json") or "{}")
        timeline = list(metadata.get("timeline") or [])
        timeline.append({"status": status, "at": now_iso(), "receipt_ref": receipt_ref, "actual_cash": actual_cash, "actor_id": actor_id, "confirmation_method": confirmation_method})
        metadata.update({"external_write": False, "confirmation_method": confirmation_method, "confirmed_by": actor_id, "timeline": timeline, "receipt_ref": receipt_ref or metadata.get("receipt_ref"), "actual_cash": actual_cash if actual_cash is not None else metadata.get("actual_cash")})
        self.conn.execute("UPDATE execution_tasks SET status=?, metadata_json=?, version=version+1 WHERE id=? AND tenant_id=?", (status, dumps(metadata), task_id, tenant_id))
        self._commit()
        self.audit("execution_task", task_id, "status_updated", {"status": status, "receipt_ref": receipt_ref, "actual_cash": actual_cash}, tenant_id, actor_id)
        result = self.one("SELECT * FROM execution_tasks WHERE id=?", (task_id,)) or {}
        result["metadata"] = json.loads(result.pop("metadata_json"))
        return result

    @_transactional
    def import_inventory(self, filename, rows, as_of_date, actor_id="demo-user", tenant_id="demo", duplicates=0):
        digest = inventory_fingerprint(tenant_id, rows, as_of_date)
        snapshot_id = "file-inventory-" + digest
        existing = self.one("SELECT * FROM real_inventory_snapshots WHERE id=? AND tenant_id=?", (snapshot_id, tenant_id))
        if not existing:
            # Old fingerprints depended on CSV order. Compare immutable source
            # lines, never effective risks that may have confirmed corrections.
            for previous in self.rows("SELECT r.* FROM real_inventory_snapshots r JOIN snapshots s ON s.id=r.id AND s.tenant_id=r.tenant_id WHERE r.tenant_id=? AND r.as_of_date IS ? AND r.record_count=? AND s.kind='inventory_file' ORDER BY r.created_at DESC, r.id DESC", (tenant_id, as_of_date, len(rows))):
                metadata = json.loads(previous["metadata_json"])
                semantic = metadata.get("semantic_sha256")
                if not semantic:
                    source = self.rows("SELECT sku, org_code AS store_id, org_name AS store, product_name AS product, unit, inventory_qty, latest_cost AS unit_cost, sales_30, sales_90, sales_cost_30, stat_class, purchase_status FROM real_inventory_lines WHERE snapshot_id=? AND tenant_id=?", (previous["id"], tenant_id))
                    normalized, errors, _ = inventory_rows(source)
                    if errors or len(normalized) != len(rows):
                        continue
                    semantic = inventory_fingerprint(tenant_id, normalized, previous["as_of_date"])
                if semantic == digest:
                    existing = previous
                    snapshot_id = previous["id"]
                    metadata.update(semantic_sha256=digest, fingerprint_version=2)
                    for table in ("snapshots", "real_inventory_snapshots"):
                        self.conn.execute(f"UPDATE {table} SET metadata_json=? WHERE id=? AND tenant_id=?", (dumps(metadata), snapshot_id, tenant_id))
                    break
        if not existing:
            now = now_iso()
            for old_risk in self.rows("SELECT id FROM risks WHERE tenant_id=?", (tenant_id,)):
                self._invalidate_risk_proposals(old_risk["id"], tenant_id)
            self.conn.execute("UPDATE workbench_drafts SET status='needs_recalculation', calculation_json=NULL, version=version+1 WHERE tenant_id=?", (tenant_id,))
            total = sum((row["cost_amount"] for row in rows), money(0))
            metadata = {"source_filename": filename, "content_sha256": digest, "semantic_sha256": digest, "fingerprint_version": 2, "as_of_date_basis": "用户指定" if as_of_date else "unknown", "teacher_baseline_version": TEACHER_BASELINE_VERSION, "quality": {"raw_rows": len(rows)+duplicates, "deduplicated_rows": duplicates}, "missing_fields": ["accounts", "purchase_orders", "expiry_batches", "replenishment_rules"]}
            baselines = [teacher_baseline({**row, "inventory_amount": row["cost_amount"]}) for row in rows]
            metadata["teacher_baseline_missing_fields"] = sorted({field for baseline in baselines for field in baseline["missing_fields"]})
            metadata["teacher_baseline_incomplete_rows"] = sum(bool(baseline["missing_fields"]) for baseline in baselines)
            self.conn.execute("INSERT INTO snapshots VALUES(?,?,?,?,?,?,?)", (snapshot_id, tenant_id, "inventory_file", now, filename, 0, dumps(metadata)))
            self.conn.execute("INSERT INTO real_inventory_snapshots VALUES(?,?,?,?,?,?,?,?,?,?,?)", (snapshot_id, tenant_id, filename, as_of_date, now, len(rows), len({r["store_id"] for r in rows}), len({r["sku"] for r in rows}), str(total), None, dumps(metadata)))
            for row, baseline in zip(rows, baselines):
                # The detail API reads peers from snapshot lines; do not duplicate
                # every SKU's peer list in every risk (quadratic import growth).
                comparison = []
                cursor = self.conn.execute("INSERT INTO risks(tenant_id,snapshot_id,sku,product,store,store_id,sales_30,comparison_json,inventory_qty,unit_cost,tags_json,days_to_sell,risk_type,priority,observation,evidence_level,missing_fields_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (tenant_id, snapshot_id, row["sku"], row["product"], row["store"], row["store_id"], row["sales_30"], dumps(comparison), row["inventory_qty"], str(row["unit_cost"]), dumps(["slow"] if baseline["candidate"] else []), None if not row["sales_30"] else round(row["inventory_qty"]*30/row["sales_30"]), "滞销", baseline.get("priority") or "待补充", "文件库存快照；原因待人工核查", "partial", dumps(list(baseline["missing_fields"])+["verified_cause"]), now))
                values = {"snapshot_id": snapshot_id, "tenant_id": tenant_id, "risk_id": cursor.lastrowid, "org_code": row["store_id"], "org_name": row["store"], "sku": row["sku"], "product_name": row["product"], "unit": row["unit"], "inventory_qty": row["inventory_qty"], "available_qty": row["inventory_qty"], "latest_cost": float(row["unit_cost"]), "cost_amount": float(row["cost_amount"]), "sales_30": row["sales_30"], "sales_90": row["sales_90"], "sales_cost_30": float(row["sales_cost_30"]) if row["sales_cost_30"] is not None else None, "stat_class": row["stat_class"], "purchase_status": row["purchase_status"], "teacher_monthly_sales": baseline.get("monthly_sales"), "teacher_ratio": baseline.get("teacher_ratio"), "reduction_ratio": baseline.get("reduction_ratio"), "teacher_target_inventory_amount": baseline.get("target_inventory_amount"), "teacher_suggested_reduction_amount": baseline.get("suggested_reduction_amount"), "teacher_reference_reduction_qty": baseline.get("reference_reduction_quantity"), "teacher_priority": baseline.get("priority"), "teacher_trigger_reason": baseline.get("trigger_reason"), "teacher_candidate": int(baseline["candidate"]), "teacher_eligible": int(baseline["eligible"])}
                values.update(teacher_stockout=int(baseline["stockout"]) if baseline["stockout"] is not None else None,
                              teacher_near_stockout=int(baseline["near_stockout"]) if baseline["near_stockout"] is not None else None)
                self.conn.execute("INSERT INTO real_inventory_lines("+",".join(values)+") VALUES("+",".join("?" for _ in values)+")", tuple(values.values()))
            self.audit("snapshot", snapshot_id, "inventory_imported", {"rows": len(rows), "sha256": digest}, tenant_id, actor_id)
        original_digest = json.loads(existing["metadata_json"]).get("content_sha256", digest) if existing else digest
        summary = {"rows": len(rows), "data_kind": "inventory", "snapshot_id": snapshot_id, "content_sha256": original_digest, "semantic_sha256": digest, "fingerprint_version": 2, "deduplicated_rows": duplicates, "replayed": bool(existing), "as_of_date": as_of_date, "next_step": "正式快照已保存，库存诊断已使用该数据；缺少采购与效期事实时不生成动作"}
        return self.add_data_import(filename, "erp_file", "imported", summary, [], actor_id, tenant_id)

    @_transactional
    def add_data_import(self, filename: str, mode: str, status: str, summary: Dict[str, Any], errors: List[Dict[str, Any]], actor_id: str = "demo-user", tenant_id: str = "demo") -> Dict[str, Any]:
        import_id = "IMP-" + uuid.uuid4().hex[:10]
        self.conn.execute("INSERT INTO data_imports(id, tenant_id, filename, mode, status, summary_json, errors_json, created_at, actor_id) VALUES(?,?,?,?,?,?,?,?,?)", (import_id, tenant_id, filename, mode, status, dumps(summary), dumps(errors), now_iso(), actor_id))
        self._commit()
        return self.one("SELECT * FROM data_imports WHERE id=?", (import_id,)) or {}

    @_serialized
    def data_imports(self, tenant_id: str = "demo") -> List[Dict[str, Any]]:
        rows = self.rows("SELECT * FROM data_imports WHERE tenant_id=? ORDER BY created_at DESC", (tenant_id,))
        for row in rows:
            row["summary"] = json.loads(row.pop("summary_json"))
            row["errors"] = json.loads(row.pop("errors_json"))
        return rows

    @_serialized
    def real_inventory_snapshot(self, tenant_id: str = "demo") -> Optional[Dict[str, Any]]:
        row = self.one(
            "SELECT * FROM real_inventory_snapshots WHERE tenant_id=? ORDER BY created_at DESC LIMIT 1",
            (tenant_id,),
        )
        if row:
            row["metadata"] = json.loads(row.pop("metadata_json") or "{}")
            row["cost_total"] = money(row["cost_total"])
            row["untaxed_cost_total"] = money(row["untaxed_cost_total"])
        return row

    @_serialized
    def real_inventory_store_summary(self, snapshot_id: str, tenant_id: str = "demo") -> List[Dict[str, Any]]:
        rows = self.rows(
            """
            SELECT org_code, org_name,
                   COUNT(DISTINCT sku) AS categories,
                   SUM(inventory_qty) AS inventory_qty,
                   SUM(available_qty) AS available_qty,
                   SUM(cost_amount) AS inventory_value,
                   SUM(untaxed_cost_amount) AS untaxed_inventory_value,
                   SUM(CASE WHEN purchase_status='停止采购' THEN cost_amount ELSE 0 END) AS stopped_purchase_value,
                   SUM(CASE WHEN purchase_status='停止采购' THEN 1 ELSE 0 END) AS stopped_purchase_rows,
                   SUM(CASE WHEN teacher_candidate=1 THEN 1 ELSE 0 END) AS slow_moving_skus,
                   SUM(CASE WHEN teacher_candidate=1 THEN cost_amount ELSE 0 END) AS candidate_inventory_value,
                   SUM(CASE WHEN teacher_candidate=1 THEN teacher_suggested_reduction_amount ELSE 0 END) AS suggested_reduction_amount,
                   SUM(CASE WHEN teacher_candidate=1 AND teacher_priority='P1' THEN 1 ELSE 0 END) AS p1_count,
                   SUM(CASE WHEN teacher_candidate=1 AND teacher_priority='P2' THEN 1 ELSE 0 END) AS p2_count,
                   SUM(CASE WHEN teacher_candidate=1 AND teacher_priority='P3' THEN 1 ELSE 0 END) AS p3_count
            FROM real_inventory_lines
            WHERE snapshot_id=? AND tenant_id=?
            GROUP BY org_code, org_name
            ORDER BY inventory_value DESC
            """,
            (snapshot_id, tenant_id),
        )
        for row in rows:
            for key in ("categories", "stopped_purchase_rows", "slow_moving_skus", "p1_count", "p2_count", "p3_count"):
                row[key] = int(row.get(key) or 0)
            for key in (
                "inventory_qty", "available_qty", "inventory_value", "untaxed_inventory_value", "stopped_purchase_value",
                "candidate_inventory_value", "suggested_reduction_amount",
            ):
                row[key] = float(row.get(key) or 0)
        return rows

    @_serialized
    def real_inventory_attention_items(self, snapshot_id: str, tenant_id: str = "demo", limit_per_store: int = 5) -> List[Dict[str, Any]]:
        """每店按库存成本取前几项已计算的候选，供经营总览下钻展示。"""
        return self.rows(
            """
            SELECT id, org_code, sku, product_name, cost_amount,
                   teacher_priority, teacher_trigger_reason
            FROM (
                SELECT COALESCE(risk_id,rowid) AS id, org_code, sku, product_name, cost_amount,
                       teacher_priority, teacher_trigger_reason,
                       ROW_NUMBER() OVER (
                           PARTITION BY org_code ORDER BY COALESCE(cost_amount, 0) DESC, sku
                       ) AS item_rank
                FROM real_inventory_lines
                WHERE snapshot_id=? AND tenant_id=? AND teacher_candidate=1
            )
            WHERE item_rank<=?
            ORDER BY org_code, item_rank
            """,
            (snapshot_id, tenant_id, max(1, int(limit_per_store))),
        )

    @_serialized
    def real_teacher_baseline_summary(self, snapshot_id: str, tenant_id: str = "demo") -> Dict[str, Any]:
        row = self.one(
            """
            SELECT
              SUM(CASE WHEN teacher_candidate=1 THEN 1 ELSE 0 END) AS candidate_count,
              SUM(CASE WHEN teacher_candidate=1 AND teacher_priority='P1' THEN 1 ELSE 0 END) AS p1_count,
              SUM(CASE WHEN teacher_candidate=1 AND teacher_priority='P2' THEN 1 ELSE 0 END) AS p2_count,
              SUM(CASE WHEN teacher_candidate=1 AND teacher_priority='P3' THEN 1 ELSE 0 END) AS p3_count,
              SUM(CASE WHEN teacher_candidate=1 THEN cost_amount ELSE 0 END) AS candidate_inventory_amount,
              SUM(CASE WHEN teacher_candidate=1 THEN teacher_target_inventory_amount ELSE 0 END) AS target_inventory_amount,
              SUM(CASE WHEN teacher_candidate=1 THEN teacher_suggested_reduction_amount ELSE 0 END) AS suggested_reduction_amount
            FROM real_inventory_lines
            WHERE snapshot_id=? AND tenant_id=?
            """,
            (snapshot_id, tenant_id),
        ) or {}
        return {
            key: int(row.get(key) or 0) if key.endswith("_count") else round(float(row.get(key) or 0), 2)
            for key in (
                "candidate_count", "p1_count", "p2_count", "p3_count", "candidate_inventory_amount",
                "target_inventory_amount", "suggested_reduction_amount",
            )
        }

    @_serialized
    def real_teacher_candidates(
        self,
        snapshot_id: str,
        tenant_id: str = "demo",
        limit: int = 300,
        priority: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        priority_filter = " AND teacher_priority=?" if priority in {"P1", "P2", "P3"} else ""
        parameters: List[Any] = [snapshot_id, tenant_id]
        if priority_filter:
            parameters.append(priority)
        parameters.append(int(limit))
        return self.rows(
            """ 
            SELECT COALESCE(risk_id,rowid) AS id, snapshot_id, org_code, org_name, sku, product_name, unit,
                   inventory_qty, cost_amount, sales_30, sales_90, sales_cost_30, purchase_status,
                   stat_class, teacher_monthly_sales, teacher_ratio, reduction_ratio,
                   teacher_target_inventory_amount, teacher_suggested_reduction_amount,
                   teacher_reference_reduction_qty, teacher_priority, teacher_trigger_reason,
                   teacher_candidate, teacher_eligible, teacher_stockout, teacher_near_stockout,
                   store_price, member_price
            FROM real_inventory_lines
            WHERE snapshot_id=? AND tenant_id=? AND teacher_candidate=1%s
            ORDER BY CASE teacher_priority WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END,
                     teacher_suggested_reduction_amount DESC, cost_amount DESC
            LIMIT ?
            """ % priority_filter,
            tuple(parameters),
        )

    @_serialized
    def real_teacher_line(self, snapshot_id: str, line_id: int, tenant_id: str = "demo") -> Optional[Dict[str, Any]]:
        return self.one(
            """
            SELECT COALESCE(risk_id,rowid) AS id, snapshot_id, org_code, org_name, sku, product_name, unit,
                   inventory_qty, cost_amount, sales_30, sales_90, sales_cost_30, purchase_status,
                   stat_class, teacher_monthly_sales, teacher_ratio, reduction_ratio,
                   teacher_target_inventory_amount, teacher_suggested_reduction_amount,
                   teacher_reference_reduction_qty, teacher_priority, teacher_trigger_reason,
                   teacher_candidate, teacher_eligible, teacher_stockout, teacher_near_stockout,
                   store_price, member_price
            FROM real_inventory_lines
            WHERE snapshot_id=? AND tenant_id=? AND COALESCE(risk_id,rowid)=? AND teacher_candidate=1
            """,
            (snapshot_id, tenant_id, int(line_id)),
        )

    @_serialized
    def real_sku_sales_comparison(self, snapshot_id: str, sku: str, org_code: str, tenant_id: str = "demo") -> List[float]:
        rows = self.rows(
            """
            SELECT sales_30 FROM real_inventory_lines
            WHERE snapshot_id=? AND tenant_id=? AND sku=? AND org_code<>? AND sales_30 IS NOT NULL
            """,
            (snapshot_id, tenant_id, sku, org_code),
        )
        return [float(row["sales_30"]) for row in rows]

    @_serialized
    def real_inventory_top_lines(self, snapshot_id: str, tenant_id: str = "demo", limit: int = 20) -> List[Dict[str, Any]]:
        rows = self.rows(
            """
            SELECT org_code, org_name, sku, product_name, unit, inventory_qty,
                   available_qty, latest_cost, cost_amount, purchase_status
            FROM real_inventory_lines
            WHERE snapshot_id=? AND tenant_id=?
            ORDER BY cost_amount DESC
            LIMIT ?
            """,
            (snapshot_id, tenant_id, int(limit)),
        )
        return rows

    @_transactional
    def add_case(self, content: Dict[str, Any], risk_id: Optional[int], actor_id: str = "demo-user", tenant_id: str = "demo") -> Dict[str, Any]:
        case_id = "CASE-" + uuid.uuid4().hex[:10]
        self.conn.execute("INSERT INTO cases(id, tenant_id, risk_id, stage, status, content_json, actor_id, created_at) VALUES(?,?,?,?,?,?,?,?)", (case_id, tenant_id, risk_id, content.get("stage", "confirmed_investigation"), content.get("status", "active"), dumps(content), actor_id, now_iso()))
        self._commit()
        return self.case(case_id, tenant_id) or {}

    @_serialized
    def case(self, case_id: str, tenant_id: str = "demo") -> Optional[Dict[str, Any]]:
        row = self.one("SELECT * FROM cases WHERE id=? AND tenant_id=?", (case_id, tenant_id))
        if row:
            row["content"] = json.loads(row.pop("content_json"))
        return row

    @_serialized
    def cases(self, tenant_id: str = "demo", risk_type: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = self.rows("SELECT * FROM cases WHERE tenant_id=? AND status!='withdrawn' ORDER BY created_at DESC", (tenant_id,))
        result = []
        for row in rows:
            row["content"] = json.loads(row.pop("content_json"))
            if risk_type and row["content"].get("risk_type") != risk_type:
                continue
            result.append(row)
        return result

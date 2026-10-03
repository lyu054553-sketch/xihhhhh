"""SQLite 持久化：开发和黑客松交付阶段的最小真相源。"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Iterable, List, Optional

from .domain import TEACHER_BASELINE_VERSION, evidence_label, evidence_level, money


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
  created_at TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}',
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


class Store:
    def __init__(self, path: str = "inventory_cash_agent.db") -> None:
        self.path = path
        # check_same_thread=False permits cross-thread use; it does not serialize
        # execute/fetch, statement-cache access or multi-statement mutations.
        # Nested Store calls need a reentrant lock on the same connection.
        self._lock = RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate_real_inventory_lines()
        self.conn.commit()

    @_serialized
    def _migrate_real_inventory_lines(self) -> None:
        """为已导入的库存快照补齐老师口径字段，不重建或删除历史快照。"""
        columns = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(real_inventory_lines)").fetchall()
        }
        additions = {
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

    @_serialized
    def reset_demo(self) -> None:
        for table in [
            "audit_events", "cases", "cash_events", "execution_tasks", "approvals",
            "proposal_versions", "proposals", "feedback_versions", "investigations", "workbench_drafts", "data_imports", "risks", "snapshots"
        ]:
            self.conn.execute("DELETE FROM %s" % table)
        self.conn.commit()
        self.seed_demo()

    @_serialized
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
            self.conn.execute("UPDATE snapshots SET metadata_json=? WHERE id=?", (json.dumps(metadata, ensure_ascii=False), sample["id"]))
            self.conn.execute("UPDATE risks SET observation=? WHERE id=6 AND tenant_id='demo' AND snapshot_id='snapshot-demo-v1' AND observation=?", ("批次剩余可售时间仅14天，按当前销量预计无法售完。", "批次距最晚处置日仅14天，按当前销量预计无法售完。"))
            snack_names = {'钙维生素D软胶囊': '每日坚果礼盒 750g', '阿胶块 250g': '炭烤腰果礼盒 600g', '藿香正气口服液': '纯牛奶整箱 250ml×24', '乳酸菌素片 32片': '酸奶夹心饼干整箱 100g×12', '血糖试纸 50片': '山楂果脯礼盒 1kg', '复方氨酚烷胺胶囊': '海盐薯片分享装 80g×8', '维生素C泡腾片': '气泡果汁整箱 330ml×12', '健胃消食片': '水果果冻分享桶 1kg', '藿香正气水': '乌龙茶整箱 500ml×15', '医用退热贴': '奶香蛋卷礼盒 400g', '蒙脱石散': '芝士威化组合装 500g', '益生菌粉 30袋': '黑巧燕麦棒整盒 30g×20', '阿胶糕 10块': '混合坚果礼盒 1kg'}
            for previous, current in snack_names.items():
                self.conn.execute("UPDATE risks SET product=? WHERE tenant_id='demo' AND snapshot_id='snapshot-demo-v1' AND product=?", (current, previous))
            for draft in self.rows("SELECT id, input_json FROM workbench_drafts WHERE tenant_id='demo' AND risk_id IN (SELECT id FROM risks WHERE snapshot_id='snapshot-demo-v1' AND tenant_id='demo')"):
                data = json.loads(draft["input_json"])
                if data.get("product") in snack_names:
                    data["product"] = snack_names[data["product"]]
                    self.conn.execute("UPDATE workbench_drafts SET input_json=? WHERE id=?", (json.dumps(data, ensure_ascii=False), draft["id"]))
        self._seed_proposal(1, 1, "transfer", created)
        self._seed_cash_events()
        self.conn.commit()

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
        self.conn.execute("INSERT OR IGNORE INTO proposal_versions(id, proposal_id, version, payload_json, status, invalid_reason, created_at) VALUES(?,?,?,?,?,?,?)", ("PV-AC10-V1", proposal_id, version, json.dumps(payload, ensure_ascii=False), "pending_approval", None, created))
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

    @_serialized
    def audit(self, entity_type: str, entity_id: str, event_type: str, payload: Dict[str, Any], tenant_id: str = "demo", actor_id: str = "demo-user") -> None:
        self.conn.execute("INSERT INTO audit_events(id, tenant_id, entity_type, entity_id, event_type, payload_json, actor_id, created_at) VALUES(?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), tenant_id, entity_type, entity_id, event_type, json.dumps(payload, ensure_ascii=False), actor_id, now_iso()))
        self.conn.commit()

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
        return [self.risk(row["id"], tenant_id) for row in self.rows("SELECT id FROM risks WHERE tenant_id=? ORDER BY priority='紧急' DESC, id", (tenant_id,))]

    @_serialized
    def create_investigation(self, risk_id: int, actor_id: str = "demo-user", tenant_id: str = "demo") -> Dict[str, Any]:
        existing = self.one("SELECT * FROM investigations WHERE risk_id=? AND tenant_id=? AND status NOT IN ('confirmed','unable_to_verify') ORDER BY created_at DESC LIMIT 1", (risk_id, tenant_id))
        if existing:
            return existing
        investigation_id = "INV-" + uuid.uuid4().hex[:10]
        self.conn.execute("INSERT INTO investigations(id, tenant_id, risk_id, status, created_by, created_at) VALUES(?,?,?,?,?,?)", (investigation_id, tenant_id, risk_id, "pending", actor_id, now_iso()))
        self.conn.execute("UPDATE risks SET investigation_status='pending' WHERE id=? AND tenant_id=?", (risk_id, tenant_id))
        self.conn.commit()
        self.audit("investigation", investigation_id, "created", {"risk_id": risk_id}, tenant_id, actor_id)
        return self.one("SELECT * FROM investigations WHERE id=?", (investigation_id,)) or {}

    @_serialized
    def add_feedback(self, investigation_id: str, raw_text: str, submitted_at: str, draft: Dict[str, Any], actor_id: str = "demo-user", tenant_id: str = "demo") -> Dict[str, Any]:
        investigation = self.one("SELECT * FROM investigations WHERE id=? AND tenant_id=?", (investigation_id, tenant_id))
        if not investigation:
            raise ValueError("核查任务不存在或无权访问")
        version = self.one("SELECT COALESCE(MAX(version),0)+1 AS v FROM feedback_versions WHERE investigation_id=?", (investigation_id,))["v"]
        feedback_id = "FB-" + uuid.uuid4().hex[:10]
        self.conn.execute("INSERT INTO feedback_versions(id, tenant_id, investigation_id, version, raw_text, draft_json, confirmed_json, confirmation_status, submitted_at, confirmed_at, actor_id, source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (feedback_id, tenant_id, investigation_id, version, raw_text, json.dumps(draft, ensure_ascii=False), None, "pending_confirmation", submitted_at, None, actor_id, "customer_input"))
        self.conn.execute("UPDATE investigations SET status='feedback_pending' WHERE id=?", (investigation_id,))
        self.conn.commit()
        self.audit("feedback", feedback_id, "draft_created", {"investigation_id": investigation_id, "version": version}, tenant_id, actor_id)
        return self.feedback(feedback_id, tenant_id) or {}

    @_serialized
    def feedback(self, feedback_id: str, tenant_id: str = "demo") -> Optional[Dict[str, Any]]:
        row = self.one("SELECT * FROM feedback_versions WHERE id=? AND tenant_id=?", (feedback_id, tenant_id))
        if row:
            row["draft"] = json.loads(row.pop("draft_json"))
            row["confirmed"] = json.loads(row.pop("confirmed_json")) if row.get("confirmed_json") else None
        return row

    @_serialized
    def confirm_feedback(self, feedback_id: str, confirmed: Dict[str, Any], actor_id: str = "demo-user", tenant_id: str = "demo") -> Dict[str, Any]:
        existing = self.feedback(feedback_id, tenant_id)
        if not existing:
            raise ValueError("反馈不存在或无权访问")
        if existing["confirmation_status"] == "confirmed":
            return existing
        now = now_iso()
        self.conn.execute("UPDATE feedback_versions SET confirmed_json=?, confirmation_status='confirmed', confirmed_at=? WHERE id=? AND tenant_id=?", (json.dumps(confirmed, ensure_ascii=False), now, feedback_id, tenant_id))
        investigation = self.one("SELECT * FROM investigations WHERE id=?", (existing["investigation_id"],))
        risk = self.risk(investigation["risk_id"], tenant_id)
        new_fact_version = int(risk["current_fact_version"]) + 1
        self.conn.execute("UPDATE risks SET investigation_status='confirmed', current_fact_version=?, evidence_level='partial' WHERE id=? AND tenant_id=?", (new_fact_version, investigation["risk_id"], tenant_id))
        self.conn.execute("UPDATE investigations SET status='confirmed' WHERE id=?", (existing["investigation_id"],))
        self.conn.execute("UPDATE proposal_versions SET status='invalidated', invalid_reason='事实版本已更新，需要重新评估' WHERE proposal_id IN (SELECT id FROM proposals WHERE risk_id=? AND tenant_id=?) AND status IN ('pending_approval','approved')", (investigation["risk_id"], tenant_id))
        self.conn.execute("UPDATE proposals SET status='needs_replan', fact_version=? WHERE risk_id=? AND tenant_id=? AND status IN ('pending_approval','approved')", (new_fact_version, investigation["risk_id"], tenant_id))
        case_content = {
            "risk_type": risk["risk_type"],
            "sku": risk["sku"],
            "store": risk["store"],
            "fact_version": new_fact_version,
            "raw_feedback": existing["raw_text"],
            "confirmed": confirmed,
            "suggested_check": "优先核查同类门店的上架与可售记录",
            "evidence_level": "partial",
            "outcome_status": "待观察",
        }
        self.conn.execute("INSERT INTO cases(id, tenant_id, risk_id, stage, status, content_json, actor_id, created_at) VALUES(?,?,?,?,?,?,?,?)", ("CASE-" + uuid.uuid4().hex[:10], tenant_id, investigation["risk_id"], "confirmed_investigation", "active", json.dumps(case_content, ensure_ascii=False), actor_id, now))
        self.conn.commit()
        self.audit("feedback", feedback_id, "confirmed", {"fact_version": new_fact_version}, tenant_id, actor_id)
        return self.feedback(feedback_id, tenant_id) or {}

    @_serialized
    def revise_feedback(self, feedback_id: str, status: str, actor_id: str = "demo-user", tenant_id: str = "demo") -> Dict[str, Any]:
        """保存纠正/撤回，不删除原始反馈和历史版本。"""
        existing = self.feedback(feedback_id, tenant_id)
        if not existing:
            raise ValueError("反馈不存在或无权访问")
        if status not in ("corrected", "withdrawn"):
            raise ValueError("只允许 corrected 或 withdrawn")
        confirmed = dict(existing.get("confirmed") or existing.get("draft") or {})
        confirmed["revision_status"] = status
        self.conn.execute("UPDATE feedback_versions SET confirmed_json=?, confirmation_status=? WHERE id=? AND tenant_id=?", (json.dumps(confirmed, ensure_ascii=False), status, feedback_id, tenant_id))
        self.conn.commit()
        self.audit("feedback", feedback_id, status, {}, tenant_id, actor_id)
        return self.feedback(feedback_id, tenant_id) or {}

    @_serialized
    def mark_replan_pending(self, risk_id: int, tenant_id: str = "demo", reason: str = "重算工具失败") -> Dict[str, Any]:
        """事实已保存但计算失败时，让旧方案保持不可执行。"""
        self.conn.execute("UPDATE proposals SET status='replan_pending' WHERE risk_id=? AND tenant_id=? AND status IN ('needs_replan','pending_approval','approved')", (risk_id, tenant_id))
        self.conn.commit()
        return {"status": "replan_pending", "risk_id": risk_id, "reason": reason, "fact_saved": True}

    @_serialized
    def replan(self, risk_id: int, tenant_id: str = "demo", actor_id: str = "demo-user") -> Dict[str, Any]:
        """根据当前事实版本创建可重新审批的方案版本，不覆写旧版。"""
        proposal = self.one("SELECT * FROM proposals WHERE risk_id=? AND tenant_id=? ORDER BY created_at DESC LIMIT 1", (risk_id, tenant_id))
        risk = self.risk(risk_id, tenant_id)
        if not proposal or not risk:
            raise ValueError("风险或方案不存在")
        old = self.one("SELECT * FROM proposal_versions WHERE proposal_id=? AND version=?", (proposal["id"], proposal["current_version"]))
        if not old:
            raise ValueError("缺少当前方案版本")
        payload = json.loads(old["payload_json"])
        payload["basis"] = dict(payload.get("basis") or {})
        payload["basis"]["fact_version"] = risk["current_fact_version"]
        payload["basis"]["replan_reason"] = "人工核查事实已确认，需基于新事实复核"
        payload["cash"] = dict(payload.get("cash") or {})
        payload["cash"]["estimated_net_cash_improvement"] = None
        payload["cash"]["completeness"] = "unavailable"
        payload["cash"]["missing_fields"] = list(dict.fromkeys(list(payload["cash"].get("missing_fields") or []) + ["post_feedback_sales"] ))
        new_version = int(proposal["current_version"]) + 1
        version_id = "PV-%s-V%s" % (proposal["id"], new_version)
        self.conn.execute("INSERT INTO proposal_versions(id, proposal_id, version, payload_json, status, invalid_reason, created_at) VALUES(?,?,?,?,?,?,?)", (version_id, proposal["id"], new_version, json.dumps(payload, ensure_ascii=False), "pending_approval", None, now_iso()))
        self.conn.execute("UPDATE proposals SET current_version=?, status='pending_approval', fact_version=? WHERE id=? AND tenant_id=?", (new_version, risk["current_fact_version"], proposal["id"], tenant_id))
        self.conn.commit()
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

    @_serialized
    def approve(self, proposal_id: str, actor_id: str = "demo-user", tenant_id: str = "demo", idem: Optional[str] = None) -> Dict[str, Any]:
        proposal = self.proposal(proposal_id, tenant_id)
        if not proposal:
            raise ValueError("方案不存在或无权访问")
        key = self._scoped_idem(tenant_id, "approve", proposal_id, idem or "approve|%s|%s" % (proposal_id, proposal["current_version"]))
        existing = self.one("SELECT * FROM approvals WHERE idempotency_key=? AND tenant_id=?", (key, tenant_id))
        if existing:
            return existing
        if proposal["status"] in ("needs_replan", "invalidated", "replan_pending"):
            raise ValueError("方案版本已失效，不能审批")
        if proposal["status"] != "pending_approval":
            raise ValueError("方案尚未提交审批，或已不在待审批状态")
        approval_id = "APR-" + uuid.uuid4().hex[:10]
        version = proposal["current_version"]
        self.conn.execute("INSERT INTO approvals(id, tenant_id, proposal_id, proposal_version, actor_id, status, idempotency_key, created_at) VALUES(?,?,?,?,?,?,?,?)", (approval_id, tenant_id, proposal_id, version, actor_id, "approved", key, now_iso()))
        self.conn.execute("UPDATE proposals SET status='approved' WHERE id=? AND tenant_id=?", (proposal_id, tenant_id))
        self.conn.execute("UPDATE proposal_versions SET status='approved' WHERE proposal_id=? AND version=?", (proposal_id, version))
        self.conn.commit()
        self.audit("proposal", proposal_id, "approved", {"version": version}, tenant_id, actor_id)
        return self.one("SELECT * FROM approvals WHERE id=?", (approval_id,)) or {}

    @_serialized
    def execute(self, proposal_id: str, actor_id: str = "demo-user", tenant_id: str = "demo", idem: Optional[str] = None) -> Dict[str, Any]:
        proposal = self.proposal(proposal_id, tenant_id)
        if not proposal:
            raise ValueError("方案不存在或无权访问")
        key = self._scoped_idem(tenant_id, "execute", proposal_id, idem or "execute|%s|%s" % (proposal_id, proposal["current_version"]))
        existing = self.one("SELECT * FROM execution_tasks WHERE idempotency_key=? AND tenant_id=?", (key, tenant_id))
        if existing:
            return existing
        if proposal["status"] != "approved":
            raise ValueError("只有已批准的具体版本可以生成执行任务")
        task_id = "TASK-" + uuid.uuid4().hex[:10]
        self.conn.execute("INSERT INTO execution_tasks(id, tenant_id, proposal_id, proposal_version, status, idempotency_key, created_at, metadata_json) VALUES(?,?,?,?,?,?,?,?)", (task_id, tenant_id, proposal_id, proposal["current_version"], "draft_pending_external_execution", key, now_iso(), json.dumps({"external_write": False}, ensure_ascii=False)))
        self.conn.execute("UPDATE proposals SET status='execution_task_created' WHERE id=? AND tenant_id=?", (proposal_id, tenant_id))
        self.conn.commit()
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

    @_serialized
    def save_workbench_draft(
        self,
        module_type: str,
        risk_id: int,
        input_data: Dict[str, Any],
        calculation: Optional[Dict[str, Any]],
        status: str,
        actor_id: str = "demo-user",
        tenant_id: str = "demo",
    ) -> Dict[str, Any]:
        existing = self.workbench_draft(module_type, risk_id, tenant_id)
        now = now_iso()
        if existing:
            version = int(existing["version"]) + 1
            self.conn.execute(
                "UPDATE workbench_drafts SET version=?, status=?, input_json=?, calculation_json=?, updated_by=?, updated_at=? WHERE id=?",
                (version, status, json.dumps(input_data, ensure_ascii=False), json.dumps(calculation, ensure_ascii=False, default=str) if calculation is not None else None, actor_id, now, existing["id"]),
            )
            draft_id = existing["id"]
        else:
            draft_id = "WBD-" + uuid.uuid4().hex[:10]
            version = 1
            self.conn.execute(
                "INSERT INTO workbench_drafts(id, tenant_id, module_type, risk_id, version, status, input_json, calculation_json, proposal_id, updated_by, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (draft_id, tenant_id, module_type, risk_id, version, status, json.dumps(input_data, ensure_ascii=False), json.dumps(calculation, ensure_ascii=False, default=str) if calculation is not None else None, None, actor_id, now),
            )
        self.conn.commit()
        self.audit("workbench_draft", draft_id, "calculated" if calculation else "input_changed", {"module_type": module_type, "risk_id": risk_id, "version": version, "status": status}, tenant_id, actor_id)
        return self.workbench_draft(module_type, risk_id, tenant_id) or {}

    @_serialized
    def mark_workbench_dirty(self, module_type: str, risk_id: int, input_data: Dict[str, Any], actor_id: str = "demo-user", tenant_id: str = "demo") -> Dict[str, Any]:
        return self.save_workbench_draft(module_type, risk_id, input_data, None, "needs_recalculation", actor_id, tenant_id)

    @_serialized
    def save_workbench_proposal(
        self,
        module_type: str,
        risk_id: int,
        input_data: Dict[str, Any],
        calculation: Dict[str, Any],
        actor_id: str = "demo-user",
        tenant_id: str = "demo",
    ) -> Dict[str, Any]:
        if not calculation.get("valid"):
            raise ValueError("存在约束错误，不能保存方案")
        risk = self.risk(risk_id, tenant_id)
        if not risk:
            raise ValueError("风险不存在或无权访问")
        previous = self.one("SELECT * FROM proposals WHERE tenant_id=? AND risk_id=? ORDER BY created_at DESC LIMIT 1", (tenant_id, risk_id))
        # 已生成执行任务的版本保持不可变，编辑后另建一张待审批方案。
        if previous and previous["status"] != "execution_task_created":
            proposal_id = previous["id"]
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
        self.conn.execute("INSERT INTO proposal_versions(id, proposal_id, version, payload_json, status, invalid_reason, created_at) VALUES(?,?,?,?,?,?,?)", ("PV-%s-V%s" % (proposal_id, new_version), proposal_id, new_version, json.dumps(payload, ensure_ascii=False, default=str), "draft", None, now_iso()))
        self.conn.execute("UPDATE proposals SET current_version=?, status='draft', snapshot_id=?, fact_version=? WHERE id=? AND tenant_id=?", (new_version, risk["snapshot_id"], risk["current_fact_version"], proposal_id, tenant_id))
        self.conn.execute("UPDATE workbench_drafts SET proposal_id=?, status='saved', calculation_json=? WHERE tenant_id=? AND module_type=? AND risk_id=?", (proposal_id, json.dumps(calculation, ensure_ascii=False, default=str), tenant_id, module_type, risk_id))
        self.conn.commit()
        self.audit("proposal", proposal_id, "workbench_saved", {"module_type": module_type, "version": new_version, "risk_id": risk_id}, tenant_id, actor_id)
        return self.proposal(proposal_id, tenant_id) or {}

    @_serialized
    def submit_proposal(self, proposal_id: str, actor_id: str = "demo-user", tenant_id: str = "demo") -> Dict[str, Any]:
        proposal = self.proposal(proposal_id, tenant_id)
        if not proposal:
            raise ValueError("方案不存在或无权访问")
        if proposal["status"] == "pending_approval":
            return proposal
        if proposal["status"] != "draft" or not proposal.get("version") or proposal["version"].get("status") != "draft":
            raise ValueError("只有已保存且未失效的草稿方案可以提交审批")
        self.conn.execute("UPDATE proposals SET status='pending_approval' WHERE id=? AND tenant_id=?", (proposal_id, tenant_id))
        self.conn.execute("UPDATE proposal_versions SET status='pending_approval' WHERE proposal_id=? AND version=?", (proposal_id, proposal["current_version"]))
        self.conn.commit()
        self.audit("proposal", proposal_id, "submitted_for_approval", {"version": proposal["current_version"]}, tenant_id, actor_id)
        return self.proposal(proposal_id, tenant_id) or {}

    @_serialized
    def execution_tasks(self, tenant_id: str = "demo") -> List[Dict[str, Any]]:
        rows = self.rows("SELECT * FROM execution_tasks WHERE tenant_id=? ORDER BY created_at DESC", (tenant_id,))
        for row in rows:
            row["metadata"] = json.loads(row.pop("metadata_json"))
        return rows

    @_serialized
    def update_execution_status(
        self,
        task_id: str,
        status: str,
        receipt_ref: Optional[str] = None,
        actual_cash: Optional[Any] = None,
        actor_id: str = "demo-user",
        tenant_id: str = "demo",
    ) -> Dict[str, Any]:
        task = self.one("SELECT * FROM execution_tasks WHERE id=? AND tenant_id=?", (task_id, tenant_id))
        if not task:
            raise ValueError("执行任务不存在或无权访问")
        allowed = {"pending_dispatch", "in_transit", "awaiting_receipt", "received", "completed", "exception"}
        if status not in allowed:
            raise ValueError("不支持的执行状态")
        if status in ("received", "completed") and not receipt_ref:
            raise ValueError("收货或完成需要填写执行回执号")
        metadata = json.loads(task.get("metadata_json") or "{}")
        timeline = list(metadata.get("timeline") or [])
        timeline.append({"status": status, "at": now_iso(), "receipt_ref": receipt_ref, "actual_cash": actual_cash})
        metadata.update({"external_write": False, "timeline": timeline, "receipt_ref": receipt_ref or metadata.get("receipt_ref"), "actual_cash": actual_cash if actual_cash is not None else metadata.get("actual_cash")})
        self.conn.execute("UPDATE execution_tasks SET status=?, metadata_json=? WHERE id=? AND tenant_id=?", (status, json.dumps(metadata, ensure_ascii=False), task_id, tenant_id))
        self.conn.commit()
        self.audit("execution_task", task_id, "status_updated", {"status": status, "receipt_ref": receipt_ref, "actual_cash": actual_cash}, tenant_id, actor_id)
        result = self.one("SELECT * FROM execution_tasks WHERE id=?", (task_id,)) or {}
        result["metadata"] = json.loads(result.pop("metadata_json"))
        return result

    @_serialized
    def add_data_import(self, filename: str, mode: str, status: str, summary: Dict[str, Any], errors: List[Dict[str, Any]], actor_id: str = "demo-user", tenant_id: str = "demo") -> Dict[str, Any]:
        import_id = "IMP-" + uuid.uuid4().hex[:10]
        self.conn.execute("INSERT INTO data_imports(id, tenant_id, filename, mode, status, summary_json, errors_json, created_at, actor_id) VALUES(?,?,?,?,?,?,?,?,?)", (import_id, tenant_id, filename, mode, status, json.dumps(summary, ensure_ascii=False), json.dumps(errors, ensure_ascii=False), now_iso(), actor_id))
        self.conn.commit()
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
                SELECT rowid AS id, org_code, sku, product_name, cost_amount,
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
            SELECT rowid AS id, snapshot_id, org_code, org_name, sku, product_name, unit,
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
            SELECT rowid AS id, snapshot_id, org_code, org_name, sku, product_name, unit,
                   inventory_qty, cost_amount, sales_30, sales_90, sales_cost_30, purchase_status,
                   stat_class, teacher_monthly_sales, teacher_ratio, reduction_ratio,
                   teacher_target_inventory_amount, teacher_suggested_reduction_amount,
                   teacher_reference_reduction_qty, teacher_priority, teacher_trigger_reason,
                   teacher_candidate, teacher_eligible, teacher_stockout, teacher_near_stockout,
                   store_price, member_price
            FROM real_inventory_lines
            WHERE snapshot_id=? AND tenant_id=? AND rowid=? AND teacher_candidate=1
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

    @_serialized
    def add_case(self, content: Dict[str, Any], risk_id: Optional[int], actor_id: str = "demo-user", tenant_id: str = "demo") -> Dict[str, Any]:
        case_id = "CASE-" + uuid.uuid4().hex[:10]
        self.conn.execute("INSERT INTO cases(id, tenant_id, risk_id, stage, status, content_json, actor_id, created_at) VALUES(?,?,?,?,?,?,?,?)", (case_id, tenant_id, risk_id, content.get("stage", "confirmed_investigation"), content.get("status", "active"), json.dumps(content, ensure_ascii=False), actor_id, now_iso()))
        self.conn.commit()
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

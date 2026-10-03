"""One versioned fact authority on the application's existing Store connection."""
from contextlib import nullcontext
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json

from backend.errors import BusinessConflict
from backend.hackathon_shared import CONTRACT_VERSION
from backend.serialization import dumps, json_value
from .loader import load_scenario, parse_clock
from .risk import scenario_risks


SCHEMA = (
    """CREATE TABLE IF NOT EXISTS hackathon_fact_imports (
       scope_key TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, scenario_id TEXT NOT NULL,
       branch_id TEXT NOT NULL, snapshot_id TEXT NOT NULL, source_version TEXT NOT NULL,
       base_json TEXT NOT NULL, UNIQUE(tenant_id,scenario_id,branch_id))""",
    """CREATE TABLE IF NOT EXISTS hackathon_fact_versions (
       scope_key TEXT NOT NULL, version INTEGER NOT NULL, context_json TEXT NOT NULL,
       state_json TEXT NOT NULL, PRIMARY KEY(scope_key,version))""",
    """CREATE TABLE IF NOT EXISTS hackathon_fact_events (
       scope_key TEXT NOT NULL, event_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
       version INTEGER NOT NULL, payload_json TEXT NOT NULL, PRIMARY KEY(scope_key,event_id))""",
    """CREATE TABLE IF NOT EXISTS hackathon_legacy_risk_map (
       scope_key TEXT NOT NULL, risk_key TEXT NOT NULL, legacy_risk_id INTEGER NOT NULL,
       PRIMARY KEY(scope_key,risk_key), FOREIGN KEY(legacy_risk_id) REFERENCES risks(id))""",
)
CANONICAL = {"inventory", "sales_history", "availability_history", "demand_forecasts", "procurement", "routes", "policies", "payables"}
MAPPED_TABLES = {"inventory", "sales_daily", "availability_daily", "demand_forecasts", "purchase_orders", "in_transit", "routes", "risk_policies", "return_terms", "payables"}
STATUS_EVENTS = {"supplier_confirmed", "promotion_price_effective", "promotion_ended", "execution_exception", "execution_scheduled", "execution_cancelled", "execution_receipt_recorded"}


def migrate(tx):
    if not tx.in_transaction:
        raise ValueError("Fact migrations require the shared active transaction")
    for statement in SCHEMA:
        tx.execute(statement)


def inventory_key(store_id, sku_id, lot_id):
    return "|".join((store_id, sku_id, lot_id))


def risk_key(scenario_id, store_id, sku_id, lot_id, risk_type):
    return ":".join((scenario_id, store_id, sku_id, lot_id, risk_type))


def _scope(tenant, scenario, branch):
    if not all(isinstance(value, str) and value for value in (tenant, scenario, branch)):
        raise ValueError("Tenant, scenario and branch IDs are required")
    return hashlib.sha256(dumps([tenant, scenario, branch]).encode()).hexdigest()


def _number(value, field="quantity", *, signed=False):
    if value is None or isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"Invalid {field}") from None
    if not result.is_finite() or (result < 0 and not signed):
        raise ValueError(f"Invalid {field}")
    return result


def _source(row, fallback):
    return {"source": row.get("source") or "confirmed_business_event",
            "record_id": row.get("inventory_id") or row.get("event_id") or row.get("source_ref") or fallback,
            "known_at": row.get("known_at") or fallback, "is_demo": row.get("is_demo", True)}


def _selectors(query, tables):
    selected = {}
    for selector, table, field in (("store_ids", "stores", "store_id"), ("sku_ids", "products", "sku_id"), ("lot_ids", "lots", "lot_id")):
        values = query.get(selector, [])
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise ValueError("Fact selectors must be lists of IDs")
        selected[selector] = set(values)
        if selected[selector] - {row[field] for row in tables[table]}:
            raise ValueError("Unknown fact selector: " + selector)
    return selected


class RetailFactService:
    def __init__(self, store, *, root=None):
        self.store, self.root = store, root

    def import_scenario(self, tenant_id, scenario_id, branch_id=None, *, as_of=None, actor_id="system", tx=None):
        facts = load_scenario(scenario_id, branch_id, clock_at=as_of, root=self.root)
        scope = _scope(tenant_id, facts["scenario_id"], facts["branch_id"])
        with nullcontext(tx) if tx is not None else self.store.transaction() as active:
            self._active(active)
            prior = active.execute("SELECT * FROM hackathon_fact_imports WHERE scope_key=?", (scope,)).fetchone()
            if prior:
                if prior["source_version"] != facts["snapshot_id"]:
                    raise BusinessConflict("dataset_changed", "场景已导入其他版本，不能覆盖现有事实")
                context, _ = self._version(active, scope)
                return {"contract_version": CONTRACT_VERSION, "context": context, "idempotent_replay": True,
                        "row_counts": {name: len(rows) for name, rows in facts["tables"].items()}, "missing_fields": context["missing_fields"]}
            snapshot = "hf-" + hashlib.sha256((scope + facts["snapshot_id"]).encode()).hexdigest()[:28]
            missing = sorted({inventory_key(item["store_id"], item["sku_id"], item["lot_id"]) + "." + field
                              for item in scenario_risks(facts)["items"] for kind in ("slow", "near_expiry") for field in item[kind]["missing_fields"]})
            context = {"tenant_id": tenant_id, "scenario_id": facts["scenario_id"], "branch_id": facts["branch_id"],
                       "snapshot_id": snapshot, "as_of": facts["clock_at"], "data_version": facts["dataset_id"],
                       "fact_version": 1, "is_demo": True,
                       "source_refs": [{"source": "retail-v2", "record_id": facts["snapshot_id"], "known_at": facts["clock_at"], "is_demo": True}],
                       "missing_fields": missing}
            state = {"inventory": deepcopy(facts["tables"]["inventory"]), "tables": {}, "appended": {}, "confirmed_override_ids": facts["applied_override_ids"]}
            active.execute("INSERT INTO hackathon_fact_imports VALUES(?,?,?,?,?,?,?)", (scope, tenant_id, scenario_id,
                           facts["branch_id"], snapshot, facts["snapshot_id"], dumps(facts)))
            active.execute("INSERT INTO hackathon_fact_versions VALUES(?,?,?,?)", (scope, 1, dumps(context), dumps(state)))
            active.execute("INSERT INTO snapshots(id,tenant_id,kind,created_at,source,is_sample,metadata_json) VALUES(?,?,?,?,?,?,?)",
                           (snapshot, tenant_id, "hackathon_scenario", facts["clock_at"], "retail-v2", 1, dumps({"scenario_id": scenario_id, "branch_id": facts["branch_id"], "actor_id": actor_id})))
            self._create_legacy_mapping(active, scope, context, facts)
            return {"contract_version": CONTRACT_VERSION, "context": context, "idempotent_replay": False,
                    "row_counts": {name: len(rows) for name, rows in facts["tables"].items()},
                    "missing_fields": missing, "warnings": facts["warnings"],
                    "complete_store_count": sum(bool(row["include_in_summary"]) for row in facts["tables"]["stores"]),
                    "directory_store_count": len(facts["tables"]["stores"])}

    @staticmethod
    def _active(tx):
        if tx is None or not tx.in_transaction:
            raise ValueError("Fact writes require the existing Store transaction")

    @staticmethod
    def _version(tx, scope):
        row = tx.execute("SELECT context_json,state_json FROM hackathon_fact_versions WHERE scope_key=? ORDER BY version DESC LIMIT 1", (scope,)).fetchone()
        if row is None:
            raise ValueError("Scenario has not been imported for this tenant")
        return json.loads(row["context_json"]), json.loads(row["state_json"])

    def get_context(self, tenant_id, scenario_id, branch_id=None, *, tx=None):
        with nullcontext(tx) if tx is not None else self.store.transaction() as active:
            rows = active.execute("SELECT scope_key,branch_id FROM hackathon_fact_imports WHERE tenant_id=? AND scenario_id=?", (tenant_id, scenario_id)).fetchall()
            matches = [row for row in rows if branch_id is None or row["branch_id"] == branch_id]
            if len(matches) != 1:
                raise ValueError("Scenario branch is missing or ambiguous")
            return self._version(active, matches[0]["scope_key"])[0]

    def _checked(self, tx, context):
        scope = _scope(context["tenant_id"], context["scenario_id"], context["branch_id"])
        current, state = self._version(tx, scope)
        if type(context.get("fact_version")) is not int:
            raise ValueError("Fact version must be an integer")
        for field in ("snapshot_id", "fact_version", "data_version", "as_of"):
            if context.get(field) != current[field]:
                raise BusinessConflict("version_conflict", "事实版本或时点已变化，请重新读取", current["fact_version"])
        if type(context.get("is_demo")) is not bool or context["is_demo"] is not current["is_demo"]:
            raise BusinessConflict("context_conflict", "事实的数据来源标记与持久化上下文不一致")
        for field in ("source_refs", "missing_fields"):
            supplied = json.dumps(context.get(field), sort_keys=True, ensure_ascii=False, allow_nan=False)
            persisted = json.dumps(current[field], sort_keys=True, ensure_ascii=False, allow_nan=False)
            if supplied != persisted:
                raise BusinessConflict("context_conflict", "事实来源或缺项与持久化上下文不一致")
        return scope, current, state

    def _read(self, tx, context):
        scope, current, state = self._checked(tx, context)
        row = tx.execute("SELECT base_json FROM hackathon_fact_imports WHERE scope_key=?", (scope,)).fetchone()
        facts = json.loads(row["base_json"])
        facts["tables"].update(deepcopy(state["tables"]))
        facts["tables"]["inventory"] = deepcopy(state["inventory"])
        for name, rows in state["appended"].items():
            facts["tables"].setdefault(name, []).extend(deepcopy(rows))
        facts.update(snapshot_id=current["snapshot_id"], data_version=current["data_version"], clock_at=current["as_of"])
        facts["applied_override_ids"] = state.get("confirmed_override_ids", [])
        held = {}
        for row in tx.execute("SELECT resource_key,quantity FROM inventory_reservations WHERE tenant_id=? AND snapshot_id=?", (current["tenant_id"], current["snapshot_id"])):
            held[row["resource_key"]] = held.get(row["resource_key"], Decimal(0)) + _number(row["quantity"])
        for row in facts["tables"]["inventory"]:
            row["external_reserved_qty"] = row["reserved_qty"]
            row["reserved_qty"] = _number(row["reserved_qty"]) + held.get(inventory_key(row["store_id"], row["sku_id"], row["lot_id"]) + "|" + row["stock_state"], 0)
        accounts = facts["tables"].get("accounts", [])
        cash_rows = tx.execute("SELECT amount,direction,source FROM cash_events WHERE tenant_id=? AND scenario_id=?", (current["tenant_id"], current["snapshot_id"])).fetchall()
        by_account = {row["account_id"]: [] for row in accounts}
        for cash in cash_rows:
            source = cash["source"]
            account_id = source.split(":", 1)[1] if source.startswith("hackathon_execution:") else accounts[0]["account_id"] if len(accounts) == 1 else None
            if account_id not in by_account:
                raise ValueError("Cash projection requires a known, unambiguous account")
            by_account[account_id].append(cash)
        for account in accounts:
            balance = _number(account["available_balance"])
            for cash in by_account[account["account_id"]]:
                if cash["direction"] not in {"in", "out"}:
                    raise ValueError("Invalid cash direction")
                if cash["amount"] is not None:
                    balance += _number(cash["amount"]) * (1 if cash["direction"] == "in" else -1)
            account["available_balance"] = balance
            account["snapshot_at"] = current["as_of"]
        return scope, current, state, facts

    def read_facts(self, context, *, tx=None):
        with nullcontext(tx) if tx is not None else self.store.transaction() as active:
            return json_value(self._read(active, context)[3])

    def advance_clock(self, tx, context, as_of, *, confirmed_override_ids=()):
        """Publish newly known reference records, never future replay actuals."""
        self._active(tx)
        scope, current, state = self._checked(tx, context)
        clock = parse_clock(as_of)
        if clock < parse_clock(current["as_of"]):
            raise ValueError("Fact clock cannot move backwards")
        if clock == parse_clock(current["as_of"]) and not confirmed_override_ids:
            return {"contract_version": CONTRACT_VERSION, "context": current, "advanced_to": current["as_of"]}
        confirmed = sorted(set(state.get("confirmed_override_ids", [])) | set(confirmed_override_ids))
        source = tx.execute("SELECT source_version,base_json FROM hackathon_fact_imports WHERE scope_key=?", (scope,)).fetchone()
        imported = json.loads(source["base_json"])
        baseline = load_scenario(current["scenario_id"], current["branch_id"], clock_at=imported["clock_at"], root=self.root)
        if baseline["snapshot_id"] != source["source_version"]:
            raise BusinessConflict("dataset_changed", "场景来源已变化，不能把新来源混入当前事实")
        known = load_scenario(current["scenario_id"], current["branch_id"], clock_at=clock.isoformat(),
                              confirmed_override_ids=confirmed, root=self.root)
        state["confirmed_override_ids"] = confirmed
        # Inventory, orders, cash and historical sales change only by receipts.
        for name in ("lots", "materials", "store_calendar"):
            refreshed = known["tables"][name]
            id_fields = {"lots": ("lot_id",), "materials": ("material_id",), "store_calendar": ("store_id", "date")}[name]
            index = {tuple(row.get(key) for key in id_fields): row for row in refreshed}
            for row in state["tables"].get(name, []):
                if row.get("source") in {"business_receipt", "confirmed_material"}:
                    index[tuple(row.get(key) for key in id_fields)] = row
            state["tables"][name] = list(index.values())
        current.update(as_of=clock.isoformat(), fact_version=current["fact_version"] + 1)
        tx.execute("INSERT INTO hackathon_fact_versions VALUES(?,?,?,?)", (scope, current["fact_version"], dumps(current), dumps(state)))
        return {"contract_version": CONTRACT_VERSION, "context": current, "advanced_to": current["as_of"]}

    def query(self, query):
        includes = set(query.get("include") or CANONICAL)
        if includes - CANONICAL:
            raise ValueError("Unregistered fact query category")
        with self.store.transaction() as tx:
            _, context, _, facts = self._read(tx, query["context"])
        tables = facts["tables"]
        selectors = _selectors(query, tables)
        for field in ("history_start", "history_end"):
            if query.get(field):
                date.fromisoformat(query[field])
        if query.get("history_start") and query.get("history_end") and query["history_start"] > query["history_end"]:
            raise ValueError("History start exceeds end")
        def match(row):
            for selector, field in (("store_ids", "store_id"), ("sku_ids", "sku_id"), ("lot_ids", "lot_id")):
                if selectors[selector] and row.get(field) is not None and row[field] not in selectors[selector]:
                    return False
            if row.get("date") and ((query.get("history_start") and row["date"] < query["history_start"]) or
                                    (query.get("history_end") and row["date"] > query["history_end"])):
                return False
            return True
        products = {row["sku_id"]: row for row in tables["products"]}
        inventory = []
        for row in tables["inventory"]:
            if not match(row):
                continue
            inventory.append({key: row.get(key) for key in ("inventory_id", "store_id", "sku_id", "lot_id", "stock_state", "quantity", "shipment_line_id", "blocked_qty", "reserved_qty", "external_reserved_qty", "sellable_until")} |
                             {"base_unit": products[row["sku_id"]]["base_unit"], "unit_cost_cny": row["unit_cost"], "source_ref": _source(row, context["as_of"])})
        identity = {"context": context, "selectors": {key: sorted(values) for key, values in selectors.items()},
                    "include": sorted(includes), "history_start": query.get("history_start"), "history_end": query.get("history_end")}
        query_id = "query-" + hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:32]
        output = {"contract_version": CONTRACT_VERSION, "query_id": query_id,
                  "context": deepcopy(context), "inventory": inventory if "inventory" in includes else [],
                  "sales_history": [row for row in tables["sales_daily"] if match(row)] if "sales_history" in includes else [],
                  "availability_history": [row for row in tables["availability_daily"] if match(row)] if "availability_history" in includes else [],
                  "demand_forecasts": [row for row in tables["demand_forecasts"] if match({key: value for key, value in row.items() if key != "date"})] if "demand_forecasts" in includes else [],
                  "procurement": [{**row, "record_type": kind} for name, kind in (("purchase_orders", "purchase_order"), ("in_transit", "in_transit")) for row in tables[name] if match(row)] if "procurement" in includes else [],
                  "routes": [row for row in tables["routes"] if not selectors["store_ids"] or row["from_store_id"] in selectors["store_ids"] or row["to_store_id"] in selectors["store_ids"]] if "routes" in includes else [],
                  "policies": [{**row, "record_type": kind} for name, kind in (("risk_policies", "risk_policy"), ("return_terms", "return_terms")) for row in tables[name]] if "policies" in includes else [],
                  "payables": tables["payables"] if "payables" in includes else [],
                  "missing_fields": [], "warnings": list(facts["warnings"]),
                  "reference_data": {"tables": {name: [row for row in rows if match({key: value for key, value in row.items() if key != "date"})]
                                                 for name, rows in tables.items() if name not in MAPPED_TABLES and name not in {"inventory_movements", "historical_orders"}},
                                     "target": facts["target"], "evaluation_end": facts["evaluation_end"]}}
        for store in tables["stores"]:
            if not store["include_in_summary"] and store["store_id"] in selectors["store_ids"]:
                output["missing_fields"].append("stores." + store["store_id"] + ".business_facts")
        return json_value(output)

    def assess_risks(self, query):
        with self.store.transaction() as tx:
            scope, context, _, facts = self._read(tx, query["context"])
            legacy = {row["risk_key"]: row["legacy_risk_id"] for row in tx.execute("SELECT risk_key,legacy_risk_id FROM hackathon_legacy_risk_map WHERE scope_key=?", (scope,))}
        selected = _selectors(query, facts["tables"])
        assessed = scenario_risks(facts)
        missing = ["stores." + row["store_id"] + ".business_facts" for row in facts["tables"]["stores"]
                   if row["store_id"] in selected["store_ids"] and not row["include_in_summary"]]
        items, counted, total = [], set(), Decimal(0)
        incomplete = bool(missing)
        for row in assessed["items"]:
            if any(selected[key] and row[field] not in selected[key] for key, field in (("store_ids", "store_id"), ("sku_ids", "sku_id"), ("lot_ids", "lot_id"))):
                continue
            stock_key = inventory_key(row["store_id"], row["sku_id"], row["lot_id"])
            for name, kind in (("slow", "slow_moving"), ("near_expiry", "near_expiry")):
                key = risk_key(context["scenario_id"], row["store_id"], row["sku_id"], row["lot_id"], kind)
                assessment = row[name]
                result = "insufficient_data" if assessment["status"] == "unknown" else "risk" if assessment["status"] in {"risk", "unsellable"} else "normal"
                items.append({"risk_key": key, "risk_id": legacy.get(key),
                              "store_id": row["store_id"], "sku_id": row["sku_id"], "lot_id": row["lot_id"],
                              "risk_type": kind, "result": result, "quantity": row["quantity"], "base_unit": row["unit"],
                              "amount_cny": row["inventory_cost"] if result == "risk" else None if result == "insufficient_data" else 0,
                              "coverage_days": row["slow"]["coverage_days"], "remaining_sellable_days": row["near_expiry"]["remaining_sellable_days"],
                              "evidence_refs": [{"source": "retail-v2", "record_id": row["inventory_id"], "known_at": context["as_of"], "is_demo": True}],
                              "missing_fields": assessment["missing_fields"], "rule_version": next((str(policy["rule_version"]) for policy in facts["tables"]["risk_policies"] if policy["policy_id"] == row["policy_id"]), None),
                              "unsellable": assessment["status"] == "unsellable"})
                missing.extend(assessment["missing_fields"])
            if row["risk_tags"] and stock_key not in counted:
                counted.add(stock_key)
                total += _number(row["inventory_cost"])
            incomplete |= row["risk_inventory_cost"] is None
        return json_value({"contract_version": CONTRACT_VERSION, "context": context, "calculation_version": assessed["calculation_version"],
                           "items": items, "attention_inventory_cost_cny": None if incomplete else total,
                           "counted_inventory_keys": sorted(counted), "missing_fields": sorted(set(missing))})

    def resolve_legacy_risk_id(self, context, risk_key):
        with self.store.transaction() as tx:
            scope, _, _ = self._checked(tx, context)
            row = tx.execute("SELECT legacy_risk_id FROM hackathon_legacy_risk_map WHERE scope_key=? AND risk_key=?", (scope, risk_key)).fetchone()
            return row["legacy_risk_id"] if row else None

    @staticmethod
    def _create_legacy_mapping(tx, scope, context, facts):
        for item in scenario_risks(facts)["items"]:
            cursor = tx.execute("""INSERT INTO risks(tenant_id,snapshot_id,sku,product,store,store_id,sales_30,
                inventory_qty,unit_cost,tags_json,days_to_sell,risk_type,priority,observation,evidence_level,missing_fields_json,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (context["tenant_id"], context["snapshot_id"], item["sku_id"], item["product_name"],
                item["store_name"], item["store_id"], item["slow"]["sales_30"], item["quantity"],
                str(next(row["unit_cost"] for row in facts["tables"]["inventory"] if row["inventory_id"] == item["inventory_id"])),
                dumps(item["risk_tags"]), item["near_expiry"]["remaining_sellable_days"], "临期" if "near_expiry" in item["risk_tags"] else "滞销",
                "待核查", "retail-v2 场景批次兼容关联；业务事实以场景服务为准", "partial",
                dumps(item["slow"]["missing_fields"] + item["near_expiry"]["missing_fields"]), context["as_of"]))
            for kind in ("slow_moving", "near_expiry"):
                key = risk_key(context["scenario_id"], item["store_id"], item["sku_id"], item["lot_id"], kind)
                tx.execute("INSERT INTO hackathon_legacy_risk_map VALUES(?,?,?)", (scope, key, cursor.lastrowid))

    def apply_business_events(self, tx, events, *, expected_fact_version):
        self._active(tx)
        if isinstance(expected_fact_version, bool) or not isinstance(expected_fact_version, int) or expected_fact_version < 1:
            raise ValueError("Expected fact version must be a positive integer")
        if not events:
            raise ValueError("At least one business event is required")
        first = events[0]
        scope = _scope(first["tenant_id"], first["scenario_id"], first["branch_id"])
        context, state = self._version(tx, scope)
        _, _, _, facts = self._read(tx, context)
        staged, duplicates, deltas = [], [], []
        for original in events:
            if _scope(original["tenant_id"], original["scenario_id"], original["branch_id"]) != scope:
                raise ValueError("One fact transaction cannot mix tenants or scenario branches")
            event_id = original.get("event_id")
            if not isinstance(event_id, str) or not event_id:
                raise ValueError("Business event requires event_id")
            fingerprint = hashlib.sha256(json.dumps(json_value(original), sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
            prior = tx.execute("SELECT fingerprint FROM hackathon_fact_events WHERE scope_key=? AND event_id=?", (scope, event_id)).fetchone()
            if prior:
                if prior["fingerprint"] != fingerprint:
                    raise BusinessConflict("idempotency_conflict", "同一业务事件编号包含不同内容")
                duplicates.append(event_id)
                continue
            same_batch = next((row for row in staged if row[0] == event_id), None)
            if same_batch:
                if same_batch[1] != fingerprint:
                    raise BusinessConflict("idempotency_conflict", "同批次业务事件编号包含不同内容")
                duplicates.append(event_id)
                continue
            if expected_fact_version != context["fact_version"]:
                raise BusinessConflict("version_conflict", "事实版本已变化", context["fact_version"])
            known = parse_clock(original["known_at"])
            occurred = parse_clock(original["occurred_at"])
            if known < occurred:
                raise ValueError("An event cannot be known before it occurred")
            if original.get("external_write") is not False or original.get("is_demo") is not context["is_demo"]:
                raise ValueError("Only local business events are accepted")
            row = {**deepcopy(original.get("details", {})), **{key: value for key, value in original.items() if key != "details" and value is not None}}
            if row.get("credit_note_id"):
                if row.get("credit_id") and row["credit_id"] != row["credit_note_id"]:
                    raise ValueError("Conflicting credit note identifiers")
                row["credit_id"] = row["credit_note_id"]
            if row.get("amount_cny") is not None:
                _number(row["amount_cny"], "amount_cny")
            self._apply(facts, state, row, deltas)
            facts["tables"].update(deepcopy(state["tables"]))
            context["as_of"] = max(parse_clock(context["as_of"]), known).isoformat()
            staged.append((event_id, fingerprint, original))
        if staged:
            context["fact_version"] += 1
            tx.execute("INSERT INTO hackathon_fact_versions VALUES(?,?,?,?)", (scope, context["fact_version"], dumps(context), dumps(state)))
            tx.executemany("INSERT INTO hackathon_fact_events VALUES(?,?,?,?,?)", [(scope, eid, fingerprint, context["fact_version"], dumps(row)) for eid, fingerprint, row in staged])
        return {"contract_version": CONTRACT_VERSION, "context": context, "applied_event_ids": [row[0] for row in staged],
                "duplicate_event_ids": duplicates, "inventory_deltas": json_value(deltas)}

    def _apply(self, facts, state, event, deltas):
        kind = event["event_type"]
        if kind in {"transfer_shipped", "transfer_received"}:
            if not event.get("task_id"):
                raise ValueError("Transfer receipt requires its execution task")
            event["shipment_line_id"] = "transfer:" + event["task_id"]
        inventory = state["inventory"]
        def move(source_state=None, destination_state=None, destination_store=None):
            quantity = _number(event["quantity"])
            if quantity <= 0:
                raise ValueError("Inventory business quantities must be positive")
            product = next((row for row in facts["tables"]["products"] if row["sku_id"] == event["sku_id"]), None)
            if product is None or event.get("base_unit") != product["base_unit"]:
                raise ValueError("Unknown product or incompatible base unit")
            if not isinstance(event.get("lot_id"), str) or not event["lot_id"]:
                raise ValueError("Inventory receipt requires a lot identity")
            lots = state["tables"].setdefault("lots", deepcopy(facts["tables"]["lots"]))
            lot = next((row for row in lots if row["lot_id"] == event["lot_id"]), None)
            if lot and lot["sku_id"] != event["sku_id"]:
                raise ValueError("Receipt lot belongs to another product")
            if lot is None:
                lots.append({"lot_id": event["lot_id"], "sku_id": event["sku_id"], "supplier_id": event.get("supplier_id"),
                             "expiry_date": None, "known_at": event["known_at"], "source": "business_receipt", "is_demo": True})
            def selected(store, state_name):
                return next((row for row in inventory if row["store_id"] == store and row["sku_id"] == event["sku_id"] and row["lot_id"] == event["lot_id"] and row["stock_state"] == state_name
                             and (state_name != "in_transit" or row.get("shipment_line_id") == event.get("shipment_line_id"))), None)
            source = selected(event["store_id"], source_state) if source_state else None
            if source_state and (source is None or _number(source["quantity"]) < quantity):
                raise BusinessConflict("insufficient_inventory", "业务事件不能产生负库存")
            if source_state == "on_hand" and _number(source["quantity"]) - _number(source["blocked_qty"]) - _number(source["reserved_qty"]) < quantity:
                raise BusinessConflict("insufficient_inventory", "业务事件不能消耗冻结或外部预占库存")
            if source:
                if kind == "sale" and (source.get("sellable_until") is None or parse_clock(event["occurred_at"]).date() >= date.fromisoformat(source["sellable_until"])):
                    raise ValueError("Sale requires a known, unexpired sellable cutoff")
                source["quantity"] = _number(source["quantity"]) - quantity
                deltas.append({"store_id": source["store_id"], "sku_id": source["sku_id"], "lot_id": source["lot_id"], "stock_state": source_state, "quantity_delta": -quantity, "event_id": event["event_id"], "base_unit": product["base_unit"]})
            if destination_state:
                store = destination_store or event["store_id"]
                if not any(row["store_id"] == store for row in facts["tables"]["stores"]):
                    raise ValueError("Unknown destination store")
                target = selected(store, destination_state)
                if target is None:
                    cost = source["unit_cost"] if source else event.get("unit_cost_cny", event.get("unit_cost"))
                    _number(cost, "unit_cost")
                    target = {"inventory_id": "event-stock:" + inventory_key(store, event["sku_id"], event["lot_id"]) + "|" + destination_state + (":" + event["shipment_line_id"] if destination_state == "in_transit" else ""),
                              "store_id": store, "sku_id": event["sku_id"], "lot_id": event["lot_id"], "stock_state": destination_state,
                              "quantity": 0, "unit_cost": cost, "blocked_qty": 0, "reserved_qty": 0,
                              "sellable_until": source["sellable_until"] if source else event.get("sellable_until"),
                              "shipment_line_id": event.get("shipment_line_id") if destination_state == "in_transit" else None, "source": event.get("source", "business_receipt"), "known_at": event["known_at"]}
                    inventory.append(target)
                elif source and _number(target["unit_cost"]) != _number(source["unit_cost"]):
                    raise ValueError("The same inventory lot has inconsistent unit cost")
                target["quantity"] = _number(target["quantity"]) + quantity
                deltas.append({"store_id": store, "sku_id": target["sku_id"], "lot_id": target["lot_id"], "stock_state": destination_state, "quantity_delta": quantity, "event_id": event["event_id"], "base_unit": product["base_unit"]})
            return source
        if kind == "transfer_shipped":
            target_store = event.get("target_store_id") or event.get("to_store_id")
            if not target_store or target_store == event["store_id"]:
                raise ValueError("Transfer requires a distinct destination store")
            source = move("on_hand", "in_transit", target_store)
            shipments = state["tables"].setdefault("in_transit", deepcopy(facts["tables"]["in_transit"]))
            shipment = next((row for row in shipments if row["shipment_line_id"] == event["shipment_line_id"]), None)
            if shipment is None:
                shipment = {"shipment_line_id": event["shipment_line_id"], "purchase_order_line_id": None, "transfer_order_line_id": event["task_id"],
                            "store_id": target_store, "sku_id": event["sku_id"], "lot_id": event["lot_id"], "shipped_qty": 0, "received_qty": 0,
                            "expected_arrival_at": event.get("expected_arrival_at"), "unit_cost": source["unit_cost"], "known_at": event["known_at"], "source": "business_receipt"}
                shipments.append(shipment)
            shipment["shipped_qty"] = _number(shipment["shipped_qty"]) + _number(event["quantity"])
            shipment["status"] = "in_transit"
        elif kind == "transfer_received":
            move("in_transit", "on_hand")
            shipments = state["tables"].setdefault("in_transit", deepcopy(facts["tables"]["in_transit"]))
            shipment = next((row for row in shipments if row["shipment_line_id"] == event["shipment_line_id"]), None)
            if shipment is None or shipment["store_id"] != event["store_id"]:
                raise ValueError("Transfer receipt has no matching shipment")
            shipment["received_qty"] = _number(shipment["received_qty"]) + _number(event["quantity"])
            if shipment["received_qty"] > _number(shipment["shipped_qty"]):
                raise ValueError("Transfer receipt exceeds shipped amount")
            shipment["status"] = "received" if shipment["received_qty"] == _number(shipment["shipped_qty"]) else "partially_received"
        elif kind == "return_shipped":
            move("on_hand", "return_in_transit")
        elif kind == "supplier_accepted":
            move("return_in_transit")
        elif kind in {"purchase_received", "exchange_received"}:
            move("in_transit" if event.get("shipment_line_id") else None, "on_hand")
            if kind == "purchase_received":
                orders = state["tables"].setdefault("purchase_orders", deepcopy(facts["tables"]["purchase_orders"]))
                order = next((row for row in orders if row["po_line_id"] == event.get("po_line_id")), None)
                if not order:
                    raise ValueError("Purchase receipt requires a confirmed purchase order")
                order["received_qty"] = _number(order["received_qty"]) + _number(event["quantity"])
                if order["received_qty"] > _number(order["ordered_qty"]):
                    raise BusinessConflict("receipt_exceeds_plan", "采购收货超过已确认数量")
                if order["store_id"] != event["store_id"] or order["sku_id"] != event["sku_id"]:
                    raise ValueError("Purchase receipt identity disagrees with its order")
                order["order_status"] = "completed" if order["received_qty"] == _number(order["ordered_qty"]) else "partially_received"
                if event.get("shipment_line_id"):
                    shipments = state["tables"].setdefault("in_transit", deepcopy(facts["tables"]["in_transit"]))
                    shipment = next((row for row in shipments if row["shipment_line_id"] == event["shipment_line_id"]), None)
                    if not shipment:
                        raise ValueError("Unknown inbound shipment")
                    if shipment["purchase_order_line_id"] != order["po_line_id"]:
                        raise ValueError("Shipment and receipt purchase order disagree")
                    shipment["received_qty"] = _number(shipment["received_qty"]) + _number(event["quantity"])
                    if shipment["received_qty"] > _number(shipment["shipped_qty"]):
                        raise BusinessConflict("receipt_exceeds_plan", "收货超过在途数量")
                    shipment["status"] = "received" if shipment["received_qty"] == _number(shipment["shipped_qty"]) else "partially_received"
        elif kind == "sale":
            source = move("on_hand")
            sales = state["appended"].setdefault("sales_daily", [])
            sales.append({"sales_day_id": event["event_id"], "store_id": event["store_id"], "sku_id": event["sku_id"], "lot_id": event["lot_id"],
                          "date": event.get("date") or event["occurred_at"][:10], "sold_qty": event["quantity"], "customer_return_qty": 0,
                          "sales_amount": event.get("sales_amount", event.get("amount_cny")), "refund_amount": 0,
                          "sold_cost": _number(event["quantity"]) * _number(source["unit_cost"]), "returned_cost": 0,
                          "known_at": event["known_at"], "source": event.get("source", "business_receipt"), "is_demo": True})
        elif kind == "order_confirmed":
            product = next((row for row in facts["tables"]["products"] if row["sku_id"] == event.get("sku_id")), None)
            if not product or event.get("base_unit") != product["base_unit"] or not any(row["store_id"] == event.get("store_id") for row in facts["tables"]["stores"]):
                raise ValueError("Confirmed order requires known store, product and base unit")
            if _number(event["quantity"]) <= 0:
                raise ValueError("Confirmed order quantity must be positive")
            orders = state["tables"].setdefault("purchase_orders", deepcopy(facts["tables"]["purchase_orders"]))
            if any(row["po_line_id"] == event["po_line_id"] for row in orders):
                raise BusinessConflict("duplicate_order", "订单行已经存在")
            orders.append({"po_line_id": event["po_line_id"], "po_id": event.get("po_id"), "store_id": event["store_id"], "sku_id": event["sku_id"],
                           "lot_id": event.get("lot_id"), "ordered_qty": _number(event["quantity"]), "received_qty": 0,
                           "unit_cost": _number(event.get("unit_cost_cny", event.get("unit_cost"))), "paid_amount": 0,
                           "due_at": event.get("payment_due"), "expected_arrival_at": event.get("expected_arrival_date"),
                           "supplier_id": event.get("supplier_id"), "payment_status": "unpaid", "order_status": "confirmed",
                           "known_at": event["known_at"], "source": event.get("source", "business_receipt")})
            payables = state["tables"].setdefault("payables", deepcopy(facts["tables"]["payables"]))
            total = _number(event["quantity"]) * _number(event.get("unit_cost_cny", event.get("unit_cost")))
            payables.append({"payable_id": "order:" + event["po_line_id"], "po_line_id": event["po_line_id"], "po_id": event.get("po_id"),
                             "supplier_id": event.get("supplier_id"), "original_amount": total, "outstanding_amount": total, "paid_amount": 0,
                             "applied_credit_amount": 0, "due_at": event.get("payment_due"), "status": "unpaid", "known_at": event["known_at"], "source": "business_receipt"})
            intents = state["tables"].setdefault("purchase_intents", deepcopy(facts["tables"]["purchase_intents"]))
            if event.get("intent_id"):
                intents[:] = [row for row in intents if row["intent_id"] != event["intent_id"]]
        elif kind == "purchase_cancelled":
            if _number(event.get("quantity")) != 0 or not event.get("receipt_ref"):
                raise ValueError("Purchase cancellation requires zero retained quantity and supplier confirmation reference")
            intents = state["tables"].setdefault("purchase_intents", deepcopy(facts["tables"]["purchase_intents"]))
            intent = next((row for row in intents if row["intent_id"] == event.get("intent_id")), None)
            if intent is None:
                raise ValueError("Purchase cancellation references an unknown intent")
            intent.update(intent_status="cancelled", confirmation_ref=event["receipt_ref"], confirmed_at=event["known_at"])
        elif kind in {"credit_applied", "purchase_payment", "payable_payment"}:
            table, id_field = ("purchase_orders", "po_line_id") if kind == "purchase_payment" else ("payables", "payable_id")
            rows = state["tables"].setdefault(table, deepcopy(facts["tables"][table]))
            target_id = event.get(id_field) or event.get("business_ref")
            row = next((item for item in rows if item[id_field] == target_id), None)
            if not row:
                raise ValueError("Settlement references an unknown payable or order")
            amount = _number(event.get("amount_cny", event.get("amount")), "amount")
            if kind == "purchase_payment":
                row["paid_amount"] = _number(row["paid_amount"]) + amount
                if row["paid_amount"] > _number(row["ordered_qty"]) * _number(row["unit_cost"]):
                    raise BusinessConflict("overpayment", "付款超过采购金额")
                payables = state["tables"].setdefault("payables", deepcopy(facts["tables"]["payables"]))
                linked = [item for item in payables if item.get("po_line_id") == row["po_line_id"]]
                if len(linked) > 1:
                    raise ValueError("Order payment requires an unambiguous payable")
                if linked:
                    payable = linked[0]
                    if _number(payable["outstanding_amount"]) < amount:
                        raise ValueError("Order payment exceeds linked outstanding amount")
                    payable["paid_amount"] = _number(payable["paid_amount"]) + amount
                    payable["outstanding_amount"] = _number(payable["outstanding_amount"]) - amount
                    payable["status"] = "settled" if payable["outstanding_amount"] == 0 else "partially_settled"
            else:
                if amount > _number(row["outstanding_amount"]):
                    raise BusinessConflict("overpayment", "结算超过应付未付金额")
                field = "applied_credit_amount" if kind == "credit_applied" else "paid_amount"
                row[field] = _number(row[field]) + amount
                row["outstanding_amount"] = _number(row["outstanding_amount"]) - amount
                row["status"] = "settled" if row["outstanding_amount"] == 0 else "partially_settled"
            if kind == "credit_applied":
                credits = state["tables"].setdefault("credit_notes", deepcopy(facts["tables"].get("credit_notes", [])))
                credit = next((item for item in credits if item["credit_id"] == event.get("credit_id")), None)
                if credit is None or credit["supplier_id"] != row["supplier_id"] or _number(credit["remaining_amount"]) < amount:
                    raise ValueError("Credit application requires sufficient issued credit for the same supplier")
                credit["remaining_amount"] = _number(credit["remaining_amount"]) - amount
        elif kind == "credit_issued":
            credits = state["tables"].setdefault("credit_notes", deepcopy(facts["tables"].get("credit_notes", [])))
            if not event.get("credit_id") or any(row["credit_id"] == event["credit_id"] for row in credits):
                raise ValueError("Credit note requires a unique credit_id")
            amount = _number(event.get("amount_cny", event.get("amount")), "amount")
            if amount <= 0 or not any(row["supplier_id"] == event.get("supplier_id") for row in facts["tables"]["suppliers"]):
                raise ValueError("Issued credit requires a positive amount and known supplier")
            credits.append({"credit_id": event["credit_id"], "supplier_id": event["supplier_id"], "issued_amount": amount,
                            "remaining_amount": amount, "known_at": event["known_at"], "source": event["source"]})
        elif kind == "material_confirmed":
            self._material(facts, state, event)
        elif kind not in STATUS_EVENTS:
            raise ValueError("Unsupported fact business event: " + kind)

    @staticmethod
    def _material(facts, state, event):
        if not event.get("business_ref") or not event.get("receipt_ref"):
            raise ValueError("Material confirmation requires draft and source references")
        fields = deepcopy(event["fields"])
        kind = event["material_kind"]
        common = {"store_id", "sku_id", "lot_id", "supplier_id", "quantity", "unit", "unit_cost_cny"}
        options = {
            "purchase_intent": (common | {"product_name", "expected_arrival_date", "payment_date"},
                                {"store_id", "sku_id", "quantity", "unit", "unit_cost_cny", "expected_arrival_date", "payment_date", "supplier_id"}),
            "return_terms": (common | {"settlement_mode", "return_deadline", "refund_pct", "max_return_qty", "freight_fee_cny", "restocking_fee_cny", "settlement_days", "contract_allows_return", "requires_supplier_acceptance"},
                             {"supplier_id", "sku_id", "settlement_mode", "return_deadline"}),
        }
        if kind not in options or not isinstance(fields, dict):
            raise ValueError("Unsupported material kind or field shape")
        allowed, required = options[kind]
        if set(fields) - allowed:
            raise ValueError("Unsupported confirmed material fields")
        unresolved = {key for key in required if fields.get(key) is None or fields.get(key) == "" or fields.get(key) == "unknown"}
        accepted = event.get("accepted_unresolved_fields", [])
        if not isinstance(accepted, list) or set(accepted) != unresolved:
            raise ValueError("Missing material fields require explicit, exact acknowledgement")
        for key in unresolved:
            fields[key] = None
        for field, table in (("store_id", "stores"), ("sku_id", "products"), ("supplier_id", "suppliers"), ("lot_id", "lots")):
            if fields.get(field) is not None and not any(row[field] == fields[field] for row in facts["tables"][table]):
                raise ValueError("Unknown material reference: " + field)
        if fields.get("lot_id") and fields.get("sku_id") and not any(row["lot_id"] == fields["lot_id"] and row["sku_id"] == fields["sku_id"] for row in facts["tables"]["lots"]):
            raise ValueError("Material lot and product disagree")
        if fields.get("sku_id") and fields.get("unit"):
            product = next(row for row in facts["tables"]["products"] if row["sku_id"] == fields["sku_id"])
            if fields["unit"] != product["base_unit"]:
                raise ValueError("Material quantity must use the product base unit")
        for key in ("quantity", "unit_cost_cny", "refund_pct", "max_return_qty", "freight_fee_cny", "restocking_fee_cny", "settlement_days"):
            if fields.get(key) is not None:
                value = _number(fields[key], key)
                if key == "quantity" and value <= 0 or key == "refund_pct" and value > 100 or key == "settlement_days" and value != value.to_integral_value():
                    raise ValueError("Invalid confirmed material number: " + key)
        for key in ("contract_allows_return", "requires_supplier_acceptance"):
            if fields.get(key) is not None and not isinstance(fields[key], bool):
                raise ValueError("Material flags must be boolean")
        for key in ("expected_arrival_date", "payment_date", "return_deadline"):
            if fields.get(key) is not None:
                date.fromisoformat(fields[key])
        if fields.get("settlement_mode") not in {None, "cash_refund", "payable_credit", "exchange"}:
            raise ValueError("Unsupported material settlement mode")
        if "unit_cost_cny" in fields:
            fields["unit_cost"] = fields.pop("unit_cost_cny")
        fields["missing_fields"] = sorted(unresolved)
        if kind == "purchase_intent":
            row = {**fields, "intent_id": event["business_ref"], "source_ref": event["receipt_ref"], "intent_status": "draft_unconfirmed",
                   "confirmation_required": True, "known_at": event["known_at"], "source": "confirmed_material", "is_demo": True}
            rows = state["tables"].setdefault("purchase_intents", deepcopy(facts["tables"]["purchase_intents"]))
            rows[:] = [item for item in rows if item.get("source_ref") != event["receipt_ref"]]
            rows.append(row)
        elif kind == "return_terms":
            rows = state["tables"].setdefault("return_terms", deepcopy(facts["tables"]["return_terms"]))
            replaced = [item for item in rows if item.get("supplier_id") == fields.get("supplier_id") and item.get("sku_scope") == fields.get("sku_id")]
            if len(replaced) > 1:
                raise ValueError("Multiple existing return terms require explicit business resolution")
            row = {**fields, "term_id": event["business_ref"], "source_ref": event["receipt_ref"], "confirmed_at": event["known_at"],
                   "sku_scope": fields.get("sku_id"), "allowed_settlement_modes": fields.get("settlement_mode"),
                   "supersedes_term_id": replaced[0]["term_id"] if replaced else None,
                   "known_at": event["known_at"], "source": "confirmed_material", "is_demo": True}
            rows[:] = [item for item in rows if item not in replaced]
            rows.append(row)

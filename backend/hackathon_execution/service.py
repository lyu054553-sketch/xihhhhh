"""Execution services over the shared database and injected fact/calculation services.

Only receipts, channel histories and command identities are owned here. Stock is
published through FactService; proposals, tasks, reservations and money use the
existing shared tables. The domain state is a disposable transaction projection.
"""
from copy import deepcopy
from datetime import date
from decimal import Decimal
import hashlib
import json

from ..errors import BusinessConflict
from ..hackathon_shared import CONTRACT_VERSION, TransactionProvider, FactService, CalculationService
from ..serialization import dumps, json_value
from . import domain


SCHEMA = (
    """CREATE TABLE IF NOT EXISTS hackathon_execution_commands (
      scope TEXT NOT NULL, command_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
      response_json TEXT NOT NULL, PRIMARY KEY(scope,command_key))""",
    """CREATE TABLE IF NOT EXISTS hackathon_execution_receipts (
      scope TEXT NOT NULL, event_key TEXT NOT NULL, kind TEXT NOT NULL,
      fingerprint TEXT NOT NULL, payload_json TEXT NOT NULL, cash_id TEXT,
      PRIMARY KEY(scope,event_key), FOREIGN KEY(cash_id) REFERENCES cash_events(id))""",
    """CREATE TABLE IF NOT EXISTS hackathon_channel_actions (
      scope TEXT NOT NULL, task_id TEXT NOT NULL, channel TEXT NOT NULL,
      payload_json TEXT NOT NULL, PRIMARY KEY(scope,task_id,channel),
      FOREIGN KEY(task_id) REFERENCES execution_tasks(id))""",
)
ID_FIELDS = {"business": "event_id", "sale": "sale_id", "cash": "cash_event_id",
             "cash_allocation": "allocation_id", "return_confirmation": "return_id"}
LEDGERS = {"business": "receipts", "sale": "sales", "cash": "cash_events",
           "cash_allocation": "cash_allocations", "return_confirmation": "return_confirmations"}
APPLIERS = {"business": domain.apply_business_receipt, "sale": domain.apply_sale,
            "cash": domain.apply_cash, "cash_allocation": domain.apply_cash_allocation,
            "return_confirmation": domain.apply_return_confirmation}


def migrate(tx):
    if not tx.in_transaction:
        raise ValueError("Migration requires the shared active transaction")
    for statement in SCHEMA:
        tx.execute(statement)


def decode(value):
    return json.loads(value, parse_float=Decimal)


def fingerprint(value):
    return hashlib.sha256(json.dumps(json_value(value), sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def scope(context):
    return dumps([context["tenant_id"], context["snapshot_id"]])


def raw_status(task):
    if task["exception_flags"]:
        return "exception"
    if task["execution_status"] == "completed" and not task["cancelled"]:
        return "completed"
    progress = task["progress"]
    if progress.get("received_qty"):
        return "awaiting_receipt"
    if progress.get("shipped_qty"):
        return "in_transit"
    return "draft_pending_external_execution"


def presentation(task):
    result = deepcopy(task)
    result["task_id"] = result.pop("id")
    result["assignee_id"] = result.pop("owner_id")
    result["planned_qty"] = task["plan"]["allocated_qty"]
    result["completed_qty"] = task["progress"].get("received_qty", task["progress"].get("accepted_qty", 0))
    if task["type"] == "promotion":
        result["completed_qty"] = result["planned_qty"] if task["progress"].get("promotion_ended") else 0
    result.update(is_demo=True, external_write=False)
    cash = task.get("result", {})
    received = cash.get("sales_cash_received", 0) + cash.get("refund_cash_received", 0)
    result["accounting"] = {"expected_cash_cny": task.get("candidate_calculation", {}).get("expected_cash_in_cny"),
        "actual_cash_cny": received if received else None, "uncollected_expected_cny": cash.get("outstanding_cash"),
        "status_detail": task["accounting_status"]}
    result["exception"] = task["exception_flags"] or None
    result["status"] = raw_status(task)
    result["closed_reason"] = task.get("cancellation_reason")
    result["display_status"] = "cancelled" if task["cancelled"] else "exception" if task["exception_flags"] else (
        "completed" if task["execution_status"] == task["accounting_status"] == "completed" else "following_up")
    result["next_action"] = "重新规划" if task["cancelled"] or task["exception_flags"] else (
        "核对资金与费用回执" if task["execution_status"] == "completed" else "跟进执行回执")
    return result


class ExecutionService:
    def __init__(self, database: TransactionProvider, facts: FactService, calculations: CalculationService,
                 *, replay_reader=None, clock_advancer=None):
        self.database, self.facts, self.calculations = database, facts, calculations
        self.replay_reader, self.clock_advancer = replay_reader, clock_advancer

    def _query(self, context):
        return self.facts.query({"context": context})

    def _command(self, request, operation, action):
        context = request["context"]
        actor = request.get("actor_id")
        key = request.get("idempotency_key")
        if not isinstance(actor, str) or not actor.strip():
            raise ValueError("actor_id is required for audit; authorization belongs to the HTTP boundary")
        if not isinstance(key, str) or not key.strip() or len(key) > 200:
            raise ValueError("A bounded idempotency_key is required")
        digest = fingerprint({"operation": operation, "request": request})
        with self.database.transaction() as tx:
            previous = tx.execute("SELECT * FROM hackathon_execution_commands WHERE scope=? AND command_key=?", (scope(context), key)).fetchone()
            if previous:
                if previous["fingerprint"] != digest:
                    raise BusinessConflict("idempotency_conflict", "幂等键已经用于其他内容")
                return {**decode(previous["response_json"]), "idempotent_replay": True}
            facts = self._query(context)  # authoritative version and tenant check, inside transaction
            response = {"contract_version": CONTRACT_VERSION, "idempotent_replay": False,
                        **action(tx, facts)}
            tx.execute("INSERT INTO hackathon_execution_commands VALUES(?,?,?,?)", (scope(context), key, digest, dumps(response)))
            return json_value(response)

    def save_proposal(self, request):
        def save(tx, facts):
            context = facts["context"]
            comparison_request = {key: request[key] for key in ("context", "risk_keys", "objective", "horizon_start", "horizon_end", "assumption_ids", "inputs", "business_inputs") if key in request}
            risk_keys = request.get("risk_keys", [])
            if not risk_keys or len(risk_keys) != len(set(risk_keys)):
                raise ValueError("A nonempty unique risk_keys list is required")
            risk_key = risk_keys[0]
            comparison = self.calculations.compare(facts, comparison_request)
            if comparison["comparison_id"] != request["comparison_id"]:
                raise BusinessConflict("stale_comparison", "比较依据已变化，请重新计算")
            selected = next((item for item in comparison["candidates"] + comparison.get("candidate_groups", [])
                             if item.get("candidate_id", item.get("group_id")) == request["candidate_id"]), None)
            if selected is None:
                raise ValueError("Candidate does not belong to this comparison")
            risk_id = self.facts.resolve_legacy_risk_id(context, risk_key)
            if risk_id is None:
                raise ValueError("A mapped factual risk_key is required")
            # The mapped risk must refer to the selected stock, not an unrelated row.
            plan = selected["calculation"]["execution_plan"]
            actions = plan.get("actions", [])
            target = facts["reference_data"]["target"]
            allowed = {"|".join(str(row.get(k)) for k in ("store_id", "sku_id", "lot_id")) for row in actions}
            allowed.add("|".join(target[k] for k in ("store_id", "sku_id", "lot_id")))
            parts = risk_key.split(":")
            if len(parts) != 5 or parts[0] != context["scenario_id"] or "|".join(parts[1:4]) not in allowed:
                raise ValueError("risk_key does not identify the compared stock")
            proposal_id = request.get("proposal_id") or domain.identifier("proposal")
            expected = request["expected_current_proposal_version"]
            if type(expected) is not int or expected < 0:
                raise ValueError("expected_current_proposal_version must be a nonnegative integer")
            old = tx.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()
            version = 1
            if old:
                if old["tenant_id"] != context["tenant_id"] or old["snapshot_id"] != context["snapshot_id"]:
                    raise ValueError("Unknown proposal")
                if old["status"] != "pending_approval" or old["current_version"] != expected:
                    raise BusinessConflict("version_conflict", "只能更新当前待确认方案；已执行方案需创建新方案")
                version = old["current_version"] + 1
                tx.execute("UPDATE proposal_versions SET status='invalidated',invalid_reason='superseded' WHERE proposal_id=? AND version=?", (proposal_id, old["current_version"]))
                tx.execute("UPDATE proposals SET current_version=?,fact_version=? WHERE id=?", (version, context["fact_version"], proposal_id))
            else:
                if expected != 0:
                    raise BusinessConflict("version_conflict", "新方案的预期版本必须为0")
                tx.execute("INSERT INTO proposals VALUES(?,?,?,?,?,?,?,?)", (proposal_id, context["tenant_id"], risk_id, version,
                           "pending_approval", context["snapshot_id"], context["fact_version"], context["as_of"]))
            children = plan["children"] if plan["type"] == "combination" else [plan]
            units = {row["sku_id"]: row["base_unit"] for row in facts["reference_data"]["tables"]["products"]}
            action_lines = []
            action_calculations = {}
            for index, child in enumerate(children):
                if not child["actions"]:
                    continue  # retaining stock saves a baseline but creates no execution action
                action = child["actions"][0]
                action_lines.append({"action_line_id": "LINE-" + fingerprint([comparison["comparison_id"], request["candidate_id"], index])[:24],
                    "action_type": "procurement" if child["type"] == "purchase" else child["type"],
                    "store_id": action["store_id"], "target_store_id": action.get("target_store_id"),
                    "sku_id": action["sku_id"], "lot_id": action.get("lot_id"), "quantity": child["allocated_qty"],
                    "base_unit": "组" if child["type"] == "promotion" else units[action["sku_id"]]})
                public_child = next((c for c in comparison["candidates"] if c["calculation"]["execution_plan"] == child), None)
                action_calculations[action_lines[-1]["action_line_id"]] = public_child["calculation"] if public_child else {}
            payload = {"context": context, "comparison_request": comparison_request, "comparison_id": comparison["comparison_id"],
                       "candidate_id": request["candidate_id"], "candidate": selected, "baseline_id": comparison["baseline_id"],
                       "evaluation_end": comparison["horizon_end"], "risk_key": risk_key, "created_by": request["actor_id"],
                       "action_lines": action_lines, "action_calculations": action_calculations}
            tx.execute("INSERT INTO proposal_versions VALUES(?,?,?,?,?,?,?)", (domain.identifier("pv"), proposal_id, version,
                       dumps(payload), "pending_approval", None, context["as_of"]))
            return {"context": context, "proposal_id": proposal_id, "proposal_version": version,
                    "status": "draft", "comparison_id": comparison["comparison_id"], "candidate_id": request["candidate_id"],
                    "risk_key": risk_key, "snapshot_id": context["snapshot_id"], "fact_version": context["fact_version"],
                    "data_version": context["data_version"], "policy_version": comparison["policy_version"],
                    "calculation_version": comparison["calculation_version"], "action_lines": action_lines}
        return self._command(request, "save_proposal", save)

    def confirm_and_schedule(self, request):
        def confirm(tx, facts):
            context = facts["context"]
            if any(type(request[key]) is not int or request[key] < 1 for key in ("expected_fact_version", "expected_proposal_version")):
                raise ValueError("Expected versions must be positive integers")
            if request["expected_fact_version"] != context["fact_version"] or request["expected_snapshot_id"] != context["snapshot_id"]:
                raise BusinessConflict("version_conflict", "确认时的事实或快照版本不一致")
            row = tx.execute("SELECT * FROM proposals WHERE id=? AND tenant_id=? AND snapshot_id=?", (
                request["proposal_id"], context["tenant_id"], context["snapshot_id"])).fetchone()
            if not row or row["status"] != "pending_approval" or row["current_version"] != request["expected_proposal_version"]:
                raise BusinessConflict("stale_proposal", "方案已确认或版本已变化")
            payload = decode(tx.execute("SELECT payload_json FROM proposal_versions WHERE proposal_id=? AND version=?", (row["id"], row["current_version"])).fetchone()[0])
            if request["candidate_id"] != payload["candidate_id"]:
                raise BusinessConflict("stale_proposal", "确认候选与保存方案不一致")
            comparison = self.calculations.compare(facts, payload["comparison_request"])
            if comparison["comparison_id"] != payload["comparison_id"]:
                raise BusinessConflict("stale_proposal", "事实、库存占用或计算规则已变化，请重新比较")
            if not payload["candidate"]["feasible"]:
                raise BusinessConflict("infeasible_proposal", "方案仍有未满足的执行条件")
            assignments = request["task_assignments"]
            if len(assignments) != len(payload["action_lines"]) or {a["action_line_id"] for a in assignments} != {a["action_line_id"] for a in payload["action_lines"]}:
                raise ValueError("Each executable action requires exactly one assignment")
            assignments = {a["action_line_id"]: a for a in assignments}
            state = self._hydrate(tx, facts)
            plan = payload["candidate"]["calculation"]["execution_plan"]
            children = plan["children"] if plan["type"] == "combination" else [plan]
            if len(children) != len(payload["action_lines"]):
                raise BusinessConflict("infeasible_proposal", "保留原计划不产生执行任务")
            tasks = []
            for child, line in zip(children, payload["action_lines"]):
                assignment = assignments[line["action_line_id"]]
                if domain.timestamp(assignment["due_at"]) < domain.timestamp(context["as_of"]):
                    raise ValueError("Task deadline precedes the business clock")
                task = domain.arrange_execution(state, {"id": row["id"], "version": row["current_version"],
                    "candidate": child, "evaluation_end": payload["evaluation_end"]}, actor_id=request["actor_id"],
                    owner_id=assignment["assignee_id"], due_at=assignment["due_at"])
                task.update(action_line_id=line["action_line_id"], base_unit=line["base_unit"],
                            candidate_calculation=payload["action_calculations"][line["action_line_id"]])
                tasks.append(task)
            approval_id, group = domain.identifier("approval"), domain.identifier("task-group")
            tx.execute("INSERT INTO approvals VALUES(?,?,?,?,?,?,?,?)", (approval_id, context["tenant_id"], row["id"],
                       row["current_version"], request["actor_id"], "approved", dumps([scope(context), request["idempotency_key"]]), context["as_of"]))
            for task in tasks:
                task["task_group_id"] = group
                tx.execute("INSERT INTO execution_tasks VALUES(?,?,?,?,?,?,?,?,?)", (task["id"], context["tenant_id"], row["id"],
                           row["current_version"], "draft_pending_external_execution", task["id"], context["as_of"], dumps(task), 1))
            tx.execute("UPDATE proposals SET status='execution_task_created' WHERE id=?", (row["id"],))
            tx.execute("UPDATE proposal_versions SET status='approved' WHERE proposal_id=? AND version=?", (row["id"], row["current_version"]))
            self._persist_tasks(tx, context, state)
            changed = self._publish(tx, context, [self._event(context, "execution_scheduled", approval_id, {}, tasks[0])])
            return {"context": changed["context"], "approval_id": approval_id, "proposal_id": row["id"],
                    "proposal_version": row["current_version"], "approved_by": request["actor_id"], "approved_at": context["as_of"],
                    "status": "approved", "task_group_id": group, "tasks": [presentation(t) for t in tasks]}
        return self._command(request, "confirm_and_schedule", confirm)

    def _hydrate(self, tx, facts):
        context = facts["context"]
        tables = deepcopy(facts["reference_data"]["tables"])
        tables["payables"] = facts["payables"]
        tables["inventory"] = [{**row, "unit_cost": row["unit_cost_cny"], "reserved_qty": row["external_reserved_qty"]}
                               for row in facts["inventory"]]
        state = domain.initial_execution({"clock_at": context["as_of"], "tables": tables})
        state["base_units"] = {row["sku_id"]: row["base_unit"] for row in tables["products"]}
        stored_rows = tx.execute("SELECT * FROM hackathon_execution_receipts WHERE scope=? ORDER BY rowid", (scope(context),)).fetchall()
        recorded_sales = [decode(row["payload_json"]) for row in stored_rows if row["kind"] == "sale"]
        rows = tx.execute("SELECT t.* FROM execution_tasks t JOIN proposals p ON p.id=t.proposal_id WHERE t.tenant_id=? AND p.snapshot_id=? ORDER BY t.rowid", (context["tenant_id"], context["snapshot_id"])).fetchall()
        state["tasks"] = [decode(r["metadata_json"]) for r in rows if decode(r["metadata_json"]).get("task_group_id")]
        for task in state["tasks"]:
            if task["type"] == "transfer" and domain.number(task["progress"].get("shipped_qty", 0)) < domain.number(task["plan"]["allocated_qty"]):
                action = task["plan"]["actions"][0]
                receiving = [row for row in tables.get("store_calendar", []) if row["store_id"] == action["target_store_id"] and row["date"] == action["arrival_date"]]
                if receiving and any(not row.get("is_open") or not row.get("can_receive") for row in receiving) and "replan_required" not in task["exception_flags"]:
                    task["exception_flags"].append("replan_required")
            if task["cancelled"] or task["progress"].get("promotion_ended"):
                continue
            for allocation in task["plan"]["allocations"]:
                consumed = sum((domain.number(s["sold_qty"]) for s in recorded_sales if s.get("task_id") == task["id"]
                                and all(s.get(k) == allocation[k] for k in ("store_id", "sku_id", "lot_id"))), Decimal(0)) if task["type"] == "promotion" else task["progress"].get("shipped_qty", 0)
                remaining = domain.number(allocation["quantity"]) - domain.number(consumed)
                state["reservations"].append({"task_id": task["id"], "resource": domain.resource(allocation), "quantity": remaining})
        own_proposals = {t["proposal_id"] for t in state["tasks"]}
        for row in tx.execute("SELECT * FROM inventory_reservations WHERE tenant_id=? AND snapshot_id=?", (context["tenant_id"], context["snapshot_id"])):
            if row["proposal_id"] not in own_proposals:
                state["reservations"].append({"task_id": None, "resource": row["resource_key"], "quantity": row["quantity"]})
        for entry in stored_rows:
            record = decode(entry["payload_json"])
            if entry["cash_id"]:
                cash = tx.execute("SELECT * FROM cash_events WHERE id=?", (entry["cash_id"],)).fetchone()
                record["amount"], record["direction"] = domain.number(cash["amount"]), cash["direction"]
            state[LEDGERS[entry["kind"]]].append(record)
        for receipt in state["receipts"]:
            if receipt["event_type"] == "credit_issued":
                used = sum((domain.number(r["amount"]) for r in state["receipts"] if r["event_type"] == "credit_applied" and r["credit_note_id"] == receipt["credit_note_id"]), Decimal(0))
                state["credits"].append({**receipt, "used_amount": used})
        return state

    def _persist_tasks(self, tx, context, state):
        domain.project_execution(state)
        for task in state["tasks"]:
            tx.execute("UPDATE execution_tasks SET status=?,metadata_json=?,version=? WHERE id=? AND tenant_id=?",
                       (raw_status(task), dumps(task), task["version"], task["id"], context["tenant_id"]))
        for proposal_id in {t["proposal_id"] for t in state["tasks"]}:
            tx.execute("DELETE FROM inventory_reservations WHERE tenant_id=? AND proposal_id=?", (context["tenant_id"], proposal_id))
        totals = {}
        tasks = {t["id"]: t for t in state["tasks"]}
        for held in state["reservations"]:
            task = tasks.get(held["task_id"])
            if task and held["quantity"]:
                key = (task["proposal_id"], task["proposal_version"], held["resource"])
                totals[key] = totals.get(key, Decimal(0)) + domain.number(held["quantity"])
        for (proposal_id, version, resource), quantity in totals.items():
            if quantity != quantity.to_integral_value():
                raise ValueError("Current shared reservation schema requires whole base units")
            tx.execute("INSERT INTO inventory_reservations VALUES(?,?,?,?,?,?)", (context["tenant_id"], context["snapshot_id"], resource, proposal_id, version, int(quantity)))

    def _event(self, context, kind, event_id, details, task=None):
        return {"event_id": event_id, "tenant_id": context["tenant_id"], "scenario_id": context["scenario_id"],
                "branch_id": context["branch_id"], "task_id": task["id"] if task else None,
                "proposal_id": task["proposal_id"] if task else None, "proposal_version": task["proposal_version"] if task else None,
                "event_type": kind, "occurred_at": details.get("occurred_at", details.get("known_at", context["as_of"])),
                "known_at": details.get("known_at", context["as_of"]), "store_id": details.get("store_id"),
                "target_store_id": details.get("to_store_id"), "sku_id": details.get("sku_id"), "lot_id": details.get("lot_id"),
                "quantity": details.get("quantity", details.get("sold_qty")), "base_unit": details.get("base_unit"),
                "amount_cny": details.get("amount"), "business_ref": details.get("business_ref"),
                "receipt_ref": details.get("receipt_ref"), "source": "local_execution", "is_demo": True,
                "external_write": False, "details": deepcopy(details)}

    def _publish(self, tx, context, events):
        return self.facts.apply_business_events(tx, events, expected_fact_version=context["fact_version"])

    def _record(self, tx, context, state, kind, raw, *, clock_at):
        if kind not in ID_FIELDS:
            raise ValueError("Unsupported receipt kind")
        record = {**deepcopy(raw), "is_demo": True, "external_write": False}
        expected_task_version = record.pop("task_version", None)
        if record.get("sku_id"):
            base_unit = state["base_units"].get(record["sku_id"])
            if base_unit is None or any(record.get(field) is not None and record[field] != base_unit for field in ("base_unit", "unit")):
                raise ValueError("Receipt quantity must use the product's explicit base unit")
            record["base_unit"] = base_unit
        task = next((t for t in state["tasks"] if t["id"] == record.get("task_id")), None)
        if task and (record.get("proposal_id") != task["proposal_id"] or record.get("proposal_version") != task["proposal_version"]):
            raise BusinessConflict("version_conflict", "业务回执必须绑定批准的方案版本")
        if task and kind == "business":
            action = task["plan"]["actions"][0]
            identity_fields = ("supplier_id", "intent_id", "expected_arrival_date") if record["event_type"] in {"order_confirmed", "purchase_cancelled"} else ()
            if record["event_type"] == "supplier_accepted":
                identity_fields = ("store_id", "sku_id", "lot_id", "supplier_id")
            for field in identity_fields:
                if record.get(field) is not None and record[field] != action.get(field):
                    raise BusinessConflict("receipt_scope_mismatch", "回执身份或到货条件与批准动作不一致")
                record[field] = action.get(field)
        event_key = kind + ":" + record[ID_FIELDS[kind]]
        digest = fingerprint(record)
        previous = tx.execute("SELECT fingerprint FROM hackathon_execution_receipts WHERE scope=? AND event_key=?", (scope(context), event_key)).fetchone()
        if previous:
            if previous["fingerprint"] != digest:
                raise BusinessConflict("event_identity_conflict", "事件编号对应的内容已变化")
            return None, event_key
        if task and expected_task_version is not None:
            if type(expected_task_version) is not int or expected_task_version != task["version"]:
                raise BusinessConflict("version_conflict", "任务版本已变化，请重新读取", task["version"])
        clock = domain.timestamp(clock_at)
        if not record.get("known_at") or domain.timestamp(record["known_at"]) > clock:
            raise BusinessConflict("future_receipt", "回执尚未到达当前业务时钟")
        if record.get("occurred_at") and domain.timestamp(record["occurred_at"]) > clock or record.get("date") and date.fromisoformat(record["date"]) > clock.date():
            raise BusinessConflict("future_receipt", "回执发生在当前业务时钟之后")
        APPLIERS[kind](state, record)
        # Capture normalized cost and canonical receivable attribution from the domain.
        stored = deepcopy(state[LEDGERS[kind]][-1])
        cash_id = None
        if kind == "cash":
            cash_id = "cash-" + fingerprint([scope(context), record["cash_event_id"]])
            tx.execute("INSERT INTO cash_events VALUES(?,?,?,?,?,?,?,?,?,?)", (cash_id, context["tenant_id"], context["snapshot_id"],
                       record.get("category", "cash_receipt"), str(domain.number(record["amount"])), record["direction"],
                       record["occurred_at"], record.get("business_ref"), "hackathon_execution:" + record["account_id"], record["receipt_ref"]))
            stored.pop("amount")  # shared cash_events is the only persisted amount truth
        tx.execute("INSERT INTO hackathon_execution_receipts VALUES(?,?,?,?,?,?)", (scope(context), event_key, kind, digest, dumps(stored), cash_id))
        event_type = record["event_type"] if kind == "business" else "sale" if kind == "sale" else (
            record.get("category") if kind == "cash" and record.get("category") in {"purchase_payment", "payable_payment"} else "execution_receipt_recorded")
        details = {**record}
        if task:
            action = task["plan"]["actions"][0]
            for field in ("supplier_id", "expected_arrival_date", "intent_id"):
                if details.get(field) is None:
                    details[field] = action.get(field)
            if kind == "business" and record["event_type"] == "supplier_accepted":
                for field in ("store_id", "sku_id", "lot_id"):
                    details[field] = action[field]
            if kind == "business" and record["event_type"] in {"transfer_shipped", "transfer_received"}:
                details["shipment_line_id"] = "transfer:" + task["id"]
                details["expected_arrival_at"] = action.get("arrival_date")
        if details.get("sku_id"):
            details["base_unit"] = state["base_units"].get(details["sku_id"])
        return self._event(context, event_type, event_key, details, task), None

    def record_business_events(self, request):
        def record(tx, facts):
            context = facts["context"]
            event_times = [item.get("record", {}).get("known_at") for item in request["events"]]
            event_times = [value for value in event_times if isinstance(value, str)]
            if event_times:
                latest_known = max(event_times, key=domain.timestamp)
                if domain.timestamp(latest_known) > domain.timestamp(context["as_of"]):
                    if self.clock_advancer is None:
                        raise BusinessConflict("future_receipt", "回执晚于当前业务时钟，无法安全写入")
                    advanced = self.clock_advancer(tx, context, latest_known)
                    context = advanced["context"]
                    facts = self._query(context)
            state = self._hydrate(tx, facts)
            events, duplicates = [], []
            for item in request["events"]:
                event, duplicate = self._record(tx, context, state, item["kind"], item["record"], clock_at=context["as_of"])
                if event:
                    events.append(event)
                if duplicate:
                    duplicates.append(duplicate)
            self._persist_tasks(tx, context, state)
            result = self._publish(tx, context, events) if events else {"context": context, "applied_event_ids": [], "inventory_deltas": []}
            return {**result, "duplicate_event_ids": duplicates, "accounting": self._accounting(tx, result["context"])}
        return self._command(request, "record_business_events", record)

    def cancel_task(self, request):
        def cancel(tx, facts):
            context = facts["context"]
            state = self._hydrate(tx, facts)
            task = next((t for t in state["tasks"] if t["id"] == request["task_id"]), None)
            if not task or task["cancelled"] or not str(request.get("reason", "")).strip():
                raise BusinessConflict("task_not_active", "需要有效任务和撤销原因")
            task.update(cancelled=True, cancellation_reason=request["reason"], cancelled_by=request["actor_id"])
            task["version"] += 1
            state["reservations"] = [r for r in state["reservations"] if r["task_id"] != task["id"]]
            self._persist_tasks(tx, context, state)
            changed = self._publish(tx, context, [self._event(context, "execution_cancelled", domain.identifier("cancel"), {}, task)])
            return {"context": changed["context"], "task": presentation(task)}
        return self._command(request, "cancel_task", cancel)

    def record_channel_action(self, request):
        def record(tx, facts):
            context = facts["context"]
            state = self._hydrate(tx, facts)
            task = next((t for t in state["tasks"] if t["id"] == request["task_id"]), None)
            if not task or task["cancelled"] or task["exception_flags"]:
                raise BusinessConflict("unapproved_action", "需要有效的已确认执行任务")
            expected_task_version = request.get("task_version")
            if expected_task_version is not None and (type(expected_task_version) is not int or expected_task_version != task["version"]):
                raise BusinessConflict("version_conflict", "任务版本已变化，请重新读取", task["version"])
            channel, status = request["channel"], request["status"]
            if request["proposal_id"] != task["proposal_id"] or request["proposal_version"] != task["proposal_version"]:
                raise BusinessConflict("version_conflict", "渠道动作的批准版本不一致")
            if channel not in {"feishu", "wecom", "email"} or not request.get("target_ref") or not request.get("content_snapshot"):
                raise ValueError("Local channel, recipient and content are required")
            row = tx.execute("SELECT payload_json FROM hackathon_channel_actions WHERE scope=? AND task_id=? AND channel=?", (scope(context), task["id"], channel)).fetchone()
            previous = decode(row[0]) if row else None
            transitions = {None: {"draft_saved"}, "draft_saved": {"sent", "failed"}, "failed": {"draft_saved", "sent"}, "sent": {"accepted", "reply_received"}, "reply_received": {"accepted"}, "accepted": {"completed"}, "completed": set()}
            if status not in transitions.get(previous["status"] if previous else None, set()):
                raise BusinessConflict("invalid_transition", "渠道记录需要保留前序状态")
            if previous and any(previous[k] != request[k] for k in ("content_snapshot", "target_ref")):
                raise BusinessConflict("channel_content_changed", "已经记录的内容和收件人不能覆盖")
            action = previous or {"action_id": domain.identifier("channel"), "task_id": task["id"], "channel": channel,
                "proposal_id": task["proposal_id"], "proposal_version": task["proposal_version"], "target_ref": request["target_ref"],
                "content_snapshot": request["content_snapshot"], "action_type": request.get("action_type"),
                "is_demo": True, "external_write": False, "history": [], "source": "local_channel_simulation", "created_at": context["as_of"]}
            action["status"] = status
            action.update(idempotency_key=request["idempotency_key"], receipt_ref=request.get("receipt_ref"))
            action["history"].append({"status": status, "at": context["as_of"], "actor_id": request["actor_id"], "receipt": request.get("receipt")})
            tx.execute("INSERT INTO hackathon_channel_actions VALUES(?,?,?,?) ON CONFLICT(scope,task_id,channel) DO UPDATE SET payload_json=excluded.payload_json", (scope(context), task["id"], channel, dumps(action)))
            return {"context": context, **action}
        return self._command(request, "record_channel_action", record)

    def _accounting(self, tx, context):
        facts = self._query(context)
        state = self._hydrate(tx, facts)
        projection = domain.project_execution(state)
        projection["tasks"] = [presentation(t) for t in state["tasks"]]
        accounts = facts["reference_data"]["tables"].get("accounts", [])
        projection["account_balance_cny"] = sum((domain.number(a["available_balance"]) for a in accounts), Decimal(0)) if accounts else None
        projection["actual_cash_in_cny"] = projection["cash_in"] if any(c["direction"] == "in" for c in state["cash_events"]) else None
        projection["channels"] = [decode(r[0]) for r in tx.execute("SELECT payload_json FROM hackathon_channel_actions WHERE scope=? ORDER BY rowid", (scope(context),))]
        projection["timeline"] = [{"event_id": r["event_key"], "kind": r["kind"], "record": decode(r["payload_json"])} for r in tx.execute("SELECT * FROM hackathon_execution_receipts WHERE scope=? ORDER BY rowid", (scope(context),))]
        projection["payables"] = state["payables"]
        projection["case_results"] = [self._case_accounting(state, task) for task in state["tasks"]]
        return json_value(projection)

    def _case_accounting(self, state, task):
        values, progress = task["result"], task["progress"]
        sales = [row for row in state["sales"] if row.get("task_id") == task["id"]]
        allocations = [row for row in state["cash_allocations"] if row.get("task_id") == task["id"]]
        cash_ids = {row["cash_event_id"] for row in allocations}
        cash_ids.update(row["cash_event_id"] for row in state["cash_events"] if row.get("task_id") == task["id"])
        received = values["sales_cash_received"] + values["refund_cash_received"]
        action = task["plan"]["actions"][0]
        ending = sum((p["quantity"] for p in state["positions"].values() if p["stock_state"] == "on_hand"
                      and p["store_id"] == action.get("target_store_id", action["store_id"])
                      and p["sku_id"] == action["sku_id"] and p["lot_id"] == action.get("lot_id")), Decimal(0)) if action.get("lot_id") else None
        owned_cash = [c for c in state["cash_events"] if c["cash_event_id"] in cash_ids and c["direction"] == "in"]
        unmatched = sum((domain.number(c["amount"]) - sum((domain.number(a["allocated_amount"]) for a in state["cash_allocations"] if a["cash_event_id"] == c["cash_event_id"]), Decimal(0)) for c in owned_cash), Decimal(0))
        return {"task_id": task["id"], "proposal_id": task["proposal_id"], "proposal_version": task["proposal_version"],
                "planned_qty": task["plan"]["allocated_qty"], "shipped_qty": progress.get("shipped_qty", 0),
                "received_qty": progress.get("received_qty", 0), "remaining_unexecuted_qty": values["remaining_execution_qty"],
                "sold_qty": progress.get("sold_qty"), "sold_components": progress.get("sold_components", {}), "base_unit": task["base_unit"],
                "ending_qty": ending, "sales_amount_cny": values["sales_amount"] if sales else None,
                "expected_cash_in_cny": task.get("candidate_calculation", {}).get("expected_cash_in_cny"),
                "actual_cash_in_cny": received if owned_cash else None, "unmatched_cash_cny": unmatched if owned_cash else None,
                "uncollected_expected_cny": values["outstanding_cash"], "sold_cost_cny": values["sold_cost"] if sales else None,
                "execution_cost_cny": values["execution_fees_paid"], "unpaid_execution_cost_cny": values["unpaid_planned_execution_cost"],
                "purchase_cash_paid_cny": values["purchase_cash_paid"], "credit_applied_cny": values["credit_applied"],
                "cash_event_ids": sorted(cash_ids), "allocation_ids": [a["allocation_id"] for a in allocations],
                "event_refs": [r["event_id"] for r in state["receipts"] if r.get("task_id") == task["id"]] + [s["sale_id"] for s in sales],
                "execution_status": raw_status(task), "accounting_note": task["accounting_status"],
                "missing_fields": [] if owned_cash else ["actual_cash_in_cny"], "is_demo": True, "external_write": False}

    def get_accounting(self, request):
        with self.database.transaction() as tx:
            result = self._accounting(tx, request["context"])
            if request.get("task_id") or request.get("proposal_id"):
                tasks = [t for t in result["tasks"] if (not request.get("task_id") or t["task_id"] == request["task_id"])
                         and (not request.get("proposal_id") or t["proposal_id"] == request["proposal_id"])]
                if not tasks:
                    raise ValueError("Unknown task or proposal in this context")
                result["tasks"] = tasks
                if request.get("task_id"):
                    case = next(c for c in result["case_results"] if c["task_id"] == request["task_id"])
                    return {"contract_version": CONTRACT_VERSION, "context": request["context"], **case}
                result["case_results"] = [c for c in result["case_results"] if c["proposal_id"] == request["proposal_id"]]
            return {"contract_version": CONTRACT_VERSION, "context": request["context"], **result}

    def advance_replay(self, request):
        from .replay import advance
        return self._command(request, "advance_replay", lambda tx, facts: advance(self, tx, facts, request))

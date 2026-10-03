"""Shared public types and dependency-injection seams for hackathon modules.

This module intentionally imports no feature module. Modules 1--4 can depend
on these protocols without importing each other or creating a second store.
The HTTP integration router installs all feature services against the
application's existing Store.
"""

from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Connection
from typing import Any, ContextManager, Literal, NotRequired, Optional, Protocol, TypedDict


CONTRACT_VERSION = "hackathon.v1"
CONTRACT_STATUS = "integration_wired"
DEFAULT_DECISION_AT = "2026-10-03T09:30:00+08:00"
DEFAULT_DATA_VERSION = "retail-v2.1"


class SourceRef(TypedDict):
    source: str
    record_id: str
    known_at: str
    is_demo: bool


class FactContext(TypedDict):
    tenant_id: str
    scenario_id: str
    branch_id: Optional[str]
    snapshot_id: str
    as_of: str
    data_version: str
    fact_version: int
    is_demo: bool
    source_refs: list[SourceRef]
    missing_fields: list[str]


class FactQuery(TypedDict):
    context: FactContext
    store_ids: list[str]
    sku_ids: list[str]
    lot_ids: list[str]
    include: list[str]
    history_start: Optional[str]
    history_end: Optional[str]


class InventoryFact(TypedDict):
    store_id: str
    sku_id: str
    lot_id: str
    stock_state: Literal["on_hand", "in_transit", "blocked", "reserved"]
    quantity: Optional[float]
    base_unit: str
    unit_cost_cny: Optional[float]
    blocked_qty: Optional[float]
    reserved_qty: Optional[float]
    sellable_until: Optional[str]
    source_ref: SourceRef


class FactQueryResult(TypedDict):
    contract_version: str
    query_id: str
    context: FactContext
    inventory: list[InventoryFact]
    sales_history: list[dict[str, Any]]
    availability_history: list[dict[str, Any]]
    demand_forecasts: list[dict[str, Any]]
    procurement: list[dict[str, Any]]
    routes: list[dict[str, Any]]
    policies: list[dict[str, Any]]
    payables: list[dict[str, Any]]
    reference_data: NotRequired[dict[str, Any]]
    missing_fields: list[str]
    warnings: list[str]


class RiskItem(TypedDict):
    risk_key: str
    risk_id: Optional[int]
    store_id: str
    sku_id: str
    lot_id: str
    risk_type: Literal["slow_moving", "near_expiry"]
    result: Literal["risk", "normal", "insufficient_data"]
    quantity: Optional[float]
    base_unit: str
    amount_cny: Optional[float]
    coverage_days: Optional[float]
    remaining_sellable_days: Optional[int]
    evidence_refs: list[SourceRef]
    missing_fields: list[str]
    rule_version: str


class RiskAssessment(TypedDict):
    contract_version: str
    context: FactContext
    calculation_version: str
    items: list[RiskItem]
    attention_inventory_cost_cny: Optional[float]
    counted_inventory_keys: list[str]
    missing_fields: list[str]


class CandidateAction(TypedDict):
    candidate_id: str
    action_type: Literal["keep", "transfer", "promotion", "return", "procurement"]
    feasible: bool
    exclusion_reasons: list[str]
    store_id: Optional[str]
    target_store_id: Optional[str]
    sku_id: str
    lot_id: Optional[str]
    quantity: Optional[float]
    base_unit: str
    calculation: dict[str, Any]
    assumptions: list[str]
    missing_fields: list[str]
    inventory_changes: list[dict[str, Any]]


class ProposalComparison(TypedDict):
    contract_version: str
    comparison_id: str
    context: FactContext
    calculation_version: str
    policy_version: str
    objective: str
    horizon_start: str
    horizon_end: str
    baseline_id: str
    candidates: list[CandidateAction]
    candidate_groups: list[dict[str, Any]]
    selected_candidate_id: Optional[str]
    fact_notices: list[str]


class ExtractedField(TypedDict):
    value: Any
    unit: Optional[str]
    evidence_text: Optional[str]
    page: Optional[int]
    confidence: Optional[float]
    review_status: Literal["needs_review", "confirmed", "missing", "unmatched"]


class ExtractionDraft(TypedDict):
    contract_version: str
    draft_id: str
    material_id: str
    tenant_id: str
    context: NotRequired[FactContext]
    scenario_id: Optional[str]
    fact_version: int
    kind: Literal["purchase_intent", "return_terms"]
    status: Literal["needs_review", "confirmed", "rejected", "failed"]
    source: str
    is_demo: bool
    external_write: Literal[False]
    fields: dict[str, ExtractedField]
    missing_fields: list[str]
    unmatched_entities: list[dict[str, Any]]
    created_at: str
    model_run_id: Optional[str]


class ModelRunEvent(TypedDict):
    sequence: int
    event_id: str
    event_type: Literal[
        "run_started",
        "tool_started",
        "tool_succeeded",
        "tool_failed",
        "needs_input",
        "run_completed",
        "run_failed",
        "run_unavailable",
    ]
    occurred_at: str
    tool_name: Optional[str]
    input_summary: Optional[dict[str, Any]]
    result_ref: Optional[str]
    error: Optional[dict[str, Any]]


class AgentRun(TypedDict):
    contract_version: str
    run_id: str
    status: Literal["queued", "running", "completed", "failed", "unavailable", "needs_input"]
    context: FactContext
    summary: Optional[str]
    events: list[ModelRunEvent]
    missing_fields: list[str]
    proposal_comparison_id: Optional[str]
    usage: Optional[dict[str, Any]]
    created_at: str
    finished_at: Optional[str]


class BusinessEvent(TypedDict):
    event_id: str
    tenant_id: str
    scenario_id: str
    branch_id: str
    task_id: str
    proposal_id: str
    proposal_version: int
    event_type: str
    occurred_at: str
    known_at: str
    store_id: Optional[str]
    target_store_id: Optional[str]
    sku_id: str
    lot_id: Optional[str]
    quantity: Optional[float]
    base_unit: Optional[str]
    amount_cny: Optional[float]
    business_ref: Optional[str]
    receipt_ref: Optional[str]
    source: str
    is_demo: bool
    external_write: Literal[False]


class ApprovalTaskResult(TypedDict):
    contract_version: str
    approval_id: str
    proposal_id: str
    proposal_version: int
    approved_by: str
    approved_at: str
    status: Literal["approved"]
    task_group_id: str
    tasks: list[dict[str, Any]]
    idempotent_replay: bool


class ReplayResult(TypedDict):
    contract_version: str
    context: FactContext
    advanced_to: str
    applied_event_ids: list[str]
    duplicate_event_ids: list[str]
    held_event_ids: list[str]
    inventory_deltas: list[dict[str, Any]]
    cash_event_ids: list[str]
    accounting: dict[str, Any]


class Transaction(Protocol):
    """The active connection yielded by the shared Store transaction scope."""

    def execute(self, sql: str, parameters: Any = ...) -> Any: ...

    def executemany(self, sql: str, seq_of_parameters: Any) -> Any: ...


class TransactionProvider(Protocol):
    def transaction(self) -> ContextManager[Connection]: ...


class FactService(Protocol):
    def query(self, query: FactQuery) -> FactQueryResult: ...

    def assess_risks(self, query: FactQuery) -> RiskAssessment: ...

    def resolve_legacy_risk_id(self, context: FactContext, risk_key: str) -> Optional[int]: ...

    def apply_business_events(
        self, tx: Transaction, events: list[BusinessEvent], *, expected_fact_version: int
    ) -> dict[str, Any]: ...


class CalculationService(Protocol):
    def compare(self, facts: FactQueryResult, request: dict[str, Any]) -> ProposalComparison: ...


class AgentService(Protocol):
    def run(self, request: dict[str, Any]) -> AgentRun: ...

    def get_run(self, run_id: str, *, tenant_id: str, after_sequence: int = 0) -> AgentRun: ...

    def extract_material(self, request: dict[str, Any]) -> ExtractionDraft: ...

    def confirm_material(
        self, draft_id: str, request: dict[str, Any], *, expected_fact_version: int
    ) -> dict[str, Any]: ...


class ExecutionService(Protocol):
    def save_proposal(self, request: dict[str, Any]) -> dict[str, Any]: ...

    def confirm_and_schedule(self, request: dict[str, Any]) -> ApprovalTaskResult: ...

    def record_channel_action(self, request: dict[str, Any]) -> dict[str, Any]: ...

    def record_business_events(self, request: dict[str, Any]) -> dict[str, Any]: ...

    def advance_replay(self, request: dict[str, Any]) -> ReplayResult: ...

    def get_accounting(self, request: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class HackathonServices:
    """Per-app service registry; optional features can be wired incrementally."""

    database: TransactionProvider
    facts: Optional[FactService] = None
    calculations: Optional[CalculationService] = None
    agent: Optional[AgentService] = None
    execution: Optional[ExecutionService] = None


def install_services(app: Any, services: HackathonServices) -> None:
    """Install the shared service graph at ``app.state.hackathon_services``."""

    app.state.hackathon_services = services


def get_services(app: Any) -> HackathonServices:
    """Return the graph installed by integration, with a useful setup error."""

    services = getattr(app.state, "hackathon_services", None)
    if services is None:
        raise RuntimeError("hackathon services are not registered; integration wiring is pending")
    return services


__all__ = [
    "AgentRun",
    "AgentService",
    "ApprovalTaskResult",
    "BusinessEvent",
    "CONTRACT_STATUS",
    "CONTRACT_VERSION",
    "CalculationService",
    "CandidateAction",
    "DEFAULT_DATA_VERSION",
    "DEFAULT_DECISION_AT",
    "ExecutionService",
    "ExtractionDraft",
    "FactContext",
    "FactQuery",
    "FactQueryResult",
    "FactService",
    "HackathonServices",
    "InventoryFact",
    "ModelRunEvent",
    "ProposalComparison",
    "ReplayResult",
    "RiskAssessment",
    "RiskItem",
    "SourceRef",
    "Transaction",
    "TransactionProvider",
    "get_services",
    "install_services",
]

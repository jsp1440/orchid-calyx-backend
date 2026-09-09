"""Calyx research executor audit — Approved Task Priority 12.

Audits the research executor pipeline: state machine correctness, governance
boundaries, external literature acquisition, executor registry, dry-run path,
and fail-closed blocking behavior.

Status vocabulary:
  READY        — implemented, tested, and integrated
  GAP          — described in acceptance criteria but not yet closed
  BLOCKED      — requires external dependency (NO-API mode, unprovisioned infra)
  OWNER_GATED  — requires explicit owner authorization before proceeding

No live-model spending. No production KG mutation. Read-only static audit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "calyx-research-executor-audit/v1"
AUDIT_DATE = "2026-09-09"


class ExecutorAuditStatus:
    READY = "READY"
    GAP = "GAP"
    BLOCKED = "BLOCKED"
    OWNER_GATED = "OWNER_GATED"


@dataclass(frozen=True)
class ExecutorAuditCriterion:
    """One measurable criterion in the research executor audit."""

    criterion_id: str
    area: str        # state_machine | governance | literature | registry | dry_run | security
    title: str
    status: str      # ExecutorAuditStatus constant
    authoritative_module: str
    evidence: str
    gap_description: str | None
    blocker_reason: str | None
    next_action: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "area": self.area,
            "title": self.title,
            "status": self.status,
            "authoritative_module": self.authoritative_module,
            "evidence": self.evidence,
            "gap_description": self.gap_description,
            "blocker_reason": self.blocker_reason,
            "next_action": self.next_action,
        }


# ---------------------------------------------------------------------------
# Canonical executor audit criteria
# ---------------------------------------------------------------------------

EXECUTOR_AUDIT_CRITERIA: tuple[ExecutorAuditCriterion, ...] = (

    # ------------------------------------------------------------------ STATE MACHINE
    ExecutorAuditCriterion(
        criterion_id="state_machine_valid_transitions",
        area="state_machine",
        title="Research request state machine — valid transitions only",
        status=ExecutorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.research_executor._VALID_TRANSITIONS",
        evidence=(
            "_VALID_TRANSITIONS enforces: queued_waiting_for_executor→{queued, blocked}; "
            "queued→{running, blocked}; running→{completed, blocked}; "
            "completed/blocked→{} (terminal); invalid transitions raise ValueError"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ExecutorAuditCriterion(
        criterion_id="state_machine_terminal_states",
        area="state_machine",
        title="Terminal states (completed, blocked) cannot be re-transitioned",
        status=ExecutorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.research_executor._TERMINAL_STATES",
        evidence=(
            "_TERMINAL_STATES = frozenset({'completed', 'blocked'}); "
            "transition to terminal state empties outbound edges; "
            "GovervedResearchExecutor enforces terminal guard"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ExecutorAuditCriterion(
        criterion_id="state_machine_idempotent_requests",
        area="state_machine",
        title="Exactly-once / idempotent request execution (same request_id → same result)",
        status=ExecutorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.research_executor.ResearchRequestStore.upsert",
        evidence=(
            "upsert() returns (existing_record, False) for duplicate request_id; "
            "project_id and artifact digest are deterministic from request_id; "
            "replay is detected and skipped"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ExecutorAuditCriterion(
        criterion_id="state_machine_fail_closed_blocking",
        area="state_machine",
        title="Fail-closed blocking on unrecoverable retrieval failure",
        status=ExecutorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.research_executor.GovervedResearchExecutor",
        evidence=(
            "Any unrecoverable retrieval failure transitions to 'blocked' with machine-readable "
            "blocker_code; never fabricates evidence when retrieval is unavailable; "
            "ResearchExecutorResult.blocker_code exposed in to_dict()"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ GOVERNANCE
    ExecutorAuditCriterion(
        criterion_id="governance_authority_constants",
        area="governance",
        title="Governance authority constants — all production actions permanently False",
        status=ExecutorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.research_executor._AUTHORITY",
        evidence=(
            "_AUTHORITY: knowledge_graph_mutation_authorized=False, "
            "taxonomy_activation_authorized=False, scientific_publication_authorized=False, "
            "production_deployment_authorized=False, evidence_promotion_authorized=False; "
            "copied into every ResearchExecutorResult.authority"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ExecutorAuditCriterion(
        criterion_id="governance_review_required",
        area="governance",
        title="review_required=True enforced on all executor results",
        status=ExecutorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.research_executor.ResearchExecutorResult",
        evidence=(
            "ResearchExecutorResult defaults review_required=True; "
            "external_literature_summary.review_required=True; "
            "automatic_publication=False; knowledge_graph_mutation=False in every to_dict()"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ExecutorAuditCriterion(
        criterion_id="governance_schema_version",
        area="governance",
        title="Executor result schema version (calyx-research-executor/v1)",
        status=ExecutorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.research_executor.SCHEMA_VERSION",
        evidence=(
            "SCHEMA_VERSION='calyx-research-executor/v1'; "
            "included in ResearchExecutorResult.to_dict() under 'schema_version'; "
            "stable contract for downstream consumers"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ LITERATURE
    ExecutorAuditCriterion(
        criterion_id="literature_europe_pmc_integration",
        area="literature",
        title="Europe PMC external literature search integration",
        status=ExecutorAuditStatus.READY,
        authoritative_module="app.calyx_conversation.external_literature.search_europe_pmc",
        evidence=(
            "GovervedResearchExecutor imports search_europe_pmc from external_literature; "
            "results stored in ResearchExecutorResult.external_literature; "
            "result_count and status exposed in to_dict() external_literature_summary"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ExecutorAuditCriterion(
        criterion_id="literature_live_network_blocked",
        area="literature",
        title="Live network calls to Europe PMC / external APIs",
        status=ExecutorAuditStatus.BLOCKED,
        authoritative_module="app.calyx_conversation.external_literature.search_europe_pmc",
        evidence=(
            "search_europe_pmc() issues HTTP requests to api.europepmc.org; "
            "live calls return BLOCKED state when network unavailable; "
            "GovervedResearchExecutor transitions to blocked with appropriate blocker_code"
        ),
        gap_description=None,
        blocker_reason=(
            "NO-API mode: live outbound HTTP to Europe PMC and other literature APIs "
            "may be restricted in this execution environment"
        ),
        next_action="Verify network policy allows api.europepmc.org when NO-API constraint lifts",
    ),
    ExecutorAuditCriterion(
        criterion_id="literature_no_automatic_promotion",
        area="literature",
        title="External literature never automatically promoted to KG",
        status=ExecutorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.research_executor.ResearchExecutorResult",
        evidence=(
            "external_literature_summary.automatic_publication=False; "
            "external_literature_summary.knowledge_graph_mutation=False; "
            "_AUTHORITY.evidence_promotion_authorized=False; "
            "all literature results require human review before any use"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ REGISTRY
    ExecutorAuditCriterion(
        criterion_id="registry_authoritative_executor",
        area="registry",
        title="AuthoritativeExecutorRegistry — registered executor dispatch",
        status=ExecutorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.executor_registry.AuthoritativeExecutorRegistry",
        evidence=(
            "AuthoritativeExecutorRegistry holds RegisteredExecutor entries; "
            "executor dispatch resolves by executor_key; "
            "AutonomyProbeExecutor available for capability probing"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ExecutorAuditCriterion(
        criterion_id="registry_governed_assignment",
        area="registry",
        title="GovernedAssignment — input checksum verification before execution",
        status=ExecutorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.executor.GovernedAssignment",
        evidence=(
            "GovernedAssignment.verified_input_checksum() computes SHA-256 of inputs; "
            "raises ASSIGNMENT_INPUT_CHECKSUM_MISMATCH if stored checksum disagrees; "
            "frozen dataclass prevents mutation after construction"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ExecutorAuditCriterion(
        criterion_id="registry_execution_receipt",
        area="registry",
        title="ExecutionReceipt — output checksum and state-outcome consistency",
        status=ExecutorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.executor.ExecutionReceipt",
        evidence=(
            "ExecutionReceipt.verify() checks output_checksum, state-outcome pairing; "
            "RECEIPT_OUTPUT_CHECKSUM_MISMATCH and RECEIPT_STATE_OUTCOME_MISMATCH are hard errors; "
            "frozen dataclass; ExecutionState ∈ {delivered, blocked, cancelled, timed_out}"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ DRY RUN
    ExecutorAuditCriterion(
        criterion_id="dry_run_deterministic_executor",
        area="dry_run",
        title="DeterministicDryRunExecutor — no shell/network/production actions",
        status=ExecutorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.executor.DeterministicDryRunExecutor",
        evidence=(
            "DeterministicDryRunExecutor: executor_key='deterministic_dry_run_v1'; "
            "PROHIBITED_CAPABILITIES frozenset includes shell, network, merge, deploy, "
            "publish, credential_access, production_graph_mutation; "
            "supported_capabilities only: validate_input, produce_receipt, collect_evidence_uris"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ExecutorAuditCriterion(
        criterion_id="dry_run_prohibited_capabilities",
        area="dry_run",
        title="PROHIBITED_CAPABILITIES enforced — no executor can claim forbidden capabilities",
        status=ExecutorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.executor.PROHIBITED_CAPABILITIES",
        evidence=(
            "PROHIBITED_CAPABILITIES frozenset: {shell, network, merge, deploy, publish, "
            "credential_access, production_graph_mutation}; "
            "AuthoritativeExecutorRegistry validates against this set at registration"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ SECURITY
    ExecutorAuditCriterion(
        criterion_id="security_no_kg_mutation",
        area="security",
        title="No Knowledge Graph mutation path in research executor",
        status=ExecutorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.research_executor._AUTHORITY",
        evidence=(
            "_AUTHORITY.knowledge_graph_mutation_authorized=False; "
            "PROHIBITED_CAPABILITIES includes production_graph_mutation; "
            "ResearchExecutorResult.to_dict() sets knowledge_graph_mutation=False in summary"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ExecutorAuditCriterion(
        criterion_id="security_no_taxonomy_activation",
        area="security",
        title="No taxonomy activation or scientific publication in executor path",
        status=ExecutorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.research_executor._AUTHORITY",
        evidence=(
            "_AUTHORITY.taxonomy_activation_authorized=False; "
            "_AUTHORITY.scientific_publication_authorized=False; "
            "GovervedResearchExecutor docstring: 'never activates or mutates taxonomy, "
            "never publishes scientific conclusions'"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ExecutorAuditCriterion(
        criterion_id="security_production_promotion_owner_gated",
        area="security",
        title="Evidence promotion and production deployment require owner authorization",
        status=ExecutorAuditStatus.OWNER_GATED,
        authoritative_module="app.calyx_orchestrator.research_executor._AUTHORITY",
        evidence=(
            "_AUTHORITY.evidence_promotion_authorized=False; "
            "_AUTHORITY.production_deployment_authorized=False by default; "
            "no executor path changes these values without explicit owner authorization"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action="Owner must explicitly authorize evidence promotion and production deployment",
    ),
)


# ---------------------------------------------------------------------------
# Audit builders
# ---------------------------------------------------------------------------

@dataclass
class CalyxResearchExecutorAudit:
    """Machine-readable Calyx research executor audit result."""

    schema_version: str = SCHEMA_VERSION
    audit_date: str = AUDIT_DATE
    no_auto_publication: bool = True
    no_production_mutation: bool = True
    criteria: list[ExecutorAuditCriterion] = field(default_factory=list)

    def by_status(self, status: str) -> list[ExecutorAuditCriterion]:
        return [c for c in self.criteria if c.status == status]

    def by_area(self, area: str) -> list[ExecutorAuditCriterion]:
        return [c for c in self.criteria if c.area == area]

    def ready_count(self) -> int:
        return len(self.by_status(ExecutorAuditStatus.READY))

    def gap_count(self) -> int:
        return len(self.by_status(ExecutorAuditStatus.GAP))

    def blocked_count(self) -> int:
        return len(self.by_status(ExecutorAuditStatus.BLOCKED))

    def owner_gated_count(self) -> int:
        return len(self.by_status(ExecutorAuditStatus.OWNER_GATED))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "audit_date": self.audit_date,
            "no_auto_publication": self.no_auto_publication,
            "no_production_mutation": self.no_production_mutation,
            "summary": {
                "total": len(self.criteria),
                "ready": self.ready_count(),
                "gap": self.gap_count(),
                "blocked": self.blocked_count(),
                "owner_gated": self.owner_gated_count(),
            },
            "criteria": [c.to_dict() for c in self.criteria],
        }

    def serialize_as_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2)


def get_calyx_research_executor_audit() -> CalyxResearchExecutorAudit:
    """Return the current research executor audit. Pure function — no external calls."""
    return CalyxResearchExecutorAudit(criteria=list(EXECUTOR_AUDIT_CRITERIA))


def get_criteria_by_status(status: str) -> list[ExecutorAuditCriterion]:
    return [c for c in EXECUTOR_AUDIT_CRITERIA if c.status == status]


def get_criteria_by_area(area: str) -> list[ExecutorAuditCriterion]:
    return [c for c in EXECUTOR_AUDIT_CRITERIA if c.area == area]


def get_gaps() -> list[ExecutorAuditCriterion]:
    return get_criteria_by_status(ExecutorAuditStatus.GAP)


def get_next_actions() -> list[dict[str, str]]:
    return [
        {
            "criterion_id": c.criterion_id,
            "area": c.area,
            "title": c.title,
            "status": c.status,
            "next_action": c.next_action,
        }
        for c in EXECUTOR_AUDIT_CRITERIA
        if c.next_action
    ]

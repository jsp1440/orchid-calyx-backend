"""Calyx runtime truth audit — Approved Task Priority 11.

Verifies canonical runtime state: registered routes, persistence mode,
provider configuration, degraded-mode truthfulness, orchestrator readiness,
and NO-API mode compliance.

Status vocabulary:
  READY        — implemented, tested, and integrated; runtime behavior is truthful
  GAP          — accepted criterion not yet met or not yet verifiable
  BLOCKED      — requires external dependency (NO-API mode, unprovisioned infra)
  OWNER_GATED  — requires explicit owner authorization before proceeding

No live-model spending. No production KG mutation. Read-only static audit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "calyx-runtime-truth-audit/v1"
AUDIT_DATE = "2026-09-09"


class RuntimeTruthStatus:
    READY = "READY"
    GAP = "GAP"
    BLOCKED = "BLOCKED"
    OWNER_GATED = "OWNER_GATED"


@dataclass(frozen=True)
class RuntimeTruthCriterion:
    """One measurable criterion in the Calyx runtime truth audit."""

    criterion_id: str
    area: str        # routes | provider | persistence | degraded | orchestrator | security
    title: str
    status: str      # RuntimeTruthStatus constant
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
# Canonical runtime truth criteria
# ---------------------------------------------------------------------------

RUNTIME_TRUTH_CRITERIA: tuple[RuntimeTruthCriterion, ...] = (

    # ------------------------------------------------------------------ ROUTES
    RuntimeTruthCriterion(
        criterion_id="routes_calyx_conversation",
        area="routes",
        title="Calyx Conversation API routes registered (/api/calyx/*)",
        status=RuntimeTruthStatus.READY,
        authoritative_module="app.calyx_conversation.routes",
        evidence=(
            "FastAPI router at /api/calyx: /query, /analyze, /dataset/analyze, "
            "/knowledge-graph, /brain-query, /conversations, /report, "
            "/synthesis/{taxon_id}; capabilities() endpoint lists all 8 routes"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RuntimeTruthCriterion(
        criterion_id="routes_synthesis_endpoint",
        area="routes",
        title="TeachingSynthesisV1 HTTP endpoint registered (GET /calyx/synthesis/{taxon_id})",
        status=RuntimeTruthStatus.READY,
        authoritative_module="app.calyx_conversation.routes.teaching_synthesis",
        evidence=(
            "GET /calyx/synthesis/{taxon_id} wired; query params: taxon_name (required), "
            "audience, depth, taxon_rank, canonical_source; returns synthesis.to_dict(); "
            "listed in capabilities() endpoint array; 15 tests passing"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RuntimeTruthCriterion(
        criterion_id="routes_owner_narrative",
        area="routes",
        title="Owner narrative route (/calyx-narrative) wired with synthesis metadata",
        status=RuntimeTruthStatus.READY,
        authoritative_module="app.routers.owner_operations.owner_calyx_narrative",
        evidence=(
            "GET /calyx-narrative returns scientific_synthesis block: contract_version, "
            "schema_version, endpoint template, graph_mutation=False, "
            "sensitive_locality_withheld=True"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RuntimeTruthCriterion(
        criterion_id="routes_capabilities_truthful",
        area="routes",
        title="capabilities() endpoint truthfully reflects registered routes",
        status=RuntimeTruthStatus.READY,
        authoritative_module="app.calyx_conversation.routes.capabilities",
        evidence=(
            "capabilities() returns status='operational', interface='Calyx Conversational "
            "Analysis Phase 2', retrieval modes [LEXICAL, SEMANTIC, HYBRID], "
            "publication_boundary='read/analyze only; no automatic scientific publication "
            "or graph mutation'"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ PROVIDER
    RuntimeTruthCriterion(
        criterion_id="provider_configuration_disclosure",
        area="provider",
        title="runtime_provider_configuration() discloses truthful provider state",
        status=RuntimeTruthStatus.READY,
        authoritative_module="app.calyx_conversation.provider_runtime.runtime_provider_configuration",
        evidence=(
            "Returns selected provider, generative_ready flag, missing_configuration list, "
            "secrets_exposed=False always; never exposes key values; "
            "falls back to 'deterministic-governed' when no API key present"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RuntimeTruthCriterion(
        criterion_id="provider_no_api_mode_truthful",
        area="provider",
        title="NO-API mode correctly surfaces generative_ready=False in runtime config",
        status=RuntimeTruthStatus.READY,
        authoritative_module="app.calyx_conversation.provider_runtime.runtime_provider_configuration",
        evidence=(
            "When OPENAI_API_KEY and CALYX_CHAT_COMPLETIONS_URL are absent, "
            "selected='deterministic-governed', generative_ready=False; "
            "missing_configuration list populated; never falsely claims readiness"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RuntimeTruthCriterion(
        criterion_id="provider_secret_non_exposure",
        area="provider",
        title="Provider configuration never exposes credential values",
        status=RuntimeTruthStatus.READY,
        authoritative_module="app.calyx_conversation.provider_runtime.runtime_provider_configuration",
        evidence=(
            "runtime_provider_configuration() returns boolean presence flags only: "
            "openai_key_present, chat_url_present, chat_model_present; "
            "secrets_exposed=False asserted in return value; "
            "_provider_http_error() strips key from error messages"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RuntimeTruthCriterion(
        criterion_id="provider_live_generative",
        area="provider",
        title="Live generative provider (OpenAI / chat-completions endpoint)",
        status=RuntimeTruthStatus.BLOCKED,
        authoritative_module="app.calyx_conversation.provider_runtime.OpenAIRuntimeResponsesProvider",
        evidence=(
            "OpenAIRuntimeResponsesProvider raises RuntimeError('...NOT_CONFIGURED') "
            "when key absent; deterministic-governed path is available without key"
        ),
        gap_description=None,
        blocker_reason=(
            "NO-API mode: live generative provider requires OPENAI_API_KEY or "
            "CALYX_CHAT_COMPLETIONS_URL which are not provisioned in this execution environment"
        ),
        next_action="Activate live provider when NO-API constraint lifts and owner authorizes spend",
    ),

    # ------------------------------------------------------------------ PERSISTENCE
    RuntimeTruthCriterion(
        criterion_id="persistence_dual_mode",
        area="persistence",
        title="ConversationStore dual-mode persistence (postgres | memory fallback)",
        status=RuntimeTruthStatus.READY,
        authoritative_module="app.calyx_conversation.store.ConversationStore",
        evidence=(
            "ConversationStore.persistence_mode property returns 'postgres' if DATABASE_URL "
            "is set, else 'memory'; capabilities() endpoint reflects actual mode; "
            "LEGACY_OWNER sentinel preserves pre-auth API compatibility"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RuntimeTruthCriterion(
        criterion_id="persistence_postgres_ready",
        area="persistence",
        title="Postgres persistence path (DATABASE_URL provisioning)",
        status=RuntimeTruthStatus.BLOCKED,
        authoritative_module="app.calyx_conversation.store.ConversationStore.ensure_schema",
        evidence=(
            "ensure_schema() creates conversations and messages tables when DATABASE_URL set; "
            "memory fallback activates automatically when DATABASE_URL absent; "
            "RLock protects in-memory state"
        ),
        gap_description=None,
        blocker_reason=(
            "DATABASE_URL is not provisioned in this execution environment; "
            "persistence operates in memory-only mode"
        ),
        next_action="Provision DATABASE_URL in deployment environment to enable durable persistence",
    ),
    RuntimeTruthCriterion(
        criterion_id="persistence_owner_scoped",
        area="persistence",
        title="Owner-scoped conversation isolation (per-owner conversation access)",
        status=RuntimeTruthStatus.READY,
        authoritative_module="app.calyx_conversation.store.ConversationStore",
        evidence=(
            "All conversation reads enforce owner_id filter; "
            "LEGACY_OWNER path preserved for pre-auth notebook/dataset workflows; "
            "per-owner conversation list and message access"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ DEGRADED MODE
    RuntimeTruthCriterion(
        criterion_id="degraded_deterministic_fallback",
        area="degraded",
        title="Deterministic governed fallback when no generative provider is available",
        status=RuntimeTruthStatus.READY,
        authoritative_module="app.calyx_conversation.provider_runtime.configured_runtime_provider",
        evidence=(
            "configured_runtime_provider() selects 'deterministic-governed' path when no "
            "OpenAI key and no chat-completions URL; routes return structured evidence "
            "packets rather than generating replies; never hallucinates 'available'"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RuntimeTruthCriterion(
        criterion_id="degraded_synthesis_unavailable",
        area="degraded",
        title="Synthesis domains return UNAVAILABLE (not fabricated) when provider absent",
        status=RuntimeTruthStatus.READY,
        authoritative_module="app.calyx_conversation.teaching_synthesis.build_teaching_synthesis",
        evidence=(
            "All 8 domain slots accept None; None → UNKNOWN_DOMAIN_DATA sentinel; "
            "evidence_state='unavailable' for every domain when no provider connected; "
            "knowledge_gaps lists all 8 domains; 15 endpoint tests validate this"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RuntimeTruthCriterion(
        criterion_id="degraded_interaction_gateway",
        area="degraded",
        title="InteractionGateway returns UNKNOWN sentinel in degraded mode",
        status=RuntimeTruthStatus.READY,
        authoritative_module="app.scientific_adapter_lab.interaction_laboratory.InteractionGateway",
        evidence=(
            "InteractionGateway(available=False) raises NotImplementedError for live calls; "
            "normalize_interaction() returns UNKNOWN_INTERACTION sentinel when source is None; "
            "stage_interaction_for_review() raises ValueError for invalid source; "
            "72 tests cover UNKNOWN/UNKNOWN_SOURCE paths"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ ORCHESTRATOR
    RuntimeTruthCriterion(
        criterion_id="orchestrator_factory_gate",
        area="orchestrator",
        title="Software Factory gate (evaluate_factory_gate) — deterministic routing",
        status=RuntimeTruthStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy.evaluate_factory_gate",
        evidence=(
            "evaluate_factory_gate() pure function; FactoryAction ∈ "
            "{AUTO_INTEGRATE, REQUIRE_CHECKER, PREPARE_REPAIR, PARK_PROVIDER_REQUIRED, "
            "PARK_INFRASTRUCTURE, OWNER_GATE, WAIT}; no_api_mode=True by default"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RuntimeTruthCriterion(
        criterion_id="orchestrator_bridge_decision",
        area="orchestrator",
        title="Queue Bridge / Factory Bridge compound routing decision",
        status=RuntimeTruthStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_bridge.route_completion_to_factory",
        evidence=(
            "route_completion_to_factory() composes reconcile_completion_event with "
            "evaluate_factory_gate; FactoryBridgeAction.PARK_PROVIDER_REQUIRED for NO-API; "
            "integration_authorized=False unless factory returns AUTO_INTEGRATE"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RuntimeTruthCriterion(
        criterion_id="orchestrator_approved_tasks",
        area="orchestrator",
        title="Approved tasks reservoir (APPROVED_TASKS) — read-only priority queue",
        status=RuntimeTruthStatus.READY,
        authoritative_module="app.calyx_orchestrator.approved_tasks",
        evidence=(
            "APPROVED_TASKS list with priority-sorted approved read-only audit tasks; "
            "P1=finish-line audit (DELIVERED), P10=taxonomy readiness (IN PROGRESS), "
            "P11+=queued; no autonomous execution of owner-gated tasks"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ SECURITY
    RuntimeTruthCriterion(
        criterion_id="security_agent_gateway_runtime",
        area="security",
        title="Agent Security Gateway enforced at runtime (no-bypass invariant)",
        status=RuntimeTruthStatus.READY,
        authoritative_module="app.calyx_orchestrator.agent_security_gateway.AgentSecurityGateway",
        evidence=(
            "AgentSecurityGateway.evaluate() hard-stops on policy violations; "
            "cannot be bypassed, disabled, or made permissive; "
            "KG candidate contracts: review_required=True, graph_mutation=False"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RuntimeTruthCriterion(
        criterion_id="security_no_autonomous_production",
        area="security",
        title="Autonomous production activation permanently blocked at runtime",
        status=RuntimeTruthStatus.OWNER_GATED,
        authoritative_module="app.calyx_orchestrator.factory_policy.evaluate_factory_gate",
        evidence=(
            "AUTO_INTEGRATE only valid for non-main integration branches; "
            "no factory path reaches main or production KG without owner authorization; "
            "taxonomy_publication_authorized=False in ReadinessDecision default"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action="Owner must explicitly authorize any production activation path",
    ),
)


# ---------------------------------------------------------------------------
# Audit builders
# ---------------------------------------------------------------------------

@dataclass
class CalyxRuntimeTruthAudit:
    """Machine-readable Calyx runtime truth audit result."""

    schema_version: str = SCHEMA_VERSION
    audit_date: str = AUDIT_DATE
    no_auto_publication: bool = True
    no_production_mutation: bool = True
    criteria: list[RuntimeTruthCriterion] = field(default_factory=list)

    def by_status(self, status: str) -> list[RuntimeTruthCriterion]:
        return [c for c in self.criteria if c.status == status]

    def by_area(self, area: str) -> list[RuntimeTruthCriterion]:
        return [c for c in self.criteria if c.area == area]

    def ready_count(self) -> int:
        return len(self.by_status(RuntimeTruthStatus.READY))

    def gap_count(self) -> int:
        return len(self.by_status(RuntimeTruthStatus.GAP))

    def blocked_count(self) -> int:
        return len(self.by_status(RuntimeTruthStatus.BLOCKED))

    def owner_gated_count(self) -> int:
        return len(self.by_status(RuntimeTruthStatus.OWNER_GATED))

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


def get_calyx_runtime_truth_audit() -> CalyxRuntimeTruthAudit:
    """Return the current Calyx runtime truth audit. Pure function — no external calls."""
    return CalyxRuntimeTruthAudit(criteria=list(RUNTIME_TRUTH_CRITERIA))


def get_criteria_by_status(status: str) -> list[RuntimeTruthCriterion]:
    """Filter criteria by status."""
    return [c for c in RUNTIME_TRUTH_CRITERIA if c.status == status]


def get_criteria_by_area(area: str) -> list[RuntimeTruthCriterion]:
    """Filter criteria by area."""
    return [c for c in RUNTIME_TRUTH_CRITERIA if c.area == area]


def get_gaps() -> list[RuntimeTruthCriterion]:
    """Return criteria with GAP status."""
    return get_criteria_by_status(RuntimeTruthStatus.GAP)


def get_next_actions() -> list[dict[str, str]]:
    """Return actionable next steps — criteria with a defined next_action."""
    return [
        {
            "criterion_id": c.criterion_id,
            "area": c.area,
            "title": c.title,
            "status": c.status,
            "next_action": c.next_action,
        }
        for c in RUNTIME_TRUTH_CRITERIA
        if c.next_action
    ]

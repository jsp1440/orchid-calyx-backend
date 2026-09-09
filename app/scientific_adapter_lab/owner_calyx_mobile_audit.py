"""Owner Calyx mobile experience audit — Approved Task Priority 15.

Inspects the phone/iPad conversation shell: persistent sessions, streaming,
citations, uncertainty, live status, and degraded states.

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

SCHEMA_VERSION = "owner-calyx-mobile-audit/v1"
AUDIT_DATE = "2026-09-09"


class MobileAuditStatus:
    READY = "READY"
    GAP = "GAP"
    BLOCKED = "BLOCKED"
    OWNER_GATED = "OWNER_GATED"


@dataclass(frozen=True)
class MobileAuditCriterion:
    """One measurable criterion in the owner Calyx mobile experience audit."""

    criterion_id: str
    area: str        # shell | sessions | streaming | citations | uncertainty | live_status | degraded
    title: str
    status: str      # MobileAuditStatus constant
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
# Canonical mobile experience criteria
# ---------------------------------------------------------------------------

MOBILE_AUDIT_CRITERIA: tuple[MobileAuditCriterion, ...] = (

    # ------------------------------------------------------------------ SHELL
    MobileAuditCriterion(
        criterion_id="shell_speak_router",
        area="shell",
        title="Calyx Speak router — phone/iPad conversation API surface (/calyx/speak/*)",
        status=MobileAuditStatus.READY,
        authoritative_module="app.calyx_conversation.speak_routes",
        evidence=(
            "FastAPI router at /calyx/speak: POST /conversations, GET /conversations, "
            "GET /conversations/{id}, POST /conversations/{id}/turns, GET /status; "
            "CALYX-SPEAK-012-DEEP-RESEARCH-DELIVERABLES release"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    MobileAuditCriterion(
        criterion_id="shell_authentication_guard",
        area="shell",
        title="Owner authentication guard — verify_owner_or_api_key on all Speak routes",
        status=MobileAuditStatus.READY,
        authoritative_module="app.calyx_conversation.speak_routes.AuthDependency",
        evidence=(
            "AuthDependency = Depends(verify_owner_or_api_key) on all Speak endpoints; "
            "_subject() raises HTTP 401 on missing authenticated subject; "
            "per-owner isolation in STORE.recent() and STORE.get()"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    MobileAuditCriterion(
        criterion_id="shell_synthesis_endpoint",
        area="shell",
        title="Synthesis endpoint accessible from mobile shell (/calyx/synthesis/{taxon_id})",
        status=MobileAuditStatus.READY,
        authoritative_module="app.calyx_conversation.routes.teaching_synthesis",
        evidence=(
            "GET /calyx/synthesis/{taxon_id} registered; listed in capabilities(); "
            "returns TeachingSynthesisV1.to_dict() with sensitive_locality_withheld=True; "
            "no authentication required for synthesis (owner-narrative has auth)"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ SESSIONS
    MobileAuditCriterion(
        criterion_id="sessions_persistent_store",
        area="sessions",
        title="Persistent conversation sessions — ConversationStore (postgres | memory)",
        status=MobileAuditStatus.READY,
        authoritative_module="app.calyx_conversation.store.ConversationStore",
        evidence=(
            "STORE = ConversationStore(); persistence_mode in status response; "
            "create_or_touch() idempotent session creation; "
            "STORE.recent() returns per-owner recent conversations"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    MobileAuditCriterion(
        criterion_id="sessions_postgres_durable",
        area="sessions",
        title="Durable Postgres session persistence (DATABASE_URL)",
        status=MobileAuditStatus.BLOCKED,
        authoritative_module="app.calyx_conversation.store.ConversationStore",
        evidence=(
            "ConversationStore.dsn uses DATABASE_URL env; "
            "ensure_schema() creates conversations + messages tables; "
            "without DATABASE_URL falls back to in-memory (not durable across restarts)"
        ),
        gap_description=None,
        blocker_reason=(
            "DATABASE_URL not provisioned in this execution environment; "
            "sessions survive only in-process (memory mode)"
        ),
        next_action="Provision DATABASE_URL in deployment environment for durable session persistence",
    ),
    MobileAuditCriterion(
        criterion_id="sessions_context_preservation",
        area="sessions",
        title="Conversation context preserved across turns (interaction_context, project_id)",
        status=MobileAuditStatus.READY,
        authoritative_module="app.calyx_conversation.speak_routes.append_turn",
        evidence=(
            "append_turn() loads interaction_context from prior conversation state; "
            "project_id scoping in STORE; "
            "sanitize_interaction_context() cleans incoming context before storage"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ STREAMING
    MobileAuditCriterion(
        criterion_id="streaming_governed_turn",
        area="streaming",
        title="Governed turn execution — _run_governed_turn() full response path",
        status=MobileAuditStatus.READY,
        authoritative_module="app.calyx_conversation.speak_routes._run_governed_turn",
        evidence=(
            "_run_governed_turn() assembles evidence, builds synthesis packet, "
            "calls provider, returns structured JSON turn; "
            "MAX_USER_TURN_CHARS=100000; deep-research path uses retrieval_limit=20"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    MobileAuditCriterion(
        criterion_id="streaming_live_sse",
        area="streaming",
        title="Live SSE streaming response to phone/iPad",
        status=MobileAuditStatus.BLOCKED,
        authoritative_module="app.calyx_conversation.speak_routes",
        evidence=(
            "append_turn() returns synchronous JSON response; "
            "no Server-Sent Events or streaming response type in current implementation; "
            "mobile client receives full response in one HTTP response"
        ),
        gap_description=None,
        blocker_reason=(
            "NO-API mode: live streaming requires generative provider which is not "
            "provisioned in this execution environment; SSE infrastructure not yet implemented"
        ),
        next_action="Implement SSE streaming path when generative provider is activated",
    ),
    MobileAuditCriterion(
        criterion_id="streaming_deep_research_mode",
        area="streaming",
        title="Deep research mode — automatic detection and DEEP_RESEARCH_RETRIEVAL_LIMIT",
        status=MobileAuditStatus.READY,
        authoritative_module="app.calyx_conversation.speak_routes._deep_research_requested",
        evidence=(
            "_deep_research_requested() keyword detection on user message; "
            "_effective_retrieval_limit() raises limit to DEEP_RESEARCH_RETRIEVAL_LIMIT=20; "
            "research_mode param: auto | always | never"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ CITATIONS
    MobileAuditCriterion(
        criterion_id="citations_external_trail",
        area="citations",
        title="External citation trail — _external_citations() in mobile turn response",
        status=MobileAuditStatus.READY,
        authoritative_module="app.calyx_conversation.speak_routes._external_citations",
        evidence=(
            "_external_citations() extracts doi/pmid/pmcid/authors/title/journal "
            "from retrieval external_literature results; "
            "citations list included in turn response for mobile display"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    MobileAuditCriterion(
        criterion_id="citations_reference_trail",
        area="citations",
        title="Reference trail — _reference_trail() builds conversation citation context",
        status=MobileAuditStatus.READY,
        authoritative_module="app.calyx_conversation.speak_routes._reference_trail",
        evidence=(
            "_reference_trail() builds citation context from prior conversation messages; "
            "passed into evidence synthesis as reference context; "
            "no fabricated citations — only surface what was in retrieval results"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ UNCERTAINTY
    MobileAuditCriterion(
        criterion_id="uncertainty_casual_mode",
        area="uncertainty",
        title="Casual vs research message detection — _is_casual() avoids over-synthesis",
        status=MobileAuditStatus.READY,
        authoritative_module="app.calyx_conversation.speak_routes._is_casual",
        evidence=(
            "_is_casual() detects casual/greeting messages and skips full evidence retrieval; "
            "DeterministicGovernedReplyProvider fallback for casual mode; "
            "uncertainty is not surfaced for casual messages that don't need synthesis"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    MobileAuditCriterion(
        criterion_id="uncertainty_teaching_synthesis_gaps",
        area="uncertainty",
        title="Knowledge gaps surfaced in synthesis — unavailable domain disclosure",
        status=MobileAuditStatus.READY,
        authoritative_module="app.calyx_conversation.teaching_synthesis.build_teaching_synthesis",
        evidence=(
            "knowledge_gaps list in TeachingSynthesisV1.to_dict() names unavailable domains; "
            "evidence_state='unavailable' for each domain without provider; "
            "mobile UI can render gap list directly"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    MobileAuditCriterion(
        criterion_id="uncertainty_review_required_flagging",
        area="uncertainty",
        title="External literature flagged review_required — mobile display boundary",
        status=MobileAuditStatus.READY,
        authoritative_module="app.calyx_conversation.speak_routes._external_citations",
        evidence=(
            "External citation items carry review_state='REVIEW_REQUIRED'; "
            "status endpoint: automatic_publication=False; "
            "knowledge_graph_mutation=False in turn response"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ LIVE STATUS
    MobileAuditCriterion(
        criterion_id="live_status_endpoint",
        area="live_status",
        title="Live status endpoint — GET /calyx/speak/status (provider, persistence, release)",
        status=MobileAuditStatus.READY,
        authoritative_module="app.calyx_conversation.speak_routes.speak_status",
        evidence=(
            "speak_status() returns: release (CALYX-SPEAK-004-CONTEXT), "
            "integration_release (CALYX-SPEAK-012-DEEP-RESEARCH-DELIVERABLES), "
            "conversation_persistence (postgres|memory), provider block, "
            "continuum_context block, deliverables, automatic_publication=False"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    MobileAuditCriterion(
        criterion_id="live_status_provider_disclosure",
        area="live_status",
        title="Provider status disclosed in live status (generative, configuration, model)",
        status=MobileAuditStatus.READY,
        authoritative_module="app.calyx_conversation.speak_routes.speak_status",
        evidence=(
            "provider block: name, model, generative (bool), configuration (dict); "
            "runtime_provider_configuration() supplies: selected, generative_ready, "
            "missing_configuration, secrets_exposed=False"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    MobileAuditCriterion(
        criterion_id="live_status_deliverables",
        area="live_status",
        title="_deliverable_capabilities() — workspace, diagram, code deliverable status",
        status=MobileAuditStatus.READY,
        authoritative_module="app.calyx_conversation.speak_routes._deliverable_capabilities",
        evidence=(
            "_deliverable_capabilities() returns supported output types for mobile "
            "deliverable tray: workspace, diagram (mermaid), code, tables; "
            "semantic_retrieval_degraded_mode=True disclosed in status"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ DEGRADED
    MobileAuditCriterion(
        criterion_id="degraded_deterministic_governed",
        area="degraded",
        title="Degraded mode — DeterministicGovernedReplyProvider when no generative provider",
        status=MobileAuditStatus.READY,
        authoritative_module="app.calyx_conversation.provider.DeterministicGovernedReplyProvider",
        evidence=(
            "speak_routes imports DeterministicGovernedReplyProvider; "
            "speak_status.provider.generative=False in degraded mode; "
            "casual turn uses deterministic provider; evidence packet still built"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    MobileAuditCriterion(
        criterion_id="degraded_semantic_retrieval",
        area="degraded",
        title="Semantic retrieval degraded mode disclosed in status",
        status=MobileAuditStatus.READY,
        authoritative_module="app.calyx_conversation.speak_routes.speak_status",
        evidence=(
            "semantic_retrieval_degraded_mode=True in speak_status response; "
            "_safe_retrieval() catches exceptions and returns empty result set "
            "rather than crashing; mobile shell can display 'reduced coverage' notice"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    MobileAuditCriterion(
        criterion_id="degraded_safe_retrieval_fallback",
        area="degraded",
        title="_safe_retrieval() / _safe_continuum_context() — fail-closed context degradation",
        status=MobileAuditStatus.READY,
        authoritative_module="app.calyx_conversation.speak_routes._safe_retrieval",
        evidence=(
            "_safe_retrieval() returns empty dict on exception (not crash); "
            "_safe_continuum_context() same pattern; _safe_climate_context() same; "
            "synthesis still produced with UNAVAILABLE states for all unavailable domains"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
)


# ---------------------------------------------------------------------------
# Audit builders
# ---------------------------------------------------------------------------

@dataclass
class OwnerCalyxMobileAudit:
    """Machine-readable owner Calyx mobile experience audit result."""

    schema_version: str = SCHEMA_VERSION
    audit_date: str = AUDIT_DATE
    no_auto_publication: bool = True
    no_production_mutation: bool = True
    criteria: list[MobileAuditCriterion] = field(default_factory=list)

    def by_status(self, status: str) -> list[MobileAuditCriterion]:
        return [c for c in self.criteria if c.status == status]

    def by_area(self, area: str) -> list[MobileAuditCriterion]:
        return [c for c in self.criteria if c.area == area]

    def ready_count(self) -> int:
        return len(self.by_status(MobileAuditStatus.READY))

    def gap_count(self) -> int:
        return len(self.by_status(MobileAuditStatus.GAP))

    def blocked_count(self) -> int:
        return len(self.by_status(MobileAuditStatus.BLOCKED))

    def owner_gated_count(self) -> int:
        return len(self.by_status(MobileAuditStatus.OWNER_GATED))

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


def get_owner_calyx_mobile_audit() -> OwnerCalyxMobileAudit:
    """Return the current mobile experience audit. Pure function — no external calls."""
    return OwnerCalyxMobileAudit(criteria=list(MOBILE_AUDIT_CRITERIA))


def get_criteria_by_status(status: str) -> list[MobileAuditCriterion]:
    return [c for c in MOBILE_AUDIT_CRITERIA if c.status == status]


def get_criteria_by_area(area: str) -> list[MobileAuditCriterion]:
    return [c for c in MOBILE_AUDIT_CRITERIA if c.area == area]


def get_gaps() -> list[MobileAuditCriterion]:
    return get_criteria_by_status(MobileAuditStatus.GAP)


def get_next_actions() -> list[dict[str, str]]:
    return [
        {
            "criterion_id": c.criterion_id,
            "area": c.area,
            "title": c.title,
            "status": c.status,
            "next_action": c.next_action,
        }
        for c in MOBILE_AUDIT_CRITERIA
        if c.next_action
    ]

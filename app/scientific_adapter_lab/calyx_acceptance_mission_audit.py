"""Calyx acceptance mission audit — Approved Task Priority 14.

Verifies that one real read-only orchid mission can reach canonical evidence,
synthesis, citations, uncertainty disclosure, immutable artifact registration,
and replay via the idempotent executor path.

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

SCHEMA_VERSION = "calyx-acceptance-mission-audit/v1"
AUDIT_DATE = "2026-09-09"


class AcceptanceMissionStatus:
    READY = "READY"
    GAP = "GAP"
    BLOCKED = "BLOCKED"
    OWNER_GATED = "OWNER_GATED"


@dataclass(frozen=True)
class AcceptanceMissionCriterion:
    """One measurable criterion in the acceptance mission audit."""

    criterion_id: str
    area: str        # canonical_evidence | synthesis | citations | uncertainty | artifact | replay | security
    title: str
    status: str      # AcceptanceMissionStatus constant
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
# Canonical acceptance mission criteria
# ---------------------------------------------------------------------------

ACCEPTANCE_MISSION_CRITERIA: tuple[AcceptanceMissionCriterion, ...] = (

    # ------------------------------------------------------------------ CANONICAL EVIDENCE
    AcceptanceMissionCriterion(
        criterion_id="canonical_evidence_retrieval",
        area="canonical_evidence",
        title="Canonical evidence retrieval — lexical/semantic/hybrid read from evidence index",
        status=AcceptanceMissionStatus.READY,
        authoritative_module="app.calyx_conversation.routes._retrieval",
        evidence=(
            "_retrieval() dispatches to LEXICAL, SEMANTIC, or HYBRID retrieval mode; "
            "results from evidence_index, knowledge_graph, brain_graph; "
            "read_only=True, knowledge_graph_mutation=False in synthesis output"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    AcceptanceMissionCriterion(
        criterion_id="canonical_evidence_continuum_context",
        area="canonical_evidence",
        title="Calyx Continuum context — taxa, environmental facts, KG reads",
        status=AcceptanceMissionStatus.READY,
        authoritative_module="app.calyx_conversation.continuum_context",
        evidence=(
            "continuum_context module assembles taxa, knowledge_graph, brain_graph; "
            "evidence items tagged with source_family='knowledge_graph' or 'brain_graph'; "
            "review_state='CANONICAL_OR_GOVERNED' for KG evidence"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    AcceptanceMissionCriterion(
        criterion_id="canonical_evidence_read_only_enforcement",
        area="canonical_evidence",
        title="Evidence retrieval enforces read-only contract at every source",
        status=AcceptanceMissionStatus.READY,
        authoritative_module="app.calyx_conversation.evidence_synthesis.build_synthesis_packet",
        evidence=(
            "build_synthesis_packet() aggregates retrieval + continuum + climate + mission; "
            "no write path in any evidence assembly; "
            "SYNTHESIS_CONTRACT_VERSION='CALYX-EVIDENCE-SYNTHESIS-002'; "
            "read_only=True, knowledge_graph_mutation=False in output"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ SYNTHESIS
    AcceptanceMissionCriterion(
        criterion_id="synthesis_teaching_v1_mission",
        area="synthesis",
        title="TeachingSynthesisV1 returns structured synthesis for a read-only mission",
        status=AcceptanceMissionStatus.READY,
        authoritative_module="app.calyx_conversation.teaching_synthesis.build_teaching_synthesis",
        evidence=(
            "build_teaching_synthesis() produces 8-domain synthesis from read evidence; "
            "graph_mutation=False; sensitive_locality_withheld=True enforced; "
            "47 tests passing; merged via PR #1275"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    AcceptanceMissionCriterion(
        criterion_id="synthesis_http_mission_path",
        area="synthesis",
        title="GET /calyx/synthesis/{taxon_id} returns synthesis for orchid mission",
        status=AcceptanceMissionStatus.READY,
        authoritative_module="app.calyx_conversation.routes.teaching_synthesis",
        evidence=(
            "GET /calyx/synthesis/{taxon_id} with taxon_name returns TeachingSynthesisV1.to_dict(); "
            "UNAVAILABLE states for all 8 domains when no provider wired; "
            "15 endpoint tests; read-only path; no production mutation"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    AcceptanceMissionCriterion(
        criterion_id="synthesis_evidence_packet_to_provider",
        area="synthesis",
        title="Evidence synthesis packet passed to provider (governed context compaction)",
        status=AcceptanceMissionStatus.READY,
        authoritative_module="app.calyx_conversation.provider_runtime.compact_governed_context",
        evidence=(
            "compact_governed_context() caps context at _MAX_CONTEXT_CHARS=60000; "
            "provider_context() formats governed context for provider consumption; "
            "generative path blocked in NO-API mode; synthesis packet always built"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    AcceptanceMissionCriterion(
        criterion_id="synthesis_live_generative",
        area="synthesis",
        title="Live generative synthesis from Calyx provider",
        status=AcceptanceMissionStatus.BLOCKED,
        authoritative_module="app.calyx_conversation.provider_runtime.OpenAIRuntimeResponsesProvider",
        evidence=(
            "OpenAIRuntimeResponsesProvider available; "
            "generative_ready=False in NO-API mode; "
            "deterministic-governed path produces evidence without generation"
        ),
        gap_description=None,
        blocker_reason=(
            "NO-API mode: live generative synthesis requires OPENAI_API_KEY or "
            "CALYX_CHAT_COMPLETIONS_URL, not provisioned in this execution environment"
        ),
        next_action="Activate live provider when NO-API constraint lifts",
    ),

    # ------------------------------------------------------------------ CITATIONS
    AcceptanceMissionCriterion(
        criterion_id="citations_per_evidence_item",
        area="citations",
        title="Per-evidence-item citation surfaced in synthesis packet",
        status=AcceptanceMissionStatus.READY,
        authoritative_module="app.calyx_conversation.evidence_synthesis.build_synthesis_packet",
        evidence=(
            "Each retrieval result: provenance.citation field from result.get('citation'); "
            "external literature: provenance includes doi, pmid, pmcid, authors, journal; "
            "KG evidence: provenance includes graph source label"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    AcceptanceMissionCriterion(
        criterion_id="citations_source_family_tagging",
        area="citations",
        title="Source family tagging — continuum_retrieval vs external_literature vs graph",
        status=AcceptanceMissionStatus.READY,
        authoritative_module="app.calyx_conversation.evidence_synthesis._evidence_item",
        evidence=(
            "_evidence_item() tags source_family ∈ {continuum_retrieval, external_literature, "
            "knowledge_graph, brain_graph}; downstream consumers can distinguish citation types; "
            "review_state distinguishes CANONICAL_OR_GOVERNED from REVIEW_REQUIRED"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    AcceptanceMissionCriterion(
        criterion_id="citations_no_fabrication",
        area="citations",
        title="Citations never fabricated — only surface identifiers present in source data",
        status=AcceptanceMissionStatus.READY,
        authoritative_module="app.calyx_conversation.evidence_synthesis.build_synthesis_packet",
        evidence=(
            "provenance dict uses item.get() for all citation fields; "
            "None values are preserved (not substituted); "
            "evidence_state='unavailable' when no data available rather than fabricated citation"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ UNCERTAINTY
    AcceptanceMissionCriterion(
        criterion_id="uncertainty_evidence_state_disclosure",
        area="uncertainty",
        title="Evidence state disclosure — unavailable/gap/unknown states surfaced explicitly",
        status=AcceptanceMissionStatus.READY,
        authoritative_module="app.calyx_conversation.teaching_synthesis.build_teaching_synthesis",
        evidence=(
            "Domain data None → UNKNOWN_DOMAIN_DATA → evidence_state='unavailable'; "
            "knowledge_gaps list populated for all unavailable domains; "
            "no domain silently omitted — UNAVAILABLE is explicit, not hidden"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    AcceptanceMissionCriterion(
        criterion_id="uncertainty_system_prompt_label",
        area="uncertainty",
        title="Provider system prompt labels uncertainty, external-review-required, missing evidence",
        status=AcceptanceMissionStatus.READY,
        authoritative_module="app.calyx_conversation.evidence_synthesis.build_synthesis_packet",
        evidence=(
            "System prompt: 'Label inference, uncertainty, external review-required "
            "literature, and missing evidence naturally'; "
            "review_state='REVIEW_REQUIRED' for external literature evidence items"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    AcceptanceMissionCriterion(
        criterion_id="uncertainty_coverage_matrix",
        area="uncertainty",
        title="Coverage matrix — domain × evidence-state accounting for uncertainty",
        status=AcceptanceMissionStatus.READY,
        authoritative_module="app.scientific_adapter_lab.coverage_matrix",
        evidence=(
            "CoverageMatrix with DomainCoverage rows; evidence_state per domain; "
            "63 tests passing; merged via PR #1304; "
            "read-only accounting — never promotes uncertain evidence"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ ARTIFACT
    AcceptanceMissionCriterion(
        criterion_id="artifact_immutable_registration",
        area="artifact",
        title="ImmutableArtifactRegistry — idempotent registration, checksum integrity",
        status=AcceptanceMissionStatus.READY,
        authoritative_module="app.calyx_orchestrator.artifact_registry.ImmutableArtifactRegistry",
        evidence=(
            "register() raises on duplicate artifact_id; "
            "ArtifactRegistration.checksum = SHA-256 of content; "
            "ArtifactRelationType: DERIVED_FROM, EVIDENCES, RECEIPT_FOR, SUPERSEDES; "
            "ImmutableArtifactRegistry is not a publication authority"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    AcceptanceMissionCriterion(
        criterion_id="artifact_research_result_binding",
        area="artifact",
        title="ResearchExecutorResult bound to artifact_ids — provenance chain",
        status=AcceptanceMissionStatus.READY,
        authoritative_module="app.calyx_orchestrator.research_executor.ResearchExecutorResult",
        evidence=(
            "ResearchExecutorResult.artifact_ids list bound at execution time; "
            "project_id deterministic from request_id + _sha(); "
            "provenance dict links executor result to artifact registry entries"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ REPLAY
    AcceptanceMissionCriterion(
        criterion_id="replay_idempotent_executor",
        area="replay",
        title="Idempotent mission replay — same request_id produces same result",
        status=AcceptanceMissionStatus.READY,
        authoritative_module="app.calyx_orchestrator.research_executor.ResearchRequestStore.upsert",
        evidence=(
            "ResearchRequestStore.upsert() returns (existing_record, False) for duplicate; "
            "no re-execution of terminal states (completed/blocked); "
            "project_id and artifact_ids are deterministic hashes"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    AcceptanceMissionCriterion(
        criterion_id="replay_bundle_reproducibility",
        area="replay",
        title="Bundle reproducibility — verify_reproducibility() cross-checks digest",
        status=AcceptanceMissionStatus.READY,
        authoritative_module="runtime.taxonomy_preflight_reproducibility.verify_reproducibility",
        evidence=(
            "verify_reproducibility() re-hashes all bundle artifacts; "
            "cross-checks report_id across multiple bundle paths; "
            "digest mismatch raises ValueError"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    AcceptanceMissionCriterion(
        criterion_id="replay_event_continuation",
        area="replay",
        title="CompletionEvent deduplication via fingerprint — no-op replay prevention",
        status=AcceptanceMissionStatus.READY,
        authoritative_module="app.calyx_orchestrator.event_continuation.reconcile_completion_event",
        evidence=(
            "reconcile_completion_event() returns NO_OP_REPLAY when fingerprint in seen_fingerprints; "
            "FactoryBridgeAction.NO_OP for duplicate events; "
            "MissionStatus.DONE on replay prevents double-execution"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ SECURITY
    AcceptanceMissionCriterion(
        criterion_id="security_mission_read_only_enforced",
        area="security",
        title="Read-only mission contract enforced — no write path in acceptance path",
        status=AcceptanceMissionStatus.READY,
        authoritative_module="app.calyx_orchestrator.research_executor._AUTHORITY",
        evidence=(
            "_AUTHORITY all False; PROHIBITED_CAPABILITIES blocks production_graph_mutation; "
            "RepositoryEvidenceExecutor raises PermissionError on mutating_intent=True; "
            "ImmutableArtifactRegistry is not a publication authority"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    AcceptanceMissionCriterion(
        criterion_id="security_acceptance_publication_gated",
        area="security",
        title="Acceptance mission conclusions require owner authorization to publish",
        status=AcceptanceMissionStatus.OWNER_GATED,
        authoritative_module="app.calyx_orchestrator.research_executor._AUTHORITY",
        evidence=(
            "_AUTHORITY.scientific_publication_authorized=False; "
            "_AUTHORITY.evidence_promotion_authorized=False; "
            "all mission conclusions are staged pending human review"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action="Owner must explicitly authorize publication of acceptance mission conclusions",
    ),
)


# ---------------------------------------------------------------------------
# Audit builders
# ---------------------------------------------------------------------------

@dataclass
class CalyxAcceptanceMissionAudit:
    """Machine-readable Calyx acceptance mission audit result."""

    schema_version: str = SCHEMA_VERSION
    audit_date: str = AUDIT_DATE
    no_auto_publication: bool = True
    no_production_mutation: bool = True
    criteria: list[AcceptanceMissionCriterion] = field(default_factory=list)

    def by_status(self, status: str) -> list[AcceptanceMissionCriterion]:
        return [c for c in self.criteria if c.status == status]

    def by_area(self, area: str) -> list[AcceptanceMissionCriterion]:
        return [c for c in self.criteria if c.area == area]

    def ready_count(self) -> int:
        return len(self.by_status(AcceptanceMissionStatus.READY))

    def gap_count(self) -> int:
        return len(self.by_status(AcceptanceMissionStatus.GAP))

    def blocked_count(self) -> int:
        return len(self.by_status(AcceptanceMissionStatus.BLOCKED))

    def owner_gated_count(self) -> int:
        return len(self.by_status(AcceptanceMissionStatus.OWNER_GATED))

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


def get_calyx_acceptance_mission_audit() -> CalyxAcceptanceMissionAudit:
    """Return the current acceptance mission audit. Pure function — no external calls."""
    return CalyxAcceptanceMissionAudit(criteria=list(ACCEPTANCE_MISSION_CRITERIA))


def get_criteria_by_status(status: str) -> list[AcceptanceMissionCriterion]:
    return [c for c in ACCEPTANCE_MISSION_CRITERIA if c.status == status]


def get_criteria_by_area(area: str) -> list[AcceptanceMissionCriterion]:
    return [c for c in ACCEPTANCE_MISSION_CRITERIA if c.area == area]


def get_gaps() -> list[AcceptanceMissionCriterion]:
    return get_criteria_by_status(AcceptanceMissionStatus.GAP)


def get_next_actions() -> list[dict[str, str]]:
    return [
        {
            "criterion_id": c.criterion_id,
            "area": c.area,
            "title": c.title,
            "status": c.status,
            "next_action": c.next_action,
        }
        for c in ACCEPTANCE_MISSION_CRITERIA
        if c.next_action
    ]

"""Knowledge Graph quality audit — Approved Task Priority 20.

Inspects coverage, contradictions, orphan nodes, unsupported edges,
stale sources, and provenance gaps.

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

SCHEMA_VERSION = "knowledge-graph-quality-audit/v1"
AUDIT_DATE = "2026-09-09"


class KGQualityAuditStatus:
    READY = "READY"
    GAP = "GAP"
    BLOCKED = "BLOCKED"
    OWNER_GATED = "OWNER_GATED"


@dataclass(frozen=True)
class KGQualityCriterion:
    """One measurable criterion in the KG quality audit."""

    criterion_id: str
    area: str        # coverage | contradictions | orphans | edges | staleness | provenance | mutation
    title: str
    status: str      # KGQualityAuditStatus constant
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
# Canonical KG quality criteria
# ---------------------------------------------------------------------------

KG_QUALITY_CRITERIA: tuple[KGQualityCriterion, ...] = (

    # ------------------------------------------------------------------ COVERAGE
    KGQualityCriterion(
        criterion_id="coverage_source_registry",
        area="coverage",
        title="Source registry coverage — KnowledgeSourceRegistry with SourceKind taxonomy",
        status=KGQualityAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.knowledge_source_registry.KnowledgeSourceRegistry",
        evidence=(
            "KnowledgeSourceRegistry.register(): enforces unique source_id; "
            "KnowledgeSource: source_id, source_kind (SourceKind enum), trust_class, "
            "access_policy, provenance; public_view() / query() for coverage inspection"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    KGQualityCriterion(
        criterion_id="coverage_source_kind_taxonomy",
        area="coverage",
        title="Source kind taxonomy — SourceKind enum (primary, secondary, derived, synthetic)",
        status=KGQualityAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.knowledge_source_registry.SourceKind",
        evidence=(
            "SourceKind enum: primary | secondary | derived | synthetic; "
            "TrustClass: authoritative | peer_reviewed | community | unverified; "
            "AccessPolicy: public | restricted | internal"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    KGQualityCriterion(
        criterion_id="coverage_graph_operation_types",
        area="coverage",
        title="Graph operation coverage — GraphOperationType (add_node, add_edge, etc.)",
        status=KGQualityAuditStatus.READY,
        authoritative_module="app.knowledge_publication.graph_models.GraphOperationType",
        evidence=(
            "GraphOperationType: add_node | add_edge | remove_node | remove_edge | update_node | update_edge; "
            "GraphOperation: operation_type, subject, predicate, object, provenance; "
            "PublicationExecutionRequest: batches operations with transaction context"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    KGQualityCriterion(
        criterion_id="coverage_brain_candidate_types",
        area="coverage",
        title="Brain candidate record type coverage — BrainRecordType enum",
        status=KGQualityAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.brain_capture.BrainRecordType",
        evidence=(
            "BrainRecordType: multiple candidate record types enumerated in brain_capture.py; "
            "BrainCandidateRecord: checksum(), bundle_id, record_type, content, provenance; "
            "BrainCaptureBundle: groups multiple records with rollback support"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ CONTRADICTIONS
    KGQualityCriterion(
        criterion_id="contradictions_source_state",
        area="contradictions",
        title="Contradictory source state — SourceState.CONTRADICTORY in source registry",
        status=KGQualityAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.knowledge_source_registry.SourceState",
        evidence=(
            "SourceState.CONTRADICTORY: explicitly registered state for sources with conflicting claims; "
            "SourceState enum: active | inactive | stale | contradictory; "
            "KnowledgeSourceRegistry.query(): filter by SourceState.CONTRADICTORY for contradiction audit"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    KGQualityCriterion(
        criterion_id="contradictions_connector_policy",
        area="contradictions",
        title="Connector policy deduplication — ConnectorPolicy prevents duplicate registration",
        status=KGQualityAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.knowledge_source_registry.ConnectorPolicy",
        evidence=(
            "ConnectorPolicy: source_id dedup on registry; "
            "KnowledgeSourceRegistry.register(): raises ValueError if source_id exists with "
            "different policy or provenance (contradiction at registration time); "
            "stable_idempotency_key(): deterministic key prevents action collision"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    KGQualityCriterion(
        criterion_id="contradictions_live_resolution",
        area="contradictions",
        title="Live contradiction resolution — blocked without canonical KG write authority",
        status=KGQualityAuditStatus.BLOCKED,
        authoritative_module="app.knowledge_publication.graph_service.ControlledGraphPublicationService",
        evidence=(
            "ControlledGraphPublicationService.publish(): writes to KG via repository; "
            "contradiction resolution requires canonical KG mutation; "
            "CLAUDE.md: never mutate production KG without owner authorization"
        ),
        gap_description=None,
        blocker_reason=(
            "Live contradiction resolution requires production KG write access which "
            "is owner-gated; static audit can identify contradictions but not resolve them"
        ),
        next_action="Await owner authorization before resolving contradictions in canonical KG",
    ),

    # ------------------------------------------------------------------ ORPHANS
    KGQualityCriterion(
        criterion_id="orphans_artifact_evidence_required",
        area="orphans",
        title="Artifact orphan prevention — require_evidence() enforces EVIDENCES linkage",
        status=KGQualityAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.artifact_registry.ImmutableArtifactRegistry.require_evidence",
        evidence=(
            "require_evidence(): raises KeyError if artifact has no EVIDENCES relation; "
            "ArtifactRelationType.EVIDENCES: prevents orphaned artifacts; "
            "ArtifactRelation: source_artifact_id, relation, target_artifact_id chain"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    KGQualityCriterion(
        criterion_id="orphans_brain_capture_rollback",
        area="orphans",
        title="Candidate record rollback — BrainCandidateStore.rollback() removes orphaned bundles",
        status=KGQualityAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.brain_capture.BrainCandidateStore.rollback",
        evidence=(
            "BrainCandidateStore.rollback(bundle_id): removes bundle and all its candidate records; "
            "prevents orphaned partial bundles after failed captures; "
            "checksum(): SHA-256 of bundle content verifies bundle integrity before promotion"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ EDGES
    KGQualityCriterion(
        criterion_id="edges_graph_operation_provenance",
        area="edges",
        title="Graph edge provenance — GraphOperation provenance field required",
        status=KGQualityAuditStatus.READY,
        authoritative_module="app.knowledge_publication.graph_models.GraphOperation",
        evidence=(
            "GraphOperation: operation_type, subject, predicate, object, provenance; "
            "__post_init__(): validates required fields; "
            "every add_edge operation must carry provenance; unsupported edges rejected at creation"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    KGQualityCriterion(
        criterion_id="edges_controlled_publication",
        area="edges",
        title="Controlled edge publication — ControlledGraphPublicationService.prepare() before publish",
        status=KGQualityAuditStatus.READY,
        authoritative_module="app.knowledge_publication.graph_service.ControlledGraphPublicationService",
        evidence=(
            "ControlledGraphPublicationService: prepare() validates before publish(); "
            "two-phase: prepare (dry-run validation) → publish (committed mutation); "
            "transaction() and graph_version() for audit trail access"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    KGQualityCriterion(
        criterion_id="edges_live_kg_write",
        area="edges",
        title="Live KG edge write — owner-gated graph mutation",
        status=KGQualityAuditStatus.OWNER_GATED,
        authoritative_module="app.knowledge_publication.graph_service.ControlledGraphPublicationService.publish",
        evidence=(
            "ControlledGraphPublicationService.publish(): performs actual KG mutation; "
            "knowledge_graph_mutation=False in speak_routes status; "
            "CLAUDE.md: never mutate production KG without required owner authorization"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action="Await explicit owner authorization before any live KG edge write",
    ),

    # ------------------------------------------------------------------ STALENESS
    KGQualityCriterion(
        criterion_id="staleness_source_state",
        area="staleness",
        title="Stale source detection — SourceState.STALE in knowledge source registry",
        status=KGQualityAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.knowledge_source_registry.SourceState",
        evidence=(
            "SourceState.STALE: registered state for sources with outdated information; "
            "KnowledgeSource.to_dict(): includes source_state in registry view; "
            "KnowledgeSourceRegistry.query(): filter by SourceState.STALE for staleness audit"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    KGQualityCriterion(
        criterion_id="staleness_temporal_retrieval_filter",
        area="staleness",
        title="Stale document filtering — temporal_status filter in RetrievalQuery",
        status=KGQualityAuditStatus.READY,
        authoritative_module="app.evidence_retrieval.models.RetrievalQuery",
        evidence=(
            "RetrievalQuery.temporal_status filter: exclude stale documents from retrieval; "
            "RetrievalEngine._temporal(): freshness signal per document; "
            "stale sources can be filtered without suppression"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ PROVENANCE
    KGQualityCriterion(
        criterion_id="provenance_source_registration",
        area="provenance",
        title="Source provenance at registration — KnowledgeSource provenance field",
        status=KGQualityAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.knowledge_source_registry.KnowledgeSource",
        evidence=(
            "KnowledgeSource: source_id, provenance field required; "
            "KnowledgeSourceRegistry.register(): raises ValueError on conflicting provenance; "
            "to_dict(): surfaces provenance in public_view() for external consumers"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    KGQualityCriterion(
        criterion_id="provenance_brain_candidate_checksum",
        area="provenance",
        title="Brain candidate provenance — SHA-256 checksum per record and per bundle",
        status=KGQualityAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.brain_capture.BrainCandidateRecord",
        evidence=(
            "BrainCandidateRecord.checksum(): SHA-256 of candidate content; "
            "BrainCaptureBundle.checksum(): SHA-256 of bundle; "
            "BrainCandidateStore.capture(): records provenance with each captured record"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ MUTATION
    KGQualityCriterion(
        criterion_id="mutation_owner_authorization_required",
        area="mutation",
        title="KG mutation owner gate — knowledge_graph_mutation=False at runtime",
        status=KGQualityAuditStatus.OWNER_GATED,
        authoritative_module="app.calyx_conversation.speak_routes.speak_status",
        evidence=(
            "speak_status(): knowledge_graph_mutation=False; "
            "CLAUDE.md: never mutate production DB/KG without required owner authorization; "
            "FactoryAction.OWNER_GATE routes all KG mutation requests to owner"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action="Await explicit owner authorization before any production KG mutation",
    ),
    KGQualityCriterion(
        criterion_id="mutation_candidate_knowledge_review",
        area="mutation",
        title="Candidate knowledge review gate — review-first extraction (BUILD-086A)",
        status=KGQualityAuditStatus.READY,
        authoritative_module="app.candidate_knowledge",
        evidence=(
            "candidate_knowledge module: BUILD-086A review-first extraction; "
            "all candidate knowledge requires human review before canonical promotion; "
            "automatic_publication=False enforced; no autonomous KG mutation"
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
class KnowledgeGraphQualityAudit:
    """Machine-readable KG quality audit result."""

    schema_version: str = SCHEMA_VERSION
    audit_date: str = AUDIT_DATE
    no_auto_publication: bool = True
    no_production_mutation: bool = True
    criteria: list[KGQualityCriterion] = field(default_factory=list)

    def by_status(self, status: str) -> list[KGQualityCriterion]:
        return [c for c in self.criteria if c.status == status]

    def by_area(self, area: str) -> list[KGQualityCriterion]:
        return [c for c in self.criteria if c.area == area]

    def ready_count(self) -> int:
        return len(self.by_status(KGQualityAuditStatus.READY))

    def gap_count(self) -> int:
        return len(self.by_status(KGQualityAuditStatus.GAP))

    def blocked_count(self) -> int:
        return len(self.by_status(KGQualityAuditStatus.BLOCKED))

    def owner_gated_count(self) -> int:
        return len(self.by_status(KGQualityAuditStatus.OWNER_GATED))

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


def get_knowledge_graph_quality_audit() -> KnowledgeGraphQualityAudit:
    """Return the current KG quality audit. Pure function — no external calls."""
    return KnowledgeGraphQualityAudit(criteria=list(KG_QUALITY_CRITERIA))


def get_criteria_by_status(status: str) -> list[KGQualityCriterion]:
    return [c for c in KG_QUALITY_CRITERIA if c.status == status]


def get_criteria_by_area(area: str) -> list[KGQualityCriterion]:
    return [c for c in KG_QUALITY_CRITERIA if c.area == area]


def get_gaps() -> list[KGQualityCriterion]:
    return get_criteria_by_status(KGQualityAuditStatus.GAP)


def get_next_actions() -> list[dict[str, str]]:
    return [
        {
            "criterion_id": c.criterion_id,
            "area": c.area,
            "title": c.title,
            "status": c.status,
            "next_action": c.next_action,
        }
        for c in KG_QUALITY_CRITERIA
        if c.next_action
    ]

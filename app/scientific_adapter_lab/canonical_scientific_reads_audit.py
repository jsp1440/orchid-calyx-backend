"""Canonical scientific reads audit — Approved Task Priority 13.

Verifies that taxonomy, occurrence, elevation, traits, literature, ecological
relationship, and provenance reads are canonical and read-only.

Status vocabulary:
  READY        — implemented, tested, and integrated; read is canonical and read-only
  GAP          — described in acceptance criteria but not yet closed
  BLOCKED      — requires external dependency (NO-API mode, unprovisioned infra)
  OWNER_GATED  — requires explicit owner authorization before proceeding

No live-model spending. No production KG mutation. Read-only static audit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "canonical-scientific-reads-audit/v1"
AUDIT_DATE = "2026-09-09"


class ReadsAuditStatus:
    READY = "READY"
    GAP = "GAP"
    BLOCKED = "BLOCKED"
    OWNER_GATED = "OWNER_GATED"


@dataclass(frozen=True)
class ReadsAuditCriterion:
    """One measurable criterion in the canonical scientific reads audit."""

    criterion_id: str
    area: str        # taxonomy | occurrence | elevation | traits | literature | ecology | provenance
    title: str
    status: str      # ReadsAuditStatus constant
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
# Canonical scientific reads criteria
# ---------------------------------------------------------------------------

READS_AUDIT_CRITERIA: tuple[ReadsAuditCriterion, ...] = (

    # ------------------------------------------------------------------ TAXONOMY
    ReadsAuditCriterion(
        criterion_id="taxonomy_preflight_read",
        area="taxonomy",
        title="Taxonomy preflight validation — read-only candidate CSV/TSV inspection",
        status=ReadsAuditStatus.READY,
        authoritative_module="runtime.taxonomy_preflight.validate",
        evidence=(
            "validate() reads candidate file; never writes to it; "
            "compare_rows() read-only diff against baseline; "
            "Report produced from read evidence only; no taxonomy mutation"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ReadsAuditCriterion(
        criterion_id="taxonomy_release_intake_read",
        area="taxonomy",
        title="Taxonomy release intake — REVIEW_ONLY decision, no activation path",
        status=ReadsAuditStatus.READY,
        authoritative_module="runtime.taxonomy_release_intake_v2.TaxonomyReleaseIntakeService",
        evidence=(
            "TaxonomyReleaseIntakeService decision ∈ {REVIEW_ONLY, HOLD}; "
            "no ACTIVATE or PROMOTE decision exists; "
            "staging artifacts written to review queue, not to canonical store"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ReadsAuditCriterion(
        criterion_id="taxonomy_conservation_read",
        area="taxonomy",
        title="Conservation status contract — governed read contract (IUCN/CITES/appendix)",
        status=ReadsAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.conservation_status",
        evidence=(
            "ConservationStatusRecord: review_required=True, graph_mutation=False; "
            "auto_promotion_blocked=True; enforced in __post_init__ via PermissionError; "
            "merged into oc-autonomous-integration"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ OCCURRENCE
    ReadsAuditCriterion(
        criterion_id="occurrence_gbif_source_registered",
        area="occurrence",
        title="GBIF occurrence — source registered in discovery registry",
        status=ReadsAuditStatus.READY,
        authoritative_module="app.scientific_adapter_lab.source_discovery_registry",
        evidence=(
            "GloBI source references GBIF taxon IDs; iNaturalist source maps taxon IDs "
            "to GBIF backbone; Zenodo occurrence datasets reference GBIF; "
            "source_discovery_registry.py documents taxon_reconciliation_strategy for each"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ReadsAuditCriterion(
        criterion_id="occurrence_gbif_live_adapter",
        area="occurrence",
        title="Live GBIF occurrence API adapter (real occurrence data fetch)",
        status=ReadsAuditStatus.BLOCKED,
        authoritative_module="app.scientific_adapter_lab.source_discovery_registry (GBIF via iNat/GloBI)",
        evidence=(
            "iNaturalist and GloBI adapters reference GBIF backbone IDs; "
            "no standalone GBIF occurrence HTTP adapter is implemented; "
            "occurrence data flows through GloBI/iNat federation paths"
        ),
        gap_description=None,
        blocker_reason=(
            "NO-API mode: live GBIF occurrence API calls require outbound HTTPS "
            "which is not verified available in this execution environment"
        ),
        next_action="Implement standalone GBIF occurrence adapter when NO-API constraint lifts",
    ),
    ReadsAuditCriterion(
        criterion_id="occurrence_locality_withheld",
        area="occurrence",
        title="Sensitive locality withheld in all occurrence read paths",
        status=ReadsAuditStatus.READY,
        authoritative_module="app.calyx_conversation.teaching_synthesis.build_teaching_synthesis",
        evidence=(
            "sensitive_locality_withheld=True enforced in TeachingSynthesisV1; "
            "iNaturalist source_discovery_registry entry: sensitive_locality_risk=HIGH; "
            "coordinates_withheld=True in sensitive_locality_policy dict; "
            "no lat/lon emitted in any read output"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ ELEVATION
    ReadsAuditCriterion(
        criterion_id="elevation_teaching_synthesis",
        area="elevation",
        title="Elevation / habitat domain — read from TeachingSynthesisV1 habitat slot",
        status=ReadsAuditStatus.READY,
        authoritative_module="app.calyx_conversation.teaching_synthesis.build_teaching_synthesis",
        evidence=(
            "habitat domain slot in build_teaching_synthesis() accepts domain_data['habitat']; "
            "None → UNKNOWN_DOMAIN_DATA sentinel → evidence_state='unavailable'; "
            "no fabricated elevation data; elevation reads wait for provider wiring"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ReadsAuditCriterion(
        criterion_id="elevation_live_provider",
        area="elevation",
        title="Live elevation / habitat provider (real elevation data fetch)",
        status=ReadsAuditStatus.BLOCKED,
        authoritative_module="app.calyx_conversation.teaching_synthesis.build_teaching_synthesis",
        evidence=(
            "habitat domain slot accepts None → UNAVAILABLE; "
            "no external elevation API is integrated; "
            "habitat slot becomes UNAVAILABLE in degraded mode"
        ),
        gap_description=None,
        blocker_reason=(
            "NO-API mode: live elevation / habitat data from external APIs "
            "not available in current execution environment"
        ),
        next_action="Wire elevation/habitat provider when NO-API constraint lifts",
    ),

    # ------------------------------------------------------------------ TRAITS
    ReadsAuditCriterion(
        criterion_id="traits_vision_matrix_read",
        area="traits",
        title="Morphological traits read — Vision/Matrix proof path (Epidendrum fixture)",
        status=ReadsAuditStatus.READY,
        authoritative_module="app.scientific_adapter_lab.vision_matrix_proof.run_vision_matrix_proof",
        evidence=(
            "run_vision_matrix_proof() 5-stage fixture reads morphology, resupination, "
            "labellum traits from VisionLexicon; 51 tests; read-only fixture path; "
            "no KG write; merged via PR #1304"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ReadsAuditCriterion(
        criterion_id="traits_molecular_sequence_read",
        area="traits",
        title="Molecular sequence traits read — ITS accession / GenBank adapter",
        status=ReadsAuditStatus.READY,
        authoritative_module="app.scientific_adapter_lab.molecular_sequence",
        evidence=(
            "MolecularSequenceRecord frozen dataclass; validate() reads accession metadata; "
            "63 tests passing; graph_mutation=False; read-only; merged via PR #1304"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ReadsAuditCriterion(
        criterion_id="traits_teaching_synthesis_domain",
        area="traits",
        title="Traits domain in TeachingSynthesisV1 (morphology_anatomy_physiology slot)",
        status=ReadsAuditStatus.READY,
        authoritative_module="app.calyx_conversation.teaching_synthesis.build_teaching_synthesis",
        evidence=(
            "morphology_anatomy_physiology domain slot: None → unavailable; "
            "trait evidence surfaced via relationship_model dict when provider wired; "
            "8-domain coverage matrix tracks traits evidence state"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ LITERATURE
    ReadsAuditCriterion(
        criterion_id="literature_europe_pmc_read",
        area="literature",
        title="Europe PMC literature read — governed external_literature acquisition",
        status=ReadsAuditStatus.READY,
        authoritative_module="app.calyx_conversation.external_literature.search_europe_pmc",
        evidence=(
            "search_europe_pmc() read-only API call; results stored in "
            "ResearchExecutorResult.external_literature; review_required=True; "
            "automatic_publication=False; knowledge_graph_mutation=False in summary"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ReadsAuditCriterion(
        criterion_id="literature_evidence_synthesis_read",
        area="literature",
        title="Evidence synthesis read contract (CALYX-EVIDENCE-SYNTHESIS-002)",
        status=ReadsAuditStatus.READY,
        authoritative_module="app.calyx_conversation.evidence_synthesis",
        evidence=(
            "SYNTHESIS_CONTRACT_VERSION='CALYX-EVIDENCE-SYNTHESIS-002'; "
            "build_synthesis_packet() assembles evidence from read sources; "
            "read_only=True, knowledge_graph_mutation=False in synthesis output"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ReadsAuditCriterion(
        criterion_id="literature_source_registry_decisions",
        area="literature",
        title="Source discovery registry — literature sources (Zenodo, BHL, Europe PMC)",
        status=ReadsAuditStatus.READY,
        authoritative_module="app.scientific_adapter_lab.source_discovery_registry",
        evidence=(
            "SCHEMA_VERSION='oc-source-discovery-registry/v1'; "
            "Zenodo (ADD), BHL (ADD), Europe PMC (KEEP); "
            "all decisions include provenance_contract field; no source decision is ACTIVATE"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ ECOLOGY
    ReadsAuditCriterion(
        criterion_id="ecology_globi_interaction_read",
        area="ecology",
        title="GloBI ecological interaction read — normalize/stage/resolve adapter",
        status=ReadsAuditStatus.READY,
        authoritative_module="app.scientific_adapter_lab.interaction_laboratory",
        evidence=(
            "normalize_interaction() read-only; stage_interaction_for_review() → staged, not promoted; "
            "resolve_interaction_precedence() pure read; InteractionGateway(available=False) → UNKNOWN; "
            "72 tests; PR #1307"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ReadsAuditCriterion(
        criterion_id="ecology_pollination_read",
        area="ecology",
        title="Pollination / mycorrhizal domain read in TeachingSynthesisV1",
        status=ReadsAuditStatus.READY,
        authoritative_module="app.calyx_conversation.teaching_synthesis.build_teaching_synthesis",
        evidence=(
            "pollination and mycorrhizae domain slots in build_teaching_synthesis(); "
            "None → unavailable; relationship_model dict surfaced when provider wired; "
            "iNaturalist source registered for pollination observations (source_discovery_registry)"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ PROVENANCE
    ReadsAuditCriterion(
        criterion_id="provenance_per_record_contract",
        area="provenance",
        title="Per-record provenance contract — all sources document provenance_contract",
        status=ReadsAuditStatus.READY,
        authoritative_module="app.scientific_adapter_lab.source_discovery_registry",
        evidence=(
            "Every SOURCE_CANDIDATES entry has provenance_contract field; "
            "GloBI: 'globi-canonical-dataset-review-bound-v1'; "
            "Europe PMC: 'Surface PMCID + DOI + journal + authors'; "
            "BHL: 'Surface BHLItemID + volume/page + publication title'"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ReadsAuditCriterion(
        criterion_id="provenance_research_executor_result",
        area="provenance",
        title="ResearchExecutorResult provenance dict — source identity in every result",
        status=ReadsAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.research_executor.ResearchExecutorResult",
        evidence=(
            "ResearchExecutorResult.provenance dict included in to_dict(); "
            "_sha() deterministic SHA-256 of any provenance value; "
            "SCHEMA_VERSION included in every result for downstream traceability"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ReadsAuditCriterion(
        criterion_id="provenance_repository_evidence_read",
        area="provenance",
        title="Repository evidence executor — read-only git metadata/hash provenance",
        status=ReadsAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.repository_evidence_executor.RepositoryEvidenceExecutor",
        evidence=(
            "RepositoryEvidenceExecutor.execute() raises PermissionError on mutating_intent=True; "
            "raises PermissionError on repository mismatch; "
            "produces SHA-256 file hashes + git metadata; never writes to repository"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ReadsAuditCriterion(
        criterion_id="provenance_no_autonomous_publish",
        area="provenance",
        title="No autonomous publication of provenance-backed conclusions",
        status=ReadsAuditStatus.OWNER_GATED,
        authoritative_module="app.calyx_orchestrator.research_executor._AUTHORITY",
        evidence=(
            "_AUTHORITY.scientific_publication_authorized=False; "
            "evidence_promotion_authorized=False; "
            "all provenance-backed conclusions require human review before use"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action="Owner must explicitly authorize scientific publication of any conclusion",
    ),
)


# ---------------------------------------------------------------------------
# Audit builders
# ---------------------------------------------------------------------------

@dataclass
class CanonicalScientificReadsAudit:
    """Machine-readable canonical scientific reads audit result."""

    schema_version: str = SCHEMA_VERSION
    audit_date: str = AUDIT_DATE
    no_auto_publication: bool = True
    no_production_mutation: bool = True
    criteria: list[ReadsAuditCriterion] = field(default_factory=list)

    def by_status(self, status: str) -> list[ReadsAuditCriterion]:
        return [c for c in self.criteria if c.status == status]

    def by_area(self, area: str) -> list[ReadsAuditCriterion]:
        return [c for c in self.criteria if c.area == area]

    def ready_count(self) -> int:
        return len(self.by_status(ReadsAuditStatus.READY))

    def gap_count(self) -> int:
        return len(self.by_status(ReadsAuditStatus.GAP))

    def blocked_count(self) -> int:
        return len(self.by_status(ReadsAuditStatus.BLOCKED))

    def owner_gated_count(self) -> int:
        return len(self.by_status(ReadsAuditStatus.OWNER_GATED))

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


def get_canonical_scientific_reads_audit() -> CanonicalScientificReadsAudit:
    """Return the current canonical scientific reads audit. Pure function — no external calls."""
    return CanonicalScientificReadsAudit(criteria=list(READS_AUDIT_CRITERIA))


def get_criteria_by_status(status: str) -> list[ReadsAuditCriterion]:
    return [c for c in READS_AUDIT_CRITERIA if c.status == status]


def get_criteria_by_area(area: str) -> list[ReadsAuditCriterion]:
    return [c for c in READS_AUDIT_CRITERIA if c.area == area]


def get_gaps() -> list[ReadsAuditCriterion]:
    return get_criteria_by_status(ReadsAuditStatus.GAP)


def get_next_actions() -> list[dict[str, str]]:
    return [
        {
            "criterion_id": c.criterion_id,
            "area": c.area,
            "title": c.title,
            "status": c.status,
            "next_action": c.next_action,
        }
        for c in READS_AUDIT_CRITERIA
        if c.next_action
    ]

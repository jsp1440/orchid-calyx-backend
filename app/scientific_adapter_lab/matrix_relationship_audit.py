"""Relationship Matrix audit — Approved Task Priority 30.

Inspect evidence coverage, unavailable dimensions, neighborhood quality,
and relationship-path explanations.

No live-model spending. No production mutation. Read-only static audit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "matrix-relationship-audit/v1"
AUDIT_DATE = "2026-09-09"


class MatrixRelationshipAuditStatus:
    READY = "READY"
    GAP = "GAP"
    BLOCKED = "BLOCKED"
    OWNER_GATED = "OWNER_GATED"


@dataclass(frozen=True)
class MatrixRelationshipCriterion:
    criterion_id: str
    area: str
    title: str
    status: str
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


MATRIX_RELATIONSHIP_CRITERIA: tuple[MatrixRelationshipCriterion, ...] = (

    # ------------------------------------------------------------------ EVIDENCE_COVERAGE
    MatrixRelationshipCriterion(
        criterion_id="evidence_class_observational_default",
        area="evidence_coverage",
        title="OBSERVATIONAL default — automatic extraction defaults to OBSERVATIONAL evidence class",
        status=MatrixRelationshipAuditStatus.READY,
        authoritative_module="app.scientific_synthesis.matrix.EvidenceMatrixBuilder",
        evidence=(
            "EvidenceMatrixBuilder.build(): evidence_class=EvidenceClass.OBSERVATIONAL always; "
            "docstring: 'A stronger design class such as CONTROLLED_EXPERIMENT or DIRECT_TRACER "
            "requires a later reviewed classification rather than being inferred from persuasive prose'; "
            "conservative default prevents unreviewed extraction from claiming stronger evidence"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    MatrixRelationshipCriterion(
        criterion_id="evidence_class_hierarchy",
        area="evidence_coverage",
        title="Evidence class hierarchy — EvidenceClass enum defines six ordered evidence types",
        status=MatrixRelationshipAuditStatus.READY,
        authoritative_module="app.scientific_synthesis.models.EvidenceClass",
        evidence=(
            "EvidenceClass enum: DIRECT_TRACER | CONTROLLED_EXPERIMENT | OBSERVATIONAL | "
            "EXPERT_PRACTICE | COMMERCIAL_CLAIM | MECHANISTIC_INFERENCE; "
            "six distinct epistemic levels prevent class conflation; "
            "EvidenceMatrixRow carries evidence_class per row"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    MatrixRelationshipCriterion(
        criterion_id="evidence_anchors_content_hash",
        area="evidence_coverage",
        title="Anchor content integrity — EvidenceAnchor carries content_hash and excerpt_hash",
        status=MatrixRelationshipAuditStatus.READY,
        authoritative_module="app.scientific_synthesis.models.EvidenceAnchor",
        evidence=(
            "EvidenceAnchor(anchor_id, source_id, source_revision_id, locator, content_hash, excerpt_hash); "
            "matrix._expected_integrity_proof(): SHA-256 of excerpt + char_start/end span; "
            "anchor provenance is bound to source content hash — not just identifier"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    MatrixRelationshipCriterion(
        criterion_id="evidence_absence_not_fabricated",
        area="evidence_coverage",
        title="Absence not fabricated — missing rows become not_recorded, never biological absent",
        status=MatrixRelationshipAuditStatus.READY,
        authoritative_module="runtime.matrix_relationship.build_relationship_matrix",
        evidence=(
            "build_relationship_matrix(): cells with no assertions → state='not_recorded'; "
            "matrix_relationship_sources.py docstring: 'missing rows never become biological absence'; "
            "disclaimer in matrix output: 'A blank evidence record is never interpreted as biological absence'"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ UNAVAILABLE_DIMENSIONS
    MatrixRelationshipCriterion(
        criterion_id="unavailable_db_required",
        area="unavailable_dimensions",
        title="Live dimension query requires DATABASE_URL — governed_source_dimensions() blocked in NO-DB mode",
        status=MatrixRelationshipAuditStatus.BLOCKED,
        authoritative_module="runtime.matrix_relationship_sources.governed_source_dimensions",
        evidence=(
            "governed_source_dimensions(): calls registry_by_domain() which requires live DB; "
            "_DIMENSION_TO_DOMAIN: pollinator | mycorrhizal_partner | literature | trait | "
            "conservation_status | geography | elevation → 7 governed dimensions; "
            "returned only when domain is registry.enabled and registry.sql non-null"
        ),
        gap_description=None,
        blocker_reason="DATABASE_URL required to enumerate live governed source dimensions at runtime",
        next_action="Provide DATABASE_URL to enumerate which of the 7 governed dimensions have enabled source queries",
    ),
    MatrixRelationshipCriterion(
        criterion_id="unavailable_distinct_from_absent",
        area="unavailable_dimensions",
        title="Unavailable distinct from absent — audit schema failure is never a biological finding",
        status=MatrixRelationshipAuditStatus.READY,
        authoritative_module="app.readiness.relationship_measurement._unavailable",
        evidence=(
            "_unavailable(name, detail): returns {'state': 'unavailable', ...} — not 'absent'; "
            "module docstring: 'Absence is only ever reported from a join that ran'; "
            "'A schema-discovery failure is a fact about this audit's assumptions'; "
            "'converting it into a finding about orchid biology is the exact defect AUDIT-MEASUREMENT-001'"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    MatrixRelationshipCriterion(
        criterion_id="unavailable_candidate_probe",
        area="unavailable_dimensions",
        title="All candidates probed — _probe_candidates() measures all candidates, not just selected",
        status=MatrixRelationshipAuditStatus.READY,
        authoritative_module="app.readiness.relationship_measurement._probe_candidates",
        evidence=(
            "_probe_candidates(): returns (selected_table, list_of_all_candidate_measurements); "
            "module docstring: 'Every candidate is probed, not just the selected one'; "
            "'_first_existing semantics mean a small legacy relation earlier in a list silently hides "
            "a larger corpus behind it — which is how the occurrence metric came to read 26 rows "
            "while roughly 580,000 sat in another relation'; unselected candidates reported"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ NEIGHBORHOOD_QUALITY
    MatrixRelationshipCriterion(
        criterion_id="neighborhood_compare_subjects",
        area="neighborhood_quality",
        title="Neighbor comparison — compare_subjects() compares matrix rows without collapsing states",
        status=MatrixRelationshipAuditStatus.READY,
        authoritative_module="runtime.matrix_relationship.compare_subjects",
        evidence=(
            "compare_subjects(): returns shared_present, present_absent_disagreements, comparisons; "
            "each comparison carries left_state, right_state, same_state separately; "
            "states are not averaged or merged — epistemic distinctions preserved across neighbor comparison"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    MatrixRelationshipCriterion(
        criterion_id="neighborhood_conflicting_preserved",
        area="neighborhood_quality",
        title="Conflicting state preserved — _collapse_states() returns conflicting when present+absent co-exist",
        status=MatrixRelationshipAuditStatus.READY,
        authoritative_module="runtime.matrix_relationship._collapse_states",
        evidence=(
            "_collapse_states(): 'conflicting' in states → 'conflicting'; "
            "{'present', 'absent'} <= states → 'conflicting'; "
            "conflicting is never resolved to present or absent — contradiction preserved as a distinct state"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    MatrixRelationshipCriterion(
        criterion_id="neighborhood_state_counts",
        area="neighborhood_quality",
        title="State count summary — build_relationship_matrix() returns per-state counts for coverage visibility",
        status=MatrixRelationshipAuditStatus.READY,
        authoritative_module="runtime.matrix_relationship.build_relationship_matrix",
        evidence=(
            "build_relationship_matrix(): state_counts = {state: count for state in sorted(_ALLOWED_STATES)}; "
            "all five states counted: present | absent | unknown | not_recorded | conflicting; "
            "state distribution visible without scanning individual cells"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ RELATIONSHIP_PATH
    MatrixRelationshipCriterion(
        criterion_id="path_epistemic_state_vocab",
        area="relationship_path",
        title="Epistemic state vocabulary — five distinct states, not binary present/absent",
        status=MatrixRelationshipAuditStatus.READY,
        authoritative_module="runtime.matrix_relationship.RelationshipAssertion",
        evidence=(
            "RelationshipState = Literal['present', 'absent', 'unknown', 'not_recorded', 'conflicting']; "
            "_ALLOWED_STATES enforced in _validate(); "
            "five states cover: positive evidence | negative evidence | epistemic gap | "
            "no data collected | contradictory evidence — each conveying distinct scientific meaning"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    MatrixRelationshipCriterion(
        criterion_id="path_disclaimer",
        area="relationship_path",
        title="Matrix disclaimer — build_relationship_matrix() embeds epistemic state disclaimer",
        status=MatrixRelationshipAuditStatus.READY,
        authoritative_module="runtime.matrix_relationship.build_relationship_matrix",
        evidence=(
            "build_relationship_matrix(): disclaimer = 'Not-recorded, unknown, conflicting and absent "
            "are distinct states. A blank evidence record is never interpreted as biological absence'; "
            "disclaimer is a top-level key in every matrix response — not buried in metadata"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    MatrixRelationshipCriterion(
        criterion_id="path_dimension_domain_mapping",
        area="relationship_path",
        title="Dimension-to-domain mapping — 7 governed dimensions mapped to canonical source domains",
        status=MatrixRelationshipAuditStatus.READY,
        authoritative_module="runtime.matrix_relationship_sources._DIMENSION_TO_DOMAIN",
        evidence=(
            "_DIMENSION_TO_DOMAIN: {'pollinator': 'pollinators', 'mycorrhizal_partner': 'mycorrhiza', "
            "'literature': 'literature', 'trait': 'traits', 'conservation_status': 'conservation', "
            "'geography': 'occurrences', 'elevation': 'occurrences'}; "
            "router CanonicalSourceMatrixRequest dimension Literal enforces same vocabulary at API boundary"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    MatrixRelationshipCriterion(
        criterion_id="path_confidence_bounded",
        area="relationship_path",
        title="Confidence bounded 0-1 — confidence validated at assertion input and source adapter",
        status=MatrixRelationshipAuditStatus.READY,
        authoritative_module="runtime.matrix_relationship._validate",
        evidence=(
            "_validate(): confidence is not None and not 0 <= confidence <= 1 → ValueError; "
            "AssertionInput: confidence = Field(default=None, ge=0, le=1); "
            "_bounded_confidence() in sources: clips Decimal values to [0.0, 1.0]; "
            "_mean_confidence(): averages non-None confidence values, rounds to 6 decimal places"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ SECURITY
    MatrixRelationshipCriterion(
        criterion_id="security_owner_auth_required",
        area="security",
        title="Owner auth required — all matrix router endpoints require verify_owner_or_api_key",
        status=MatrixRelationshipAuditStatus.READY,
        authoritative_module="app.routers.matrix_relationship",
        evidence=(
            "router: all endpoints use Depends(verify_owner_or_api_key); "
            "contract(), canonical_matrix(), compare(), and assertion POST all guarded; "
            "no public access to relationship matrix data"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    MatrixRelationshipCriterion(
        criterion_id="security_safe_ident_validation",
        area="security",
        title="SQL identifier safety — _safe() rejects unsafe identifiers before interpolation",
        status=MatrixRelationshipAuditStatus.READY,
        authoritative_module="app.readiness.relationship_measurement._safe",
        evidence=(
            "_SAFE_IDENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*(\\.[A-Za-z_][A-Za-z0-9_]*)?$'); "
            "_safe(identifier): raises ValueError on mismatch; "
            "module docstring: 'Identifiers reach SQL by interpolation ... this guard is the third check, "
            "so a future edit to a candidate list cannot turn into injection'"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    MatrixRelationshipCriterion(
        criterion_id="security_no_canonical_graph_mutation",
        area="security",
        title="Canonical graph mutation forbidden — matrix engine is read-only; writes require owner authorization",
        status=MatrixRelationshipAuditStatus.OWNER_GATED,
        authoritative_module="runtime.matrix_relationship.build_relationship_matrix",
        evidence=(
            "build_relationship_matrix(): 'canonical_graph_mutation': False in every response; "
            "runtime/matrix_relationship.py docstring: 'It preserves unknown, not-recorded, "
            "conflicting, present and absent as distinct states and does not mutate the canonical graph'; "
            "matrix_relationship_sources: SELECT and catalog reads only — no INSERT/UPDATE/DELETE"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action="Owner authorization required before any write to the canonical relationship graph",
    ),
)


@dataclass
class MatrixRelationshipAudit:
    schema_version: str = SCHEMA_VERSION
    audit_date: str = AUDIT_DATE
    no_auto_publication: bool = True
    no_production_mutation: bool = True
    criteria: list[MatrixRelationshipCriterion] = field(default_factory=list)

    def by_status(self, status: str) -> list[MatrixRelationshipCriterion]:
        return [c for c in self.criteria if c.status == status]

    def by_area(self, area: str) -> list[MatrixRelationshipCriterion]:
        return [c for c in self.criteria if c.area == area]

    def ready_count(self) -> int:
        return len(self.by_status(MatrixRelationshipAuditStatus.READY))

    def gap_count(self) -> int:
        return len(self.by_status(MatrixRelationshipAuditStatus.GAP))

    def blocked_count(self) -> int:
        return len(self.by_status(MatrixRelationshipAuditStatus.BLOCKED))

    def owner_gated_count(self) -> int:
        return len(self.by_status(MatrixRelationshipAuditStatus.OWNER_GATED))

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


def get_matrix_relationship_audit() -> MatrixRelationshipAudit:
    return MatrixRelationshipAudit(criteria=list(MATRIX_RELATIONSHIP_CRITERIA))


def get_criteria_by_status(status: str) -> list[MatrixRelationshipCriterion]:
    return [c for c in MATRIX_RELATIONSHIP_CRITERIA if c.status == status]


def get_criteria_by_area(area: str) -> list[MatrixRelationshipCriterion]:
    return [c for c in MATRIX_RELATIONSHIP_CRITERIA if c.area == area]


def get_gaps() -> list[MatrixRelationshipCriterion]:
    return get_criteria_by_status(MatrixRelationshipAuditStatus.GAP)


def get_next_actions() -> list[dict[str, str]]:
    return [
        {
            "criterion_id": c.criterion_id,
            "area": c.area,
            "title": c.title,
            "status": c.status,
            "next_action": c.next_action,
        }
        for c in MATRIX_RELATIONSHIP_CRITERIA
        if c.next_action
    ]

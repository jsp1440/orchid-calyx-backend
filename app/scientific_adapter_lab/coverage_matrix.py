"""Machine-readable scientific coverage/freshness/backfill matrix for OC-COMPLETE-003.

Defines the schema and safety semantics for measuring current production state
across all major scientific domains. When production DB is unavailable, every
metric defaults to UNKNOWN — never fabricated as zero.

Safety invariants:
- Fabricated zero is forbidden: missing measurement → UNKNOWN, not 0.
- Unreviewed science is never promoted: evidence_state gates promotion.
- Stale metrics are surfaced explicitly, never silently reused as current.
- Production mutation is never triggered by reading this matrix.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

SCHEMA_VERSION = "oc-scientific-coverage-matrix/v1"


class CoverageState(StrEnum):
    MEASURED = "measured"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    STALE = "stale"
    BACKFILL_REQUIRED = "backfill_required"
    NOT_APPLICABLE = "not_applicable"


class CoverageDomain(StrEnum):
    TAXONOMY = "taxonomy"
    OCCURRENCES = "occurrences"
    IMAGES_MEDIA = "images_media"
    TRAITS = "traits"
    LITERATURE = "literature"
    POLLINATION = "pollination"
    MYCORRHIZA = "mycorrhiza"
    HABITAT = "habitat"
    KNOWLEDGE_GRAPH = "knowledge_graph"
    MOLECULAR_SEQUENCE = "molecular_sequence"


class EvidenceState(StrEnum):
    CANONICAL_REVIEWED = "canonical_reviewed"
    PENDING_REVIEW = "pending_review"
    MACHINE_GENERATED = "machine_generated"
    SOURCE_DISCOVERY = "source_discovery_only"
    UNKNOWN = "unknown"


class BackfillPriority(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


_NEVER_ZERO_FABRICATION = True
_AUTOMATIC_PUBLICATION = False
_KNOWLEDGE_GRAPH_MUTATION = False


@dataclass(frozen=True)
class DomainMetric:
    """One measurement for one metric in one scientific domain."""

    domain: CoverageDomain
    metric_key: str
    state: CoverageState
    value: int | float | str | None = None
    source_relation: str = ""
    source_version: str = ""
    generated_at: str = ""
    evidence_state: EvidenceState = EvidenceState.UNKNOWN
    notes: str = ""

    def __post_init__(self) -> None:
        # Fabricated zero: if state is MEASURED but value is 0 and no source,
        # that is suspicious — require at least a source_relation.
        if (
            self.state == CoverageState.MEASURED
            and self.value == 0
            and not self.source_relation
        ):
            raise ValueError(
                f"FABRICATED_ZERO_FORBIDDEN: {self.domain}.{self.metric_key} "
                "reports 0 with no source_relation; use UNKNOWN instead"
            )

    @property
    def is_backfill_candidate(self) -> bool:
        return self.state in (
            CoverageState.STALE,
            CoverageState.BACKFILL_REQUIRED,
            CoverageState.UNKNOWN,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain.value,
            "metric_key": self.metric_key,
            "state": self.state.value,
            "value": self.value,
            "source_relation": self.source_relation,
            "source_version": self.source_version,
            "generated_at": self.generated_at,
            "evidence_state": self.evidence_state.value,
            "notes": self.notes,
            "is_backfill_candidate": self.is_backfill_candidate,
        }


@dataclass(frozen=True)
class BackfillTask:
    """A deduplicated, prioritized backfill action."""

    domain: CoverageDomain
    metric_key: str
    priority: BackfillPriority
    description: str
    idempotency_key: str
    review_required: bool = True
    automatic_publication: bool = False
    knowledge_graph_mutation: bool = False

    def __post_init__(self) -> None:
        if self.automatic_publication:
            raise PermissionError("BACKFILL_TASK_AUTO_PUBLICATION_FORBIDDEN")
        if self.knowledge_graph_mutation:
            raise PermissionError("BACKFILL_TASK_KG_MUTATION_FORBIDDEN")

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain.value,
            "metric_key": self.metric_key,
            "priority": self.priority.value,
            "description": self.description,
            "idempotency_key": self.idempotency_key,
            "review_required": self.review_required,
            "automatic_publication": self.automatic_publication,
            "knowledge_graph_mutation": self.knowledge_graph_mutation,
        }


@dataclass
class CoverageMatrix:
    """Full multi-domain scientific coverage matrix."""

    schema_version: str = SCHEMA_VERSION
    generated_at: str = ""
    production_sha: str = ""
    db_identity: str = ""
    metrics: list[DomainMetric] = field(default_factory=list)
    backfill_tasks: list[BackfillTask] = field(default_factory=list)
    automatic_publication: bool = False
    knowledge_graph_mutation: bool = False
    fabricated_zero: bool = False

    def __post_init__(self) -> None:
        if self.automatic_publication:
            raise PermissionError("COVERAGE_MATRIX_AUTO_PUBLICATION_FORBIDDEN")
        if self.knowledge_graph_mutation:
            raise PermissionError("COVERAGE_MATRIX_KG_MUTATION_FORBIDDEN")
        if self.fabricated_zero:
            raise ValueError("COVERAGE_MATRIX_FABRICATED_ZERO_FORBIDDEN")

    def metrics_by_domain(self, domain: CoverageDomain) -> list[DomainMetric]:
        return [m for m in self.metrics if m.domain == domain]

    def metrics_by_state(self, state: CoverageState) -> list[DomainMetric]:
        return [m for m in self.metrics if m.state == state]

    def backfill_candidates(self) -> list[DomainMetric]:
        return [m for m in self.metrics if m.is_backfill_candidate]

    def coverage_summary(self) -> dict[str, Any]:
        state_counts: dict[str, int] = {}
        for s in CoverageState:
            count = sum(1 for m in self.metrics if m.state == s)
            if count:
                state_counts[s.value] = count
        domain_counts: dict[str, int] = {}
        for d in CoverageDomain:
            count = sum(1 for m in self.metrics if m.domain == d)
            if count:
                domain_counts[d.value] = count
        return {
            "total_metrics": len(self.metrics),
            "state_counts": state_counts,
            "domain_counts": domain_counts,
            "backfill_candidates": len(self.backfill_candidates()),
            "backfill_task_count": len(self.backfill_tasks),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "production_sha": self.production_sha,
            "db_identity": self.db_identity,
            "automatic_publication": self.automatic_publication,
            "knowledge_graph_mutation": self.knowledge_graph_mutation,
            "fabricated_zero": self.fabricated_zero,
            "summary": self.coverage_summary(),
            "metrics": [m.to_dict() for m in self.metrics],
            "backfill_tasks": [t.to_dict() for t in self.backfill_tasks],
        }


def _unknown(domain: CoverageDomain, key: str, notes: str = "") -> DomainMetric:
    """Build an UNKNOWN metric (DB unavailable)."""
    return DomainMetric(
        domain=domain,
        metric_key=key,
        state=CoverageState.UNKNOWN,
        value=None,
        notes=notes or "DB unavailable; measurement deferred to live run",
    )


def build_unavailable_matrix(*, generated_at: str = "", production_sha: str = "") -> CoverageMatrix:
    """Return a full matrix with all metrics in UNKNOWN state.

    Used when the production DB is not accessible. Every metric is explicitly
    UNKNOWN — never fabricated as zero. Callers can update individual metrics
    with live values after DB connection is established.
    """
    metrics: list[DomainMetric] = [
        # ---- Taxonomy -------------------------------------------------------
        _unknown(CoverageDomain.TAXONOMY, "release_version"),
        _unknown(CoverageDomain.TAXONOMY, "canonical_taxon_count"),
        _unknown(CoverageDomain.TAXONOMY, "accepted_names_count"),
        _unknown(CoverageDomain.TAXONOMY, "synonym_count"),
        _unknown(CoverageDomain.TAXONOMY, "hassler_release_ready"),
        # ---- Occurrences ----------------------------------------------------
        _unknown(CoverageDomain.OCCURRENCES, "total_records"),
        _unknown(CoverageDomain.OCCURRENCES, "canonical_bound_count"),
        _unknown(CoverageDomain.OCCURRENCES, "lat_lng_coverage_fraction"),
        _unknown(CoverageDomain.OCCURRENCES, "coordinate_uncertainty_covered"),
        _unknown(CoverageDomain.OCCURRENCES, "elevation_covered"),
        _unknown(CoverageDomain.OCCURRENCES, "stale_records"),
        _unknown(CoverageDomain.OCCURRENCES, "backfill_debt"),
        # ---- Images / Media -------------------------------------------------
        _unknown(CoverageDomain.IMAGES_MEDIA, "total_records"),
        _unknown(CoverageDomain.IMAGES_MEDIA, "canonical_bound_count"),
        _unknown(CoverageDomain.IMAGES_MEDIA, "license_attribution_covered"),
        _unknown(CoverageDomain.IMAGES_MEDIA, "broken_unusable_count"),
        _unknown(CoverageDomain.IMAGES_MEDIA, "herbarium_count"),
        _unknown(CoverageDomain.IMAGES_MEDIA, "field_count"),
        _unknown(CoverageDomain.IMAGES_MEDIA, "collection_count"),
        # ---- Traits ---------------------------------------------------------
        _unknown(CoverageDomain.TRAITS, "normalized_records"),
        _unknown(CoverageDomain.TRAITS, "taxon_bound_count"),
        _unknown(CoverageDomain.TRAITS, "cited_evidence_backed"),
        _unknown(CoverageDomain.TRAITS, "units_controlled_vocab_coverage"),
        _unknown(CoverageDomain.TRAITS, "unresolved_conflicting_count"),
        # ---- Literature -----------------------------------------------------
        _unknown(CoverageDomain.LITERATURE, "discovered_count"),
        _unknown(CoverageDomain.LITERATURE, "full_text_available"),
        _unknown(CoverageDomain.LITERATURE, "extracted_count"),
        _unknown(CoverageDomain.LITERATURE, "taxon_bound_count"),
        _unknown(CoverageDomain.LITERATURE, "methods_extracted"),
        _unknown(CoverageDomain.LITERATURE, "traits_measurements_extracted"),
        _unknown(CoverageDomain.LITERATURE, "kg_ready_materialized"),
        # ---- Pollination / Interactions -------------------------------------
        _unknown(CoverageDomain.POLLINATION, "orchid_bound_count"),
        _unknown(CoverageDomain.POLLINATION, "partner_resolved_count"),
        _unknown(CoverageDomain.POLLINATION, "evidence_method_covered"),
        _unknown(CoverageDomain.POLLINATION, "unresolved_ambiguous_count"),
        # ---- Mycorrhiza -----------------------------------------------------
        _unknown(CoverageDomain.MYCORRHIZA, "orchid_bound_count"),
        _unknown(CoverageDomain.MYCORRHIZA, "fungus_resolved_count"),
        _unknown(CoverageDomain.MYCORRHIZA, "its_sequence_accession_evidence"),
        _unknown(CoverageDomain.MYCORRHIZA, "unresolved_fungal_identity_count"),
        _unknown(CoverageDomain.MYCORRHIZA, "method_tissue_life_stage_covered"),
        # ---- Habitat --------------------------------------------------------
        _unknown(CoverageDomain.HABITAT, "habitat_elevation_env_count"),
        _unknown(CoverageDomain.HABITAT, "climate_data_covered"),
        _unknown(CoverageDomain.HABITAT, "conservation_status_covered"),
        # ---- Knowledge Graph ------------------------------------------------
        _unknown(CoverageDomain.KNOWLEDGE_GRAPH, "domain_readiness"),
        _unknown(CoverageDomain.KNOWLEDGE_GRAPH, "source_vs_materialized_coverage"),
        _unknown(CoverageDomain.KNOWLEDGE_GRAPH, "unresolved_link_queue_size"),
        # ---- Molecular / Sequence -------------------------------------------
        _unknown(CoverageDomain.MOLECULAR_SEQUENCE, "sequence_record_count"),
        _unknown(CoverageDomain.MOLECULAR_SEQUENCE, "taxon_bound_count"),
        _unknown(CoverageDomain.MOLECULAR_SEQUENCE, "accession_linked"),
    ]

    return CoverageMatrix(
        generated_at=generated_at,
        production_sha=production_sha,
        metrics=metrics,
    )


def compute_backfill_priority(matrix: CoverageMatrix) -> list[BackfillTask]:
    """Derive a deduplicated, prioritized backfill list from a measured matrix.

    Critical: domains with zero measured records in a non-UNKNOWN/NOT_APPLICABLE
    state (i.e., the measurement ran and found nothing or backfill_required).
    High: stale or backfill_required metrics with source_relation known.
    Medium: unknown metrics where a source_relation is available.
    Low: unknown metrics without a source_relation yet.
    """
    seen: set[str] = set()
    tasks: list[BackfillTask] = []

    for m in matrix.metrics:
        if not m.is_backfill_candidate:
            continue
        key = f"{m.domain.value}:{m.metric_key}"
        if key in seen:
            continue
        seen.add(key)

        if m.state == CoverageState.BACKFILL_REQUIRED:
            priority = BackfillPriority.CRITICAL
        elif m.state == CoverageState.STALE:
            priority = BackfillPriority.HIGH
        elif m.state == CoverageState.UNKNOWN and m.source_relation:
            priority = BackfillPriority.MEDIUM
        else:
            priority = BackfillPriority.LOW

        tasks.append(BackfillTask(
            domain=m.domain,
            metric_key=m.metric_key,
            priority=priority,
            description=(
                f"{m.domain.value}.{m.metric_key}: state={m.state.value}"
                + (f" source={m.source_relation}" if m.source_relation else "")
            ),
            idempotency_key=key,
        ))

    tasks.sort(key=lambda t: list(BackfillPriority).index(t.priority))
    return tasks


def classify_source_precedence(
    canonical_value: float | None,
    external_value: float | None,
    *,
    canonical_reviewed: bool,
) -> tuple[float | None, str]:
    """Return (chosen_value, rationale) per source-precedence rules.

    Canonical reviewed data outranks external discovery.
    External may augment but never silently replace canonical evidence.
    """
    if canonical_reviewed and canonical_value is not None:
        return canonical_value, "canonical_db_read_through"
    if canonical_value is not None:
        return canonical_value, "canonical_unreviewed"
    if external_value is not None:
        return external_value, "external_discovery_fallback"
    return None, "unavailable"


def serialize_matrix_as_json(matrix: CoverageMatrix) -> str:
    return json.dumps(matrix.to_dict(), indent=2, sort_keys=True)

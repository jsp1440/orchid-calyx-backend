"""Taxonomy readiness audit — Approved Task Priority 10.

Inspects taxonomy storage, staging, smoke certification, crosswalk, impact,
promotion blockers, and rollback readiness across the Calyx taxonomy pipeline.

Status vocabulary:
  READY        — implemented, tested, and integrated; gate is functional
  GAP          — described in acceptance criteria but not yet closed
  BLOCKED      — requires external dependency (NO-API mode, unprovisioned infra)
  OWNER_GATED  — requires explicit owner authorization before proceeding

No live-model spending. No taxonomy activation. No production KG mutation.
Read-only static audit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "taxonomy-readiness-audit/v1"
AUDIT_DATE = "2026-09-09"


class ReadinessStatus:
    READY = "READY"
    GAP = "GAP"
    BLOCKED = "BLOCKED"
    OWNER_GATED = "OWNER_GATED"


@dataclass(frozen=True)
class ReadinessCriterion:
    """One measurable criterion in the taxonomy readiness audit."""

    criterion_id: str
    area: str        # storage | staging | smoke | crosswalk | impact | promotion | rollback
    title: str
    status: str      # ReadinessStatus constant
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
# Canonical readiness criteria
# ---------------------------------------------------------------------------

READINESS_CRITERIA: tuple[ReadinessCriterion, ...] = (

    # ------------------------------------------------------------------ STORAGE
    ReadinessCriterion(
        criterion_id="storage_csv_tsv_validation",
        area="storage",
        title="CSV/TSV taxonomy file validation (encoding, delimiter, row loading)",
        status=ReadinessStatus.READY,
        authoritative_module="runtime.taxonomy_preflight.validate",
        evidence=(
            "validate() loads candidate CSV/TSV, detects delimiter and encoding, "
            "computes SHA-256 source digest, enforces Policy.minimum_rows; "
            "VALIDATOR_VERSION=0.3.0; tested in test suite"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ReadinessCriterion(
        criterion_id="storage_legacy_world_orchids",
        area="storage",
        title="Legacy World Orchids / World Plants pipe-delimited export loader",
        status=ReadinessStatus.READY,
        authoritative_module="runtime.taxonomy_preflight.load_csv",
        evidence=(
            "LEGACY_WORLD_PLANTS_COLUMNS tuple; _legacy_columns() auto-expands narrow rows; "
            "_looks_like_header() distinguishes headered vs headerless exports; "
            "HASSLER_RANKS crosswalk (F/SF/T/ST/G/S/SS/V/FM)"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ReadinessCriterion(
        criterion_id="storage_sha256_identity",
        area="storage",
        title="SHA-256 source-file identity digest (tamper detection)",
        status=ReadinessStatus.READY,
        authoritative_module="runtime.taxonomy_preflight.sha256_file",
        evidence=(
            "sha256_file() hashes candidate and baseline; run_id derived from digest pair; "
            "governance bundle stores per-artifact digests for reproducibility verification"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ STAGING
    ReadinessCriterion(
        criterion_id="staging_intake_service",
        area="staging",
        title="TaxonomyReleaseIntakeService — governed staging review queue",
        status=ReadinessStatus.READY,
        authoritative_module="runtime.taxonomy_release_intake_v2.TaxonomyReleaseIntakeService",
        evidence=(
            "INTAKE_SCHEMA_VERSION=1.5.0; ingest() preserves immutable source identity, "
            "normalizes Hassler and generic files, creates read-only review queue; "
            "decision: REVIEW_ONLY | HOLD; no taxonomy activation path"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ReadinessCriterion(
        criterion_id="staging_release_identity",
        area="staging",
        title="ReleaseIdentity — immutable source-file fingerprint for staged releases",
        status=ReadinessStatus.READY,
        authoritative_module="runtime.taxonomy_release_intake_v2.ReleaseIdentity",
        evidence=(
            "ReleaseIdentity frozen dataclass: release_id (RELEASE_ID_RE sanitized), "
            "source_sha256, row_count, intake_schema_version; immutable from intake time"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ReadinessCriterion(
        criterion_id="staging_projection_batching",
        area="staging",
        title="Bounded batch staging projections (no unbounded in-memory loads)",
        status=ReadinessStatus.READY,
        authoritative_module="runtime.taxonomy_release_intake_v2.TaxonomyReleaseIntakeService",
        evidence=(
            "project_staging_artifacts() uses itertools.islice for bounded batches; "
            "never loads full dataset into memory; prevents OOM on large World Orchids exports"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ SMOKE
    ReadinessCriterion(
        criterion_id="smoke_preflight_report",
        area="smoke",
        title="Preflight smoke report — finding-level evidence record (WARN/ERROR/INFO)",
        status=ReadinessStatus.READY,
        authoritative_module="runtime.taxonomy_preflight.Report",
        evidence=(
            "Report dataclass: report_schema_version, run_id, findings (list[Finding]), "
            "compare_stats, policy_hash; Finding.level ∈ {WARN, ERROR, INFO}; "
            "finding_sample_limit caps noise"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ReadinessCriterion(
        criterion_id="smoke_governance_enforcement",
        area="smoke",
        title="Governance enforcement — null ratio, identity columns, schema contract",
        status=ReadinessStatus.READY,
        authoritative_module="runtime.taxonomy_preflight_governance.enforce_governance",
        evidence=(
            "enforce_governance() checks overall null ratio, validates report_schema_version, "
            "enforces GovernancePolicy.maximum_overall_null_ratio; returns list[str] of violations"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ReadinessCriterion(
        criterion_id="smoke_attestation_gates",
        area="smoke",
        title="Typed attestation gates (CI, real-dataset, billing-credit, budget-alerts, architecture-review)",
        status=ReadinessStatus.READY,
        authoritative_module="runtime.taxonomy_preflight_attestations.load_and_evaluate",
        evidence=(
            "load_and_evaluate() validates 5 gates from signed attestation file; "
            "evidence_digest (SHA-256 of attestation payload); "
            "ReadinessDecision.decision ∈ {READY_FOR_REVIEW, HOLD}"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ CROSSWALK
    ReadinessCriterion(
        criterion_id="crosswalk_hassler_ranks",
        area="crosswalk",
        title="Hassler/WorldOrchids rank-code crosswalk (F/SF/T/ST/G/S/SS/V/FM)",
        status=ReadinessStatus.READY,
        authoritative_module="runtime.taxonomy_release_intake_v2.HASSLER_RANKS",
        evidence=(
            "HASSLER_RANKS maps 9 single/double-letter codes to canonical rank names; "
            "HASSLER_SPECIES_CODES frozenset distinguishes species-level rows; "
            "HASSLER_SPECIES_NAME_RE validates binomial orthography"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ReadinessCriterion(
        criterion_id="crosswalk_binomial_regex",
        area="crosswalk",
        title="Binomial name regex validation (BINOMIAL_RE, hybrid × prefix support)",
        status=ReadinessStatus.READY,
        authoritative_module="runtime.taxonomy_preflight.BINOMIAL_RE",
        evidence=(
            "BINOMIAL_RE = r'^[A-Z][A-Za-z-]+\\s+(?:×\\s*)?[a-z][a-z-]+'; "
            "handles hybrid × prefix; normalize() strips whitespace/case for matching; "
            "malformed-name detection via _is_malformed_hassler_name()"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ReadinessCriterion(
        criterion_id="crosswalk_synonym_normalization",
        area="crosswalk",
        title="Synonym marker normalization (SYNONYM_MARKER_RE)",
        status=ReadinessStatus.READY,
        authoritative_module="runtime.taxonomy_release_intake_v2.SYNONYM_MARKER_RE",
        evidence=(
            "SYNONYM_MARKER_RE strips '= ' synonym markers from legacy pipe-delimited rows; "
            "synonym rows preserved in staging but distinguished from accepted taxa; "
            "no automatic synonym promotion"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ IMPACT
    ReadinessCriterion(
        criterion_id="impact_removed_ratio",
        area="impact",
        title="Removed-row impact gate (maximum_removed_ratio ≤ 5%)",
        status=ReadinessStatus.READY,
        authoritative_module="runtime.taxonomy_preflight.Policy.maximum_removed_ratio",
        evidence=(
            "Policy.maximum_removed_ratio=0.05 default; compare_rows() computes removals; "
            "Report.findings includes WARN/ERROR for ratio violations; "
            "configurable via JSON policy file"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ReadinessCriterion(
        criterion_id="impact_changed_ratio",
        area="impact",
        title="Changed-row impact gate (maximum_changed_ratio ≤ 25%)",
        status=ReadinessStatus.READY,
        authoritative_module="runtime.taxonomy_preflight.Policy.maximum_changed_ratio",
        evidence=(
            "Policy.maximum_changed_ratio=0.25 default; compare_rows() diffs candidate vs "
            "baseline on canonical_row(); large-batch changes trigger WARN findings"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ReadinessCriterion(
        criterion_id="impact_duplicate_key",
        area="impact",
        title="Duplicate taxon-key detection (maximum_duplicate_key_ratio ≤ 1%)",
        status=ReadinessStatus.READY,
        authoritative_module="runtime.taxonomy_preflight.Policy.maximum_duplicate_key_ratio",
        evidence=(
            "taxon_key() normalizes scientific_name|taxon_id composite; "
            "collections.Counter detects duplicates; Policy.maximum_duplicate_key_ratio=0.01; "
            "duplicate ERROR findings block READY_FOR_REVIEW decision"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ReadinessCriterion(
        criterion_id="impact_identity_column",
        area="impact",
        title="Identity column presence check (taxon_id or scientific_name required)",
        status=ReadinessStatus.READY,
        authoritative_module="runtime.taxonomy_preflight._has_identity_columns",
        evidence=(
            "_has_identity_columns() checks for HEADER_TOKENS intersection; "
            "missing identity columns produce ERROR finding; "
            "maximum_missing_identity_ratio=0.001 enforced at row level"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ PROMOTION BLOCKERS
    ReadinessCriterion(
        criterion_id="promotion_readiness_gate",
        area="promotion",
        title="Preflight readiness gate (READY_FOR_REVIEW / HOLD decision)",
        status=ReadinessStatus.READY,
        authoritative_module="runtime.taxonomy_preflight_readiness.evaluate",
        evidence=(
            "evaluate() aggregates 5 attestation gates into READY_FOR_REVIEW | HOLD; "
            "READINESS_VERSION=0.2.0; decision is advisory — promotion still OWNER_GATED"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ReadinessCriterion(
        criterion_id="promotion_release_gate",
        area="promotion",
        title="Release gate — operator review reference, bundle integrity, safety flags",
        status=ReadinessStatus.READY,
        authoritative_module="runtime.taxonomy_preflight_release_gate.plan_release",
        evidence=(
            "ReleaseGatePolicy: require_review_reference=True, reject_symlinks=True, "
            "maximum_bundle_bytes=25 MB, require_safety_flags=True, require_policy_hashes=True; "
            "output_lock() prevents concurrent bundle writes"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ReadinessCriterion(
        criterion_id="promotion_activation_blocked",
        area="promotion",
        title="Autonomous taxonomy activation permanently blocked",
        status=ReadinessStatus.OWNER_GATED,
        authoritative_module="runtime.taxonomy_preflight_readiness.ReadinessDecision",
        evidence=(
            "ReadinessDecision.taxonomy_publication_authorized=False by default; "
            "database_mutation_authorized=False by default; "
            "TaxonomyReleaseIntakeService decision='REVIEW_ONLY | HOLD' — never 'ACTIVATE'"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action="Owner must explicitly set taxonomy_publication_authorized and database_mutation_authorized",
    ),

    # ------------------------------------------------------------------ ROLLBACK
    ReadinessCriterion(
        criterion_id="rollback_bundle_verification",
        area="rollback",
        title="Governance bundle verification — reproducibility of staged bundles",
        status=ReadinessStatus.READY,
        authoritative_module="runtime.taxonomy_preflight_governance.verify_bundle",
        evidence=(
            "verify_bundle() re-hashes all bundle artifacts against stored digests; "
            "verify_release_bundle() adds release-gate marker checks; "
            "verify_reproducibility() cross-checks report_id across multiple bundles"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ReadinessCriterion(
        criterion_id="rollback_atomic_writes",
        area="rollback",
        title="Atomic file writes — no partial-update state corruption",
        status=ReadinessStatus.READY,
        authoritative_module="runtime.taxonomy_preflight.atomic_write_text",
        evidence=(
            "atomic_write_text() uses tempfile.mkstemp + os.fsync + os.replace; "
            "all JSON bundle artifacts written atomically; "
            "partial writes leave original artifact intact for rollback"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ReadinessCriterion(
        criterion_id="rollback_production_authorization",
        area="rollback",
        title="Production migration authorization for rollback path",
        status=ReadinessStatus.OWNER_GATED,
        authoritative_module="runtime.taxonomy_preflight_readiness.ReadinessDecision",
        evidence=(
            "ReadinessDecision.production_migration_authorized=False by default; "
            "azure_provisioning_authorized=False by default; "
            "no autonomous rollback path in production environment"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=(
            "Owner must explicitly set production_migration_authorized "
            "and azure_provisioning_authorized for any rollback execution"
        ),
    ),
)


# ---------------------------------------------------------------------------
# Audit builders
# ---------------------------------------------------------------------------

@dataclass
class TaxonomyReadinessAudit:
    """Machine-readable taxonomy readiness audit result."""

    schema_version: str = SCHEMA_VERSION
    audit_date: str = AUDIT_DATE
    no_auto_publication: bool = True
    no_production_mutation: bool = True
    criteria: list[ReadinessCriterion] = field(default_factory=list)

    def by_status(self, status: str) -> list[ReadinessCriterion]:
        return [c for c in self.criteria if c.status == status]

    def by_area(self, area: str) -> list[ReadinessCriterion]:
        return [c for c in self.criteria if c.area == area]

    def ready_count(self) -> int:
        return len(self.by_status(ReadinessStatus.READY))

    def gap_count(self) -> int:
        return len(self.by_status(ReadinessStatus.GAP))

    def blocked_count(self) -> int:
        return len(self.by_status(ReadinessStatus.BLOCKED))

    def owner_gated_count(self) -> int:
        return len(self.by_status(ReadinessStatus.OWNER_GATED))

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


def get_taxonomy_readiness_audit() -> TaxonomyReadinessAudit:
    """Return the current taxonomy readiness audit. Pure function — no external calls."""
    return TaxonomyReadinessAudit(criteria=list(READINESS_CRITERIA))


def get_criteria_by_status(status: str) -> list[ReadinessCriterion]:
    """Filter criteria by status."""
    return [c for c in READINESS_CRITERIA if c.status == status]


def get_criteria_by_area(area: str) -> list[ReadinessCriterion]:
    """Filter criteria by area."""
    return [c for c in READINESS_CRITERIA if c.area == area]


def get_gaps() -> list[ReadinessCriterion]:
    """Return criteria with GAP status."""
    return get_criteria_by_status(ReadinessStatus.GAP)


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
        for c in READINESS_CRITERIA
        if c.next_action
    ]

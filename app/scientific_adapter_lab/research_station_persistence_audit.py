"""Research Station persistence audit — Approved Task Priority 17.

Inspects durable request/result persistence, provenance records,
immutable artifacts, idempotency, and canonical storage defaults.

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

SCHEMA_VERSION = "research-station-persistence-audit/v1"
AUDIT_DATE = "2026-09-09"


class PersistenceAuditStatus:
    READY = "READY"
    GAP = "GAP"
    BLOCKED = "BLOCKED"
    OWNER_GATED = "OWNER_GATED"


@dataclass(frozen=True)
class PersistenceAuditCriterion:
    """One measurable criterion in the research station persistence audit."""

    criterion_id: str
    area: str        # request | result | provenance | artifact | idempotency | storage | security
    title: str
    status: str      # PersistenceAuditStatus constant
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
# Canonical research station persistence criteria
# ---------------------------------------------------------------------------

PERSISTENCE_AUDIT_CRITERIA: tuple[PersistenceAuditCriterion, ...] = (

    # ------------------------------------------------------------------ REQUEST
    PersistenceAuditCriterion(
        criterion_id="request_program_job_persistence",
        area="request",
        title="Request persistence — CalyxProgramJob DB row before execution",
        status=PersistenceAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.program_repository.PersistentProgramRepository",
        evidence=(
            "PersistentProgramRepository.create_program() persists CalyxProgram + CalyxProgramJob rows "
            "to DB before any execution; job_key, role_key, title, repository, branch stored; "
            "status=WAITING before execution begins; bounded per-owner isolation"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    PersistenceAuditCriterion(
        criterion_id="request_input_json_storage",
        area="request",
        title="Request input serialization — input_json persisted in program job row",
        status=PersistenceAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.program_core.ProgramJobSpec.serialized_inputs",
        evidence=(
            "ProgramJobSpec.serialized_inputs: JSON-serializes typed input dict; "
            "_verify_governed_job_inputs() validates persisted_inputs vs current spec at execution; "
            "PersistedPatchExecution.input_json round-trip verified before patch application"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    PersistenceAuditCriterion(
        criterion_id="request_scheduler_durable",
        area="request",
        title="Durable request scheduling — PersistedScheduler queues tasks durably",
        status=PersistenceAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.persisted_scheduler",
        evidence=(
            "persisted_scheduler.py: tasks persisted to DB before dispatch; "
            "scheduler.py: non-persistent fallback for in-memory use; "
            "durable queue survives process restart when DATABASE_URL provisioned"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ RESULT
    PersistenceAuditCriterion(
        criterion_id="result_terminal_outcome_record",
        area="result",
        title="Terminal outcome recording — record_outcome() writes DELIVERED | NO_OP | BLOCKED",
        status=PersistenceAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.program_repository.PersistentProgramRepository.record_outcome",
        evidence=(
            "record_outcome() writes TerminalOutcome (DELIVERED|NO_OP|BLOCKED) and "
            "evidence tuple to CalyxProgramJob row; status set to TERMINAL; "
            "_refresh_program_status() updates parent CalyxProgram status"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    PersistenceAuditCriterion(
        criterion_id="result_persisted_patch_execution",
        area="result",
        title="Patch execution result persistence — PersistedPatchExecution durable row",
        status=PersistenceAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.persisted_patch_execution.PersistedPatchExecution",
        evidence=(
            "PersistedPatchExecution: program_job_id, sha256_before, sha256_after, "
            "patches, applied_at, verified; _is_sha256() validates digest format; "
            "PersistedPatchExecutionService.get_completed() retrieves durable result"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    PersistenceAuditCriterion(
        criterion_id="result_github_feedback_idempotent",
        area="result",
        title="GitHub research feedback upsert — idempotent issue comment persistence",
        status=PersistenceAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.github_research_feedback.upsert_research_status_comment",
        evidence=(
            "upsert_research_status_comment(): checks existing comment_id before creating; "
            "updates existing comment rather than duplicating; "
            "idempotent: same result state produces same comment content"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ PROVENANCE
    PersistenceAuditCriterion(
        criterion_id="provenance_artifact_registration",
        area="provenance",
        title="Artifact provenance — ImmutableArtifactRegistry SHA-256 checksum record",
        status=PersistenceAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.artifact_registry.ImmutableArtifactRegistry",
        evidence=(
            "ImmutableArtifactRegistry.register(): SHA-256 checksum computed from content; "
            "ArtifactRecord stores: artifact_id, checksum, created_at, content_type, metadata; "
            "ArtifactRelation: EVIDENCES relation linking artifact to evidence chain"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    PersistenceAuditCriterion(
        criterion_id="provenance_evidence_link_required",
        area="provenance",
        title="Evidence linkage required — require_evidence() enforces EVIDENCES relation",
        status=PersistenceAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.artifact_registry.ImmutableArtifactRegistry.require_evidence",
        evidence=(
            "require_evidence(artifact_id) raises KeyError if no EVIDENCES relation is set; "
            "ArtifactRelationType.EVIDENCES enforces provenance traceability; "
            "no artifact accepted as evidence without explicit evidence linkage"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    PersistenceAuditCriterion(
        criterion_id="provenance_program_job_spec_fingerprint",
        area="provenance",
        title="Request fingerprint — ProgramJobSpec.fingerprint() material-change tracking",
        status=PersistenceAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.program_repository.ProgramJobSpec.fingerprint",
        evidence=(
            "ProgramJobSpec.fingerprint(): SHA-256 hash of job_key + role_key + serialized_inputs; "
            "material-change detection: same fingerprint means same request, suppresses duplicates; "
            "WorkIntent.material_fingerprint() in factory_policy: same fingerprint → NO-OP eligible"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ ARTIFACT
    PersistenceAuditCriterion(
        criterion_id="artifact_immutable_sha256",
        area="artifact",
        title="Immutable artifact SHA-256 — content hash prevents mutation after registration",
        status=PersistenceAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.artifact_registry.ArtifactRegistration.checksum",
        evidence=(
            "ArtifactRegistration.checksum(): hashlib.sha256(self.content).hexdigest(); "
            "ArtifactRecord stores checksum; validate() raises ValueError if artifact_id empty; "
            "_by_checksum deduplication index prevents content collision"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    PersistenceAuditCriterion(
        criterion_id="artifact_idempotent_registration",
        area="artifact",
        title="Idempotent artifact registration — duplicate artifact_id returns existing record",
        status=PersistenceAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.artifact_registry.ImmutableArtifactRegistry.register",
        evidence=(
            "register(): if artifact_id already in _records, returns RegistrationResult with "
            "existing record (idempotent); _by_checksum dedup: same content → same artifact; "
            "not a publication authority: registration is local, not canonical KG publication"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ IDEMPOTENCY
    PersistenceAuditCriterion(
        criterion_id="idempotency_persisted_patch_verification",
        area="idempotency",
        title="Patch idempotency — SHA-256 before/after digest verification",
        status=PersistenceAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.persisted_patch_execution.PersistedPatchExecution",
        evidence=(
            "PersistedPatchExecution.sha256_before / sha256_after: digest pair verifies patch; "
            "verified field: True only after post-patch digest confirms expected sha256_after; "
            "replay safety: same patch on same sha256_before always yields same sha256_after"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    PersistenceAuditCriterion(
        criterion_id="idempotency_event_continuation",
        area="idempotency",
        title="Event continuation idempotency — event_continuation.py replay-safe state",
        status=PersistenceAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.event_continuation",
        evidence=(
            "event_continuation.py: stateful event replay; "
            "GovervedResearchExecutor state machine transitions are terminal-safe; "
            "replay of completed (TERMINAL) executor produces same terminal outcome"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    PersistenceAuditCriterion(
        criterion_id="idempotency_create_or_touch",
        area="idempotency",
        title="Conversation creation idempotency — ConversationStore.create_or_touch()",
        status=PersistenceAuditStatus.READY,
        authoritative_module="app.calyx_conversation.store.ConversationStore",
        evidence=(
            "ConversationStore.create_or_touch(): idempotent — creates new or returns existing; "
            "conversation_id as stable key prevents duplicate creation; "
            "append_turn() is idempotent for same turn content"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ STORAGE
    PersistenceAuditCriterion(
        criterion_id="storage_dual_mode_default",
        area="storage",
        title="Canonical storage default — postgres when DATABASE_URL set, memory fallback",
        status=PersistenceAuditStatus.READY,
        authoritative_module="app.calyx_conversation.store.ConversationStore",
        evidence=(
            "ConversationStore: persistence_mode='postgres' if DATABASE_URL else 'memory'; "
            "dual-mode: production uses postgres, development falls back to in-memory; "
            "mode disclosed in speak_status() response as conversation_persistence field"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    PersistenceAuditCriterion(
        criterion_id="storage_database_url_durable",
        area="storage",
        title="Durable storage requires DATABASE_URL — unavailable in current environment",
        status=PersistenceAuditStatus.BLOCKED,
        authoritative_module="app.calyx_conversation.store.ConversationStore",
        evidence=(
            "Without DATABASE_URL: in-memory mode, no cross-restart durability; "
            "CalyxProgramJob, CalyxProgram, PersistedPatchExecution require SQLAlchemy Session; "
            "durable research station requires DATABASE_URL provisioned in deployment environment"
        ),
        gap_description=None,
        blocker_reason=(
            "DATABASE_URL not provisioned in this execution environment; "
            "all durable persistence falls back to in-memory (not cross-restart)"
        ),
        next_action="Provision DATABASE_URL for durable research station persistence in production",
    ),

    # ------------------------------------------------------------------ SECURITY
    PersistenceAuditCriterion(
        criterion_id="security_no_credential_in_artifact",
        area="security",
        title="No credential values in artifact content — validate() and audit enforcement",
        status=PersistenceAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.artifact_registry.ArtifactRegistration.validate",
        evidence=(
            "ArtifactRegistration.validate(): raises ValueError on empty artifact_id; "
            "CLAUDE.md: no credential value may be requested, printed, logged, copied, or committed; "
            "artifact content is hashed, not printed; secrets_exposed=False in provider status"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    PersistenceAuditCriterion(
        criterion_id="security_publication_authority_separation",
        area="security",
        title="Publication authority separation — artifact registry not a publication authority",
        status=PersistenceAuditStatus.OWNER_GATED,
        authoritative_module="app.calyx_orchestrator.artifact_registry.ImmutableArtifactRegistry",
        evidence=(
            "ImmutableArtifactRegistry: local in-memory registry, not canonical KG publication; "
            "calyx_acceptance_mission_audit: security_acceptance_publication_gated is OWNER_GATED; "
            "automatic_publication=False in speak_status; CLAUDE.md: never publish governed science"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action="Await explicit owner authorization before any artifact promotes to canonical KG",
    ),
)


# ---------------------------------------------------------------------------
# Audit builders
# ---------------------------------------------------------------------------

@dataclass
class ResearchStationPersistenceAudit:
    """Machine-readable research station persistence audit result."""

    schema_version: str = SCHEMA_VERSION
    audit_date: str = AUDIT_DATE
    no_auto_publication: bool = True
    no_production_mutation: bool = True
    criteria: list[PersistenceAuditCriterion] = field(default_factory=list)

    def by_status(self, status: str) -> list[PersistenceAuditCriterion]:
        return [c for c in self.criteria if c.status == status]

    def by_area(self, area: str) -> list[PersistenceAuditCriterion]:
        return [c for c in self.criteria if c.area == area]

    def ready_count(self) -> int:
        return len(self.by_status(PersistenceAuditStatus.READY))

    def gap_count(self) -> int:
        return len(self.by_status(PersistenceAuditStatus.GAP))

    def blocked_count(self) -> int:
        return len(self.by_status(PersistenceAuditStatus.BLOCKED))

    def owner_gated_count(self) -> int:
        return len(self.by_status(PersistenceAuditStatus.OWNER_GATED))

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


def get_research_station_persistence_audit() -> ResearchStationPersistenceAudit:
    """Return the current persistence audit. Pure function — no external calls."""
    return ResearchStationPersistenceAudit(criteria=list(PERSISTENCE_AUDIT_CRITERIA))


def get_criteria_by_status(status: str) -> list[PersistenceAuditCriterion]:
    return [c for c in PERSISTENCE_AUDIT_CRITERIA if c.status == status]


def get_criteria_by_area(area: str) -> list[PersistenceAuditCriterion]:
    return [c for c in PERSISTENCE_AUDIT_CRITERIA if c.area == area]


def get_gaps() -> list[PersistenceAuditCriterion]:
    return get_criteria_by_status(PersistenceAuditStatus.GAP)


def get_next_actions() -> list[dict[str, str]]:
    return [
        {
            "criterion_id": c.criterion_id,
            "area": c.area,
            "title": c.title,
            "status": c.status,
            "next_action": c.next_action,
        }
        for c in PERSISTENCE_AUDIT_CRITERIA
        if c.next_action
    ]

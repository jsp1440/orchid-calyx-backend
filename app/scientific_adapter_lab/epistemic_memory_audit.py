"""Epistemic memory audit — Approved Task Priority 22.

Inspects source/inference/memory distinctions, contradiction handling,
confidence, uncertainty, and provenance.

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

SCHEMA_VERSION = "epistemic-memory-audit/v1"
AUDIT_DATE = "2026-09-09"


class EpistemicAuditStatus:
    READY = "READY"
    GAP = "GAP"
    BLOCKED = "BLOCKED"
    OWNER_GATED = "OWNER_GATED"


@dataclass(frozen=True)
class EpistemicAuditCriterion:
    """One measurable criterion in the epistemic memory audit."""

    criterion_id: str
    area: str        # distinctions | contradictions | confidence | uncertainty | provenance | security | memory
    title: str
    status: str      # EpistemicAuditStatus constant
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
# Canonical epistemic memory criteria
# ---------------------------------------------------------------------------

EPISTEMIC_AUDIT_CRITERIA: tuple[EpistemicAuditCriterion, ...] = (

    # ------------------------------------------------------------------ DISTINCTIONS
    EpistemicAuditCriterion(
        criterion_id="distinctions_evidence_state_enum",
        area="distinctions",
        title="EvidenceState enum — AVAILABLE | UNAVAILABLE | GAP | CONFLICT distinctions",
        status=EpistemicAuditStatus.READY,
        authoritative_module="app.calyx_conversation.teaching_synthesis.EvidenceState",
        evidence=(
            "EvidenceState: AVAILABLE | UNAVAILABLE | GAP | CONFLICT; "
            "each domain claim carries evidence_state field; "
            "synthesis contract: source vs inference vs unavailable are distinguished, not collapsed"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    EpistemicAuditCriterion(
        criterion_id="distinctions_source_trust_class",
        area="distinctions",
        title="Source trust class distinction — TrustClass (authoritative | peer_reviewed | community | unverified)",
        status=EpistemicAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.knowledge_source_registry.TrustClass",
        evidence=(
            "TrustClass: authoritative | peer_reviewed | community | unverified; "
            "KnowledgeSource carries trust_class per source; "
            "trust class is distinct from source state — a stale source can still be authoritative in kind"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    EpistemicAuditCriterion(
        criterion_id="distinctions_evidence_provenance_survival",
        area="distinctions",
        title="Evidence provenance survival — no claim may lose its source through synthesis",
        status=EpistemicAuditStatus.READY,
        authoritative_module="app.calyx_conversation.teaching_synthesis",
        evidence=(
            "teaching_synthesis.py contract: 'Evidence provenance must survive from input to output; "
            "no claim may lose its source.'; EvidenceClaim.provenance field; "
            "TeachingSynthesisV1.evidence_provenance list in output"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    EpistemicAuditCriterion(
        criterion_id="distinctions_domain_evidence_claim",
        area="distinctions",
        title="Domain evidence claim model — DomainEvidenceClaim with evidence_state per claim",
        status=EpistemicAuditStatus.READY,
        authoritative_module="app.calyx_conversation.teaching_synthesis.DomainEvidenceClaim",
        evidence=(
            "DomainEvidenceClaim: provenance-anchored claim with evidence_state, source_ids; "
            "TeachingNarrativeSegment: claim-first with evidence_state; "
            "every claim is typed — no floating assertions without evidence_state"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ CONTRADICTIONS
    EpistemicAuditCriterion(
        criterion_id="contradictions_not_resolved",
        area="contradictions",
        title="Contradictions preserved — not resolved into support in synthesis",
        status=EpistemicAuditStatus.READY,
        authoritative_module="app.calyx_conversation.teaching_synthesis",
        evidence=(
            "teaching_synthesis.py contract: 'Contradictions remain contradictions; "
            "they must not be resolved into support.'; "
            "EvidenceState.CONFLICT: synthesized when conflicting claims present; "
            "contradictions list in TeachingSynthesisV1 output"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    EpistemicAuditCriterion(
        criterion_id="contradictions_evidence_state_conflict",
        area="contradictions",
        title="Contradiction evidence state — EvidenceState.CONFLICT for conflicting claims",
        status=EpistemicAuditStatus.READY,
        authoritative_module="app.calyx_conversation.teaching_synthesis.EvidenceState",
        evidence=(
            "EvidenceState.CONFLICT: assigned when conflicting sources provide opposing claims; "
            "build_teaching_synthesis(): evidence_state=EvidenceState.CONFLICT for domains; "
            "KnowledgeSource.SourceState.CONTRADICTORY: conflict at registry level"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    EpistemicAuditCriterion(
        criterion_id="contradictions_kg_source_state",
        area="contradictions",
        title="KG contradiction state — SourceState.CONTRADICTORY in knowledge source registry",
        status=EpistemicAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.knowledge_source_registry.SourceState",
        evidence=(
            "SourceState.CONTRADICTORY: explicit source-level contradiction state; "
            "registry.query() can filter by SourceState.CONTRADICTORY; "
            "source-level contradiction tracked separately from claim-level CONFLICT"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ CONFIDENCE
    EpistemicAuditCriterion(
        criterion_id="confidence_vision_matrix_cap",
        area="confidence",
        title="Vision confidence cap — confidence > 0.98 fails validate() (overconfidence guard)",
        status=EpistemicAuditStatus.READY,
        authoritative_module="app.scientific_adapter_lab.vision_matrix_glossary_inventory",
        evidence=(
            "Vision matrix guard: 'confidence capped — any observation.confidence > 0.98 fails validate()'; "
            "overconfidence guard prevents spuriously certain detection claims; "
            "epistemic humility enforced at model layer"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    EpistemicAuditCriterion(
        criterion_id="confidence_success_rate_semantics",
        area="confidence",
        title="Empirical confidence semantics — historical_observation_not_predictive_certainty",
        status=EpistemicAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.capability_memory._empirical_stats",
        evidence=(
            "_empirical_stats(): success_rate_semantics: 'historical_observation_not_predictive_certainty'; "
            "descriptive_success_rate is observational, not a confidence bound; "
            "empirical metrics do not expand authority regardless of rate"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ UNCERTAINTY
    EpistemicAuditCriterion(
        criterion_id="uncertainty_knowledge_gaps_list",
        area="uncertainty",
        title="Knowledge gaps list — TeachingSynthesisV1.knowledge_gaps disclosed per domain",
        status=EpistemicAuditStatus.READY,
        authoritative_module="app.calyx_conversation.teaching_synthesis.TeachingSynthesisV1",
        evidence=(
            "TeachingSynthesisV1.knowledge_gaps: list of unavailable domains; "
            "UNAVAILABLE and GAP evidence states contribute to knowledge_gaps; "
            "gaps disclosed to mobile owner without fabricating absent evidence"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    EpistemicAuditCriterion(
        criterion_id="uncertainty_unavailable_evidence_state",
        area="uncertainty",
        title="Unavailable evidence state — EvidenceState.UNAVAILABLE for missing providers",
        status=EpistemicAuditStatus.READY,
        authoritative_module="app.calyx_conversation.teaching_synthesis.EvidenceState",
        evidence=(
            "EvidenceState.UNAVAILABLE: assigned when domain provider not reachable; "
            "build_teaching_synthesis(): evidence_state=EvidenceState.UNAVAILABLE per domain; "
            "no fabrication: synthesis produces honest UNAVAILABLE rather than invented claims"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    EpistemicAuditCriterion(
        criterion_id="uncertainty_gap_evidence_state",
        area="uncertainty",
        title="Gap evidence state — EvidenceState.GAP for known-missing evidence",
        status=EpistemicAuditStatus.READY,
        authoritative_module="app.calyx_conversation.teaching_synthesis.EvidenceState",
        evidence=(
            "EvidenceState.GAP: distinct from UNAVAILABLE — domain known to lack evidence, "
            "not merely unreachable; gap is a positive epistemic claim about the state of knowledge; "
            "synthesis correctly distinguishes 'no data' from 'no provider'"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ PROVENANCE
    EpistemicAuditCriterion(
        criterion_id="provenance_per_claim",
        area="provenance",
        title="Per-claim provenance — EvidenceClaim.provenance field survives to output",
        status=EpistemicAuditStatus.READY,
        authoritative_module="app.calyx_conversation.teaching_synthesis.EvidenceClaim",
        evidence=(
            "EvidenceClaim: provenance field, evidence_state, source_ids; "
            "to_dict(): 'evidence_state': self.evidence_state.value included; "
            "TeachingSynthesisV1.evidence_provenance: full per-claim trail in output"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    EpistemicAuditCriterion(
        criterion_id="provenance_locality_withheld",
        area="provenance",
        title="Sensitive locality withheld from provenance — sensitive_locality_withheld=True",
        status=EpistemicAuditStatus.READY,
        authoritative_module="app.calyx_conversation.teaching_synthesis.TeachingSynthesisV1",
        evidence=(
            "TeachingSynthesisV1.sensitive_locality_withheld=True; "
            "_remove_coordinates_from_provenance(): strips lat/lon from provenance before output; "
            "epistemic commitment: locality claim is withheld but its existence is disclosed"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    EpistemicAuditCriterion(
        criterion_id="provenance_brain_candidate_checksum",
        area="provenance",
        title="Brain candidate provenance checksum — SHA-256 per record in capture bundle",
        status=EpistemicAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.brain_capture.BrainCandidateRecord",
        evidence=(
            "BrainCandidateRecord.checksum(): SHA-256 of record content; "
            "BrainCaptureBundle.checksum(): SHA-256 of bundle; "
            "provenance integrity verified at capture before any promotion attempt"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ SECURITY
    EpistemicAuditCriterion(
        criterion_id="security_no_fabricated_claims",
        area="security",
        title="No fabricated epistemic claims — synthesis cannot invent evidence",
        status=EpistemicAuditStatus.READY,
        authoritative_module="app.calyx_conversation.teaching_synthesis",
        evidence=(
            "teaching_synthesis.py: synthesis contract forbids fabricated scientific evidence; "
            "UNAVAILABLE evidence state is the honest output when provider is absent; "
            "citations_no_fabrication criterion READY in calyx_acceptance_mission_audit"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    EpistemicAuditCriterion(
        criterion_id="security_graph_mutation_false",
        area="security",
        title="Epistemic memory read-only — knowledge_graph_mutation=False at runtime",
        status=EpistemicAuditStatus.READY,
        authoritative_module="app.calyx_conversation.speak_routes.speak_status",
        evidence=(
            "speak_status(): knowledge_graph_mutation=False; "
            "automatic_publication=False; "
            "epistemic memory is read-only: evidence is surfaced, not autonomously written to KG"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ MEMORY
    EpistemicAuditCriterion(
        criterion_id="memory_conversation_context",
        area="memory",
        title="Conversation memory — per-turn context retained in ConversationStore",
        status=EpistemicAuditStatus.READY,
        authoritative_module="app.calyx_conversation.store.ConversationStore",
        evidence=(
            "ConversationStore: conversation messages persisted per owner; "
            "_reference_trail(): builds citation context from prior conversation messages; "
            "sanitize_interaction_context(): cleans incoming context before storage"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    EpistemicAuditCriterion(
        criterion_id="memory_live_durable_sessions",
        area="memory",
        title="Live durable memory — requires DATABASE_URL for cross-restart persistence",
        status=EpistemicAuditStatus.BLOCKED,
        authoritative_module="app.calyx_conversation.store.ConversationStore",
        evidence=(
            "ConversationStore falls back to in-memory without DATABASE_URL; "
            "epistemic memory across restarts requires DATABASE_URL provisioned; "
            "calyx_runtime_truth_audit P11: persistence_postgres_unavailable is BLOCKED"
        ),
        gap_description=None,
        blocker_reason=(
            "DATABASE_URL not provisioned in this execution environment; "
            "epistemic conversation memory survives only in-process"
        ),
        next_action="Provision DATABASE_URL for durable epistemic conversation memory",
    ),
)


# ---------------------------------------------------------------------------
# Audit builders
# ---------------------------------------------------------------------------

@dataclass
class EpistemicMemoryAudit:
    """Machine-readable epistemic memory audit result."""

    schema_version: str = SCHEMA_VERSION
    audit_date: str = AUDIT_DATE
    no_auto_publication: bool = True
    no_production_mutation: bool = True
    criteria: list[EpistemicAuditCriterion] = field(default_factory=list)

    def by_status(self, status: str) -> list[EpistemicAuditCriterion]:
        return [c for c in self.criteria if c.status == status]

    def by_area(self, area: str) -> list[EpistemicAuditCriterion]:
        return [c for c in self.criteria if c.area == area]

    def ready_count(self) -> int:
        return len(self.by_status(EpistemicAuditStatus.READY))

    def gap_count(self) -> int:
        return len(self.by_status(EpistemicAuditStatus.GAP))

    def blocked_count(self) -> int:
        return len(self.by_status(EpistemicAuditStatus.BLOCKED))

    def owner_gated_count(self) -> int:
        return len(self.by_status(EpistemicAuditStatus.OWNER_GATED))

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


def get_epistemic_memory_audit() -> EpistemicMemoryAudit:
    """Return the current epistemic memory audit. Pure function — no external calls."""
    return EpistemicMemoryAudit(criteria=list(EPISTEMIC_AUDIT_CRITERIA))


def get_criteria_by_status(status: str) -> list[EpistemicAuditCriterion]:
    return [c for c in EPISTEMIC_AUDIT_CRITERIA if c.status == status]


def get_criteria_by_area(area: str) -> list[EpistemicAuditCriterion]:
    return [c for c in EPISTEMIC_AUDIT_CRITERIA if c.area == area]


def get_gaps() -> list[EpistemicAuditCriterion]:
    return get_criteria_by_status(EpistemicAuditStatus.GAP)


def get_next_actions() -> list[dict[str, str]]:
    return [
        {
            "criterion_id": c.criterion_id,
            "area": c.area,
            "title": c.title,
            "status": c.status,
            "next_action": c.next_action,
        }
        for c in EPISTEMIC_AUDIT_CRITERIA
        if c.next_action
    ]

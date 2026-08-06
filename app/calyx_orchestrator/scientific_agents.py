from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ScientificAgentRole(StrEnum):
    CHIEF_SCIENTIST = "chief_scientist"
    TAXONOMY_ENGINEER = "taxonomy_engineer"
    LITERATURE_EXTRACTION_ENGINEER = "literature_extraction_engineer"
    ATLAS_ENGINEER = "atlas_engineer"
    HARVESTER_ENGINEER = "harvester_engineer"
    IMAGE_VISION_ENGINEER = "image_vision_engineer"
    MATRIX_IDENTIFICATION_ENGINEER = "matrix_identification_engineer"
    MYCORRHIZA_ENGINEER = "mycorrhiza_engineer"
    POLLINATION_ECOLOGY_ENGINEER = "pollination_ecology_engineer"
    CONSERVATION_ENGINEER = "conservation_engineer"
    EVIDENCE_PROVENANCE_ENGINEER = "evidence_provenance_engineer"


class ScientificPolicyClass(StrEnum):
    REVIEW_ONLY = "review_only"
    STAGING_ONLY = "staging_only"
    CANDIDATE_KNOWLEDGE = "candidate_knowledge"


PROHIBITED_SCIENTIFIC_ACTIONS = frozenset(
    {
        "activate_taxonomy",
        "mutate_production_graph",
        "publish_scientific_knowledge",
        "promote_unlicensed_media",
        "bypass_human_review",
        "expose_private_chain_of_thought",
    }
)


@dataclass(frozen=True, slots=True)
class ScientificRoleSpec:
    role: ScientificAgentRole
    title: str
    mission: str
    policy_class: ScientificPolicyClass
    required_evidence: tuple[str, ...]
    prohibited_actions: frozenset[str] = PROHIBITED_SCIENTIFIC_ACTIONS
    requires_human_approval: bool = True


SCIENTIFIC_ROLE_REGISTRY: dict[ScientificAgentRole, ScientificRoleSpec] = {
    ScientificAgentRole.CHIEF_SCIENTIST: ScientificRoleSpec(
        ScientificAgentRole.CHIEF_SCIENTIST,
        "Chief Scientist",
        "Consolidate evidence, contradictions, confidence, provenance, and review readiness.",
        ScientificPolicyClass.REVIEW_ONLY,
        ("source_summary", "contradictions", "confidence", "provenance", "human_action"),
    ),
    ScientificAgentRole.TAXONOMY_ENGINEER: ScientificRoleSpec(
        ScientificAgentRole.TAXONOMY_ENGINEER,
        "Taxonomy Engineer",
        "Prepare bounded taxonomy release comparisons without activation.",
        ScientificPolicyClass.STAGING_ONLY,
        ("release_identity", "checksum", "comparison", "canonical_taxon_identity", "provenance"),
    ),
    ScientificAgentRole.LITERATURE_EXTRACTION_ENGINEER: ScientificRoleSpec(
        ScientificAgentRole.LITERATURE_EXTRACTION_ENGINEER,
        "Literature Extraction Engineer",
        "Acquire and extract literature into candidate knowledge with citation-preserving evidence.",
        ScientificPolicyClass.CANDIDATE_KNOWLEDGE,
        ("source_record_id", "content_hash", "evidence_spans", "citations", "provenance"),
    ),
    ScientificAgentRole.ATLAS_ENGINEER: ScientificRoleSpec(
        ScientificAgentRole.ATLAS_ENGINEER,
        "Atlas Engineer",
        "Prepare occurrence and geospatial staging-readiness evidence.",
        ScientificPolicyClass.STAGING_ONLY,
        ("occurrence_identity", "canonical_taxon_identity", "coordinates", "license", "provenance"),
    ),
    ScientificAgentRole.HARVESTER_ENGINEER: ScientificRoleSpec(
        ScientificAgentRole.HARVESTER_ENGINEER,
        "Harvester Engineer",
        "Run bounded source acquisition with checkpoints, retries, and replay evidence.",
        ScientificPolicyClass.STAGING_ONLY,
        ("source", "checkpoint", "acquisition_hash", "replay_result", "provenance"),
    ),
    ScientificAgentRole.IMAGE_VISION_ENGINEER: ScientificRoleSpec(
        ScientificAgentRole.IMAGE_VISION_ENGINEER,
        "Image and Vision Engineer",
        "Stage licensed images with canonical identity, attribution, and quality evidence.",
        ScientificPolicyClass.STAGING_ONLY,
        ("media_identity", "license", "attribution", "canonical_taxon_identity", "provenance"),
    ),
    ScientificAgentRole.MATRIX_IDENTIFICATION_ENGINEER: ScientificRoleSpec(
        ScientificAgentRole.MATRIX_IDENTIFICATION_ENGINEER,
        "Matrix Identification Engineer",
        "Audit characters, states, uncertainty, and matrix consistency.",
        ScientificPolicyClass.REVIEW_ONLY,
        ("matrix_identity", "characters", "states", "uncertainty", "provenance"),
    ),
    ScientificAgentRole.MYCORRHIZA_ENGINEER: ScientificRoleSpec(
        ScientificAgentRole.MYCORRHIZA_ENGINEER,
        "Mycorrhiza Engineer",
        "Reconcile fungal association evidence with uncertainty and provenance.",
        ScientificPolicyClass.CANDIDATE_KNOWLEDGE,
        ("host_taxon_identity", "fungal_identity", "association", "confidence", "provenance"),
    ),
    ScientificAgentRole.POLLINATION_ECOLOGY_ENGINEER: ScientificRoleSpec(
        ScientificAgentRole.POLLINATION_ECOLOGY_ENGINEER,
        "Pollination and Ecology Engineer",
        "Reconcile pollination and ecological relationships as reviewable evidence.",
        ScientificPolicyClass.CANDIDATE_KNOWLEDGE,
        ("taxon_identity", "interaction_identity", "relationship", "confidence", "provenance"),
    ),
    ScientificAgentRole.CONSERVATION_ENGINEER: ScientificRoleSpec(
        ScientificAgentRole.CONSERVATION_ENGINEER,
        "Conservation Engineer",
        "Prepare threats, status, protected-area, and conservation-action evidence for review.",
        ScientificPolicyClass.CANDIDATE_KNOWLEDGE,
        ("taxon_identity", "status_source", "threats", "actions", "provenance"),
    ),
    ScientificAgentRole.EVIDENCE_PROVENANCE_ENGINEER: ScientificRoleSpec(
        ScientificAgentRole.EVIDENCE_PROVENANCE_ENGINEER,
        "Evidence and Provenance Engineer",
        "Audit source identity, claim lineage, confidence, review hashes, and supersession state.",
        ScientificPolicyClass.REVIEW_ONLY,
        ("source_identity", "claim_lineage", "confidence", "review_hash", "provenance"),
    ),
}


@dataclass(frozen=True, slots=True)
class ScientificResult:
    role: ScientificAgentRole
    canonical_taxon_identity: str | None
    provenance: tuple[str, ...]
    evidence: dict[str, Any]
    contradictions: tuple[str, ...] = ()
    confidence: float | None = None
    requested_action: str | None = None

    def validate(self) -> None:
        spec = SCIENTIFIC_ROLE_REGISTRY[self.role]
        if not self.provenance:
            raise ValueError("PROVENANCE_REQUIRED")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("CONFIDENCE_OUT_OF_RANGE")
        missing = [key for key in spec.required_evidence if key not in self.evidence]
        if missing:
            raise ValueError(f"REQUIRED_EVIDENCE_MISSING:{','.join(sorted(missing))}")
        if self.requested_action in PROHIBITED_SCIENTIFIC_ACTIONS:
            raise PermissionError("SCIENTIFIC_ACTION_PROHIBITED")


def scientific_role_snapshot() -> list[dict[str, Any]]:
    return [
        {
            "role": role.value,
            "title": spec.title,
            "mission": spec.mission,
            "policy_class": spec.policy_class.value,
            "required_evidence": list(spec.required_evidence),
            "prohibited_actions": sorted(spec.prohibited_actions),
            "requires_human_approval": spec.requires_human_approval,
        }
        for role, spec in SCIENTIFIC_ROLE_REGISTRY.items()
    ]

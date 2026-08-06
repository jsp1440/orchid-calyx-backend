from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .scientific_agents import (
    PROHIBITED_SCIENTIFIC_ACTIONS,
    SCIENTIFIC_ROLE_REGISTRY,
    ScientificAgentRole,
    scientific_role_snapshot,
)


@dataclass(frozen=True, slots=True)
class ScientificJobTemplate:
    job_key: str
    role: ScientificAgentRole
    title: str
    domain: str
    policy_gate: str
    required_outputs: tuple[str, ...]
    depends_on: tuple[str, ...] = ()


SCIENTIFIC_JOB_TEMPLATES: tuple[ScientificJobTemplate, ...] = (
    ScientificJobTemplate(
        "taxonomy_release_comparison",
        ScientificAgentRole.TAXONOMY_ENGINEER,
        "Hassler taxonomy release comparison preparation",
        "taxonomy",
        "owner_taxonomy_activation_required",
        ("release_identity", "checksum", "comparison", "canonical_taxon_identity", "provenance"),
    ),
    ScientificJobTemplate(
        "literature_candidate_handoff",
        ScientificAgentRole.LITERATURE_EXTRACTION_ENGINEER,
        "Bounded literature extraction and candidate-knowledge handoff",
        "literature",
        "human_scientific_review_required",
        ("source_record_id", "content_hash", "evidence_spans", "citations", "provenance"),
    ),
    ScientificJobTemplate(
        "atlas_staging_readiness",
        ScientificAgentRole.ATLAS_ENGINEER,
        "Occurrence and Atlas staging-readiness proof",
        "atlas",
        "production_graph_mutation_prohibited",
        ("occurrence_identity", "canonical_taxon_identity", "coordinates", "license", "provenance"),
    ),
    ScientificJobTemplate(
        "harvester_replay_proof",
        ScientificAgentRole.HARVESTER_ENGINEER,
        "Bounded harvester checkpoint and replay proof",
        "harvester",
        "staging_only",
        ("source", "checkpoint", "acquisition_hash", "replay_result", "provenance"),
    ),
    ScientificJobTemplate(
        "licensed_image_staging",
        ScientificAgentRole.IMAGE_VISION_ENGINEER,
        "Licensed-image staging and attribution proof",
        "images",
        "license_allowlist_required",
        ("media_identity", "license", "attribution", "canonical_taxon_identity", "provenance"),
    ),
    ScientificJobTemplate(
        "matrix_consistency_audit",
        ScientificAgentRole.MATRIX_IDENTIFICATION_ENGINEER,
        "Matrix character-state consistency audit",
        "matrix",
        "review_only",
        ("matrix_identity", "characters", "states", "uncertainty", "provenance"),
    ),
    ScientificJobTemplate(
        "mycorrhiza_reconciliation",
        ScientificAgentRole.MYCORRHIZA_ENGINEER,
        "Mycorrhizal evidence reconciliation",
        "mycorrhiza",
        "human_scientific_review_required",
        ("host_taxon_identity", "fungal_identity", "association", "confidence", "provenance"),
    ),
    ScientificJobTemplate(
        "pollination_ecology_reconciliation",
        ScientificAgentRole.POLLINATION_ECOLOGY_ENGINEER,
        "Pollination and ecology relationship reconciliation",
        "pollination_ecology",
        "human_scientific_review_required",
        ("taxon_identity", "interaction_identity", "relationship", "confidence", "provenance"),
    ),
    ScientificJobTemplate(
        "conservation_readiness_audit",
        ScientificAgentRole.CONSERVATION_ENGINEER,
        "Conservation evidence readiness audit",
        "conservation",
        "human_scientific_review_required",
        ("taxon_identity", "status_source", "threats", "actions", "provenance"),
    ),
    ScientificJobTemplate(
        "provenance_lineage_audit",
        ScientificAgentRole.EVIDENCE_PROVENANCE_ENGINEER,
        "Provenance and evidence-lineage audit",
        "provenance",
        "review_only",
        ("source_identity", "claim_lineage", "confidence", "review_hash", "provenance"),
    ),
)

SCIENTIFIC_PREREQUISITE_KEYS = tuple(item.job_key for item in SCIENTIFIC_JOB_TEMPLATES)
CHIEF_SCIENTIST_JOB = ScientificJobTemplate(
    "chief_scientist_report",
    ScientificAgentRole.CHIEF_SCIENTIST,
    "Chief Scientist consolidated scientific program report",
    "scientific_governance",
    "human_scientific_review_required",
    ("source_summary", "contradictions", "confidence", "provenance", "human_action"),
    depends_on=SCIENTIFIC_PREREQUISITE_KEYS,
)


def build_scientific_program_fixture() -> dict[str, Any]:
    jobs = [*_template_snapshots(SCIENTIFIC_JOB_TEMPLATES), *_template_snapshots((CHIEF_SCIENTIST_JOB,))]
    return {
        "program_key": "phase_2_scientific_data_demonstration",
        "title": "CALYX Phase 2 Scientific and Data Agent Demonstration",
        "max_active_jobs": 6,
        "jobs": jobs,
        "dependencies": [
            {"upstream": key, "downstream": CHIEF_SCIENTIST_JOB.job_key}
            for key in SCIENTIFIC_PREREQUISITE_KEYS
        ],
        "release_rule": {
            "job_key": CHIEF_SCIENTIST_JOB.job_key,
            "successful_outcomes": ["DELIVERED", "NO_OP"],
            "on_failed_prerequisite": "BLOCKED",
            "human_action_required": True,
        },
        "safety": {
            "automatic_merge": False,
            "production_deployment": False,
            "taxonomy_activation": False,
            "production_graph_mutation": False,
            "scientific_publication": False,
            "unlicensed_media_promotion": False,
        },
    }


def scientific_mission_control_snapshot() -> dict[str, Any]:
    fixture = build_scientific_program_fixture()
    return {
        "phase": 2,
        "status": "foundation_active",
        "roles": scientific_role_snapshot(),
        "role_count": len(SCIENTIFIC_ROLE_REGISTRY),
        "job_templates": fixture["jobs"],
        "program": fixture,
        "policy_gates": sorted(PROHIBITED_SCIENTIFIC_ACTIONS),
        "human_actions": [
            "Review taxonomy comparison before any activation.",
            "Review scientific evidence before publication eligibility.",
            "Approve any production Knowledge Graph mutation separately.",
            "Resolve blocked prerequisites before Chief Scientist consolidation.",
        ],
    }


def _template_snapshots(templates: tuple[ScientificJobTemplate, ...]) -> list[dict[str, Any]]:
    return [
        {
            "job_key": item.job_key,
            "role": item.role.value,
            "title": item.title,
            "domain": item.domain,
            "policy_gate": item.policy_gate,
            "required_outputs": list(item.required_outputs),
            "depends_on": list(item.depends_on),
            "status": "waiting" if item.depends_on else "ready",
        }
        for item in templates
    ]

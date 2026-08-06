from __future__ import annotations

import pytest

from app.calyx_orchestrator.scientific_agents import ScientificAgentRole
from app.calyx_orchestrator.scientific_execution import (
    ScientificWorkIdentity,
    scientific_program_specs,
    validate_scientific_payload,
)
from app.main import app


def test_scientific_program_specs_create_eleven_jobs_and_ten_dependencies() -> None:
    jobs, dependencies = scientific_program_specs()
    assert len(jobs) == 11
    assert len(dependencies) == 10
    assert jobs[-1].job_key == "chief_scientist_report"
    assert all(downstream == "chief_scientist_report" for _, downstream in dependencies)
    assert all(job.repository == "jsp1440/orchid-calyx-backend" for job in jobs)
    assert len({job.branch for job in jobs}) == 11


def test_domain_identity_is_deterministic_and_domain_aware() -> None:
    taxonomy = ScientificWorkIdentity(
        domain="taxonomy",
        role=ScientificAgentRole.TAXONOMY_ENGINEER,
        template_key="taxonomy_release_comparison",
    )
    atlas = ScientificWorkIdentity(
        domain="atlas",
        role=ScientificAgentRole.TAXONOMY_ENGINEER,
        template_key="taxonomy_release_comparison",
    )
    assert taxonomy.fingerprint == taxonomy.fingerprint
    assert taxonomy.fingerprint != atlas.fingerprint


def test_taxonomy_payload_requires_role_specific_evidence() -> None:
    evidence = {
        "release_identity": "WorldOrchids-26-08",
        "checksum": "abc123",
        "comparison": {"added": 1},
        "canonical_taxon_identity": "taxon:laelia-anceps",
        "provenance": ["fixture:hassler-release"],
        "contradictions": [],
        "confidence": 0.99,
    }
    result = validate_scientific_payload(
        role_key=ScientificAgentRole.TAXONOMY_ENGINEER.value,
        evidence=evidence,
    )
    assert result.role is ScientificAgentRole.TAXONOMY_ENGINEER
    assert result.provenance == ("fixture:hassler-release",)


def test_scientific_payload_fails_closed_without_provenance() -> None:
    with pytest.raises(ValueError, match="PROVENANCE_REQUIRED"):
        validate_scientific_payload(
            role_key=ScientificAgentRole.HARVESTER_ENGINEER.value,
            evidence={
                "source": "fixture",
                "checkpoint": "1",
                "acquisition_hash": "abc",
                "replay_result": "NO_DUPLICATES",
            },
        )


def test_scientific_payload_rejects_prohibited_action() -> None:
    with pytest.raises(PermissionError, match="SCIENTIFIC_ACTION_PROHIBITED"):
        validate_scientific_payload(
            role_key=ScientificAgentRole.IMAGE_VISION_ENGINEER.value,
            evidence={
                "media_identity": "image:1",
                "license": "CC-BY",
                "attribution": "Fixture Author",
                "canonical_taxon_identity": "taxon:1",
                "provenance": ["fixture:image"],
                "requested_action": "promote_unlicensed_media",
            },
        )


def test_scientific_execution_routes_are_registered() -> None:
    paths = {route.path for route in app.routes}
    assert "/brain/orchestrator/scientific/programs/phase-2-demo" in paths
    assert "/brain/orchestrator/scientific/workers/jobs/{program_job_id}/complete" in paths

from __future__ import annotations

from pathlib import Path

from runtime.cultivation_guidance import CultivationGuidanceService


def literature(guidance_id: str, water: str = "water thoroughly, then allow modest drying") -> dict:
    return {
        "guidance_id": guidance_id,
        "version": 1,
        "identity": {"canonical_taxon_id": "taxon:laelia-anceps", "accepted_name": "Laelia anceps"},
        "source_kind": "literature_evidence",
        "source": {"uri": f"doi:10.0000/{guidance_id}", "citation": "Fixture paper"},
        "locality_context": {"scope": "species range"},
        "confidence": 0.8,
        "temperature": {"day_c": [18, 27], "night_c": [10, 18]},
        "light": {"description": "bright filtered light"},
        "water": water,
        "ventilation": "continuous air movement",
    }


def test_literature_guidance_is_distinct_from_anecdote(tmp_path: Path):
    service = CultivationGuidanceService(tmp_path)
    evidence = service.register_guidance("owner-a", literature("lit-1"), actor="owner-a")
    anecdote = service.register_guidance(
        "owner-a",
        {
            "guidance_id": "grower-1",
            "version": 1,
            "identity": {"canonical_taxon_id": "taxon:laelia-anceps"},
            "source_kind": "grower_observation",
            "grower_observation": {"grower": "fixture", "years": 3},
            "locality_context": {"location": "cool coastal greenhouse"},
            "confidence": 0.5,
            "water": "reduced winter watering in this collection",
        },
        actor="owner-a",
    )
    assert evidence["evidence_backed"] is True
    assert evidence["anecdotal"] is False
    assert anecdote["anecdotal"] is True
    profile = service.assemble_profile("owner-a", "taxon:laelia-anceps")
    assert len(profile["evidence_backed_guidance"]) == 1
    assert len(profile["grower_observations"]) == 1
    assert profile["evidence_anecdote_separation"] is True


def test_local_adaptation_is_not_promoted_to_general_guidance(tmp_path: Path):
    service = CultivationGuidanceService(tmp_path)
    service.register_guidance(
        "owner-a",
        {
            "guidance_id": "local-1",
            "version": 1,
            "identity": {"canonical_taxon_id": "taxon:laelia-anceps"},
            "source_kind": "local_adaptation",
            "locality_context": {"location": "fixture coast", "greenhouse": "cool"},
            "confidence": 0.6,
            "humidity": {"target_percent": [60, 75]},
        },
        actor="owner-a",
    )
    profile = service.assemble_profile("owner-a", "taxon:laelia-anceps")
    assert len(profile["local_adaptations"]) == 1
    assert profile["evidence_backed_guidance"] == []


def test_contradictory_guidance_routes_to_review(tmp_path: Path):
    service = CultivationGuidanceService(tmp_path)
    service.register_guidance("owner-a", literature("lit-1", "keep evenly moist"), actor="owner-a")
    service.register_guidance(
        "owner-a",
        {
            "guidance_id": "grower-1",
            "version": 1,
            "identity": {"canonical_taxon_id": "taxon:laelia-anceps"},
            "source_kind": "grower_observation",
            "grower_observation": {"grower": "fixture"},
            "confidence": 0.4,
            "water": "dry hard between winter waterings",
        },
        actor="owner-a",
    )
    profile = service.assemble_profile("owner-a", "taxon:laelia-anceps")
    assert profile["contradiction_count"] >= 1
    assert any(item["field"] == "water" for item in profile["contradictions"])


def test_version_is_immutable_and_review_is_separate(tmp_path: Path):
    service = CultivationGuidanceService(tmp_path)
    original = service.register_guidance("owner-a", literature("lit-1"), actor="owner-a")
    same = service.register_guidance("owner-a", literature("lit-1"), actor="owner-a")
    assert same == original
    decision = service.review_guidance(
        "owner-a", "lit-1", 1, state="accepted_as_guidance", reviewer="human-reviewer", rationale="evidence and scope reviewed"
    )
    assert decision["source_digest"] == original["record_digest"]
    assert decision["state"] == "accepted_as_guidance"


def test_handoff_is_decision_support_only_and_never_controls_greenhouse(tmp_path: Path):
    service = CultivationGuidanceService(tmp_path)
    service.register_guidance("owner-a", literature("lit-1"), actor="owner-a")
    handoff = service.conservatory_oasis_handoff("owner-a", "taxon:laelia-anceps")
    assert handoff["handoff_targets"] == ["Conservatory", "OASIS"]
    assert handoff["decision_support_only"] is True
    assert handoff["autonomous_greenhouse_control_authorized"] is False
    assert handoff["pesticide_advice_authorized"] is False
    assert handoff["medical_advice_authorized"] is False

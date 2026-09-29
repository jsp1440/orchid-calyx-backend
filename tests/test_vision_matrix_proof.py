"""Tests for OC-COMPLETE-007 AI Vision, Matrix, Glossary convergence proof.

Proves acceptance criteria:
- licensed image accepted; unlicensed image rejected at intake
- vision analysis produces MACHINE_GENERATED observations with bounded confidence
- every character observation is grounded to a canonical glossary concept
- matrix scoring produces support/contradiction/unknown accounting per character
- review handoff preserves MACHINE_GENERATED state, review_required=True
- no automatic publication at any stage
- no knowledge graph mutation at any stage
- AI suggestions are never promoted to KG without human review
- capability inventory covers all Vision/Matrix/Glossary engines
- GAPs are documented with child task titles
"""

from __future__ import annotations

import json

from app.scientific_adapter_lab.vision_matrix_glossary_inventory import (
    CAPABILITY_INVENTORY,
    get_capabilities_by_status,
    get_child_tasks,
    get_inventory,
    serialize_inventory_as_json,
)
from app.scientific_adapter_lab.vision_matrix_proof import (
    EPIDENDRUM_MATRIX_PROFILE,
    EPIDENDRUM_RADICANS_PROFILE,
    ORCHID_IMAGE_FIXTURE,
    build_vision_analysis_result,
    run_vision_matrix_proof,
    serialize_proof_as_json,
    stage_glossary_grounding,
    stage_image_intake,
    stage_matrix_scoring,
    stage_review_handoff,
)

# ---------------------------------------------------------------------------
# Inventory: capability/readiness audit
# ---------------------------------------------------------------------------


def test_inventory_covers_all_four_domains():
    domains = {c["domain"] for c in CAPABILITY_INVENTORY}
    assert {"vision", "glossary", "matrix", "end_to_end"} <= domains


def test_inventory_has_at_least_fifteen_capabilities():
    assert len(CAPABILITY_INVENTORY) >= 15


def test_every_capability_has_required_fields():
    required = {"capability_id", "capability", "domain", "status", "authoritative_module", "evidence"}
    for cap in CAPABILITY_INVENTORY:
        missing = required - set(cap)
        assert not missing, f"{cap['capability_id']} missing: {missing}"


def test_every_status_is_valid():
    valid = {"KEEP", "CONVERGE", "SUPERSEDE", "GAP"}
    for cap in CAPABILITY_INVENTORY:
        assert cap["status"] in valid, f"{cap['capability_id']} has invalid status: {cap['status']}"


def test_inventory_has_keep_capabilities():
    keep = get_capabilities_by_status("KEEP")
    assert len(keep) >= 8


def test_inventory_has_gap_capabilities():
    gaps = get_capabilities_by_status("GAP")
    assert len(gaps) >= 2


def test_gaps_have_child_task_titles():
    for cap in get_capabilities_by_status("GAP"):
        assert cap.get("child_task"), f"GAP {cap['capability_id']} missing child_task"
        assert cap.get("gap_description"), f"GAP {cap['capability_id']} missing gap_description"


def test_converge_capabilities_have_child_tasks():
    for cap in get_capabilities_by_status("CONVERGE"):
        assert cap.get("child_task"), f"CONVERGE {cap['capability_id']} missing child_task"


def test_herbarium_ocr_is_documented_gap():
    cap = next(c for c in CAPABILITY_INVENTORY if c["capability_id"] == "vision_herbarium_ocr")
    assert cap["status"] == "GAP"
    assert "herbarium" in cap["gap_description"].lower()


def test_cannot_determine_is_keep():
    cap = next(c for c in CAPABILITY_INVENTORY if c["capability_id"] == "vision_cannot_determine")
    assert cap["status"] == "KEEP"


def test_matrix_support_contradiction_unknown_is_keep():
    cap = next(c for c in CAPABILITY_INVENTORY if c["capability_id"] == "matrix_support_contradiction_unknown")
    assert cap["status"] == "KEEP"


def test_child_tasks_list_has_titles():
    tasks = get_child_tasks()
    assert len(tasks) >= 4
    for t in tasks:
        assert t["title"]
        assert t["capability_id"]


def test_inventory_schema_version():
    inv = get_inventory()
    assert inv["schema_version"] == "oc-vision-matrix-glossary-inventory/v1"


def test_inventory_graph_mutation_false():
    inv = get_inventory()
    assert inv["graph_mutation"] is False
    assert inv["automatic_publication"] is False


def test_inventory_serializable_as_json():
    raw = serialize_inventory_as_json()
    parsed = json.loads(raw)
    assert parsed["capability_count"] == len(CAPABILITY_INVENTORY)


# ---------------------------------------------------------------------------
# Stage 1: Image intake
# ---------------------------------------------------------------------------


def test_image_intake_accepts_licensed_fixture():
    result = stage_image_intake(ORCHID_IMAGE_FIXTURE)
    assert result.image_id == ORCHID_IMAGE_FIXTURE["image_id"]
    assert result.license_code == "CC-BY-4.0"
    assert result.review_state == "MACHINE_GENERATED"
    assert result.automatic_publication is False
    assert result.knowledge_graph_mutation is False
    assert result.review_required is True


def test_image_intake_rejects_missing_license():
    import pytest
    fixture = dict(ORCHID_IMAGE_FIXTURE)
    fixture["license_code"] = ""
    with pytest.raises(PermissionError, match="LICENSE_AND_ATTRIBUTION_REQUIRED"):
        stage_image_intake(fixture)


def test_image_intake_rejects_missing_attribution():
    import pytest
    fixture = dict(ORCHID_IMAGE_FIXTURE)
    fixture["attribution"] = ""
    with pytest.raises(PermissionError, match="LICENSE_AND_ATTRIBUTION_REQUIRED"):
        stage_image_intake(fixture)


# ---------------------------------------------------------------------------
# Stage 2: Vision analysis
# ---------------------------------------------------------------------------


def test_vision_analysis_validates_without_error():
    result = build_vision_analysis_result()
    result.validate()


def test_vision_analysis_has_detected_parts():
    result = build_vision_analysis_result()
    assert len(result.detected_parts) >= 3
    part_names = {p.part for p in result.detected_parts}
    assert "labellum" in part_names


def test_vision_analysis_confidence_below_cap():
    result = build_vision_analysis_result()
    for obs in result.character_observations:
        assert obs.confidence <= 0.98, f"Confidence cap violated: {obs.character_id}={obs.confidence}"


def test_vision_analysis_requires_provenance():
    result = build_vision_analysis_result()
    for obs in result.character_observations:
        assert obs.provenance, f"Observation {obs.character_id} has no provenance"


def test_vision_analysis_model_provenance_complete():
    result = build_vision_analysis_result()
    result.model.validate()
    assert result.model.provider == "anthropic"


def test_vision_analysis_license_and_attribution_present():
    result = build_vision_analysis_result()
    assert result.license_code
    assert result.attribution


def test_vision_analysis_none_state_preserved_for_occluded():
    result = build_vision_analysis_result()
    pseudobulb = next((o for o in result.character_observations if o.character_id == "chr:pseudobulb_presence"), None)
    assert pseudobulb is not None
    assert pseudobulb.state is None, "Occluded observation state must be None, not collapsed"


# ---------------------------------------------------------------------------
# Stage 3: Glossary grounding
# ---------------------------------------------------------------------------


def test_glossary_grounding_produces_one_result_per_observation():
    vision = build_vision_analysis_result()
    groundings = stage_glossary_grounding(vision.character_observations)
    assert len(groundings) == len(vision.character_observations)


def test_glossary_grounding_marks_known_characters_grounded():
    vision = build_vision_analysis_result()
    groundings = stage_glossary_grounding(vision.character_observations)
    grounded = [g for g in groundings if g.grounding_status == "GROUNDED"]
    assert len(grounded) >= 3


def test_glossary_grounding_preserves_none_state():
    vision = build_vision_analysis_result()
    groundings = stage_glossary_grounding(vision.character_observations)
    pseudobulb = next(g for g in groundings if g.character_id == "chr:pseudobulb_presence")
    assert pseudobulb.observed_state is None


def test_glossary_grounding_machine_generated():
    vision = build_vision_analysis_result()
    groundings = stage_glossary_grounding(vision.character_observations)
    for g in groundings:
        assert g.review_state == "MACHINE_GENERATED"
        assert g.automatic_publication is False
        assert g.knowledge_graph_mutation is False


def test_glossary_grounding_concept_has_lexicon_source():
    vision = build_vision_analysis_result()
    groundings = stage_glossary_grounding(vision.character_observations)
    for g in groundings:
        if g.grounding_status == "GROUNDED":
            assert g.concept["lexicon_source"]


# ---------------------------------------------------------------------------
# Stage 4: Matrix scoring
# ---------------------------------------------------------------------------


def test_matrix_scoring_produces_candidates_for_each_profile():
    vision = build_vision_analysis_result()
    result = stage_matrix_scoring(vision, [EPIDENDRUM_MATRIX_PROFILE, EPIDENDRUM_RADICANS_PROFILE])
    assert len(result.candidates) == 2


def test_matrix_scoring_ranks_by_score_descending():
    vision = build_vision_analysis_result()
    result = stage_matrix_scoring(vision, [EPIDENDRUM_MATRIX_PROFILE, EPIDENDRUM_RADICANS_PROFILE])
    scores = [c.score for c in result.candidates]
    assert scores == sorted(scores, reverse=True)


def test_matrix_scoring_epidendrum_secundum_tops_ranking():
    """Fixture observations include pink lip → matches secundum not radicans (orange)."""
    vision = build_vision_analysis_result()
    result = stage_matrix_scoring(vision, [EPIDENDRUM_MATRIX_PROFILE, EPIDENDRUM_RADICANS_PROFILE])
    assert result.candidates[0].accepted_name == "Epidendrum secundum Jacq."


def test_matrix_scoring_support_contradiction_unknown_sum_to_observation_count():
    vision = build_vision_analysis_result()
    result = stage_matrix_scoring(vision, [EPIDENDRUM_MATRIX_PROFILE])
    candidate = result.candidates[0]
    assert (
        candidate.support_count + candidate.contradiction_count + candidate.unknown_count
        == len(vision.character_observations)
    )


def test_matrix_scoring_radicans_has_contradiction_for_pink_lip():
    """Pink observed lip should contradict orange/red expected lip of radicans."""
    vision = build_vision_analysis_result()
    result = stage_matrix_scoring(vision, [EPIDENDRUM_RADICANS_PROFILE])
    candidate = result.candidates[0]
    lip_contrib = next(c for c in candidate.contributions if c.character_id == "chr:lip_color")
    assert lip_contrib.outcome == "CONTRADICTION"


def test_matrix_scoring_machine_generated():
    vision = build_vision_analysis_result()
    result = stage_matrix_scoring(vision, [EPIDENDRUM_MATRIX_PROFILE])
    assert result.review_state == "MACHINE_GENERATED"
    assert result.automatic_publication is False
    assert result.knowledge_graph_mutation is False
    assert result.review_required is True


def test_matrix_scoring_no_character_contributions_missing():
    vision = build_vision_analysis_result()
    result = stage_matrix_scoring(vision, [EPIDENDRUM_MATRIX_PROFILE])
    candidate = result.candidates[0]
    obs_ids = {o.character_id for o in vision.character_observations}
    contrib_ids = {c.character_id for c in candidate.contributions}
    assert obs_ids == contrib_ids


# ---------------------------------------------------------------------------
# Stage 5: Review handoff
# ---------------------------------------------------------------------------


def test_review_handoff_review_state_machine_generated():
    intake = stage_image_intake(ORCHID_IMAGE_FIXTURE)
    vision = build_vision_analysis_result()
    scoring = stage_matrix_scoring(vision, [EPIDENDRUM_MATRIX_PROFILE, EPIDENDRUM_RADICANS_PROFILE])
    handoff = stage_review_handoff(intake, vision, scoring)
    assert handoff.review_state == "MACHINE_GENERATED"


def test_review_handoff_not_promoted():
    intake = stage_image_intake(ORCHID_IMAGE_FIXTURE)
    vision = build_vision_analysis_result()
    scoring = stage_matrix_scoring(vision, [EPIDENDRUM_MATRIX_PROFILE, EPIDENDRUM_RADICANS_PROFILE])
    handoff = stage_review_handoff(intake, vision, scoring)
    assert handoff.promoted_to_kg is False


def test_review_handoff_no_auto_publication():
    intake = stage_image_intake(ORCHID_IMAGE_FIXTURE)
    vision = build_vision_analysis_result()
    scoring = stage_matrix_scoring(vision, [EPIDENDRUM_MATRIX_PROFILE, EPIDENDRUM_RADICANS_PROFILE])
    handoff = stage_review_handoff(intake, vision, scoring)
    assert handoff.automatic_publication is False
    assert handoff.knowledge_graph_mutation is False
    assert handoff.review_required is True


def test_review_handoff_top_candidate_is_epidendrum_secundum():
    intake = stage_image_intake(ORCHID_IMAGE_FIXTURE)
    vision = build_vision_analysis_result()
    scoring = stage_matrix_scoring(vision, [EPIDENDRUM_MATRIX_PROFILE, EPIDENDRUM_RADICANS_PROFILE])
    handoff = stage_review_handoff(intake, vision, scoring)
    assert "Epidendrum secundum" in handoff.top_candidate


# ---------------------------------------------------------------------------
# Full proof runner
# ---------------------------------------------------------------------------


def test_full_proof_passes():
    proof = run_vision_matrix_proof()
    assert proof["verdict"] == "PASS", proof.get("invariant_attestations")


def test_full_proof_has_all_five_stages():
    proof = run_vision_matrix_proof()
    assert set(proof["stages"]) >= {
        "image_intake",
        "vision_analysis",
        "glossary_grounding",
        "matrix_scoring",
        "review_handoff",
    }


def test_full_proof_no_auto_publication():
    proof = run_vision_matrix_proof()
    assert proof["automatic_publication"] is False
    for stage_key, stage in proof["stages"].items():
        assert stage.get("automatic_publication") is False, f"{stage_key}: automatic_publication is not False"


def test_full_proof_no_kg_mutation():
    proof = run_vision_matrix_proof()
    assert proof["knowledge_graph_mutation"] is False
    for stage_key, stage in proof["stages"].items():
        assert stage.get("knowledge_graph_mutation") is False, f"{stage_key}: knowledge_graph_mutation is not False"


def test_full_proof_all_stages_machine_generated():
    proof = run_vision_matrix_proof()
    for stage_key in ["image_intake", "vision_analysis", "glossary_grounding", "matrix_scoring"]:
        assert proof["stages"][stage_key]["review_state"] == "MACHINE_GENERATED", (
            f"{stage_key}: review_state is not MACHINE_GENERATED"
        )
    assert proof["stages"]["review_handoff"]["review_state"] == "MACHINE_GENERATED"


def test_full_proof_not_promoted_to_kg():
    proof = run_vision_matrix_proof()
    assert proof["stages"]["review_handoff"]["promoted_to_kg"] is False


def test_full_proof_invariant_attestations_all_hold():
    proof = run_vision_matrix_proof()
    attestations = proof["invariant_attestations"]
    assert attestations["all_stages_machine_generated"] is True
    assert attestations["no_automatic_publication_at_any_stage"] is True
    assert attestations["no_knowledge_graph_mutation_at_any_stage"] is True
    assert attestations["not_promoted_to_kg"] is True
    assert attestations["all_invariants_hold"] is True


def test_full_proof_matrix_scoring_stage_has_ranked_candidates():
    proof = run_vision_matrix_proof()
    scoring = proof["stages"]["matrix_scoring"]
    assert scoring["candidate_count"] == 2
    candidates = scoring["ranked_candidates"]
    scores = [c["score"] for c in candidates]
    assert scores == sorted(scores, reverse=True)


def test_full_proof_glossary_grounding_stage_has_groundings():
    proof = run_vision_matrix_proof()
    grounding = proof["stages"]["glossary_grounding"]
    assert grounding["grounded_count"] >= 3
    for g in grounding["groundings"]:
        assert "character_id" in g
        assert "grounding_status" in g


def test_full_proof_serializable_as_json():
    proof = run_vision_matrix_proof()
    raw = serialize_proof_as_json(proof)
    parsed = json.loads(raw)
    assert parsed["verdict"] == "PASS"
    assert parsed["schema_version"] == "oc-vision-matrix-proof/v1"

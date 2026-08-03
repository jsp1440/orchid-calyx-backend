from app.parallel_platform.identification_candidates import (
    IdentificationCandidateRecord,
    rank_identification_candidates,
)
from app.parallel_platform.identification_observations import (
    CharacterObservation,
    OrchidObservation,
)


def test_candidate_ranking_reports_support_conflict_and_next_question():
    observation = OrchidObservation(
        observation_id="obs:1",
        characters=(
            CharacterObservation(character="flower_shape", state="observed", value="star-shaped"),
            CharacterObservation(character="geography", state="observed", value="Mexico"),
        ),
    )
    candidates = (
        IdentificationCandidateRecord(
            taxon_id="taxon:1",
            accepted_name="Example one",
            features={
                "flower_shape": "star-shaped",
                "geography": "Mexico",
                "lip_structure": "three-lobed",
            },
            provenance=("taxonomy:release",),
        ),
        IdentificationCandidateRecord(
            taxon_id="taxon:2",
            accepted_name="Example two",
            features={
                "flower_shape": "round",
                "geography": "Mexico",
                "lip_structure": "entire",
            },
        ),
    )
    result = rank_identification_candidates(observation, candidates)
    assert result["state"] == "candidate_suggestions"
    assert result["candidates"][0]["taxon_id"] == "taxon:1"
    assert result["candidates"][0]["supporting_characters"] == ["flower_shape", "geography"]
    assert result["candidates"][1]["conflicting_characters"] == ["flower_shape"]
    assert result["next_best_observation"] == "lip_structure"
    assert result["verified_identity"] is None


def test_tied_candidates_are_ambiguous():
    observation = OrchidObservation(
        observation_id="obs:2",
        characters=(CharacterObservation(character="geography", state="observed", value="Peru"),),
    )
    candidates = (
        IdentificationCandidateRecord("taxon:a", "Alpha", {"geography": "Peru"}),
        IdentificationCandidateRecord("taxon:b", "Beta", {"geography": "Peru"}),
    )
    result = rank_identification_candidates(observation, candidates)
    assert result["state"] == "ambiguous"
    assert all(candidate["verified_identity"] is False for candidate in result["candidates"])

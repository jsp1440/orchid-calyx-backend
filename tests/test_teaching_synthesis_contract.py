from __future__ import annotations

import json

import pytest

from app.calyx_conversation.teaching_synthesis import (
    EvidenceState,
    RelationshipClaim,
    SubjectIdentity,
    build_featured_genus_pool,
    build_teaching_synthesis,
)


def _subject() -> SubjectIdentity:
    return SubjectIdentity(
        taxon_name="Phalaenopsis violacea",
        taxon_id="taxon:phalaenopsis-violacea",
        common_names=(),
        taxon_rank="species",
        canonical_source="World Plants",
        synonym_names=(),
        authority=None,
    )


def test_teaching_synthesis_is_claim_first_provenance_preserving_and_fail_closed() -> None:
    synthesis = build_teaching_synthesis(
        _subject(),
        {
            "morphology_anatomy_physiology": {
                "claims": [
                    {
                        "statement": "Flowers are fragrant.",
                        "source_references": [
                            {
                                "source": "reviewed-literature",
                                "type": "paper",
                                "review_state": "reviewed",
                                "doi": "10.0000/example",
                                "latitude": "1.234",
                                "longitude": "5.678",
                            }
                        ],
                    }
                ]
            },
            "pollination": {
                "claims": [
                    {
                        "statement": "A visitor association is reported.",
                        "source_references": [{"source": "paper-a", "review_state": "reviewed"}],
                    }
                ],
                "conflicts": [
                    {
                        "statement": "The visitor identity is disputed.",
                        "source_references": [{"source": "paper-b", "review_state": "reviewed"}],
                    }
                ],
            },
            "habitat": None,
            "literature": {},
        },
        audience="student",
        depth="detailed",
        taxonomy_release="world-plants-2026-08",
        kg_release="kg-read-through-v1",
        deeper_routes={"atlas": "/atlas/taxon:phalaenopsis-violacea", "calyx": "/calyx"},
        generated_at="2026-09-05T17:25:00+00:00",
    )

    payload = synthesis.to_dict()
    assert payload["subject"]["taxon_id"] == "taxon:phalaenopsis-violacea"
    assert payload["relationship_model"]["morphology_anatomy_physiology"]["evidence_state"] == "supported"
    assert payload["relationship_model"]["pollination"]["evidence_state"] == "conflict"
    assert payload["relationship_model"]["habitat"]["evidence_state"] == "unavailable"
    assert payload["relationship_model"]["literature"]["evidence_state"] == "gap"
    assert payload["publication_boundary"]["knowledge_graph_mutation"] is False
    assert payload["publication_boundary"]["taxonomy_activation"] is False
    assert payload["graph_mutation"] is False

    encoded = json.dumps(payload).casefold()
    assert '"latitude"' not in encoded
    assert '"longitude"' not in encoded
    assert "10.0000/example" in encoded
    assert payload["deeper_routes"]["atlas"] == "/atlas/taxon:phalaenopsis-violacea"


def test_generated_explanation_cannot_become_relationship_evidence() -> None:
    with pytest.raises(ValueError, match="generated explanation"):
        RelationshipClaim(
            claim_id="claim:generated",
            domain="habitat",
            statement="Generated interpretation",
            evidence_state=EvidenceState.SUPPORTED,
            source_references=(),
            is_generated_interpretation=True,
        )


def test_featured_genus_pool_is_deterministic_deduplicated_and_not_limited_to_nine() -> None:
    species = [
        {
            "taxon_name": f"Phalaenopsis species-{index:02d}",
            "taxon_id": f"taxon:{index:02d}",
            "has_media": index % 2 == 0,
            "media_attribution": "Example Herbarium" if index % 2 == 0 else None,
            "sort_key": f"{index:02d}",
        }
        for index in range(12)
    ]
    species.append(dict(species[3]))

    first = build_featured_genus_pool("Phalaenopsis", species)
    second = build_featured_genus_pool("Phalaenopsis", list(reversed(species)))

    assert first["pool_size"] == 12
    assert first["pool"] == second["pool"]
    assert first["deduplication_applied"] is True
    assert first["rotation_plan"]["rotation_interval_seconds"] == 45
    assert first["rotation_plan"]["deterministic"] is True
    assert first["rotation_plan"]["client_side_inference_required"] is False
    assert first["graph_mutation"] is False

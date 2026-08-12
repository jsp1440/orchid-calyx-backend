import app.routers.matrix_identification_registry as registry_router

APPROVED = "11111111-1111-4111-8111-111111111111"
UNAVAILABLE = "22222222-2222-4222-8222-222222222222"


def _registry():
    return {
        "registry_id": "angraecum",
        "version": "2",
        "checksum_sha256": "registry-checksum",
        "publication_state": "review_required",
        "characters": [
            {
                "character": "spur_length_mm",
                "label": "Spur length",
                "weight": 3,
                "concept_id": APPROVED,
            },
            {
                "character": "flower_color",
                "label": "Flower color",
                "weight": 1,
                "concept_id": UNAVAILABLE,
            },
            {
                "character": "lip_shape",
                "label": "Lip shape",
                "weight": 2,
                "concept_id": None,
            },
            {
                "character": "column_shape",
                "label": "Column shape",
                "weight": 2,
                "concept_id": "malformed",
            },
        ],
    }


def test_mapping_readiness_distinguishes_approved_unavailable_unmapped_and_invalid(monkeypatch):
    monkeypatch.setattr(registry_router, "get_registry_version", lambda registry_id, version: _registry())

    def concept_lookup(concept_id):
        if str(concept_id) == APPROVED:
            return {
                "preferred_term": "spur",
                "review_state": "approved",
                "source_system": "oc_concepts",
                "source_record_id": APPROVED,
            }
        return None

    monkeypatch.setattr(registry_router, "_load_entry_by_concept_id", concept_lookup)

    result = registry_router.concept_mapping_status(
        "angraecum",
        "2",
        {"auth_type": "session", "actor": "reviewer@example.org"},
    )

    assert result["character_count"] == 4
    assert result["mapped_approved_count"] == 1
    assert result["mapped_unavailable_count"] == 1
    assert result["unmapped_count"] == 1
    assert result["invalid_mapping_count"] == 1
    assert result["approved_mapping_coverage"] == 0.25
    assert result["ready_for_reviewed_lexicon_guidance"] is False
    assert result["automatic_concept_matching"] is False
    assert [item["mapping_status"] for item in result["characters"]] == [
        "mapped_approved",
        "mapped_concept_unavailable",
        "unmapped",
        "invalid_concept_id",
    ]


def test_mapping_readiness_is_true_only_when_every_character_is_currently_approved(monkeypatch):
    record = _registry()
    record["characters"] = [record["characters"][0]]
    monkeypatch.setattr(registry_router, "get_registry_version", lambda registry_id, version: record)
    monkeypatch.setattr(
        registry_router,
        "_load_entry_by_concept_id",
        lambda concept_id: {
            "preferred_term": "spur",
            "review_state": "approved",
            "source_system": "oc_concepts",
            "source_record_id": str(concept_id),
        },
    )

    result = registry_router.concept_mapping_status(
        "angraecum",
        "2",
        {"auth_type": "session", "actor": "reviewer@example.org"},
    )

    assert result["approved_mapping_coverage"] == 1.0
    assert result["ready_for_reviewed_lexicon_guidance"] is True

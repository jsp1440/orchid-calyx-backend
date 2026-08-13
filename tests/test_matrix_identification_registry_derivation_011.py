from pathlib import Path

import pytest

from runtime.matrix_identification import Candidate
from runtime.matrix_identification_registry import (
    RegistryCharacter,
    create_registry_version,
    derive_registry_version_with_concept_mappings,
    get_registry_version,
)

CONCEPT_A = "11111111-1111-4111-8111-111111111111"
CONCEPT_B = "22222222-2222-4222-8222-222222222222"


def _source(root: Path):
    return create_registry_version(
        registry_id="angraecum-reviewed",
        version="1",
        title="Angraecum reviewed mapping fixture",
        scope={"genus": "Angraecum"},
        characters=[
            RegistryCharacter(
                "flower_color",
                "Flower color",
                weight=0,
                provenance={"source": "matrix fixture"},
            ),
            RegistryCharacter(
                "spur_length_mm",
                "Spur length",
                value_type="numeric_range",
                weight=3,
                provenance={"source": "matrix fixture"},
            ),
        ],
        candidates=[
            Candidate(
                "taxon:a",
                "Angraecum alpha",
                {"flower_color": "white", "spur_length_mm": {"min": 250, "max": 350}},
                provenance={"source": "candidate fixture"},
            ),
            Candidate(
                "taxon:b",
                "Angraecum beta",
                {"flower_color": "white", "spur_length_mm": {"min": 80, "max": 150}},
                provenance={"source": "candidate fixture"},
            ),
        ],
        provenance={"source": "source registry"},
        actor="source-reviewer",
        root=root,
    )["record"]


def test_reviewed_derivation_preserves_candidates_source_checksum_and_zero_weight(tmp_path: Path):
    source = _source(tmp_path)
    result = derive_registry_version_with_concept_mappings(
        registry_id="angraecum-reviewed",
        source_version="1",
        new_version="2",
        concept_mappings={
            "flower_color": CONCEPT_A,
            "spur_length_mm": CONCEPT_B,
        },
        actor="reviewer-a",
        mapping_provenance={"reviewer": "reviewer-a", "policy": "explicit"},
        root=tmp_path,
    )

    derived = result["record"]
    assert derived["version"] == "2"
    assert derived["created_by"] == "reviewer-a"
    assert derived["candidates"] == source["candidates"]
    assert derived["scope"] == source["scope"]
    assert derived["characters"][0]["weight"] == 0
    assert derived["characters"][0]["concept_id"] == CONCEPT_A
    assert derived["characters"][1]["concept_id"] == CONCEPT_B
    assert derived["provenance"]["source_registry"]["checksum_sha256"] == source["checksum_sha256"]
    assert derived["provenance"]["derivation_type"] == "reviewed_canonical_concept_mappings"
    assert derived["publication_state"] == "review_required"


def test_partial_derivation_changes_only_explicit_mapping(tmp_path: Path):
    _source(tmp_path)
    first = derive_registry_version_with_concept_mappings(
        registry_id="angraecum-reviewed",
        source_version="1",
        new_version="2",
        concept_mappings={"flower_color": CONCEPT_A},
        actor="reviewer-a",
        root=tmp_path,
    )["record"]
    second = derive_registry_version_with_concept_mappings(
        registry_id="angraecum-reviewed",
        source_version="2",
        new_version="3",
        concept_mappings={"spur_length_mm": CONCEPT_B},
        actor="reviewer-b",
        root=tmp_path,
    )["record"]

    assert first["characters"][0]["concept_id"] == CONCEPT_A
    assert first["characters"][1]["concept_id"] is None
    assert second["characters"][0]["concept_id"] == CONCEPT_A
    assert second["characters"][1]["concept_id"] == CONCEPT_B


def test_derivation_rejects_unknown_character_without_writing_version(tmp_path: Path):
    _source(tmp_path)
    with pytest.raises(ValueError, match="absent from source registry"):
        derive_registry_version_with_concept_mappings(
            registry_id="angraecum-reviewed",
            source_version="1",
            new_version="2",
            concept_mappings={"invented_character": CONCEPT_A},
            actor="reviewer-a",
            root=tmp_path,
        )
    with pytest.raises(FileNotFoundError):
        get_registry_version("angraecum-reviewed", "2", root=tmp_path)


def test_derivation_rejects_invalid_concept_uuid(tmp_path: Path):
    _source(tmp_path)
    with pytest.raises(ValueError, match="canonical concept UUID"):
        derive_registry_version_with_concept_mappings(
            registry_id="angraecum-reviewed",
            source_version="1",
            new_version="2",
            concept_mappings={"flower_color": "not-a-concept"},
            actor="reviewer-a",
            root=tmp_path,
        )


def test_derivation_is_immutable_and_idempotent_for_same_review_packet(tmp_path: Path):
    _source(tmp_path)
    kwargs = {
        "registry_id": "angraecum-reviewed",
        "source_version": "1",
        "new_version": "2",
        "concept_mappings": {"flower_color": CONCEPT_A},
        "actor": "reviewer-a",
        "mapping_provenance": {"reviewer": "reviewer-a"},
        "root": tmp_path,
    }
    first = derive_registry_version_with_concept_mappings(**kwargs)
    second = derive_registry_version_with_concept_mappings(**kwargs)
    assert first["created"] is True
    assert second["created"] is False
    assert first["record"]["checksum_sha256"] == second["record"]["checksum_sha256"]

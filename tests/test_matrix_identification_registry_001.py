from pathlib import Path

import pytest

from runtime.matrix_identification import Candidate
from runtime.matrix_identification_registry import (
    RegistryCharacter,
    candidates_from_registry,
    create_registry_version,
    get_registry_version,
    list_registry_versions,
)


def _create(root: Path):
    return create_registry_version(
        registry_id="angraecum-demo",
        version="1.0.0",
        title="Angraecum demonstration matrix",
        scope={"genus": "Angraecum", "canonical": False},
        characters=[
            RegistryCharacter(character="flower_color", label="Flower color"),
            RegistryCharacter(character="spur_length_mm", label="Spur length", value_type="numeric"),
        ],
        candidates=[
            Candidate(
                taxon_id="demo:1",
                scientific_name="Angraecum alpha",
                states={"flower_color": "white", "spur_length_mm": {"min": 250, "max": 350}},
                provenance={"source": "demonstration"},
            ),
            Candidate(
                taxon_id="demo:2",
                scientific_name="Angraecum beta",
                states={"flower_color": "green", "spur_length_mm": {"min": 50, "max": 120}},
                provenance={"source": "demonstration"},
            ),
        ],
        provenance={"source": "test fixture", "canonical": False},
        actor="pytest",
        root=root,
    )


def test_registry_version_is_immutable_and_idempotent(tmp_path: Path):
    first = _create(tmp_path)
    second = _create(tmp_path)
    assert first["created"] is True
    assert second["created"] is False
    assert first["record"]["checksum_sha256"] == second["record"]["checksum_sha256"]
    assert first["record"]["publication_state"] == "review_required"


def test_registry_rejects_same_version_with_different_content(tmp_path: Path):
    _create(tmp_path)
    with pytest.raises(ValueError, match="already exists with different content"):
        create_registry_version(
            registry_id="angraecum-demo",
            version="1.0.0",
            title="Changed title",
            scope={"genus": "Angraecum"},
            characters=[RegistryCharacter(character="flower_color", label="Flower color")],
            candidates=[
                Candidate(
                    taxon_id="demo:1",
                    scientific_name="Angraecum alpha",
                    states={"flower_color": "white"},
                )
            ],
            provenance={"source": "different"},
            actor="pytest",
            root=tmp_path,
        )


def test_registry_rejects_unregistered_candidate_character(tmp_path: Path):
    with pytest.raises(ValueError, match="unregistered characters"):
        create_registry_version(
            registry_id="bad",
            version="1",
            title="Bad",
            scope={},
            characters=[RegistryCharacter(character="flower_color", label="Flower color")],
            candidates=[
                Candidate(
                    taxon_id="demo:1",
                    scientific_name="Angraecum alpha",
                    states={"leaf_shape": "linear"},
                )
            ],
            provenance={"source": "test"},
            actor="pytest",
            root=tmp_path,
        )


def test_registry_list_get_and_candidate_conversion(tmp_path: Path):
    created = _create(tmp_path)["record"]
    loaded = get_registry_version("angraecum-demo", "1.0.0", root=tmp_path)
    assert loaded["checksum_sha256"] == created["checksum_sha256"]
    summaries = list_registry_versions(root=tmp_path)
    assert summaries[0]["candidate_count"] == 2
    assert summaries[0]["character_count"] == 2
    candidates = candidates_from_registry(loaded)
    assert [item.taxon_id for item in candidates] == ["demo:1", "demo:2"]


def test_registry_requires_provenance(tmp_path: Path):
    with pytest.raises(ValueError, match="provenance"):
        create_registry_version(
            registry_id="bad",
            version="1",
            title="Bad",
            scope={},
            characters=[RegistryCharacter(character="flower_color", label="Flower color")],
            candidates=[
                Candidate(
                    taxon_id="demo:1",
                    scientific_name="Angraecum alpha",
                    states={"flower_color": "white"},
                )
            ],
            provenance={},
            actor="pytest",
            root=tmp_path,
        )

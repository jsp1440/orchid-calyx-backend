from pathlib import Path
from uuid import uuid4

import pytest

from runtime.matrix_identification import Candidate
from runtime.matrix_identification_registry import (
    RegistryCharacter,
    create_registry_version,
    get_registry_version,
)


def test_registry_character_preserves_positional_provenance_compatibility():
    character = RegistryCharacter(
        "lip_shape",
        "Lip shape",
        None,
        "categorical",
        2.0,
        {"source": "legacy positional provenance"},
    )
    assert character.provenance == {"source": "legacy positional provenance"}
    assert character.concept_id is None


def test_registry_character_persists_canonical_concept_id(tmp_path: Path):
    concept_id = str(uuid4())
    created = create_registry_version(
        registry_id="lexicon-bound",
        version="1",
        title="Lexicon-bound Matrix fixture",
        scope={"genus": "Angraecum"},
        characters=[
            RegistryCharacter(
                "spur_length_mm",
                "Spur length",
                value_type="numeric_range",
                weight=3,
                provenance={"source": "reviewed character assertion"},
                concept_id=concept_id,
            )
        ],
        candidates=[
            Candidate("t1", "Taxon alpha", {"spur_length_mm": {"min": 250, "max": 350}}),
            Candidate("t2", "Taxon beta", {"spur_length_mm": {"min": 80, "max": 150}}),
        ],
        provenance={"source": "test"},
        actor="owner",
        root=tmp_path,
    )
    assert created["record"]["characters"][0]["concept_id"] == concept_id
    loaded = get_registry_version("lexicon-bound", "1", root=tmp_path)
    assert loaded["characters"][0]["concept_id"] == concept_id


def test_registry_character_rejects_noncanonical_concept_identifier(tmp_path: Path):
    with pytest.raises(ValueError, match="canonical concept UUID"):
        create_registry_version(
            registry_id="lexicon-invalid",
            version="1",
            title="Invalid Lexicon mapping fixture",
            scope={"genus": "Angraecum"},
            characters=[
                RegistryCharacter(
                    "spur_length_mm",
                    "Spur length",
                    value_type="numeric_range",
                    concept_id="spur",
                )
            ],
            candidates=[Candidate("t1", "Taxon alpha", {"spur_length_mm": 300})],
            provenance={"source": "test"},
            actor="owner",
            root=tmp_path,
        )

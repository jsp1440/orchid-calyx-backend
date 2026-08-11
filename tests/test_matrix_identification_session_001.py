from pathlib import Path

import pytest

from runtime.matrix_identification import Candidate
from runtime.matrix_identification_registry import RegistryCharacter, create_registry_version
from runtime.matrix_identification_session import (
    add_observation,
    create_session,
    evaluate_session,
    get_session,
)


def _registry(root: Path) -> None:
    create_registry_version(
        registry_id="angraecum-demo",
        version="1",
        title="Angraecum bounded diagnostic matrix",
        scope={"genus": "Angraecum"},
        characters=[
            RegistryCharacter("flower_color", "Flower color", weight=1),
            RegistryCharacter("spur_length_mm", "Spur length", value_type="numeric_range", weight=3),
            RegistryCharacter("flower_shape", "Flower shape", weight=1),
        ],
        candidates=[
            Candidate(
                "world-plants:angraecum-sesquipedale",
                "Angraecum sesquipedale",
                {
                    "flower_color": "white",
                    "spur_length_mm": {"min": 250, "max": 350},
                    "flower_shape": "star-shaped",
                },
            ),
            Candidate(
                "world-plants:angraecum-eburneum",
                "Angraecum eburneum",
                {
                    "flower_color": "white",
                    "spur_length_mm": {"min": 80, "max": 150},
                    "flower_shape": "star-shaped",
                },
            ),
        ],
        provenance={"source": "test governed assertions"},
        actor="test",
        root=root,
    )


def test_session_binds_registry_and_preserves_observation_provenance(tmp_path: Path):
    registry_root = tmp_path / "registries"
    session_root = tmp_path / "sessions"
    _registry(registry_root)

    session = create_session(
        registry_id="angraecum-demo",
        version="1",
        actor="owner",
        metadata={"input_mode": "guided"},
        root=session_root,
        registry_root=registry_root,
    )
    session = add_observation(
        session["session_id"],
        character="flower_color",
        value="white",
        certainty="certain",
        source={"kind": "user_observation", "interface": "guided"},
        actor="owner",
        access_actor="owner",
        root=session_root,
        registry_root=registry_root,
    )

    stored = get_session(session["session_id"], root=session_root, access_actor="owner")
    assert stored["registry"]["registry_id"] == "angraecum-demo"
    assert stored["registry"]["checksum_sha256"]
    assert stored["actor"] == "owner"
    assert stored["observations"][0]["source"]["interface"] == "guided"
    assert stored["observations"][0]["recorded_by"] == "owner"
    assert stored["observations"][0]["review_state"] == "observed"


def test_owner_scope_hides_session_from_other_owner(tmp_path: Path):
    registry_root = tmp_path / "registries"
    session_root = tmp_path / "sessions"
    _registry(registry_root)
    session = create_session(
        registry_id="angraecum-demo",
        version="1",
        actor="owner-a",
        root=session_root,
        registry_root=registry_root,
    )

    with pytest.raises(FileNotFoundError, match="identification session not found"):
        get_session(session["session_id"], root=session_root, access_actor="owner-b")
    with pytest.raises(FileNotFoundError, match="identification session not found"):
        evaluate_session(
            session["session_id"],
            access_actor="owner-b",
            root=session_root,
            registry_root=registry_root,
        )
    with pytest.raises(FileNotFoundError, match="identification session not found"):
        add_observation(
            session["session_id"],
            character="flower_color",
            value="white",
            actor="owner-b",
            access_actor="owner-b",
            root=session_root,
            registry_root=registry_root,
        )

    stored = get_session(session["session_id"], root=session_root, access_actor="owner-a")
    assert stored["revision"] == 0
    assert stored["observations"] == []


def test_trusted_system_scope_can_access_session_without_impersonating_owner(tmp_path: Path):
    registry_root = tmp_path / "registries"
    session_root = tmp_path / "sessions"
    _registry(registry_root)
    session = create_session(
        registry_id="angraecum-demo",
        version="1",
        actor="owner-a",
        root=session_root,
        registry_root=registry_root,
    )

    system_read = get_session(session["session_id"], root=session_root, access_actor=None)
    assert system_read["actor"] == "owner-a"
    system_eval = evaluate_session(
        session["session_id"],
        access_actor=None,
        root=session_root,
        registry_root=registry_root,
    )
    assert system_eval["session"]["actor"] == "owner-a"


def test_observation_rejects_character_outside_bound_registry(tmp_path: Path):
    registry_root = tmp_path / "registries"
    session_root = tmp_path / "sessions"
    _registry(registry_root)
    session = create_session(
        registry_id="angraecum-demo",
        version="1",
        actor="owner",
        root=session_root,
        registry_root=registry_root,
    )

    with pytest.raises(ValueError, match="character is not defined by bound registry"):
        add_observation(
            session["session_id"],
            character="invented_character",
            value="invented_state",
            actor="owner",
            access_actor="owner",
            root=session_root,
            registry_root=registry_root,
        )

    stored = get_session(session["session_id"], root=session_root, access_actor="owner")
    assert stored["revision"] == 0
    assert stored["observations"] == []


def test_next_observation_prefers_discriminating_weighted_character(tmp_path: Path):
    registry_root = tmp_path / "registries"
    session_root = tmp_path / "sessions"
    _registry(registry_root)

    session = create_session(
        registry_id="angraecum-demo",
        version="1",
        actor="owner",
        root=session_root,
        registry_root=registry_root,
    )
    add_observation(
        session["session_id"],
        character="flower_color",
        value="white",
        actor="owner",
        access_actor="owner",
        root=session_root,
        registry_root=registry_root,
    )
    result = evaluate_session(
        session["session_id"],
        access_actor="owner",
        root=session_root,
        registry_root=registry_root,
    )

    assert result["report"]["candidates"][0]["score"] == 1.0
    assert result["next_observation"]["character"] == "spur_length_mm"
    assert result["next_observation"]["reason_code"] == "highest_deterministic_discrimination"


def test_observing_next_character_revises_ranking_and_removes_it_from_next_question(tmp_path: Path):
    registry_root = tmp_path / "registries"
    session_root = tmp_path / "sessions"
    _registry(registry_root)

    session = create_session(
        registry_id="angraecum-demo",
        version="1",
        actor="owner",
        root=session_root,
        registry_root=registry_root,
    )
    add_observation(
        session["session_id"],
        character="flower_color",
        value="white",
        actor="owner",
        access_actor="owner",
        root=session_root,
        registry_root=registry_root,
    )
    add_observation(
        session["session_id"],
        character="spur_length_mm",
        value=300,
        actor="owner",
        access_actor="owner",
        root=session_root,
        registry_root=registry_root,
    )
    result = evaluate_session(
        session["session_id"],
        access_actor="owner",
        root=session_root,
        registry_root=registry_root,
    )

    assert result["report"]["candidates"][0]["taxon_id"].endswith("sesquipedale")
    if result["next_observation"] is not None:
        assert result["next_observation"]["character"] != "spur_length_mm"

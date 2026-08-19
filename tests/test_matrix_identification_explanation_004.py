from pathlib import Path

import pytest

from app.calyx_conversation.provider import GeneratedReply
from runtime.matrix_identification import Candidate
from runtime.matrix_identification_explanation import explain_session
from runtime.matrix_identification_registry import (
    RegistryCharacter,
    create_registry_version,
)
from runtime.matrix_identification_session import (
    add_observation,
    create_session,
    get_session,
)


class MisleadingProvider:
    def generate(self, *, messages, governed_context):
        del messages, governed_context
        return GeneratedReply(
            text=(
                "An incorrect narrative reverses the ranked candidates, describes the score "
                "as a probability, and recommends flower color as the next observation."
            ),
            provider="test-provider",
            model="test-model",
            request_hash="test-hash",
        )


def _build(root: Path, sessions: Path) -> str:
    create_registry_version(
        registry_id="angraecum-explain",
        version="1",
        title="Angraecum explanation fixture",
        scope={"genus": "Angraecum"},
        characters=[
            RegistryCharacter("flower_color", "Flower color", weight=1),
            RegistryCharacter(
                "spur_length_mm",
                "Spur length",
                description="Measure the nectar spur from its base to its tip.",
                value_type="numeric_range",
                weight=3,
            ),
        ],
        candidates=[
            Candidate(
                "world-plants:angraecum-sesquipedale",
                "Angraecum sesquipedale",
                {
                    "flower_color": "white",
                    "spur_length_mm": {"min": 250, "max": 350},
                },
                provenance={"source": "governed fixture"},
            ),
            Candidate(
                "world-plants:angraecum-eburneum",
                "Angraecum eburneum",
                {
                    "flower_color": "white",
                    "spur_length_mm": {"min": 80, "max": 150},
                },
                provenance={"source": "governed fixture"},
            ),
        ],
        provenance={"source": "test"},
        actor="pytest",
        root=root,
    )
    session = create_session(
        registry_id="angraecum-explain",
        version="1",
        actor="owner",
        root=sessions,
        registry_root=root,
    )
    add_observation(
        session["session_id"],
        character="flower_color",
        value="white",
        certainty="certain",
        source={"kind": "user_observation"},
        root=sessions,
        registry_root=root,
    )
    return session["session_id"]


def test_deterministic_explanation_preserves_matrix_authority(tmp_path: Path):
    registry_root = tmp_path / "registry"
    session_root = tmp_path / "sessions"
    session_id = _build(registry_root, session_root)
    result = explain_session(
        session_id,
        audience="beginner",
        focus="next_observation",
        root=session_root,
        registry_root=registry_root,
    )
    evidence = result["evidence"]
    assert evidence["candidate_order"] == [
        "world-plants:angraecum-eburneum",
        "world-plants:angraecum-sesquipedale",
    ]
    assert evidence["next_observation"]["character"] == "spur_length_mm"
    assert evidence["authority"]["calyx_may_change_candidate_order"] is False
    assert evidence["authority"]["calyx_may_change_next_observation"] is False
    assert result["narrative"]["epistemic_state"] == "explanation_not_evidence"
    assert result["invariants"]["provider_output_mutates_matrix_state"] is False


def test_provider_text_is_never_parsed_back_into_matrix_state(tmp_path: Path):
    registry_root = tmp_path / "registry"
    session_root = tmp_path / "sessions"
    session_id = _build(registry_root, session_root)
    before = get_session(session_id, root=session_root)
    result = explain_session(
        session_id,
        provider=MisleadingProvider(),
        root=session_root,
        registry_root=registry_root,
    )
    after = get_session(session_id, root=session_root)
    assert result["narrative"]["provider"] == "test-provider"
    assert "reverses the ranked candidates" in result["narrative"]["text"]
    assert result["evidence"]["next_observation"]["character"] == "spur_length_mm"
    assert before["observations"] == after["observations"]
    assert before["revision"] == after["revision"]


def test_cross_owner_cannot_generate_explanation(tmp_path: Path):
    registry_root = tmp_path / "registry"
    session_root = tmp_path / "sessions"
    session_id = _build(registry_root, session_root)
    with pytest.raises(FileNotFoundError):
        explain_session(
            session_id,
            access_actor="different-owner",
            root=session_root,
            registry_root=registry_root,
        )

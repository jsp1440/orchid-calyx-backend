from __future__ import annotations

import pytest

from app.calyx_orchestrator.artifact_registry import (
    ArtifactRegistration,
    ArtifactRelationType,
    ImmutableArtifactRegistry,
)


def registration(artifact_id: str = "artifact-1", content: bytes = b"evidence", **overrides):
    values = {
        "artifact_id": artifact_id,
        "content": content,
        "media_type": "application/json",
        "source_uri": f"github:artifact/{artifact_id}",
        "producer_assignment_id": "assignment-1",
        "license": "internal-review-only",
        "evidence_uris": ("github:issue/440",),
        "metadata": {"published": False, "approved": False},
    }
    values.update(overrides)
    return ArtifactRegistration(**values)


def test_registration_is_immutable_and_idempotent():
    registry = ImmutableArtifactRegistry()
    first = registry.register(registration())
    replay = registry.register(registration())
    assert first.created is True
    assert replay.created is False
    assert first.record == replay.record
    with pytest.raises(ValueError, match="IMMUTABLE_ARTIFACT_CONFLICT"):
        registry.register(registration(content=b"changed"))


def test_duplicate_content_is_detected_without_collapsing_identity():
    registry = ImmutableArtifactRegistry()
    registry.register(registration("artifact-1"))
    duplicate = registry.register(registration("artifact-2", source_uri="brain:artifact/2"))
    assert duplicate.created is True
    assert duplicate.duplicate_content_of == "artifact-1"
    assert registry.snapshot()["artifact_count"] == 2
    assert registry.snapshot()["unique_content_count"] == 1


def test_lineage_requires_registered_artifacts_and_is_idempotent():
    registry = ImmutableArtifactRegistry()
    registry.register(registration("receipt"))
    registry.register(registration("output", source_uri="brain:artifact/output"))
    first = registry.relate(
        source_artifact_id="output",
        relation=ArtifactRelationType.DERIVED_FROM,
        target_artifact_id="receipt",
    )
    replay = registry.relate(
        source_artifact_id="output",
        relation="derived_from",
        target_artifact_id="receipt",
    )
    assert first == replay
    assert len(registry.lineage("output")) == 1
    with pytest.raises(LookupError, match="ARTIFACT_NOT_FOUND"):
        registry.relate(
            source_artifact_id="missing",
            relation="derived_from",
            target_artifact_id="receipt",
        )


def test_missing_evidence_is_rejected_until_evidence_relationship_exists():
    registry = ImmutableArtifactRegistry()
    registry.register(registration("claim", evidence_uris=()))
    registry.register(registration("evidence"))
    with pytest.raises(ValueError, match="ARTIFACT_EVIDENCE_REQUIRED"):
        registry.require_evidence("claim")
    registry.relate(
        source_artifact_id="claim",
        relation=ArtifactRelationType.EVIDENCES,
        target_artifact_id="evidence",
    )
    assert registry.require_evidence("claim").artifact_id == "claim"


def test_discovery_is_read_only_deterministic_and_filterable():
    registry = ImmutableArtifactRegistry()
    registry.register(registration("b", producer_assignment_id="assignment-2"))
    registry.register(registration("a", media_type="text/plain"))
    assert [item.artifact_id for item in registry.discover()] == ["a", "b"]
    assert [item.artifact_id for item in registry.discover(producer_assignment_id="assignment-2")] == ["b"]
    assert [item.artifact_id for item in registry.discover(media_type="text/plain")] == ["a"]


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"artifact_id": ""}, "ARTIFACT_ID_REQUIRED"),
        ({"content": b""}, "ARTIFACT_CONTENT_REQUIRED"),
        ({"media_type": "json"}, "ARTIFACT_MEDIA_TYPE_INVALID"),
        ({"source_uri": "not-a-uri"}, "ARTIFACT_SOURCE_URI_INVALID"),
        ({"producer_assignment_id": ""}, "PRODUCER_ASSIGNMENT_REQUIRED"),
        ({"evidence_uris": ("invalid",)}, "EVIDENCE_URI_INVALID"),
    ],
)
def test_invalid_registration_fails_closed(overrides, code):
    with pytest.raises(ValueError, match=code):
        ImmutableArtifactRegistry().register(registration(**overrides))

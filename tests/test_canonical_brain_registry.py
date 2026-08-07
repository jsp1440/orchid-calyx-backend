from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.canonical_brain import (
    BrainObject,
    BrainRelationship,
    CanonicalBrainRegistry,
    build_canonical_brain_fixture,
)


def test_search_and_intent_alignment_are_deterministic():
    registry = build_canonical_brain_fixture()
    assert registry.search("FigureLabs glossary")[0].object_id == "architecture:knowledge-explorer"
    assert [x.object_id for x in registry.aligned_intents("architecture:atlas")] == ["intent:preserve-biodiversity"]
    assert registry.snapshot().snapshot_checksum == registry.snapshot().snapshot_checksum


def test_registry_is_idempotent_and_rejects_conflicts():
    registry = build_canonical_brain_fixture()
    record = registry.get("architecture:brain")
    assert record is not None
    assert registry.register_object(record) == record
    with pytest.raises(ValueError):
        registry.register_object(record.model_copy(update={"title": "Conflicting title"}))


def test_relationships_require_registered_endpoints():
    registry = CanonicalBrainRegistry()
    with pytest.raises(ValueError):
        registry.register_relationship(
            BrainRelationship(
                relationship_id="rel:test",
                subject_id="architecture:first",
                relationship_type="depends_on",
                object_id="architecture:second",
                rationale="Endpoints must exist first.",
                source_uri="test://relationship",
            )
        )


def test_alias_and_supersession_validation():
    common = {
        "object_type": "architecture",
        "summary": "Architecture test record.",
        "tags": [],
        "source_uri": "test://object",
        "content_checksum": "a" * 64,
        "created_at": datetime.now(timezone.utc),
    }
    with pytest.raises(ValidationError):
        BrainObject(
            object_id="architecture:aliases",
            title="Aliases",
            aliases=["Atlas", "atlas"],
            lifecycle="approved",
            **common,
        )
    with pytest.raises(ValidationError):
        BrainObject(
            object_id="architecture:old",
            title="Old architecture",
            aliases=[],
            lifecycle="superseded",
            **common,
        )

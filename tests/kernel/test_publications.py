from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from app.kernel import (
    OCIDFactory,
    OCIDKind,
    Publication,
    PublicationManifest,
    PublicationStatus,
    ScientificObjectValidationError,
)


def test_publication_defaults_to_publication_ocid() -> None:
    publication = Publication(
        manifest=PublicationManifest((OCIDFactory.new(),)),
    )

    assert publication.ocid.kind is OCIDKind.PUBLICATION
    assert publication.status is PublicationStatus.DRAFT
    assert publication.object_count == 1
    assert not publication.is_committed


def test_publication_manifest_requires_objects() -> None:
    with pytest.raises(ScientificObjectValidationError, match="at least one object"):
        PublicationManifest(())


def test_publication_manifest_rejects_duplicate_objects() -> None:
    object_ocid = OCIDFactory.new()

    with pytest.raises(ScientificObjectValidationError, match="must be unique"):
        PublicationManifest((object_ocid, object_ocid))


def test_publication_manifest_requires_roots_in_objects() -> None:
    with pytest.raises(ScientificObjectValidationError, match="roots"):
        PublicationManifest(
            (OCIDFactory.new(),),
            root_ocids=(OCIDFactory.new(),),
        )


def test_committed_publication_requires_commit_metadata() -> None:
    with pytest.raises(ScientificObjectValidationError, match="require prepared_by"):
        Publication(
            manifest=PublicationManifest((OCIDFactory.new(),)),
            status=PublicationStatus.COMMITTED,
        )


def test_committed_publication_normalizes_timestamp_to_utc() -> None:
    local_tz = timezone(timedelta(hours=-7))
    committed_at = datetime(2026, 7, 23, 12, tzinfo=local_tz)
    publication = Publication(
        created_at=datetime(2026, 7, 23, 18, tzinfo=timezone.utc),
        manifest=PublicationManifest((OCIDFactory.new(),)),
        status=PublicationStatus.COMMITTED,
        prepared_by="curator",
        committed_by="reviewer",
        committed_at=committed_at,
    )

    assert publication.committed_at == datetime(
        2026, 7, 23, 19, tzinfo=timezone.utc
    )
    assert publication.is_committed


def test_rejected_publication_requires_reason() -> None:
    with pytest.raises(ScientificObjectValidationError, match="rejection_reason"):
        Publication(
            manifest=PublicationManifest((OCIDFactory.new(),)),
            status=PublicationStatus.REJECTED,
        )


def test_publication_is_immutable_and_annotations_are_read_only() -> None:
    publication = Publication(
        manifest=PublicationManifest((OCIDFactory.new(),)),
        annotations={"release": "pilot"},
    )

    with pytest.raises(FrozenInstanceError):
        publication.status = PublicationStatus.COMMITTED  # type: ignore[misc]
    with pytest.raises(TypeError):
        publication.annotations["release"] = "changed"  # type: ignore[index]

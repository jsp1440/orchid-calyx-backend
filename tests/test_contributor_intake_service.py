"""Service-level tests for the governed contributor intake workspace.

Covers original-byte preservation, server-side checksum authority, batch
manifest persistence, cross-batch checksum dedup, batch-id replay idempotency,
contributor identity governance, and filename→taxon→session mapping.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

import pytest

from runtime.contributor_intake_service import ContributorIntakeService
from runtime.matrix_identification import Candidate
from runtime.matrix_identification_registry import (
    RegistryCharacter,
    create_registry_version,
)
from runtime.matrix_identification_session import get_session

PHOTO_A = b"\xff\xd8\xff\xe0" + b"orchid-photo-a" * 8
PHOTO_B = b"\x89PNG\r\n\x1a\n" + b"orchid-photo-b" * 8


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _submission(**overrides):
    base = {
        "original_filename": "besseae_flower.jpg",
        "content_base64": _b64(PHOTO_A),
        "contributor_display_name": "R. Orchidist",
        "permission_grant": "cc-by-nc",
        "rights_holder_affirmed": True,
        "taxon_certainty": "unknown",
        "candidate_taxa": [{"name": "Phragmipedium besseae"}],
        "provenance": {"channel": "member-upload"},
    }
    base.update(overrides)
    return base


def _make_registry(root: Path) -> None:
    os.environ["CALYX_MATRIX_REGISTRY_DIR"] = str(root / "registries")
    create_registry_version(
        registry_id="phragmipedium-demo",
        version="1",
        title="Phragmipedium bounded diagnostic matrix",
        scope={"genus": "Phragmipedium"},
        characters=[RegistryCharacter("petal_color", "Petal color", weight=1)],
        candidates=[
            Candidate(
                "world-plants:phragmipedium-besseae",
                "Phragmipedium besseae",
                {"petal_color": "red"},
                provenance={"source": "test"},
            )
        ],
        provenance={"source": "test"},
        actor="test",
    )


def test_original_bytes_preserved_content_addressed(tmp_path) -> None:
    service = ContributorIntakeService(tmp_path / "intake")
    manifest = service.intake_batch([_submission()], actor="member-7")
    entry = manifest["filename_mapping"][0]
    assert entry["status"] == "staged"
    ref = entry["original_object_ref"]
    stored = (tmp_path / "intake" / ref).read_bytes()
    assert stored == PHOTO_A
    assert hashlib.sha256(stored).hexdigest() == entry["content_sha256"]
    assert ref.startswith("originals/")


def test_server_checksum_overrides_and_mismatch_rejected(tmp_path) -> None:
    service = ContributorIntakeService(tmp_path / "intake")
    computed = hashlib.sha256(PHOTO_A).hexdigest()
    manifest = service.intake_batch(
        [_submission(content_sha256=computed)], actor="member-7"
    )
    assert manifest["filename_mapping"][0]["status"] == "staged"
    with pytest.raises(ValueError, match="content_sha256 mismatch"):
        service.intake_batch(
            [_submission(content_sha256="0" * 64, batch_id=None)],
            actor="member-7",
            batch_id="batch-mismatch",
        )


def test_contributor_identity_forced_to_actor_unless_automation(tmp_path) -> None:
    service = ContributorIntakeService(tmp_path / "intake")
    manifest = service.intake_batch(
        [_submission(contributor_id="someone-else")], actor="member-7"
    )
    staged = manifest["staged"][0]
    assert staged["contributor_id"] == "member-7"
    manifest2 = service.intake_batch(
        [
            _submission(
                content_base64=_b64(PHOTO_B),
                original_filename="b.png",
                contributor_id="someone-else",
            )
        ],
        actor="backend_api_key",
        batch_id="batch-automation",
        allow_contributor_override=True,
    )
    assert manifest2["staged"][0]["contributor_id"] == "someone-else"


def test_batch_manifest_persisted_and_replay_idempotent(tmp_path) -> None:
    service = ContributorIntakeService(tmp_path / "intake")
    first = service.intake_batch([_submission()], actor="member-7", batch_id="batch-1")
    assert first["idempotent_replay"] is False
    on_disk = json.loads(
        (tmp_path / "intake" / "batches" / "batch-1.json").read_text(encoding="utf-8")
    )
    assert on_disk["schema_version"] == "matrix-contributor-intake-batch/v1"
    replay = service.intake_batch([_submission()], actor="member-7", batch_id="batch-1")
    assert replay["idempotent_replay"] is True
    assert replay["summary"]["staged_count"] == 1
    assert service.get_batch_manifest("batch-1")["batch_id"] == "batch-1"


def test_cross_batch_checksum_dedup(tmp_path) -> None:
    service = ContributorIntakeService(tmp_path / "intake")
    service.intake_batch([_submission()], actor="member-7", batch_id="batch-1")
    second = service.intake_batch(
        [_submission(original_filename="renamed_copy.jpg")],
        actor="member-8",
        batch_id="batch-2",
    )
    assert second["summary"]["staged_count"] == 0
    assert second["summary"]["duplicate_skipped"] == 1
    assert second["filename_mapping"][0]["status"] == "duplicate_skipped"


def test_missing_permission_and_unsupported_media_rejected(tmp_path) -> None:
    service = ContributorIntakeService(tmp_path / "intake")
    manifest = service.intake_batch(
        [
            _submission(permission_grant=None, original_filename="no_permit.jpg"),
            _submission(
                original_filename="clip.mp4",
                content_base64=_b64(b"video-bytes"),
                mime_type="video/mp4",
            ),
        ],
        actor="member-7",
        batch_id="batch-rejects",
    )
    reasons = {
        item["original_filename"]: item["status"] for item in manifest["filename_mapping"]
    }
    assert reasons == {"no_permit.jpg": "rejected", "clip.mp4": "rejected"}
    recorded = {item["reason"] for item in manifest["rejected"]}
    assert "missing_or_unrecognized_permission_grant" in recorded
    assert "unsupported_media_type" in recorded


def test_open_sessions_maps_filename_to_taxon_and_session(tmp_path) -> None:
    _make_registry(tmp_path)
    os.environ["CALYX_MATRIX_SESSION_DIR"] = str(tmp_path / "sessions")
    service = ContributorIntakeService(tmp_path / "intake")
    manifest = service.intake_batch(
        [
            _submission(),
            _submission(
                original_filename="kovachii.png",
                content_base64=_b64(PHOTO_B),
                taxon_name="Phragmipedium kovachii",
                taxon_certainty="suggested",
            ),
        ],
        actor="member-7",
        batch_id="batch-sessions",
        open_sessions=True,
        registry_id="phragmipedium-demo",
        registry_version="1",
        canonical_lookup={"Phragmipedium kovachii": "world-plants:phragmipedium-kovachii"},
    )
    assert manifest["sessions_opened"] == 2
    mapping = {item["original_filename"]: item for item in manifest["filename_mapping"]}
    first = mapping["besseae_flower.jpg"]
    assert first["status"] == "staged"
    assert first["session"]["registry_id"] == "phragmipedium-demo"
    second = mapping["kovachii.png"]
    assert second["taxon_certainty"] == "suggested"
    assert second["canonical_taxon_id"] == "world-plants:phragmipedium-kovachii"
    assert second["reconciliation_state"] == "resolved"
    session = get_session(first["session"]["session_id"])
    assert session["metadata"]["contributor_batch_id"] == "batch-sessions"
    assert session["metadata"]["content_sha256"] == first["content_sha256"]


def test_session_replay_does_not_duplicate_sessions(tmp_path) -> None:
    _make_registry(tmp_path)
    os.environ["CALYX_MATRIX_SESSION_DIR"] = str(tmp_path / "sessions")
    service = ContributorIntakeService(tmp_path / "intake")
    kwargs = dict(
        actor="member-7",
        batch_id="batch-replay",
        open_sessions=True,
        registry_id="phragmipedium-demo",
        registry_version="1",
    )
    first = service.intake_batch([_submission()], **kwargs)
    replay = service.intake_batch([_submission()], **kwargs)
    assert replay["idempotent_replay"] is True
    assert (
        replay["filename_mapping"][0]["session"]["session_id"]
        == first["filename_mapping"][0]["session"]["session_id"]
    )
    session_files = list((tmp_path / "sessions").glob("*.json"))
    assert len(session_files) == 1

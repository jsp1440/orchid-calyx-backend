from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.archive.policy import ArchivePolicy, ArchivePolicyError
from app.archive.scanner import ArchiveScanner


def policy(root: Path, **overrides: int) -> ArchivePolicy:
    values = {
        "max_file_bytes": 1024,
        "max_zip_members": 10,
        "max_zip_uncompressed_bytes": 4096,
        "max_zip_expansion_ratio": 20,
        "max_path_depth": 5,
    }
    values.update(overrides)
    return ArchivePolicy((root.resolve(),), **values)


def test_source_allowlist_accepts_descendant_and_rejects_outside(tmp_path: Path):
    approved = tmp_path / "approved"
    approved.mkdir()
    source = approved / "notes"
    source.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    configured = policy(approved)
    assert configured.authorize_source(source) == source.resolve()
    with pytest.raises(ArchivePolicyError, match="outside approved roots"):
        configured.authorize_source(outside)


def test_empty_allowlist_disables_imports(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(ArchivePolicyError, match="imports are disabled"):
        ArchivePolicy(()).authorize_source(source)


def test_scanner_rejects_oversized_file(tmp_path: Path):
    oversized = tmp_path / "large.txt"
    oversized.write_bytes(b"x" * 20)
    scanner = ArchiveScanner(policy(tmp_path, max_file_bytes=10))
    with pytest.raises(ArchivePolicyError, match="maximum size"):
        list(scanner.scan(tmp_path))


def test_zip_member_count_limit(tmp_path: Path):
    archive = tmp_path / "many.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("one.txt", "1")
        handle.writestr("two.txt", "2")
    scanner = ArchiveScanner(policy(tmp_path, max_zip_members=1))
    with pytest.raises(ArchivePolicyError, match="too many members"):
        scanner.extract_zip(archive, tmp_path / "out")


def test_zip_uncompressed_size_limit(tmp_path: Path):
    archive = tmp_path / "large.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        handle.writestr("large.txt", "x" * 200)
    scanner = ArchiveScanner(
        policy(tmp_path, max_file_bytes=1024, max_zip_uncompressed_bytes=100)
    )
    with pytest.raises(ArchivePolicyError, match="uncompressed size"):
        scanner.extract_zip(archive, tmp_path / "out")


def test_zip_path_depth_limit(tmp_path: Path):
    archive = tmp_path / "deep.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("a/b/c/d.txt", "deep")
    scanner = ArchiveScanner(policy(tmp_path, max_path_depth=3))
    with pytest.raises(ArchivePolicyError, match="path depth"):
        scanner.extract_zip(archive, tmp_path / "out")


def test_hardening_migration_defines_execution_controls():
    sql = Path("migrations/107_archive_production_hardening.sql").read_text(
        encoding="utf-8"
    )
    for column in (
        "cancel_requested",
        "attempt_count",
        "heartbeat_at",
        "lease_owner",
        "lease_expires_at",
        "dispatch_reference",
    ):
        assert column in sql
    for state in ("queued", "cancelling", "cancelled"):
        assert state in sql


def test_run_control_fences_lease_updates_by_attempt():
    source = Path("app/archive/control.py").read_text(encoding="utf-8")
    assert "attempt_count=%s" in source
    assert "def lease_guard" in source
    assert "status='cancelled'" in source
    assert "def fail_unclaimed" in source


def test_rollback_normalizes_hardening_only_states():
    sql = Path("migrations/107_archive_production_hardening_rollback.sql").read_text(
        encoding="utf-8"
    )
    assert "WHEN status = 'queued' THEN 'interrupted'" in sql
    assert "WHEN status = 'cancelling' THEN 'interrupted'" in sql
    assert "WHEN status = 'cancelled' THEN 'failed'" in sql
    assert sql.index("UPDATE archive_import_runs") < sql.index(
        "ADD CONSTRAINT archive_import_runs_status_check"
    )

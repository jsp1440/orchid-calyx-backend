from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from app.archive.activation import (
    REQUIRED_ARCHIVE_TABLES,
    REQUIRED_HARDENING_COLUMNS,
    ArchiveActivationInspector,
)
from app.archive.policy import ArchivePolicy


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _Connection:
    def __init__(self, *, tables=(), columns=()):
        self.tables = tables
        self.columns = columns

    def execute(self, sql, params=None):
        if "information_schema.tables" in sql:
            return _Result([{"table_name": item} for item in self.tables])
        if "information_schema.columns" in sql:
            return _Result([{"column_name": item} for item in self.columns])
        raise AssertionError(f"unexpected SQL: {sql}")


class _Registry:
    def __init__(self, *, tables=(), columns=()):
        self.conn = _Connection(tables=tables, columns=columns)

    @contextmanager
    def connection(self):
        yield self.conn


def _policy(tmp_path: Path) -> ArchivePolicy:
    root = tmp_path / "approved"
    root.mkdir(exist_ok=True)
    return ArchivePolicy((root.resolve(),))


def test_activation_reports_exact_migration_and_policy_blockers(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured-but-not-exposed")
    inspector = ArchiveActivationInspector(
        _Registry(tables=(), columns=()),
        policy_factory=lambda: ArchivePolicy(()),
    )
    evidence = inspector.inspect()
    assert evidence.database_configured is True
    assert evidence.archive_schema_complete is False
    assert evidence.hardening_complete is False
    assert evidence.allowed_source_roots_configured is False
    assert evidence.missing_tables == tuple(sorted(REQUIRED_ARCHIVE_TABLES))
    assert evidence.missing_hardening_columns == tuple(sorted(REQUIRED_HARDENING_COLUMNS))
    assert evidence.blockers == (
        "ARCHIVE_MIGRATION_106_NOT_CERTIFIED",
        "ARCHIVE_HARDENING_107_NOT_CERTIFIED",
        "ARCHIVE_ALLOWED_ROOTS_NOT_CONFIGURED",
    )
    assert "postgresql" not in str(evidence)


def test_activation_certifies_complete_schema_without_authorizing_import(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured-but-not-exposed")
    inspector = ArchiveActivationInspector(
        _Registry(tables=REQUIRED_ARCHIVE_TABLES, columns=REQUIRED_HARDENING_COLUMNS),
        policy_factory=lambda: _policy(tmp_path),
    )
    evidence = inspector.inspect()
    assert evidence.archive_schema_complete is True
    assert evidence.hardening_complete is True
    assert evidence.allowed_source_roots_configured is True
    assert evidence.blockers == ()
    assert evidence.production_import_authorized is False
    assert evidence.graph_publication_authorized is False
    assert evidence.unrestricted_filesystem_scanning_authorized is False
    assert evidence.deployment_authorized is False


def test_sanitized_activation_evidence_is_content_addressed_and_path_free(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured-but-not-exposed")
    inspector = ArchiveActivationInspector(
        _Registry(tables=REQUIRED_ARCHIVE_TABLES, columns=REQUIRED_HARDENING_COLUMNS),
        policy_factory=lambda: _policy(tmp_path),
    )
    receipt = inspector.sanitized_evidence()
    assert receipt["sanitized"] is True
    assert receipt["contains_secrets"] is False
    assert receipt["contains_source_paths"] is False
    assert receipt["artifact"]["artifact_id"].startswith("archive-activation:")
    assert str(tmp_path) not in str(receipt)
    assert "postgresql://" not in str(receipt)


def test_contract_inventory_reuses_archive_contracts_and_forbids_graph_write():
    inventory = ArchiveActivationInspector(_Registry()).contract_inventory()
    assert set(inventory["contracts"].values()) == set(REQUIRED_ARCHIVE_TABLES)
    assert inventory["bounded_import"] is True
    assert inventory["safe_zip_extraction_required"] is True
    assert inventory["duplicate_fingerprint_handling_required"] is True
    assert inventory["malformed_file_continuation_required"] is True
    assert inventory["checkpoint_resume_required"] is True
    assert inventory["canonical_graph_write_authorized"] is False


def test_existing_archive_runtime_preserves_required_ingestion_controls():
    scanner = Path("app/archive/scanner.py").read_text(encoding="utf-8")
    importer = Path("app/archive/importer.py").read_text(encoding="utf-8")
    routes = Path("app/archive/routes.py").read_text(encoding="utf-8")
    assert "path traversal" in scanner or "relative_to" in scanner
    assert "duplicates_skipped" in importer
    assert "file_error" in importer
    assert "checkpoint" in importer
    assert "authorize_source" in routes
    assert 'dependencies=[Depends(verify_owner_or_api_key)]' in routes


def test_migrations_are_additive_and_do_not_target_canonical_graph():
    migration_106 = Path("migrations/106_institutional_archive_manager.sql").read_text(encoding="utf-8")
    migration_107 = Path("migrations/107_archive_production_hardening.sql").read_text(encoding="utf-8")
    for table in REQUIRED_ARCHIVE_TABLES:
        assert table in migration_106
    combined = f"{migration_106}\n{migration_107}".lower()
    assert "oc_graph" not in combined
    assert "truncate" not in combined

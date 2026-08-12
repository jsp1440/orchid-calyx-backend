from pathlib import Path

from scripts.calyx_matrix_registry_migrate import (
    execute_registry_migration,
    plan_registry_migration,
)


def _record(registry_id: str, version: str, checksum: str) -> dict:
    return {
        "registry_id": registry_id,
        "version": version,
        "checksum_sha256": checksum,
        "publication_state": "review_required",
        "created_by": "reviewer",
        "created_at": "2026-08-12T00:00:00+00:00",
    }


class FakeSource:
    def __init__(self, records):
        self.records = list(records)
        self.root = Path("/tmp/test-matrix-registry")

    def list_records(self):
        return list(self.records)


class FakeDestination:
    def __init__(self, records, *, schema_ready=True):
        self.records = list(records)
        self.schema_ready = schema_ready
        self.saved = []

    def schema_inspection(self):
        return {
            "migration_613_schema_ready": self.schema_ready,
            "blockers": [] if self.schema_ready else ["MATRIX_REGISTRY_TABLE_NOT_FOUND"],
        }

    def list_records(self):
        return list(self.records)

    def save(self, record):
        self.saved.append(record)
        key = (record["registry_id"], record["version"])
        existing = next(
            (
                item
                for item in self.records
                if (item["registry_id"], item["version"]) == key
            ),
            None,
        )
        if existing is not None:
            if existing["checksum_sha256"] != record["checksum_sha256"]:
                raise ValueError("registry version already exists with different content")
            return {"created": False, "record": existing}
        self.records.append(record)
        return {"created": True, "record": record}


def test_plan_selects_only_missing_file_backed_versions():
    file_records = [
        _record("angraecum", "1", "a" * 64),
        _record("angraecum", "2", "b" * 64),
    ]
    database_records = [_record("angraecum", "1", "a" * 64)]

    plan = plan_registry_migration(file_records, database_records)

    assert plan["copy_count"] == 1
    assert [(item["registry_id"], item["version"]) for item in plan["copy_records"]] == [
        ("angraecum", "2")
    ]
    assert plan["apply_allowed"] is True


def test_dry_run_performs_zero_writes_and_reports_would_copy():
    source = FakeSource([_record("angraecum", "1", "a" * 64)])
    destination = FakeDestination([])

    result = execute_registry_migration(source=source, destination=destination, apply=False)

    assert result["mode"] == "dry_run"
    assert result["applied"] is False
    assert destination.saved == []
    assert result["would_copy"] == [
        {
            "registry_id": "angraecum",
            "version": "1",
            "checksum_sha256": "a" * 64,
        }
    ]
    assert result["automatic_activation"] is False


def test_checksum_conflict_blocks_even_explicit_apply_before_any_write():
    source = FakeSource([_record("angraecum", "1", "a" * 64)])
    destination = FakeDestination([_record("angraecum", "1", "b" * 64)])

    result = execute_registry_migration(source=source, destination=destination, apply=True)

    assert result["applied"] is False
    assert result["blockers"] == ["MATRIX_REGISTRY_CHECKSUM_MISMATCH"]
    assert destination.saved == []


def test_apply_copies_only_missing_versions_then_verifies_checksums():
    source = FakeSource(
        [
            _record("angraecum", "1", "a" * 64),
            _record("angraecum", "2", "b" * 64),
        ]
    )
    destination = FakeDestination([_record("angraecum", "1", "a" * 64)])

    result = execute_registry_migration(source=source, destination=destination, apply=True)

    assert result["applied"] is True
    assert [(item["registry_id"], item["version"]) for item in destination.saved] == [
        ("angraecum", "2")
    ]
    assert result["verification"]["data_copy_ready"] is True
    assert result["automatic_activation"] is False


def test_schema_not_ready_blocks_dry_run_before_inventory_copy_logic():
    source = FakeSource([_record("angraecum", "1", "a" * 64)])
    destination = FakeDestination([], schema_ready=False)

    result = execute_registry_migration(source=source, destination=destination, apply=False)

    assert result["schema_ready"] is False
    assert result["applied"] is False
    assert result["blockers"] == ["MATRIX_REGISTRY_TABLE_NOT_FOUND"]
    assert destination.saved == []

import json
from pathlib import Path

from runtime.matrix_identification_registry import compute_registry_record_checksum
from runtime.matrix_identification_registry_store import FileMatrixRegistryStore
from scripts.calyx_matrix_registry_migrate import (
    execute_registry_migration,
    plan_registry_migration,
    strict_source_inventory,
)


def _record(registry_id: str, version: str) -> dict:
    record = {
        "schema_version": "matrix-identification-registry/v1",
        "registry_id": registry_id,
        "version": version,
        "title": f"{registry_id} matrix",
        "scope": {"genus": registry_id.title()},
        "characters": [
            {
                "character": "flower_color",
                "label": "Flower color",
                "description": None,
                "value_type": "categorical",
                "weight": 1.0,
                "provenance": {"source": "test"},
                "concept_id": None,
            }
        ],
        "candidates": [
            {
                "taxon_id": f"taxon-{version}",
                "scientific_name": f"{registry_id.title()} testensis",
                "states": {"flower_color": "white"},
                "provenance": {"source": "test"},
            }
        ],
        "provenance": {"source": "test"},
        "publication_state": "review_required",
        "created_by": "reviewer",
        "created_at": "2026-08-12T00:00:00+00:00",
    }
    record["checksum_sha256"] = compute_registry_record_checksum(record)
    return record


def _source(tmp_path: Path, records: list[dict]) -> FileMatrixRegistryStore:
    store = FileMatrixRegistryStore(tmp_path)
    for record in records:
        path = tmp_path / record["registry_id"] / f"{record['version']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record), encoding="utf-8")
    return store


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
    first = _record("angraecum", "1")
    second = _record("angraecum", "2")
    plan = plan_registry_migration([first, second], [first])

    assert plan["copy_count"] == 1
    assert [(item["registry_id"], item["version"]) for item in plan["copy_records"]] == [
        ("angraecum", "2")
    ]
    assert plan["apply_allowed"] is True


def test_dry_run_performs_zero_writes_and_reports_would_copy(tmp_path: Path):
    record = _record("angraecum", "1")
    source = _source(tmp_path, [record])
    destination = FakeDestination([])

    result = execute_registry_migration(source=source, destination=destination, apply=False)

    assert result["mode"] == "dry_run"
    assert result["applied"] is False
    assert destination.saved == []
    assert result["would_copy"] == [
        {
            "registry_id": "angraecum",
            "version": "1",
            "checksum_sha256": record["checksum_sha256"],
        }
    ]
    assert result["source_inventory"]["inventory_complete"] is True
    assert result["automatic_activation"] is False


def test_checksum_conflict_blocks_even_explicit_apply_before_any_write(tmp_path: Path):
    source_record = _record("angraecum", "1")
    conflicting = dict(source_record)
    conflicting["checksum_sha256"] = "b" * 64
    source = _source(tmp_path, [source_record])
    destination = FakeDestination([conflicting])

    result = execute_registry_migration(source=source, destination=destination, apply=True)

    assert result["applied"] is False
    assert result["blockers"] == ["MATRIX_REGISTRY_CHECKSUM_MISMATCH"]
    assert destination.saved == []


def test_apply_copies_only_missing_versions_then_verifies_checksums(tmp_path: Path):
    first = _record("angraecum", "1")
    second = _record("angraecum", "2")
    source = _source(tmp_path, [first, second])
    destination = FakeDestination([first])

    result = execute_registry_migration(source=source, destination=destination, apply=True)

    assert result["applied"] is True
    assert [(item["registry_id"], item["version"]) for item in destination.saved] == [
        ("angraecum", "2")
    ]
    assert result["verification"]["data_copy_ready"] is True
    assert result["automatic_activation"] is False


def test_schema_not_ready_blocks_dry_run_before_inventory_copy_logic(tmp_path: Path):
    source = _source(tmp_path, [_record("angraecum", "1")])
    destination = FakeDestination([], schema_ready=False)

    result = execute_registry_migration(source=source, destination=destination, apply=False)

    assert result["schema_ready"] is False
    assert result["applied"] is False
    assert result["blockers"] == ["MATRIX_REGISTRY_TABLE_NOT_FOUND"]
    assert destination.saved == []


def test_strict_inventory_rejects_tampered_payload_even_when_claimed_checksum_is_present(tmp_path: Path):
    record = _record("angraecum", "1")
    claimed = record["checksum_sha256"]
    record["title"] = "tampered after checksum"
    source = _source(tmp_path, [record])

    inventory = strict_source_inventory(source)

    assert inventory["inventory_complete"] is False
    assert inventory["valid_package_count"] == 0
    blocker = inventory["blockers"][0]
    assert blocker["code"] == "MATRIX_REGISTRY_SOURCE_CHECKSUM_INVALID"
    assert blocker["claimed_checksum_sha256"] == claimed
    assert blocker["computed_checksum_sha256"] != claimed


def test_malformed_source_package_blocks_migration_instead_of_being_skipped(tmp_path: Path):
    valid = _record("angraecum", "1")
    source = _source(tmp_path, [valid])
    bad_path = tmp_path / "angraecum" / "2.json"
    bad_path.write_text("{not-json", encoding="utf-8")
    destination = FakeDestination([])

    result = execute_registry_migration(source=source, destination=destination, apply=True)

    assert result["applied"] is False
    assert "MATRIX_REGISTRY_SOURCE_PACKAGE_UNREADABLE" in result["blockers"]
    assert destination.saved == []
    assert result["source_inventory"]["physical_package_count"] == 2
    assert result["source_inventory"]["valid_package_count"] == 1

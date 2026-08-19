import json
from pathlib import Path

from runtime.matrix_identification_registry import compute_registry_record_checksum
from runtime.matrix_identification_registry_preflight import (
    compare_registry_records,
    strict_file_registry_inventory,
)


def _record(registry_id: str, version: str, checksum: str) -> dict:
    return {
        "registry_id": registry_id,
        "version": version,
        "checksum_sha256": checksum,
    }


def _full_record(registry_id: str, version: str) -> dict:
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


def _write(root: Path, record: dict, *, raw: str | None = None) -> Path:
    path = root / str(record.get("registry_id") or "unknown") / f"{record.get('version') or 'unknown'}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw if raw is not None else json.dumps(record), encoding="utf-8")
    return path


def test_identical_file_and_database_registry_sets_are_copy_ready():
    records = [
        _record("angraecum", "1", "a" * 64),
        _record("angraecum", "2", "b" * 64),
    ]

    result = compare_registry_records(records, list(reversed(records)))

    assert result["data_copy_ready"] is True
    assert result["missing_in_database"] == []
    assert result["checksum_mismatches"] == []
    assert result["database_only"] == []


def test_missing_file_backed_version_blocks_durable_activation_readiness():
    file_records = [
        _record("angraecum", "1", "a" * 64),
        _record("angraecum", "2", "b" * 64),
    ]
    database_records = [_record("angraecum", "1", "a" * 64)]

    result = compare_registry_records(file_records, database_records)

    assert result["data_copy_ready"] is False
    assert result["missing_in_database"] == [
        {
            "registry_id": "angraecum",
            "version": "2",
            "checksum_sha256": "b" * 64,
        }
    ]


def test_checksum_mismatch_blocks_activation_even_when_version_key_exists():
    result = compare_registry_records(
        [_record("angraecum", "1", "a" * 64)],
        [_record("angraecum", "1", "b" * 64)],
    )

    assert result["data_copy_ready"] is False
    assert result["checksum_mismatches"] == [
        {
            "registry_id": "angraecum",
            "version": "1",
            "file_checksum_sha256": "a" * 64,
            "database_checksum_sha256": "b" * 64,
        }
    ]


def test_database_only_registry_does_not_make_complete_file_copy_unready():
    result = compare_registry_records(
        [_record("angraecum", "1", "a" * 64)],
        [
            _record("angraecum", "1", "a" * 64),
            _record("dracula", "1", "c" * 64),
        ],
    )

    assert result["data_copy_ready"] is True
    assert result["database_only"] == [
        {
            "registry_id": "dracula",
            "version": "1",
            "checksum_sha256": "c" * 64,
        }
    ]


def test_strict_preflight_inventory_accepts_only_recomputed_valid_packages(tmp_path: Path):
    record = _full_record("angraecum", "1")
    _write(tmp_path, record)

    inventory = strict_file_registry_inventory(tmp_path)

    assert inventory["inventory_complete"] is True
    assert inventory["physical_package_count"] == 1
    assert inventory["valid_package_count"] == 1
    assert inventory["blockers"] == []


def test_strict_preflight_inventory_blocks_tampered_checksum_and_malformed_file(tmp_path: Path):
    tampered = _full_record("angraecum", "1")
    tampered["title"] = "tampered after checksum"
    _write(tmp_path, tampered)

    malformed = _full_record("angraecum", "2")
    _write(tmp_path, malformed, raw="{not-json")

    inventory = strict_file_registry_inventory(tmp_path)

    assert inventory["inventory_complete"] is False
    assert inventory["physical_package_count"] == 2
    assert inventory["valid_package_count"] == 0
    codes = [item["code"] for item in inventory["blockers"]]
    assert codes == [
        "MATRIX_REGISTRY_SOURCE_CHECKSUM_INVALID",
        "MATRIX_REGISTRY_SOURCE_PACKAGE_UNREADABLE",
    ]

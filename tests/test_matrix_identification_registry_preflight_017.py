from runtime.matrix_identification_registry_preflight import compare_registry_records


def _record(registry_id: str, version: str, checksum: str) -> dict:
    return {
        "registry_id": registry_id,
        "version": version,
        "checksum_sha256": checksum,
    }


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

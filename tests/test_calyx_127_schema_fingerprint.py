from runtime.calyx_certification.schema_fingerprint import build_schema_fingerprint


def test_complete_schema_builds_hash():
    result = build_schema_fingerprint(
        {
            "migration_head": "build-088e",
            "table_count": 42,
            "extension_versions": {"pgcrypto": "1.3"},
        }
    )
    assert result["schema_fingerprint_ready"] is True
    assert len(result["schema_hash"]) == 64


def test_missing_schema_data_blocks():
    assert build_schema_fingerprint({})["schema_fingerprint_ready"] is False

from runtime.calyx_certification.environment_fingerprint import (
    build_environment_fingerprint,
)


def test_complete_environment_builds_hash():
    result = build_environment_fingerprint(
        {
            "runtime": "python-3.12",
            "region": "oregon",
            "service": "calyx-backend",
            "database_host": "neon",
            "mount_path": "/var/data",
        }
    )
    assert result["fingerprint_ready"] is True
    assert len(result["environment_hash"]) == 64


def test_missing_field_blocks():
    assert build_environment_fingerprint({})["fingerprint_ready"] is False

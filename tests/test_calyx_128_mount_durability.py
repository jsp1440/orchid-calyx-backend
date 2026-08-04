from runtime.calyx_certification.mount_durability import validate_mount_durability


def test_restart_read_proves_durability():
    result = validate_mount_durability(
        {
            "mount_path": "/var/data",
            "write_verified": True,
            "read_after_restart": True,
            "artifact_hash": "abc",
        }
    )
    assert result["mount_durable"] is True


def test_missing_restart_read_blocks():
    result = validate_mount_durability(
        {"mount_path": "/var/data", "write_verified": True, "artifact_hash": "abc"}
    )
    assert "mount_persistence_unverified" in result["blockers"]

from runtime.calyx_certification.dependency_manifest import validate_dependency_manifest


def test_complete_manifest_passes_without_authorizing_action():
    result = validate_dependency_manifest({"backend_url": "u", "database": "d", "persistent_mount": "/var/data", "owner_secret": "configured", "deployed_commit": "abc"})
    assert result["complete"] is True
    assert result["production_action_authorized"] is False


def test_missing_dependency_blocks():
    assert validate_dependency_manifest({})["complete"] is False

from runtime.calyx_certification.rollback_readiness import validate_rollback_readiness


def test_tested_rollback_plan_passes():
    result = validate_rollback_readiness({"previous_commit_sha": "abc", "restore_command": "deploy abc", "database_backup_id": "b1", "tested": True})
    assert result["rollback_ready"] is True


def test_untested_plan_blocks():
    assert "rollback_not_tested" in validate_rollback_readiness({"previous_commit_sha": "a", "restore_command": "r", "database_backup_id": "b", "tested": False})["blockers"]

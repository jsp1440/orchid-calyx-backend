from typing import Any


def validate_rollback_readiness(plan: dict[str, Any]) -> dict[str, Any]:
    required = ("previous_commit_sha", "restore_command", "database_backup_id", "tested")
    blockers = [f"missing:{key}" for key in required if plan.get(key) in (None, "")]
    if plan.get("tested") is not True:
        blockers.append("rollback_not_tested")
    return {"rollback_ready": not blockers, "blockers": blockers, "production_action_authorized": False}

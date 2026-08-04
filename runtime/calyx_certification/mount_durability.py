from typing import Any


def validate_mount_durability(payload: dict[str, Any]) -> dict[str, Any]:
    required = ("mount_path", "write_verified", "read_after_restart", "artifact_hash")
    blockers = [f"missing:{key}" for key in required if payload.get(key) in (None, "")]
    if payload.get("write_verified") is not True:
        blockers.append("mount_write_unverified")
    if payload.get("read_after_restart") is not True:
        blockers.append("mount_persistence_unverified")
    return {
        "mount_durable": not blockers,
        "blockers": sorted(set(blockers)),
        "production_action_authorized": False,
    }

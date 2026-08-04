from __future__ import annotations

from typing import Any


def evaluate_post_release_verification(payload: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    for key in ("release_id", "expected_commit_sha", "deployed_commit_sha", "verified_at"):
        if payload.get(key) in (None, ""):
            blockers.append(f"missing:{key}")
    if payload.get("expected_commit_sha") != payload.get("deployed_commit_sha"):
        blockers.append("post_release_commit_mismatch")
    for key in ("route_healthy", "database_healthy", "worker_healthy"):
        if payload.get(key) is not True:
            blockers.append(f"failed:{key}")
    if payload.get("unexpected_mutation_count") != 0:
        blockers.append("unexpected_post_release_mutation")
    return {
        "post_release_verified": not blockers,
        "blockers": blockers,
        "rollback_evaluation_required": bool(blockers),
        "production_action_authorized": False,
    }

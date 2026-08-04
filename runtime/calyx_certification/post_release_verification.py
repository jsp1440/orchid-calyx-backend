from __future__ import annotations

from typing import Any


def evaluate_post_release_verification(payload: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    required = (
        "release_id",
        "expected_commit_sha",
        "deployed_commit_sha",
        "verified_at",
        "unexpected_mutation_count",
    )
    for key in required:
        if payload.get(key) in (None, ""):
            blockers.append(f"missing:{key}")

    expected = payload.get("expected_commit_sha")
    deployed = payload.get("deployed_commit_sha")
    if expected not in (None, "") and deployed not in (None, "") and expected != deployed:
        blockers.append("post_release_commit_mismatch")

    for key in ("route_healthy", "database_healthy", "worker_healthy"):
        if payload.get(key) is not True:
            blockers.append(f"failed:{key}")

    mutation_count = payload.get("unexpected_mutation_count")
    if mutation_count not in (None, ""):
        if isinstance(mutation_count, bool) or not isinstance(mutation_count, int):
            blockers.append("invalid:unexpected_mutation_count")
        elif mutation_count != 0:
            blockers.append("unexpected_post_release_mutation")

    return {
        "post_release_verified": not blockers,
        "blockers": blockers,
        "rollback_evaluation_required": bool(blockers),
        "production_action_authorized": False,
    }

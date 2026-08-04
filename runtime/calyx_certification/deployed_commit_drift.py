from __future__ import annotations

from typing import Any


def evaluate_deployed_commit_drift(payload: dict[str, Any]) -> dict[str, Any]:
    deployed = str(payload.get("deployed_commit_sha") or "")
    main = str(payload.get("main_commit_sha") or "")
    expected = str(payload.get("expected_commit_sha") or main)
    blockers: list[str] = []
    if not deployed:
        blockers.append("missing:deployed_commit_sha")
    if not main:
        blockers.append("missing:main_commit_sha")
    if not expected:
        blockers.append("missing:expected_commit_sha")
    if deployed and expected and deployed != expected:
        blockers.append("deployed_commit_drift")
    if main and expected and main != expected:
        blockers.append("expected_commit_not_current_main")
    return {
        "aligned": not blockers,
        "blockers": blockers,
        "deployed_commit_sha": deployed,
        "expected_commit_sha": expected,
        "production_action_authorized": False,
    }

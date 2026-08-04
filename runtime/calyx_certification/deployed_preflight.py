REQUIRED_CHECKS = {
    "route_reachable",
    "owner_authentication",
    "database_connectivity",
    "persistent_mount_writable",
    "dry_run_directory_writable",
    "deployed_commit_matches_main",
    "no_production_mutation",
}


def certify_deployed_preflight(report: dict) -> dict:
    checks = report.get("checks") or {}
    blockers = [
        f"{name}:FAILED"
        for name in sorted(REQUIRED_CHECKS)
        if checks.get(name) is not True
    ]
    if not report.get("run_id"):
        blockers.append("RUN_ID_MISSING")
    if not report.get("deployed_commit_sha"):
        blockers.append("DEPLOYED_COMMIT_SHA_MISSING")
    if not report.get("artifact_hash"):
        blockers.append("ARTIFACT_HASH_MISSING")
    return {
        "certified": not blockers,
        "blockers": blockers,
        "production_action_authorized": False,
        "owner_authorization_required": True,
    }

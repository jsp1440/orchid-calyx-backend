REQUIRED_LEDGER_CAPABILITIES = {
    "support_and_counterevidence",
    "assumptions",
    "uncertainty",
    "conflicts",
    "resolved_and_superseded_dispositions",
    "immutable_revisions",
    "optimistic_concurrency",
    "owner_isolation",
    "complete_history",
    "current_version_approval",
    "stale_approval_invalidation",
    "private_reasoning_rejection",
}


def certify_reasoning_ledger(evidence: dict) -> dict:
    capabilities = evidence.get("capabilities") or {}
    blockers = [
        f"{name}:NOT_PROVEN"
        for name in sorted(REQUIRED_LEDGER_CAPABILITIES)
        if capabilities.get(name) is not True
    ]
    if not evidence.get("postgresql_test_run_id"):
        blockers.append("POSTGRESQL_TEST_RUN_ID_MISSING")
    if not evidence.get("artifact_hash"):
        blockers.append("ARTIFACT_HASH_MISSING")
    return {
        "certified": not blockers,
        "blockers": blockers,
        "capability_count": len(REQUIRED_LEDGER_CAPABILITIES),
        "publication_authorized": False,
        "private_reasoning_stored": False,
    }

REQUIRED_PUBLICATION_FIELDS = (
    "ledger_artifact_id",
    "ledger_version",
    "review_hash",
    "source_hash",
    "assertion_identity",
)


def evaluate_controlled_publication(request: dict) -> dict:
    blockers: list[str] = []
    for field in REQUIRED_PUBLICATION_FIELDS:
        if not request.get(field):
            blockers.append(f"{field.upper()}:MISSING")

    if request.get("current_human_approval") is not True:
        blockers.append("CURRENT_HUMAN_APPROVAL_REQUIRED")
    if request.get("review_hash_valid") is not True:
        blockers.append("REVIEW_HASH_INVALID")
    if request.get("source_hash_valid") is not True:
        blockers.append("SOURCE_HASH_INVALID")
    if request.get("stable_assertion_identity") is not True:
        blockers.append("ASSERTION_IDENTITY_UNSTABLE")
    if request.get("delegates_to_build_088_gate") is not True:
        blockers.append("CANONICAL_PUBLICATION_GATE_REQUIRED")
    if request.get("direct_graph_sql") is True:
        blockers.append("DIRECT_GRAPH_SQL_FORBIDDEN")

    return {
        "eligible_for_build_088_gate": not blockers,
        "blockers": blockers,
        "production_publication_authorized": False,
        "append_only_attempt_required": True,
        "idempotent_artifact_reuse_required": True,
    }

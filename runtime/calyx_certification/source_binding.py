REQUIRED_BINDING_FIELDS = (
    "paper_id",
    "analysis_id",
    "evidence_id",
    "source_revision_id",
    "extraction_run_id",
    "source_anchor",
    "source_hash",
)


def evaluate_source_binding(binding: dict) -> dict:
    blockers: list[str] = []
    for field in REQUIRED_BINDING_FIELDS:
        if not binding.get(field):
            blockers.append(f"{field.upper()}:MISSING")

    if binding.get("ambiguous") is True:
        blockers.append("AMBIGUOUS_BINDING")
    if binding.get("conflicting") is True:
        blockers.append("CONFLICTING_BINDING")
    if binding.get("owner_isolated") is not True:
        blockers.append("OWNER_ISOLATION_NOT_PROVEN")
    if binding.get("project_isolated") is not True:
        blockers.append("PROJECT_ISOLATION_NOT_PROVEN")
    if binding.get("idempotent") is not True:
        blockers.append("IDEMPOTENCY_NOT_PROVEN")

    return {
        "binding_complete": not blockers,
        "blockers": blockers,
        "candidate_handoff_allowed": not blockers,
        "candidate_published": False,
        "production_graph_mutation": False,
    }

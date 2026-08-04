REQUIRED_STEPS = (
    "verify_secrets_present",
    "verify_deployed_commit",
    "run_deployed_preflight",
    "collect_artifact",
    "verify_no_mutation",
    "record_owner_decision",
)


def validate_operator_plan(plan: dict) -> dict:
    steps = plan.get("steps") or []
    blockers = [f"STEP_MISSING:{step}" for step in REQUIRED_STEPS if step not in steps]
    if plan.get("automatic_owner_authorization") is True:
        blockers.append("AUTOMATIC_OWNER_AUTHORIZATION_FORBIDDEN")
    if plan.get("production_mutation") is True:
        blockers.append("PRODUCTION_MUTATION_FORBIDDEN")
    return {
        "ready_to_execute_preflight": not blockers,
        "blockers": blockers,
        "owner_action_required": True,
        "production_action_authorized": False,
    }

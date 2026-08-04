REQUIRED_FIELDS = {
    "certification_ready",
    "owner_authorization_required",
    "blockers",
    "unavailable_dependencies",
    "metrics",
}


def validate_status_contract(payload: dict) -> dict:
    blockers = [f"FIELD_MISSING:{name}" for name in sorted(REQUIRED_FIELDS) if name not in payload]
    if payload.get("owner_authorization_required") is not True:
        blockers.append("OWNER_AUTHORIZATION_NOT_REQUIRED")
    if payload.get("certification_ready") is True and (payload.get("blockers") or payload.get("unavailable_dependencies")):
        blockers.append("READY_WITH_ACTIVE_BLOCKERS")
    return {
        "contract_valid": not blockers,
        "blockers": blockers,
        "write_operation": False,
        "production_action_authorized": False,
    }

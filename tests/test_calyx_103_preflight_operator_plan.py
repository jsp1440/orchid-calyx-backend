from runtime.calyx_certification.preflight_operator_plan import (
    REQUIRED_STEPS,
    validate_operator_plan,
)


def test_complete_plan_requires_owner_action():
    result = validate_operator_plan({"steps": list(REQUIRED_STEPS)})
    assert result["ready_to_execute_preflight"] is True
    assert result["owner_action_required"] is True
    assert result["production_action_authorized"] is False


def test_plan_rejects_automatic_authorization():
    result = validate_operator_plan(
        {"steps": list(REQUIRED_STEPS), "automatic_owner_authorization": True}
    )
    assert "AUTOMATIC_OWNER_AUTHORIZATION_FORBIDDEN" in result["blockers"]

from runtime.calyx_certification.owner_authorization import (
    validate_owner_authorization,
)


def test_valid_approval_is_recorded_but_not_executed():
    result = validate_owner_authorization(
        {
            "owner_id": "owner",
            "decision": "approve",
            "snapshot_hash": "s",
            "decided_at": "now",
        }
    )
    assert result["approved"] is True
    assert result["production_action_authorized"] is False


def test_missing_fields_fail_closed():
    assert validate_owner_authorization({})["valid"] is False

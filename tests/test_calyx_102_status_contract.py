from runtime.calyx_certification.status_contract import validate_status_contract


def test_valid_read_only_status_contract():
    result = validate_status_contract(
        {
            "certification_ready": False,
            "owner_authorization_required": True,
            "blockers": [{"code": "LIVE_PREFLIGHT_REQUIRED"}],
            "unavailable_dependencies": [],
            "metrics": {},
        }
    )
    assert result["contract_valid"] is True
    assert result["write_operation"] is False


def test_ready_status_cannot_hide_blockers():
    result = validate_status_contract(
        {
            "certification_ready": True,
            "owner_authorization_required": True,
            "blockers": [{"code": "BLOCKED"}],
            "unavailable_dependencies": [],
            "metrics": {},
        }
    )
    assert "READY_WITH_ACTIVE_BLOCKERS" in result["blockers"]

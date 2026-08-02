from runtime.mission_control_briefing import BriefingStore, mission_control_response


def test_briefing_is_saved_without_enabling_reactive_mode():
    store = BriefingStore()
    saved = store.save({"overall_status": "attention_required", "finding_count": 2})

    assert saved["execution_policy"]["automatic_merge"] is False
    response = mission_control_response(store.latest())
    assert response["available"] is True
    assert response["reactive_mode_enabled"] is False
    assert response["requires_owner_activation"] is True


def test_store_returns_defensive_copies():
    store = BriefingStore()
    saved = store.save({"top_findings": [{"finding_key": "github:ci"}]})
    saved["top_findings"].clear()
    assert store.latest()["top_findings"] == [{"finding_key": "github:ci"}]

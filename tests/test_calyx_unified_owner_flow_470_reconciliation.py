from app.routers import calyx_unified_owner_flow as flow


def _mission() -> dict:
    return {
        "mission_id": "mission-laelia",
        "question": flow.LAELIA_ANCEPS_QUESTION,
        "project_id": "11111111-1111-4111-8111-111111111111",
        "state": "AWAITING_HUMAN_REVIEW",
        "current_stage": "eligible_for_publication_state",
        "review_status": "HUMAN_REVIEW_REQUIRED",
        "publication_eligibility": {
            "eligible": False,
            "automatic_publication": False,
        },
        "reasoning_ledger": {"ledger_id": "ledger-laelia", "version": 4},
    }


def test_durable_review_state_overrides_stale_mission_review_projection():
    durable = {
        "ledger_id": "ledger-laelia",
        "version": 5,
        "review_content_hash": "a" * 64,
        "review_decisions": [
            {
                "outcome": "approved",
                "ledger_version": 5,
                "reviewed_content_hash": "a" * 64,
            }
        ],
    }
    candidate = {
        "ledger_id": "ledger-laelia",
        "version": 5,
        "review_content_hash": "a" * 64,
    }

    view = flow._durable_mission_view(_mission(), durable, candidate)

    assert view["review_status"] == "APPROVED"
    assert view["review_decision_current"] is True
    assert view["ledger_version"] == 5
    assert view["publication_eligibility"] == {
        "eligible": True,
        "automatic_publication": False,
        "source": "durable_reasoning_ledger",
        "review_content_hash_current": True,
    }
    assert view["review_state_source"] == "durable_reasoning_ledger"
    assert view["private_reasoning_exposed"] is False


def test_stale_approval_is_not_displayed_for_new_ledger_version_or_hash():
    durable = {
        "ledger_id": "ledger-laelia",
        "version": 6,
        "review_content_hash": "b" * 64,
        "review_decisions": [
            {
                "outcome": "approved",
                "ledger_version": 5,
                "reviewed_content_hash": "a" * 64,
            }
        ],
    }

    view = flow._durable_mission_view(_mission(), durable, None)

    assert view["review_status"] == "HUMAN_REVIEW_REQUIRED"
    assert view["review_decision_current"] is False
    assert view["ledger_version"] == 6
    assert view["publication_eligibility"] == {
        "eligible": False,
        "automatic_publication": False,
        "source": "durable_reasoning_ledger",
        "review_content_hash_current": False,
    }

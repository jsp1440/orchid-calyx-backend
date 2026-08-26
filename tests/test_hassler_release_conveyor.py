from runtime.hassler_release_conveyor import build_release_conveyor_plan


def _lifecycle(state, **overrides):
    payload = {
        "lifecycle_state": state,
        "staging": {
            "next_row_index": None,
            "open_review_items": None,
            "change_report_present": None,
        },
    }
    payload.update(overrides)
    return payload


def test_unavailable_refreshes_evidence_without_claiming_absence():
    plan = build_release_conveyor_plan(lifecycle=_lifecycle("UNAVAILABLE"))
    assert plan["next_step"]["code"] == "REFRESH_READ_ONLY_EVIDENCE"
    assert plan["next_step"]["mode"] == "read_only"
    assert plan["next_step"]["owner_approval_required"] is False


def test_absent_release_points_to_exact_upload_but_does_not_authorize_it():
    plan = build_release_conveyor_plan(lifecycle=_lifecycle("ABSENT"))
    step = plan["next_step"]
    assert step["code"] == "UPLOAD_EXACT_RELEASE"
    assert step["owner_approval_required"] is True
    assert step["execution_authorized"] is False
    assert step["production_mutation_authorized"] is False


def test_uploaded_release_advances_to_smoke_readback():
    plan = build_release_conveyor_plan(lifecycle=_lifecycle("UPLOADED_INSPECTED"))
    assert plan["next_step"]["code"] == "RUN_SMOKE_READBACK"


def test_smoke_verified_advances_to_bounded_staging_without_authority():
    plan = build_release_conveyor_plan(lifecycle=_lifecycle("SMOKE_VERIFIED"))
    step = plan["next_step"]
    assert step["code"] == "START_BOUNDED_STAGING"
    assert step["owner_approval_required"] is True
    assert step["taxonomy_activation_authorized"] is False


def test_partial_staging_resumes_exact_checkpoint_instead_of_restarting():
    lifecycle = _lifecycle("STAGING_IN_PROGRESS")
    lifecycle["staging"] = {
        "next_row_index": 12400,
        "open_review_items": 0,
        "change_report_present": False,
    }
    plan = build_release_conveyor_plan(lifecycle=lifecycle)
    step = plan["next_step"]
    assert step["code"] == "RESUME_BOUNDED_STAGING"
    assert "12400" in step["action"]


def test_open_review_queue_blocks_activation_readiness():
    lifecycle = _lifecycle("STAGED_COMPLETE")
    lifecycle["staging"] = {
        "next_row_index": 34724,
        "open_review_items": 3,
        "change_report_present": True,
    }
    plan = build_release_conveyor_plan(lifecycle=lifecycle)
    step = plan["next_step"]
    assert step["code"] == "RESOLVE_TAXONOMY_REVIEW_QUEUE"
    assert step["scientific_review_required"] is True
    assert step["taxonomy_activation_authorized"] is False


def test_missing_change_report_is_verified_before_activation_packet():
    lifecycle = _lifecycle("STAGED_COMPLETE")
    lifecycle["staging"] = {
        "next_row_index": 34724,
        "open_review_items": 0,
        "change_report_present": False,
    }
    plan = build_release_conveyor_plan(lifecycle=lifecycle)
    assert plan["next_step"]["code"] == "VERIFY_CHANGE_REPORT"


def test_clean_staged_release_prepares_owner_decision_not_activation():
    lifecycle = _lifecycle("STAGED_COMPLETE")
    lifecycle["staging"] = {
        "next_row_index": 34724,
        "open_review_items": 0,
        "change_report_present": True,
    }
    plan = build_release_conveyor_plan(lifecycle=lifecycle)
    step = plan["next_step"]
    assert step["code"] == "PREPARE_OWNER_ACTIVATION_DECISION"
    assert step["owner_approval_required"] is True
    assert step["taxonomy_activation_authorized"] is False


def test_activated_release_audits_downstream_when_counts_are_incomplete():
    plan = build_release_conveyor_plan(
        lifecycle=_lifecycle("ACTIVATED"),
        downstream={"counts_complete": False, "unresolved_blockers": []},
    )
    assert plan["next_step"]["code"] == "AUDIT_DOWNSTREAM_RELINK_IMPACT"


def test_activated_release_only_prepares_relink_when_impact_is_complete():
    plan = build_release_conveyor_plan(
        lifecycle=_lifecycle("ACTIVATED"),
        downstream={"counts_complete": True, "unresolved_blockers": []},
    )
    step = plan["next_step"]
    assert step["code"] == "PREPARE_DOWNSTREAM_RELINK"
    assert step["knowledge_graph_mutation_authorized"] is False


def test_unresolved_downstream_blocker_prevents_relink_preparation():
    plan = build_release_conveyor_plan(
        lifecycle=_lifecycle("ACTIVATED"),
        downstream={
            "counts_complete": True,
            "unresolved_blockers": ["duplicate_identities_present"],
        },
    )
    assert plan["next_step"]["code"] == "AUDIT_DOWNSTREAM_RELINK_IMPACT"


def test_superseded_release_switches_target_instead_of_finishing_old_release():
    plan = build_release_conveyor_plan(lifecycle=_lifecycle("SUPERSEDED"))
    assert plan["next_step"]["code"] == "SWITCH_TO_NEWER_RELEASE"
    assert plan["next_step"]["mode"] == "read_only_target_selection"


def test_unknown_state_fails_closed_to_read_only_discovery():
    plan = build_release_conveyor_plan(lifecycle=_lifecycle("MYSTERY"))
    assert plan["next_step"]["code"] == "REFRESH_READ_ONLY_EVIDENCE"
    assert plan["execution_authorized"] is False


def test_conveyor_never_grants_taxonomy_or_graph_mutation_authority():
    for state in (
        "UNAVAILABLE",
        "ABSENT",
        "UPLOADED_INSPECTED",
        "SMOKE_VERIFIED",
        "STAGING_IN_PROGRESS",
        "STAGED_COMPLETE",
        "ACTIVATED",
        "SUPERSEDED",
    ):
        plan = build_release_conveyor_plan(lifecycle=_lifecycle(state))
        assert plan["execution_authorized"] is False
        assert plan["production_taxonomy_mutation_authorized"] is False
        assert plan["knowledge_graph_mutation_authorized"] is False
        assert plan["scientific_publication_authorized"] is False

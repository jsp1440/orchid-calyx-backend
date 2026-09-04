"""Tests for ORCHESTRATION-EVENT-DRIVEN-001 — event-driven completion dispatcher.

Covers all 8 acceptance criteria from issue #1023:
1. Event deduplication: replayed GitHub events produce no-op, no duplicate task
2. Exact-head binding: stale SHA fails closed before any continuation
3. Success continuation: CI success immediately enqueues a continuation task
4. Failure repair: CI failure creates deduped repair task with exact evidence
5. Infrastructure failure: cancelled/timed_out → HALT, not repaired
6. Owner-gate preservation: no autonomous merge/deploy at any dispatch path
7. Transient retry ceiling: stops at MAX_TRANSIENT_RETRIES, never loops forever
8. No duplicate Claude launches: same idempotency_key → deduplicated_no_op
"""

from __future__ import annotations

import json

import pytest

from app.calyx_engineering.event_dispatcher import (
    MAX_TRANSIENT_RETRIES,
    SCHEMA_VERSION,
    DispatchAction,
    EventDeduplicator,
    EventKey,
    EventOutcome,
    bind_event_key,
    classify_workflow_run_event,
    create_continuation_task,
    create_repair_task,
    dispatch_event,
    get_dispatcher_manifest,
    serialize_manifest_as_json,
    validate_head_binding,
)

# ---------------------------------------------------------------------------
# Fixtures — minimal synthetic GitHub event payloads
# ---------------------------------------------------------------------------

_REPO = "jsp1440/orchid-calyx-backend"
_HEAD_SHA = "abc1234567890abcdef"
_RUN_ID = "9876543210"
_BRANCH = "claude/test-branch"
_PR_NUMBER = 42


def _workflow_run_payload(
    *,
    conclusion: str | None = "success",
    status: str = "completed",
    head_sha: str = _HEAD_SHA,
    branch: str = _BRANCH,
    run_id: str = _RUN_ID,
    pr_number: int = _PR_NUMBER,
) -> dict:
    return {
        "repository": {"full_name": _REPO},
        "workflow_run": {
            "id": run_id,
            "status": status,
            "conclusion": conclusion,
            "head_sha": head_sha,
            "head_branch": branch,
            "pull_requests": [{"number": pr_number}],
        },
    }


def _check_suite_payload(
    *,
    conclusion: str | None = "success",
    status: str = "completed",
) -> dict:
    return {
        "repository": {"full_name": _REPO},
        "check_suite": {
            "id": _RUN_ID,
            "status": status,
            "conclusion": conclusion,
            "head_sha": _HEAD_SHA,
            "head_branch": _BRANCH,
            "pull_requests": [{"number": _PR_NUMBER}],
        },
    }


def _pull_request_payload(
    *,
    sha: str = _HEAD_SHA,
    pr_number: int = _PR_NUMBER,
) -> dict:
    return {
        "repository": {"full_name": _REPO},
        "pull_request": {
            "number": pr_number,
            "head": {"ref": _BRANCH, "sha": sha},
        },
    }


def _make_key(*, head_sha: str = _HEAD_SHA, run_id: str = _RUN_ID) -> EventKey:
    return EventKey(
        repository=_REPO,
        pull_request_number=_PR_NUMBER,
        branch=_BRANCH,
        head_sha=head_sha,
        run_id=run_id,
        event_kind="workflow_run",
    )


# ---------------------------------------------------------------------------
# EventKey
# ---------------------------------------------------------------------------


def test_event_key_requires_repository():
    with pytest.raises(ValueError, match="REPOSITORY_REQUIRED"):
        EventKey(
            repository="",
            pull_request_number=1,
            branch=_BRANCH,
            head_sha=_HEAD_SHA,
            run_id=_RUN_ID,
            event_kind="workflow_run",
        )


def test_event_key_requires_valid_head_sha():
    with pytest.raises(ValueError, match="HEAD_SHA_INVALID"):
        EventKey(
            repository=_REPO,
            pull_request_number=1,
            branch=_BRANCH,
            head_sha="",
            run_id=_RUN_ID,
            event_kind="workflow_run",
        )


def test_event_key_idempotency_key_is_deterministic():
    k1 = _make_key()
    k2 = _make_key()
    assert k1.idempotency_key == k2.idempotency_key


def test_event_key_idempotency_key_differs_for_different_head_sha():
    k1 = _make_key(head_sha="aaaaaa0000000000000")
    k2 = _make_key(head_sha="bbbbbb0000000000000")
    assert k1.idempotency_key != k2.idempotency_key


def test_event_key_idempotency_key_is_32_hex_chars():
    k = _make_key()
    assert len(k.idempotency_key) == 32
    assert all(c in "0123456789abcdef" for c in k.idempotency_key)


# ---------------------------------------------------------------------------
# bind_event_key
# ---------------------------------------------------------------------------


def test_bind_workflow_run_extracts_all_fields():
    key = bind_event_key(_workflow_run_payload(), "workflow_run")
    assert key.repository == _REPO
    assert key.head_sha == _HEAD_SHA
    assert key.branch == _BRANCH
    assert key.run_id == _RUN_ID
    assert key.pull_request_number == _PR_NUMBER
    assert key.event_kind == "workflow_run"


def test_bind_check_suite_extracts_all_fields():
    key = bind_event_key(_check_suite_payload(), "check_suite")
    assert key.repository == _REPO
    assert key.head_sha == _HEAD_SHA


def test_bind_pull_request_extracts_all_fields():
    key = bind_event_key(_pull_request_payload(), "pull_request")
    assert key.repository == _REPO
    assert key.head_sha == _HEAD_SHA
    assert key.pull_request_number == _PR_NUMBER


def test_bind_rejects_unsupported_event_kind():
    with pytest.raises(ValueError, match="EVENT_KIND_UNSUPPORTED"):
        bind_event_key({}, "push")


# ---------------------------------------------------------------------------
# classify_workflow_run_event
# ---------------------------------------------------------------------------


def test_classify_success():
    p = _workflow_run_payload(conclusion="success")
    assert classify_workflow_run_event(p) == EventOutcome.SUCCESS


def test_classify_failure():
    p = _workflow_run_payload(conclusion="failure")
    assert classify_workflow_run_event(p) == EventOutcome.FAILURE


def test_classify_neutral_as_failure():
    p = _workflow_run_payload(conclusion="neutral")
    assert classify_workflow_run_event(p) == EventOutcome.FAILURE


def test_classify_cancelled_as_infrastructure():
    p = _workflow_run_payload(conclusion="cancelled")
    assert classify_workflow_run_event(p) == EventOutcome.INFRASTRUCTURE


def test_classify_timed_out_as_infrastructure():
    p = _workflow_run_payload(conclusion="timed_out")
    assert classify_workflow_run_event(p) == EventOutcome.INFRASTRUCTURE


def test_classify_action_required_as_infrastructure():
    p = _workflow_run_payload(conclusion="action_required")
    assert classify_workflow_run_event(p) == EventOutcome.INFRASTRUCTURE


def test_classify_pending_when_not_completed():
    p = _workflow_run_payload(status="in_progress", conclusion=None)
    assert classify_workflow_run_event(p) == EventOutcome.PENDING


def test_classify_skipped_as_transient():
    p = _workflow_run_payload(conclusion="skipped")
    assert classify_workflow_run_event(p) == EventOutcome.TRANSIENT


# ---------------------------------------------------------------------------
# validate_head_binding (AC-2: stale-head handling)
# ---------------------------------------------------------------------------


def test_head_binding_passes_when_sha_matches():
    key = _make_key(head_sha=_HEAD_SHA)
    assert validate_head_binding(key, _HEAD_SHA) is True


def test_head_binding_fails_when_sha_differs():
    key = _make_key(head_sha="stale000000000000000")
    assert validate_head_binding(key, _HEAD_SHA) is False


def test_head_binding_passes_when_no_expected_sha():
    key = _make_key()
    assert validate_head_binding(key, "") is True


# ---------------------------------------------------------------------------
# EventDeduplicator (AC-1 & AC-8: deduplication, no duplicate launches)
# ---------------------------------------------------------------------------


def test_deduplicator_not_duplicate_initially():
    dedup = EventDeduplicator()
    assert not dedup.is_duplicate(_make_key())


def test_deduplicator_is_duplicate_after_mark():
    dedup = EventDeduplicator()
    key = _make_key()
    dedup.mark_seen(key)
    assert dedup.is_duplicate(key)


def test_deduplicator_different_head_sha_not_duplicate():
    dedup = EventDeduplicator()
    k1 = _make_key(head_sha="aaaa111111111111111")
    k2 = _make_key(head_sha="bbbb222222222222222")
    dedup.mark_seen(k1)
    assert not dedup.is_duplicate(k2)


def test_deduplicator_clear_resets_state():
    dedup = EventDeduplicator()
    key = _make_key()
    dedup.mark_seen(key)
    dedup.clear()
    assert not dedup.is_duplicate(key)


# ---------------------------------------------------------------------------
# create_continuation_task
# ---------------------------------------------------------------------------


def test_continuation_task_has_required_fields():
    key = _make_key()
    task = create_continuation_task(key, EventOutcome.SUCCESS)
    assert task.pr_number == _PR_NUMBER
    assert task.head_sha == _HEAD_SHA
    assert task.branch == _BRANCH
    assert task.repository == _REPO
    assert task.task_kind == "continuation"
    assert task.idempotency_key == key.idempotency_key


def test_continuation_task_never_auto_merges():
    key = _make_key()
    task = create_continuation_task(key, EventOutcome.SUCCESS)
    assert task.autonomous_merge is False


def test_continuation_task_never_deploys():
    key = _make_key()
    task = create_continuation_task(key, EventOutcome.SUCCESS)
    assert task.deployment is False


def test_continuation_task_owner_gate_preserved():
    key = _make_key()
    task = create_continuation_task(key, EventOutcome.SUCCESS)
    assert task.owner_gate_preserved is True


def test_continuation_task_no_auto_publication():
    key = _make_key()
    task = create_continuation_task(key, EventOutcome.SUCCESS)
    assert task.automatic_publication is False


def test_continuation_task_no_kg_mutation():
    key = _make_key()
    task = create_continuation_task(key, EventOutcome.SUCCESS)
    assert task.knowledge_graph_mutation is False


def test_continuation_task_title_contains_pr_number():
    key = _make_key()
    task = create_continuation_task(key, EventOutcome.SUCCESS)
    assert str(_PR_NUMBER) in task.title


# ---------------------------------------------------------------------------
# create_repair_task
# ---------------------------------------------------------------------------


def test_repair_task_has_failure_logs():
    key = _make_key()
    task = create_repair_task(key, "FAILED: test_foo", retry_count=0)
    assert task is not None
    assert "FAILED" in task.failure_logs


def test_repair_task_includes_retry_count():
    key = _make_key()
    task = create_repair_task(key, "err", retry_count=1)
    assert task is not None
    assert task.retry_count == 1


def test_repair_task_returns_none_at_ceiling():
    key = _make_key()
    task = create_repair_task(key, "err", retry_count=MAX_TRANSIENT_RETRIES)
    assert task is None


def test_repair_task_never_auto_merges():
    key = _make_key()
    task = create_repair_task(key, "err")
    assert task is not None
    assert task.autonomous_merge is False


def test_repair_task_owner_gate_preserved():
    key = _make_key()
    task = create_repair_task(key, "err")
    assert task is not None
    assert task.owner_gate_preserved is True


# ---------------------------------------------------------------------------
# ContinuationTask safety-invariant enforcement
# ---------------------------------------------------------------------------


def test_continuation_task_raises_if_autonomous_merge_attempted():
    key = _make_key()
    with pytest.raises(PermissionError, match="AUTONOMOUS_MERGE_FORBIDDEN"):
        from app.calyx_engineering.event_dispatcher import ContinuationTask
        ContinuationTask(
            title="bad",
            task_kind="continuation",
            pr_number=1,
            head_sha=_HEAD_SHA,
            branch=_BRANCH,
            repository=_REPO,
            outcome=EventOutcome.SUCCESS,
            idempotency_key=key.idempotency_key,
            autonomous_merge=True,
        )


def test_continuation_task_raises_if_deployment_attempted():
    key = _make_key()
    with pytest.raises(PermissionError, match="DEPLOYMENT_FORBIDDEN"):
        from app.calyx_engineering.event_dispatcher import ContinuationTask
        ContinuationTask(
            title="bad",
            task_kind="continuation",
            pr_number=1,
            head_sha=_HEAD_SHA,
            branch=_BRANCH,
            repository=_REPO,
            outcome=EventOutcome.SUCCESS,
            idempotency_key=key.idempotency_key,
            deployment=True,
        )


# ---------------------------------------------------------------------------
# dispatch_event — AC-1: deduplication
# ---------------------------------------------------------------------------


def test_dispatch_deduplicated_on_replay():
    dedup = EventDeduplicator()
    payload = _workflow_run_payload()
    # first dispatch
    dispatch_event(payload, "workflow_run", dedup)
    # replay
    result = dispatch_event(payload, "workflow_run", dedup)
    assert result.action == DispatchAction.DEDUPLICATED_NO_OP


def test_dispatch_dedup_no_task_on_replay():
    dedup = EventDeduplicator()
    payload = _workflow_run_payload()
    dispatch_event(payload, "workflow_run", dedup)
    result = dispatch_event(payload, "workflow_run", dedup)
    assert result.task is None


# ---------------------------------------------------------------------------
# dispatch_event — AC-2: exact-head binding / stale-head
# ---------------------------------------------------------------------------


def test_dispatch_fails_closed_on_stale_head():
    dedup = EventDeduplicator()
    payload = _workflow_run_payload(head_sha="stale000000000000000")
    result = dispatch_event(payload, "workflow_run", dedup, expected_head_sha=_HEAD_SHA)
    assert result.action == DispatchAction.FAIL_CLOSED_STALE_HEAD
    assert result.outcome == EventOutcome.STALE_HEAD


def test_dispatch_stale_head_never_creates_task():
    dedup = EventDeduplicator()
    payload = _workflow_run_payload(head_sha="stale000000000000000")
    result = dispatch_event(payload, "workflow_run", dedup, expected_head_sha=_HEAD_SHA)
    assert result.task is None


def test_dispatch_stale_head_marks_seen_to_prevent_retry():
    dedup = EventDeduplicator()
    payload = _workflow_run_payload(head_sha="stale000000000000000")
    dispatch_event(payload, "workflow_run", dedup, expected_head_sha=_HEAD_SHA)
    result2 = dispatch_event(payload, "workflow_run", dedup, expected_head_sha=_HEAD_SHA)
    assert result2.action == DispatchAction.DEDUPLICATED_NO_OP


# ---------------------------------------------------------------------------
# dispatch_event — AC-3: success continuation
# ---------------------------------------------------------------------------


def test_dispatch_success_enqueues_continuation():
    dedup = EventDeduplicator()
    result = dispatch_event(_workflow_run_payload(conclusion="success"), "workflow_run", dedup)
    assert result.action == DispatchAction.ENQUEUE_CONTINUATION
    assert result.outcome == EventOutcome.SUCCESS
    assert result.task is not None
    assert result.task.task_kind == "continuation"


def test_dispatch_success_task_has_pr_number():
    dedup = EventDeduplicator()
    result = dispatch_event(_workflow_run_payload(), "workflow_run", dedup)
    assert result.task is not None
    assert result.task.pr_number == _PR_NUMBER


def test_dispatch_success_no_autonomous_merge():
    dedup = EventDeduplicator()
    result = dispatch_event(_workflow_run_payload(), "workflow_run", dedup)
    assert result.autonomous_merge is False
    if result.task:
        assert result.task.autonomous_merge is False


# ---------------------------------------------------------------------------
# dispatch_event — AC-4: failure repair task
# ---------------------------------------------------------------------------


def test_dispatch_failure_enqueues_repair():
    dedup = EventDeduplicator()
    payload = _workflow_run_payload(conclusion="failure")
    result = dispatch_event(payload, "workflow_run", dedup, failure_logs="FAILED: test_bar")
    assert result.action == DispatchAction.ENQUEUE_REPAIR
    assert result.task is not None
    assert result.task.task_kind == "repair"


def test_dispatch_failure_repair_task_contains_logs():
    dedup = EventDeduplicator()
    payload = _workflow_run_payload(conclusion="failure")
    result = dispatch_event(payload, "workflow_run", dedup, failure_logs="SPECIFIC ERROR HERE")
    assert result.task is not None
    assert "SPECIFIC ERROR HERE" in result.task.failure_logs


def test_dispatch_failure_repair_is_idempotent():
    dedup = EventDeduplicator()
    payload = _workflow_run_payload(conclusion="failure")
    dispatch_event(payload, "workflow_run", dedup)
    result2 = dispatch_event(payload, "workflow_run", dedup)
    assert result2.action == DispatchAction.DEDUPLICATED_NO_OP


# ---------------------------------------------------------------------------
# dispatch_event — AC-5: infrastructure failure → halt, not repair
# ---------------------------------------------------------------------------


def test_dispatch_cancelled_halts_not_repairs():
    dedup = EventDeduplicator()
    result = dispatch_event(_workflow_run_payload(conclusion="cancelled"), "workflow_run", dedup)
    assert result.action == DispatchAction.HALT_INFRASTRUCTURE
    assert result.task is None


def test_dispatch_timed_out_halts():
    dedup = EventDeduplicator()
    result = dispatch_event(_workflow_run_payload(conclusion="timed_out"), "workflow_run", dedup)
    assert result.action == DispatchAction.HALT_INFRASTRUCTURE


def test_dispatch_action_required_halts():
    dedup = EventDeduplicator()
    result = dispatch_event(_workflow_run_payload(conclusion="action_required"), "workflow_run", dedup)
    assert result.action == DispatchAction.HALT_INFRASTRUCTURE


# ---------------------------------------------------------------------------
# dispatch_event — AC-6: owner-gate preservation at every action
# ---------------------------------------------------------------------------


def test_owner_gate_preserved_on_success():
    dedup = EventDeduplicator()
    result = dispatch_event(_workflow_run_payload(conclusion="success"), "workflow_run", dedup)
    assert result.owner_gate_preserved is True
    assert result.autonomous_merge is False
    assert result.deployment is False


def test_owner_gate_preserved_on_failure():
    dedup = EventDeduplicator()
    result = dispatch_event(_workflow_run_payload(conclusion="failure"), "workflow_run", dedup)
    assert result.owner_gate_preserved is True
    assert result.autonomous_merge is False
    assert result.deployment is False


def test_owner_gate_preserved_on_stale_head():
    dedup = EventDeduplicator()
    result = dispatch_event(
        _workflow_run_payload(head_sha="stale000000000000000"),
        "workflow_run",
        dedup,
        expected_head_sha=_HEAD_SHA,
    )
    assert result.owner_gate_preserved is True


def test_automatic_publication_never_true():
    for conclusion in ("success", "failure", "cancelled", "timed_out"):
        dedup = EventDeduplicator()
        result = dispatch_event(_workflow_run_payload(conclusion=conclusion), "workflow_run", dedup)
        assert result.automatic_publication is False, f"Got True for {conclusion}"


def test_knowledge_graph_mutation_never_true():
    for conclusion in ("success", "failure", "cancelled"):
        dedup = EventDeduplicator()
        result = dispatch_event(_workflow_run_payload(conclusion=conclusion), "workflow_run", dedup)
        assert result.knowledge_graph_mutation is False, f"Got True for {conclusion}"


# ---------------------------------------------------------------------------
# dispatch_event — AC-7: transient retry ceiling
# ---------------------------------------------------------------------------


def test_transient_permits_retry_below_ceiling():
    dedup = EventDeduplicator()
    payload = _workflow_run_payload(conclusion="skipped")
    result = dispatch_event(payload, "workflow_run", dedup, retry_count=0)
    assert result.action == DispatchAction.RETRY_BACKOFF


def test_transient_halts_at_ceiling():
    dedup = EventDeduplicator()
    payload = _workflow_run_payload(conclusion="skipped")
    result = dispatch_event(payload, "workflow_run", dedup, retry_count=MAX_TRANSIENT_RETRIES)
    assert result.action == DispatchAction.HALT_RETRY_LIMIT


def test_failure_repair_ceiling():
    dedup = EventDeduplicator()
    payload = _workflow_run_payload(conclusion="failure")
    result = dispatch_event(payload, "workflow_run", dedup, retry_count=MAX_TRANSIENT_RETRIES)
    assert result.action == DispatchAction.HALT_RETRY_LIMIT
    assert result.task is None


# ---------------------------------------------------------------------------
# dispatch_event — AC-8: no duplicate Claude launches (same key → no-op)
# ---------------------------------------------------------------------------


def test_same_delivery_twice_is_no_op():
    dedup = EventDeduplicator()
    payload = _workflow_run_payload()
    r1 = dispatch_event(payload, "workflow_run", dedup)
    r2 = dispatch_event(payload, "workflow_run", dedup)
    assert r1.action != DispatchAction.DEDUPLICATED_NO_OP
    assert r2.action == DispatchAction.DEDUPLICATED_NO_OP


def test_different_run_id_is_not_deduplicated():
    dedup = EventDeduplicator()
    p1 = _workflow_run_payload(run_id="11111")
    p2 = _workflow_run_payload(run_id="22222")
    r1 = dispatch_event(p1, "workflow_run", dedup)
    r2 = dispatch_event(p2, "workflow_run", dedup)
    assert r1.action != DispatchAction.DEDUPLICATED_NO_OP
    assert r2.action != DispatchAction.DEDUPLICATED_NO_OP


# ---------------------------------------------------------------------------
# check_suite events
# ---------------------------------------------------------------------------


def test_dispatch_check_suite_success():
    dedup = EventDeduplicator()
    result = dispatch_event(_check_suite_payload(conclusion="success"), "check_suite", dedup)
    assert result.action == DispatchAction.ENQUEUE_CONTINUATION


def test_dispatch_check_suite_failure():
    dedup = EventDeduplicator()
    result = dispatch_event(_check_suite_payload(conclusion="failure"), "check_suite", dedup)
    assert result.action == DispatchAction.ENQUEUE_REPAIR


# ---------------------------------------------------------------------------
# pull_request events (sync triggers)
# ---------------------------------------------------------------------------


def test_dispatch_pull_request_pending_awaits_completion():
    dedup = EventDeduplicator()
    payload = _pull_request_payload()
    payload["pull_request"]["status"] = "in_progress"
    result = dispatch_event(payload, "pull_request", dedup)
    assert result.action == DispatchAction.AWAIT_COMPLETION


# ---------------------------------------------------------------------------
# Manifest / invariants report
# ---------------------------------------------------------------------------


def test_manifest_schema_version():
    m = get_dispatcher_manifest()
    assert m["schema_version"] == SCHEMA_VERSION


def test_manifest_invariants_all_safe():
    m = get_dispatcher_manifest()
    inv = m["invariants"]
    assert inv["autonomous_merge"] is False
    assert inv["deployment"] is False
    assert inv["production_db_mutation"] is False
    assert inv["owner_gate_preserved"] is True
    assert inv["automatic_publication"] is False
    assert inv["knowledge_graph_mutation"] is False


def test_manifest_contains_all_event_kinds():
    m = get_dispatcher_manifest()
    assert set(m["supported_event_kinds"]) >= {"workflow_run", "check_suite", "pull_request", "check_run"}


def test_manifest_serializable_as_json():
    raw = serialize_manifest_as_json()
    parsed = json.loads(raw)
    assert parsed["schema_version"] == SCHEMA_VERSION


def test_manifest_no_secrets():
    raw = serialize_manifest_as_json()
    for bad in ("sk-live-", "Bearer ", "api_key=", "password=", "API_KEY="):
        assert bad not in raw, f"Potential secret pattern found: {bad}"


def test_manifest_max_transient_retries_matches_constant():
    m = get_dispatcher_manifest()
    assert m["max_transient_retries"] == MAX_TRANSIENT_RETRIES

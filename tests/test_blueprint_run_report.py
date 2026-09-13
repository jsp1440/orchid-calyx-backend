"""Tests for BlueprintRunReport aggregation.

Contracts verified:
  1. all_complete when every leaf COMPLETED
  2. awaiting_owner_gate when non-gated leaves COMPLETED; OWNER_GATED remain
  3. partially_blocked when some BLOCKED; nothing in_progress
  4. in_progress when READY leaves remain
  5. in_progress when ACTIVE (leased) leaves remain
  6. in_progress when REPAIR_BACKOFF leaves remain
  7. owner_gated_pending list is accurate
  8. blocked list with reason is accurate
  9. completed list contains execution evidence
 10. unknown/missing task (not in reservoir) → counted as ready/in_progress
 11. empty blueprint → all_complete
 12. report is immutable (frozen dataclass)
 13. as_dict() is fully serializable (no non-dict objects)
 14. E2E: GovernanceDecision → blueprint → enqueue → dispatch → report
"""

from __future__ import annotations

import pytest

from app.calyx_orchestrator.blueprint_run_report import (
    REPORT_VERSION,
    build_blueprint_run_report,
)
from app.calyx_orchestrator.bounded_dispatcher import (
    BoundedDispatcher,
    DispatchConfig,
    DispatchRun,
)
from app.calyx_orchestrator.deep_orchestrate import (
    AUTH_GOVERNANCE,
    AUTH_PRODUCTION,
    AUTH_WORKSPACE,
    DeepOrchestrate,
    Priority,
    TaskLeaf,
    TaskState,
)
from app.calyx_orchestrator.leaf_worker import DeterministicResearchWorker

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _reservoir() -> DeepOrchestrate:
    return DeepOrchestrate(configured_width=5)


def _leaf(key: str, *, authority_class: str = AUTH_WORKSPACE, deps: list[str] | None = None) -> TaskLeaf:
    return TaskLeaf(
        key=key,
        title=key,
        repo="test/repo",
        module="test",
        priority=Priority.P1,
        authority_class=authority_class,
        consequence_risk="low",
        acceptance_criteria=["done"],
        dependencies=deps or [],
    )


class _FakeBlueprint:
    """Minimal stand-in for ResearchBlueprint (avoids decompose overhead)."""

    def __init__(self, leaves: list[TaskLeaf], *, human_review_required: bool = True) -> None:
        self.blueprint_id = "a" * 64
        self.run_fingerprint = "b" * 64
        self.proposed_action = "test-action"
        self.human_review_required = human_review_required
        self.task_leaves = tuple(leaves)


def _empty_run() -> DispatchRun:
    return DispatchRun()


# ---------------------------------------------------------------------------
# 1. all_complete when every leaf COMPLETED
# ---------------------------------------------------------------------------


def test_all_complete_status():
    res = _reservoir()
    leaf_a = _leaf("bp:t1:retrieve-evidence")
    leaf_b = _leaf("bp:t2:normalize-evidence", deps=[leaf_a.key])
    res.register(leaf_a)
    res.register(leaf_b)
    res.refill()
    res.lease(leaf_a.key, holder="test")
    res.complete(leaf_a.key, evidence={"done": True})
    res.refill()
    res.lease(leaf_b.key, holder="test")
    res.complete(leaf_b.key, evidence={"done": True})

    bp = _FakeBlueprint([leaf_a, leaf_b])
    report = build_blueprint_run_report(bp, _empty_run(), res)

    assert report.run_status == "all_complete"
    assert len(report.completed) == 2
    assert len(report.blocked) == 0
    assert len(report.owner_gated_pending) == 0


# ---------------------------------------------------------------------------
# 2. awaiting_owner_gate when non-gated COMPLETED; OWNER_GATED remain
# ---------------------------------------------------------------------------


def test_awaiting_owner_gate_status():
    res = _reservoir()
    leaf_ws = _leaf("bp:t1:retrieve-evidence", authority_class=AUTH_WORKSPACE)
    leaf_og = _leaf("bp:t2:canonical-mutation", authority_class=AUTH_PRODUCTION, deps=[leaf_ws.key])
    res.register(leaf_ws)
    res.register(leaf_og)
    res.refill()

    # Complete the workspace leaf.
    res.lease(leaf_ws.key, holder="test")
    res.complete(leaf_ws.key, evidence={"done": True})
    res.refill()

    # Owner-gated leaf must still be OWNER_GATED (not auto-dispatched).
    assert res.get(leaf_og.key).state == TaskState.OWNER_GATED

    bp = _FakeBlueprint([leaf_ws, leaf_og])
    report = build_blueprint_run_report(bp, _empty_run(), res)

    assert report.run_status == "awaiting_owner_gate"
    assert len(report.owner_gated_pending) == 1
    assert report.owner_gated_pending[0]["key"] == leaf_og.key
    assert report.owner_gated_pending[0]["requires_owner_gate"] is True
    assert len(report.completed) == 1


# ---------------------------------------------------------------------------
# 3. partially_blocked when BLOCKED and nothing in_progress
# ---------------------------------------------------------------------------


def test_partially_blocked_status():
    res = _reservoir()
    leaf_a = _leaf("bp:t1:retrieve-evidence")
    leaf_b = _leaf("bp:t2:normalize-evidence")
    res.register(leaf_a)
    res.register(leaf_b)
    res.refill()
    res.lease(leaf_a.key, holder="test")
    res.block(leaf_a.key, reason="SOURCE_UNAVAILABLE")
    res.lease(leaf_b.key, holder="test")
    res.complete(leaf_b.key, evidence={"done": True})

    bp = _FakeBlueprint([leaf_a, leaf_b])
    report = build_blueprint_run_report(bp, _empty_run(), res)

    assert report.run_status == "partially_blocked"
    assert len(report.blocked) == 1
    assert report.blocked[0]["key"] == leaf_a.key
    assert len(report.completed) == 1


# ---------------------------------------------------------------------------
# 4. in_progress when READY leaves remain
# ---------------------------------------------------------------------------


def test_in_progress_when_ready_leaves_remain():
    res = _reservoir()
    leaf_a = _leaf("bp:t1:retrieve-evidence")
    leaf_b = _leaf("bp:t2:normalize-evidence")
    res.register(leaf_a)
    res.register(leaf_b)
    res.refill()
    # Only complete leaf_a; leaf_b is still READY.
    res.lease(leaf_a.key, holder="test")
    res.complete(leaf_a.key, evidence={"done": True})

    bp = _FakeBlueprint([leaf_a, leaf_b])
    report = build_blueprint_run_report(bp, _empty_run(), res)

    assert report.run_status == "in_progress"
    assert len(report.ready) == 1
    assert report.ready[0]["key"] == leaf_b.key


# ---------------------------------------------------------------------------
# 5. in_progress when ACTIVE (leased) leaves remain
# ---------------------------------------------------------------------------


def test_in_progress_when_active_leaves_remain():
    res = _reservoir()
    leaf_a = _leaf("bp:t1:retrieve-evidence")
    res.register(leaf_a)
    res.refill()
    res.lease(leaf_a.key, holder="test")  # leaf_a now LEASED

    bp = _FakeBlueprint([leaf_a])
    report = build_blueprint_run_report(bp, _empty_run(), res)

    assert report.run_status == "in_progress"
    assert len(report.active) == 1


# ---------------------------------------------------------------------------
# 6. in_progress when REPAIR_BACKOFF leaves remain
# ---------------------------------------------------------------------------


def test_in_progress_when_repair_backoff():
    res = _reservoir()
    leaf_a = _leaf("bp:t1:retrieve-evidence")
    res.register(leaf_a)
    res.refill()
    res.lease(leaf_a.key, holder="test")
    # Expire the lease immediately.
    expired = res.recover_expired_leases(max_lease_age_seconds=0.0)
    assert len(expired) == 1

    bp = _FakeBlueprint([leaf_a])
    report = build_blueprint_run_report(bp, _empty_run(), res)

    assert report.run_status == "in_progress"
    assert len(report.repair_backoff) == 1


# ---------------------------------------------------------------------------
# 7. owner_gated_pending list is accurate
# ---------------------------------------------------------------------------


def test_owner_gated_pending_list():
    res = _reservoir()
    leaf_ws = _leaf("bp:t1:retrieve-evidence", authority_class=AUTH_WORKSPACE)
    leaf_gov = _leaf("bp:t2:governed-action", authority_class=AUTH_GOVERNANCE)
    leaf_prod = _leaf("bp:t3:prod-action", authority_class=AUTH_PRODUCTION)
    res.register(leaf_ws)
    res.register(leaf_gov)
    res.register(leaf_prod)
    res.refill()
    res.lease(leaf_ws.key, holder="test")
    res.complete(leaf_ws.key, evidence={})

    bp = _FakeBlueprint([leaf_ws, leaf_gov, leaf_prod])
    report = build_blueprint_run_report(bp, _empty_run(), res)

    gated_keys = {e["key"] for e in report.owner_gated_pending}
    assert leaf_gov.key in gated_keys
    assert leaf_prod.key in gated_keys
    assert leaf_ws.key not in gated_keys
    assert all(e["requires_owner_gate"] for e in report.owner_gated_pending)


# ---------------------------------------------------------------------------
# 8. blocked list with reason is accurate
# ---------------------------------------------------------------------------


def test_blocked_list_with_reason():
    res = _reservoir()
    leaf_a = _leaf("bp:t1:retrieve-evidence")
    res.register(leaf_a)
    res.refill()
    res.lease(leaf_a.key, holder="test")
    res.block(leaf_a.key, reason="UPSTREAM_FAILURE")

    # Simulate a DispatchRun that recorded a blocked result.
    from app.calyx_orchestrator.leaf_worker import TaskExecutionResult

    result = TaskExecutionResult(
        task_key=leaf_a.key,
        worker_id="test-worker",
        status="blocked",
        started_at="2026-01-01T00:00:00+00:00",
        completed_at="2026-01-01T00:00:01+00:00",
        duration_seconds=1.0,
        output={},
        error_reason="UPSTREAM_FAILURE",
    )
    run = DispatchRun(results=[result])

    bp = _FakeBlueprint([leaf_a])
    report = build_blueprint_run_report(bp, run, res)

    assert report.run_status == "partially_blocked"
    assert len(report.blocked) == 1
    entry = report.blocked[0]
    assert entry["key"] == leaf_a.key
    assert entry["blocked_reason"] == "UPSTREAM_FAILURE"
    assert "execution_result" in entry


# ---------------------------------------------------------------------------
# 9. completed list contains execution evidence
# ---------------------------------------------------------------------------


def test_completed_list_has_evidence():
    res = _reservoir()
    leaf_a = _leaf("bp:t1:retrieve-evidence")
    res.register(leaf_a)
    res.refill()
    res.lease(leaf_a.key, holder="test")
    res.complete(leaf_a.key, evidence={"retrieved": True})

    from app.calyx_orchestrator.leaf_worker import TaskExecutionResult

    result = TaskExecutionResult(
        task_key=leaf_a.key,
        worker_id="test-worker",
        status="completed",
        started_at="2026-01-01T00:00:00+00:00",
        completed_at="2026-01-01T00:00:01+00:00",
        duration_seconds=1.0,
        output={"retrieved": True, "provider_api_called": False},
    )
    run = DispatchRun(results=[result])

    bp = _FakeBlueprint([leaf_a])
    report = build_blueprint_run_report(bp, run, res)

    assert report.run_status == "all_complete"
    assert len(report.completed) == 1
    completed_entry = report.completed[0]
    assert "execution_result" in completed_entry
    assert completed_entry["execution_result"]["output"]["provider_api_called"] is False


# ---------------------------------------------------------------------------
# 10. missing task (not in reservoir) → counted as ready/in_progress
# ---------------------------------------------------------------------------


def test_missing_task_counted_as_in_progress():
    res = _reservoir()
    leaf_a = _leaf("bp:t1:retrieve-evidence")
    # Deliberately do NOT register leaf_a in the reservoir.

    bp = _FakeBlueprint([leaf_a])
    report = build_blueprint_run_report(bp, _empty_run(), res)

    # Unknown state → falls into ready bucket → in_progress
    assert report.run_status == "in_progress"
    assert len(report.ready) == 1


# ---------------------------------------------------------------------------
# 11. empty blueprint → all_complete
# ---------------------------------------------------------------------------


def test_empty_blueprint_is_all_complete():
    res = _reservoir()
    bp = _FakeBlueprint([])
    report = build_blueprint_run_report(bp, _empty_run(), res)

    assert report.run_status == "all_complete"
    assert report.total_leaves == 0
    assert len(report.completed) == 0


# ---------------------------------------------------------------------------
# 12. report is immutable (frozen dataclass)
# ---------------------------------------------------------------------------


def test_report_is_frozen():
    res = _reservoir()
    bp = _FakeBlueprint([])
    report = build_blueprint_run_report(bp, _empty_run(), res)

    with pytest.raises((AttributeError, TypeError)):
        report.run_status = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 13. as_dict() is fully serializable
# ---------------------------------------------------------------------------


def test_as_dict_is_serializable():
    import json

    res = _reservoir()
    leaf_a = _leaf("bp:t1:retrieve-evidence")
    res.register(leaf_a)
    res.refill()
    res.lease(leaf_a.key, holder="test")
    res.complete(leaf_a.key, evidence={"done": True})

    bp = _FakeBlueprint([leaf_a])
    report = build_blueprint_run_report(bp, _empty_run(), res)

    d = report.as_dict()
    # Must not raise — all values must be JSON-serializable.
    serialized = json.dumps(d)
    assert "all_complete" in serialized
    assert REPORT_VERSION in serialized


# ---------------------------------------------------------------------------
# 14. E2E: GovernanceDecision → blueprint → enqueue → dispatch → report
# ---------------------------------------------------------------------------


def test_e2e_full_autonomous_loop_produces_report():
    """Provider-free end-to-end: governance → blueprint → queue → dispatch → report."""
    from app.scientific_synthesis.blueprint import (
        decompose_governed_action,
        enqueue_blueprint,
        validate_blueprint,
    )
    from app.scientific_synthesis.governance import (
        GovernanceDecision,
        GovernanceOutcome,
    )
    from app.scientific_synthesis.run_manifest import (
        MANIFEST_VERSION,
        build_run_evidence_manifest,
    )

    # Build a minimal but valid verification packet.
    _packet = {
        "contract_version": "oc-verification-handoff-v1",
        "verification_state": "ready_for_review",
        "reasoning": {
            "contract_version": "oc-parallel-v1",
            "candidate_knowledge": {
                "candidate_id": "candidate:report-e2e",
                "subject_id": "taxon:orchidaceae",
                "predicate": "has_common_name",
                "object_id": "Moth Orchid",
                "evidence_ids": ["ev-r-1"],
                "confidence": 0.9,
                "review_state": "candidate",
            },
            "contradictions": [],
            "validation_pathways": ["taxonomist_review"],
            "human_review_required": True,
            "automatic_scientific_publication_allowed": False,
            "private_chain_of_thought_stored": False,
        },
        "resolved_evidence": [
            {
                "evidence_id": "ev-r-1",
                "source_id": "src-r-001",
                "statement": "Phalaenopsis amabilis is the Moth Orchid.",
                "provenance": ["doi:10.0000/report-e2e"],
                "confidence": 0.9,
            }
        ],
        "missing_evidence_ids": [],
        "knowledge_gaps": [],
        "contradictions": [],
        "human_review_required": True,
        "automatic_scientific_publication_allowed": False,
    }

    manifest_dict = build_run_evidence_manifest(
        run_id="e2e-report-run-001",
        taxon_id="taxon:orchidaceae",
        research_question="Is the common name correct?",
        taxonomy_snapshot_id="snap-report-001",
        verification_packets=(_packet,),
        review_records=(),
        epistemic_memory_entries=(),
    )
    assert manifest_dict.get("contract_version") == MANIFEST_VERSION

    decision = GovernanceDecision(
        outcome=GovernanceOutcome.ADMITTED,
        admitted=True,
        reason="Test governance pass",
        blocking_flags=[],
    )

    blueprint = decompose_governed_action(
        decision,
        manifest_dict,
        "build_synthesis",
        run_id="e2e-report-run-001",
        taxon_id="taxon:orchidaceae",
        research_question="Is the common name correct?",
    )
    validate_blueprint(blueprint)

    assert blueprint.governance_outcome == GovernanceOutcome.ADMITTED

    res = DeepOrchestrate(configured_width=8)
    enqueue_blueprint(blueprint, res)

    dispatcher = BoundedDispatcher(
        res, worker=DeterministicResearchWorker()
    )
    run = dispatcher.run(config=DispatchConfig(max_tasks=20, max_iterations=20))

    report = build_blueprint_run_report(blueprint, run, res)

    # Every non-owner-gated leaf should be completed.
    assert report.run_status in ("all_complete", "awaiting_owner_gate")

    # No provider calls made anywhere.
    for result in run.results:
        assert result.output.get("provider_api_called") is False, (
            f"provider call detected in {result.task_key}"
        )

    # Report is serializable.
    import json
    serialized = json.dumps(report.as_dict())
    assert blueprint.blueprint_id in serialized
    assert REPORT_VERSION in serialized

    # Report metadata matches blueprint.
    assert report.blueprint_id == blueprint.blueprint_id
    assert report.run_fingerprint == blueprint.run_fingerprint
    assert report.proposed_action == blueprint.proposed_action
    assert report.total_leaves == len(blueprint.task_leaves)

    # Owner-gated tasks (if any) are surfaced in the report.
    gated_in_report = {e["key"] for e in report.owner_gated_pending}
    gated_in_reservoir = {t.key for t in res.owner_gated_tasks()}
    assert gated_in_report == gated_in_reservoir

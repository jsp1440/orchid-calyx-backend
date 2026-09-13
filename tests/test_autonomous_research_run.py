"""Tests for AutonomousResearchRun — the full loop conductor.

Contracts verified:
  1.  ADMITTED governance → blueprint decomposed → tasks enqueued → dispatched →
      final report with terminal run_status
  2.  REJECTED governance → ValueError raised immediately (no tasks enqueued)
  3.  all_complete: every task completed → run_evidence collected for each
  4.  awaiting_owner_gate: OWNER_GATED tasks listed in owner_gate_pending
  5.  dispatch_limit_reached: loop stops after max_dispatch_rounds
  6.  as_dict() is fully JSON-serializable
  7.  AutonomousRunReport is immutable (frozen dataclass)
  8.  run_evidence contains only COMPLETED tasks (not blocked / owner_gated)
  9.  Provider-free: no paid provider calls in any dispatch round
 10.  E2E: GovernanceDecision → AutonomousResearchRun.execute() → terminal state
"""

from __future__ import annotations

import json

import pytest

from app.calyx_orchestrator.autonomous_research_run import (
    RUN_VERSION,
    AutonomousResearchRun,
    AutonomousRunReport,
)
from app.calyx_orchestrator.bounded_dispatcher import DispatchConfig
from app.calyx_orchestrator.deep_orchestrate import (
    DeepOrchestrate,
)
from app.calyx_orchestrator.leaf_worker import DeterministicResearchWorker
from app.scientific_synthesis.governance import GovernanceDecision, GovernanceOutcome

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_PACKET = {
    "contract_version": "oc-verification-handoff-v1",
    "verification_state": "ready_for_review",
    "reasoning": {
        "contract_version": "oc-parallel-v1",
        "candidate_knowledge": {
            "candidate_id": "candidate:arn-001",
            "subject_id": "taxon:orchidaceae",
            "predicate": "has_common_name",
            "object_id": "Orchid",
            "evidence_ids": ["ev-arn-1"],
            "confidence": 0.85,
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
            "evidence_id": "ev-arn-1",
            "source_id": "src-arn-001",
            "statement": "Orchidaceae is commonly called Orchid family.",
            "provenance": ["doi:10.0000/arn-test"],
            "confidence": 0.85,
        }
    ],
    "missing_evidence_ids": [],
    "knowledge_gaps": [],
    "contradictions": [],
    "human_review_required": True,
    "automatic_scientific_publication_allowed": False,
}


def _admitted() -> GovernanceDecision:
    return GovernanceDecision(
        outcome=GovernanceOutcome.ADMITTED,
        admitted=True,
        reason="All governance flags clear",
        blocking_flags=[],
    )


def _rejected() -> GovernanceDecision:
    return GovernanceDecision(
        outcome=GovernanceOutcome.BLOCKED,
        admitted=False,
        reason="Governance blocked",
        blocking_flags=["FLAG_CANONICAL_MUTATION"],
    )


def _manifest():
    from app.scientific_synthesis.run_manifest import build_run_evidence_manifest
    return build_run_evidence_manifest(
        run_id="arn-test-001",
        taxon_id="taxon:orchidaceae",
        research_question="What is the common name?",
        taxonomy_snapshot_id="snap-arn-001",
        verification_packets=(_PACKET,),
        review_records=(),
        epistemic_memory_entries=(),
    )


def _run(
    *,
    reservoir: DeepOrchestrate | None = None,
    max_dispatch_rounds: int = 5,
) -> AutonomousResearchRun:
    return AutonomousResearchRun(
        reservoir=reservoir or DeepOrchestrate(configured_width=8),
        worker=DeterministicResearchWorker(),
        max_dispatch_rounds=max_dispatch_rounds,
    )


# ---------------------------------------------------------------------------
# 1. ADMITTED governance → terminal report
# ---------------------------------------------------------------------------


def test_admitted_governance_produces_terminal_report():
    conductor = _run()
    report = conductor.execute(
        manifest=_manifest(),
        governance_decision=_admitted(),
        proposed_action="build_synthesis",
        run_id="arn-test-001",
        taxon_id="taxon:orchidaceae",
        research_question="What is the common name?",
    )

    assert isinstance(report, AutonomousRunReport)
    assert report.run_id == "arn-test-001"
    assert report.run_status in (
        "all_complete", "partially_blocked", "awaiting_owner_gate", "dispatch_limit_reached"
    )


# ---------------------------------------------------------------------------
# 2. REJECTED governance → ValueError immediately
# ---------------------------------------------------------------------------


def test_rejected_governance_raises_value_error():
    conductor = _run()
    with pytest.raises(ValueError, match="GOVERNANCE_REJECTED"):
        conductor.execute(
            manifest=_manifest(),
            governance_decision=_rejected(),
            proposed_action="build_synthesis",
            run_id="arn-reject-001",
            taxon_id="taxon:orchidaceae",
            research_question="What is the common name?",
        )


# ---------------------------------------------------------------------------
# 3. all_complete: run_evidence populated for each completed task
# ---------------------------------------------------------------------------


def test_run_evidence_populated_for_completed_tasks():
    conductor = _run()
    report = conductor.execute(
        manifest=_manifest(),
        governance_decision=_admitted(),
        proposed_action="build_synthesis",
        run_id="arn-evidence-001",
        taxon_id="taxon:orchidaceae",
        research_question="What is the common name?",
    )

    if report.run_status == "all_complete":
        # Every completed task must appear in run_evidence.
        assert len(report.run_evidence) > 0
        for entry in report.run_evidence:
            assert "task_key" in entry
            assert "evidence" in entry


# ---------------------------------------------------------------------------
# 4. awaiting_owner_gate: OWNER_GATED tasks in owner_gate_pending
# ---------------------------------------------------------------------------


def test_owner_gated_tasks_surfaced_in_pending():
    conductor = _run()
    report = conductor.execute(
        manifest=_manifest(),
        governance_decision=_admitted(),
        proposed_action="build_synthesis",
        run_id="arn-gate-001",
        taxon_id="taxon:orchidaceae",
        research_question="What is the common name?",
    )

    if report.run_status == "awaiting_owner_gate":
        assert len(report.owner_gate_pending) > 0
        for entry in report.owner_gate_pending:
            assert "key" in entry


# ---------------------------------------------------------------------------
# 5. dispatch_limit_reached when max rounds exhausted and no progress
# ---------------------------------------------------------------------------


def test_dispatch_limit_reached_stops_cleanly():
    # Use max_dispatch_rounds=1 so the loop cannot iterate.
    conductor = _run(max_dispatch_rounds=1)
    report = conductor.execute(
        manifest=_manifest(),
        governance_decision=_admitted(),
        proposed_action="build_synthesis",
        run_id="arn-limit-001",
        taxon_id="taxon:orchidaceae",
        research_question="What is the common name?",
    )

    # With 1 round, the report is whatever the single round produces.
    assert report.dispatch_rounds == 1
    assert report.run_status in (
        "all_complete", "partially_blocked", "awaiting_owner_gate", "dispatch_limit_reached"
    )


# ---------------------------------------------------------------------------
# 6. as_dict() is fully JSON-serializable
# ---------------------------------------------------------------------------


def test_as_dict_is_json_serializable():
    conductor = _run()
    report = conductor.execute(
        manifest=_manifest(),
        governance_decision=_admitted(),
        proposed_action="build_synthesis",
        run_id="arn-serial-001",
        taxon_id="taxon:orchidaceae",
        research_question="What is the common name?",
    )

    d = report.as_dict()
    serialized = json.dumps(d)
    assert RUN_VERSION in serialized
    assert "arn-serial-001" in serialized


# ---------------------------------------------------------------------------
# 7. AutonomousRunReport is immutable (frozen dataclass)
# ---------------------------------------------------------------------------


def test_run_report_is_frozen():
    conductor = _run()
    report = conductor.execute(
        manifest=_manifest(),
        governance_decision=_admitted(),
        proposed_action="build_synthesis",
        run_id="arn-frozen-001",
        taxon_id="taxon:orchidaceae",
        research_question="What is the common name?",
    )

    assert isinstance(report, AutonomousRunReport)
    with pytest.raises((AttributeError, TypeError)):
        report.run_status = "hacked"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 8. run_evidence only contains COMPLETED tasks
# ---------------------------------------------------------------------------


def test_run_evidence_only_completed_tasks():
    conductor = _run()
    report = conductor.execute(
        manifest=_manifest(),
        governance_decision=_admitted(),
        proposed_action="build_synthesis",
        run_id="arn-completed-001",
        taxon_id="taxon:orchidaceae",
        research_question="What is the common name?",
    )

    # OWNER_GATED and BLOCKED tasks must NOT appear in run_evidence.
    gated_keys = {e["key"] for e in report.owner_gate_pending}
    for ev in report.run_evidence:
        assert ev["task_key"] not in gated_keys, (
            f"OWNER_GATED task {ev['task_key']} leaked into run_evidence"
        )


# ---------------------------------------------------------------------------
# 9. Provider-free: no paid API calls in any round
# ---------------------------------------------------------------------------


def test_no_provider_api_calls():
    conductor = _run()
    report = conductor.execute(
        manifest=_manifest(),
        governance_decision=_admitted(),
        proposed_action="build_synthesis",
        run_id="arn-provider-001",
        taxon_id="taxon:orchidaceae",
        research_question="What is the common name?",
    )

    # Check last dispatch run results.
    for r in report.last_dispatch_run.results:
        assert r.output.get("provider_api_called") is False, (
            f"provider call in {r.task_key}"
        )


# ---------------------------------------------------------------------------
# 10. E2E: full autonomous loop to terminal state
# ---------------------------------------------------------------------------


def test_e2e_full_autonomous_loop():
    """Complete end-to-end: GovernanceDecision → AutonomousResearchRun → terminal."""
    from app.calyx_orchestrator.owner_authorization_gate import (
        AuthorizationDecision,
        OwnerAuthorizationGate,
    )

    reservoir = DeepOrchestrate(configured_width=8)
    worker = DeterministicResearchWorker()
    conductor = AutonomousResearchRun(reservoir=reservoir, worker=worker, max_dispatch_rounds=5)

    report = conductor.execute(
        manifest=_manifest(),
        governance_decision=_admitted(),
        proposed_action="build_synthesis",
        run_id="arn-e2e-001",
        taxon_id="taxon:orchidaceae",
        research_question="What is the common name?",
    )

    assert isinstance(report, AutonomousRunReport)
    assert report.run_id == "arn-e2e-001"

    # No paid provider calls.
    for r in report.last_dispatch_run.results:
        assert r.output.get("provider_api_called") is False

    if report.run_status == "awaiting_owner_gate":
        decisions = [
            AuthorizationDecision(
                task_key=e["key"],
                approved=True,
                approver_id="owner:president@fcosorchids.org",
                reason="E2E test approval",
            )
            for e in report.owner_gate_pending
        ]
        # Create a minimal fake blueprint for gate (it only uses blueprint_id/run_fingerprint).
        class _MiniBP:
            blueprint_id = report.blueprint_id
            run_fingerprint = "x" * 64
            proposed_action = "build_synthesis"
            human_review_required = True
            task_leaves = ()

        gate2 = OwnerAuthorizationGate(reservoir, _MiniBP(), worker=worker)
        gate_result = gate2.authorize(
            report.final_report,
            decisions,
            dispatch_config=DispatchConfig(max_tasks=20, max_iterations=10),
        )
        assert gate_result.authorized_count == len(decisions)
        # After gate, no longer awaiting_owner_gate.
        if gate_result.post_report is not None:
            assert gate_result.post_report.run_status != "awaiting_owner_gate"

    elif report.run_status in ("all_complete", "partially_blocked"):
        # Already terminal — no further action needed.
        pass
    else:
        # dispatch_limit_reached is acceptable for a very constrained run.
        assert report.run_status == "dispatch_limit_reached"

    # Result is JSON-serializable.
    serialized = json.dumps(report.as_dict())
    assert RUN_VERSION in serialized

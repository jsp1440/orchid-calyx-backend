"""Contract tests for the event-driven continuous-execution supervisor.

These are deliberately structural: the supervisor delegates priority, leasing,
repair and owner-gate decisions to the already-tested canonical portfolio
scheduler. This suite proves that terminal worker events cannot become a silent
endpoint and that the supervisor does not bypass the canonical scheduler.
"""

from pathlib import Path


WORKFLOW = Path(".github/workflows/orchid-continuation-supervisor.yml")
POLICY = Path("docs/governance/CONTINUOUS_EXECUTION_RULE.md")


def test_completion_lane_terminal_event_wakes_supervisor() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'workflows: ["Orchid Completion Lane"]' in text
    assert "types: [completed]" in text


def test_supervisor_delegates_to_canonical_scheduler() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "SCHEDULER_WORKFLOW: orchid-continuous-completion.yml" in text
    assert 'gh workflow run "$SCHEDULER_WORKFLOW"' in text
    assert '--ref "$INTEGRATION_BRANCH"' in text


def test_checkpoint_contract_includes_failure_correction_and_next_action() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for required in (
        "Error/failure:",
        "Likely cause:",
        "Correction:",
        "Continuation decision:",
        "Next action:",
    ):
        assert required in text
    assert 'decision="REPAIR"' in text
    assert 'decision="SELECT_NEXT_TASK"' in text


def test_policy_makes_reporting_nonterminal_and_preserves_owner_gates() -> None:
    text = POLICY.read_text(encoding="utf-8")
    assert "Status reports are execution checkpoints, not endpoints." in text
    assert "VERIFY → REPORT → REPAIR → CONTINUE → SELECT NEXT TASK" in text
    assert "oc-owner-gate" in text
    assert "MUST NOT prevent unrelated eligible work from continuing" in text


def test_periodic_recovery_heartbeat_is_preserved() -> None:
    """The new supervisor must complement, not replace, scheduler recovery."""
    policy = POLICY.read_text(encoding="utf-8")
    assert "periodic scheduler remains a recovery heartbeat" in policy

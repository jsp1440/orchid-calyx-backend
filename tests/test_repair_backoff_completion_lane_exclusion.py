"""``oc-repair-backoff`` stays authoritative in the completion lane.

#1795 moved lease ownership out of inline workflow shell into
``scripts.oc_swarm_settlement``. The guarantee is unchanged: a repair-backoff
issue never runs a provider and is never requeued by a worker. The mechanism
changed. ``oc-repair-backoff`` is a parked label, so the lane's lease
verification and every settlement refuse the claim, and the label state is
left untouched rather than rewritten by the worker. These tests pin the
workflow wiring and exercise the real settlement code.
"""

from pathlib import Path

import pytest

from scripts.oc_swarm_claim import PARKED
from scripts.oc_swarm_settlement import settle_worker
from tests.test_oc_swarm_acquisition_worker import claimed

WORKFLOW = Path(".github/workflows/orchid-completion-lane.yml")


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _settle_step(text: str) -> str:
    return text[
        text.index("- name: Classify result, dispatch validation, release slot") :
    ]


def test_repair_backoff_blocks_completion_lane_before_provider_execution() -> None:
    text = _workflow_text()
    lease = text[
        text.index("- name: Verify scheduler lease") : text.index(
            "- name: Load issue context"
        )
    ]
    # Execution is granted only by verified ownership; labels never grant it.
    assert "python3 -m scripts.oc_swarm_settlement --verify-only" in lease
    assert lease.index("--verify-only") < lease.index('echo "execute=true"')
    assert 'echo "execute=false" >> "$GITHUB_OUTPUT"' in lease
    assert "oc-repair-backoff" in PARKED


def test_repair_backoff_is_authoritative_during_worker_settlement() -> None:
    settle = _settle_step(_workflow_text())
    # Every disposition goes through the verified settlement helper; the step
    # never edits the claimed issue's queue labels itself. (Issue #1031 is the
    # global runtime circuit breaker, not the worker's issue.)
    assert "settle() {" in settle
    assert "python3 -m scripts.oc_swarm_settlement --disposition" in settle
    assert "--add-label oc-queued" not in settle
    assert 'gh issue edit "$ISSUE_NUMBER"' not in settle


def test_all_no_durable_pr_requeue_paths_are_behind_repair_backoff_guard() -> None:
    settle = _settle_step(_workflow_text())
    helper = settle.index("settle() {")
    for marker in (
        'elif [[ "$CLAUDE_FALLBACK" == "true" && "$GEMINI_OUTCOME" == "success" ]]',
        'elif [[ "$GEMINI_FALLBACK" == "true" && "$OPENAI_OUTCOME" == "success" ]]',
    ):
        position = settle.index(marker)
        assert position > helper
        branch = settle[position:].split("\n", 2)[1]
        assert branch.strip().startswith("settle queued ")


def test_settlement_refuses_a_repair_backoff_claim_and_writes_nothing() -> None:
    transport, identity = claimed()
    transport.issue["labels"].append("oc-repair-backoff")
    labels_before = sorted(transport.issue["labels"])
    comments_before = len(transport.comments)
    with pytest.raises(ValueError, match="exclusive running state"):
        settle_worker(
            result={"disposition": "queued", "repair_queued": True},
            call=transport,
            **identity,
        )
    assert sorted(transport.issue["labels"]) == labels_before
    assert len(transport.comments) == comments_before

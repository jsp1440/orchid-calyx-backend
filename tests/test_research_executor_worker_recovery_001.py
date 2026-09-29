"""Worker binding for the research executor (CALYX-RECOVERY-001 Gate 2 wiring).

The executor is useless if nothing invokes it, and dangerous if a deploy that
was never authorized to execute research starts executing it. These cover the
wiring: which store is live, when the loop is allowed to run, and that a
terminal request reports back to the issue that asked for it — once.
"""

from __future__ import annotations

from runtime.research_executor import MemoryRequestStore, RunOutcome
from runtime.research_executor_worker import (
    WORKER_ENABLED_ENV,
    build_feedback,
    run_once,
    store_persistence_mode,
    worker_enabled,
)

ENABLED = {WORKER_ENABLED_ENV: "true"}


class _Runner:
    def run(self, request):
        return RunOutcome.completed(artifact_ids=("artifact-1",))


class _Blocked:
    def run(self, request):
        return RunOutcome.blocked(code="INSUFFICIENT_EVIDENCE", detail="nothing eligible")


def _request():
    return {
        "id": "RSR-GH-WIRE01",
        "status": "queued_waiting_for_executor",
        "research_question": "Ecology of Calypso bulbosa",
        "provenance": {
            "source_repository": "jsp1440/Orchid-Continuum-Brain",
            "source_issue_number": 101,
        },
    }


# ------------------------------------------------------------------- the gate


def test_the_worker_is_off_unless_explicitly_enabled():
    """A deploy not authorized to execute research must not start executing."""
    assert worker_enabled({}) is False
    assert worker_enabled({WORKER_ENABLED_ENV: "false"}) is False

    store = MemoryRequestStore([_request()])
    report = run_once(runner=_Runner(), store=store, feedback=lambda record: None, env={})

    assert report.claimed is False
    assert WORKER_ENABLED_ENV in report.notes[0]
    assert store.all()[0]["status"] == "queued_waiting_for_executor"


def test_enabling_the_worker_lets_one_request_execute():
    store = MemoryRequestStore([_request()])
    report = run_once(
        runner=_Runner(), store=store, feedback=lambda record: None, env=ENABLED
    )

    assert report.claimed is True
    assert store.all()[0]["status"] == "completed"


# ---------------------------------------------------------------- persistence


def test_persistence_mode_is_reported_not_assumed():
    """A caller must be able to tell durable storage from the fallback."""
    assert store_persistence_mode({"DATABASE_URL": "postgres://x"}) == "durable_database"
    assert store_persistence_mode({}) == "in_process_memory"


# ------------------------------------------------------------------- feedback


def test_a_completed_request_reports_its_artifacts_to_the_asking_issue():
    sent = []
    feedback = build_feedback(send=lambda **kwargs: sent.append(kwargs))
    store = MemoryRequestStore([_request()])
    run_once(runner=_Runner(), store=store, feedback=feedback, env=ENABLED)

    assert len(sent) == 1
    assert sent[0]["repository"] == "jsp1440/Orchid-Continuum-Brain"
    assert sent[0]["issue_number"] == 101
    assert "artifact-1" in sent[0]["message"]
    assert "completed" in sent[0]["message"]


def test_the_status_comment_reuses_the_intake_marker():
    """Keyed by request id, so the executor edits the intake's own comment.

    Deduplication is a property of the marker rather than of a check somebody
    has to remember to write.
    """
    sent = []
    feedback = build_feedback(send=lambda **kwargs: sent.append(kwargs))
    store = MemoryRequestStore([_request()])
    run_once(runner=_Runner(), store=store, feedback=feedback, env=ENABLED)

    assert sent[0]["marker"] == "<!-- calyx-research-bridge:RSR-GH-WIRE01 -->"
    assert sent[0]["marker"] in sent[0]["message"]


def test_a_blocked_request_says_whether_asking_again_could_help():
    """"Blocked" on its own invites a pointless retry."""
    sent = []
    feedback = build_feedback(send=lambda **kwargs: sent.append(kwargs))
    store = MemoryRequestStore([_request()])
    run_once(runner=_Blocked(), store=store, feedback=feedback, env=ENABLED)

    message = sent[0]["message"]
    assert "INSUFFICIENT_EVIDENCE" in message
    assert "will not change this without new evidence" in message


def test_a_request_with_no_source_issue_is_not_reported_anywhere():
    """Not every request came from GitHub; inventing a destination is worse."""
    sent = []
    feedback = build_feedback(send=lambda **kwargs: sent.append(kwargs))
    record = _request()
    record["provenance"] = {}
    run_once(
        runner=_Runner(),
        store=MemoryRequestStore([record]),
        feedback=feedback,
        env=ENABLED,
    )

    assert sent == []

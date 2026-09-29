"""Acceptance tests for the BUILD-051 research executor (CALYX-RECOVERY-001 Gate 2).

These prove the state machine, not the science. The runner is deterministic on
purpose: the properties that matter here are durability properties — claimed
exactly once, replayed without duplication, abandoned work reclaimable, failure
recorded rather than smoothed over — and a real scientific runner would make
those harder to test without making them any more true.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from runtime.research_executor import (
    BLOCKED,
    COMPLETED,
    QUEUED_WAITING_FOR_EXECUTOR,
    RUNNING,
    BlockerCode,
    MemoryRequestStore,
    ResearchExecutor,
    RunOutcome,
)

T0 = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)


def _request(request_id: str = "RSR-GH-TEST01") -> dict:
    """A record shaped the way the GitHub bridge actually persists one."""
    return {
        "id": request_id,
        "title": "Ecology of Calypso bulbosa",
        "research_question": "What is known about the mycorrhizal associations of Calypso bulbosa?",
        "taxa": ["Calypso bulbosa"],
        "status": QUEUED_WAITING_FOR_EXECUTOR,
        "blocker": "No live research executor/result-return worker is activated.",
        "created_by": "github_research_bridge",
        "created_at": T0.isoformat(),
        "updated_at": T0.isoformat(),
    }


class _CompletingRunner:
    def __init__(self, artifact_ids=("artifact-1",)) -> None:
        self.artifact_ids = tuple(artifact_ids)
        self.calls = 0

    def run(self, request):
        self.calls += 1
        return RunOutcome.completed(
            artifact_ids=self.artifact_ids,
            evidence_summary={"literature": "AVAILABLE", "records": 3},
        )


class _BlockingRunner:
    def __init__(self, code=BlockerCode.INSUFFICIENT_EVIDENCE) -> None:
        self.code = code
        self.calls = 0

    def run(self, request):
        self.calls += 1
        return RunOutcome.blocked(code=self.code, detail="no eligible evidence found")


class _ExplodingRunner:
    def run(self, request):
        raise RuntimeError("retrieval provider exploded")


def _executor(store, runner, *, worker_id="w1", clock=None, feedback=None):
    return ResearchExecutor(
        store=store,
        runner=runner,
        worker_id=worker_id,
        feedback=feedback,
        clock=clock or (lambda: T0),
    )


# ----------------------------------------------------------------- the claim


def test_one_queued_request_is_claimed_and_completed():
    store = MemoryRequestStore([_request()])
    runner = _CompletingRunner()

    report = _executor(store, runner).execute_once()

    assert report.claimed is True
    assert report.state == COMPLETED
    assert report.artifact_ids == ("artifact-1",)
    assert runner.calls == 1


def test_the_intakes_resting_state_is_claimable():
    """Nothing promotes queued_waiting_for_executor to queued.

    If the executor only accepted `queued`, the queue would stay permanently
    empty while every part of the system looked correctly configured.
    """
    store = MemoryRequestStore([_request()])
    assert store.all()[0]["status"] == QUEUED_WAITING_FOR_EXECUTOR

    assert _executor(store, _CompletingRunner()).execute_once().claimed is True


def test_the_intake_blocker_is_cleared_once_a_worker_holds_the_request():
    """That blocker asserts no executor exists. One now does."""
    store = MemoryRequestStore([_request()])
    _executor(store, _CompletingRunner()).execute_once()

    assert store.all()[0]["blocker"] is None


def test_two_workers_cannot_claim_the_same_request():
    store = MemoryRequestStore([_request()])
    first = _executor(store, _CompletingRunner(), worker_id="w1").execute_once()
    second = _executor(store, _CompletingRunner(), worker_id="w2").execute_once()

    assert first.claimed is True
    assert second.claimed is False
    assert "no claimable request" in second.notes


def test_a_second_worker_runs_a_different_request_rather_than_idling():
    store = MemoryRequestStore([_request("RSR-A"), _request("RSR-B")])
    first = _executor(store, _CompletingRunner(), worker_id="w1").execute_once()
    second = _executor(store, _CompletingRunner(), worker_id="w2").execute_once()

    assert {first.request_id, second.request_id} == {"RSR-A", "RSR-B"}


# ---------------------------------------------------------------- idempotency


def test_replaying_a_completed_request_does_no_work():
    """Re-running would mint a second set of artifacts for one question."""
    store = MemoryRequestStore([_request()])
    runner = _CompletingRunner()
    executor = _executor(store, runner)
    executor.execute_once()

    replay = executor.execute_request("RSR-GH-TEST01")

    assert replay.replayed is True
    assert replay.state == COMPLETED
    assert replay.artifact_ids == ("artifact-1",)
    assert runner.calls == 1, "the runner must not run twice for one request"


def test_replaying_a_blocked_request_does_not_re_run_it():
    store = MemoryRequestStore([_request()])
    runner = _BlockingRunner()
    executor = _executor(store, runner)
    executor.execute_once()

    replay = executor.execute_request("RSR-GH-TEST01")

    assert replay.replayed is True
    assert replay.state == BLOCKED
    assert runner.calls == 1


def test_feedback_is_sent_once_per_terminal_transition():
    """One request, one answer posted back — not one per replay."""
    store = MemoryRequestStore([_request()])
    sent: list[dict] = []
    executor = _executor(store, _CompletingRunner(), feedback=sent.append)

    executor.execute_once()
    executor.execute_request("RSR-GH-TEST01")

    assert len(sent) == 1


def test_feedback_failure_does_not_undo_a_completed_request():
    def _explode(record):
        raise RuntimeError("github unavailable")

    store = MemoryRequestStore([_request()])
    report = _executor(store, _CompletingRunner(), feedback=_explode).execute_once()

    assert report.state == COMPLETED
    assert store.all()[0]["status"] == COMPLETED


# -------------------------------------------------------------------- leases


def test_an_abandoned_running_request_is_reclaimable_after_its_lease_expires():
    """A worker that dies must not leave a request running forever."""
    store = MemoryRequestStore([_request()])
    _executor(store, _CompletingRunner(), worker_id="dead", clock=lambda: T0).execute_once()
    # Force the record back to a running state with an expired lease, as a
    # crashed worker would have left it.
    record = store.all()[0]
    record["status"] = RUNNING
    record["lease_expires_at"] = (T0 - timedelta(seconds=1)).isoformat()
    store.save(record)

    later = T0 + timedelta(hours=1)
    report = _executor(
        store, _CompletingRunner(), worker_id="fresh", clock=lambda: later
    ).execute_once()

    assert report.claimed is True
    assert store.all()[0]["attempts"] == 2, "a reclaim must be visible as a retry"


def test_a_running_request_inside_its_lease_is_not_stolen():
    store = MemoryRequestStore([_request()])
    record = store.all()[0]
    record["status"] = RUNNING
    record["lease_expires_at"] = (T0 + timedelta(minutes=30)).isoformat()
    store.save(record)

    assert _executor(store, _CompletingRunner(), worker_id="thief").execute_once().claimed is False


def test_a_terminal_request_is_never_reclaimed():
    store = MemoryRequestStore([_request()])
    _executor(store, _CompletingRunner()).execute_once()

    later = T0 + timedelta(days=7)
    assert (
        _executor(store, _CompletingRunner(), clock=lambda: later).execute_once().claimed
        is False
    )


# --------------------------------------------------------- truthful failures


def test_a_runner_that_finds_nothing_blocks_rather_than_completing():
    store = MemoryRequestStore([_request()])
    report = _executor(store, _BlockingRunner()).execute_once()

    assert report.state == BLOCKED
    assert report.blocker_code == BlockerCode.INSUFFICIENT_EVIDENCE
    assert store.all()[0]["blocker"] == "no eligible evidence found"


def test_a_completion_must_point_at_something():
    """A completion with no artifact is indistinguishable from a claim."""
    with pytest.raises(ValueError):
        RunOutcome.completed(artifact_ids=[])


def test_a_runner_crash_is_recorded_as_a_blocker_not_a_silence():
    store = MemoryRequestStore([_request()])
    report = _executor(store, _ExplodingRunner()).execute_once()

    assert report.state == BLOCKED
    assert report.blocker_code == BlockerCode.RUNNER_FAILED
    assert "retrieval provider exploded" in store.all()[0]["blocker"]


def test_retryable_and_terminal_blockers_are_distinguished():
    """Requeueing an insufficient-evidence request would just burn the corpus."""
    assert BlockerCode.is_retryable(BlockerCode.EVIDENCE_UNAVAILABLE) is True
    assert BlockerCode.is_retryable(BlockerCode.INSUFFICIENT_EVIDENCE) is False

    store = MemoryRequestStore([_request()])
    _executor(store, _BlockingRunner(BlockerCode.EVIDENCE_UNAVAILABLE)).execute_once()
    assert store.all()[0]["blocker_retryable"] is True


# ------------------------------------------------------------ durable record


def test_artifact_ids_and_evidence_summary_survive_completion():
    store = MemoryRequestStore([_request()])
    _executor(store, _CompletingRunner(("a1", "a2"))).execute_once()

    record = store.all()[0]
    assert record["artifact_ids"] == ["a1", "a2"]
    assert record["evidence_summary"] == {"literature": "AVAILABLE", "records": 3}


def test_transition_history_records_the_whole_path():
    store = MemoryRequestStore([_request()])
    _executor(store, _CompletingRunner()).execute_once()

    path = [(item["from"], item["to"]) for item in store.all()[0]["transitions"]]
    assert path == [(QUEUED_WAITING_FOR_EXECUTOR, RUNNING), (RUNNING, COMPLETED)]


def test_a_terminal_record_releases_its_lease():
    store = MemoryRequestStore([_request()])
    _executor(store, _CompletingRunner()).execute_once()

    assert store.all()[0]["lease_expires_at"] is None


def test_the_executor_never_writes_scientific_state():
    """It records what a runner returned. It decides nothing scientific.

    Asserted structurally: the module imports nothing that could activate
    taxonomy, mutate the graph or publish, so no call path through it can.
    """
    import runtime.research_executor as module

    source = module.__doc__ or ""
    assert "no publication" in source.lower()

    forbidden = ("knowledge_graph", "taxonomy_activation", "publish", "world_plants")
    with open(module.__file__, encoding="utf-8") as handle:
        text = handle.read()
    import_lines = [
        line for line in text.splitlines() if line.startswith(("import ", "from "))
    ]
    for line in import_lines:
        assert not any(token in line for token in forbidden), line

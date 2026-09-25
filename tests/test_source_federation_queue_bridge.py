from dataclasses import replace

from app.source_federation import (
    AccessState,
    CandidateDisposition,
    FederationCandidate,
    RightsState,
    bridge_source_candidates,
    build_default_candidate_inventory,
    persist_source_candidates,
    source_task_key,
)


class FakeQueue:
    def __init__(self) -> None:
        self.tasks: dict[str, dict[str, object]] = {}

    def create_task_once(self, **task: object) -> dict[str, object]:
        task_key = str(task["task_key"])
        if task_key in self.tasks:
            return {"status": "duplicate", "task_key": task_key}
        self.tasks[task_key] = task
        return {"status": "created", "task": task}


def _admitted_candidate(**overrides: object) -> FederationCandidate:
    candidate = FederationCandidate(
        source_owner="Example Herbarium",
        source_name="Example Orchid Trait Dataset",
        identity="doi:10.0000/example",
        access=AccessState.REPOSITORY,
        rights=RightsState.OPEN,
        domains=("traits",),
        identifiers=("10.0000/example",),
        overlap="No existing adapter",
        incremental_value="Reviewed orchid trait records",
        taxonomy_reconciliation="Retain verbatim names and map by pinned taxonomy",
        provenance_contract="Preserve DOI, release, file hash, and row identity",
        locality_risk="low",
        implementation_cost="low",
        requested_disposition=CandidateDisposition.ADD,
        license_identifier="CC-BY-4.0",
        source_url="https://example.org/dataset",
        update_cadence="annual",
        metadata_evidence=("https://example.org/metadata",),
    )
    return replace(candidate, **overrides)


def test_only_fully_admitted_add_candidate_produces_child_task() -> None:
    admitted = _admitted_candidate()
    deferred = replace(admitted, identity="doi:10.0000/deferred", rights=RightsState.UNKNOWN)
    kept = replace(
        admitted,
        identity="https://example.org/existing",
        requested_disposition=CandidateDisposition.KEEP,
    )

    result = bridge_source_candidates((admitted, deferred, kept))

    assert [task.task_key for task in result.create] == [source_task_key(admitted)]
    assert [item.reason for item in result.suppressed] == [
        "not-admitted",
        "not-admitted",
    ]
    assert result.suppressed[0].blockers == ("rights_unknown",)


def test_child_task_preserves_governance_and_provenance_contract() -> None:
    candidate = _admitted_candidate(
        locality_risk="high: specimen coordinates",
        locality_controls=("strip_precise_coordinates",),
    )

    task = bridge_source_candidates((candidate,)).create[0]

    assert task.priority == "P2"
    assert f"OC-QUEUE-CAPABILITY: {task.task_key}" in task.body
    assert f"OC-SOURCE-FINGERPRINT: {candidate.fingerprint}" in task.body
    assert "OC-SOURCE-LICENSE: CC-BY-4.0" in task.body
    assert "OC-SOURCE-URL: https://example.org/dataset" in task.body
    assert "OC-SOURCE-UPDATE-CADENCE: annual" in task.body
    assert "OC-SOURCE-METADATA-EVIDENCE: https://example.org/metadata" in task.body
    assert "OC-PROVENANCE-CONTRACT: Preserve DOI, release" in task.body
    assert "OC-LOCALITY-CONTROLS: strip_precise_coordinates" in task.body
    assert "OC-SWARM-READS: taxonomy" in task.body
    assert "OC-SWARM-WRITES: source-federation" in task.body
    assert "does not authorize harvesting" in task.body


def test_existing_issue_or_pr_lineage_suppresses_duplicate_capability() -> None:
    candidate = _admitted_candidate()
    task_key = source_task_key(candidate)

    result = bridge_source_candidates(
        (candidate,),
        existing_task_keys=(f"  {task_key.upper()}  ",),
    )

    assert result.create == ()
    assert len(result.suppressed) == 1
    assert result.suppressed[0].reason == "existing-delivery-lineage"


def test_same_candidate_rediscovered_in_one_wave_is_suppressed() -> None:
    candidate = _admitted_candidate()
    rediscovered = replace(candidate, incremental_value="Different queue rationale")

    result = bridge_source_candidates((candidate, rediscovered))

    assert len(result.create) == 1
    assert len(result.suppressed) == 1
    assert result.suppressed[0].reason == "duplicate-candidate"


def test_default_inventory_creates_no_unadmitted_work() -> None:
    result = bridge_source_candidates(build_default_candidate_inventory())

    assert result.create == ()
    assert len(result.suppressed) == len(build_default_candidate_inventory())
    assert {item.reason for item in result.suppressed} == {"not-admitted"}


def test_non_low_cost_candidate_is_conservatively_p3() -> None:
    candidate = _admitted_candidate(implementation_cost="medium")

    task = bridge_source_candidates((candidate,)).create[0]

    assert task.priority == "P3"


def test_durable_bridge_refills_once_and_replay_deduplicates() -> None:
    candidate = _admitted_candidate()
    queue = FakeQueue()

    first = persist_source_candidates((candidate,), queue)
    second = persist_source_candidates((candidate,), queue)

    assert first["status"] == "refill_planned"
    assert first["created_task_keys"] == [source_task_key(candidate)]
    assert second["status"] == "reserve_satisfied"
    assert second["created_task_keys"] == []
    assert second["duplicate_task_keys"] == [source_task_key(candidate)]
    assert len(queue.tasks) == 1


def test_durable_payload_cannot_authorize_fetch_publication_or_mutation() -> None:
    queue = FakeQueue()

    result = persist_source_candidates((_admitted_candidate(),), queue)
    task = queue.tasks[result["created_task_keys"][0]]
    payload = task["payload"]

    assert task["task_type"] == "source_federation_adapter_evaluation"
    assert task["priority"] == 20
    assert payload["execution_mode"] == "draft_only"
    assert payload["network_fetch_authorized"] is False
    assert payload["scientific_publication_authorized"] is False
    assert payload["knowledge_graph_mutation_authorized"] is False
    assert payload["taxonomy_mutation_authorized"] is False
    assert payload["automatic_merge"] is False
    assert payload["automatic_deploy"] is False


def test_unadmitted_protected_source_is_suppressed_before_queue_write() -> None:
    queue = FakeQueue()
    candidate = _admitted_candidate(
        locality_risk="high: specimen coordinates",
        locality_controls=(),
    )

    result = persist_source_candidates((candidate,), queue)

    assert result["status"] == "queue_empty_healthy"
    assert result["eligible_count"] == 0
    assert result["created_task_keys"] == []
    assert result["suppressed"][0]["reason"] == "not-admitted"
    assert "locality_controls_missing" in result["suppressed"][0]["blockers"]
    assert queue.tasks == {}


def test_existing_delivery_lineage_is_suppressed_before_queue_write() -> None:
    queue = FakeQueue()
    candidate = _admitted_candidate()

    result = persist_source_candidates(
        (candidate,),
        queue,
        existing_task_keys=(source_task_key(candidate),),
    )

    assert result["status"] == "queue_empty_healthy"
    assert result["suppressed"][0]["reason"] == "existing-delivery-lineage"
    assert queue.tasks == {}


def test_durable_bridge_bounds_refill_and_reports_truncation() -> None:
    queue = FakeQueue()
    candidates = tuple(
        _admitted_candidate(identity=f"doi:10.0000/example-{index}")
        for index in range(3)
    )

    result = persist_source_candidates(candidates, queue, limit=2)

    assert result["status"] == "refill_planned"
    assert result["candidate_count"] == 3
    assert result["eligible_count"] == 3
    assert result["selected_count"] == 2
    assert result["truncated_count"] == 1
    assert len(queue.tasks) == 2


def test_zero_limit_is_healthy_depletion_not_planner_failure() -> None:
    queue = FakeQueue()

    result = persist_source_candidates((_admitted_candidate(),), queue, limit=0)

    assert result["status"] == "queue_empty_healthy"
    assert result["eligible_count"] == 1
    assert result["selected_count"] == 0
    assert result["truncated_count"] == 1
    assert queue.tasks == {}

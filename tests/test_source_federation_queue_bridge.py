from dataclasses import replace

from app.source_federation import (
    AccessState,
    CandidateDisposition,
    FederationCandidate,
    RightsState,
    bridge_source_candidates,
    build_default_candidate_inventory,
    source_task_key,
)


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

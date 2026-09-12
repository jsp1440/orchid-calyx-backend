"""End-to-end proof of the repaired Calyx path (CALYX-RECOVERY-001 item 7).

BUILD-051 request -> claim -> durable Research Station project -> taxon
resolution -> canonical reads -> artifact -> terminal state -> feedback ->
idempotent replay.

Nothing here is a mocked success. The executor, the worker binding, the
Research Station, the artifact registry, the evidence chain and the taxon
planner are the real implementations. What is substituted is the *data
sources* — the domain readers — because no database is reachable from this
container. That substitution is the honest one: it stands in for rows, not for
the pipeline, and the tests below assert the pipeline's behaviour when the data
is present, when it is absent, and when it was never consultable at all.
"""

from __future__ import annotations

from pathlib import Path

from runtime.research_executor import BlockerCode, MemoryRequestStore
from runtime.research_executor_worker import (
    WORKER_ENABLED_ENV,
    build_feedback,
    run_once,
)
from runtime.research_runner import GovernedResearchRunner
from runtime.research_station import ResearchStationService
from runtime.research_station_store import MemoryProjectRecordStore
from runtime.scientific_reads import (
    CANONICAL_DATABASE,
    REVIEWED_EXTERNAL_DISCOVERY,
    ScientificReadThrough,
    available,
    empty,
)

ENABLED = {WORKER_ENABLED_ENV: "true"}
TAXON = "Laelia anceps"


def _request(request_id="RSR-GH-LAELIA01", question=None):
    return {
        "id": request_id,
        "title": "Laelia anceps ecology",
        "research_question": question
        or f"What habitat, elevation and pollinators are recorded for {TAXON}?",
        "status": "queued_waiting_for_executor",
        "provenance": {
            "source_repository": "jsp1440/Orchid-Continuum-Brain",
            "source_issue_number": 101,
        },
    }


def _covered_readers():
    """Domains a well-covered taxon would answer from, plus honest gaps."""
    return {
        "taxonomy": lambda t: available(
            "taxonomy",
            CANONICAL_DATABASE,
            [{"accepted_name": t, "synonyms": ["Amalia anceps"]}],
        ),
        "occurrences": lambda t: available(
            "occurrences", CANONICAL_DATABASE, [{"id": "occ-1", "country": "MX"}]
        ),
        "elevation": lambda t: available(
            "elevation", CANONICAL_DATABASE, [{"metres": 1500, "source": "occ-1"}]
        ),
        "literature": lambda t: available(
            "literature",
            REVIEWED_EXTERNAL_DISCOVERY,
            [{"doi": "10.0000/fixture", "title": "Fixture record"}],
        ),
        # Genuinely nothing recorded — different from never consulted.
        "pollinators": lambda t: empty("pollinators", CANONICAL_DATABASE, "no rows"),
    }


def _pipeline(tmp_path, readers, request=None, feedback=None):
    station = ResearchStationService(
        tmp_path / "workspace", record_store=MemoryProjectRecordStore()
    )
    runner = GovernedResearchRunner(
        station=station, read_through=ScientificReadThrough(readers)
    )
    store = MemoryRequestStore([request or _request()])
    sent: list[dict] = []
    report = run_once(
        runner=runner,
        store=store,
        # The real feedback binding, capturing what it would send to GitHub
        # rather than the record the executor hands it.
        feedback=feedback if feedback is not None else build_feedback(
            send=lambda **kwargs: sent.append(kwargs)
        ),
        env=ENABLED,
    )
    return report, store, station, sent


# ------------------------------------------------------------ the happy path


def test_a_real_request_runs_end_to_end_and_completes(tmp_path):
    report, store, _, _ = _pipeline(tmp_path, _covered_readers())

    assert report.claimed is True
    assert report.state == "completed"
    assert report.artifact_ids, "a completion must point at an artifact"
    assert store.all()[0]["status"] == "completed"


def test_the_research_project_carries_the_request_identity(tmp_path):
    _, _, station, _ = _pipeline(tmp_path, _covered_readers())

    project = station.manifest("calyx-research-executor", "RSR-GH-LAELIA01")["project"]
    assert project["project_id"] == "RSR-GH-LAELIA01"


def test_the_taxon_is_resolved_from_the_question_when_not_listed(tmp_path):
    request = _request(question=f"Review the mycorrhizal associations of {TAXON}")
    _, store, _, _ = _pipeline(tmp_path, _covered_readers(), request=request)

    # The bare genus is not returned alongside its own binomial: same
    # organism, and reading it twice would search and count it twice.
    assert store.all()[0]["evidence_summary"]["taxa"] == [TAXON]


def test_every_domain_reports_its_origin_and_state(tmp_path):
    _, store, _, _ = _pipeline(tmp_path, _covered_readers())

    domains = store.all()[0]["evidence_summary"]["per_taxon"][TAXON]["domains"]
    assert domains["taxonomy"]["origin"] == CANONICAL_DATABASE
    assert domains["literature"]["origin"] == REVIEWED_EXTERNAL_DISCOVERY
    # Recorded as holding nothing, by a source that was actually consulted.
    assert domains["pollinators"]["state"] == "EMPTY"
    assert domains["pollinators"]["origin"] == CANONICAL_DATABASE
    # Never consulted at all — and never reported as empty.
    assert domains["mycorrhiza"]["state"] == "UNAVAILABLE"
    assert domains["mycorrhiza"]["origin"] is None


def test_an_immutable_artifact_is_created_and_readable(tmp_path):
    report, _, station, _ = _pipeline(tmp_path, _covered_readers())

    record = station.artifact_registry.require(report.artifact_ids[0])
    assert record.checksum
    assert record.media_type == "application/json"


def test_the_claim_recorded_is_for_review_not_a_finding(tmp_path):
    """A read-through is material for review. A claim that marks itself
    supported is a finding nobody made."""
    _, _, station, _ = _pipeline(tmp_path, _covered_readers())

    manifest = station.manifest("calyx-research-executor", "RSR-GH-LAELIA01")
    claims = manifest["records"]["claims"]
    assert claims, "the run recorded no claim"
    assert all(claim["state"] == "needs_review" for claim in claims)


def test_feedback_reaches_the_asking_issue_once(tmp_path):
    report, _, _, sent = _pipeline(tmp_path, _covered_readers())

    assert len(sent) == 1
    assert sent[0]["issue_number"] == 101
    assert report.artifact_ids[0] in sent[0]["message"]


# ----------------------------------------------------------------- replay


def test_replaying_the_request_produces_no_second_project_or_artifact(tmp_path):
    station = ResearchStationService(
        tmp_path / "workspace", record_store=MemoryProjectRecordStore()
    )
    runner = GovernedResearchRunner(
        station=station, read_through=ScientificReadThrough(_covered_readers())
    )
    store = MemoryRequestStore([_request()])
    sent: list[dict] = []

    feedback = build_feedback(send=lambda **kwargs: sent.append(kwargs))
    first = run_once(runner=runner, store=store, feedback=feedback, env=ENABLED)
    second = run_once(runner=runner, store=store, feedback=feedback, env=ENABLED)

    assert first.claimed is True
    assert second.claimed is False, "a completed request was claimed a second time"
    assert len(sent) == 1, "the asking issue was told twice"
    assert len(station.artifact_registry.discover()) == len(first.artifact_ids)


# --------------------------------------------------- truthful missing evidence


def test_a_taxon_with_no_evidence_anywhere_blocks_rather_than_completing(tmp_path):
    """The answer "the Continuum holds nothing for this" is a real answer.

    A fabricated paragraph would not be, and this is the point in the pipeline
    where one would otherwise be tempting.
    """
    readers = {"pollinators": lambda t: empty("pollinators", CANONICAL_DATABASE, "no rows")}
    report, store, _, _ = _pipeline(tmp_path, readers)

    assert report.state == "blocked"
    assert report.blocker_code == BlockerCode.INSUFFICIENT_EVIDENCE
    assert TAXON in store.all()[0]["blocker"]


def test_a_request_naming_no_taxon_blocks_without_searching(tmp_path):
    """Inventing a taxon to have something to search for would be the first
    fabrication in the chain."""
    request = _request(question="Could this be interesting to look at?")
    request["title"] = "General enquiry"
    report, store, _, _ = _pipeline(tmp_path, _covered_readers(), request=request)

    assert report.state == "blocked"
    assert report.blocker_code == BlockerCode.TAXON_UNRESOLVED
    assert store.all()[0]["evidence_summary"]["taxa"] == []


def test_a_reader_that_raises_is_unavailable_not_empty(tmp_path):
    def _broken(taxon):
        raise ConnectionError("canonical database unreachable")

    readers = {**_covered_readers(), "traits": _broken}
    _, store, _, _ = _pipeline(tmp_path, readers)

    traits = store.all()[0]["evidence_summary"]["per_taxon"][TAXON]["domains"]["traits"]
    assert traits["state"] == "UNAVAILABLE"
    assert "ConnectionError" in traits["detail"]


def test_the_summary_never_counts_an_unconsulted_domain_as_zero(tmp_path):
    _, store, _, _ = _pipeline(tmp_path, _covered_readers())

    summary = store.all()[0]["evidence_summary"]["per_taxon"][TAXON]["summary"]
    assert "mycorrhiza" in summary["domains_not_consulted"]
    assert "pollinators" not in summary["domains_not_consulted"]


# ------------------------------------------------------------- no mutation


def test_the_run_publishes_nothing_and_activates_nothing(tmp_path):
    _, _, station, _ = _pipeline(tmp_path, _covered_readers())

    project = station.manifest("calyx-research-executor", "RSR-GH-LAELIA01")["project"]
    assert project["scientific_publication_authorized"] is False
    assert project["knowledge_graph_mutation_authorized"] is False
    assert project["production_deployment_authorized"] is False

"""Synthetic values and in-memory boundaries; never a live scientific receipt."""

from dataclasses import replace
from decimal import Decimal

import pytest

from app.candidate_knowledge.repository import MemoryCandidateRepository
from app.candidate_knowledge.service import CandidateExtractionService
from app.evidence_aggregation.repository import MemoryAggregateRepository
from app.evidence_aggregation.service import EvidenceAggregationService
from app.literature_extraction.candidate_handoff import (
    LiteratureCandidateHandoffService,
)
from app.literature_extraction.firecrawl_acquisition import acquire_matrix_sources
from app.literature_extraction.firecrawl_provider import (
    AcquisitionBlocked,
    FirecrawlConfig,
    FirecrawlProvider,
    canonical_url,
)
from app.literature_extraction.repository import LiteratureResultRepository
from app.literature_extraction.source_binding import (
    CanonicalLiteratureSourceBinding,
    FileLiteratureSourceBindingRepository,
)
from runtime.knowledge_graph.canonical_taxonomy import (
    CanonicalRegistry,
    CanonicalTaxon,
    WorldPlantsRelease,
)

URL = "https://flora.example/monograph"
# Deliberately synthetic measurements, not published botanical assertions.
TEXT = "Synthetic Paphiopedilum fixture\n\nPaphiopedilum delenatii leaf length 10-12 cm.\nPaphiopedilum armeniacum petal width 3 cm.\n"
CONFIG = FirecrawlConfig(enabled=True, domains=("flora.example",))


def transport(endpoint, payload):
    if endpoint == "search":
        return 200, {
            "success": True,
            "data": {"web": [{"url": URL}, {"url": URL + "#part"}]},
        }
    return 200, {
        "success": True,
        "data": {"markdown": TEXT, "metadata": {"sourceURL": URL}},
    }


def taxonomy():
    taxa = {
        i: CanonicalTaxon(i, name, name, None, "species", "accepted", False)
        for i, name in enumerate(
            ("Paphiopedilum delenatii", "Paphiopedilum armeniacum"), 1
        )
    }
    release = WorldPlantsRelease(
        "fixture-release", "world_plants", "fixture", "a" * 64, 2, None
    )
    return CanonicalRegistry(
        release, taxa, {t.canonical_name: i for i, t in taxa.items()}
    )


@pytest.mark.asyncio
async def test_multi_taxon_source_to_candidates_aggregates_and_replay(tmp_path):
    provider = FirecrawlProvider(CONFIG, fixture_transport=transport)
    literature = LiteratureResultRepository(tmp_path / "literature")
    bindings = FileLiteratureSourceBindingRepository(tmp_path / "literature")
    candidates = MemoryCandidateRepository()
    aggregates = MemoryAggregateRepository()
    handoff = LiteratureCandidateHandoffService(
        CandidateExtractionService(candidates), candidates
    )

    def bind(source, paper):
        # Stand-in for existing canonical intake IDs, not generated production identities.
        binding = CanonicalLiteratureSourceBinding(
            paper.paper_id,
            "LITERATURE_DOCUMENT",
            1,
            2,
            3,
            {e.evidence_id: i for i, e in enumerate(paper.evidence, 1)},
        )
        binding = binding.with_verified_integrity(paper, source.markdown.encode())
        return bindings.create(binding)[0]

    checks = []

    async def run(provider):
        return await acquire_matrix_sources(
            provider=provider,
            genus="Paphiopedilum",
            task_id="fixture",
            taxonomy=taxonomy(),
            literature_repository=literature,
            register_and_bind=bind,
            handoff_service=handoff,
            aggregation_service=EvidenceAggregationService(aggregates),
            verify_lease=lambda: checks.append("verified"),
        )

    first = await run(provider)
    assert first["status"] == "review_pending"
    assert first["sources"][0]["mocked"] is True
    assert provider.documents == 1
    assert len(candidates.candidates) == 2
    assert len(aggregates.aggregates) == 2
    assert len(literature.list_paper_ids()) == 1
    assert all(
        c["review_state"] == "REQUIRED" and not c["published"]
        for c in candidates.candidates
    )
    assert {c["normalized_subject"] for c in candidates.candidates} == {
        "local:world_plants:1",
        "local:world_plants:2",
    }
    assert all(e["anchor"]["locator"]["source_hash"] for e in candidates.evidence_links)
    assert first["matrix_readiness"]["availability"] == "degraded"
    assert len(checks) >= 4
    second = await run(FirecrawlProvider(CONFIG, fixture_transport=transport))
    assert first["sources"][0]["candidate_ids"] == second["sources"][0]["candidate_ids"]
    assert len(candidates.candidates) == 2
    assert len(aggregates.aggregates) == 2


@pytest.mark.parametrize(
    "url",
    [
        "http://flora.example/a",
        "https://flora.example.evil/a",
        "https://user:pass@flora.example/a",
        "https://127.0.0.1/a",
        "https://flora.example:444/a",
    ],
)
def test_url_boundary(url):
    with pytest.raises(AcquisitionBlocked):
        canonical_url(url, CONFIG.domains)


def test_url_deduplication_and_kill_switch():
    env = {}
    provider = FirecrawlProvider(CONFIG, fixture_transport=transport, env=env)
    first = provider.scrape(URL + "?utm_source=x#section", task_id="fixture")
    assert provider.scrape(URL, task_id="fixture") == first
    assert provider.calls == 1
    env["FIRECRAWL_KILL_SWITCH"] = "true"
    with pytest.raises(AcquisitionBlocked, match="DISABLED"):
        provider.scrape(URL, task_id="fixture")


def test_bounded_retries_and_searches():
    calls = []

    def retry(endpoint, payload):
        calls.append(endpoint)
        return (429, {})

    provider = FirecrawlProvider(CONFIG, fixture_transport=retry, sleep=lambda _: None)
    with pytest.raises(AcquisitionBlocked, match="RETRIES_EXHAUSTED"):
        provider.search("Paphiopedilum", task_id="fixture")
    assert len(calls) == 3
    with pytest.raises(AcquisitionBlocked, match="SEARCH_LIMIT"):
        provider.search("Paphiopedilum", task_id="fixture")


def test_live_fail_closed_without_authority():
    provider = FirecrawlProvider(replace(CONFIG, dry_run=False), env={})
    with pytest.raises(AcquisitionBlocked, match="PROVIDER_NOT_AUTHORIZED"):
        provider.scrape(URL, task_id="fixture")
    assert provider.calls == 0
    provider.env.update(PROVIDER_AUTHORIZED="true", NO_API_MODE="false")
    with pytest.raises(AcquisitionBlocked, match="KEY_UNAVAILABLE"):
        provider.scrape(URL, task_id="fixture")
    provider.env["FIRECRAWL_API_KEY"] = "test-placeholder"
    with pytest.raises(AcquisitionBlocked, match="BUDGET_AUTHORITY"):
        provider.scrape(URL, task_id="fixture")


@pytest.mark.parametrize("cost", ["NaN", "Infinity", "-1"])
def test_invalid_budget(cost):
    with pytest.raises(AcquisitionBlocked):
        replace(CONFIG, max_call_cost=Decimal(cost))


def test_coverage_materializes_one_task_per_genus_and_parks_paid_work():
    from datetime import datetime, timezone

    from app.literature_extraction.coverage_audit import matrix_acquisition_gaps
    from app.provider_reservoir.routing import route_task
    from scripts.oc_work_discovery import discover_matrix_coverage
    from scripts.oc_work_materialize import plan

    gaps = matrix_acquisition_gaps(taxonomy(), set())
    assert len(gaps) == 1 and len(gaps[0]["missing_taxon_ids"]) == 2
    report = {
        "schema": "oc.matrix-acquisition-coverage.v1",
        "available": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gaps": gaps,
    }
    candidates = discover_matrix_coverage(report)
    materialized = plan(
        {
            "schema": "oc.work-discovery.v1",
            "candidates": [c.to_record() for c in candidates],
        },
        {},
        search=lambda _: [],
    )
    action = materialized["actions"][0]
    assert action["action"] == "create_issue"
    assert "oc-queued" in action["labels"]
    route = route_task({"number": 123, "body": action["body"]})
    assert not route.provider_free
    assert route.blocking_provider_capabilities == ["firecrawl-acquisition"]
    assert not matrix_acquisition_gaps(taxonomy(), {1, 2})
    report["generated_at"] = "2020-01-01T00:00:00+00:00"
    with pytest.raises(ValueError, match="STALE"):
        discover_matrix_coverage(report)


@pytest.mark.asyncio
async def test_unknown_taxon_and_locality_do_not_become_claims(tmp_path):
    from app.literature_extraction.context import PipelineContext
    from app.literature_extraction.extractors.morphology import (
        CanonicalMorphologyExtractor,
    )
    from app.literature_extraction.ingest import build_empty_paper, ingest_text

    source = tmp_path / "source.txt"
    source.write_text(
        TEXT + "Paphiopedilum unknown leaf length 9 cm.\n"
        "Paphiopedilum delenatii leaf length 12 cm. Latitude 30.912 longitude 60.78.\n"
    )
    paper = await CanonicalMorphologyExtractor(taxonomy()).run(
        PipelineContext(source_path=source, output_dir=tmp_path),
        build_empty_paper(ingest_text(source)),
    )
    assert len(paper.claims) == 2
    assert all(
        "unknown" not in c.statement and "Latitude" not in c.statement
        for c in paper.claims
    )


def test_lease_revocation_stops_transport():
    provider = FirecrawlProvider(CONFIG, fixture_transport=transport)

    def revoked():
        raise ValueError("LEASE_REVOKED")

    provider.lease_check = revoked
    with pytest.raises(ValueError, match="LEASE_REVOKED"):
        provider.scrape(URL, task_id="fixture")
    assert provider.calls == 0


def test_acquisition_is_not_misrouted_to_a_coding_provider():
    from scripts.oc_swarm_controller import unstaffed_numbers

    issue = {
        "number": 123,
        "state": "OPEN",
        "labels": ["oc-queued"],
        "body": "OC-SWARM-CAPABILITY: firecrawl-acquisition",
    }
    assert unstaffed_numbers({"issues": [issue]}) == []
    # Dedicated acquisition execution is covered by test_oc_swarm_acquisition_worker.
    from scripts.oc_swarm_controller import build_swarm_plan

    issue["title"] = "Acquire a morphology source"
    issue["labels"].append("oc-p2")
    plan = build_swarm_plan({"issues": [issue], "pull_requests": []}, worker_slots=1)
    assert plan["provider_matrix"] == {"include": []}
    assert plan["acquisition_matrix"]["include"][0]["issue_number"] == 123

    # NO-API mode still admits the deterministic held-corpus audit. The
    # acquisition boundary remains disabled; only external calls are gated.
    no_api_plan = build_swarm_plan(
        {"issues": [issue], "pull_requests": []},
        worker_slots=1,
        provider_free_only=True,
    )
    assert no_api_plan["provider_matrix"] == {"include": []}
    assert no_api_plan["acquisition_matrix"]["include"][0]["issue_number"] == 123


@pytest.mark.asyncio
async def test_canonical_worker_rechecks_real_claim_contract_before_acquisition(
    monkeypatch,
):
    import json
    from copy import deepcopy

    from app.literature_extraction import firecrawl_acquisition as acquisition
    from scripts.oc_swarm_claim import claim_workers

    repository = "jsp1440/orchid-calyx-backend"
    issue = {
        "number": 123,
        "title": "Paphiopedilum acquisition fixture",
        "state": "OPEN",
        "body": "OC-SWARM-CAPABILITY: firecrawl-acquisition",
        "labels": ["oc-queued"],
    }
    comments = []

    def github(args, payload=None):
        if args[:2] == ["issue", "view"]:
            return deepcopy(issue)
        if args[:2] == ["issue", "edit"]:
            issue["labels"] = ["oc-running"]
            return None
        receipt = {
            "id": 100,
            "body": payload["body"],
            "user": {"login": "github-actions[bot]"},
            "issue_url": f"https://api.github.com/repos/{repository}/issues/123",
        }
        comments.append(receipt)
        return receipt

    worker = {
        "issue_number": 123,
        "dependencies": [],
        "reads": ["taxonomy"],
        "writes": ["literature"],
        "provider_free": False,
        "lane_executable": False,
        "acquisition": True,
    }
    claimed = claim_workers(
        {"workers": [worker]},
        {"issues": [deepcopy(issue)]},
        repository=repository,
        run_id=77,
        call=github,
    )
    assert claimed["launch_count"] == 1
    assert (
        json.loads(comments[0]["body"].split("`")[1])["lease_id"]
        == f"{repository}:77:1:123"
    )
    calls = []

    async def boundary(**kwargs):
        kwargs["verify_lease"]()
        calls.append(kwargs["task_id"])
        return {"status": "boundary_verified"}

    monkeypatch.setattr(acquisition, "acquire_matrix_sources", boundary)
    kwargs = {
        "issue_number": 123,
        "repository": repository,
        "run_id": 77,
        "run_attempt": 1,
        "comment_id": 100,
        "read_issue": lambda _: deepcopy(issue),
        "read_lease": lambda _: comments[0],
    }
    await acquisition.acquire_for_swarm_issue(**kwargs)
    assert calls == [f"{repository}#123"]
    issue["labels"].append("oc-owner-gate")
    with pytest.raises(ValueError, match="exclusive running"):
        await acquisition.acquire_for_swarm_issue(**kwargs)
    assert len(calls) == 1


def test_targeted_gap_uses_one_bounded_multi_taxon_source_query():
    calls = []

    def record(endpoint, payload):
        calls.append((endpoint, payload))
        return transport(endpoint, payload)

    provider = FirecrawlProvider(CONFIG, fixture_transport=record)
    provider.search(
        "Paphiopedilum",
        task_id="gap",
        target_names=(
            "Paphiopedilum delenatii",
            "Paphiopedilum armeniacum",
        ),
    )
    assert len(calls) == 1
    assert (
        '"Paphiopedilum delenatii" OR "Paphiopedilum armeniacum"'
        in calls[0][1]["query"]
    )
    assert "monograph OR revision OR flora OR key" in calls[0][1]["query"]
    with pytest.raises(AcquisitionBlocked, match="INVALID_TARGETED_GAP"):
        FirecrawlProvider(CONFIG, fixture_transport=record).search(
            "Paphiopedilum",
            task_id="gap",
            target_names=("Othergenus species",),
        )
    assert len(calls) == 1


def test_differing_measurements_in_one_document_are_not_duplicates():
    from app.evidence_aggregation.models import CandidateInput

    repository = MemoryAggregateRepository()
    service = EvidenceAggregationService(repository)
    candidates = [
        CandidateInput(
            candidate_id=index,
            candidate_version=1,
            candidate_type="TRAIT_ASSERTION",
            normalized_subject="local:orchid_taxonomy:1",
            predicate="leaf_length",
            object_value=statement,
            source_revision_id=1,
            source_anchor_ids=(index,),
            document_hash="a" * 64,
        )
        for index, statement in enumerate(
            (
                "Paphiopedilum delenatii leaf length 10-12 cm.",
                "Paphiopedilum delenatii leaf length 15 cm.",
            ),
            1,
        )
    ]
    plan = service.preview(candidates)
    assert service.execute(plan["aggregate_run_id"])["state"] == "COMPLETED"
    assert repository.relationships[0]["relationship_type"] == "UNRESOLVED_RELATIONSHIP"
    assert repository.conflicts
    assert repository.aggregates[0]["measurement_summary"]["unweighted_mean"] is None

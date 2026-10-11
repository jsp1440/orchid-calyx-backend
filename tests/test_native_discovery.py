"""Deterministic native-discovery contracts: no network, no database."""

from __future__ import annotations

from datetime import UTC, date, datetime
from urllib.parse import parse_qs, urlparse

import pytest

from app.intake.discovery.digest import build_digest, render_markdown
from app.intake.discovery.profiles import (
    DEFAULT_PROFILES,
    DiscoveryProfile,
    load_profiles,
)
from app.intake.discovery.providers import (
    CrossrefProvider,
    EuropePmcProvider,
    OpenAlexProvider,
)
from app.intake.discovery.records import (
    assess_verification,
    classify_domain,
    is_orchid_relevant,
    ledger_fingerprint,
    mentioned_names,
    merge_works,
    novelty,
    parse_partial_date,
    to_intelligence_item,
)
from tests.native_discovery_fixtures import CROSSREF_PAGE, EUROPEPMC_PAGE, OPENALEX_PAGE

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


def crossref_works():
    return {work.doi: work for work in CrossrefProvider().parse(CROSSREF_PAGE)}


def test_crossref_parse_normalizes_identity_dates_and_markup():
    works = crossref_works()
    lepanthes = works["10.5555/oc-fixture-lepanthes"]
    assert lepanthes.title.startswith("Lepanthes fixtura (Orchidaceae")
    assert lepanthes.published_on == date(2026, 10, 2)
    assert lepanthes.published_precision == "DAY"
    assert lepanthes.authors == ("Ana Fixture", "Luis Example")
    assert lepanthes.affiliations == ("Herbario Fixture",)
    assert "<" not in lepanthes.abstract
    assert works["10.5555/oc-fixture-old"].published_precision == "YEAR"


def test_openalex_and_europepmc_parse():
    [openalex] = OpenAlexProvider().parse(OPENALEX_PAGE)
    assert openalex.doi == "10.5555/oc-fixture-pollination"
    assert openalex.abstract == "Preserved orchid specimens pollinators"
    assert openalex.affiliations == ("Fixture University",)
    [preprint] = EuropePmcProvider().parse(EUROPEPMC_PAGE)
    assert preprint.work_type == "preprint"
    assert preprint.provider_record_id == "PPR:PPR000001"
    assert preprint.published_on == date(2026, 10, 5)


def test_requests_are_bounded_incremental_and_contact_is_configuration(monkeypatch):
    monkeypatch.delenv("OC_DISCOVERY_CONTACT_EMAIL", raising=False)
    request = CrossrefProvider().build_request(
        "orchid", date(2026, 10, 1), date(2026, 10, 11), 50
    )
    params = parse_qs(urlparse(request.url).query)
    assert params["filter"] == [
        "from-index-date:2026-10-01,until-index-date:2026-10-11"
    ]
    assert params["rows"] == ["50"]
    assert "mailto" not in params
    monkeypatch.setenv("OC_DISCOVERY_CONTACT_EMAIL", "ops@example.invalid")
    params = parse_qs(
        urlparse(
            CrossrefProvider()
            .build_request("orchid", date(2026, 10, 1), date(2026, 10, 2), 5)
            .url
        ).query
    )
    assert params["mailto"] == ["ops@example.invalid"]
    epmc = parse_qs(
        urlparse(
            EuropePmcProvider()
            .build_request("orchid*", date(2026, 10, 1), date(2026, 10, 2), 5)
            .url
        ).query
    )
    assert "FIRST_IDATE:[2026-10-01 TO 2026-10-02]" in epmc["query"][0]


def test_relevance_gate_and_domain_classification_are_content_based():
    works = crossref_works()
    assert not is_orchid_relevant(works["10.5555/oc-fixture-wheat"])
    assert classify_domain(works["10.5555/oc-fixture-lepanthes"]) == "taxonomy"
    assert classify_domain(works["10.5555/oc-fixture-pollination"]) == "conservation"


def test_name_mentions_are_unreconciled_signals():
    names = mentioned_names(crossref_works()["10.5555/oc-fixture-lepanthes"])
    assert {
        "name": "Lepanthes fixtura",
        "signal": "PROPOSED_NOVELTY",
        "reconciliation": "PENDING",
    } in names


def test_novelty_distinguishes_source_date_from_discovery_date():
    works = crossref_works()
    new = works["10.5555/oc-fixture-lepanthes"]
    old = works["10.5555/oc-fixture-old"]
    assert (
        novelty(
            new, discovered_at=NOW, new_window_days=60, previous_metadata_sha256=None
        )
        == "NEW_PUBLICATION"
    )
    assert (
        novelty(
            old, discovered_at=NOW, new_window_days=60, previous_metadata_sha256=None
        )
        == "HISTORICAL_RECOVERY"
    )
    sha = new.metadata_sha256()
    assert (
        novelty(
            new, discovered_at=NOW, new_window_days=60, previous_metadata_sha256=sha
        )
        == "ALREADY_TRACKED"
    )
    assert (
        novelty(
            new,
            discovered_at=NOW,
            new_window_days=60,
            previous_metadata_sha256="0" * 64,
        )
        == "UPDATED"
    )


def test_verification_states_never_verify_claims():
    crossref = crossref_works()["10.5555/oc-fixture-pollination"]
    [openalex] = OpenAlexProvider().parse(OPENALEX_PAGE)
    state, basis = assess_verification([crossref])
    assert state == "SOURCE_LOCATED" and basis["claim_verified"] is False
    assert assess_verification([crossref, openalex])[0] == "PARTIALLY_VERIFIED"
    confirmed = {
        "outcome": "SOURCE_CONFIRMED",
        "source_title": crossref.title,
        "resolved_url": "https://x",
    }
    state, basis = assess_verification([crossref, openalex], primary_source=confirmed)
    assert state == "VERIFIED" and basis["claim_verified"] is False
    assert (
        assess_verification([crossref], primary_source={"outcome": "UNREACHABLE"})[0]
        == "UNRESOLVED"
    )
    wrong_page = {
        "outcome": "SOURCE_CONFIRMED",
        "source_title": "Quarterly sales of garden furniture",
    }
    assert (
        assess_verification([crossref], primary_source=wrong_page)[0] == "CONTRADICTED"
    )


def test_conflicting_providers_are_contradicted_not_merged_silently():
    crossref = crossref_works()["10.5555/oc-fixture-pollination"]
    from dataclasses import replace

    conflicting = replace(
        crossref,
        provider="openalex",
        title="Unrelated soil chemistry survey",
        published_on=date(2001, 1, 1),
    )
    state, basis = assess_verification([crossref, conflicting])
    assert state == "CONTRADICTED"
    assert {c["field"] for c in basis["contradictions"]} == {
        "title",
        "publication_year",
    }


def test_intelligence_item_contract_and_cross_provider_identity():
    crossref = crossref_works()["10.5555/oc-fixture-pollination"]
    [openalex] = OpenAlexProvider().parse(OPENALEX_PAGE)
    merged = merge_works([crossref, openalex])
    assert ledger_fingerprint(crossref) == ledger_fingerprint(merged)
    state, basis = assess_verification([crossref, openalex])
    item = to_intelligence_item(
        merged,
        provider_views=[crossref, openalex],
        novelty_state="NEW_PUBLICATION",
        verification_state=state,
        verification_basis=basis,
        discovered_at=NOW,
        profile_key="orchid-literature",
    )
    assert item["dois"] == ["10.5555/oc-fixture-pollination"]
    assert "https://doi.org/10.5555/oc-fixture-pollination" in item["source_urls"]
    assert {"orep", "pollinator_network"} <= set(item["canonical_destinations"])
    assert "EVALUATE_RELATIONSHIP_EVIDENCE" in item["follow_up_tasks"]
    native = item["native_discovery"]
    assert native["source_published_on"] == "2026-09-20"
    assert native["discovered_at"] == NOW.isoformat()
    assert native["evidence_layers"]["scientific_interpretation"] is None
    assert native["claim_verified"] is False
    assert (
        item["canonical_graph_mutated"] is False and item["external_contacted"] is False
    )
    pinned = to_intelligence_item(
        merged,
        provider_views=[crossref],
        novelty_state="UPDATED",
        verification_state=state,
        verification_basis=basis,
        discovered_at=NOW,
        profile_key="orchid-literature",
        existing_identity={"knowledge_fingerprint": "f" * 64, "domain": "research"},
    )
    assert (
        pinned["knowledge_fingerprint"] == "f" * 64 and pinned["domain"] == "research"
    )


def test_partial_dates_and_profiles():
    assert parse_partial_date("2026-02") == (date(2026, 2, 1), "MONTH")
    assert parse_partial_date(None) == (None, "UNKNOWN")
    assert load_profiles() == DEFAULT_PROFILES
    with pytest.raises(ValueError):
        DiscoveryProfile(
            key="bad-provider",
            description="x",
            domain_hint="research",
            providers=("twin",),
            queries={"default": "x"},
        )


def test_digest_separates_completed_from_proposed_and_reports_gaps():
    now = NOW
    inputs = {
        "items": [
            {
                "id": 1,
                "domain": "taxonomy",
                "title": "Lepanthes fixtura",
                "priority": "HIGH",
                "lifecycle": "ROUTED",
                "canonical_destinations": ["orep", "taxonomy_reconciliation"],
                "follow_up_tasks": ["VERIFY_PRIMARY_SOURCE", "RECONCILE_TAXONOMY"],
                "source_urls": [],
                "dois": ["10.5555/oc-fixture-lepanthes"],
                "verification_state": "VERIFIED",
                "providers": ["crossref"],
                "novelty_states": ["NEW_PUBLICATION"],
                "source_published_on": date(2026, 10, 2),
                "first_discovered_at": now,
                "metadata": {
                    "name_mentions": [
                        {"name": "Lepanthes fixtura", "signal": "PROPOSED_NOVELTY"}
                    ]
                },
            },
            {
                "id": 2,
                "domain": "research",
                "title": "Conflicting record",
                "priority": "HIGH",
                "lifecycle": "DISCOVERED",
                "canonical_destinations": ["orep"],
                "follow_up_tasks": [],
                "source_urls": ["https://fixture.example/x"],
                "dois": [],
                "verification_state": "CONTRADICTED",
                "providers": ["crossref", "openalex"],
                "novelty_states": ["NEW_PUBLICATION"],
                "metadata": {},
            },
        ],
        "routes": [
            {"intelligence_item_id": 1, "destination": "orep", "route_status": "READY"}
        ],
        "actions": [],
        "runs": [
            {
                "run_key": "scheduled:2026-10-11",
                "attempt": 1,
                "status": "NO_WORK",
                "zero_work_reason": "PROVIDERS_RETURNED_NO_RECORDS_IN_WINDOW",
                "failure_reasons": [],
                "counts": {},
            }
        ],
        "failing_cursors": [],
    }
    digest = build_digest(inputs, period="daily", since=now, until=now)
    entry = digest["important_discoveries"]["taxonomy"]["shown"][0]
    assert entry["primary_source"] == "https://doi.org/10.5555/oc-fixture-lepanthes"
    assert entry["integration"]["ready_for_governed_intake"] == ["orep"]
    assert entry["integration"]["proposed"] == ["taxonomy_reconciliation"]
    assert entry["integration"]["completed"] == []
    assert digest["decisions_required"][0]["intelligence_item_id"] == 2
    assert digest["deadlines"]["items"] == [] and "funding" in digest["coverage_gaps"]
    text = render_markdown(digest)
    assert "PROVIDERS_RETURNED_NO_RECORDS_IN_WINDOW" in text
    assert "https://doi.org/10.5555/oc-fixture-lepanthes" in text


def test_scheduled_discover_job_dispatches_through_existing_autonomy(monkeypatch):
    from app.intake import intelligence_autonomy
    from app.intake.discovery import service

    calls = []

    def fake_cycle(**kwargs):
        calls.append(kwargs)
        return {"status": "NO_WORK", "usage": {"provider_requests": 0}}

    monkeypatch.setattr(service, "run_discovery_cycle", fake_cycle)
    result = intelligence_autonomy.execute_internal_intelligence_job(
        "calyx_intelligence_discover_20261011"
    )
    assert calls == [{"mode": "SCHEDULED", "run_key": "scheduled:2026-10-11"}]
    assert result["stage"] == "discover" and result["external_contacted"] is False
    assert (
        intelligence_autonomy.execute_internal_intelligence_job(
            "calyx_intelligence_unknown_1"
        )
        is None
    )

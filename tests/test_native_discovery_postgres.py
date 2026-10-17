"""Native discovery lifecycle against the isolated intelligence-ledger CI database."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import ClassVar

import psycopg
import pytest

from app.intake.discovery import repository as repo
from app.intake.discovery.digest import build_digest
from app.intake.discovery.profiles import DEFAULT_PROFILES, DiscoveryBudget
from app.intake.discovery.service import run_discovery_cycle
from app.intake.intelligence_repository import get_intelligence_item
from tests.native_discovery_fixtures import CROSSREF_PAGE, FakeHttp

DATABASE_URL = os.getenv("NATIVE_DISCOVERY_DATABASE_URL")
# Dedicated database: these tests drop and rebuild the oc_intake schema.
CI_DATABASE_URL = (
    "postgresql://postgres:postgres@localhost:5432/orchid_native_discovery_test"
)
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="NATIVE_DISCOVERY_DATABASE_URL not set"
)

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
NO_WAIT = DiscoveryBudget(min_interval_seconds=0)


@dataclass
class Snapshot:
    source_url: str
    resolved_url: str | None
    source_kind: str
    outcome: str
    http_status: int | None
    content_type: str | None
    source_title: str | None
    source_doi: str | None
    published_at: str | None
    authority_host: str | None
    authority_tier: str
    evidence_sha256: str | None
    metadata: dict


class FakeFetch:
    titles: ClassVar[dict[str, str]] = {
        "10.5555/oc-fixture-lepanthes": "Lepanthes fixtura (Orchidaceae: Pleurothallidinae), a new species from Ecuador",
        "10.5555/oc-fixture-pollination": "Herbarium flowers reveal long-term decline in orchid pollination",
    }

    def __init__(self):
        self.urls: list[str] = []

    def __call__(self, url):
        self.urls.append(url)
        doi = url.removeprefix("https://doi.org/")
        title = self.titles.get(doi)
        return Snapshot(
            source_url=url,
            resolved_url=f"https://publisher.example/{doi}",
            source_kind="DOI",
            outcome="SOURCE_CONFIRMED" if title else "UNREACHABLE",
            http_status=200 if title else 404,
            content_type="text/html",
            source_title=title,
            source_doi=doi,
            published_at=None,
            authority_host="publisher.example",
            authority_tier="PRIMARY",
            evidence_sha256=("a" * 64) if title else None,
            metadata={"claim_verified": False},
        )


@pytest.fixture(autouse=True)
def ledger(monkeypatch):
    if DATABASE_URL != CI_DATABASE_URL:
        pytest.fail(
            "Native discovery tests require the fixed isolated ledger CI database"
        )
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute("DROP SCHEMA IF EXISTS oc_intake CASCADE")
        connection.execute("DROP SCHEMA IF EXISTS oc_admin CASCADE")
        for name in (
            "070_knowledge_intake.sql",
            "108_intelligence_assimilation_ledger.sql",
            "109_intelligence_verification_routing.sql",
            "142_native_intelligence_discovery.sql",
        ):
            connection.execute((Path("migrations") / name).read_text(encoding="utf-8"))


def run(**kwargs):
    defaults = {
        "profiles": DEFAULT_PROFILES,
        "budget": NO_WAIT,
        "now": NOW,
        "sleep": lambda _: None,
    }
    defaults.update(kwargs)
    defaults.setdefault("http_get", FakeHttp())
    defaults.setdefault("fetch_source", FakeFetch())
    return run_discovery_cycle(**defaults)


def scalar(sql, *params):
    with psycopg.connect(DATABASE_URL) as connection:
        return connection.execute(sql, params).fetchone()[0]


def test_vertical_slice_records_dedupes_verifies_and_advances_cursors():
    http, fetch = FakeHttp(), FakeFetch()
    result = run(http_get=http, fetch_source=fetch)
    assert result["status"] == "COMPLETED", result
    # wheat filtered; Lepanthes, pollination (crossref+openalex), old revision, mycorrhiza preprint
    assert result["counts"]["new_items"] == 4
    assert result["counts"]["filtered_irrelevant"] == 2  # wheat seen by two profiles
    assert result["usage"]["paid_provider_calls"] == 0
    assert result["usage"]["model_inference_calls"] == 0
    assert len(http.urls) == result["usage"]["provider_requests"] == 4

    assert scalar("SELECT count(*) FROM oc_intake.intelligence_items") == 4
    pollination_id = scalar(
        "SELECT intelligence_item_id FROM oc_intake.discovery_records WHERE doi='10.5555/oc-fixture-pollination' LIMIT 1"
    )
    assert (
        scalar(
            "SELECT count(*) FROM oc_intake.discovery_records WHERE intelligence_item_id=%s",
            pollination_id,
        )
        == 2
    )
    assert (
        scalar(
            "SELECT verification_state FROM oc_intake.discovery_verification_states WHERE intelligence_item_id=%s",
            pollination_id,
        )
        == "VERIFIED"
    )
    assert (
        scalar(
            "SELECT bool_or(claim_verified) FROM oc_intake.discovery_verification_states"
        )
        is False
    )
    # Primary-source evidence went through the existing verification table.
    assert (
        scalar(
            "SELECT outcome FROM oc_intake.intelligence_verifications WHERE intelligence_item_id=%s",
            pollination_id,
        )
        == "SOURCE_CONFIRMED"
    )
    assert (
        scalar(
            "SELECT verification_state FROM oc_intake.discovery_verification_states v "
            "JOIN oc_intake.discovery_records r USING (intelligence_item_id) WHERE r.doi='10.5555/oc-fixture-mycorrhiza'"
        )
        == "UNRESOLVED"
    )
    assert (
        scalar(
            "SELECT novelty FROM oc_intake.discovery_records WHERE doi='10.5555/oc-fixture-old'"
        )
        == "HISTORICAL_RECOVERY"
    )
    item = get_intelligence_item(pollination_id)
    snapshot = item["observations"][0]["raw_snapshot"]["native_discovery"]
    assert snapshot["source_published_on"] == "2026-09-20"
    assert (
        item["canonical_promotion_prohibited"] and item["external_contact_prohibited"]
    )
    assert repo.get_cursor("orchid-literature", "crossref")["watermark"] == date(
        2026, 10, 11
    )


def test_rerun_is_idempotent_and_zero_work_reports_why():
    run()
    assert run()["status"] == "SKIPPED"  # same scheduled run key
    second = run(mode="MANUAL", now=NOW + timedelta(days=1))
    assert second["status"] == "NO_WORK"
    assert second["zero_work_reason"].startswith("ALL_RELEVANT_RECORDS_ALREADY_TRACKED")
    assert scalar("SELECT count(*) FROM oc_intake.intelligence_items") == 4
    assert scalar("SELECT count(*) FROM oc_intake.intelligence_observations") == 4
    no_pages = {"api.crossref.org": {}, "api.openalex.org": {}, "www.ebi.ac.uk": {}}
    empty = run(
        mode="MANUAL", now=NOW + timedelta(days=2), http_get=FakeHttp(pages=no_pages)
    )
    assert empty["status"] == "NO_WORK"
    assert empty["zero_work_reason"] == "PROVIDERS_RETURNED_NO_RECORDS_IN_WINDOW"
    down = run(
        mode="MANUAL",
        now=NOW + timedelta(days=3),
        http_get=FakeHttp(
            failures={
                "api.crossref.org": 503,
                "api.openalex.org": 503,
                "www.ebi.ac.uk": 503,
            }
        ),
    )
    assert down["status"] == "FAILED"
    assert (
        down["zero_work_reason"]
        == "NO_WORK_ALL_ATTEMPTS_FAILED:PROVIDER_REQUEST_FAILED"
    )


def test_metadata_update_is_recognized_without_duplicate_item():
    run()
    import copy

    page = copy.deepcopy(CROSSREF_PAGE)
    page["message"]["items"][0]["abstract"] = (
        "Lepanthes fixtura sp. nov. is described; a corrigendum adds a key."
    )
    result = run(
        mode="MANUAL",
        now=NOW + timedelta(days=1),
        http_get=FakeHttp(pages={"api.crossref.org": page}),
    )
    assert result["counts"]["updated_items"] == 1 and result["counts"]["new_items"] == 0
    assert (
        scalar(
            "SELECT update_count FROM oc_intake.discovery_records WHERE doi='10.5555/oc-fixture-lepanthes'"
        )
        == 1
    )
    assert scalar("SELECT count(*) FROM oc_intake.intelligence_items") == 4


def test_provider_failure_is_partial_and_holds_only_that_cursor():
    result = run(http_get=FakeHttp(failures={"api.openalex.org": 429}))
    assert result["status"] == "PARTIAL"
    assert any(f["detail"] == "RATE_LIMITED" for f in result["failure_reasons"])
    cursor = repo.get_cursor("orchid-literature", "openalex")
    assert cursor["watermark"] is None and cursor["consecutive_failures"] == 1
    assert repo.get_cursor("orchid-literature", "crossref")["watermark"] == date(
        2026, 10, 11
    )


def test_budget_exhaustion_stops_partial_and_never_claims_completion():
    result = run(budget=DiscoveryBudget(max_requests=1, min_interval_seconds=0))
    assert result["status"] == "PARTIAL"
    assert result["usage"]["provider_requests"] == 1
    assert result["usage"]["budget_exhausted"]
    assert repo.get_cursor("orchid-literature", "openalex") is None


def test_stale_running_attempt_is_interrupted_and_resumed():
    claim = repo.start_run(
        run_key="scheduled:2026-10-11", mode="SCHEDULED", profiles=[], budget={}
    )
    assert run()["status"] == "SKIPPED"  # live lease respected
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            "UPDATE oc_intake.discovery_runs SET started_at = NOW() - interval '3 hours' WHERE id=%s",
            (claim["run"]["id"],),
        )
    result = run()
    assert result["status"] == "COMPLETED" and result["attempt"] == 2
    assert (
        scalar(
            "SELECT status FROM oc_intake.discovery_runs WHERE id=%s",
            claim["run"]["id"],
        )
        == "INTERRUPTED"
    )


def test_historical_recovery_is_bounded_and_does_not_move_live_cursor():
    with pytest.raises(ValueError):
        run(mode="HISTORICAL", historical_window=(date(2020, 1, 1), date(2026, 1, 1)))
    result = run(
        mode="HISTORICAL", historical_window=(date(2026, 1, 1), date(2026, 3, 1))
    )
    assert result["status"] == "COMPLETED"
    assert repo.get_cursor("orchid-literature", "crossref") is None


def test_digest_reads_ledger_state():
    run(verify_sources=False)
    inputs = repo.digest_inputs(
        NOW - timedelta(days=1), datetime.now(UTC) + timedelta(minutes=1)
    )
    digest = build_digest(inputs, period="daily", since=NOW, until=NOW)
    assert digest["headline"]["items_touched"] == 4
    assert digest["headline"]["historical_recoveries"] == 1
    assert digest["autonomous_work"]["runs"][0]["status"] == "COMPLETED"
    assert digest["taxonomy_reconciliation_candidates"]


def test_autonomy_enqueues_one_daily_discovery_job_only_when_enabled(monkeypatch):
    from app.intake.intelligence_autonomy import enqueue_due_intelligence_jobs

    monkeypatch.delenv("OC_INTELLIGENCE_DISCOVERY_ENABLED", raising=False)
    disabled = enqueue_due_intelligence_jobs(now=NOW)
    assert (
        disabled["discovery"]["job"] is None
        and "not enabled" in disabled["discovery"]["reason"]
    )
    monkeypatch.setenv("OC_INTELLIGENCE_DISCOVERY_ENABLED", "1")
    first = enqueue_due_intelligence_jobs(now=NOW)
    assert "calyx_intelligence_discover_20261011" in first["jobs_created"]
    again = enqueue_due_intelligence_jobs(now=NOW)
    assert "calyx_intelligence_discover_20261011" not in again["jobs_created"]

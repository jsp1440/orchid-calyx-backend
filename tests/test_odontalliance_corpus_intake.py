from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.literature_extraction.odontalliance import (
    CULTURE_URL,
    IntakeLimits,
    OdontAllianceIntakeError,
    canonical_url,
    discover_resources,
    ingest_culture_page,
    project_culture_page,
)

FIXTURE = (
    Path(__file__).parent / "fixtures" / "literature" / "odontalliance_culture.html"
)


def test_discovery_is_same_origin_allowlisted_deduplicated_and_review_only() -> None:
    resources = discover_resources([(CULTURE_URL, FIXTURE.read_bytes())])

    assert [resource.url for resource in resources] == [
        "https://www.odontalliance.org/ewExternalFiles/Master%20index-20.pdf",
        "https://www.odontalliance.org/recent-journals.html",
    ]
    assert all(
        resource.rights_status == "unknown_requires_review" for resource in resources
    )
    assert all(
        resource.ingest_state == "metadata_only_pending_rights_review"
        for resource in resources
    )
    assert all(
        resource.historical_taxonomy_requires_resolution for resource in resources
    )


@pytest.mark.parametrize(
    "url",
    (
        "http://www.odontalliance.org/culture.html",
        "https://odontalliance.org/culture.html",
        "https://www.odontalliance.org/../secret.txt",
        "https://www.odontalliance.org/constitution.html",
        "https://example.org/culture.html",
    ),
)
def test_url_boundary_fails_closed(url: str) -> None:
    with pytest.raises(OdontAllianceIntakeError):
        canonical_url(url)


def test_discovery_limits_fail_closed() -> None:
    with pytest.raises(OdontAllianceIntakeError, match="RESOURCE_COUNT_LIMIT_EXCEEDED"):
        discover_resources(
            [(CULTURE_URL, FIXTURE.read_bytes())],
            limits=IntakeLimits(max_resources=1),
        )


def test_culture_projection_is_deterministic_and_marks_governance() -> None:
    first = project_culture_page(FIXTURE.read_bytes())
    second = project_culture_page(FIXTURE.read_bytes())

    assert first == second
    assert "Rights status: unknown; review required" in first
    assert "Historical taxonomy: source-reported names require resolution" in first
    assert "CULTIVATION GUIDANCE" in first
    assert "Odontoglossum: Temperature" in first


@pytest.mark.asyncio
async def test_culture_page_enters_review_only_literature_pipeline(
    tmp_path: Path,
) -> None:
    acquired, paper = await ingest_culture_page(
        FIXTURE.read_bytes(),
        tmp_path,
        retrieved_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
    )

    assert acquired.text_path.is_file()
    assert acquired.acquisition_path.is_file()
    assert paper.source.origin_uri == CULTURE_URL
    assert paper.source.origin_content_hash == acquired.source_html_hash
    assert paper.source.rights_status == "unknown_requires_review"
    assert paper.source.redistribution_allowed is False
    assert paper.source.historical_taxonomy_requires_resolution is True
    assert paper.claims
    assert all(claim.claim_type == "recommendation" for claim in paper.claims)
    assert all(
        record.domain == "cultivation" for record in paper.normalized_evidence_records
    )
    assert all(
        record.unresolved_entities == ["odontoglossum"]
        for record in paper.normalized_evidence_records
    )
    assert all(item.status == "blocked" for item in paper.publication_decisions)
    assert all(item.status == "pending" for item in paper.review_items)
    acquisition = json.loads(acquired.acquisition_path.read_text(encoding="utf-8"))
    assert acquisition["knowledge_graph_publication_allowed"] is False
    assert acquisition["source_html_sha256"] == acquired.source_html_hash

    raw = acquired.text_path.read_text(encoding="utf-8")
    for evidence in paper.evidence:
        assert (
            raw[evidence.span.char_start : evidence.span.char_end] == evidence.excerpt
        )
        assert evidence.supports_ids

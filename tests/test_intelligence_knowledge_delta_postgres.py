from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest

from app.intake.extractor import content_hash, extract
from app.intake.intelligence import canonical_email_text, parse_external_intelligence
from app.intake.intelligence_repository import record_intelligence_items
from app.intake.knowledge_delta import assess_item
from app.intake.knowledge_delta_repository import record_comparison
from app.intake.repository import create_source

DATABASE_URL = os.getenv("INTELLIGENCE_DELTA_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="INTELLIGENCE_DELTA_DATABASE_URL not set")


def _apply_migrations() -> None:
    with psycopg.connect(DATABASE_URL) as connection:
        for path in (
            "migrations/070_knowledge_intake.sql",
            "migrations/108_intelligence_assimilation_ledger.sql",
            "migrations/081_brain_source_registry.sql",
        ):
            connection.execute(Path(path).read_text(encoding="utf-8"))


def _record_briefing(body: str, message_id: str) -> int:
    os.environ["DATABASE_URL"] = str(DATABASE_URL)
    canonical = canonical_email_text(
        sender="twin@twin-mail.com",
        subject=f"Daily briefing {message_id}",
        body=body,
        message_id=message_id,
    )
    items = parse_external_intelligence(body, sender="twin@twin-mail.com", message_id=message_id)
    source = create_source(
        source_type="email",
        title=f"Daily briefing {message_id}",
        content=canonical,
        content_hash=content_hash(canonical),
        source_url=None,
        imported_by="delta-postgres-test",
        extraction=extract(canonical),
    )
    recorded = record_intelligence_items(
        source_id=source["id"], items=items, sender="twin@twin-mail.com", message_id=message_id
    )
    assert len(recorded) == 1
    return recorded[0]["id"]


def test_registered_earth_engine_source_is_already_known_but_still_requires_verification():
    _apply_migrations()
    os.environ["DATABASE_URL"] = str(DATABASE_URL)
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            """
            INSERT INTO oc_sources.sources
                (source_name, source_type, authentication_method, status, configuration)
            VALUES ('Google Earth Engine', 'geospatial_platform', 'oauth', 'ACTIVE', '{}'::jsonb)
            ON CONFLICT (source_name, source_type) DO NOTHING
            """
        )

    item_id = _record_briefing(
        """
Technology and Infrastructure Opportunities
Google Earth Engine for orchid habitat surveillance High Priority
Earth Engine supports satellite and remote sensing analysis of habitat and fire.
View Source →
""",
        "known-earth-engine",
    )
    assessment = assess_item(item_id)
    assert assessment.knowledge_delta == "ALREADY_KNOWN"
    assert assessment.candidate_delta is None
    assert assessment.verification_required is True
    assert any(match["store"] == "source_registry" for match in assessment.matches)

    persisted = record_comparison(assessment)
    assert persisted["lifecycle"] == "COMPARED"
    assert persisted["knowledge_delta"] == "ALREADY_KNOWN"
    assert persisted["verification_required"] is True
    assert persisted["canonical_graph_mutated"] is False
    assert persisted["external_contacted"] is False


def test_unregistered_technology_is_candidate_new_source_not_confirmed_novelty():
    _apply_migrations()
    os.environ["DATABASE_URL"] = str(DATABASE_URL)
    item_id = _record_briefing(
        """
Technology and Infrastructure Opportunities
Novel Orchid Remote Sensing Platform High Priority
A platform exposes a new habitat dataset and API for orchid monitoring.
View Source →
""",
        "unknown-tech",
    )
    assessment = assess_item(item_id)
    assert assessment.knowledge_delta == "REQUIRES_REVIEW"
    assert assessment.candidate_delta == "NEW_SOURCE"
    assert assessment.verification_required is True

    persisted = record_comparison(assessment)
    assert persisted["knowledge_delta"] == "REQUIRES_REVIEW"
    assert persisted["candidate_delta"] == "NEW_SOURCE"
    assert persisted["verification_required"] is True


def test_existing_doi_is_strong_match_even_when_briefing_wording_differs():
    _apply_migrations()
    os.environ["DATABASE_URL"] = str(DATABASE_URL)
    doi = "10.1234/orchid.pollinator.2026"
    prior_text = f"Primary paper record DOI {doi}"
    create_source(
        source_type="text",
        title="Existing pollinator paper",
        content=prior_text,
        content_hash=content_hash(prior_text),
        source_url=f"https://doi.org/{doi}",
        imported_by="delta-postgres-test",
        extraction=extract(prior_text),
    )
    item_id = _record_briefing(
        f"""
Research and Publications
Different headline for the same pollination paper High Priority
This paper describes orchid pollinator behaviour. DOI {doi}
View Source →
""",
        "known-doi",
    )
    assessment = assess_item(item_id)
    assert assessment.knowledge_delta == "ALREADY_KNOWN"
    assert assessment.confidence == pytest.approx(0.95)
    assert any(match.get("matched_doi") == doi for match in assessment.matches)


def test_unverified_scientific_relationship_can_never_be_persisted_as_new_relationship():
    _apply_migrations()
    os.environ["DATABASE_URL"] = str(DATABASE_URL)
    item_id = _record_briefing(
        """
Research and Publications
Unexpected orchid pollinator interaction High Priority
A report describes a previously undocumented pollinator relationship.
View Source →
""",
        "candidate-relationship",
    )
    assessment = assess_item(item_id)
    assert assessment.knowledge_delta == "REQUIRES_REVIEW"
    assert assessment.candidate_delta == "NEW_RELATIONSHIP"
    persisted = record_comparison(assessment)
    assert persisted["knowledge_delta"] == "REQUIRES_REVIEW"
    assert persisted["candidate_delta"] == "NEW_RELATIONSHIP"

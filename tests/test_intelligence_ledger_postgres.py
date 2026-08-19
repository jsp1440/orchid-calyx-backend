from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest

from app.intake.extractor import content_hash, extract
from app.intake.intelligence import canonical_email_text, parse_external_intelligence
from app.intake.intelligence_repository import get_intelligence_item, record_intelligence_items
from app.intake.repository import create_source

DATABASE_URL = os.getenv("INTELLIGENCE_LEDGER_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="INTELLIGENCE_LEDGER_DATABASE_URL not set")


BRIEFING = """
Technology and Infrastructure Opportunities
Google Earth Engine for orchid habitat surveillance High Priority
Earth Engine could support satellite and remote sensing analysis of orchid habitat and fire.
Relevance: Atlas environmental analysis.
Recommended Actions: Evaluate it as an Atlas analytical provider.
View Source →
"""


def _ingest(message_id: str) -> tuple[dict, list[dict]]:
    os.environ["DATABASE_URL"] = str(DATABASE_URL)
    canonical = canonical_email_text(
        sender="twin@twin-mail.com",
        subject=f"Daily briefing {message_id}",
        body=BRIEFING,
        message_id=message_id,
    )
    items = parse_external_intelligence(
        BRIEFING,
        sender="twin@twin-mail.com",
        message_id=message_id,
    )
    extraction = extract(canonical)
    source = create_source(
        source_type="email",
        title=f"Daily briefing {message_id}",
        content=canonical,
        content_hash=content_hash(canonical),
        source_url=None,
        imported_by="postgres-test",
        extraction=extraction,
    )
    records = record_intelligence_items(
        source_id=source["id"],
        items=items,
        sender="twin@twin-mail.com",
        message_id=message_id,
    )
    return source, records


def test_recurring_briefings_become_one_item_with_multiple_observations():
    migration_070 = Path("migrations/070_knowledge_intake.sql").read_text(encoding="utf-8")
    migration_108 = Path("migrations/108_intelligence_assimilation_ledger.sql").read_text(encoding="utf-8")
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(migration_070)
        connection.execute(migration_108)
        connection.execute(migration_108)

    _, first = _ingest("twin-day-1")
    _, second = _ingest("twin-day-2")

    assert len(first) == 1
    assert len(second) == 1
    assert first[0]["id"] == second[0]["id"]
    assert first[0]["knowledge_fingerprint"] == second[0]["knowledge_fingerprint"]
    assert first[0]["new_observation"] is True
    assert second[0]["new_observation"] is True
    assert second[0]["observation_count"] == 2

    restored = get_intelligence_item(first[0]["id"])
    assert restored is not None
    assert restored["lifecycle"] == "DISCOVERED"
    assert restored["knowledge_delta"] == "UNASSESSED"
    assert restored["canonical_promotion_prohibited"] is True
    assert restored["external_contact_prohibited"] is True
    assert len(restored["observations"]) == 2
    assert len(restored["events"]) == 2
    assert {observation["message_id"] for observation in restored["observations"]} == {"twin-day-1", "twin-day-2"}


def test_reingesting_exact_same_email_is_idempotent():
    _, first = _ingest("twin-idempotent")
    _, second = _ingest("twin-idempotent")

    assert first[0]["id"] == second[0]["id"]
    assert first[0]["new_observation"] is True
    assert second[0]["new_observation"] is False

    restored = get_intelligence_item(first[0]["id"])
    matching = [obs for obs in restored["observations"] if obs["message_id"] == "twin-idempotent"]
    assert len(matching) == 1

"""The knowledge-gap record is stale by contract, never by inference.

``runtime/knowledge_gaps/latest.json`` was generated on 2026-07-12 by keyword
matching discovery-memory module names. Its ``KG-TAXONOMY-001`` claims
``Matched runtime items: 0`` while ``app/`` contains taxonomy modules: the
number is an artefact of the method, not evidence about the application.
Regenerating it from the same 2026-07-12 snapshot would reproduce the same
false zero, so the record is marked stale with the reason, and every reader
sees ``freshness`` rather than having to infer age from ``generated_at``.

The first test fails closed: if the committed record is older than its own
``max_record_age_days`` and does not say ``stale: true``, it fails.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime.knowledge_gap_discovery import (
    DISCOVERY_METHOD,
    MAX_RECORD_AGE_DAYS,
    KnowledgeGapDiscoveryEngine,
    assess_freshness,
    freshness_block,
)

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "runtime" / "knowledge_gaps" / "latest.json"


class FrozenSnapshot:
    """A discovery-memory store that returns one fixed snapshot."""

    def __init__(self, generated_at: str) -> None:
        self.snapshot = {
            "snapshot_id": "DSM-TEST",
            "generated_at": generated_at,
            "modules": [{"name": "TaxonomyResolver"}, {"name": "ImageQuality"}],
            "capabilities": [{"name": "species_lookup"}],
            "recommendations": [],
        }

    def latest(self) -> dict:
        return self.snapshot


# -- the committed record fails closed ----------------------------------------


def test_committed_record_older_than_its_max_age_declares_itself_stale():
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    freshness = record["freshness"]
    generated = datetime.fromisoformat(record["generated_at"])
    age_days = (datetime.now(timezone.utc) - generated).days
    if age_days > freshness["max_record_age_days"]:
        assert freshness["stale"] is True, (
            f"record is {age_days} days old, older than {freshness['max_record_age_days']}, "
            "and does not declare stale: true"
        )
        assert freshness["reason"]
    assert freshness["generated_at"] == record["generated_at"]
    assert freshness["method"] == DISCOVERY_METHOD


def test_committed_record_names_the_taxonomy_false_zero_in_its_reason():
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    assert "KG-TAXONOMY-001" in record["freshness"]["reason"]
    assert "not an inventory of app/" in record["freshness"]["method"]


# -- freshness_block and assess_freshness ---------------------------------------


def test_a_record_within_its_max_age_is_fresh():
    now = datetime(2026, 9, 25, tzinfo=timezone.utc)
    generated = (now - timedelta(days=MAX_RECORD_AGE_DAYS)).isoformat()
    block = freshness_block(generated, now=now)
    assert block["stale"] is False
    assert block["reason"] is None
    assert block["age_days"] == MAX_RECORD_AGE_DAYS


def test_a_record_one_day_past_its_max_age_is_stale_with_the_age_named():
    now = datetime(2026, 9, 25, tzinfo=timezone.utc)
    generated = (now - timedelta(days=MAX_RECORD_AGE_DAYS + 1)).isoformat()
    block = freshness_block(generated, now=now)
    assert block["stale"] is True
    assert f"{MAX_RECORD_AGE_DAYS + 1} days old" in block["reason"]


def test_an_unparseable_generated_at_is_stale_not_fresh():
    block = freshness_block(
        "last tuesday", now=datetime(2026, 9, 25, tzinfo=timezone.utc)
    )
    assert block["stale"] is True
    assert block["age_days"] is None


def test_a_caller_supplied_reason_makes_a_young_record_stale():
    now = datetime(2026, 9, 25, tzinfo=timezone.utc)
    block = freshness_block(
        now.isoformat(), now=now, stale_reason="snapshot was already old"
    )
    assert block["stale"] is True
    assert block["reason"] == "snapshot was already old"


def test_assess_freshness_marks_an_aged_record_stale_at_read_time_without_rewriting():
    generated = datetime(2026, 7, 12, tzinfo=timezone.utc)
    payload = {
        "generated_at": generated.isoformat(),
        "freshness": {"stale": False, "reason": None, "max_record_age_days": 30},
    }
    assessed = assess_freshness(payload, now=generated + timedelta(days=75))
    assert assessed["freshness"]["stale"] is True
    assert "75 days old" in assessed["freshness"]["reason"]
    assert payload["freshness"]["stale"] is False  # the input is untouched


def test_assess_freshness_keeps_a_reason_the_record_already_carries():
    generated = datetime(2026, 7, 12, tzinfo=timezone.utc)
    payload = {
        "generated_at": generated.isoformat(),
        "freshness": {"stale": True, "reason": "false zero", "max_record_age_days": 30},
    }
    assessed = assess_freshness(payload, now=generated + timedelta(days=75))
    assert "false zero" in assessed["freshness"]["reason"]
    assert "75 days old" in assessed["freshness"]["reason"]


# -- the generator is honest about what it measures ---------------------------


def test_discover_emits_freshness_and_names_its_method(tmp_path):
    now = datetime(2026, 9, 25, tzinfo=timezone.utc)
    engine = KnowledgeGapDiscoveryEngine(
        output_dir=tmp_path, memory_store=FrozenSnapshot(now.isoformat())
    )
    payload = engine.discover(write_cache=True, now=now)
    assert payload["freshness"]["stale"] is False
    assert payload["freshness"]["method"] == DISCOVERY_METHOD
    assert payload["source_snapshot_generated_at"] == now.isoformat()
    for gap in payload["gaps"]:
        assert any(line.startswith("Method: ") for line in gap["evidence"]), gap[
            "gap_id"
        ]


def test_discover_from_a_stale_snapshot_is_stale_at_generation(tmp_path):
    now = datetime(2026, 9, 25, tzinfo=timezone.utc)
    old = (now - timedelta(days=75)).isoformat()
    engine = KnowledgeGapDiscoveryEngine(
        output_dir=tmp_path, memory_store=FrozenSnapshot(old)
    )
    payload = engine.discover(write_cache=True, now=now)
    assert payload["freshness"]["stale"] is True
    assert "DSM-TEST" in payload["freshness"]["reason"]
    assert "75 days old" in payload["freshness"]["reason"]


def test_every_reader_sees_freshness(tmp_path):
    now = datetime(2026, 9, 25, tzinfo=timezone.utc)
    engine = KnowledgeGapDiscoveryEngine(
        output_dir=tmp_path, memory_store=FrozenSnapshot(now.isoformat())
    )
    engine.discover(write_cache=True, now=now)
    for reader in (
        engine.gaps,
        engine.domains,
        engine.priorities,
        engine.research_queue,
        engine.dashboard,
    ):
        assert "freshness" in reader(), reader.__name__
    assert engine.latest(now=now + timedelta(days=40))["freshness"]["stale"] is True
    assert engine.latest(now=now + timedelta(days=1))["freshness"]["stale"] is False

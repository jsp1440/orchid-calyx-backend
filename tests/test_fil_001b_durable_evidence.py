"""FIL-001B: Calyx candidates persist through the existing PostgreSQL snapshot store.

Runs against a disposable test database named by TEST_DATABASE_URL only. It
deliberately does not fall back to DATABASE_URL, so a developer shell that
exports a production DATABASE_URL never receives synthetic fixture candidates.
In CI an unusable database fails the run rather than skipping.
"""

from __future__ import annotations

import os

import pytest

from app.candidate_knowledge.postgres_repository import PostgresCandidateRepository
from app.candidate_knowledge.service import CandidateExtractionService
from app.functional_interaction.literature_to_calyx import run_chain

pytestmark = pytest.mark.requires_postgres("TEST_DATABASE_URL")
DSN = os.getenv("TEST_DATABASE_URL")


def _components():
    repository = PostgresCandidateRepository(DSN)
    return repository, CandidateExtractionService(repository)


def test_candidates_persist_reload_with_provenance_and_replay_idempotently():
    first = run_chain(
        candidate_components=_components, allow_import_time_database_contact=True
    )
    assert first.succeeded, [r.failure_reason for r in first.receipts]
    handoffs = first.final_output["handoffs"]
    ids = {cid for h in handoffs for cid in h["calyx_candidate_ids"]}

    fresh = PostgresCandidateRepository(DSN)
    stored = {
        c["candidate_id"]: c for c in fresh.candidates if c["candidate_id"] in ids
    }
    assert set(stored) == ids
    by_reasoning = {c["qualifiers"]["reasoning_id"]: c for c in stored.values()}
    for handoff in handoffs:
        candidate = by_reasoning[handoff["candidate_id"]]
        assert candidate["review_state"] == "REQUIRED"
        assert candidate["published"] is False
        assert candidate["qualifiers"]["human_review_required"] is True
        assert (
            candidate["qualifiers"]["provenance"]["contradictions"]
            == handoff["contradicts"]
        )
        anchors = [
            link["anchor"]["logical_unit"]
            for link in fresh.evidence_links
            if link["candidate_id"] == candidate["candidate_id"]
        ]
        assert any(
            a.startswith(tuple(handoff["sources"])) and "sha256:" in a for a in anchors
        ), anchors

    before = len(fresh.candidates)
    second = run_chain(
        candidate_components=_components, allow_import_time_database_contact=True
    )
    assert second.succeeded
    assert [h["calyx_candidate_ids"] for h in second.final_output["handoffs"]] == [
        h["calyx_candidate_ids"] for h in handoffs
    ]
    assert len(PostgresCandidateRepository(DSN).candidates) == before, (
        "replay must reuse, never duplicate"
    )
    assert PostgresCandidateRepository(DSN).lock_available()

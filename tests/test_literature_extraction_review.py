from __future__ import annotations

from datetime import datetime, timezone

from app.literature_extraction.models import ReviewDecision
from app.literature_extraction.review import (
    build_review_queue,
    evaluate_publication_decision,
    refresh_publication_decisions,
)


def test_review_queue_is_deterministic_and_prioritizes_unresolved_entities(sample_paper):
    paper = build_review_queue(sample_paper)
    first = [item.model_dump(mode="json") for item in paper.review_items]

    paper.review_items = []
    paper = build_review_queue(paper)
    second = [item.model_dump(mode="json") for item in paper.review_items]

    assert first == second
    assert paper.review_items
    assert paper.review_items[0].priority_reasons
    assert paper.review_items == sorted(
        paper.review_items,
        key=lambda item: (-item.priority, item.review_item_id),
    )


def test_publication_decision_requires_review(sample_paper):
    paper = build_review_queue(sample_paper)
    item = paper.review_items[0]

    pending = evaluate_publication_decision(item, None)
    assert pending.status == "blocked"
    assert pending.reason_codes == ["awaiting_review"]

    decision = ReviewDecision(
        decision_id="decision-1",
        review_item_id=item.review_item_id,
        decision="accept",
        reviewer_id="reviewer@example.org",
        decided_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
        source_record_fingerprint=item.source_record_fingerprint,
    )
    accepted = evaluate_publication_decision(item, decision)
    assert accepted.status == "eligible_for_publication"
    assert accepted.based_on_decision_id == "decision-1"


def test_refresh_publication_decisions_uses_latest_append_only_decision(sample_paper):
    paper = build_review_queue(sample_paper)
    item = paper.review_items[0]
    paper.review_decisions = [
        ReviewDecision(
            decision_id="decision-old",
            review_item_id=item.review_item_id,
            decision="defer",
            reviewer_id="reviewer@example.org",
            decided_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
            source_record_fingerprint=item.source_record_fingerprint,
        ),
        ReviewDecision(
            decision_id="decision-new",
            review_item_id=item.review_item_id,
            decision="accept_with_corrections",
            reviewer_id="reviewer@example.org",
            decided_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
            reason_codes=["corrected_taxon_identifier"],
            corrections={"canonical_entity_ids": ["powo:123"]},
            source_record_fingerprint=item.source_record_fingerprint,
        ),
    ]

    refresh_publication_decisions(paper)

    publication = next(
        item for item in paper.publication_decisions
        if item.review_item_id == paper.review_items[0].review_item_id
    )
    assert publication.status == "eligible_for_publication"
    assert publication.based_on_decision_id == "decision-new"

from __future__ import annotations

from hashlib import sha256
import json

from .models import (
    NormalizedEvidenceRecord,
    PaperKnowledge,
    PublicationDecision,
    ReconciliationRelation,
    ReviewDecision,
    ReviewItem,
)


def _stable_id(prefix: str, *parts: str) -> str:
    digest = sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _record_fingerprint(record: NormalizedEvidenceRecord) -> str:
    payload = {
        "record_id": record.record_id,
        "statement": record.statement,
        "normalized_statement": record.normalized_statement,
        "domain": record.domain,
        "polarity": record.polarity,
        "canonical_entity_ids": record.canonical_entity_ids,
        "unresolved_entities": record.unresolved_entities,
        "evidence_ids": record.evidence_ids,
        "reconciliation_group_id": record.reconciliation_group_id,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def _priority(
    record: NormalizedEvidenceRecord,
    relations: list[ReconciliationRelation],
) -> tuple[int, list[str]]:
    reasons: list[str] = []
    score = 0
    if record.unresolved_entities:
        score += 100
        reasons.append("unresolved_entities")
    if any(
        relation.relation_type == "potential_contradiction"
        and record.record_id in {relation.subject_record_id, relation.object_record_id}
        for relation in relations
    ):
        score += 80
        reasons.append("potential_contradiction")
    if record.normalization_confidence < 0.75:
        score += 60
        reasons.append("low_normalization_confidence")
    if any(
        relation.relation_type == "duplicate"
        and record.record_id in {relation.subject_record_id, relation.object_record_id}
        for relation in relations
    ):
        score += 40
        reasons.append("duplicate_group")
    if not reasons:
        reasons.append("standard_review")
    return score, reasons


def build_review_queue(paper: PaperKnowledge) -> PaperKnowledge:
    items: list[ReviewItem] = []
    for record in paper.normalized_evidence_records:
        priority, reasons = _priority(record, paper.reconciliation_relations)
        fingerprint = _record_fingerprint(record)
        items.append(
            ReviewItem(
                review_item_id=_stable_id("review", record.record_id, fingerprint),
                source_record_id=record.record_id,
                reconciliation_group_id=record.reconciliation_group_id,
                priority=priority,
                priority_reasons=reasons,
                source_record_fingerprint=fingerprint,
            )
        )
    paper.review_items = sorted(
        items,
        key=lambda item: (-item.priority, item.review_item_id),
    )
    return paper


def evaluate_publication_decision(
    item: ReviewItem,
    decision: ReviewDecision | None,
) -> PublicationDecision:
    status = "blocked"
    reasons = ["awaiting_review"]
    decision_id = None
    if decision is not None:
        decision_id = decision.decision_id
        mapping = {
            "accept": ("eligible_for_publication", ["review_accepted"]),
            "accept_with_corrections": ("eligible_for_publication", ["review_accepted_with_corrections"]),
            "reject": ("rejected", ["review_rejected"]),
            "defer": ("deferred", ["review_deferred"]),
            "needs_expert_review": ("blocked", ["expert_review_required"]),
        }
        status, reasons = mapping[decision.decision]
    return PublicationDecision(
        publication_decision_id=_stable_id(
            "publication",
            item.review_item_id,
            decision_id or "pending",
            status,
        ),
        review_item_id=item.review_item_id,
        source_record_id=item.source_record_id,
        status=status,
        reason_codes=reasons,
        based_on_decision_id=decision_id,
    )


def refresh_publication_decisions(paper: PaperKnowledge) -> PaperKnowledge:
    latest_by_item: dict[str, ReviewDecision] = {}
    for decision in paper.review_decisions:
        current = latest_by_item.get(decision.review_item_id)
        if current is None or decision.decided_at >= current.decided_at:
            latest_by_item[decision.review_item_id] = decision
    paper.publication_decisions = [
        evaluate_publication_decision(item, latest_by_item.get(item.review_item_id))
        for item in paper.review_items
    ]
    return paper

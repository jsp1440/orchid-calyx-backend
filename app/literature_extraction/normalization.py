from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import re

from .models import (
    Claim,
    Evidence,
    NormalizedEvidenceRecord,
    PaperKnowledge,
    ReconciliationRelation,
)


_CLAIM_DOMAIN_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("taxonomy", ("species", "genus", "taxon", "synonym", "classified")),
    ("occurrence", ("occur", "distribution", "range", "site", "locality")),
    ("habitat", ("habitat", "forest", "wetland", "substrate", "elevation")),
    ("ecological_interaction", ("pollinat", "mycorrh", "fung", "host", "interaction")),
    ("conservation", ("threat", "endangered", "conservation", "decline", "protected")),
    ("cultivation", ("cultivat", "grow", "water", "fertiliz", "temperature", "light")),
    ("trait", ("flower", "leaf", "growth", "height", "length", "color", "shape")),
)


def _normalized_text(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def _stable_id(prefix: str, *parts: str) -> str:
    digest = sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _classify_domain(claim: Claim) -> str:
    text = _normalized_text(claim.statement)
    for domain, markers in _CLAIM_DOMAIN_RULES:
        if any(marker in text for marker in markers):
            return domain
    return "other"


def _resolve_entities(paper: PaperKnowledge, claim: Claim) -> tuple[list[str], list[str]]:
    entity_by_id = {entity.entity_id: entity for entity in paper.entities}
    resolved: list[str] = []
    unresolved: list[str] = []
    for entity_id in [*claim.subject_ids, *claim.object_ids]:
        entity = entity_by_id.get(entity_id)
        if entity is None:
            unresolved.append(entity_id)
            continue
        external = next((item for item in entity.external_ids if item.value), None)
        if external is not None:
            resolved.append(f"{external.scheme}:{external.value}")
        elif entity.normalized_name:
            unresolved.append(entity.normalized_name)
        else:
            unresolved.append(entity.name)
    return sorted(set(resolved)), sorted(set(unresolved))


def _record_for_claim(
    paper: PaperKnowledge,
    claim: Claim,
    evidence_by_id: dict[str, Evidence],
) -> NormalizedEvidenceRecord:
    linked = [evidence_by_id[item] for item in claim.evidence_ids if item in evidence_by_id]
    excerpts = [item.excerpt for item in linked]
    evidence_ids = [item.evidence_id for item in linked]
    resolved_ids, unresolved_entities = _resolve_entities(paper, claim)
    normalization_confidence = 1.0 if resolved_ids and not unresolved_entities else 0.5 if unresolved_entities else 0.75
    fingerprint = _normalized_text(claim.statement)
    record_id = _stable_id("record", paper.paper_id, claim.claim_id, fingerprint)
    return NormalizedEvidenceRecord(
        record_id=record_id,
        source_claim_id=claim.claim_id,
        evidence_ids=evidence_ids,
        statement=claim.statement,
        normalized_statement=fingerprint,
        domain=_classify_domain(claim),
        polarity=claim.polarity,
        canonical_entity_ids=resolved_ids,
        unresolved_entities=unresolved_entities,
        extraction_confidence=claim.provenance.confidence,
        normalization_confidence=normalization_confidence,
        review_status="unreviewed",
        validation_notes=[
            *([] if linked else ["claim_has_no_linked_evidence"]),
            *([] if resolved_ids else ["no_canonical_entity_identifier"]),
        ],
        source_excerpts=excerpts,
        provenance=claim.provenance,
    )


def normalize_and_reconcile(paper: PaperKnowledge) -> PaperKnowledge:
    evidence_by_id = {item.evidence_id: item for item in paper.evidence}
    records = [_record_for_claim(paper, claim, evidence_by_id) for claim in paper.claims]

    by_statement: dict[str, list[NormalizedEvidenceRecord]] = defaultdict(list)
    for record in records:
        by_statement[record.normalized_statement].append(record)

    relations: list[ReconciliationRelation] = []
    for statement, group in sorted(by_statement.items()):
        group_id = _stable_id("group", paper.paper_id, statement)
        for record in group:
            record.reconciliation_group_id = group_id
        if len(group) > 1:
            anchor = group[0]
            for duplicate in group[1:]:
                relations.append(
                    ReconciliationRelation(
                        relation_id=_stable_id("relation", anchor.record_id, duplicate.record_id, "duplicate"),
                        subject_record_id=anchor.record_id,
                        object_record_id=duplicate.record_id,
                        relation_type="duplicate",
                        reason="normalized statements are identical",
                    )
                )

    paper.normalized_evidence_records = records
    paper.reconciliation_relations = relations
    return paper

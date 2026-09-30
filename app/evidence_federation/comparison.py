"""Field-by-field comparison without collapsing independent source claims."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from .adapters import EvidenceAssertion, SourceRecord


def _norm(value: str) -> str:
    return " ".join(value.casefold().split())


def compare_assertions(records: Iterable[SourceRecord]) -> dict[str, dict]:
    by_predicate: dict[str, list[tuple[str, EvidenceAssertion]]] = defaultdict(list)
    for record in records:
        for assertion in record.assertions:
            by_predicate[assertion.predicate].append((record.source_id, assertion))

    out: dict[str, dict] = {}
    for predicate, claims in sorted(by_predicate.items()):
        normalized = {_norm(claim.value) for _, claim in claims}
        if len(claims) == 1:
            relationship = "single_source"
        elif len(normalized) == 1:
            relationship = "exact_agreement"
        else:
            relationship = "multiple_source_claims_review_required"
        out[predicate] = {
            "relationship": relationship,
            "claims": [
                {
                    "source_id": source_id,
                    "value": claim.value,
                    "source_field": claim.source_field,
                    "review_state": claim.review_state,
                }
                for source_id, claim in claims
            ],
        }
    return out

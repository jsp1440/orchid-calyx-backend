"""Source-preserving field comparison for federated evidence rows."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any


def _norm(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def compare_evidence_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group source claims by taxon and evidence type without collapsing them.

    Only literal normalized equality is called agreement. All other multi-source
    cases remain review-required; this deliberately avoids semantic averaging.
    """

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        taxon_pk = str(row.get("taxon_pk") or "")
        evidence_type = str(row.get("evidence_type") or "")
        if taxon_pk and evidence_type:
            grouped[(taxon_pk, evidence_type)].append(dict(row))

    out: list[dict[str, Any]] = []
    for (taxon_pk, evidence_type), claims in sorted(grouped.items()):
        distinct_sources = {str(c.get("source_name") or "") for c in claims}
        normalized_values = {_norm(c.get("excerpt")) for c in claims if c.get("excerpt")}
        if len(claims) == 1:
            relationship = "single_source"
        elif len(normalized_values) == 1:
            relationship = "exact_agreement"
        elif len(distinct_sources) > 1:
            relationship = "multiple_source_claims_review_required"
        else:
            relationship = "same_source_multiple_claims_review_required"

        out.append(
            {
                "taxon_pk": taxon_pk,
                "evidence_type": evidence_type,
                "relationship": relationship,
                "claim_count": len(claims),
                "source_count": len(distinct_sources),
                "claims": [
                    {
                        "source_name": c.get("source_name"),
                        "source_record_id": c.get("source_record_id"),
                        "claim_label": c.get("claim_label"),
                        "excerpt": c.get("excerpt"),
                        "citation": c.get("citation"),
                        "review_state": c.get("review_state"),
                    }
                    for c in claims
                ],
            }
        )
    return out

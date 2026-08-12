from __future__ import annotations

import argparse
import json

from app.trait_genomics.molecular_review_queue import (
    MolecularReviewQueueQuery,
    MolecularReviewQueueRepository,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read the governed TIG molecular evidence review queue."
    )
    parser.add_argument(
        "--state",
        choices=("candidate", "accepted", "rejected", "needs_review"),
    )
    parser.add_argument(
        "--kind",
        choices=(
            "genetic_association",
            "expression_association",
            "selection_association",
        ),
    )
    parser.add_argument("--taxon-id")
    parser.add_argument("--scientific-name")
    parser.add_argument("--source-id")
    parser.add_argument("--min-confidence", type=float, default=0.0)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()

    query = MolecularReviewQueueQuery(
        review_state=args.state,
        evidence_kind=args.kind,
        canonical_taxon_id=args.taxon_id,
        scientific_name=args.scientific_name,
        source_id=args.source_id,
        min_confidence=args.min_confidence,
        limit=args.limit,
        offset=args.offset,
    )
    page = MolecularReviewQueueRepository().list(query)
    print(json.dumps(page.as_dict(), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

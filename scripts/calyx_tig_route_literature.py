from __future__ import annotations

import argparse
import json

from app.trait_genomics.evidence_routing_service import LiteratureEvidenceRoutingService
from app.trait_genomics.molecular_harvester import MolecularHarvestTarget
from app.trait_genomics.taxon_target_resolver import CanonicalTaxonTargetResolver


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Route Europe PMC orchid literature into review-only scientific evidence channels. "
            "Routing never makes a paper live TIG evidence."
        )
    )
    parser.add_argument(
        "--name",
        action="append",
        default=[],
        help="Repeatable scientific name resolved against public.orchid_taxonomy.",
    )
    parser.add_argument("--page-size", type=int, default=10)
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Persist review-only route records to oc_literature.evidence_route_candidates.",
    )
    args = parser.parse_args()

    if not args.name:
        parser.error("provide at least one --name")

    resolver = CanonicalTaxonTargetResolver()
    targets: list[MolecularHarvestTarget] = []
    resolutions = []
    for name in args.name:
        resolution = resolver.resolve(name)
        resolutions.append(resolution.as_dict())
        if resolution.status != "resolved" or resolution.target is None:
            print(
                json.dumps(
                    {
                        "status": "blocked",
                        "reason": "canonical_taxon_resolution_failed",
                        "resolutions": resolutions,
                        "database_write": False,
                    },
                    indent=2,
                    sort_keys=True,
                    default=str,
                )
            )
            return 2
        targets.append(resolution.target)

    result = LiteratureEvidenceRoutingService().route(
        targets,
        page_size=args.page_size,
        persist=args.persist,
    )
    result["target_resolutions"] = resolutions
    result["database_write"] = bool(args.persist)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

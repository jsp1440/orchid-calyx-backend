from __future__ import annotations

import argparse
import json

from app.trait_genomics.adaptive_retrieval import AdaptiveEuropePMCClient
from app.trait_genomics.molecular_harvester import (
    EuropePMCHarvestRequest,
    EuropePMCMolecularHarvester,
    MolecularHarvestTarget,
)
from app.trait_genomics.taxon_target_resolver import CanonicalTaxonTargetResolver


def _target(value: str) -> MolecularHarvestTarget:
    if "=" not in value:
        raise argparse.ArgumentTypeError("target must use CANONICAL_TAXON_ID=Scientific name")
    taxon_id, scientific_name = value.split("=", 1)
    try:
        return MolecularHarvestTarget(
            canonical_taxon_id=taxon_id.strip(),
            scientific_name=scientific_name.strip(),
        )
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Harvest strict review-only molecular association candidates from Europe PMC. "
            "Nothing becomes live TIG evidence without later human acceptance."
        )
    )
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        type=_target,
        help="Repeatable explicit CANONICAL_TAXON_ID=Scientific name target.",
    )
    parser.add_argument(
        "--name",
        action="append",
        default=[],
        help=(
            "Repeatable scientific name resolved exactly against public.orchid_taxonomy. "
            "Ambiguous or unresolved names fail closed."
        ),
    )
    parser.add_argument("--page-size", type=int, default=25)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover and print candidates without writing to Neon/Postgres.",
    )
    parser.add_argument(
        "--resolve-only",
        action="store_true",
        help="Resolve canonical taxon IDs and exit without contacting Europe PMC.",
    )
    args = parser.parse_args()

    if not args.target and not args.name:
        parser.error("provide at least one --name or --target")

    resolved_targets = list(args.target)
    resolutions = []
    if args.name:
        resolver = CanonicalTaxonTargetResolver()
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
                        },
                        indent=2,
                        sort_keys=True,
                        default=str,
                    )
                )
                return 2
            resolved_targets.append(resolution.target)

    deduplicated = {
        (target.canonical_taxon_id, target.scientific_name): target
        for target in resolved_targets
    }
    targets = list(deduplicated.values())
    if args.resolve_only:
        print(
            json.dumps(
                {
                    "status": "resolved",
                    "targets": [target.model_dump(mode="json") for target in targets],
                    "resolutions": resolutions,
                    "harvest_executed": False,
                    "database_write": False,
                },
                indent=2,
                sort_keys=True,
                default=str,
            )
        )
        return 0

    request = EuropePMCHarvestRequest(
        targets=targets,
        page_size=args.page_size,
        persist=not args.dry_run,
    )
    client = AdaptiveEuropePMCClient()
    result = EuropePMCMolecularHarvester(client=client).harvest(
        request.targets,
        page_size=request.page_size,
        persist=request.persist,
    )
    result["target_resolutions"] = resolutions
    result["retrieval_diagnostics"] = client.retrieval_diagnostics()
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

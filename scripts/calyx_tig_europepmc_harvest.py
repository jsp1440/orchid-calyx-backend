from __future__ import annotations

import argparse
import json

from app.trait_genomics.molecular_harvester import (
    EuropePMCHarvestRequest,
    EuropePMCMolecularHarvester,
    MolecularHarvestTarget,
)


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
        required=True,
        type=_target,
        help="Repeatable CANONICAL_TAXON_ID=Scientific name target.",
    )
    parser.add_argument("--page-size", type=int, default=25)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover and print candidates without writing to Neon/Postgres.",
    )
    args = parser.parse_args()

    request = EuropePMCHarvestRequest(
        targets=args.target,
        page_size=args.page_size,
        persist=not args.dry_run,
    )
    result = EuropePMCMolecularHarvester().harvest(
        request.targets,
        page_size=request.page_size,
        persist=request.persist,
    )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

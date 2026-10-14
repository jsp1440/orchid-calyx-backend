"""Controlled TraitBank ingestion (the only write path).

    python -m app.traitbank.cli load-definitions [--apply]
    python -m app.traitbank.cli normalize-paper PAPER.json  > batch.json
    python -m app.traitbank.cli normalize-eol TRAITBANK.tsv --dataset-citation ... --dataset-license ...
    python -m app.traitbank.cli ingest BATCH.json [--apply --ingested-by NAME]

Safety rails:

- dry-run is the default; ``--apply`` is required to write;
- the database is taken from ``--database-url`` or ``TRAITBANK_DATABASE_URL``
  only, never from a generic ``DATABASE_URL`` that might point at production;
- ``--fixture-mode`` relaxes the placeholder guards for validating test
  payloads and can never be combined with ``--apply``;
- no network access: EOL files are read from a local path, never downloaded.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.literature_extraction.models import PaperKnowledge

from .adapters import TraitIndex, from_paper_knowledge, from_traitbank_harvester
from .models import TraitBankBatch, TraitDefinitionIn
from .repository import TraitBankRefused, TraitBankRepository

DEFINITIONS_PATH = Path(__file__).with_name("definitions_v1.json")


def _database_url(args: argparse.Namespace) -> str:
    url = args.database_url or os.environ.get("TRAITBANK_DATABASE_URL")
    if not url:
        raise SystemExit(
            "TraitBank needs --database-url or TRAITBANK_DATABASE_URL (DATABASE_URL is deliberately not used)"
        )
    return url


def load_definition_file(path: Path = DEFINITIONS_PATH) -> list[TraitDefinitionIn]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [TraitDefinitionIn.model_validate(d) for d in payload["definitions"]]


def _trait_index(repo: TraitBankRepository) -> TraitIndex:
    return TraitIndex(repo.definitions())


def _emit(payload: Any) -> None:
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False, default=str)
    sys.stdout.write("\n")


def parse_traitbank_tsv(path: Path) -> list[dict[str, Any]]:
    """Read a local EOL TraitBank file with the existing harvester's own parser."""
    from harvesters.traitbank import TraitBankHarvester

    harvester = TraitBankHarvester()
    parse = harvester._choose_parser(str(path))
    records = []
    for raw in parse(str(path)):
        rec = harvester._normalize(raw, source_path=str(path))
        if not harvester._is_effectively_empty(rec):
            records.append(rec)
    return records


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="traitbank")
    parser.add_argument("--database-url")
    sub = parser.add_subparsers(dest="command", required=True)

    defs = sub.add_parser("load-definitions")
    defs.add_argument("--file", type=Path, default=DEFINITIONS_PATH)
    defs.add_argument("--apply", action="store_true")

    paper = sub.add_parser("normalize-paper")
    paper.add_argument("path", type=Path)

    eol = sub.add_parser("normalize-eol")
    eol.add_argument("path", type=Path)
    eol.add_argument("--dataset-citation", required=True)
    eol.add_argument("--dataset-license", required=True)

    ingest = sub.add_parser("ingest")
    ingest.add_argument("path", type=Path)
    ingest.add_argument("--apply", action="store_true")
    ingest.add_argument("--ingested-by", default="")
    ingest.add_argument("--fixture-mode", action="store_true")

    args = parser.parse_args(argv)
    repo = TraitBankRepository(_database_url(args))
    try:
        if args.command == "load-definitions":
            definitions = load_definition_file(args.file)
            if not args.apply:
                from . import guards

                violations = [
                    v.as_dict()
                    for d in definitions
                    for v in guards.check_definition(d, live=True)
                ]
                _emit(
                    {
                        "state": "DRY_RUN_OK" if not violations else "REFUSED",
                        "violations": violations,
                        "definitions": [d.trait_id for d in definitions],
                    }
                )
                return 0 if not violations else 2
            _emit({"state": "APPLIED", **repo.load_definitions(definitions, live=True)})
            return 0
        if args.command == "normalize-paper":
            knowledge = PaperKnowledge.model_validate_json(
                args.path.read_text(encoding="utf-8")
            )
            result = from_paper_knowledge(
                knowledge, _trait_index(repo), repo.resolve_species
            )
            _emit(
                {
                    "batch": result.batch.model_dump(mode="json")
                    if result.batch
                    else None,
                    "unmapped": result.unmapped,
                }
            )
            return 0
        if args.command == "normalize-eol":
            result = from_traitbank_harvester(
                parse_traitbank_tsv(args.path),
                _trait_index(repo),
                repo.resolve_species,
                dataset_citation=args.dataset_citation,
                dataset_license=args.dataset_license,
            )
            _emit(
                {
                    "batch": result.batch.model_dump(mode="json")
                    if result.batch
                    else None,
                    "unmapped": result.unmapped,
                }
            )
            return 0
        payload = json.loads(args.path.read_text(encoding="utf-8"))
        batch = TraitBankBatch.model_validate(payload.get("batch", payload))
        if args.fixture_mode and args.apply:
            raise SystemExit(
                "--fixture-mode cannot write: fixtures are validated, never stored"
            )
        if args.apply and not args.ingested_by.strip():
            raise SystemExit("--apply requires --ingested-by")
        report = repo.ingest(
            batch,
            ingested_by=args.ingested_by or "dry-run",
            live=not args.fixture_mode,
            dry_run=not args.apply,
        )
        _emit(report)
        return 0
    except TraitBankRefused as refused:
        _emit({"state": "REFUSED", "violations": refused.violations})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

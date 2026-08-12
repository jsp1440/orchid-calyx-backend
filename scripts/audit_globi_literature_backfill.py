#!/usr/bin/env python3
"""Read-only operator for retrospective GloBI/RO literature interaction screening."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

from runtime.knowledge_graph.globi_corpus_backfill import (
    DEFAULT_MAX_PAPERS,
    globi_tsv_rows,
    scan_existing_literature_for_globi_candidates,
)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=None)
    p.add_argument("--start-after", default=None)
    p.add_argument("--max-papers", type=int, default=DEFAULT_MAX_PAPERS)
    p.add_argument("--format", choices=("json", "tsv"), default="json")
    p.add_argument("--output", default=None)
    return p


def main() -> int:
    args = parser().parse_args()
    dsn = os.getenv("DATABASE_URL", "").strip()
    report = scan_existing_literature_for_globi_candidates(
        dsn,
        root=args.root,
        start_after=args.start_after,
        max_papers=args.max_papers,
    )

    if args.format == "json":
        rendered = json.dumps(report, indent=2, default=str) + "\n"
        if args.output:
            Path(args.output).write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
        return 0

    rows = globi_tsv_rows(report)
    fields = [
        "sourceTaxonName",
        "interactionTypeName",
        "interactionTypeId",
        "targetTaxonName",
        "referenceDoi",
        "referenceCitation",
        "referenceUrl",
        "sourceId",
        "sourceCitation",
        "notes",
    ]
    handle = open(args.output, "w", encoding="utf-8", newline="") if args.output else sys.stdout
    try:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    finally:
        if args.output:
            handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

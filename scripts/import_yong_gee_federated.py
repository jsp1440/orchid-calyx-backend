#!/usr/bin/env python3
"""Dry-run the Gary Yong Gee workbook against the canonical OC taxon graph.

This command deliberately performs NO canonical graph writes. It produces a
JSON reconciliation report and, optionally, a JSONL file containing evidence
rows shaped for the existing Knowledge Graph EVIDENCE_ADAPTER.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from runtime.federated_sources.yong_gee import build_dry_run
from runtime.knowledge_graph.repository import PostgresGraphRepository


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--sheet", default="Chosen")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--report", type=Path)
    parser.add_argument("--evidence-jsonl", type=Path)
    args = parser.parse_args()

    if not args.database_url:
        parser.error(
            "DATABASE_URL or --database-url is required for canonical taxonomy lookup"
        )

    repo = PostgresGraphRepository(args.database_url)
    taxonomy_nodes = repo.taxonomy_nodes()
    rows, report = build_dry_run(
        args.workbook,
        taxonomy_nodes,
        sheet_name=args.sheet,
    )

    rendered = json.dumps(report.to_dict(), indent=2, ensure_ascii=False)
    print(rendered)
    if args.report:
        args.report.write_text(rendered + "\n", encoding="utf-8")
    if args.evidence_jsonl:
        with args.evidence_jsonl.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

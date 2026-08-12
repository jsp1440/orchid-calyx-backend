#!/usr/bin/env python3
"""Operator for reviewed literature scientific-method graph materialization.

The command is read-only unless ``--execute`` is supplied together with the exact
confirmation token. Literature document ids are always explicit so a production
run cannot accidentally expand to the complete corpus.
"""

from __future__ import annotations

import argparse
import json
import os

from runtime.knowledge_graph.reviewed_literature_materializer import (
    CONFIRMATION_TOKEN,
    DEFAULT_MAX_DOCUMENTS,
    materialize_reviewed_literature_graph,
)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--document-id",
        dest="document_ids",
        action="append",
        required=True,
        help=(
            "Canonical public.research_documents id to validate. Repeat for a "
            "bounded multi-document slice."
        ),
    )
    p.add_argument(
        "--max-documents",
        type=int,
        default=DEFAULT_MAX_DOCUMENTS,
        help="Maximum explicit document ids accepted in this invocation.",
    )
    p.add_argument(
        "--root",
        default=None,
        help=(
            "Optional literature extraction root. Defaults to "
            "LITERATURE_EXTRACTION_ROOT or runtime/literature_extraction."
        ),
    )
    p.add_argument(
        "--execute",
        action="store_true",
        help=(
            "Transactionally publish the already-reviewed scientific-method graph "
            "slice. Without this flag the command is read-only."
        ),
    )
    p.add_argument(
        "--confirm",
        default=None,
        help=f"Required with --execute: {CONFIRMATION_TOKEN}",
    )
    return p


def main() -> int:
    args = parser().parse_args()
    dsn = os.getenv("DATABASE_URL", "").strip()
    report = materialize_reviewed_literature_graph(
        dsn,
        document_ids=args.document_ids,
        root=args.root,
        execute=args.execute,
        confirmation=args.confirm,
        max_documents=args.max_documents,
    )
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

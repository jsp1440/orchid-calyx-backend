#!/usr/bin/env python3
"""Operator for verified cross-domain Knowledge Graph relationship materialization."""

from __future__ import annotations

import argparse
import json
import os

from runtime.knowledge_graph.production_materializer import (
    CONFIRMATION_TOKEN,
    materialize_verified_relationships,
)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--domains",
        nargs="*",
        default=None,
        help="Verified domains to materialize. Default: audit-priority domains.",
    )
    p.add_argument("--batch-size", type=int, default=500)
    p.add_argument(
        "--execute",
        action="store_true",
        help="Publish to oc_graph. Without this flag the command is read-only dry-run.",
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
    report = materialize_verified_relationships(
        dsn,
        domains=args.domains,
        execute=args.execute,
        confirmation=args.confirm,
        batch_size=args.batch_size,
    )
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Read-only operator for persisted Orchid Continuum Knowledge Graph integration."""

from __future__ import annotations

import json
import os

import psycopg
from psycopg.rows import dict_row

from app.readiness.live_graph_audit import run_live_graph_audit


def main() -> int:
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        raise SystemExit("DATABASE_URL_REQUIRED")
    with psycopg.connect(dsn, connect_timeout=10, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            report = run_live_graph_audit(cur)
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("homepage_ready") else 2


if __name__ == "__main__":
    raise SystemExit(main())

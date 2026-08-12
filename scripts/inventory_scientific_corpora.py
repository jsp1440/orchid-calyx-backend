from __future__ import annotations

import json
import os

import psycopg

from runtime.knowledge_graph.scientific_corpus_inventory import inventory_scientific_corpora


def main() -> int:
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        raise SystemExit("DATABASE_URL_REQUIRED")

    with psycopg.connect(dsn, connect_timeout=10) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            report = inventory_scientific_corpora(cur)
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Run a read-only corpus inventory; emit counts and blocker codes only."""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.literature_extraction.corpus_audit import audit_existing_corpus


def public_counts(report):
    """No titles, source prose, identifiers, URLs, credentials or locality."""
    return {
        "schema": report["schema"],
        "available": report["available"],
        "audit_complete": report.get("audit_complete", False),
        "complete": report["complete"],
        "relations": report["relations"],
        "persistent_evidence": report.get("persistent_evidence", {}),
        "summary_counts": report.get("summary_counts", {}),
        "relevant_documents": report.get("relevant_documents"),
        "unprocessed_documents": report.get("unprocessed_documents"),
        "document_genres": dict(Counter(row["genre"] for row in report["documents"])),
        "blocker_counts": dict(Counter(code.split(":", 1)[0] for code in report["blockers"])),
        "scientific_publication": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--genus", required=True)
    parser.add_argument("--taxon", action="append", default=[])
    parser.add_argument("--max-rows", type=int, default=25000)
    args = parser.parse_args(argv)
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        print(json.dumps({"available": False, "complete": False, "error": "DATABASE_URL_UNAVAILABLE"}))
        return 2
    import psycopg
    report = audit_existing_corpus(lambda: psycopg.connect(dsn, connect_timeout=10),
                                  genus=args.genus, taxon_names=args.taxon, max_rows=args.max_rows)
    print(json.dumps(public_counts(report), sort_keys=True))
    return 0 if report["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

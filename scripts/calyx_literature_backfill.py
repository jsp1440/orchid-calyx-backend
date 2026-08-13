from __future__ import annotations

import argparse
import hashlib
import json
from typing import Any

from app.calyx_conversation.external_literature import search_europe_pmc
from app.semantic_index import routes as semantic_index_routes
from app.semantic_index.models import IndexDocument


def _stable_id(value: str) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return int(digest[:15], 16)


def _document(record: dict[str, Any], *, query: str) -> IndexDocument | None:
    abstract = str(record.get("abstract") or "").strip()
    title = str(record.get("title") or "").strip()
    if not abstract or not title:
        return None
    identifier = str(
        record.get("doi") or record.get("pmid") or record.get("pmcid") or title
    ).strip()
    source_object_id = _stable_id("europe-pmc:" + identifier)
    revision_id = _stable_id(
        "europe-pmc-revision:"
        + identifier
        + ":"
        + str(record.get("publication_date") or "unknown")
    )
    extraction_run_id = _stable_id("europe-pmc-query:" + query)
    authors = str(record.get("authors") or "").strip()
    text = title + "\n\n" + abstract
    return IndexDocument(
        source_object_type="LITERATURE_RECORD",
        source_object_id=source_object_id,
        revision_id=revision_id,
        extraction_run_id=extraction_run_id,
        text=text,
        collections=("LITERATURE", "ORCHID_SCIENCE", "GENERAL_BRAIN"),
        title=title,
        document_class="SCIENTIFIC_LITERATURE",
        language="en",
        intended_consumers=("CALYX", "BRAIN", "RESEARCH_STATION"),
        temporal_status="CURRENT",
        verification_state="UNVERIFIED",
        review_state="CLEAR",
        internal_indexing_permission=True,
        display_policy="INTERNAL_RESEARCH_ONLY",
        metadata={
            "title": title,
            "document_title": title,
            "authors": [authors] if authors else [],
            "publication_date": record.get("publication_date"),
            "source_type": "EUROPE_PMC",
            "document_class": "SCIENTIFIC_LITERATURE",
            "source_document_id": identifier,
            "identifier": {
                "doi": record.get("doi"),
                "pmid": record.get("pmid"),
                "pmcid": record.get("pmcid"),
            },
            "collections": ["LITERATURE", "ORCHID_SCIENCE", "GENERAL_BRAIN"],
            "display_policy": "INTERNAL_RESEARCH_ONLY",
            "internal_access_allowed": True,
            "scientific_review_required": True,
            "external_discovery_provider": "Europe PMC",
            "harvest_query": query,
            "peer_reviewed": "UNKNOWN",
            "evidence_type": "PRIMARY_OR_REVIEW_UNKNOWN",
            "ai_generated": "NO",
            "citations_verified": "NO",
            "review_state": "CLEAR",
            "verification_state": "UNVERIFIED",
            "temporal_status": "CURRENT",
        },
    )


def backfill(query: str, *, limit: int, dry_run: bool) -> dict[str, Any]:
    discovery = search_europe_pmc(query, limit=limit)
    documents = [
        document
        for record in discovery.get("results") or []
        if (document := _document(record, query=query)) is not None
    ]
    if dry_run:
        return {
            "query": query,
            "discovered": discovery.get("result_count", 0),
            "indexable": len(documents),
            "dry_run": True,
            "documents": [
                {
                    "source_object_id": item.source_object_id,
                    "title": item.title,
                    "verification_state": item.verification_state,
                    "display_policy": item.display_policy,
                }
                for item in documents
            ],
        }
    if not documents:
        return {
            "query": query,
            "discovered": discovery.get("result_count", 0),
            "indexable": 0,
            "dry_run": False,
            "index_run": None,
        }

    repository, service = semantic_index_routes._ensure_repository()
    preview = semantic_index_routes._write(
        lambda: service.preview(
            documents,
            configuration={
                "source": "Europe PMC",
                "query": query,
                "purpose": "Calyx literature coverage backfill",
            },
        )
    )
    run_id = preview["index_run_id"]
    execution = semantic_index_routes._write(lambda: service.execute(run_id))
    if hasattr(repository, "refresh_for_read"):
        repository.refresh_for_read()
    return {
        "query": query,
        "discovered": discovery.get("result_count", 0),
        "indexable": len(documents),
        "dry_run": False,
        "preview": preview,
        "execution": execution,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill orchid literature from Europe PMC into the Calyx semantic index. "
            "Imported records remain unverified/internal and require scientific review."
        )
    )
    parser.add_argument(
        "--query",
        action="append",
        required=True,
        help="Repeatable Europe PMC search query.",
    )
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    output = [
        backfill(query, limit=max(1, min(args.limit, 25)), dry_run=args.dry_run)
        for query in args.query
    ]
    print(json.dumps({"results": output}, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

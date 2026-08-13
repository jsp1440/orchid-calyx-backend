from __future__ import annotations

import hashlib
from typing import Any

from app.semantic_index import routes as semantic_index_routes
from app.semantic_index.models import IndexDocument


def _stable_id(value: str) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return int(digest[:15], 16)


def document_from_external_record(
    record: dict[str, Any], *, query: str
) -> IndexDocument | None:
    """Translate a discovered literature record into review-bound research evidence.

    This does not make the record canonical knowledge. It creates a bounded,
    exactly anchored semantic-index document that the Brain may inspect as
    unverified research evidence while preserving the review boundary.
    """

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
    anchor_id = _stable_id("europe-pmc-anchor:" + identifier + ":title-abstract")
    authors = str(record.get("authors") or "").strip()
    text = title + "\n\n" + abstract
    locator = {
        "source": "Europe PMC",
        "identifier": identifier,
        "section": "title_and_abstract",
        "doi": record.get("doi"),
        "pmid": record.get("pmid"),
        "pmcid": record.get("pmcid"),
    }
    return IndexDocument(
        source_object_type="LITERATURE_RECORD",
        source_object_id=source_object_id,
        revision_id=revision_id,
        extraction_run_id=extraction_run_id,
        text=text,
        collections=("LITERATURE", "ORCHID_SCIENCE", "GENERAL_BRAIN"),
        title=title,
        source_anchor_ids=(anchor_id,),
        document_class="SCIENTIFIC_LITERATURE",
        language="en",
        intended_consumers=("CALYX", "BRAIN", "RESEARCH_STATION"),
        temporal_status="CURRENT",
        verification_state="UNVERIFIED",
        review_state="CLEAR",
        internal_indexing_permission=True,
        display_policy="LIMITED_PREVIEW_ONLY",
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
            "display_policy": "LIMITED_PREVIEW_ONLY",
            "excerpt_limit": 900,
            "locator": locator,
            "anchor_locators": {str(anchor_id): locator},
            "scientific_review_required": True,
            "external_discovery_provider": "Europe PMC",
            "harvest_query": query,
            "matched_query": record.get("matched_query"),
            "relevance_score": record.get("relevance_score"),
            "peer_reviewed": "UNKNOWN",
            "evidence_type": "PRIMARY_OR_REVIEW_UNKNOWN",
            "claim_role": "CLAIM",
            "directness": "INDIRECT",
            "source_class": "SCIENTIFIC_LITERATURE",
            "ai_generated": "NO",
            "citations_verified": "NO",
            "review_state": "CLEAR",
            "verification_state": "UNVERIFIED",
            "temporal_status": "CURRENT",
            "provenance": {
                "provider": "Europe PMC",
                "identifier": identifier,
                "review_required": True,
            },
        },
    )


def ingest_external_literature_for_research(
    records: list[dict[str, Any]], *, query: str
) -> dict[str, Any]:
    """Index newly discovered abstracts for governed Brain research use.

    Stable identities make repeat discovery idempotent. Records remain unverified,
    limited-preview, review-required evidence and are never promoted to the
    Knowledge Graph by this operation.
    """

    documents = [
        document
        for record in records
        if (document := document_from_external_record(record, query=query)) is not None
    ]
    if not documents:
        return {
            "status": "nothing_indexable",
            "discovered": len(records),
            "indexable": 0,
            "indexed": 0,
            "review_required": True,
        }

    repository, service = semantic_index_routes._ensure_repository()
    if hasattr(repository, "refresh_for_read"):
        repository.refresh_for_read()
    elif hasattr(repository, "refresh"):
        repository.refresh()

    existing = {
        (str(item.get("source_object_type") or ""), item.get("revision_id"))
        for item in getattr(repository, "documents", [])
        if item.get("active", False)
    }
    new_documents = [
        item
        for item in documents
        if (item.source_object_type, item.revision_id) not in existing
    ]
    if not new_documents:
        return {
            "status": "already_indexed",
            "discovered": len(records),
            "indexable": len(documents),
            "indexed": 0,
            "review_required": True,
        }

    preview = semantic_index_routes._write(
        lambda: service.preview(
            new_documents,
            configuration={
                "source": "Europe PMC",
                "query": query,
                "purpose": "Calyx live research evidence bridge",
                "provenance_contract": "exact-anchor-limited-preview-v2",
                "automatic_publication": False,
                "knowledge_graph_mutation": False,
            },
        )
    )
    run_id = preview["index_run_id"]
    execution = semantic_index_routes._write(lambda: service.execute(run_id))
    if hasattr(repository, "refresh_for_read"):
        repository.refresh_for_read()
    elif hasattr(repository, "refresh"):
        repository.refresh()

    return {
        "status": "indexed_for_research",
        "discovered": len(records),
        "indexable": len(documents),
        "indexed": len(new_documents),
        "index_run_id": run_id,
        "execution_state": execution.get("state"),
        "review_required": True,
        "automatic_publication": False,
        "knowledge_graph_mutation": False,
    }

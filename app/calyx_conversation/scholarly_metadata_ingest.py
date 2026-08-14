from __future__ import annotations

import hashlib
from typing import Any

from app.semantic_index import routes as semantic_index_routes
from app.semantic_index.models import IndexDocument


def _stable_id(value: str) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return int(digest[:15], 16)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _first_text(value: Any) -> str:
    if isinstance(value, list):
        return _text(value[0]) if value else ""
    return _text(value)


def _authors(record: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for author in record.get("author") or []:
        if not isinstance(author, dict):
            continue
        given = _text(author.get("given"))
        family = _text(author.get("family"))
        name = " ".join(part for part in (given, family) if part).strip()
        if name:
            result.append(name)
    return result


def _publication_date(record: dict[str, Any]) -> str | None:
    for key in ("published-print", "published-online", "published", "issued", "created"):
        value = record.get(key)
        if not isinstance(value, dict):
            continue
        parts = value.get("date-parts")
        if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
            values = [str(item) for item in parts[0][:3]]
            return "-".join(values)
        if key == "created":
            date_time = _text(value.get("date-time"))
            if date_time:
                return date_time
    return None


def document_from_crossref_work(record: dict[str, Any], *, query: str) -> IndexDocument | None:
    title = _first_text(record.get("title"))
    doi = _text(record.get("DOI"))
    if not title:
        return None
    identifier = doi or _text(record.get("URL")) or title
    authors = _authors(record)
    container = _first_text(record.get("container-title"))
    publication_date = _publication_date(record)
    work_type = _text(record.get("type"))
    url = _text(record.get("URL"))
    subjects = [str(item).strip() for item in (record.get("subject") or []) if str(item).strip()]

    source_object_id = _stable_id("crossref:" + identifier.casefold())
    revision_id = _stable_id(
        "crossref-revision:" + identifier.casefold() + ":" + str(publication_date or "unknown")
    )
    extraction_run_id = _stable_id("crossref-query:" + query)
    anchor_id = _stable_id("crossref-anchor:" + identifier.casefold())

    text_parts = [title]
    if authors:
        text_parts.append("Authors: " + "; ".join(authors))
    if container:
        text_parts.append("Container: " + container)
    if publication_date:
        text_parts.append("Published: " + publication_date)
    if subjects:
        text_parts.append("Subjects: " + "; ".join(subjects[:12]))
    if doi:
        text_parts.append("DOI: " + doi)

    locator = {
        "source": "Crossref",
        "identifier": identifier,
        "doi": doi or None,
        "url": url or None,
    }

    return IndexDocument(
        source_object_type="SCHOLARLY_METADATA_RECORD",
        source_object_id=source_object_id,
        revision_id=revision_id,
        extraction_run_id=extraction_run_id,
        text="\n".join(text_parts),
        collections=("LITERATURE", "SCHOLARLY_METADATA", "GENERAL_BRAIN"),
        title=title,
        source_anchor_ids=(anchor_id,),
        document_class="SCIENTIFIC_LITERATURE_METADATA",
        language="en",
        intended_consumers=("CALYX", "BRAIN", "RESEARCH_STATION"),
        temporal_status="CURRENT",
        verification_state="UNVERIFIED",
        review_state="CLEAR",
        internal_indexing_permission=True,
        display_policy="METADATA_ONLY",
        metadata={
            "title": title,
            "document_title": title,
            "authors": authors,
            "container_title": container or None,
            "publication_date": publication_date,
            "source_type": "CROSSREF",
            "document_class": "SCIENTIFIC_LITERATURE_METADATA",
            "source_document_id": identifier,
            "doi": doi or None,
            "url": url or None,
            "work_type": work_type or None,
            "subjects": subjects,
            "reference_count": record.get("reference-count"),
            "is_referenced_by_count": record.get("is-referenced-by-count"),
            "collections": ["LITERATURE", "SCHOLARLY_METADATA", "GENERAL_BRAIN"],
            "display_policy": "METADATA_ONLY",
            "locator": locator,
            "anchor_locators": {str(anchor_id): locator},
            "scientific_review_required": True,
            "external_discovery_provider": "Crossref",
            "harvest_query": query,
            "peer_reviewed": "UNKNOWN",
            "evidence_type": "SCHOLARLY_METADATA",
            "ai_generated": "NO",
            "citations_verified": "NO",
            "review_state": "CLEAR",
            "verification_state": "UNVERIFIED",
            "automatic_publication": False,
            "knowledge_graph_mutation": False,
        },
    )


def ingest_crossref_works_for_research(
    records: list[dict[str, Any]], *, query: str
) -> dict[str, Any]:
    documents = [
        document
        for record in records
        if (document := document_from_crossref_work(record, query=query)) is not None
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
                "source": "Crossref",
                "query": query,
                "purpose": "Calyx scholarly metadata discovery and DOI reconciliation",
                "provenance_contract": "crossref-metadata-review-bound-v1",
                "automatic_publication": False,
                "knowledge_graph_mutation": False,
            },
        )
    )
    run_id = preview["index_run_id"]
    execution = semantic_index_routes._write(lambda: service.execute(run_id))
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

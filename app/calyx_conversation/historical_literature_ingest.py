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


def _authors(record: dict[str, Any]) -> list[str]:
    raw = record.get("Authors") or record.get("Author") or []
    if isinstance(raw, list):
        result: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                name = _text(item.get("Name") or item.get("FullName"))
            else:
                name = _text(item)
            if name:
                result.append(name)
        return result
    value = _text(raw)
    return [value] if value else []


def document_from_bhl_publication(
    record: dict[str, Any], *, query: str
) -> IndexDocument | None:
    title = _text(record.get("Title") or record.get("FullTitle") or record.get("ShortTitle"))
    if not title:
        return None

    item_id = _text(record.get("ItemID") or record.get("ItemId"))
    part_id = _text(record.get("PartID") or record.get("PartId"))
    title_id = _text(record.get("TitleID") or record.get("TitleId"))
    identifier = item_id or part_id or title_id or title
    object_type = "item" if item_id else "part" if part_id else "title"
    stable_url = _text(
        record.get("ItemUrl")
        or record.get("PartUrl")
        or record.get("TitleUrl")
        or record.get("Url")
    )
    publication = _text(
        record.get("PublicationDetails")
        or record.get("Publication")
        or record.get("PublisherName")
    )
    year = _text(record.get("Year") or record.get("Date"))
    found_in = _text(record.get("FoundIn"))
    authors = _authors(record)

    source_object_id = _stable_id("bhl:" + object_type + ":" + identifier)
    revision_id = _stable_id(
        "bhl-revision:" + object_type + ":" + identifier + ":" + year
    )
    extraction_run_id = _stable_id("bhl-query:" + query)
    anchor_id = _stable_id("bhl-anchor:" + object_type + ":" + identifier)

    text_parts = [title]
    if authors:
        text_parts.append("Authors: " + "; ".join(authors))
    if publication:
        text_parts.append("Publication: " + publication)
    if year:
        text_parts.append("Year: " + year)
    if found_in:
        text_parts.append("BHL match: " + found_in)
    text = "\n".join(text_parts)

    locator = {
        "source": "Biodiversity Heritage Library",
        "identifier": identifier,
        "object_type": object_type,
        "url": stable_url or None,
    }

    return IndexDocument(
        source_object_type="HISTORICAL_LITERATURE_RECORD",
        source_object_id=source_object_id,
        revision_id=revision_id,
        extraction_run_id=extraction_run_id,
        text=text,
        collections=("LITERATURE", "HISTORICAL_BOTANY", "GENERAL_BRAIN"),
        title=title,
        source_anchor_ids=(anchor_id,),
        document_class="HISTORICAL_BOTANICAL_LITERATURE",
        language="en",
        intended_consumers=("CALYX", "BRAIN", "RESEARCH_STATION"),
        temporal_status="HISTORICAL",
        verification_state="UNVERIFIED",
        review_state="CLEAR",
        internal_indexing_permission=True,
        display_policy="METADATA_ONLY",
        metadata={
            "title": title,
            "document_title": title,
            "authors": authors,
            "publication_date": year or None,
            "source_type": "BHL",
            "document_class": "HISTORICAL_BOTANICAL_LITERATURE",
            "source_document_id": identifier,
            "bhl_object_type": object_type,
            "bhl_item_id": item_id or None,
            "bhl_part_id": part_id or None,
            "bhl_title_id": title_id or None,
            "stable_url": stable_url or None,
            "found_in": found_in or None,
            "collections": ["LITERATURE", "HISTORICAL_BOTANY", "GENERAL_BRAIN"],
            "display_policy": "METADATA_ONLY",
            "locator": locator,
            "anchor_locators": {str(anchor_id): locator},
            "scientific_review_required": True,
            "external_discovery_provider": "Biodiversity Heritage Library",
            "harvest_query": query,
            "peer_reviewed": "NOT_APPLICABLE_OR_UNKNOWN",
            "evidence_type": "HISTORICAL_SOURCE",
            "ai_generated": "NO",
            "citations_verified": "NO",
            "review_state": "CLEAR",
            "verification_state": "UNVERIFIED",
            "temporal_status": "HISTORICAL",
            "automatic_publication": False,
            "knowledge_graph_mutation": False,
        },
    )


def ingest_bhl_publications_for_research(
    records: list[dict[str, Any]], *, query: str
) -> dict[str, Any]:
    documents = [
        document
        for record in records
        if (document := document_from_bhl_publication(record, query=query)) is not None
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
                "source": "Biodiversity Heritage Library",
                "query": query,
                "purpose": "Calyx historical botanical literature discovery",
                "provenance_contract": "bhl-metadata-review-bound-v1",
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

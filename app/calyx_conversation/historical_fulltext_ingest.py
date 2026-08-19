from __future__ import annotations

import hashlib
import re
from typing import Any

from app.semantic_index import routes as semantic_index_routes
from app.semantic_index.models import IndexDocument


def _stable_id(value: str) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return int(digest[:15], 16)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _query_terms(query: str) -> set[str]:
    stop = {"and", "or", "the", "of", "a", "an", "in", "on", "for", "with"}
    return {
        token.casefold()
        for token in re.findall(r"[A-Za-z][A-Za-z-]{2,}", query)
        if token.casefold() not in stop
    }


def _score_page(page: dict[str, Any], query: str) -> tuple[int, int]:
    ocr = _text(page.get("OcrText") or page.get("OCRText"))
    normalized = ocr.casefold()
    score = sum(normalized.count(term) for term in _query_terms(query))
    page_id = int(page.get("PageID") or page.get("PageId") or 0)
    return score, -page_id


def _page_document(
    page: dict[str, Any],
    *,
    item_id: str,
    item_title: str,
    query: str,
    item_url: str | None,
    rights: str | None,
    license_url: str | None,
) -> IndexDocument | None:
    ocr = _text(page.get("OcrText") or page.get("OCRText"))
    if len(ocr) < 80:
        return None

    page_id = _text(page.get("PageID") or page.get("PageId"))
    if not page_id:
        return None
    page_number = _text(page.get("PageNumber") or page.get("Number"))
    page_url = _text(page.get("PageUrl") or page.get("Url")) or None
    page_label = page_number or page_id
    title = f"{item_title} — page {page_label}" if item_title else f"BHL item {item_id} — page {page_label}"

    source_object_id = _stable_id(f"bhl-page:{page_id}")
    revision_id = _stable_id(f"bhl-page-revision:{page_id}:{hashlib.sha256(ocr.encode('utf-8')).hexdigest()}")
    extraction_run_id = _stable_id(f"bhl-ocr-query:{query}")
    anchor_id = _stable_id(f"bhl-page-anchor:{page_id}:ocr")
    locator = {
        "source": "Biodiversity Heritage Library",
        "item_id": item_id,
        "page_id": page_id,
        "page_number": page_number or None,
        "page_url": page_url,
        "item_url": item_url,
        "section": "page_ocr",
    }

    return IndexDocument(
        source_object_type="HISTORICAL_LITERATURE_PAGE",
        source_object_id=source_object_id,
        revision_id=revision_id,
        extraction_run_id=extraction_run_id,
        text=ocr,
        representation_type="VERBATIM",
        collections=("LITERATURE", "HISTORICAL_BOTANY", "GENERAL_BRAIN"),
        title=title,
        source_anchor_ids=(anchor_id,),
        document_class="HISTORICAL_BOTANICAL_FULLTEXT",
        language="en",
        intended_consumers=("CALYX", "BRAIN", "RESEARCH_STATION"),
        temporal_status="HISTORICAL",
        verification_state="UNVERIFIED",
        review_state="CLEAR",
        internal_indexing_permission=True,
        display_policy="LIMITED_PREVIEW_ONLY",
        metadata={
            "title": title,
            "document_title": item_title or title,
            "source_type": "BHL",
            "document_class": "HISTORICAL_BOTANICAL_FULLTEXT",
            "source_document_id": page_id,
            "bhl_item_id": item_id,
            "bhl_page_id": page_id,
            "page_number": page_number or None,
            "stable_url": page_url or item_url,
            "rights": rights,
            "license": license_url,
            "collections": ["LITERATURE", "HISTORICAL_BOTANY", "GENERAL_BRAIN"],
            "display_policy": "LIMITED_PREVIEW_ONLY",
            "excerpt_limit": 900,
            "locator": locator,
            "anchor_locators": {str(anchor_id): locator},
            "scientific_review_required": True,
            "external_discovery_provider": "Biodiversity Heritage Library",
            "harvest_query": query,
            "evidence_type": "HISTORICAL_PRIMARY_SOURCE",
            "representation_type": "VERBATIM",
            "ai_generated": "NO",
            "citations_verified": "NO",
            "review_state": "CLEAR",
            "verification_state": "UNVERIFIED",
            "temporal_status": "HISTORICAL",
            "automatic_publication": False,
            "knowledge_graph_mutation": False,
        },
    )


def documents_from_bhl_item_metadata(
    item: dict[str, Any], *, query: str, max_pages: int = 2
) -> list[IndexDocument]:
    item_id = _text(item.get("ItemID") or item.get("ItemId"))
    if not item_id:
        return []
    item_title = _text(item.get("Title") or item.get("FullTitle"))
    item_url = _text(item.get("ItemUrl") or item.get("Url")) or None
    rights = _text(item.get("Rights") or item.get("CopyrightStatus")) or None
    license_url = _text(item.get("LicenseUrl") or item.get("License")) or None
    pages = [page for page in (item.get("Pages") or []) if isinstance(page, dict)]
    pages = [page for page in pages if _text(page.get("OcrText") or page.get("OCRText"))]
    pages.sort(key=lambda page: _score_page(page, query), reverse=True)

    documents: list[IndexDocument] = []
    for page in pages[: max(1, min(int(max_pages), 5))]:
        document = _page_document(
            page,
            item_id=item_id,
            item_title=item_title,
            query=query,
            item_url=item_url,
            rights=rights,
            license_url=license_url,
        )
        if document is not None:
            documents.append(document)
    return documents


def ingest_bhl_item_fulltext_for_research(
    item: dict[str, Any], *, query: str, max_pages: int = 2
) -> dict[str, Any]:
    documents = documents_from_bhl_item_metadata(item, query=query, max_pages=max_pages)
    if not documents:
        return {
            "status": "nothing_indexable",
            "pages_examined": len(item.get("Pages") or []),
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
        (str(row.get("source_object_type") or ""), row.get("revision_id"))
        for row in getattr(repository, "documents", [])
        if row.get("active", False)
    }
    new_documents = [
        document
        for document in documents
        if (document.source_object_type, document.revision_id) not in existing
    ]
    if not new_documents:
        return {
            "status": "already_indexed",
            "pages_examined": len(item.get("Pages") or []),
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
                "purpose": "Calyx bounded historical botanical OCR acquisition",
                "provenance_contract": "bhl-page-ocr-exact-anchor-v1",
                "automatic_publication": False,
                "knowledge_graph_mutation": False,
            },
        )
    )
    run_id = preview["index_run_id"]
    execution = semantic_index_routes._write(lambda: service.execute(run_id))
    return {
        "status": "indexed_for_research",
        "pages_examined": len(item.get("Pages") or []),
        "indexable": len(documents),
        "indexed": len(new_documents),
        "index_run_id": run_id,
        "execution_state": execution.get("state"),
        "review_required": True,
        "automatic_publication": False,
        "knowledge_graph_mutation": False,
    }

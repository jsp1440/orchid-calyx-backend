from __future__ import annotations

import hashlib
from typing import Any

from app.semantic_index import routes as semantic_index_routes
from app.semantic_index.models import IndexDocument


def _stable_id(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:15], 16)


def _text(record: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            text = str(value).strip()
            if text:
                return text
    return ""


def document_from_globi_interaction(
    record: dict[str, Any],
    *,
    query_role: str,
    provider_stability: str = "LIVE_EXPLORATORY_API",
    dataset_version: str | None = None,
) -> IndexDocument | None:
    """Build a review-bound interaction-discovery document from one GloBI record.

    Accepts both the live Web API's field names (``source_taxon_name``,
    ``interaction_type``, ...) and the versioned stable dataset export's
    field names (``sourceTaxonName``, ``interactionTypeName``,
    ``referenceCitation``, ...), since both are legitimate GloBI record
    shapes this function may be called with.
    """
    source_name = _text(record, "source_taxon_name", "sourceTaxonName", "source_name")
    target_name = _text(record, "target_taxon_name", "targetTaxonName", "target_name")
    interaction_type = _text(
        record, "interaction_type", "interactionType", "interaction_type_name", "interactionTypeName"
    )
    if not source_name or not target_name or not interaction_type:
        return None

    source_id = _text(record, "source_taxon_external_id", "sourceTaxonId", "source_taxon_id")
    target_id = _text(record, "target_taxon_external_id", "targetTaxonId", "target_taxon_id")
    study_id = _text(
        record, "study_external_id", "studyExternalId", "study_url", "studyUrl", "referenceDoi", "referenceUrl"
    )
    study_citation = _text(record, "study_citation", "studyCitation", "referenceCitation")
    source_citation = _text(
        record, "study_source_citation", "studySourceCitation", "source_citation", "sourceCitation"
    )
    identity = "|".join(
        [source_id or source_name.casefold(), interaction_type.casefold(), target_id or target_name.casefold(), study_id or study_citation.casefold()]
    )
    source_object_id = _stable_id("globi-interaction:" + identity)
    revision_id = _stable_id("globi-interaction-revision:" + identity)
    extraction_run_id = _stable_id("globi-discovery-role:" + query_role)
    anchor_id = _stable_id("globi-anchor:" + identity)
    statement = f"{source_name} {interaction_type} {target_name}."
    if study_citation:
        statement += " Study: " + study_citation
    if source_citation and source_citation != study_citation:
        statement += " Dataset: " + source_citation

    locator = {
        "source": "Global Biotic Interactions",
        "study_external_id": study_id or None,
        "source_taxon_id": source_id or None,
        "target_taxon_id": target_id or None,
        "interaction_type": interaction_type,
    }

    return IndexDocument(
        source_object_type="INTERACTION_DISCOVERY_RECORD",
        source_object_id=source_object_id,
        revision_id=revision_id,
        extraction_run_id=extraction_run_id,
        text=statement,
        collections=("INTERACTIONS", "ECOLOGY", "LITERATURE", "GENERAL_BRAIN"),
        title=f"{source_name} — {interaction_type} — {target_name}",
        source_anchor_ids=(anchor_id,),
        document_class="ECOLOGICAL_INTERACTION_DISCOVERY",
        language="en",
        intended_consumers=("CALYX", "BRAIN", "RESEARCH_STATION"),
        temporal_status="CURRENT",
        verification_state="UNVERIFIED",
        review_state="CLEAR",
        internal_indexing_permission=True,
        display_policy="METADATA_ONLY",
        metadata={
            "source_type": "GLOBI",
            "document_class": "ECOLOGICAL_INTERACTION_DISCOVERY",
            "source_taxon_name": source_name,
            "source_taxon_id": source_id or None,
            "target_taxon_name": target_name,
            "target_taxon_id": target_id or None,
            "interaction_type": interaction_type,
            "study_external_id": study_id or None,
            "study_citation": study_citation or None,
            "study_source_citation": source_citation or None,
            "query_role": query_role,
            "locator": locator,
            "anchor_locators": {str(anchor_id): locator},
            "external_discovery_provider": "Global Biotic Interactions",
            "provider_stability": provider_stability,
            "dataset_version": dataset_version,
            "stable_research_snapshot_preferred": provider_stability != "VERSIONED_STABLE_DATASET",
            "scientific_review_required": True,
            "evidence_type": "ECOLOGICAL_INTERACTION_CANDIDATE",
            "automatic_publication": False,
            "knowledge_graph_mutation": False,
        },
    )


def _ingest_globi_documents(
    documents: list[IndexDocument],
    *,
    discovered: int,
    configuration: dict[str, Any],
) -> dict[str, Any]:
    if not documents:
        return {
            "status": "nothing_indexable",
            "discovered": discovered,
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
            "discovered": discovered,
            "indexable": len(documents),
            "indexed": 0,
            "review_required": True,
        }

    preview = semantic_index_routes._write(
        lambda: service.preview(new_documents, configuration=configuration)
    )
    run_id = preview["index_run_id"]
    execution = semantic_index_routes._write(lambda: service.execute(run_id))
    return {
        "status": "indexed_for_research",
        "discovered": discovered,
        "indexable": len(documents),
        "indexed": len(new_documents),
        "index_run_id": run_id,
        "execution_state": execution.get("state"),
        "review_required": True,
        "automatic_publication": False,
        "knowledge_graph_mutation": False,
    }


def ingest_globi_interactions_for_research(
    records: list[dict[str, Any]], *, query_role: str
) -> dict[str, Any]:
    documents = [
        document
        for record in records
        if (document := document_from_globi_interaction(record, query_role=query_role)) is not None
    ]
    return _ingest_globi_documents(
        documents,
        discovered=len(records),
        configuration={
            "source": "Global Biotic Interactions",
            "purpose": "Orchid interaction discovery candidate intake",
            "query_role": query_role,
            "provenance_contract": "globi-live-discovery-review-bound-v1",
            "automatic_publication": False,
            "knowledge_graph_mutation": False,
        },
    )


def ingest_globi_interactions_for_canonical_dataset(
    records: list[dict[str, Any]], *, dataset_version: str
) -> dict[str, Any]:
    """Ingest rows already read from GloBI's versioned stable dataset export.

    Unlike :func:`ingest_globi_interactions_for_research`, this is intended
    for an operator-triggered, reproducible bulk backfill from a downloaded
    dataset snapshot rather than the periodic live-API sampling lane. Every
    resulting document is still review-bound: it never publishes to the
    knowledge graph or mutates canonical data by itself.
    """
    documents = [
        document
        for record in records
        if (
            document := document_from_globi_interaction(
                record,
                query_role="canonical_dataset",
                provider_stability="VERSIONED_STABLE_DATASET",
                dataset_version=dataset_version,
            )
        )
        is not None
    ]
    return _ingest_globi_documents(
        documents,
        discovered=len(records),
        configuration={
            "source": "Global Biotic Interactions",
            "purpose": "Orchid interaction discovery reproducible bulk backfill",
            "dataset_version": dataset_version,
            "provenance_contract": "globi-canonical-dataset-review-bound-v1",
            "automatic_publication": False,
            "knowledge_graph_mutation": False,
        },
    )

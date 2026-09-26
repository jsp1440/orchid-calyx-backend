"""Read-only discovery surface over review-bound ecological interaction candidates.

``runtime.globi_canonical_harvester`` and the live-API lane in
``runtime.interaction_harvester`` both write GloBI-sourced interaction
records into the semantic index as review-bound ``INTERACTION_DISCOVERY_RECORD``
documents (``verification_state="UNVERIFIED"``, ``knowledge_graph_mutation:
False`` -- see ``app.calyx_conversation.interaction_discovery_ingest``). Until
this module, nothing read that data back out: it was ingested and then
invisible. This is the first real consumer -- it lets species profiles, the
Knowledge Graph readiness audit, and research interfaces find the interaction
candidates that already exist.

Nothing here writes to the Knowledge Graph, mutates any document, or changes
a verification_state. Promoting a reviewed candidate into a verified graph
edge (``oc_graph.kg_edges``) is a separate, owner-reviewed decision this
module does not make -- consistent with every other review-bound domain in
this codebase (candidate_knowledge, evidence_aggregation).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import ValidationError

from app.interaction_discovery.models import InteractionDiscoveryRecord
from app.semantic_index.repository_runtime import get_repository_runtime
from app.semantic_index.routes import get_repository_for_read

INTERACTION_DISCOVERY_TYPE = "INTERACTION_DISCOVERY_RECORD"

IndexState = Literal["durable", "memory_unprovisioned"]

# Durable index configured but unreachable is already a 503 raised by
# SemanticIndexRepositoryRuntime.read() (SEMANTIC_INDEX_DATABASE_UNAVAILABLE),
# so a 200 from this surface only ever comes from one of these two states.
# The unprovisioned state keeps ``status: ok`` for backward compatibility but
# must never be read as "no interactions are known".
UNPROVISIONED_INDEX_NOTE = (
    "No durable interaction index is configured; this result was served from an "
    "empty-by-default in-process index. An empty result is not evidence that no "
    "interactions are known."
)

# Best-effort keyword heuristic over the source-supplied ``interaction_type``
# text, used only to group results for convenience (category=pollinator /
# category=mycorrhizal query filters below). This is NOT a claim that these
# are GloBI's exact controlled-vocabulary terms -- the raw, unmodified
# interaction_type is always included in every result, so a heuristic miss
# never hides or misrepresents the underlying evidence.
POLLINATOR_KEYWORDS = ("pollinat", "visitsflower", "flowervisit")
MYCORRHIZAL_KEYWORDS = ("mycorrhiz", "fungal", "fungus", "symbiont", "mutualist", "hashost", "hostof")

Category = Literal["pollinator", "mycorrhizal", "all"]


def _matches_category(interaction_type: str, category: Category) -> bool:
    if category == "all":
        return True
    normalized = interaction_type.casefold().replace(" ", "").replace("_", "")
    keywords = POLLINATOR_KEYWORDS if category == "pollinator" else MYCORRHIZAL_KEYWORDS
    return any(keyword in normalized for keyword in keywords)


def _classify(interaction_type: str) -> list[str]:
    matched = []
    if _matches_category(interaction_type, "pollinator"):
        matched.append("pollinator")
    if _matches_category(interaction_type, "mycorrhizal"):
        matched.append("mycorrhizal")
    return matched


def _record_from_document(document: dict[str, Any]) -> dict[str, Any] | None:
    metadata = document.get("metadata") or {}
    if metadata.get("source_type") != "GLOBI":
        return None
    interaction_type = str(metadata.get("interaction_type") or "")
    if not interaction_type:
        return None
    return {
        "source_taxon_name": metadata.get("source_taxon_name"),
        "source_taxon_id": metadata.get("source_taxon_id"),
        "target_taxon_name": metadata.get("target_taxon_name"),
        "target_taxon_id": metadata.get("target_taxon_id"),
        "interaction_type": interaction_type,
        "categories": _classify(interaction_type),
        "study_citation": metadata.get("study_citation"),
        "study_source_citation": metadata.get("study_source_citation"),
        "study_external_id": metadata.get("study_external_id"),
        "provider": metadata.get("external_discovery_provider"),
        "provider_stability": metadata.get("provider_stability"),
        "dataset_version": metadata.get("dataset_version"),
        # verification_state isn't persisted as a stored column on this
        # repository's document rows (see MemoryIndexRepository); every
        # document this ingest path produces is UNVERIFIED by construction
        # (app.calyx_conversation.interaction_discovery_ingest never sets
        # anything else), and nothing in this module promotes one, so the
        # fixed value here is accurate rather than assumed.
        "verification_state": "UNVERIFIED",
        "knowledge_graph_mutation": False,
        "revision_id": document.get("revision_id"),
        # revision_id is a 60-bit stable hash (see interaction_discovery_ingest
        # ._stable_id), larger than JavaScript's Number.MAX_SAFE_INTEGER; the
        # string form lets browser clients hold it exactly.
        "revision_id_str": None if document.get("revision_id") is None else str(document.get("revision_id")),
        "locator": metadata.get("locator"),
    }


def _readable_record(record: dict[str, Any]) -> dict[str, Any] | None:
    """Validate one record against the published record contract.

    Stored metadata is not schema-enforced, so a single record can carry a
    value the contract cannot represent (e.g. a dict ``study_citation``). Such
    a record is returned as ``None`` so the caller excludes and counts it,
    instead of the response model rejecting the entire list with a 500.
    """
    try:
        return InteractionDiscoveryRecord.model_validate(record).model_dump()
    except ValidationError:
        return None


def _taxon_matches(record: dict[str, Any], taxon: str) -> bool:
    needle = taxon.casefold().strip()
    source = str(record.get("source_taxon_name") or "").casefold()
    target = str(record.get("target_taxon_name") or "").casefold()
    return needle in source or needle in target


def _index_state(repository: Any) -> IndexState:
    """Derive availability from the repository actually serving this read.

    Mirrors SemanticIndexRepositoryRuntime.status(): durable means a database
    URL is configured and the active repository is the transactional
    (``atomic``) Postgres-backed one. Anything else is the in-process memory
    fallback used when no durable index is provisioned.
    """
    runtime = get_repository_runtime()
    if runtime.durable_mode_configured and hasattr(repository, "atomic"):
        return "durable"
    return "memory_unprovisioned"


def discover_interactions(
    *,
    taxon: str | None = None,
    category: Category = "all",
    limit: int = 100,
) -> dict[str, Any]:
    """Query review-bound GloBI interaction-discovery candidates.

    ``taxon`` filters on a case-insensitive substring match against either
    the source or target taxon name (either side may be the orchid, since
    GloBI records interactions directionally and this repository doesn't
    re-derive which side is the orchid). ``category`` narrows to
    ``pollinator`` or ``mycorrhizal`` using the keyword heuristic above, or
    ``all`` for no narrowing.
    """
    repository = get_repository_for_read()
    index_state = _index_state(repository)
    documents = [doc for doc in repository.documents if doc.get("active") and doc.get("source_object_type") == INTERACTION_DISCOVERY_TYPE]

    records: list[dict[str, Any]] = []
    unreadable_count = 0
    for document in documents:
        record = _record_from_document(document)
        if record is None:
            continue
        if category != "all" and category not in record["categories"]:
            continue
        if taxon and not _taxon_matches(record, taxon):
            continue
        readable = _readable_record(record)
        if readable is None:
            unreadable_count += 1
            continue
        records.append(readable)

    records.sort(key=lambda item: (item["source_taxon_name"] or "", item["target_taxon_name"] or ""))
    truncated = len(records) > limit
    return {
        "status": "ok",
        "count": min(len(records), limit),
        "total_matched": len(records),
        "truncated": truncated,
        "category": category,
        "taxon_filter": taxon,
        "index_state": index_state,
        "index_note": UNPROVISIONED_INDEX_NOTE if index_state == "memory_unprovisioned" else None,
        # Matched records excluded because they failed record validation; they
        # are not in count/total_matched, so non-zero means an incomplete result.
        "unreadable_count": unreadable_count,
        "review_bound": True,
        "knowledge_graph_mutation": False,
        "note": (
            "These are unverified candidate ecological interactions discovered from "
            "Global Biotic Interactions (GloBI), not verified Knowledge Graph edges. "
            "Each record carries its source study citation and dataset provenance; "
            "promotion to a verified graph edge requires separate scientific review."
        ),
        "interactions": records[:limit],
    }

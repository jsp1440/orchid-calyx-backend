"""Read-only inventory of existing scientific holdings before acquisition.

Absent optional relations are reported explicitly. Unreadable/truncated stores,
missing core stores, and relevant holdings without reusable text close the paid
acquisition gate. This module never registers a source or publishes evidence.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from psycopg import sql

from app.persistence.state_repository import decode

CORE = (
    "oc_sources.document_inventory", "oc_import.document_revisions", "oc_import.hash_index",
    "oc_document_intelligence.records", "oc_document_intelligence.extraction_runs",
    "oc_document_intelligence.literature_source_bindings",
    "oc_candidate_knowledge.runtime_repository_snapshots",
)
OPTIONAL = (
    "public.research_documents", "oc_literature.papers", "oc_literature.documents",
    "oc_literature.literature_documents", "public.literature_documents",
    "oc_candidate_knowledge.candidates", "oc_candidate_knowledge.aggregate_versions",
    "oc_graph.taxon_literature_edges", "oc_graph.kg_edges", "oc_graph.kg_nodes",
    "public.trait_assertions", "public.trait_candidates", "public.trait_observations",
    "oc_traits.trait_assertions", "oc_views.trait_resolved_v4", "public.oc_trait_consensus_normalized",
)
DOCUMENT_RELATIONS = frozenset(OPTIONAL[:5])
EVIDENCE_RELATIONS = (
    "oc_candidate_knowledge.candidates", "oc_candidate_knowledge.aggregate_versions",
    "oc_graph.kg_edges", "oc_graph.kg_nodes", "oc_graph.taxon_literature_edges",
    "public.trait_assertions", "public.trait_candidates", "public.trait_observations",
    "oc_traits.trait_assertions", "oc_views.trait_resolved_v4",
)
TEXT_KEYS = ("full_text", "text", "content", "body", "abstract", "extracted_text", "normalized_text")
TAXON_KEYS = ("scientific_name", "taxon_name", "taxon_names", "taxa", "genus", "species", "taxonomic_coverage", "subjects")


def _relation(name):
    return sql.Identifier(*name.split("."))


def _identity(row):
    metadata = row.get("metadata") or row.get("provenance") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    def field(*names):
        return next((row.get(key) or metadata.get(key) for key in names if row.get(key) or metadata.get(key)), None)
    return {"doi": field("doi"), "title": field("title", "filename"),
            "authors": field("authors", "author"), "year": field("year", "publication_year"),
            "source_url": field("source_url", "url", "origin_url", "drive_url", "canonical_url", "external_file_id"),
            "content_hash": field("sha256", "checksum", "content_hash")}


def _relevance(row, genus, names):
    metadata = row.get("metadata") or row.get("provenance") or {}
    taxonomic = [row.get(key) for key in TAXON_KEYS]
    if isinstance(metadata, dict):
        taxonomic.extend(metadata.get(key) for key in TAXON_KEYS)
    text = "\n".join(str(row.get(key) or "") for key in TEXT_KEYS)
    text += "\n" + json.dumps(taxonomic)
    # Titles/filenames alone are discovery hints, never proof of coverage.
    matches = [name for name in names if re.search(r"(?<![A-Za-z])" + re.escape(name) + r"(?![A-Za-z-])", text, re.IGNORECASE)]
    return matches, bool(matches or re.search(r"(?<![A-Za-z])" + re.escape(genus) + r"(?![A-Za-z-])", text, re.IGNORECASE))


def _relevance_assessable(row):
    metadata = row.get("metadata") or row.get("provenance") or {}
    if any(row.get(key) for key in TEXT_KEYS + TAXON_KEYS):
        return True
    return isinstance(metadata, dict) and any(metadata.get(key) for key in TAXON_KEYS)


def _genre(row):
    value = " ".join(str(row.get(key) or "") for key in ("document_type", "genre", "type", "title", "filename")).lower()
    return next((genre for genre in ("monograph", "revision", "flora", "key") if re.search(r"\b" + genre + r"s?\b", value)), "unknown")


def audit_existing_corpus(connect, *, genus: str, taxon_names=(), max_rows=25000, max_text_bytes=2000000):
    """Inspect every known corpus, never first-match-mask a larger holding."""
    if not re.fullmatch(r"[A-Z][a-z]{2,40}", genus) or not 1 <= max_rows <= 100000:
        raise ValueError("INVALID_CORPUS_AUDIT_SCOPE")
    if not 1 <= max_text_bytes <= 10000000:
        raise ValueError("INVALID_CORPUS_TEXT_BOUND")
    names = tuple(taxon_names)
    if any(not isinstance(name, str) or not name.startswith(genus + " ") for name in names):
        raise ValueError("INVALID_CORPUS_TAXON_SCOPE")
    report: dict[str, Any] = {"schema": "oc.existing-corpus-audit.v1", "available": False,
                             "complete": False, "audit_complete": False, "genus": genus, "relations": {},
                             "documents": [], "identities": [], "blockers": [],
                             "scientific_publication": False}
    rows_by_table = {}
    taxonomy_ids = set()
    pending_candidate_subjects = set()
    try:
        with connect() as connection, connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '30s'")
            cursor.execute("SELECT to_regclass('public.orchid_taxonomy')")
            if cursor.fetchone()[0] is not None:
                cursor.execute("SELECT id FROM public.orchid_taxonomy WHERE scientific_name LIKE %s", (genus + " %",))
                taxonomy_ids = {str(row[0]) for row in cursor.fetchall()}
            for table in CORE + OPTIONAL:
                cursor.execute("SELECT to_regclass(%s)", (table,))
                if cursor.fetchone()[0] is None:
                    report["relations"][table] = {"state": "absent", "count": None}
                    if table in CORE:
                        report["blockers"].append("CORE_RELATION_ABSENT:" + table)
                    continue
                cursor.execute(sql.SQL("SELECT count(*) FROM {} ").format(_relation(table)))
                count = cursor.fetchone()[0]
                report["relations"][table] = {"state": "available", "count": count}
                needs_rows = table in DOCUMENT_RELATIONS or table in CORE[:2] or table in CORE[3:6] or table == "public.oc_trait_consensus_normalized"
                if needs_rows and count > max_rows:
                    report["relations"][table]["state"] = "bounded_incomplete"
                    report["blockers"].append("CORPUS_ROW_BOUND:" + table)
                    continue
                if needs_rows:
                    cursor.execute(sql.SQL("SELECT to_jsonb(t) - 'content_bytes' FROM {} t").format(_relation(table)))
                    rows_by_table[table] = [row[0] for row in cursor.fetchall()]
            for table in EVIDENCE_RELATIONS:
                if report["relations"].get(table, {}).get("state") != "available":
                    continue
                patterns = ["%" + genus + "%"] + ['%"taxon:' + ident + '"%' for ident in taxonomy_ids]
                cursor.execute(sql.SQL("SELECT to_jsonb(t) FROM {} t WHERE to_jsonb(t)::text ILIKE ANY(%s) OR to_jsonb(t)->>'taxonomy_id' = ANY(%s) OR to_jsonb(t)->>'taxon_id' = ANY(%s) LIMIT %s").format(_relation(table)), (patterns, list(taxonomy_ids), list(taxonomy_ids), max_rows + 1))
                relevant_rows = [row[0] for row in cursor.fetchall()]
                if len(relevant_rows) > max_rows:
                    report["blockers"].append("CORPUS_ROW_BOUND:" + table)
                rows_by_table[table] = relevant_rows[:max_rows]
            report["persistent_evidence"] = {}
            morphology_taxa = set()
            snapshot_candidates = []
            aggregated_candidate_ids = set()
            if report["relations"].get(CORE[6], {}).get("state") == "available":
                cursor.execute("SELECT repository_kind, state FROM oc_candidate_knowledge.runtime_repository_snapshots WHERE repository_kind IN ('candidate_knowledge','evidence_aggregation')")
                for kind, payload in cursor.fetchall():
                    state = decode(payload)
                    if kind == "candidate_knowledge":
                        snapshot_candidates = state.get("candidates", [])
                    if kind == "evidence_aggregation":
                        for run_id, items in state.get("items", {}).items():
                            if state.get("runs", {}).get(run_id, {}).get("state") != "COMPLETED":
                                continue
                            for item in items:
                                for candidate in item.get("candidates", []):
                                    aggregated_candidate_ids.add(candidate.candidate_id)
                                    if candidate.source_anchor_ids and candidate.document_hash and re.fullmatch(r"(?:leaf|flower|petal|sepal|lip)_(?:length|width)", candidate.predicate):
                                        morphology_taxa.add(candidate.normalized_subject)
                    report["persistent_evidence"][kind] = {
                        "candidate_count": len(state.get("candidates", [])),
                        "aggregate_version_count": len(state.get("versions", [])),
                        "evidence_link_count": len(state.get("evidence_links", [])),
                        "run_count": len(state.get("runs", {})),
                    }
            for candidate in snapshot_candidates:
                subject = str(candidate.get("normalized_subject") or "")
                relevant = genus.lower() in subject.lower() or any(subject == "local:orchid_taxonomy:" + ident for ident in taxonomy_ids)
                if candidate.get("candidate_id") not in aggregated_candidate_ids:
                    if relevant:
                        pending_candidate_subjects.add(subject)
                    elif not subject.startswith("local:orchid_taxonomy:") and not re.fullmatch(r"[A-Z][a-z]+ [a-z-]+", subject):
                        report["blockers"].append("CORPUS_RELEVANCE_UNDETERMINED:candidate_identity")
            # Original bytes are used only in memory and never returned by audit.
            if "oc_import.document_revisions" in rows_by_table:
                cursor.execute("SELECT revision_id, content_bytes FROM oc_import.document_revisions WHERE byte_count <= %s", (max_text_bytes,))
                contents = {}
                for ident, raw in cursor.fetchall():
                    try:
                        contents[ident] = bytes(raw).decode("utf-8")
                    except UnicodeDecodeError:
                        pass
            else:
                contents = {}
        report["available"] = True
    except Exception as exc:  # noqa: BLE001 - an incomplete audit must close acquisition
        report["blockers"].append("CORPUS_AUDIT_UNAVAILABLE:" + type(exc).__name__)
        return report
    inventory = {row["inventory_id"]: row for row in rows_by_table.get(CORE[0], [])}
    bindings = {}
    for row in rows_by_table.get(CORE[5], []):
        bindings.setdefault(row["revision_id"], []).append(row)
    records = {row["record_id"]: row for row in rows_by_table.get(CORE[3], [])}
    normalized = {}
    for run in rows_by_table.get(CORE[4], []):
        record = records.get(run["record_id"], {})
        if run.get("state") in {"COMPLETED", "READY_FOR_REVIEW", "PARTIAL"}:
            normalized[record.get("revision_id")] = run.get("normalized_text") or ""
    for row in rows_by_table.get(CORE[1], []):
        ident = row["revision_id"]
        inventory_row = inventory.get(row["registry_id"], {})
        merged = {**inventory_row, **row}
        merged["provenance"] = {**(inventory_row.get("provenance") or {}), **(row.get("provenance") or {})}
        merged["full_text"] = contents.get(ident, "") or normalized.get(ident, "")
        identity = _identity(merged)
        report["identities"].append({**identity, "revision_id": ident, "registry_id": row["registry_id"]})
        matches, relevant = _relevance(merged, genus, names)
        if not _relevance_assessable(merged):
            report["blockers"].append("CORPUS_RELEVANCE_UNDETERMINED:revision:" + str(ident))
        if not relevant:
            continue
        raw_text = contents.get(ident)
        loadable = raw_text is not None and hashlib.sha256(raw_text.encode()).hexdigest() == row["sha256"].strip()
        document = {**identity, "revision_id": ident, "registry_id": row["registry_id"],
                    "matched_names": matches, "genre": _genre(merged), "loadable": loadable,
                    "processed": bool(bindings.get(ident)), "binding_ids": [b["binding_id"] for b in bindings.get(ident, [])],
                    "mocked": bool((row.get("provenance") or {}).get("mocked") or (inventory_row.get("provenance") or {}).get("mocked"))}
        report["documents"].append(document)
        if not loadable and not document["processed"]:
            report["blockers"].append("RELEVANT_SOURCE_REQUIRES_EXISTING_IMPORT_OR_EXTRACTION:" + str(ident))
    imported_registry_ids = {row["registry_id"] for row in rows_by_table.get(CORE[1], [])}
    for row in inventory.values():
        if row["inventory_id"] in imported_registry_ids:
            continue
        identity = _identity(row)
        report["identities"].append({**identity, "registry_id": row["inventory_id"]})
        matches, relevant = _relevance(row, genus, names)
        if not _relevance_assessable(row):
            report["blockers"].append("CORPUS_RELEVANCE_UNDETERMINED:inventory:" + str(row["inventory_id"]))
        if relevant:
            report["documents"].append({**identity, "registry_id": row["inventory_id"],
                                        "matched_names": matches, "genre": _genre(row),
                                        "loadable": False, "processed": False})
            report["blockers"].append("RELEVANT_REGISTERED_SOURCE_REQUIRES_EXISTING_IMPORT:" + str(row["inventory_id"]))
    held_hashes = {entry.get("content_hash") for entry in report["documents"]
                   if entry.get("revision_id") and (entry.get("loadable") or entry.get("processed"))}
    for table in DOCUMENT_RELATIONS:
        for row in rows_by_table.get(table, []):
            identity = _identity(row)
            report["identities"].append({**identity, "relation": table})
            matches, relevant = _relevance(row, genus, names)
            if not _relevance_assessable(row):
                report["blockers"].append("CORPUS_RELEVANCE_UNDETERMINED:" + table)
            if relevant and identity.get("content_hash") not in held_hashes:
                report["documents"].append({**identity, "relation": table, "matched_names": matches,
                                            "genre": _genre(row), "loadable": False, "processed": False})
                report["blockers"].append("RELEVANT_LEGACY_SOURCE_REQUIRES_CANONICAL_IMPORT:" + table)
    report["audit_complete"] = not any(blocker.startswith(("CORE_RELATION_ABSENT:", "CORPUS_ROW_BOUND:", "CORPUS_AUDIT_UNAVAILABLE:")) for blocker in report["blockers"])
    if pending_candidate_subjects:
        report["blockers"].append("RELEVANT_EXISTING_CANDIDATES_REQUIRE_CANONICAL_HANDOFF")
    report["existing_evidence_reuse"] = {"unaggregated_candidate_subjects": len(pending_candidate_subjects)}
    for table in EVIDENCE_RELATIONS:
        rows = rows_by_table.get(table, [])
        if table == "oc_graph.kg_nodes":
            rows = [row for row in rows if str(row.get("node_type") or "").lower() not in {"taxon", "taxonomy", "species", "genus"}]
        if rows:
            report["existing_evidence_reuse"][table] = len(rows)
            report["blockers"].append("RELEVANT_EXISTING_EVIDENCE_REQUIRES_PROVENANCE_RECONCILIATION:" + table)
    trait_rows = rows_by_table.get("public.oc_trait_consensus_normalized")
    trait_taxa = set()
    trait_unmapped = 0
    trait_literature_missing = 0
    if trait_rows is not None:
        for row in trait_rows:
            taxon = next((row.get(key) for key in ("taxonomy_id", "taxon_id", "scientific_name", "canonical_name") if row.get(key) is not None), None)
            row_relevant = str(taxon) in taxonomy_ids or (isinstance(taxon, str) and taxon.startswith(genus + " "))
            if row_relevant:
                report["blockers"].append("RELEVANT_TRAIT_EVIDENCE_REQUIRES_PROVENANCE_RECONCILIATION")
            elif taxon is None:
                report["blockers"].append("CORPUS_RELEVANCE_UNDETERMINED:trait_consensus")
            value = next((row.get(key) for key in ("trait_value", "consensus_value", "value") if row.get(key) is not None), None)
            if taxon is None or value is None:
                trait_unmapped += 1
            else:
                trait_taxa.add(str(taxon))
            if not any(row.get(key) for key in ("source_id", "source_ids", "source_url", "doi", "document_id", "revision_id", "provenance", "source_references")):
                trait_literature_missing += 1
    revisions = rows_by_table.get(CORE[1], [])
    hashes = {}
    for row in revisions:
        hashes.setdefault(row["sha256"], set()).add(row["revision_id"])
    report["blockers"] = sorted(set(report["blockers"]))
    report["summary_counts"] = {
        "bound_document_revisions": len(bindings),
        "extracted_document_revisions": len({ident for ident, text in normalized.items() if ident is not None and text}),
        "unextracted_document_revisions": sum(not normalized.get(row["revision_id"]) for row in revisions),
        "taxa_with_anchored_numeric_morphology_candidates": len(morphology_taxa),
        "matrix_ready_taxa": None,
        "matrix_ready_taxa_status": "not_inferred_from_review_pending_candidates",
        "trait_consensus_taxa_with_values": len(trait_taxa) if trait_rows is not None and not trait_unmapped else None,
        "trait_consensus_unmapped_rows": trait_unmapped if trait_rows is not None else None,
        "trait_rows_without_observable_source_reference": trait_literature_missing if trait_rows is not None else None,
        "literature_missing_taxa": None,
        "literature_missing_taxa_status": "requires_explicit_predicate_coverage_and_complete_corpus_audit",
        "duplicate_content_hash_groups": sum(len(ids) > 1 for ids in hashes.values()),
    }
    report["complete"] = not report["blockers"]
    report["relevant_documents"] = len(report["documents"])
    report["unprocessed_documents"] = sum(not row["processed"] for row in report["documents"])
    return report


def load_corpus_document(connect, document):
    """Read exact original text, preserving its existing content identity."""
    if not document.get("loadable") or not document.get("revision_id"):
        raise ValueError("EXISTING_CORPUS_DOCUMENT_NOT_LOADABLE")
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT content_bytes, sha256 FROM oc_import.document_revisions WHERE revision_id=%s", (document["revision_id"],))
        row = cursor.fetchone()
    if row is None or hashlib.sha256(bytes(row[0])).hexdigest() != str(row[1]).strip() or str(row[1]).strip() != document["content_hash"]:
        raise ValueError("EXISTING_CORPUS_IDENTITY_MISMATCH")
    return bytes(row[0]).decode("utf-8")

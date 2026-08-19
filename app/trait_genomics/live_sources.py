from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg import sql

from .models import DiscoveryDataset, EvidenceKind, EvidenceRecord


@dataclass(frozen=True)
class SourceCandidate:
    domain: str
    table: str
    evidence_mode: str


TRAIT_SOURCES = (
    SourceCandidate("traits", "oc_views.trait_resolved_v4", "trait"),
    SourceCandidate("traits", "oc_traits.traits", "trait"),
)
INTERACTION_SOURCES = (
    SourceCandidate("interactions", "oc_interactions.orchid_interaction_edges", "interaction"),
    SourceCandidate("interactions", "oc_pollination.interactions", "interaction"),
    SourceCandidate("interactions", "oc_globi.interactions", "interaction"),
    SourceCandidate("interactions", "oc_interactions.taxon_interactions", "interaction"),
)
MOLECULAR_ASSOCIATION_SOURCES = (
    SourceCandidate("molecular_association", "oc_genomics.trait_associations", "genetic_association"),
    SourceCandidate("molecular_association", "oc_genomics.expression_associations", "expression_association"),
    SourceCandidate("molecular_association", "oc_molecular.trait_associations", "genetic_association"),
    SourceCandidate("molecular_association", "oc_molecular.expression_associations", "expression_association"),
)
PHYLOGENETIC_CONTEXT_SOURCES = (
    SourceCandidate("phylogenetic_context", "oc_phylogeny.taxon_molecular_records", "phylogenetic"),
    SourceCandidate("phylogenetic_context", "oc_phylogeny.taxon_sequences", "phylogenetic"),
)

ALL_SOURCE_GROUPS = (
    TRAIT_SOURCES,
    INTERACTION_SOURCES,
    MOLECULAR_ASSOCIATION_SOURCES,
    PHYLOGENETIC_CONTEXT_SOURCES,
)

TAXON_ID_FIELDS = (
    "canonical_taxon_id",
    "accepted_taxon_id",
    "taxonomy_id",
    "taxon_id",
    "orchid_taxonomy_id",
    "taxon_key",
    "taxon_pk",
    "orchid_taxon_id",
    "source_taxon_id",
    "subject_taxon_id",
)
TAXON_NAME_FIELDS = (
    "scientific_name",
    "taxon_name",
    "accepted_name",
    "orchid_taxon_name",
    "source_taxon_name",
    "subject_taxon_name",
)
IDENTITY_FIELDS = (
    "evidence_id",
    "trait_id",
    "interaction_id",
    "association_id",
    "sequence_id",
    "record_id",
    "source_pk",
    "id",
)
SOURCE_ID_FIELDS = (
    "source_id",
    "source_name",
    "dataset_id",
    "reference_id",
    "citation_id",
)
SOURCE_URI_FIELDS = (
    "source_uri",
    "source_url",
    "reference_url",
    "url",
    "uri",
)
CONFIDENCE_FIELDS = ("confidence_score", "confidence")

TRAIT_PREDICATE_FIELDS = (
    "trait_name",
    "trait",
    "predicate",
    "measurement_type",
    "measurementtype",
    "attribute",
)
TRAIT_VALUE_FIELDS = (
    "trait_value",
    "value",
    "measurement_value",
    "measurementvalue",
    "object",
)
UNIT_FIELDS = ("unit", "units", "measurement_unit", "measurementunit")

INTERACTION_PREDICATE_FIELDS = (
    "interaction_type",
    "interaction_predicate",
    "predicate",
    "relationship_type",
    "interaction_group",
)
TARGET_TAXON_ID_FIELDS = (
    "partner_taxon_id",
    "target_taxon_id",
    "object_taxon_id",
    "pollinator_taxon_id",
    "fungal_taxon_id",
)
TARGET_TAXON_NAME_FIELDS = (
    "partner_taxon_name",
    "target_taxon_name",
    "object_taxon_name",
    "pollinator_name",
    "fungal_name",
)

GENE_FIELDS = ("gene_id", "gene", "gene_symbol", "locus", "locus_id")
PROTEIN_FIELDS = ("protein_id", "protein", "uniprot_id", "protein_accession")
SEQUENCE_FIELDS = ("sequence_accession", "accession", "genbank_accession", "ncbi_accession")
PATHWAY_FIELDS = ("pathway_id", "pathway", "kegg_pathway")
MARKER_FIELDS = ("marker_name", "marker", "locus_name", "region_name")
MOLECULAR_PREDICATE_FIELDS = (
    "association_type",
    "predicate",
    "relationship_type",
    "effect_type",
    "marker_name",
)

EVIDENCE_TEXT_FIELDS = (
    "evidence_text",
    "excerpt",
    "evidence_citation",
    "citation",
    "reference",
    "description",
)
METHOD_FIELDS = ("method", "evidence_method", "assay", "analysis_method")


def _first(row: dict[str, Any], fields: Iterable[str]) -> Any:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for field in fields:
        value = lowered.get(field.lower())
        if value not in (None, ""):
            return value
    return None


def _text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _confidence(row: dict[str, Any]) -> tuple[float, str]:
    value = _first(row, CONFIDENCE_FIELDS)
    if value not in (None, ""):
        try:
            score = max(0.0, min(1.0, float(value)))
            return score, "source_supplied"
        except (TypeError, ValueError):
            pass
    return 0.5, "conservative_default_missing_source_confidence"


def _stable_evidence_id(prefix: str, table: str, row: dict[str, Any]) -> str:
    explicit = _text(_first(row, IDENTITY_FIELDS))
    if explicit:
        return f"{prefix}:{table}:{explicit}"
    payload = json.dumps(row, sort_keys=True, default=str, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}:{table}:{digest}"


def _base_metadata(row: dict[str, Any], table: str, confidence_basis: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "source_table": table,
        "confidence_basis": confidence_basis,
    }
    for key in (
        "support_count",
        "evidence_class",
        "confidence_label",
        "review_state",
        "license",
        "doi",
        "publication_id",
    ):
        value = row.get(key)
        if value not in (None, ""):
            metadata[key] = value
    return metadata


def _taxon_identity(row: dict[str, Any]) -> tuple[str | None, str | None]:
    return _text(_first(row, TAXON_ID_FIELDS)), _text(_first(row, TAXON_NAME_FIELDS))


def map_trait_row(row: dict[str, Any], table: str) -> EvidenceRecord | None:
    taxon_id, taxon_name = _taxon_identity(row)
    predicate = _text(_first(row, TRAIT_PREDICATE_FIELDS))
    value = _first(row, TRAIT_VALUE_FIELDS)
    if not taxon_id or not predicate or value in (None, ""):
        return None
    confidence, confidence_basis = _confidence(row)
    evidence_class = (_text(row.get("evidence_class")) or "").lower()
    direct = bool(row.get("direct_observation")) or any(
        marker in evidence_class for marker in ("observed", "direct")
    )
    return EvidenceRecord(
        evidence_id=_stable_evidence_id("trait", table, row),
        taxon_id=taxon_id,
        taxon_name=taxon_name,
        kind=EvidenceKind.OBSERVED_TRAIT if direct else EvidenceKind.INFERRED_TRAIT,
        predicate=predicate,
        value=value,
        unit=_text(_first(row, UNIT_FIELDS)),
        source_id=_text(_first(row, SOURCE_ID_FIELDS)) or table,
        source_uri=_text(_first(row, SOURCE_URI_FIELDS)),
        evidence_text=_text(_first(row, EVIDENCE_TEXT_FIELDS)),
        method=_text(_first(row, METHOD_FIELDS)),
        confidence=confidence,
        direct_observation=direct,
        metadata=_base_metadata(row, table, confidence_basis),
    )


def map_interaction_row(row: dict[str, Any], table: str) -> EvidenceRecord | None:
    taxon_id, taxon_name = _taxon_identity(row)
    predicate = _text(_first(row, INTERACTION_PREDICATE_FIELDS))
    target_id = _text(_first(row, TARGET_TAXON_ID_FIELDS))
    target_name = _text(_first(row, TARGET_TAXON_NAME_FIELDS))
    if not taxon_id or not predicate or not (target_id or target_name):
        return None
    confidence, confidence_basis = _confidence(row)
    return EvidenceRecord(
        evidence_id=_stable_evidence_id("interaction", table, row),
        taxon_id=taxon_id,
        taxon_name=taxon_name,
        kind=EvidenceKind.ECOLOGICAL_INTERACTION,
        predicate=predicate,
        target_taxon_id=target_id,
        target_taxon_name=target_name,
        source_id=_text(_first(row, SOURCE_ID_FIELDS)) or table,
        source_uri=_text(_first(row, SOURCE_URI_FIELDS)),
        evidence_text=_text(_first(row, EVIDENCE_TEXT_FIELDS)),
        method=_text(_first(row, METHOD_FIELDS)),
        confidence=confidence,
        direct_observation=bool(row.get("direct_observation")),
        metadata=_base_metadata(row, table, confidence_basis),
    )


def map_molecular_association_row(
    row: dict[str, Any],
    table: str,
    *,
    expression: bool = False,
) -> EvidenceRecord | None:
    taxon_id, taxon_name = _taxon_identity(row)
    gene_id = _text(_first(row, GENE_FIELDS))
    protein_id = _text(_first(row, PROTEIN_FIELDS))
    sequence_accession = _text(_first(row, SEQUENCE_FIELDS))
    pathway_id = _text(_first(row, PATHWAY_FIELDS))
    marker_name = _text(_first(row, MARKER_FIELDS))
    predicate = _text(_first(row, MOLECULAR_PREDICATE_FIELDS))
    if not taxon_id or not (gene_id or protein_id or pathway_id or marker_name or sequence_accession):
        return None
    if not predicate:
        predicate = "expression_associated_with_trait" if expression else "genetic_associated_with_trait"
    confidence, confidence_basis = _confidence(row)
    metadata = _base_metadata(row, table, confidence_basis)
    if marker_name:
        metadata["marker_name"] = marker_name
    evidence_kind = (_text(row.get("evidence_kind")) or "").lower()
    if evidence_kind == EvidenceKind.SELECTION_ASSOCIATION.value:
        kind = EvidenceKind.SELECTION_ASSOCIATION
    elif expression or evidence_kind == EvidenceKind.EXPRESSION_ASSOCIATION.value:
        kind = EvidenceKind.EXPRESSION_ASSOCIATION
    else:
        kind = EvidenceKind.GENETIC_ASSOCIATION
    return EvidenceRecord(
        evidence_id=_stable_evidence_id("molecular", table, row),
        taxon_id=taxon_id,
        taxon_name=taxon_name,
        kind=kind,
        predicate=predicate,
        value=_first(row, ("effect", "effect_size", "association_value", "value", "effect_value")),
        gene_id=gene_id,
        protein_id=protein_id,
        sequence_accession=sequence_accession,
        pathway_id=pathway_id,
        source_id=_text(_first(row, SOURCE_ID_FIELDS)) or table,
        source_uri=_text(_first(row, SOURCE_URI_FIELDS)),
        evidence_text=_text(_first(row, EVIDENCE_TEXT_FIELDS)),
        method=_text(_first(row, METHOD_FIELDS)),
        confidence=confidence,
        direct_observation=False,
        metadata=metadata,
    )


def map_phylogenetic_row(row: dict[str, Any], table: str) -> EvidenceRecord | None:
    taxon_id, taxon_name = _taxon_identity(row)
    accession = _text(_first(row, SEQUENCE_FIELDS))
    marker_name = _text(_first(row, MARKER_FIELDS))
    if not taxon_id or not (accession or marker_name):
        return None
    confidence, confidence_basis = _confidence(row)
    metadata = _base_metadata(row, table, confidence_basis)
    if marker_name:
        metadata["marker_name"] = marker_name
    return EvidenceRecord(
        evidence_id=_stable_evidence_id("phylogeny", table, row),
        taxon_id=taxon_id,
        taxon_name=taxon_name,
        kind=EvidenceKind.PHYLOGENETIC_EVIDENCE,
        predicate=f"phylogenetic_marker:{marker_name}" if marker_name else "sequence_accession",
        sequence_accession=accession,
        source_id=_text(_first(row, SOURCE_ID_FIELDS)) or table,
        source_uri=_text(_first(row, SOURCE_URI_FIELDS)),
        evidence_text=_text(_first(row, EVIDENCE_TEXT_FIELDS)),
        method=_text(_first(row, METHOD_FIELDS)),
        confidence=confidence,
        metadata=metadata,
    )


def make_live_dataset(
    records: list[EvidenceRecord],
    *,
    source_tables: Iterable[str],
    title: str = "Orchid Continuum live Trait–Interaction–Genomics evidence snapshot",
) -> DiscoveryDataset:
    evidence_ids = sorted(record.evidence_id for record in records)
    fingerprint_payload = json.dumps(evidence_ids, separators=(",", ":"))
    digest = hashlib.sha256(fingerprint_payload.encode("utf-8")).hexdigest()[:16]
    source_snapshot_ids = [
        f"live:{table}:{digest}" for table in sorted(set(source_tables))
    ]
    return DiscoveryDataset(
        dataset_id=f"oc-live-tig-{digest}",
        title=title,
        records=records,
        source_snapshot_ids=source_snapshot_ids,
    )


class LiveScientificEvidenceBuilder:
    """Read canonical Orchid Continuum scientific sources into TIG evidence.

    Rows without recognized canonical taxon identifiers or required domain
    identifiers are skipped rather than guessed from names. Raw phylogenetic
    sequences remain context and are not promoted to genetic association evidence.
    """

    def __init__(
        self,
        database_url: str | None = None,
        *,
        connection_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.database_url = database_url or os.getenv("DATABASE_URL")
        self.connection_factory = connection_factory or psycopg.connect

    def _connect(self):
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for live TIG evidence sources")
        return self.connection_factory(self.database_url)

    @staticmethod
    def _split_table(table: str) -> tuple[str, str]:
        schema, name = table.split(".", 1)
        return schema, name

    def _table_exists(self, cur, table: str) -> bool:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL", (table,))
        row = cur.fetchone()
        return bool(row[0])

    def _columns(self, cur, table: str) -> tuple[str, ...]:
        schema, name = self._split_table(table)
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema=%s AND table_name=%s
            ORDER BY ordinal_position
            """,
            (schema, name),
        )
        return tuple(str(row[0]) for row in cur.fetchall())

    def _count(self, cur, table: str) -> int:
        schema, name = self._split_table(table)
        cur.execute(
            sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                sql.Identifier(schema),
                sql.Identifier(name),
            )
        )
        return int(cur.fetchone()[0] or 0)

    def _first_existing(self, cur, candidates: tuple[SourceCandidate, ...]) -> SourceCandidate | None:
        for candidate in candidates:
            if self._table_exists(cur, candidate.table):
                return candidate
        return None

    def readiness(self) -> dict[str, Any]:
        groups = {
            "traits": TRAIT_SOURCES,
            "interactions": INTERACTION_SOURCES,
            "molecular_association": MOLECULAR_ASSOCIATION_SOURCES,
            "phylogenetic_context": PHYLOGENETIC_CONTEXT_SOURCES,
        }
        with self._connect() as conn, conn.cursor() as cur:
            details: dict[str, Any] = {}
            for domain, candidates in groups.items():
                candidate = self._first_existing(cur, candidates)
                if candidate is None:
                    details[domain] = {
                        "available": False,
                        "source": None,
                        "row_count": 0,
                        "columns": [],
                    }
                    continue
                row_count = self._count(cur, candidate.table)
                details[domain] = {
                    "available": True,
                    "source": candidate.table,
                    "row_count": row_count,
                    "has_evidence": row_count > 0,
                    "columns": list(self._columns(cur, candidate.table)),
                }

        required_domains = ("traits", "interactions", "molecular_association")
        three_domain_ready = all(
            details[domain]["available"] and details[domain]["row_count"] > 0
            for domain in required_domains
        )
        return {
            "contract": "calyx-tig-live-evidence-readiness-v1",
            "domains": details,
            "three_domain_discovery_ready": three_domain_ready,
            "phylogenetic_context_available": details["phylogenetic_context"]["available"],
            "scientific_boundary": (
                "A source object is not evidence readiness: all three required domains must "
                "contain at least one evidence row. Raw phylogenetic sequence presence is "
                "contextual evidence only and is not treated as a genetic or expression association."
            ),
        }

    def _fetch_rows(
        self,
        cur,
        candidate: SourceCandidate,
        *,
        limit: int,
        taxon_ids: list[str] | None,
    ) -> list[dict[str, Any]]:
        columns = self._columns(cur, candidate.table)
        schema, name = self._split_table(candidate.table)
        query = sql.SQL("SELECT * FROM {}.{}").format(
            sql.Identifier(schema),
            sql.Identifier(name),
        )
        params: list[Any] = []
        if taxon_ids:
            taxon_column = next((field for field in TAXON_ID_FIELDS if field in columns), None)
            if taxon_column:
                query += sql.SQL(" WHERE {} = ANY(%s)").format(sql.Identifier(taxon_column))
                params.append(taxon_ids)
        query += sql.SQL(" LIMIT %s")
        params.append(limit)
        cur.execute(query, tuple(params))
        rows = cur.fetchall()
        return [dict(zip(columns, row, strict=True)) for row in rows]

    def build_dataset(
        self,
        *,
        limit_per_domain: int = 1000,
        taxon_ids: list[str] | None = None,
        include_phylogenetic_context: bool = True,
    ) -> tuple[DiscoveryDataset, dict[str, Any]]:
        if limit_per_domain < 1 or limit_per_domain > 10000:
            raise ValueError("limit_per_domain must be between 1 and 10000")
        if taxon_ids and len(taxon_ids) > 1000:
            raise ValueError("taxon_ids is limited to 1000 identifiers per live TIG build")

        groups: list[tuple[tuple[SourceCandidate, ...], Callable[..., EvidenceRecord | None]]] = [
            (TRAIT_SOURCES, map_trait_row),
            (INTERACTION_SOURCES, map_interaction_row),
        ]
        records: list[EvidenceRecord] = []
        source_tables: list[str] = []
        diagnostics: dict[str, Any] = {}

        with self._connect() as conn, conn.cursor() as cur:
            for candidates, mapper in groups:
                candidate = self._first_existing(cur, candidates)
                domain = candidates[0].domain
                if candidate is None:
                    diagnostics[domain] = {
                        "source": None,
                        "fetched": 0,
                        "accepted": 0,
                        "skipped": 0,
                    }
                    continue
                rows = self._fetch_rows(
                    cur,
                    candidate,
                    limit=limit_per_domain,
                    taxon_ids=taxon_ids,
                )
                accepted = 0
                for row in rows:
                    record = mapper(row, candidate.table)
                    if record is not None:
                        records.append(record)
                        accepted += 1
                source_tables.append(candidate.table)
                diagnostics[domain] = {
                    "source": candidate.table,
                    "fetched": len(rows),
                    "accepted": accepted,
                    "skipped": len(rows) - accepted,
                }

            molecular_candidate = self._first_existing(cur, MOLECULAR_ASSOCIATION_SOURCES)
            if molecular_candidate is None:
                diagnostics["molecular_association"] = {
                    "source": None,
                    "fetched": 0,
                    "accepted": 0,
                    "skipped": 0,
                }
            else:
                rows = self._fetch_rows(
                    cur,
                    molecular_candidate,
                    limit=limit_per_domain,
                    taxon_ids=taxon_ids,
                )
                expression = molecular_candidate.evidence_mode == "expression_association"
                accepted = 0
                for row in rows:
                    record = map_molecular_association_row(
                        row,
                        molecular_candidate.table,
                        expression=expression,
                    )
                    if record is not None:
                        records.append(record)
                        accepted += 1
                source_tables.append(molecular_candidate.table)
                diagnostics["molecular_association"] = {
                    "source": molecular_candidate.table,
                    "fetched": len(rows),
                    "accepted": accepted,
                    "skipped": len(rows) - accepted,
                }

            if include_phylogenetic_context:
                phylo_candidate = self._first_existing(cur, PHYLOGENETIC_CONTEXT_SOURCES)
                if phylo_candidate is None:
                    diagnostics["phylogenetic_context"] = {
                        "source": None,
                        "fetched": 0,
                        "accepted": 0,
                        "skipped": 0,
                    }
                else:
                    rows = self._fetch_rows(
                        cur,
                        phylo_candidate,
                        limit=limit_per_domain,
                        taxon_ids=taxon_ids,
                    )
                    accepted = 0
                    for row in rows:
                        record = map_phylogenetic_row(row, phylo_candidate.table)
                        if record is not None:
                            records.append(record)
                            accepted += 1
                    source_tables.append(phylo_candidate.table)
                    diagnostics["phylogenetic_context"] = {
                        "source": phylo_candidate.table,
                        "fetched": len(rows),
                        "accepted": accepted,
                        "skipped": len(rows) - accepted,
                    }

        deduplicated = {record.evidence_id: record for record in records}
        dataset = make_live_dataset(
            list(deduplicated.values()),
            source_tables=source_tables,
        )
        diagnostics["total_records"] = len(dataset.records)
        diagnostics["deduplicated_records"] = len(records) - len(dataset.records)
        diagnostics["three_domain_evidence_present"] = all(
            any(record.kind in kinds for record in dataset.records)
            for kinds in (
                {
                    EvidenceKind.OBSERVED_TRAIT,
                    EvidenceKind.INFERRED_TRAIT,
                    EvidenceKind.PREDICTED_TRAIT,
                },
                {EvidenceKind.ECOLOGICAL_INTERACTION},
                {
                    EvidenceKind.GENETIC_ASSOCIATION,
                    EvidenceKind.EXPRESSION_ASSOCIATION,
                    EvidenceKind.SELECTION_ASSOCIATION,
                },
            )
        )
        return dataset, diagnostics
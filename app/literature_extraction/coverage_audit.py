from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.readiness.relationship_measurement import (
    OBJECT_NAME_COLUMNS,
    OBJECT_TAXON_KEYS,
    RELATIONSHIP_SPECS,
    TAXONOMY_KEYS,
    TAXONOMY_NAME_COLUMNS,
    TAXONOMY_TABLES,
    _unavailable,
    measure_link_relationship,
)

from .models import PaperKnowledge
from .repository import LiteratureResultRepository

CONTRACT = "calyx-literature-coverage-telemetry-v1"
DB_UNAVAILABLE_DETAIL = "No live database connection was available for this audit run."

_METHODS_SECTION_TYPES = frozenset({"methods"})
_METHODS_CLAIM_TYPES = frozenset({"methodological"})
_RESULTS_SECTION_TYPES = frozenset({"results", "discussion", "conclusion"})
_RESULTS_CLAIM_TYPES = frozenset({"result", "interpretation"})

_LITERATURE_SPEC = next(
    spec for spec in RELATIONSHIP_SPECS if spec["name"] == "taxonomy_to_literature"
)


def discovered_corpus_measurement(cur) -> dict[str, Any]:
    return measure_link_relationship(
        cur,
        name="taxonomy_to_literature",
        taxonomy_tables=TAXONOMY_TABLES,
        taxonomy_keys=TAXONOMY_KEYS,
        taxonomy_name_columns=TAXONOMY_NAME_COLUMNS,
        object_tables=_LITERATURE_SPEC["object_tables"],
        object_taxon_keys=OBJECT_TAXON_KEYS,
        object_name_columns=OBJECT_NAME_COLUMNS,
        required_value_columns=_LITERATURE_SPEC.get("required_value_columns", ()),
        row_filters=_LITERATURE_SPEC.get("row_filters"),
    )


def _kg_literature_doi_index(cur) -> set[str] | None:
    try:
        cur.execute(
            "SELECT doi FROM oc_graph.taxon_literature_edges WHERE doi IS NOT NULL"
        )
        rows = cur.fetchall()
    except Exception:  # noqa: BLE001 - unavailable telemetry is unknown, not false
        return None
    return {
        str(row[0] if not isinstance(row, dict) else row["doi"])
        for row in rows
        if (row[0] if not isinstance(row, dict) else row["doi"])
    }


@dataclass(frozen=True, slots=True)
class PaperCoverage:
    paper_id: str
    full_text_available: bool
    extracted: bool
    taxonomically_bound: bool
    methods_extracted: bool
    traits_or_measurements_extracted: bool
    results_or_conclusions_extracted: bool
    publication_eligible: bool
    kg_materialized: bool | None
    doi_identifiers: tuple[str, ...]


def _paper_coverage(
    paper: PaperKnowledge,
    *,
    full_text_available: bool,
    kg_doi_index: set[str] | None,
) -> PaperCoverage:
    manifest = paper.analysis_manifest
    extracted = manifest.status in ("completed", "completed_with_warnings")
    taxonomically_bound = any(
        entity.entity_type == "taxon" and entity.external_ids for entity in paper.entities
    )
    methods_extracted = any(
        section.canonical_type in _METHODS_SECTION_TYPES and section.text.strip()
        for section in paper.sections
    ) or any(claim.claim_type in _METHODS_CLAIM_TYPES for claim in paper.claims)
    traits_or_measurements_extracted = bool(paper.measurements) or any(
        record.domain == "trait" for record in paper.normalized_evidence_records
    )
    results_or_conclusions_extracted = any(
        section.canonical_type in _RESULTS_SECTION_TYPES and section.text.strip()
        for section in paper.sections
    ) or any(claim.claim_type in _RESULTS_CLAIM_TYPES for claim in paper.claims)
    publication_eligible = any(
        decision.status == "eligible_for_publication"
        for decision in paper.publication_decisions
    )
    dois = tuple(
        sorted(
            {
                identifier.value
                for identifier in paper.metadata.identifiers
                if identifier.scheme == "doi"
            }
        )
    )
    kg_materialized = (
        None
        if kg_doi_index is None
        else bool(dois) and any(doi in kg_doi_index for doi in dois)
    )
    return PaperCoverage(
        paper_id=paper.paper_id,
        full_text_available=full_text_available,
        extracted=extracted,
        taxonomically_bound=taxonomically_bound,
        methods_extracted=methods_extracted,
        traits_or_measurements_extracted=traits_or_measurements_extracted,
        results_or_conclusions_extracted=results_or_conclusions_extracted,
        publication_eligible=publication_eligible,
        kg_materialized=kg_materialized,
        doi_identifiers=dois,
    )


_STAGE_FIELDS = (
    "full_text_available",
    "extracted",
    "taxonomically_bound",
    "methods_extracted",
    "traits_or_measurements_extracted",
    "results_or_conclusions_extracted",
    "publication_eligible",
)


def audit_literature_extraction_coverage(
    cur,
    repository: LiteratureResultRepository,
    *,
    db_unavailable_detail: str | None = None,
) -> dict[str, Any]:
    if cur is None:
        discovered = _unavailable(
            "taxonomy_to_literature", db_unavailable_detail or DB_UNAVAILABLE_DETAIL
        )
        kg_doi_index: set[str] | None = None
    else:
        discovered = discovered_corpus_measurement(cur)
        kg_doi_index = _kg_literature_doi_index(cur)

    stage_counts = {field: 0 for field in _STAGE_FIELDS}
    kg_materialized_count = 0
    kg_materialized_unknown_count = 0
    papers_examined = 0
    unreadable_papers: list[dict[str, str]] = []
    provenance: list[dict[str, Any]] = []

    for paper_id in repository.list_paper_ids():
        try:
            paper = repository.get(paper_id)
        except Exception as exc:  # noqa: BLE001 - one malformed bundle must not sink audit
            unreadable_papers.append(
                {"paper_id": paper_id, "error": f"{type(exc).__name__}: {exc}"}
            )
            continue
        if paper is None:
            continue
        papers_examined += 1
        coverage = _paper_coverage(
            paper,
            full_text_available=repository.get_raw_bytes(paper_id) is not None,
            kg_doi_index=kg_doi_index,
        )
        for field in _STAGE_FIELDS:
            if getattr(coverage, field):
                stage_counts[field] += 1
        if coverage.kg_materialized is True:
            kg_materialized_count += 1
        elif coverage.kg_materialized is None:
            kg_materialized_unknown_count += 1
        provenance.append(
            {
                "paper_id": coverage.paper_id,
                "doi_identifiers": list(coverage.doi_identifiers),
                "analysis_id": paper.analysis_manifest.analysis_id,
                "source_content_hash": paper.source.content_hash,
                "kg_materialized": coverage.kg_materialized,
            }
        )

    return {
        "contract": CONTRACT,
        "graph_mutation": False,
        "discovered_corpus": {
            "stage": "discovered",
            "measurement": discovered,
            "canonical_precedence": "Not established; candidate selection remains first-match-by-existence with masking warnings preserved.",
        },
        "extraction_pipeline": {
            "stage": "extraction_pipeline",
            "source": "filesystem literature_extraction bundles (app.literature_extraction)",
            "extraction_root_available": repository.root_available(),
            "papers_examined": papers_examined,
            "unreadable_papers": unreadable_papers,
            "stage_counts": {
                "ingested_full_text_available": stage_counts["full_text_available"],
                "extracted": stage_counts["extracted"],
                "taxonomically_bound": stage_counts["taxonomically_bound"],
                "methods_extracted": stage_counts["methods_extracted"],
                "traits_or_measurements_extracted": stage_counts[
                    "traits_or_measurements_extracted"
                ],
                "results_or_conclusions_extracted": stage_counts[
                    "results_or_conclusions_extracted"
                ],
                "publication_eligible": stage_counts["publication_eligible"],
            },
            "kg_materialized": kg_materialized_count,
            "kg_materialized_unknown": kg_materialized_unknown_count,
            "provenance": provenance,
        },
        "interpretation": "Discovered corpus and extracted evidence are different populations and are reported separately.",
        "publication_note": "Publication eligibility is not a publication action; this audit performs no graph mutation.",
    }

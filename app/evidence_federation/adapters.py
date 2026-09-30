"""Pure source adapters for partner orchid datasets."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any, Mapping

from runtime.knowledge_graph.canonical_taxonomy import CanonicalRegistry, canonical_name_of

REVIEW_REQUIRED = "review_required"
EXACT_ACCEPTED = "exact_accepted"
SYNONYM_RESOLVED = "synonym_resolved"
UNRESOLVED = "unresolved"


def _text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _hash_row(source_id: str, raw_fields: Mapping[str, Any]) -> str:
    payload = json.dumps(
        {"source_id": source_id, "raw_fields": dict(raw_fields)},
        sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _strip_html(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())


@dataclass(frozen=True, slots=True)
class EvidenceAssertion:
    predicate: str
    value: str
    source_field: str
    review_state: str = REVIEW_REQUIRED


@dataclass(frozen=True, slots=True)
class SourceRecord:
    source_id: str
    source_record_id: str
    source_taxon_name: str
    editorial_marker: str | None
    assertions: tuple[EvidenceAssertion, ...]
    raw_fields: Mapping[str, Any]
    row_sha256: str
    canonical_taxon_id: int | None = None
    canonical_name: str | None = None
    reconciliation_status: str = UNRESOLVED
    provenance: Mapping[str, Any] = field(default_factory=dict)


def _assertions(row: Mapping[str, Any], mapping: Mapping[str, str]) -> tuple[EvidenceAssertion, ...]:
    out: list[EvidenceAssertion] = []
    for source_field, predicate in mapping.items():
        value = _strip_html(row.get(source_field))
        if value:
            out.append(EvidenceAssertion(predicate=predicate, value=value, source_field=source_field))
    return tuple(out)


IOSPE_FIELDS = {
    "season": "phenology.flowering_season",
    "temperature": "cultivation.temperature_class",
    "light": "cultivation.light",
    "fragrance": "morphology.fragrance",
    "common name": "vernacular.common_name",
    "flower size": "morphology.flower_size",
    "description": "source.description",
    "synonyms": "taxonomy.source_reported_synonyms",
    "references": "literature.source_reported_references",
}

YONG_GEE_FIELDS = {
    "publicationsp": "taxonomy.publication",
    "pubyrsp": "taxonomy.publication_year",
    "etymology": "nomenclature.etymology",
    "synonym": "taxonomy.source_reported_synonyms",
    "commonName": "vernacular.common_name",
    "section": "taxonomy.section",
    "subsection": "taxonomy.subsection",
    "distributionsp": "geography.distribution",
    "habitat": "ecology.habitat",
    "season": "phenology.flowering_season",
    "scent": "morphology.fragrance",
    "characteristicsp": "morphology.description",
    "capsule": "morphology.capsule",
    "similarSpecies": "taxonomy.similar_species",
    "notes": "source.notes",
    "referencesp": "literature.source_reported_references",
    "notesGary": "source.owner_notes",
    "article": "literature.source_article",
}


def adapt_iospe_row(row: Mapping[str, Any], *, row_number: int) -> SourceRecord:
    raw_name = _text(row.get("name"))
    marker = raw_name[0] if raw_name[:1] in {"!", "~"} else None
    taxon_name = raw_name[1:].strip() if marker else raw_name
    raw_fields = dict(row)
    return SourceRecord(
        source_id="iospe_pfahl",
        source_record_id=f"iospe:{row_number}",
        source_taxon_name=taxon_name,
        editorial_marker=marker,
        assertions=_assertions(row, IOSPE_FIELDS),
        raw_fields=raw_fields,
        row_sha256=_hash_row("iospe_pfahl", raw_fields),
        provenance={
            "owner": "Jay Pfahl",
            "source": "Internet Orchid Species Photo Encyclopedia",
            "supplied_by": "Chris Howard",
            "scientific_status": REVIEW_REQUIRED,
        },
    )


def _yong_gee_name(row: Mapping[str, Any]) -> str:
    informal = _strip_html(row.get("websiteInformalName"))
    if informal and re.match(r"^[A-Z][A-Za-z-]+\s+[a-z×][A-Za-z×.-]+", informal):
        return informal
    genus = _text(row.get("genus"))
    species = _text(row.get("speciesName"))
    if genus and species:
        parts = [genus, species]
        if _text(row.get("subtax1")) and _text(row.get("taxon1")):
            parts.extend([_text(row.get("subtax1")), _text(row.get("taxon1"))])
        return " ".join(parts)
    return informal or species


def adapt_yong_gee_row(row: Mapping[str, Any], *, row_number: int) -> SourceRecord:
    raw_fields = dict(row)
    stable = _text(row.get("id")) or str(row_number)
    return SourceRecord(
        source_id="yong_gee",
        source_record_id=f"yong_gee:{stable}",
        source_taxon_name=_yong_gee_name(row),
        editorial_marker=None,
        assertions=_assertions(row, YONG_GEE_FIELDS),
        raw_fields=raw_fields,
        row_sha256=_hash_row("yong_gee", raw_fields),
        provenance={
            "owner": "Gary Yong Gee",
            "supplied_by": "Roger Sawkins",
            "coverage": "representative_extract_not_complete",
            "scientific_status": REVIEW_REQUIRED,
        },
    )


def reconcile_source_record(record: SourceRecord, registry: CanonicalRegistry) -> SourceRecord:
    if not record.source_taxon_name:
        return record

    source_canonical = canonical_name_of(record.source_taxon_name)
    indexed = registry.name_index.get(source_canonical)
    if indexed is None:
        return record

    original = registry.taxa.get(indexed)
    resolved = registry.resolve(record.source_taxon_name)
    if resolved is None:
        return record

    status = EXACT_ACCEPTED
    if original is not None and original.status == "synonym":
        status = SYNONYM_RESOLVED

    return SourceRecord(
        source_id=record.source_id,
        source_record_id=record.source_record_id,
        source_taxon_name=record.source_taxon_name,
        editorial_marker=record.editorial_marker,
        assertions=record.assertions,
        raw_fields=record.raw_fields,
        row_sha256=record.row_sha256,
        canonical_taxon_id=resolved.canonical_id,
        canonical_name=resolved.canonical_name,
        reconciliation_status=status,
        provenance=record.provenance,
    )

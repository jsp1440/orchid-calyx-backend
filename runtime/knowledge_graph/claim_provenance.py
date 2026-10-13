"""Claim-level provenance carried on Knowledge Graph assertions.

One nested payload key, ``claim_provenance``, on an existing graph object --
``oc_graph.kg_edges.payload_json`` / ``kg_nodes.payload_json`` for the domain
publishers (including the #901 paper-graph materializer) and
``oc_knowledge_publication.graph_object_versions.payload`` for the 088c
assertion publisher.  No new table, store or graph engine.

It records, per claim:

* the source: document id, revision id and content hash;
* the anchors: page and character span or a structured locator;
* the taxon binding: World Plants canonical name, release and taxon-link
  status (``runtime.knowledge_graph.canonical_graph_mapping``), and the graph
  node key it was bound to;
* how the claim was produced: extraction method, extractor and version, and
  confidence (a heuristic score, never a probability) or explicit uncertainty;
* its review status;
* its lineage: assertion id, conflicting assertion ids, interpretation,
  evidence-packet and normalized-record ids.

Extraction-method and review vocabularies are read from
``app.literature_extraction.models.Provenance`` so both sides stay one list.
Validation fails closed and names every violation; it never repairs a record.
"""

from __future__ import annotations

import typing
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.literature_extraction.models import Provenance as LiteratureProvenance

from .canonical_taxonomy import CANONICAL_AUTHORITY

CONTRACT_VERSION = "oc-claim-provenance-v1"
PAYLOAD_KEY = "claim_provenance"

EXTRACTION_METHODS: tuple[str, ...] = typing.get_args(
    LiteratureProvenance.model_fields["method"].annotation
)
REVIEW_STATUSES: tuple[str, ...] = typing.get_args(
    LiteratureProvenance.model_fields["review_status"].annotation
)
REVIEWED_STATUSES = frozenset({"accepted", "corrected"})
LINKED_TAXON_STATUSES = frozenset({"accepted", "synonym"})

#: Keys that would carry locality.  Claim provenance never needs them.
FORBIDDEN_KEYS = frozenset(
    {"latitude", "longitude", "decimal_latitude", "decimal_longitude", "coordinates", "locality", "verbatim_locality"}
)


@dataclass(frozen=True)
class SourceAnchor:
    page_start: int | None = None
    page_end: int | None = None
    section_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    anchor_id: str | None = None
    locator: dict[str, Any] | None = None

    def is_exact(self) -> bool:
        return self.page_start is not None or self.char_start is not None or bool(self.locator)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass(frozen=True)
class TaxonBinding:
    canonical_name: str
    link_status: str
    taxonomy_release: str | None = None
    node_key: str | None = None
    authority: str = CANONICAL_AUTHORITY

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class ClaimProvenance:
    source_document_id: str
    source_revision_id: str | None
    content_hash: str | None
    anchors: tuple[SourceAnchor, ...]
    taxon: TaxonBinding
    extraction_method: str
    review_status: str
    assertion_id: str
    confidence: float | None = None
    uncertainty: tuple[str, ...] = ()
    extractor: str | None = None
    extractor_version: str | None = None
    qualifiers: tuple[str, ...] = ()
    conflicting_assertion_ids: tuple[str, ...] = ()
    interpretation_ids: tuple[str, ...] = ()
    evidence_packet_ids: tuple[str, ...] = ()
    normalized_record_ids: tuple[str, ...] = ()
    contract_version: str = CONTRACT_VERSION
    confidence_is_probability: bool = False

    @property
    def reviewed(self) -> bool:
        return self.review_status in REVIEWED_STATUSES

    def to_payload(self) -> dict[str, Any]:
        """The value to store under ``payload[PAYLOAD_KEY]``."""

        return {
            "contract_version": self.contract_version,
            "assertion_id": self.assertion_id,
            "source": {
                "document_id": self.source_document_id,
                "revision_id": self.source_revision_id,
                "content_hash": self.content_hash,
            },
            "anchors": [a.to_dict() for a in self.anchors],
            "taxon": self.taxon.to_dict(),
            "extraction": {
                "method": self.extraction_method,
                "extractor": self.extractor,
                "extractor_version": self.extractor_version,
            },
            "confidence": self.confidence,
            "confidence_is_probability": False,
            "uncertainty": list(self.uncertainty),
            "review_status": self.review_status,
            "qualifiers": list(self.qualifiers),
            "lineage": {
                "conflicting_assertion_ids": list(self.conflicting_assertion_ids),
                "interpretation_ids": list(self.interpretation_ids),
                "evidence_packet_ids": list(self.evidence_packet_ids),
                "normalized_record_ids": list(self.normalized_record_ids),
            },
        }


def _keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, inner in value.items():
            found.add(str(key))
            found |= _keys(inner)
    elif isinstance(value, (list, tuple)):
        for inner in value:
            found |= _keys(inner)
    return found


def _strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(v) for v in value)


def parse_claim_provenance(payload: Mapping[str, Any] | None) -> tuple[ClaimProvenance | None, tuple[str, ...]]:
    """Parse ``payload[PAYLOAD_KEY]``; return ``(record, ())`` or ``(None, violations)``."""

    raw = (payload or {}).get(PAYLOAD_KEY)
    if not isinstance(raw, Mapping):
        return None, ("CLAIM_PROVENANCE_ABSENT",)
    violations: list[str] = []
    if raw.get("contract_version") != CONTRACT_VERSION:
        violations.append("CONTRACT_VERSION_UNSUPPORTED")
    leaked = _keys(raw) & FORBIDDEN_KEYS
    if leaked:
        violations.append("FORBIDDEN_LOCALITY_KEYS:" + ",".join(sorted(leaked)))
    if raw.get("confidence_is_probability"):
        violations.append("CONFIDENCE_IS_NOT_A_PROBABILITY")

    source = raw.get("source") if isinstance(raw.get("source"), Mapping) else {}
    document_id = str(source.get("document_id") or "").strip()
    if not document_id:
        violations.append("SOURCE_DOCUMENT_UNDECLARED")

    anchors: list[SourceAnchor] = []
    for item in raw.get("anchors") or ():
        if not isinstance(item, Mapping):
            violations.append("ANCHOR_MALFORMED")
            continue
        try:
            anchors.append(
                SourceAnchor(
                    page_start=None if item.get("page_start") is None else int(item["page_start"]),
                    page_end=None if item.get("page_end") is None else int(item["page_end"]),
                    section_id=item.get("section_id"),
                    char_start=None if item.get("char_start") is None else int(item["char_start"]),
                    char_end=None if item.get("char_end") is None else int(item["char_end"]),
                    anchor_id=None if item.get("anchor_id") is None else str(item["anchor_id"]),
                    locator=dict(item["locator"]) if isinstance(item.get("locator"), Mapping) else None,
                )
            )
        except (TypeError, ValueError):
            violations.append("ANCHOR_MALFORMED")
    if not any(a.is_exact() for a in anchors):
        violations.append("EXACT_ANCHOR_MISSING")
    for anchor in anchors:
        if anchor.page_start is not None and anchor.page_end is not None and anchor.page_end < anchor.page_start:
            violations.append("ANCHOR_PAGE_RANGE_INVALID")
        if anchor.char_start is not None and anchor.char_end is not None and anchor.char_end < anchor.char_start:
            violations.append("ANCHOR_CHAR_RANGE_INVALID")

    taxon_raw = raw.get("taxon") if isinstance(raw.get("taxon"), Mapping) else {}
    taxon = TaxonBinding(
        canonical_name=str(taxon_raw.get("canonical_name") or "").strip(),
        link_status=str(taxon_raw.get("link_status") or ""),
        taxonomy_release=taxon_raw.get("taxonomy_release"),
        node_key=taxon_raw.get("node_key"),
        authority=str(taxon_raw.get("authority") or ""),
    )
    if not taxon.canonical_name:
        violations.append("TAXON_UNBOUND")
    if taxon.authority != CANONICAL_AUTHORITY:
        violations.append("TAXON_AUTHORITY_NOT_WORLD_PLANTS")
    if taxon.link_status not in LINKED_TAXON_STATUSES:
        violations.append("TAXON_LINK_NOT_VERIFIED")

    extraction = raw.get("extraction") if isinstance(raw.get("extraction"), Mapping) else {}
    method = str(extraction.get("method") or "")
    if method not in EXTRACTION_METHODS:
        violations.append("EXTRACTION_METHOD_UNKNOWN")
    review_status = str(raw.get("review_status") or "")
    if review_status not in REVIEW_STATUSES:
        violations.append("REVIEW_STATUS_UNKNOWN")
    elif review_status == "rejected":
        violations.append("CLAIM_REJECTED_IN_REVIEW")

    confidence = raw.get("confidence")
    uncertainty = _strings(raw.get("uncertainty"))
    if confidence is not None:
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = -1.0
        if not 0.0 <= confidence <= 1.0:
            violations.append("CONFIDENCE_OUT_OF_RANGE")
    elif not uncertainty:
        violations.append("CONFIDENCE_AND_UNCERTAINTY_BOTH_MISSING")

    assertion_id = str(raw.get("assertion_id") or "").strip()
    if not assertion_id:
        violations.append("ASSERTION_ID_MISSING")

    if violations:
        return None, tuple(dict.fromkeys(violations))
    lineage = raw.get("lineage") if isinstance(raw.get("lineage"), Mapping) else {}
    return (
        ClaimProvenance(
            source_document_id=document_id,
            source_revision_id=None if source.get("revision_id") is None else str(source["revision_id"]),
            content_hash=source.get("content_hash"),
            anchors=tuple(anchors),
            taxon=taxon,
            extraction_method=method,
            review_status=review_status,
            assertion_id=assertion_id,
            confidence=confidence,
            uncertainty=uncertainty,
            extractor=extraction.get("extractor"),
            extractor_version=extraction.get("extractor_version"),
            qualifiers=_strings(raw.get("qualifiers")),
            conflicting_assertion_ids=_strings(lineage.get("conflicting_assertion_ids")),
            interpretation_ids=_strings(lineage.get("interpretation_ids")),
            evidence_packet_ids=_strings(lineage.get("evidence_packet_ids")),
            normalized_record_ids=_strings(lineage.get("normalized_record_ids")),
        ),
        (),
    )


def from_literature_claim(
    claim: Mapping[str, Any],
    evidence: Iterable[Mapping[str, Any]],
    *,
    source_document_id: str,
    source_revision_id: str | None,
    content_hash: str | None,
    taxon: TaxonBinding,
    conflicting_assertion_ids: Iterable[str] = (),
    normalized_record_ids: Iterable[str] = (),
) -> ClaimProvenance:
    """Producer helper: one literature ``Claim`` plus its ``Evidence`` spans.

    ``claim`` and ``evidence`` are ``app.literature_extraction.models`` objects
    as dicts (``model_dump()``).  Spans come only from the evidence the claim
    cites; nothing is inferred.  The result still goes through
    :func:`parse_claim_provenance` before a publisher may store it.
    """

    cited = set(claim.get("evidence_ids") or ())
    anchors = tuple(
        SourceAnchor(
            page_start=span.get("page_start"),
            page_end=span.get("page_end"),
            section_id=span.get("section_id"),
            char_start=span.get("char_start"),
            char_end=span.get("char_end"),
            anchor_id=str(item.get("evidence_id")),
        )
        for item in evidence
        if item.get("evidence_id") in cited
        for span in [item.get("span") or {}]
    )
    provenance = claim.get("provenance") or {}
    return ClaimProvenance(
        source_document_id=source_document_id,
        source_revision_id=source_revision_id,
        content_hash=content_hash,
        anchors=anchors,
        taxon=taxon,
        extraction_method=str(provenance.get("method") or ""),
        review_status=str(provenance.get("review_status") or "unreviewed"),
        assertion_id=str(claim.get("claim_id") or ""),
        confidence=provenance.get("confidence"),
        extractor=provenance.get("extractor"),
        extractor_version=provenance.get("extractor_version"),
        conflicting_assertion_ids=tuple(conflicting_assertion_ids),
        normalized_record_ids=tuple(normalized_record_ids),
    )


@dataclass(frozen=True)
class ProvenanceCoverage:
    """How much of a set of graph objects carries valid claim provenance."""

    total: int
    valid: int
    violations: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"total": self.total, "valid": self.valid, "violations": dict(sorted(self.violations.items()))}


def coverage(payloads: Iterable[Mapping[str, Any] | None]) -> ProvenanceCoverage:
    total = valid = 0
    counts: dict[str, int] = {}
    for payload in payloads:
        total += 1
        record, violations = parse_claim_provenance(payload)
        if record is not None:
            valid += 1
        for violation in violations:
            counts[violation] = counts.get(violation, 0) + 1
    return ProvenanceCoverage(total=total, valid=valid, violations=counts)

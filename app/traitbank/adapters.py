"""Normalize existing extraction outputs into ``oc-traitbank-v1`` batches.

1. Literature extraction: ``app.literature_extraction.models.PaperKnowledge``.
2. EOL TraitBank: the normalized records yielded by
   ``harvesters.traitbank.TraitBankHarvester`` (``source_key, scientific_name,
   trait_raw, value_raw, units_raw, reference_raw, raw``).

Adapters only normalize. They never guess: a record without a registered
trait, a uniquely resolved canonical taxon, a stated assertion level or a
convertible unit is returned in ``unmapped`` with its raw content, not dropped
and not forced. The resulting batch still goes through every guard and
reference check in ``TraitBankRepository.ingest``.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from app.literature_extraction.models import PaperKnowledge

from .contract import CONTRACT_VERSION
from .interop import kg_claim_key, kg_measurement_key
from .models import STATISTICS, TraitBankBatch, TraitDefinitionIn

TaxonResolver = Callable[[str], "str | None"]

LENGTH_TO_MM = {
    "mm": 1.0,
    "cm": 10.0,
    "m": 1000.0,
    "in": 25.4,
    "inch": 25.4,
    "inches": 25.4,
}
UNIT_ALIASES = {
    "millimeter": "mm",
    "millimetre": "mm",
    "centimeter": "cm",
    "centimetre": "cm",
    "meter": "m",
    "metre": "m",
    # Units Ontology length terms as EOL exports them (``units_term``).
    "http://purl.obolibrary.org/obo/uo_0000016": "mm",
    "http://purl.obolibrary.org/obo/uo_0000015": "cm",
    "http://purl.obolibrary.org/obo/uo_0000008": "m",
}
RANGE_RE = re.compile(
    r"^\s*(-?\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(-?\d+(?:\.\d+)?)\s*([A-Za-z]*)\s*$"
)
LEVEL_ATTRIBUTES = (
    ("specimen_id", "specimen"),
    ("population_id", "population"),
    ("observation_id", "observation"),
)
LINK_PREDICATES = {
    "pollinated_by": "pollinator",
    "visited_by": "pollinator",
    "mycorrhizal_partner": "mycorrhizal",
    "flowers_in": "phenology",
    "occurs_in": "occurrence",
    "grows_in_habitat": "habitat",
    "experiences_climate": "climate",
    "anatomically_described_in": "anatomical",
    "reproductive_observation": "reproductive",
}
ENVIRONMENT_PREDICATES = {
    "correlates_with": ("observed_correlation", None),
    "hypothesized_adaptation_to": ("proposed_hypothesis", "adaptive"),
    "hypothesized_evolutionary_response_to": ("proposed_hypothesis", "evolutionary"),
}
RIGHTS_TO_LICENSE = {
    "public_domain": "public domain",
    "open_license": "open license (see source)",
    "permission_granted": "used with permission",
    "unknown_requires_review": "unknown_requires_review",
    "restricted": "restricted",
}


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().casefold())


def convert(value: float, unit: str | None, target: str | None) -> float | None:
    unit_c = UNIT_ALIASES.get(_norm(unit), _norm(unit))
    target_c = UNIT_ALIASES.get(_norm(target), _norm(target))
    if unit_c == target_c:
        return value
    if unit_c in LENGTH_TO_MM and target_c in LENGTH_TO_MM:
        return round(value * LENGTH_TO_MM[unit_c] / LENGTH_TO_MM[target_c], 6)
    return None


@dataclass
class TraitIndex:
    definitions: dict[str, TraitDefinitionIn]
    _alias: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for d in self.definitions.values():
            for alias in (d.trait_id, d.label, *d.aliases):
                self._alias[_norm(alias)] = d.trait_id

    def resolve(self, label: str | None) -> TraitDefinitionIn | None:
        trait_id = self._alias.get(_norm(label))
        return self.definitions.get(trait_id) if trait_id else None

    @staticmethod
    def state(definition: TraitDefinitionIn, raw: str | None) -> str | None:
        key = _norm(raw)
        for s in definition.states:
            if key in (_norm(s.state_id), _norm(s.label)):
                return s.state_id
        return None


@dataclass
class Normalized:
    batch: TraitBankBatch | None
    unmapped: list[dict[str, Any]]
    # assertion_id -> evidence_crosswalk entry (KG key shared with #901).
    crosswalk: dict[str, dict[str, Any]] = field(default_factory=dict)


def _unmapped(source_id: str, record_id: str, reason: str, raw: Any) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "original_record_id": record_id,
        "reason": reason,
        "raw": raw,
    }


def _batch_key(producer: str, payload: Any) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()[:32]
    return f"{producer}:{digest}"


# ------------------------------------------------------------------ literature
def _citation(paper: PaperKnowledge) -> tuple[str, str, str | None]:
    meta = paper.metadata
    doi = next((i.value for i in meta.identifiers if i.scheme == "doi"), None)
    authors = ", ".join(meta.authors) or "Unknown author"
    parts = [
        f"{authors} ({meta.publication_year or 'n.d.'}). {meta.title or paper.paper_id}."
    ]
    venue = meta.journal or meta.publisher
    if venue:
        parts.append(venue + ".")
    if meta.volume:
        parts.append(meta.volume + (f": {meta.pages}" if meta.pages else ""))
    if doi:
        parts.append(f"https://doi.org/{doi}")
    return (
        (f"doi:{doi}" if doi else f"paper:{paper.paper_id}"),
        " ".join(parts),
        (f"https://doi.org/{doi}" if doi else None),
    )


def _evidence_type(method: str) -> str:
    return (
        "model_inferred"
        if method in ("inferred", "model_extracted")
        else "literature_reported"
    )


def _state_for_review(review_status: str) -> str:
    return {
        "accepted": "VERIFIED",
        "corrected": "VERIFIED",
        "rejected": "REJECTED",
    }.get(review_status, "PROVISIONAL")


def from_paper_knowledge(
    paper: PaperKnowledge,
    traits: TraitIndex,
    resolve_taxon: TaxonResolver,
) -> Normalized:
    source_id, citation, url = _citation(paper)
    license_ = RIGHTS_TO_LICENSE[paper.source.rights_status]
    entities = {e.entity_id: e for e in paper.entities}
    evidence = {e.evidence_id: e for e in paper.evidence}
    crosswalk: dict[str, dict[str, Any]] = {}
    unmapped: list[dict[str, Any]] = []
    assertions: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []

    def locate(ids: Iterable[str]) -> tuple[str | None, str | None]:
        rows = [evidence[i] for i in ids if i in evidence]
        if not rows:
            return None, None
        span = rows[0].span
        if span.page_start:
            locator = f"p. {span.page_start}" + (
                f"–{span.page_end}"
                if span.page_end and span.page_end != span.page_start
                else ""
            )
        elif span.section_id:
            locator = f"section {span.section_id}"
        else:
            locator = None
        return locator, " … ".join(r.excerpt for r in rows)

    def subject(
        entity_id: str, record_id: str
    ) -> tuple[dict[str, Any], str, str] | None:
        entity = entities.get(entity_id)
        if entity is None or entity.entity_type != "taxon":
            unmapped.append(
                _unmapped(
                    source_id,
                    record_id,
                    "subject_not_a_taxon_entity",
                    {"subject_id": entity_id},
                )
            )
            return None
        taxon_id = resolve_taxon(entity.normalized_name or entity.name)
        if taxon_id is None:
            unmapped.append(
                _unmapped(
                    source_id,
                    record_id,
                    "taxon_not_uniquely_resolved_in_canonical_taxonomy",
                    {"name": entity.name},
                )
            )
            return None
        attrs = entity.attributes
        level = next((lvl for key, lvl in LEVEL_ATTRIBUTES if attrs.get(key)), None)
        scope = "direct"
        if level is None and attrs.get("assertion_scope") == "taxon_description":
            level, scope = "taxon", "source_reported"
        if level is None:
            unmapped.append(
                _unmapped(
                    source_id,
                    record_id,
                    "assertion_level_not_stated",
                    {"subject": entity.name},
                )
            )
            return None
        return (
            {
                "taxon_id": taxon_id,
                "verbatim_taxon_name": entity.name,
                "specimen_id": attrs.get("specimen_id"),
                "population_id": attrs.get("population_id"),
                "observation_id": attrs.get("observation_id"),
            },
            level,
            scope,
        )

    def links_for(entity_id: str) -> list[dict[str, Any]]:
        out = []
        for rel in paper.relationships:
            domain = LINK_PREDICATES.get(rel.predicate)
            if rel.subject_id != entity_id or domain is None:
                continue
            target = entities.get(rel.object_id)
            external = (
                target.external_ids[0].value if target and target.external_ids else None
            )
            out.append(
                {
                    "domain": domain,
                    "target_id": external or f"{source_id}#{rel.object_id}",
                    "target_label": target.name if target else rel.object_id,
                    "relation": rel.predicate,
                    "source_id": source_id,
                    "note": "Context link reported by the same source; it does not assert that the trait causes the relation.",
                }
            )
        return out

    def habitats_for(entity_id: str) -> list[str]:
        return [
            entities[rel.object_id].name
            for rel in paper.relationships
            if rel.subject_id == entity_id
            and rel.predicate == "grows_in_habitat"
            and rel.object_id in entities
        ]

    def provenance(
        record_id: str, prov: Any, ids: Iterable[str], fallback_text: str
    ) -> dict[str, Any]:
        locator, excerpt = locate(ids)
        return {
            "source_id": source_id,
            "source_kind": "publication",
            "original_record_id": record_id,
            "citation": citation,
            "license": license_,
            "evidence_type": _evidence_type(prov.method),
            "source_url": url,
            "locator": locator,
            "original_text": excerpt or fallback_text,
            "extraction_method": prov.method,
            "review_status": prov.review_status,
        }

    for m in paper.measurements:
        definition = traits.resolve(m.property)
        if definition is None or definition.value_kind != "quantitative":
            unmapped.append(
                _unmapped(
                    source_id,
                    m.measurement_id,
                    "trait_not_registered",
                    m.model_dump(mode="json"),
                )
            )
            continue
        resolved = subject(m.subject_id, m.measurement_id)
        if resolved is None:
            continue
        subj, level, scope = resolved
        rng = RANGE_RE.match(m.value_text) if m.qualifier == "range" else None
        if rng:
            unit = rng.group(3) or m.unit
            lo, hi = (
                convert(float(rng.group(1)), unit, definition.unit),
                convert(float(rng.group(2)), unit, definition.unit),
            )
            if lo is None or hi is None:
                unmapped.append(
                    _unmapped(
                        source_id,
                        m.measurement_id,
                        "value_or_unit_not_convertible",
                        m.model_dump(mode="json"),
                    )
                )
                continue
            value = {
                "kind": "range",
                "minimum": lo,
                "maximum": hi,
                "unit": definition.unit,
                "statistic": "range",
                "n": m.sample_size,
                "verbatim": m.value_text,
            }
        else:
            converted = (
                convert(m.value, m.unit, definition.unit)
                if m.value is not None
                else None
            )
            if converted is None:
                unmapped.append(
                    _unmapped(
                        source_id,
                        m.measurement_id,
                        "value_or_unit_not_convertible",
                        m.model_dump(mode="json"),
                    )
                )
                continue
            qualifier = _norm(m.qualifier) or "single"
            value = {
                "kind": "quantitative",
                "numeric": converted,
                "unit": definition.unit,
                "statistic": qualifier if qualifier in STATISTICS else "single",
                "n": m.sample_size,
                "verbatim": m.value_text,
            }
        crosswalk[f"tb:lit:{paper.paper_id}:{m.measurement_id}"] = {
            "source_record_kind": "measurement",
            "kg_object_key": kg_measurement_key(paper.paper_id, m.measurement_id),
            "source_document_id": source_id,
        }
        assertions.append(
            {
                "assertion_id": f"tb:lit:{paper.paper_id}:{m.measurement_id}",
                "trait_id": definition.trait_id,
                "level": level,
                "subject": subj,
                "value": value,
                "provenance": provenance(
                    m.measurement_id, m.provenance, m.evidence_ids, m.value_text
                ),
                "evidence_state": _state_for_review(m.provenance.review_status),
                "scope_basis": scope,
                # Extraction confidence is fidelity to the source, and only
                # recorded when the extractor reported one.
                "confidence": m.provenance.confidence,
                "habitats": habitats_for(m.subject_id),
                "links": links_for(m.subject_id),
            }
        )

    for claim in paper.claims:
        predicate = claim.predicate or ""
        if predicate == "has_trait_state":
            state_entity = entities.get((claim.object_ids or [""])[0])
            attrs = state_entity.attributes if state_entity else {}
            definition = traits.resolve(attrs.get("trait"))
            state_id = (
                TraitIndex.state(definition, attrs.get("state")) if definition else None
            )
            if definition is None or state_id is None:
                unmapped.append(
                    _unmapped(
                        source_id,
                        claim.claim_id,
                        "state_not_registered",
                        claim.model_dump(mode="json"),
                    )
                )
                continue
            resolved = subject((claim.subject_ids or [""])[0], claim.claim_id)
            if resolved is None:
                continue
            subj, level, scope = resolved
            state = _state_for_review(claim.provenance.review_status)
            if claim.polarity == "uncertain" and state == "VERIFIED":
                state = "PROVISIONAL"
            crosswalk[f"tb:lit:{paper.paper_id}:{claim.claim_id}"] = {
                "source_record_kind": "claim",
                "kg_object_key": kg_claim_key(
                    paper.paper_id, claim.claim_id, claim.claim_type
                ),
                "source_document_id": source_id,
            }
            assertions.append(
                {
                    "assertion_id": f"tb:lit:{paper.paper_id}:{claim.claim_id}",
                    "trait_id": definition.trait_id,
                    "level": level,
                    "subject": subj,
                    "value": {
                        "kind": "categorical",
                        "state_id": state_id,
                        "verbatim": attrs.get("state"),
                    },
                    "provenance": provenance(
                        claim.claim_id,
                        claim.provenance,
                        claim.evidence_ids,
                        claim.statement,
                    ),
                    "evidence_state": state,
                    "scope_basis": scope,
                    "confidence": claim.provenance.confidence,
                    "habitats": habitats_for(claim.subject_ids[0]),
                    "links": links_for(claim.subject_ids[0]),
                }
            )
        elif predicate in ENVIRONMENT_PREDICATES:
            kind, hypothesis_scope = ENVIRONMENT_PREDICATES[predicate]
            trait_entity = entities.get((claim.subject_ids or [""])[0])
            env_entity = entities.get((claim.object_ids or [""])[0])
            definition = traits.resolve(
                (trait_entity.attributes.get("trait") if trait_entity else None)
                or (trait_entity.name if trait_entity else None)
            )
            if (
                definition is None
                or env_entity is None
                or env_entity.entity_type != "environmental_factor"
            ):
                unmapped.append(
                    _unmapped(
                        source_id,
                        claim.claim_id,
                        "environment_relation_unmappable",
                        claim.model_dump(mode="json"),
                    )
                )
                continue
            scope_names = list(trait_entity.attributes.get("taxon_scope") or [])
            scope_ids = [resolve_taxon(n) for n in scope_names]
            if any(t is None for t in scope_ids):
                # Dropping an unresolved name would broaden the claim (an empty
                # scope reads as "every taxon"); keep the raw claim instead.
                unmapped.append(
                    _unmapped(
                        source_id,
                        claim.claim_id,
                        "taxon_scope_not_resolved",
                        claim.model_dump(mode="json"),
                    )
                )
                continue
            relations.append(
                {
                    "relation_id": f"tb:rel:{paper.paper_id}:{claim.claim_id}",
                    "trait_id": definition.trait_id,
                    "environment_variable": env_entity.name,
                    "claim_kind": kind,
                    "statement": claim.statement,
                    "hypothesis_scope": hypothesis_scope,
                    "taxon_scope": scope_ids,
                    "provenance": provenance(
                        claim.claim_id,
                        claim.provenance,
                        claim.evidence_ids,
                        claim.statement,
                    ),
                }
            )

    if not assertions and not relations:
        return Normalized(None, unmapped)
    payload = {"assertions": assertions, "environment_relations": relations}
    batch = TraitBankBatch.model_validate(
        {
            "contract_version": CONTRACT_VERSION,
            "batch_key": _batch_key(
                "literature_extraction", {"paper": paper.paper_id, **payload}
            ),
            "producer": "literature_extraction",
            **payload,
        }
    )
    return Normalized(batch, unmapped, crosswalk)


# ----------------------------------------------------------------- EOL TraitBank
#: EOL TraitBank keeps a measured value in ``measurement`` (source units) and
#: ``normal_measurement`` (normalized units), and a categorical value as an
#: ontology term (``value_uri`` / ``object_term``) or ``literal``
#: (EOL/publishing ``doc/trait-schema.md``). ``TraitBankHarvester._normalize``
#: reads only ``value``/``measurementValue``/``object``, so on a real EOL
#: export its ``value_raw`` is empty. Pairs are checked in order and a value is
#: always taken with its own unit, never mixed across pairs.
EOL_VALUE_PAIRS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("measurement", ("units", "units_term", "units_uri")),
    ("normal_measurement", ("normal_units", "normal_units_term", "normal_units_uri")),
    ("value_uri", ()),
    ("object_term", ()),
    ("literal", ()),
)


def _eol_value_and_units(rec: dict[str, Any], raw: dict[str, Any]) -> tuple[Any, str]:
    value = rec.get("value_raw")
    if value not in (None, ""):
        return value, rec.get("units_raw") or ""
    for value_key, unit_keys in EOL_VALUE_PAIRS:
        candidate = raw.get(value_key)
        if candidate not in (None, ""):
            unit = next((str(raw[k]).strip() for k in unit_keys if raw.get(k)), "")
            return str(candidate).strip(), unit
    return None, ""


def _http_url(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if text.startswith(("https://", "http://")) else None


def _number(raw: Any) -> float | None:
    try:
        number = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def from_traitbank_harvester(
    records: Iterable[dict[str, Any]],
    traits: TraitIndex,
    resolve_taxon: TaxonResolver,
    *,
    dataset_citation: str,
    dataset_license: str,
) -> Normalized:
    """EOL rows are resource-reported taxon-level records (``AVAILABLE``, not verified)."""
    unmapped: list[dict[str, Any]] = []
    assertions: list[dict[str, Any]] = []
    for rec in records:
        raw = rec.get("raw") or {}
        record_id = str(raw.get("eol_pk") or raw.get("record_id") or "").strip()
        resource_id = str(raw.get("resource_id") or "").strip()
        if not resource_id:
            # Without the contributing resource there is no attributable
            # source; one is never manufactured.
            unmapped.append(
                _unmapped(
                    "eol-traitbank", record_id or "(none)", "resource_id_missing", raw
                )
            )
            continue
        source_id = f"eol-traitbank:resource:{resource_id}"
        if not record_id:
            unmapped.append(
                _unmapped(source_id, "(none)", "original_record_id_missing", raw)
            )
            continue
        definition = traits.resolve(rec.get("trait_raw"))
        if definition is None:
            unmapped.append(
                _unmapped(source_id, record_id, "trait_not_registered", raw)
            )
            continue
        taxon_id = resolve_taxon(rec.get("scientific_name") or "")
        if taxon_id is None:
            unmapped.append(
                _unmapped(
                    source_id,
                    record_id,
                    "taxon_not_uniquely_resolved_in_canonical_taxonomy",
                    raw,
                )
            )
            continue
        value_raw, units_raw = _eol_value_and_units(rec, raw)
        verbatim = (
            " ".join(x for x in (str(value_raw or ""), units_raw) if x).strip() or None
        )
        reported_statistic = _norm(
            raw.get("statistical_method") or raw.get("statistical_method_term")
        )
        if reported_statistic and reported_statistic not in STATISTICS:
            # A reported method (often an ontology URI in EOL) that is not
            # mapped must not be silently read as a single value.
            unmapped.append(
                _unmapped(source_id, record_id, "statistical_method_not_mapped", raw)
            )
            continue
        statistic = reported_statistic or "single"
        sample_size = _number(raw.get("sample_size"))
        if sample_size is not None and (
            sample_size < 0 or not float(sample_size).is_integer()
        ):
            # A fractional or negative count is malformed provenance; it is
            # returned unmapped rather than truncated into a different number.
            unmapped.append(
                _unmapped(source_id, record_id, "sample_size_not_a_count", raw)
            )
            continue
        if value_raw in (None, ""):
            value: dict[str, Any] = {
                "kind": "missing",
                "missing_reason": "not_reported",
                "verbatim": verbatim,
            }
            state = "UNKNOWN"
        elif definition.value_kind == "categorical":
            state_id = TraitIndex.state(
                definition, raw.get("value_uri")
            ) or TraitIndex.state(definition, str(value_raw))
            if state_id is None:
                unmapped.append(
                    _unmapped(source_id, record_id, "state_not_registered", raw)
                )
                continue
            value, state = (
                {"kind": "categorical", "state_id": state_id, "verbatim": verbatim},
                "AVAILABLE",
            )
        else:
            number = _number(value_raw)
            converted = (
                convert(number, units_raw, definition.unit)
                if number is not None
                else None
            )
            if converted is None:
                unmapped.append(
                    _unmapped(
                        source_id, record_id, "value_or_unit_not_convertible", raw
                    )
                )
                continue
            value = {
                "kind": "quantitative",
                "numeric": converted,
                "unit": definition.unit,
                "statistic": statistic if statistic in STATISTICS else "single",
                "n": int(sample_size) if sample_size is not None else None,
                "verbatim": verbatim,
            }
            state = "AVAILABLE"
        assertions.append(
            {
                "assertion_id": f"tb:eol:{record_id}",
                "trait_id": definition.trait_id,
                "level": "taxon",
                "subject": {
                    "taxon_id": taxon_id,
                    "verbatim_taxon_name": rec.get("scientific_name") or "",
                },
                "value": value,
                "provenance": {
                    "source_id": source_id,
                    "source_kind": "dataset",
                    "original_record_id": record_id,
                    "citation": (raw.get("citation") or "").strip() or dataset_citation,
                    "license": (raw.get("license") or "").strip() or dataset_license,
                    "evidence_type": "dataset_import",
                    "contributor": (raw.get("contributor") or "").strip() or None,
                    # The harvester's reference_raw falls back to citation text;
                    # only a real http(s) reference becomes source_url.
                    "source_url": _http_url(rec.get("reference_raw")),
                    "original_text": f"{rec.get('scientific_name')} | {rec.get('trait_raw')} | {verbatim or ''}",
                    "extraction_method": "imported",
                },
                "evidence_state": state,
                "scope_basis": "source_reported",
                "life_stage": (raw.get("lifestage") or None),
            }
        )
    if not assertions:
        return Normalized(None, unmapped)
    batch = TraitBankBatch.model_validate(
        {
            "contract_version": CONTRACT_VERSION,
            "batch_key": _batch_key("eol_traitbank", assertions),
            "producer": "eol_traitbank",
            "assertions": assertions,
        }
    )
    return Normalized(
        batch,
        unmapped,
        {
            a.assertion_id: {
                "source_record_kind": "dataset_record",
                "kg_object_key": None,
                "source_document_id": a.provenance.source_id,
            }
            for a in batch.assertions
        },
    )

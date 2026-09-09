"""NAOCC machine-readable evidence schema.

Defines the structured evidence record that downstream extraction pipelines must
populate for each NAOCC source that has been scientist-reviewed and cleared for
evidence entry. Separate from the corpus manifest (which records source candidates)
and from the Knowledge Graph (which records accepted scientific truth).

Evidence records at this layer are:
- PROVISIONAL: not publishable until reviewed.
- PROVENANCE-ANCHORED: every field must name its source and evidence class.
- UNCERTAINTY-AWARE: absence of data is represented as unavailable, never as zero.
- LOCALITY-SAFE: coordinate data below 10km resolution is forbidden.

The evidence class taxonomy mirrors the Packet 1 (Flywheel 1/6) contracts from #1138.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.naocc.corpus_manifest import EvidenceClass

SCHEMA_VERSION = "naocc-evidence-schema/v1"

_UNAVAILABLE = "UNAVAILABLE"


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INDETERMINATE = "indeterminate"


class ConservationThreatCategory(str, Enum):
    CRITICALLY_ENDANGERED = "CR"
    ENDANGERED = "EN"
    VULNERABLE = "VU"
    NEAR_THREATENED = "NT"
    LEAST_CONCERN = "LC"
    DATA_DEFICIENT = "DD"
    NOT_EVALUATED = "NE"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class ProvenanceAnchor:
    """Source binding for one piece of extracted evidence."""

    source_id: str
    doi: str
    page_or_section: str
    extraction_method: str
    extracted_at: str
    reviewed_by: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "doi": self.doi,
            "page_or_section": self.page_or_section,
            "extraction_method": self.extraction_method,
            "extracted_at": self.extracted_at,
            "reviewed_by": self.reviewed_by,
        }


@dataclass(frozen=True)
class NAOCCEvidenceRecord:
    """One extracted, provenance-anchored evidence record from a NAOCC-related source.

    All fields not directly supported by the source must be set to the module
    constant ``_UNAVAILABLE``; never use ``None``, ``0``, or ``""`` for data
    that was not found in the source.
    """

    record_id: str
    source_id: str
    taxon_name: str
    taxon_authority: str
    evidence_class: EvidenceClass
    confidence_level: ConfidenceLevel

    # Conservation fields
    conservation_status: str
    threat_category: ConservationThreatCategory
    population_trend: str
    habitat_description: str

    # Mycorrhizal fields
    fungal_partner: str
    fungal_lineage: str
    mycorrhizal_specificity: str

    # Geography — coarse only; no protected localities at fine resolution
    geography_region: str
    elevation_range_m: str

    # Methods and sampling context
    methods_summary: str
    sample_size_description: str

    # Results and uncertainty
    results_summary: str
    limitations: str
    contradictions: str

    # Provenance
    provenance: ProvenanceAnchor

    # These are not a finding of presence/absence
    not_publishable: bool = True
    is_provisional: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "source_id": self.source_id,
            "taxon_name": self.taxon_name,
            "taxon_authority": self.taxon_authority,
            "evidence_class": self.evidence_class.value,
            "confidence_level": self.confidence_level.value,
            "conservation_status": self.conservation_status,
            "threat_category": self.threat_category.value,
            "population_trend": self.population_trend,
            "habitat_description": self.habitat_description,
            "fungal_partner": self.fungal_partner,
            "fungal_lineage": self.fungal_lineage,
            "mycorrhizal_specificity": self.mycorrhizal_specificity,
            "geography_region": self.geography_region,
            "elevation_range_m": self.elevation_range_m,
            "methods_summary": self.methods_summary,
            "sample_size_description": self.sample_size_description,
            "results_summary": self.results_summary,
            "limitations": self.limitations,
            "contradictions": self.contradictions,
            "provenance": self.provenance.to_dict(),
            "not_publishable": self.not_publishable,
            "is_provisional": self.is_provisional,
        }


def validate_evidence_record(record: NAOCCEvidenceRecord) -> list[str]:
    """Return a list of validation errors; empty list means the record is well-formed.

    Calyx rules:
    - Provenance is required; no record may enter without a source binding.
    - No self-generated Calyx statement may be accepted as evidence for itself.
    - Sensitive locality data (coordinates below 10km) is forbidden.
    - Records must start as not_publishable and is_provisional.
    """
    errors: list[str] = []
    if not record.record_id.strip():
        errors.append("record_id is required")
    if not record.source_id.strip():
        errors.append("source_id is required; evidence must have a named source")
    if not record.taxon_name.strip():
        errors.append("taxon_name is required")
    if not record.provenance.source_id.strip():
        errors.append("provenance.source_id is required; no orphaned evidence")
    if record.provenance.source_id != record.source_id:
        errors.append(
            "provenance.source_id must match record.source_id to prevent orphaned binding"
        )
    if not record.not_publishable:
        errors.append(
            "not_publishable must be True; evidence can only be cleared for publication "
            "by the governed review pipeline, not at extraction time"
        )
    if not record.is_provisional:
        errors.append(
            "is_provisional must be True at extraction; only the KG review step may clear it"
        )
    # No coordinate fields exist at this schema level — the check is structural.
    # If any future field contains lat/lon, it must go through the locality gateway.
    return errors

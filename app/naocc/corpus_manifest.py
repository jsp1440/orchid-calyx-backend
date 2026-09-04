"""NAOCC canonical public corpus manifest.

Records candidate sources from publicly available NAOCC-related literature and
linked public datasets. Each entry carries provenance, access status, and
evidence-class metadata so downstream extraction can distinguish discovered
sources from extracted evidence.

Rules:
- All sources must be PUBLIC (peer-reviewed, public reports, public data portals).
- access_status is ``candidate_unverified`` until a scientist marks it ``verified``.
- No sensitive locality data may be recorded in this manifest.
- ``unavailable`` means the document was not found or cannot be accessed; it is
  not a finding that the scientific content is absent.
- A source added here is a corpus candidate, not scientific evidence. Extraction
  and review must happen before any claim can enter the Knowledge Graph.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

SCHEMA_VERSION = "naocc-corpus-manifest/v1"


class AccessStatus(str, Enum):
    VERIFIED_PUBLIC = "verified_public"
    CANDIDATE_UNVERIFIED = "candidate_unverified"
    FULL_TEXT_AVAILABLE = "full_text_available"
    ABSTRACT_ONLY = "abstract_only"
    UNAVAILABLE = "unavailable"


class SourceType(str, Enum):
    PEER_REVIEWED_PAPER = "peer_reviewed_paper"
    CONSERVATION_ASSESSMENT = "conservation_assessment"
    PROTOCOL_DOCUMENT = "protocol_document"
    PUBLIC_DATABASE = "public_database"
    SUPPLEMENTARY_DATA = "supplementary_data"
    GRAY_LITERATURE = "gray_literature"


class EvidenceClass(str, Enum):
    OBSERVATION = "observation"
    EXTRACTED_CLAIM = "extracted_claim"
    SYNTHESIS = "synthesis"
    HYPOTHESIS = "hypothesis"
    CONCLUSION = "conclusion"


@dataclass(frozen=True)
class NAOCCSource:
    """One candidate public source in the NAOCC corpus manifest.

    All fields required; use empty strings for unknown identifiers rather than None
    so schema validation can distinguish truly unknown from missing.
    """

    source_id: str
    title: str
    source_type: SourceType
    access_status: AccessStatus
    primary_url: str
    doi: str
    author_year: str
    taxon_scope: tuple[str, ...]
    evidence_classes_present: tuple[EvidenceClass, ...]
    conservation_domain: bool
    mycorrhizal_domain: bool
    occurrence_domain: bool
    notes: str
    provenance: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "title": self.title,
            "source_type": self.source_type.value,
            "access_status": self.access_status.value,
            "primary_url": self.primary_url,
            "doi": self.doi,
            "author_year": self.author_year,
            "taxon_scope": list(self.taxon_scope),
            "evidence_classes_present": [e.value for e in self.evidence_classes_present],
            "conservation_domain": self.conservation_domain,
            "mycorrhizal_domain": self.mycorrhizal_domain,
            "occurrence_domain": self.occurrence_domain,
            "notes": self.notes,
            "provenance": self.provenance,
        }


# ---------------------------------------------------------------------------
# Seed: known public NAOCC-related sources
# All entries are candidate_unverified until a scientist marks them verified.
# URLs and DOIs are recorded as-known; scientist must verify before extraction.
# ---------------------------------------------------------------------------

KNOWN_PUBLIC_SOURCES: tuple[NAOCCSource, ...] = (
    NAOCCSource(
        source_id="naocc-home-001",
        title="North American Orchid Conservation Center — public website and conservation program overview",
        source_type=SourceType.PROTOCOL_DOCUMENT,
        access_status=AccessStatus.CANDIDATE_UNVERIFIED,
        primary_url="https://www.naocc.org",
        doi="",
        author_year="NAOCC (ongoing)",
        taxon_scope=("Orchidaceae",),
        evidence_classes_present=(EvidenceClass.OBSERVATION,),
        conservation_domain=True,
        mycorrhizal_domain=False,
        occurrence_domain=True,
        notes=(
            "Primary public program website. Contains conservation status information, "
            "species profiles, and program scope. Scientist must verify current content "
            "before extraction."
        ),
        provenance="Seed from issue #1096 infrastructure layer; candidate_unverified.",
    ),
    NAOCCSource(
        source_id="naocc-iucn-001",
        title="IUCN Red List assessments for North American native orchid taxa",
        source_type=SourceType.PUBLIC_DATABASE,
        access_status=AccessStatus.CANDIDATE_UNVERIFIED,
        primary_url="https://www.iucnredlist.org",
        doi="",
        author_year="IUCN (ongoing)",
        taxon_scope=("Orchidaceae", "native North American taxa"),
        evidence_classes_present=(EvidenceClass.OBSERVATION, EvidenceClass.CONCLUSION),
        conservation_domain=True,
        mycorrhizal_domain=False,
        occurrence_domain=True,
        notes=(
            "Public IUCN Red List entries for native North American orchid taxa. "
            "Provides threat category, population trend, and distribution data. "
            "Scientist must verify which taxa are NAOCC-covered and extract with provenance."
        ),
        provenance="Seed from issue #1096 infrastructure layer; candidate_unverified.",
    ),
    NAOCCSource(
        source_id="naocc-gbif-001",
        title="GBIF North American native orchid occurrence records (public download)",
        source_type=SourceType.PUBLIC_DATABASE,
        access_status=AccessStatus.CANDIDATE_UNVERIFIED,
        primary_url="https://www.gbif.org",
        doi="",
        author_year="GBIF (ongoing)",
        taxon_scope=("Orchidaceae",),
        evidence_classes_present=(EvidenceClass.OBSERVATION,),
        conservation_domain=False,
        mycorrhizal_domain=False,
        occurrence_domain=True,
        notes=(
            "GBIF public occurrence downloads for North American orchid taxa. "
            "Scientist must apply locality sensitivity filter before any coordinate "
            "is stored or used. Do not record coordinates at resolution below 10km for "
            "sensitive taxa without explicit data-governance review."
        ),
        provenance="Seed from issue #1096 infrastructure layer; candidate_unverified.",
    ),
    NAOCCSource(
        source_id="naocc-mycorrhiza-lit-001",
        title=(
            "Mycorrhizal associations of North American native orchids — "
            "candidate literature cluster (peer-reviewed)"
        ),
        source_type=SourceType.PEER_REVIEWED_PAPER,
        access_status=AccessStatus.CANDIDATE_UNVERIFIED,
        primary_url="",
        doi="",
        author_year="multiple authors (see notes)",
        taxon_scope=("Orchidaceae",),
        evidence_classes_present=(
            EvidenceClass.OBSERVATION,
            EvidenceClass.EXTRACTED_CLAIM,
        ),
        conservation_domain=True,
        mycorrhizal_domain=True,
        occurrence_domain=False,
        notes=(
            "Placeholder cluster for peer-reviewed literature on orchid mycorrhizal "
            "associations relevant to North American native taxa. Scientist must identify "
            "specific papers and verify DOIs before extraction. Known relevant journals "
            "include Mycorrhiza, American Journal of Botany, Ecological Applications. "
            "Do not populate this entry with fabricated citations."
        ),
        provenance="Seed from issue #1096 infrastructure layer; candidate_unverified.",
    ),
    NAOCCSource(
        source_id="naocc-restoration-lit-001",
        title=(
            "Orchid reintroduction and restoration literature cluster — "
            "North American public corpus"
        ),
        source_type=SourceType.PEER_REVIEWED_PAPER,
        access_status=AccessStatus.CANDIDATE_UNVERIFIED,
        primary_url="",
        doi="",
        author_year="multiple authors (see notes)",
        taxon_scope=("Orchidaceae",),
        evidence_classes_present=(
            EvidenceClass.OBSERVATION,
            EvidenceClass.CONCLUSION,
            EvidenceClass.HYPOTHESIS,
        ),
        conservation_domain=True,
        mycorrhizal_domain=True,
        occurrence_domain=True,
        notes=(
            "Placeholder cluster for peer-reviewed literature on orchid restoration "
            "and reintroduction in North America. Relevant topics include symbiotic "
            "germination, ex-situ conservation, and mycorrhizal inoculation. "
            "Scientist must identify specific papers and verify DOIs."
        ),
        provenance="Seed from issue #1096 infrastructure layer; candidate_unverified.",
    ),
)


@dataclass
class CorpusManifest:
    """Machine-readable corpus manifest for the NAOCC POC."""

    schema_version: str
    generated_at: str
    graph_mutation: bool
    sources: list[NAOCCSource]
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "graph_mutation": self.graph_mutation,
            "source_count": len(self.sources),
            "sources": [s.to_dict() for s in self.sources],
            "notes": self.notes,
        }

    def verified_sources(self) -> list[NAOCCSource]:
        return [s for s in self.sources if s.access_status == AccessStatus.VERIFIED_PUBLIC]

    def candidate_sources(self) -> list[NAOCCSource]:
        return [
            s for s in self.sources
            if s.access_status == AccessStatus.CANDIDATE_UNVERIFIED
        ]


def build_corpus_manifest(
    extra_sources: list[NAOCCSource] | None = None,
) -> CorpusManifest:
    """Build the canonical NAOCC corpus manifest.

    Args:
        extra_sources: Optional additional verified sources to include beyond
            the seed set. Must each carry access_status != CANDIDATE_UNVERIFIED
            if they are to count as usable for extraction.

    Returns:
        CorpusManifest with provenance and no KG mutation.
    """
    all_sources = list(KNOWN_PUBLIC_SOURCES) + (extra_sources or [])
    return CorpusManifest(
        schema_version=SCHEMA_VERSION,
        generated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        graph_mutation=False,
        sources=all_sources,
        notes=(
            "All sources are candidate_unverified until a scientist marks them verified "
            "and extraction has been reviewed. No source in this manifest constitutes "
            "scientific evidence in Orchid Continuum; evidence only enters the KG after "
            "the full extraction + review pipeline."
        ),
    )

"""Provider-free federation candidate inventory for OC-COMPLETE-004.

This module intentionally performs no network access and no scientific writes. It
records candidate-source metadata so later adapter work can be admitted only after
rights, access, provenance, taxonomy, and locality review.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib


class RightsState(StrEnum):
    OPEN = "open"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"


class AccessState(StrEnum):
    API = "api"
    BULK = "bulk"
    REPOSITORY = "repository"
    UNKNOWN = "unknown"


class CandidateDisposition(StrEnum):
    KEEP = "keep"
    ADD = "add"
    DEFER = "defer"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class FederationCandidate:
    source_owner: str
    source_name: str
    identity: str
    access: AccessState
    rights: RightsState
    domains: tuple[str, ...]
    identifiers: tuple[str, ...]
    overlap: str
    incremental_value: str
    taxonomy_reconciliation: str
    provenance_contract: str
    locality_risk: str
    implementation_cost: str
    requested_disposition: CandidateDisposition

    @property
    def fingerprint(self) -> str:
        normalized = "|".join(
            (
                self.source_owner.strip().casefold(),
                self.source_name.strip().casefold(),
                self.identity.strip().casefold(),
            )
        )
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @property
    def disposition(self) -> CandidateDisposition:
        """Fail closed when rights or access have not been established."""
        if self.rights is RightsState.UNKNOWN or self.access is AccessState.UNKNOWN:
            return CandidateDisposition.DEFER
        if self.rights is RightsState.RESTRICTED:
            return CandidateDisposition.REJECT
        return self.requested_disposition


def deduplicate_candidates(
    candidates: tuple[FederationCandidate, ...],
) -> tuple[FederationCandidate, ...]:
    """Return first-seen candidates by stable source identity fingerprint."""
    seen: set[str] = set()
    result: list[FederationCandidate] = []
    for candidate in candidates:
        if candidate.fingerprint in seen:
            continue
        seen.add(candidate.fingerprint)
        result.append(candidate)
    return tuple(result)


def build_default_candidate_inventory() -> tuple[FederationCandidate, ...]:
    """Return the deterministic fixture-backed first federation inventory.

    Rights are intentionally UNKNOWN where repository-local evidence has not yet
    established an admissible license. UNKNOWN can never auto-admit an adapter.
    """
    candidates = (
        FederationCandidate(
            source_owner="Zenodo depositors",
            source_name="Global Orchid Pollination Database 2024",
            identity="doi:10.5281/zenodo.14601785",
            access=AccessState.REPOSITORY,
            rights=RightsState.UNKNOWN,
            domains=("pollination", "interactions", "traits"),
            identifiers=("10.5281/zenodo.14601785",),
            overlap="Requires comparison with canonical GloBI and curated pollination evidence",
            incremental_value="Potential orchid-specific breeding-system and pollinator coverage",
            taxonomy_reconciliation="Resolve source-reported orchid names through canonical taxonomy with source string retained",
            provenance_contract="Preserve DOI, record version, file identity/hash, row-level source anchors where available",
            locality_risk="Review geography fields before any public exposure",
            implementation_cost="medium",
            requested_disposition=CandidateDisposition.ADD,
        ),
        FederationCandidate(
            source_owner="Zenodo depositors",
            source_name="Caladenia huegelii mycorrhizal/environment dataset",
            identity="doi:10.5281/zenodo.15426257",
            access=AccessState.REPOSITORY,
            rights=RightsState.UNKNOWN,
            domains=("mycorrhiza", "molecular", "environment"),
            identifiers=("10.5281/zenodo.15426257",),
            overlap="Requires comparison with existing UNITE/mycorrhizal and environmental evidence",
            incremental_value="Potential fungal OTU, ITS, sample, and environment linkage",
            taxonomy_reconciliation="Keep fungal sequence/OTU identity separate from reconciled taxon assertions",
            provenance_contract="Preserve DOI, file hash, sample identity, sequence identity, and exact source fields",
            locality_risk="high: sample/site metadata must be classified before exposure",
            implementation_cost="high",
            requested_disposition=CandidateDisposition.ADD,
        ),
        FederationCandidate(
            source_owner="GBIF",
            source_name="GBIF occurrence and media federation",
            identity="https://www.gbif.org/",
            access=AccessState.API,
            rights=RightsState.OPEN,
            domains=("occurrence", "media", "herbaria"),
            identifiers=("gbif",),
            overlap="Existing canonical provider; retain rather than create a duplicate harvester",
            incremental_value="Baseline occurrence/media federation already represented in Continuum",
            taxonomy_reconciliation="Use canonical taxon mapping while retaining GBIF keys and verbatim names",
            provenance_contract="Preserve dataset key, occurrence key, source institution, license, and retrieval identity",
            locality_risk="Apply canonical locality policy to coordinates and occurrence metadata",
            implementation_cost="existing",
            requested_disposition=CandidateDisposition.KEEP,
        ),
        FederationCandidate(
            source_owner="UNITE Community",
            source_name="UNITE fungal reference data",
            identity="https://unite.ut.ee/",
            access=AccessState.REPOSITORY,
            rights=RightsState.UNKNOWN,
            domains=("mycorrhiza", "molecular"),
            identifiers=("unite",),
            overlap="Known canonical fungal source; exact current release/access terms require verification",
            incremental_value="Fungal taxon/sequence reconciliation for orchid mycorrhizal evidence",
            taxonomy_reconciliation="Do not coerce sequence hypotheses into orchid-fungus observed associations",
            provenance_contract="Preserve release, sequence/reference identity, source citation, and taxonomic hypothesis",
            locality_risk="low at reference level; linked sample data requires separate review",
            implementation_cost="medium",
            requested_disposition=CandidateDisposition.KEEP,
        ),
        FederationCandidate(
            source_owner="Zenodo depositors",
            source_name="Drakaeinae Tulasnella phylogenetic association dataset",
            identity="doi:10.5281/zenodo.7145605",
            access=AccessState.REPOSITORY,
            rights=RightsState.UNKNOWN,
            domains=("mycorrhiza", "molecular", "phylogeny"),
            identifiers=("10.5281/zenodo.7145605",),
            overlap="Compare with canonical fungal-association evidence before admission",
            incremental_value="Potential Drakaeinae/Tulasnella phylogenetic and association evidence",
            taxonomy_reconciliation="Separate phylogenetic relationship from directly observed association",
            provenance_contract="Preserve DOI, alignment identity/hash, paper linkage, and assertion evidence class",
            locality_risk="Review specimen/sample localities independently of sequence evidence",
            implementation_cost="medium",
            requested_disposition=CandidateDisposition.ADD,
        ),
        FederationCandidate(
            source_owner="IUCN",
            source_name="IUCN conservation assessments",
            identity="https://www.iucnredlist.org/",
            access=AccessState.UNKNOWN,
            rights=RightsState.UNKNOWN,
            domains=("conservation", "habitat"),
            identifiers=("iucn-red-list",),
            overlap="Known conservation source family; exact redistribution/API rights not established by this fixture",
            incremental_value="Conservation assessment context where lawfully reusable",
            taxonomy_reconciliation="Preserve assessed taxon/version and map separately to canonical taxonomy",
            provenance_contract="Require assessment/version/source identity and rights state before ingestion",
            locality_risk="Potential sensitive range/locality information; fail closed",
            implementation_cost="unknown",
            requested_disposition=CandidateDisposition.ADD,
        ),
    )
    return deduplicate_candidates(candidates)

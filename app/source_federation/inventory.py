"""Provider-free federation candidate inventory for OC-COMPLETE-004.

This module intentionally performs no network access and no scientific writes. It
records candidate-source metadata so later adapter work can be admitted only after
rights, access, provenance, taxonomy, and locality review.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum


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
    license_identifier: str | None = None
    locality_controls: tuple[str, ...] = ()
    source_url: str | None = None
    update_cadence: str = "unknown"
    metadata_evidence: tuple[str, ...] = ()
    verification_note: str = ""

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
        """Fail closed until an ADD candidate has an auditable admission contract."""
        if self.rights is RightsState.RESTRICTED:
            return CandidateDisposition.REJECT
        if self.admission_blockers:
            return CandidateDisposition.DEFER
        return self.requested_disposition

    @property
    def admission_blockers(self) -> tuple[str, ...]:
        """Return stable reasons that prevent automatic adapter admission.

        Candidate discovery may retain incomplete metadata, but an ADD decision must
        not advance without explicit rights, access, provenance, and locality
        controls.  These are policy facts, not scientific conclusions.
        """
        blockers: list[str] = []
        if self.rights is RightsState.UNKNOWN:
            blockers.append("rights_unknown")
        if self.access is AccessState.UNKNOWN:
            blockers.append("access_unknown")

        if self.requested_disposition is CandidateDisposition.ADD:
            if not self.license_identifier or not self.license_identifier.strip():
                blockers.append("license_identifier_missing")
            if not self.identifiers:
                blockers.append("source_identifier_missing")
            if not self.provenance_contract.strip():
                blockers.append("provenance_contract_missing")
            if not self.source_url or not self.source_url.strip():
                blockers.append("source_url_missing")
            if not self.metadata_evidence:
                blockers.append("metadata_evidence_missing")
            if (
                not self.update_cadence.strip()
                or self.update_cadence.strip().casefold() == "unknown"
            ):
                blockers.append("update_cadence_unknown")

            locality_risk = self.locality_risk.strip().casefold()
            risk_levels = ("negligible", "low", "medium", "high", "unknown")
            if not locality_risk.startswith(risk_levels):
                blockers.append("locality_risk_unclassified")
            elif locality_risk.startswith("unknown"):
                blockers.append("locality_risk_unknown")
            elif locality_risk.startswith("high") and not self.locality_controls:
                blockers.append("locality_controls_missing")

        return tuple(blockers)


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
            source_owner="Ackerman et al.",
            source_name=(
                "Beyond the various contrivances by which orchids are pollinated"
            ),
            identity="doi:10.5281/zenodo.14601785",
            access=AccessState.REPOSITORY,
            rights=RightsState.UNKNOWN,
            domains=("pollination", "interactions", "traits"),
            identifiers=(
                "10.5281/zenodo.14601785",
                "10.5281/zenodo.7263689",
                "10.1093/botlinnean/boac082",
            ),
            overlap=(
                "Compare orchid-pollinator relationships with canonical GloBI and "
                "curated evidence; do not create a second interaction store"
            ),
            incremental_value=(
                "Orchid-specific breeding system, attraction mechanism, and named "
                "pollinator coverage across more than 2,900 species"
            ),
            taxonomy_reconciliation=(
                "Retain verbatim orchid and pollinator names, map through pinned "
                "canonical releases, and preserve unresolved names as uncertain"
            ),
            provenance_contract=(
                "Preserve version and concept DOIs, record timestamp, file checksum, "
                "row identity, cited literature, verbatim taxa/locality, authorship, "
                "and license; never publish source coordinates by default"
            ),
            locality_risk=(
                "high: source and ongoing derivative work contain locality and "
                "coordinate fields for orchid-pollinator records"
            ),
            implementation_cost="medium",
            requested_disposition=CandidateDisposition.ADD,
            locality_controls=(
                "strip_precise_coordinates",
                "respect_source_obscuring",
                "publish_generalized_region_only",
            ),
            source_url="https://zenodo.org/records/14601785",
            update_cadence=(
                "irregular depositor-driven versions; no guaranteed schedule"
            ),
            metadata_evidence=(
                "https://zenodo.org/records/14601785",
                "https://github.com/RaymondLTremblay/"
                "Global_Orchid_Pollinators/blob/main/README.md",
                "https://hdl.handle.net/10669/89284",
            ),
            verification_note=(
                "The maintainer project identifies concept DOI 10.5281/zenodo.7263689 "
                "as CC-BY-4.0, but the exact 14601785 version license was not directly "
                "retrievable during verification; rights remain UNKNOWN and DEFER"
            ),
        ),        FederationCandidate(
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

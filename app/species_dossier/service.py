from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence
from urllib.parse import unquote, urlparse
import re

from .models import FederationResolveRequest, FederationResolveResult, SpeciesAtlasEnvelope, SpeciesDossierEnvelope


class SpeciesRepository(Protocol):
    def get_dossier(self, taxon_id: str) -> SpeciesDossierEnvelope | None: ...
    def get_atlas(self, taxon_id: str) -> SpeciesAtlasEnvelope | None: ...
    def resolve_taxon_id(self, taxon_id: str) -> tuple[str, str] | None: ...
    def resolve_name(self, normalized_name: str) -> Sequence[tuple[str, str, str]]: ...
    def resolve_partner_slug(self, partner_slug: str, species_slug: str) -> Sequence[tuple[str, str, str]]: ...


@dataclass(frozen=True)
class SpeciesDossierService:
    repository: SpeciesRepository
    public_base_url: str = "https://orchidcontinuum.org"

    def dossier(self, taxon_id: str) -> SpeciesDossierEnvelope | None:
        return self.repository.get_dossier(taxon_id.strip())

    def atlas(self, taxon_id: str) -> SpeciesAtlasEnvelope | None:
        return self.repository.get_atlas(taxon_id.strip())

    def resolve(self, request: FederationResolveRequest) -> FederationResolveResult:
        if request.taxon_id:
            hit = self.repository.resolve_taxon_id(request.taxon_id.strip())
            if hit:
                taxon_id, accepted_name = hit
                return self._resolved(
                    taxon_id=taxon_id,
                    accepted_name=accepted_name,
                    incoming_name=request.name,
                    match_state="taxon_id",
                    request=request,
                )

        if request.partner_slug and request.partner_species_slug:
            slug_hits = list(
                self.repository.resolve_partner_slug(
                    request.partner_slug.strip().lower(),
                    request.partner_species_slug.strip(),
                )
            )
            result = self._from_hits(slug_hits, request, "partner_slug")
            if result.status != "unresolved":
                return result

        incoming_name = request.name or extract_species_name_from_url(str(request.source_url or ""))
        if not incoming_name:
            return FederationResolveResult(
                status="invalid",
                incoming_name=None,
                matched_name=None,
                match_state="none",
                partner_slug=request.partner_slug,
                reciprocal_source_url=request.source_url,
                explanation="No resolvable species name or canonical taxon identifier was supplied.",
            )

        normalized_name = normalize_scientific_name(incoming_name)
        if not normalized_name:
            return FederationResolveResult(
                status="invalid",
                incoming_name=incoming_name,
                matched_name=None,
                match_state="none",
                partner_slug=request.partner_slug,
                reciprocal_source_url=request.source_url,
                explanation="The supplied name could not be normalized as a scientific name.",
            )

        return self._from_hits(
            list(self.repository.resolve_name(normalized_name)),
            request,
            "accepted_name",
            incoming_name=incoming_name,
        )

    def _from_hits(
        self,
        hits: Sequence[tuple[str, str, str]],
        request: FederationResolveRequest,
        default_match_state: str,
        *,
        incoming_name: str | None = None,
    ) -> FederationResolveResult:
        if len(hits) == 1:
            taxon_id, accepted_name, match_state = hits[0]
            return self._resolved(
                taxon_id=taxon_id,
                accepted_name=accepted_name,
                incoming_name=incoming_name or request.name,
                match_state=match_state or default_match_state,
                request=request,
            )
        if len(hits) > 1:
            return FederationResolveResult(
                status="ambiguous",
                incoming_name=incoming_name or request.name,
                matched_name=None,
                match_state="none",
                candidates=[
                    {"taxon_id": taxon_id, "accepted_name": accepted_name, "match_state": match_state}
                    for taxon_id, accepted_name, match_state in hits
                ],
                partner_slug=request.partner_slug,
                reciprocal_source_url=request.source_url,
                explanation="Multiple canonical taxa match the supplied identifier; human selection is required.",
            )
        return FederationResolveResult(
            status="unresolved",
            incoming_name=incoming_name or request.name,
            matched_name=None,
            match_state="none",
            partner_slug=request.partner_slug,
            reciprocal_source_url=request.source_url,
            explanation="No canonical accepted name or synonym match is currently available.",
        )

    def _resolved(
        self,
        *,
        taxon_id: str,
        accepted_name: str,
        incoming_name: str | None,
        match_state: str,
        request: FederationResolveRequest,
    ) -> FederationResolveResult:
        allowed_state = match_state if match_state in {"taxon_id", "accepted_name", "synonym", "partner_slug"} else "accepted_name"
        return FederationResolveResult(
            status="resolved",
            incoming_name=incoming_name,
            matched_name=accepted_name,
            match_state=allowed_state,
            taxon_id=taxon_id,
            canonical_dossier_url=f"{self.public_base_url.rstrip('/')}/species/{taxon_id}",
            partner_slug=request.partner_slug,
            reciprocal_source_url=request.source_url,
            explanation="Resolved through canonical taxonomy and synonym identity without inferring scientific claims.",
        )


def normalize_scientific_name(value: str) -> str | None:
    cleaned = " ".join(unquote(value).replace("_", " ").replace("-", " ").split())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    match = re.match(r"^([A-Za-z][A-Za-z-]+)\s+([a-z][a-z-]+)(?:\s+(subsp\.|var\.|f\.)\s+([a-z][a-z-]+))?", cleaned)
    if not match:
        return None
    genus, epithet, rank, infra = match.groups()
    normalized = f"{genus[:1].upper()}{genus[1:].lower()} {epithet.lower()}"
    if rank and infra:
        normalized += f" {rank} {infra.lower()}"
    return normalized


def extract_species_name_from_url(value: str) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    candidates = [segment for segment in parsed.path.split("/") if segment]
    candidates.extend(filter(None, re.split(r"[?&=]", parsed.query)))
    for candidate in reversed(candidates):
        normalized = normalize_scientific_name(candidate)
        if normalized:
            return normalized
    return None

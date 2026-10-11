"""Cross-surface identifier compatibility for the scientific convergence.

Priority 4 artifact. The converged surfaces use these identifier schemes,
each native to its module and preserved verbatim across surfaces:

===============================  ============================================
Scheme                           Owning surface
===============================  ============================================
``world-plants:<slug>``          Matrix canonical taxon id (World Plants /
                                 Hassler binding behind the resolver protocol)
``gbif:genus:<Name>``            Brain OAO-Lexicon-Matrix-KG bridge fixtures
``gbif:species:<slug>``          (provider keyspace, fixture scope)
``<decimal digits>``             ``public.orchid_taxonomy.id`` in string form —
                                 Atlas ``taxon_id`` and Featured Genus
                                 ``media.items[].taxon_id`` share this backbone
``oc-image:<digits>``            Featured Genus ``media_id``
                                 (``public.orchid_images.id``)
``img_<sha256[:20]>``            Image Intelligence minted reference-image id
                                 (caller-supplied ids, e.g. ``oc-image:*``,
                                 pass through unrewritten)
``dupgrp_<sha256[:16]>``         Image Intelligence duplicate group id
===============================  ============================================

This module only classifies, validates and correlates. It never rewrites an
identifier, never resolves a name (that is the Matrix resolver's job), and
never asserts that two identifiers denote the same taxon unless they are
bound through an explicit accepted-name correlation with provenance.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

# -- scheme patterns -----------------------------------------------------------

WORLD_PLANTS_TAXON_RE = re.compile(r"^world-plants:[a-z0-9][a-z0-9-]*$")
GBIF_GENUS_RE = re.compile(r"^gbif:genus:[A-Z][A-Za-z-]+$")
GBIF_SPECIES_RE = re.compile(r"^gbif:species:[A-Za-z][A-Za-z0-9-]*$")
BACKBONE_TAXON_RE = re.compile(r"^[0-9]+$")  # public.orchid_taxonomy.id, string form
OC_IMAGE_MEDIA_RE = re.compile(r"^oc-image:[0-9]+$")  # public.orchid_images.id
II_MINTED_IMAGE_RE = re.compile(r"^img_[0-9a-f]{20}$")
II_DUP_GROUP_RE = re.compile(r"^dupgrp_[0-9a-f]{16}$")

# Shared genus boundary, identical on the Featured Genus backend, the frontend
# normaliser, and the Atlas identifier declaration ("accepted Latin genus
# name, capitalised, single word").
GENUS_NAME_RE = re.compile(r"^[A-Z][A-Za-z-]+$")
GENUS_NAME_MAX_LENGTH = 120

TAXON_SCHEMES = frozenset({"world-plants", "gbif", "orchid-backbone"})
MEDIA_SCHEMES = frozenset({"oc-image", "image-intelligence"})


@dataclass(frozen=True)
class IdentifierClass:
    """Classification of one identifier string."""

    identifier: str
    scheme: str
    kind: str  # "taxon" | "media" | "duplicate-group"
    owning_surfaces: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_identifier(value: Any) -> IdentifierClass | None:
    """Classify one identifier under exactly one known scheme, or return None.

    Unknown shapes are reported as unclassifiable rather than coerced.
    """
    if not isinstance(value, str) or not value:
        return None
    if WORLD_PLANTS_TAXON_RE.match(value):
        return IdentifierClass(value, "world-plants", "taxon", ("matrix",))
    if GBIF_GENUS_RE.match(value) or GBIF_SPECIES_RE.match(value):
        return IdentifierClass(value, "gbif", "taxon", ("brain-oao-bridge",))
    if OC_IMAGE_MEDIA_RE.match(value):
        return IdentifierClass(value, "oc-image", "media", ("featured-genus",))
    if II_MINTED_IMAGE_RE.match(value):
        return IdentifierClass(value, "image-intelligence", "media", ("image-intelligence",))
    if II_DUP_GROUP_RE.match(value):
        return IdentifierClass(
            value, "image-intelligence", "duplicate-group", ("image-intelligence",)
        )
    if BACKBONE_TAXON_RE.match(value):
        return IdentifierClass(
            value, "orchid-backbone", "taxon", ("atlas", "featured-genus")
        )
    return None


def is_valid_genus_name(value: Any) -> bool:
    """The shared genus boundary used by Featured Genus, frontend and Atlas."""
    return (
        isinstance(value, str)
        and 1 < len(value) <= GENUS_NAME_MAX_LENGTH
        and bool(GENUS_NAME_RE.match(value))
    )


# -- name-bound correlation -----------------------------------------------------


@dataclass(frozen=True)
class TaxonIdentityCorrelation:
    """One accepted name correlated with its native identifiers per scheme.

    Correlation is asserted through the accepted scientific name plus its
    authority context, never by rewriting one scheme's identifier into
    another's. Every identifier keeps the scheme-native form its owning
    surface emitted.
    """

    accepted_name: str
    identifiers: dict[str, str] = field(default_factory=dict)  # scheme -> identifier
    taxonomic_authority: str | None = None
    taxonomy_version: str | None = None
    provenance: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["provenance"] = list(self.provenance)
        return payload


def build_correlation(
    accepted_name: str,
    identifiers: dict[str, str],
    *,
    taxonomic_authority: str | None = None,
    taxonomy_version: str | None = None,
    provenance: tuple[str, ...] = (),
) -> TaxonIdentityCorrelation:
    """Bind identifiers of different schemes to one accepted name.

    Refuses empty names, unknown schemes, malformed identifiers and any
    attempt to register two identifiers under one scheme. Identifiers are
    stored verbatim; nothing is rewritten.
    """
    name = " ".join(str(accepted_name or "").split()).strip()
    if not name:
        raise ValueError("accepted_name_required")
    if not identifiers:
        raise ValueError("at_least_one_identifier_required")
    validated: dict[str, str] = {}
    for scheme, identifier in identifiers.items():
        if scheme not in TAXON_SCHEMES:
            raise ValueError(f"unknown_taxon_scheme: {scheme!r}")
        classification = classify_identifier(identifier)
        if classification is None or classification.scheme != scheme:
            raise ValueError(
                f"identifier {identifier!r} is not valid under scheme {scheme!r}"
            )
        if classification.kind != "taxon":
            raise ValueError(f"identifier {identifier!r} is not a taxon identifier")
        if scheme in validated:
            raise ValueError(f"duplicate scheme: {scheme!r}")
        validated[scheme] = identifier
    return TaxonIdentityCorrelation(
        accepted_name=name,
        identifiers=validated,
        taxonomic_authority=taxonomic_authority,
        taxonomy_version=taxonomy_version,
        provenance=provenance,
    )


def correlation_lookup_key(correlation: TaxonIdentityCorrelation) -> str:
    """Normalised accepted-name join key shared across namespaces."""
    return " ".join(correlation.accepted_name.split()).casefold()

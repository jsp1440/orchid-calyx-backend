"""Canonical taxonomy resolution for the Orchid Continuum (BUILD-065).

Owner decision (authoritative): **World Plants (Dr. Michael Hassler)** is the
single canonical taxonomic backbone of the Orchid Continuum. External
authorities (GBIF, POWO, IPNI, World Flora Online, NCBI, ...) are *not*
competing taxonomies — they are recorded as authority mappings attached to the
canonical World Plants taxon.

This module implements that architecture on top of the existing Knowledge Graph
infrastructure without introducing a parallel framework:

* World Plants release selection / version supersession (older releases are
  preserved as ``historical``/``superseded`` with provenance, never deleted);
* construction of one canonical taxon registry from a World Plants release, with
  synonyms pointing at their accepted taxon;
* attachment of external authority identifiers as *mappings*;
* crosswalk classification (never auto-publish fuzzy mappings);
* taxonomic conflict detection.

Everything here is pure and read-only: functions consume iterables of ``dict``
rows (shaped exactly like the production projections) and return typed values.
Nothing opens a database connection or writes to any graph.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

# --- controlled vocabulary ---------------------------------------------------

CANONICAL_AUTHORITY = "world_plants"
CANONICAL_AUTHORITY_LABEL = "World Plants (Dr. Michael Hassler)"

#: External authorities preserved as *mappings*, never as competing taxonomies.
AUTHORITY_SOURCES: tuple[str, ...] = ("GBIF", "POWO", "IPNI", "WFO", "NCBI")

#: World Plants ``taxon_code`` rank codes → controlled rank names.
RANK_CODES: dict[str, str] = {
    "F": "family",
    "SF": "subfamily",
    "T": "tribe",
    "ST": "subtribe",
    "G": "genus",
    "S": "species",
    "SS": "subspecies",
    "V": "variety",
    "FM": "forma",
}

ACCEPTED = "accepted"
SYNONYM = "synonym"

#: Release lifecycle states. Only one release may be ``canonical`` at a time.
RELEASE_CANONICAL = "canonical"
RELEASE_SUPERSEDED = "superseded"
RELEASE_HISTORICAL = "historical"

#: Crosswalk mapping classes, ordered strongest → weakest.
MAP_EXACT_ID = "exact_id"
MAP_AUTHORITY_SYNONYM = "authority_supported_synonym"
MAP_ACCEPTED_NAME = "accepted_name_mapping"
MAP_HISTORICAL = "historical_mapping"
MAP_MANUAL_REVIEW = "manual_review_required"

#: Only these classes may be published without human review.
AUTO_PUBLISHABLE_MAPPINGS: frozenset[str] = frozenset(
    {MAP_EXACT_ID, MAP_AUTHORITY_SYNONYM, MAP_ACCEPTED_NAME}
)

# --- controlled graph activation (Part 5) ------------------------------------

#: Domains whose evidence quality is scientifically defensible for the first
#: controlled activation. Kept in sync with the source-registry status metadata.
ACTIVATED_DOMAINS: frozenset[str] = frozenset(
    {"media", "traits", "pollinators", "occurrences"}
)

#: Domains deliberately withheld from activation, with the reason.
WITHHELD_DOMAINS: dict[str, str] = {
    "climate": "occurrence-derived proxy; real climate tables empty (BLOCKED)",
    "conservation": "authoritative CITES/IUCN tables empty (PARTIALLY READY)",
    "mycorrhiza": "high name-collision/orphan rate; requires operator review",
    "literature": "records lack verified taxon identifiers (pure name join)",
}


# --- World Plants release selection ------------------------------------------


@dataclass(frozen=True)
class WorldPlantsRelease:
    """A registered World Plants snapshot (from ``oc_source.source_snapshots``)."""

    snapshot_id: str
    source_system: str
    version_label: str | None
    file_sha256: str | None
    row_count: int | None
    acquired_at: datetime | None
    notes: str | None = None
    status: str = RELEASE_HISTORICAL

    def with_status(self, status: str) -> "WorldPlantsRelease":
        return WorldPlantsRelease(
            snapshot_id=self.snapshot_id,
            source_system=self.source_system,
            version_label=self.version_label,
            file_sha256=self.file_sha256,
            row_count=self.row_count,
            acquired_at=self.acquired_at,
            notes=self.notes,
            status=status,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "source_system": self.source_system,
            "version_label": self.version_label,
            "file_sha256": self.file_sha256,
            "row_count": self.row_count,
            "acquired_at": self.acquired_at.isoformat() if self.acquired_at else None,
            "status": self.status,
            "notes": self.notes,
        }


def _is_world_plants(release: WorldPlantsRelease) -> bool:
    sys = (release.source_system or "").lower()
    return "world_plants" in sys or "worldplants" in sys or "hassler" in sys


def select_canonical_release(
    releases: Iterable[WorldPlantsRelease],
) -> tuple[WorldPlantsRelease | None, list[WorldPlantsRelease]]:
    """Designate the newest complete World Plants release as canonical.

    Returns ``(canonical, all_releases_with_status)``. Selection rules:

    * only World Plants releases are eligible to be canonical;
    * the canonical release is the one with the most recent ``acquired_at``
      (ties broken by higher ``row_count``);
    * releases sharing the canonical's ``file_sha256`` are the *same file* and
      are marked ``superseded`` (duplicate registration), not deleted;
    * all other releases are marked ``historical``.
    """

    all_releases = list(releases)
    eligible = [r for r in all_releases if _is_world_plants(r) and r.row_count != 0]
    if not eligible:
        return None, [r.with_status(RELEASE_HISTORICAL) for r in all_releases]

    def _key(r: WorldPlantsRelease) -> tuple[Any, int]:
        return (r.acquired_at or datetime.min, r.row_count or 0)

    canonical = max(eligible, key=_key)
    result: list[WorldPlantsRelease] = []
    for r in all_releases:
        if r.snapshot_id == canonical.snapshot_id:
            result.append(r.with_status(RELEASE_CANONICAL))
        elif r.file_sha256 and r.file_sha256 == canonical.file_sha256:
            result.append(r.with_status(RELEASE_SUPERSEDED))
        else:
            result.append(r.with_status(RELEASE_HISTORICAL))
    return canonical.with_status(RELEASE_CANONICAL), result


# --- canonical taxon registry ------------------------------------------------

_HYBRID_RE = re.compile(r"(^|\s)[×xX]\s")
_AUTHORSHIP_RE = re.compile(
    r"^\s*(?:[×x]\s*)?([A-Z][a-z]+(?:\s+[×x]\s*)?(?:\s+[a-z\-]+){0,3})\b"
)


def is_hybrid(name: str | None) -> bool:
    return bool(name) and bool(_HYBRID_RE.search(name or ""))


def canonical_name_of(scientific_name: str | None) -> str:
    """Strip authorship, decoding a couple of common HTML entities."""

    if not scientific_name:
        return ""
    text = scientific_name.replace("&amp;", "&").strip()
    m = _AUTHORSHIP_RE.match(text)
    return (m.group(1).strip() if m else text).strip()


def rank_of(taxon_code: str | None) -> str:
    return RANK_CODES.get((taxon_code or "").strip().upper(), "unknown")


@dataclass(frozen=True)
class AuthorityMapping:
    authority: str
    external_id: str
    confidence: float
    provenance: str


@dataclass
class CanonicalTaxon:
    canonical_id: int
    scientific_name: str
    canonical_name: str
    authorship: str | None
    rank: str
    status: str  # accepted | synonym
    is_hybrid: bool
    accepted_canonical_id: int | None = None
    authority_mappings: list[AuthorityMapping] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "scientific_name": self.scientific_name,
            "canonical_name": self.canonical_name,
            "authorship": self.authorship,
            "rank": self.rank,
            "status": self.status,
            "is_hybrid": self.is_hybrid,
            "accepted_canonical_id": self.accepted_canonical_id,
            "authority_mappings": [
                {
                    "authority": m.authority,
                    "external_id": m.external_id,
                    "confidence": m.confidence,
                    "provenance": m.provenance,
                }
                for m in self.authority_mappings
            ],
            "provenance": self.provenance,
        }


@dataclass
class CanonicalRegistry:
    canonical_release: WorldPlantsRelease | None
    taxa: dict[int, CanonicalTaxon]
    name_index: dict[str, int]  # canonical_name -> canonical_id (accepted only)

    def accepted(self) -> list[CanonicalTaxon]:
        return [t for t in self.taxa.values() if t.status == ACCEPTED]

    def synonyms(self) -> list[CanonicalTaxon]:
        return [t for t in self.taxa.values() if t.status == SYNONYM]

    def resolve(self, name: str) -> CanonicalTaxon | None:
        """Resolve a name to its accepted canonical taxon (following synonyms)."""

        key = canonical_name_of(name)
        cid = self.name_index.get(key)
        if cid is None:
            return None
        taxon = self.taxa.get(cid)
        if taxon is None:
            return None
        if taxon.status == SYNONYM and taxon.accepted_canonical_id is not None:
            return self.taxa.get(taxon.accepted_canonical_id, taxon)
        return taxon

    def summary(self) -> dict[str, Any]:
        accepted = self.accepted()
        synonyms = self.synonyms()
        mappings = sum(len(t.authority_mappings) for t in self.taxa.values())
        by_authority: dict[str, int] = {}
        for t in self.taxa.values():
            for m in t.authority_mappings:
                by_authority[m.authority] = by_authority.get(m.authority, 0) + 1
        return {
            "canonical_authority": CANONICAL_AUTHORITY_LABEL,
            "canonical_release": self.canonical_release.to_dict()
            if self.canonical_release
            else None,
            "total_taxa": len(self.taxa),
            "accepted_taxa": len(accepted),
            "synonyms": len(synonyms),
            "hybrids": sum(1 for t in self.taxa.values() if t.is_hybrid),
            "authority_mappings": mappings,
            "authority_mappings_by_source": by_authority,
        }


def build_canonical_registry(
    load_rows: Iterable[dict[str, Any]],
    synonym_rows: Iterable[dict[str, Any]] = (),
    authority_rows: Iterable[dict[str, Any]] = (),
    canonical_release: WorldPlantsRelease | None = None,
) -> CanonicalRegistry:
    """Construct a single canonical taxon registry from a World Plants release.

    ``load_rows``     — World Plants load rows: ``name`` and ``taxon_code``.
    ``synonym_rows``  — World Plants synonym graph rows: ``accepted_match_name``,
                        ``input_match_name``, ``relationship``.
    ``authority_rows``— external id rows: ``canonical_name``, ``authority``,
                        ``external_id``, optional ``confidence``/``provenance``.

    No taxon is duplicated: identity is the canonical (authorless) name; the
    first accepted occurrence wins, synonyms attach to their accepted taxon.
    """

    taxa: dict[int, CanonicalTaxon] = {}
    name_index: dict[str, int] = {}
    next_id = 1

    # Pass 1 — accepted taxa from the load (deduplicated by canonical name).
    for row in load_rows:
        sci = str(row.get("name") or "").replace("&amp;", "&").strip()
        if not sci:
            continue
        cname = canonical_name_of(sci)
        if not cname or cname in name_index:
            continue
        authorship = sci[len(cname):].strip() or None
        taxa[next_id] = CanonicalTaxon(
            canonical_id=next_id,
            scientific_name=sci,
            canonical_name=cname,
            authorship=authorship,
            rank=rank_of(row.get("taxon_code")),
            status=ACCEPTED,
            is_hybrid=is_hybrid(sci),
            provenance={
                "authority": CANONICAL_AUTHORITY,
                "source_table": "oc_source.world_plants_load",
                "taxon_code": row.get("taxon_code"),
            },
        )
        name_index[cname] = next_id
        next_id += 1

    # Pass 2 — synonyms pointing at their accepted taxon.
    for row in synonym_rows:
        if (row.get("relationship") or "").lower() != SYNONYM:
            continue
        syn_name = canonical_name_of(row.get("input_match_name") or row.get("input_name"))
        acc_name = canonical_name_of(
            row.get("accepted_match_name") or row.get("accepted_name")
        )
        if not syn_name or not acc_name or syn_name == acc_name:
            continue
        accepted_id = name_index.get(acc_name)
        if accepted_id is None:
            continue  # accepted taxon not in canonical backbone; skip (orphan)
        if syn_name in name_index:
            continue  # name already accepted/known; do not duplicate
        taxa[next_id] = CanonicalTaxon(
            canonical_id=next_id,
            scientific_name=str(row.get("input_name") or syn_name),
            canonical_name=syn_name,
            authorship=None,
            rank="unknown",
            status=SYNONYM,
            is_hybrid=is_hybrid(syn_name),
            accepted_canonical_id=accepted_id,
            provenance={
                "authority": CANONICAL_AUTHORITY,
                "source_table": "public.worldplants_synonym_graph",
                "relationship": SYNONYM,
            },
        )
        name_index[syn_name] = next_id
        next_id += 1

    # Pass 3 — attach external authority identifiers as mappings.
    for row in authority_rows:
        cname = canonical_name_of(row.get("canonical_name") or row.get("name"))
        authority = str(row.get("authority") or "").upper()
        ext = row.get("external_id")
        if not cname or not authority or ext in (None, ""):
            continue
        cid = name_index.get(cname)
        if cid is None:
            continue
        taxa[cid].authority_mappings.append(
            AuthorityMapping(
                authority=authority,
                external_id=str(ext),
                confidence=float(row.get("confidence", 1.0)),
                provenance=str(row.get("provenance", "external_id_table")),
            )
        )

    return CanonicalRegistry(
        canonical_release=canonical_release, taxa=taxa, name_index=name_index
    )


# --- crosswalk classification (Part 3) ---------------------------------------


def classify_mapping(mapping: dict[str, Any]) -> str:
    """Classify a crosswalk mapping. Fuzzy mappings never auto-publish."""

    method = (mapping.get("method") or "").lower()
    conf = float(mapping.get("confidence", 0.0) or 0.0)
    authority = mapping.get("authority")
    has_ids = mapping.get("source_id") not in (None, "") and mapping.get(
        "destination_id"
    ) not in (None, "")

    if ("exact" in method) and has_ids and conf >= 0.99:
        return MAP_EXACT_ID
    if authority and "synonym" in method and conf >= 0.9:
        return MAP_AUTHORITY_SYNONYM
    if ("canonical_name" in method or "accepted" in method) and conf >= 0.9:
        return MAP_ACCEPTED_NAME
    if "historical" in method or "superseded" in method:
        return MAP_HISTORICAL
    return MAP_MANUAL_REVIEW


def classify_crosswalk(mappings: Iterable[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {
        MAP_EXACT_ID: 0,
        MAP_AUTHORITY_SYNONYM: 0,
        MAP_ACCEPTED_NAME: 0,
        MAP_HISTORICAL: 0,
        MAP_MANUAL_REVIEW: 0,
    }
    total = 0
    for m in mappings:
        counts[classify_mapping(m)] += 1
        total += 1
    auto = sum(counts[c] for c in AUTO_PUBLISHABLE_MAPPINGS)
    return {
        "total": total,
        "by_class": counts,
        "auto_publishable": auto,
        "requires_review": total - auto,
    }


# --- taxonomic conflict detection (Part 4) -----------------------------------


def detect_conflicts(registry: CanonicalRegistry) -> dict[str, list[dict[str, Any]]]:
    """Detect taxonomic conflicts for the conflict report.

    Categories: duplicate accepted taxa (same canonical name accepted more than
    once), unresolved synonym chains (synonym whose accepted target is itself a
    synonym), and authority disagreements (one taxon carrying two different
    external ids from the same authority).
    """

    duplicate_accepted: dict[str, list[int]] = {}
    for t in registry.accepted():
        duplicate_accepted.setdefault(t.canonical_name, []).append(t.canonical_id)

    conflicts: dict[str, list[dict[str, Any]]] = {
        "duplicate_accepted_taxa": [
            {"canonical_name": name, "canonical_ids": ids}
            for name, ids in duplicate_accepted.items()
            if len(ids) > 1
        ],
        "unresolved_synonym_chains": [],
        "authority_disagreements": [],
    }

    for t in registry.synonyms():
        target = registry.taxa.get(t.accepted_canonical_id) if t.accepted_canonical_id else None
        if target is not None and target.status == SYNONYM:
            conflicts["unresolved_synonym_chains"].append(
                {
                    "synonym": t.canonical_name,
                    "points_to": target.canonical_name,
                    "target_status": target.status,
                }
            )

    for t in registry.taxa.values():
        by_auth: dict[str, set[str]] = {}
        for m in t.authority_mappings:
            by_auth.setdefault(m.authority, set()).add(m.external_id)
        for authority, ids in by_auth.items():
            if len(ids) > 1:
                conflicts["authority_disagreements"].append(
                    {
                        "canonical_name": t.canonical_name,
                        "authority": authority,
                        "external_ids": sorted(ids),
                    }
                )

    return conflicts

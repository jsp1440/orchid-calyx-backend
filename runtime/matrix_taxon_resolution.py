"""Deterministic taxon resolution with synonym reconciliation for Matrix workflows.

Resolution is evidence, not taxonomy mutation. A resolver maps a supplied
scientific name to a canonical taxon identity *for reporting purposes only*;
it never writes to the canonical taxonomy, never asserts a nomenclatural
change, and never silently discards the queried name. Synonym hits preserve
both the queried name and the accepted name so reports can show exactly how a
name was reconciled.

The resolver contract is deliberately small so the production binding (World
Plants canonical data) can be plugged in behind the same protocol while
tests and the offline demo use a static, reviewable entry set.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol

RESOLUTION_STATES = frozenset(
    {"resolved_canonical", "resolved_synonym", "unresolved"}
)


@dataclass(frozen=True)
class TaxonResolution:
    """Outcome of resolving one queried name against the resolver's entries."""

    query_name: str
    resolution_state: str
    canonical_taxon_id: str | None
    accepted_name: str | None
    matched_via: str | None  # "accepted_name" | "synonym" | None
    note: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TaxonEntry:
    """One canonical taxon with its accepted name and known synonyms."""

    canonical_taxon_id: str
    accepted_name: str
    synonyms: tuple[str, ...] = ()


class TaxonResolver(Protocol):
    def resolve(self, name: str) -> TaxonResolution: ...


def _normalize(name: Any) -> str:
    return " ".join(str(name or "").split()).strip().casefold()


class StaticTaxonResolver:
    """Deterministic resolver over an explicit, reviewable entry set.

    Matching is exact after whitespace/case normalization; no fuzzy matching
    is performed, so a near-miss name resolves as ``unresolved`` rather than
    being silently attached to the wrong taxon. When the same name string
    appears in multiple entries, the first entry in the supplied order wins
    (deterministic, and surfaced via ``matched_via``).
    """

    def __init__(self, entries: list[TaxonEntry | dict[str, Any]]) -> None:
        self._entries: list[TaxonEntry] = []
        self._by_name: dict[str, tuple[TaxonEntry, str]] = {}
        for item in entries:
            entry = (
                item
                if isinstance(item, TaxonEntry)
                else TaxonEntry(
                    canonical_taxon_id=str(item["canonical_taxon_id"]),
                    accepted_name=str(item["accepted_name"]),
                    synonyms=tuple(str(s) for s in (item.get("synonyms") or ())),
                )
            )
            self._entries.append(entry)
            accepted_key = _normalize(entry.accepted_name)
            if accepted_key:
                self._by_name.setdefault(accepted_key, (entry, "accepted_name"))
            for synonym in entry.synonyms:
                synonym_key = _normalize(synonym)
                if synonym_key:
                    self._by_name.setdefault(synonym_key, (entry, "synonym"))

    def resolve(self, name: str) -> TaxonResolution:
        query = " ".join(str(name or "").split()).strip()
        if not query:
            return TaxonResolution(
                query_name="",
                resolution_state="unresolved",
                canonical_taxon_id=None,
                accepted_name=None,
                matched_via=None,
                note="empty name cannot be resolved",
            )
        hit = self._by_name.get(_normalize(query))
        if hit is None:
            return TaxonResolution(
                query_name=query,
                resolution_state="unresolved",
                canonical_taxon_id=None,
                accepted_name=None,
                matched_via=None,
                note="no canonical or synonym match in the resolver entry set",
            )
        entry, matched_via = hit
        if matched_via == "accepted_name":
            return TaxonResolution(
                query_name=query,
                resolution_state="resolved_canonical",
                canonical_taxon_id=entry.canonical_taxon_id,
                accepted_name=entry.accepted_name,
                matched_via="accepted_name",
                note="queried name is the accepted name",
            )
        return TaxonResolution(
            query_name=query,
            resolution_state="resolved_synonym",
            canonical_taxon_id=entry.canonical_taxon_id,
            accepted_name=entry.accepted_name,
            matched_via="synonym",
            note=(
                f"queried name is treated as a synonym of {entry.accepted_name} "
                "by the resolver entry set; this is a reporting reconciliation, "
                "not a taxonomy mutation"
            ),
        )


def resolver_from_candidates(
    candidates: list[dict[str, Any]],
    *,
    extra_entries: list[TaxonEntry | dict[str, Any]] | None = None,
) -> StaticTaxonResolver:
    """Build a resolver from registry candidates plus optional synonym entries.

    Registry candidates contribute their taxon id and scientific name; synonyms
    are honored when a candidate's provenance carries an explicit ``synonyms``
    list (data-driven, never inferred). ``extra_entries`` let callers supply
    governed synonym data (e.g. a canonical taxonomy extract) for names that
    are not themselves Matrix candidates. Extra entries are registered first so
    governed reconciliation data takes precedence over candidate
    self-registration (first-registration-wins).
    """
    entries: list[dict[str, Any]] = []
    for item in extra_entries or []:
        if isinstance(item, TaxonEntry):
            entries.append(
                {
                    "canonical_taxon_id": item.canonical_taxon_id,
                    "accepted_name": item.accepted_name,
                    "synonyms": list(item.synonyms),
                }
            )
        else:
            entries.append(dict(item))
    seen_ids: set[str] = set()
    for candidate in candidates or []:
        taxon_id = str(candidate.get("taxon_id") or "").strip()
        name = str(candidate.get("scientific_name") or "").strip()
        if not taxon_id or not name or taxon_id in seen_ids:
            continue
        seen_ids.add(taxon_id)
        provenance = candidate.get("provenance") or {}
        synonyms = provenance.get("synonyms") or []
        entries.append(
            {
                "canonical_taxon_id": taxon_id,
                "accepted_name": name,
                "synonyms": [str(item) for item in synonyms],
            }
        )
    return StaticTaxonResolver(entries)


def collapse_synonym_candidates(
    candidates: list[dict[str, Any]],
    resolver: TaxonResolver,
) -> list[dict[str, Any]]:
    """Group ranked candidates that resolve to the same canonical taxon.

    Synonymous candidate rows are preserved (never deleted) but grouped so a
    report can state that two ranked rows are the same accepted taxon under
    different names. Groups keep the best-ranked member first and record every
    alias. Deterministic: groups appear in order of their first member.
    """
    groups: list[dict[str, Any]] = []
    by_canonical: dict[str, dict[str, Any]] = {}
    for candidate in candidates or []:
        resolution = resolver.resolve(str(candidate.get("scientific_name") or ""))
        key = resolution.canonical_taxon_id or f"unresolved:{candidate.get('taxon_id')}"
        group = by_canonical.get(key)
        member = {
            "taxon_id": candidate.get("taxon_id"),
            "scientific_name": candidate.get("scientific_name"),
            "score": candidate.get("score"),
            "resolution": resolution.as_dict(),
        }
        if group is None:
            group = {
                "canonical_taxon_id": resolution.canonical_taxon_id,
                "accepted_name": resolution.accepted_name
                or candidate.get("scientific_name"),
                "members": [member],
                "aliases": sorted(
                    {str(candidate.get("scientific_name") or "")} - {resolution.accepted_name or ""}
                ),
                "collapsed": False,
            }
            by_canonical[key] = group
            groups.append(group)
        else:
            group["members"].append(member)
            group["collapsed"] = True
            alias = str(candidate.get("scientific_name") or "")
            if alias and alias != group["accepted_name"]:
                group["aliases"] = sorted(set(group["aliases"]) | {alias})
    return groups

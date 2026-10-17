"""Deterministic normalization, classification and verification of discoveries.

Everything here is pure: no network, no database, no model inference.  A
registry record is a *discovered claim about a source*, never scientific
evidence of what the source asserts.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from difflib import SequenceMatcher
from hashlib import sha256
from typing import Any

from ..intelligence import (
    APPROVAL_REQUIRED_ACTIONS,
    AUTO_INTERNAL_ACTIONS,
    knowledge_fingerprint,
)
from . import DISCOVERY_VERSION

VERIFICATION_STATES = (
    "UNVERIFIED",
    "SOURCE_LOCATED",
    "VERIFIED",
    "PARTIALLY_VERIFIED",
    "CONTRADICTED",
    "UNRESOLVED",
)

NOVELTY_STATES = (
    "NEW_PUBLICATION",
    "HISTORICAL_RECOVERY",
    "UPDATED",
    "ALREADY_TRACKED",
)

DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_ITALIC_RE = re.compile(
    r"<(?:i|em|jats:italic)>(.*?)</(?:i|em|jats:italic)>", re.IGNORECASE | re.DOTALL
)
_BINOMIAL_RE = re.compile(r"\b([A-Z][a-z]{2,})\s+([a-z][a-z-]{2,})\b")
_NOVELTY_NAME_RE = re.compile(
    r"\b([A-Z][a-z]{2,})\s+([a-z][a-z-]{2,})\s*(?:\([^)]*\)\s*)?"
    r"(?:sp\.|gen\.|comb\.|stat\.|nom\.)\s*nov\b"
)

_ORCHID_RE = re.compile(
    r"\borchid|orchidaceae|orchidoideae|epidendroideae|vanilloideae|cypripedioideae",
    re.IGNORECASE,
)

# Content signals decide the ledger domain.  Domain participates in the ledger
# fingerprint, so it must depend on the work itself and never on which profile
# happened to find it; otherwise one paper found by two profiles would split
# into two canonical items.
_TAXONOMY_SIGNALS = (
    "sp. nov",
    "gen. nov",
    "comb. nov",
    "stat. nov",
    "nom. nov",
    "new species",
    "new genus",
    "new combination",
    "new record",
    "synonym",
    "taxonomic revision",
    "nomenclat",
    "lectotype",
    "neotype",
    "holotype",
    "protologue",
    "identification key",
    "phylogen",
    "natural hybrid",
)
_CONSERVATION_SIGNALS = (
    "conservation",
    "threatened",
    "endangered",
    "extinction",
    "iucn",
    "red list",
    "habitat loss",
    "fragmentation",
    "illegal",
    "trade",
    "cites",
    "reintroduction",
    "restoration",
    "protected area",
    "decline",
)
_TECHNOLOGY_SIGNALS = (
    "deep learning",
    "machine learning",
    "computer vision",
    "convolutional",
    "segmentation",
    "hyperspectral",
    "remote sensing",
    "knowledge graph",
    "digitization",
    "digitisation",
    "software",
    "pipeline",
    "neural network",
)

# Signals that open bounded *proposed* follow-up work.  None of them is evidence.
_RELATIONSHIP_SIGNALS = ("pollinat", "mycorrhiz", "fungal", "fungi", "fungus", "symbio")
_DATASET_SIGNALS = (
    "dataset",
    "data set",
    "occurrence",
    "herbarium",
    "specimen",
    "gbif",
    "darwin core",
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def clean_text(value: Any) -> str:
    text = html.unescape(_TAG_RE.sub(" ", str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


def normalize_doi(value: Any) -> str | None:
    match = DOI_RE.search(str(value or ""))
    return match.group(0).rstrip(".,;").lower() if match else None


def normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", clean_text(value).lower()).strip()


def title_similarity(left: str, right: str) -> float:
    a, b = normalize_title(left), normalize_title(right)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def parse_partial_date(value: Any) -> tuple[date | None, str]:
    """Return (date, precision) for 'YYYY', 'YYYY-MM', 'YYYY-MM-DD' or Crossref parts."""
    if isinstance(value, dict):
        parts = (value.get("date-parts") or [[None]])[0] or [None]
        parts = [int(part) for part in parts if part is not None]
    elif isinstance(value, (list, tuple)):
        parts = [int(part) for part in value if part is not None]
    else:
        raw = str(value or "").strip()[:10]
        parts = [int(part) for part in re.findall(r"\d+", raw)][:3]
    if not parts:
        return None, "UNKNOWN"
    precision = ("YEAR", "MONTH", "DAY")[min(len(parts), 3) - 1]
    year, month, day = (parts + [1, 1])[:3]
    try:
        return date(year, month, day), precision
    except ValueError:
        return None, "UNKNOWN"


@dataclass(frozen=True)
class DiscoveredWork:
    """One provider's normalized description of one source."""

    provider: str
    provider_record_id: str
    title: str
    doi: str | None = None
    url: str | None = None
    authors: tuple[str, ...] = ()
    venue: str | None = None
    publisher: str | None = None
    work_type: str | None = None
    abstract: str = ""
    published_on: date | None = None
    published_precision: str = "UNKNOWN"
    keywords: tuple[str, ...] = ()
    raw_title_markup: str = ""
    affiliations: tuple[str, ...] = ()
    related_identifiers: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return " ".join(
            [self.title, self.abstract, " ".join(self.keywords), self.venue or ""]
        )

    def metadata_sha256(self) -> str:
        """Hash of the provider fields that matter for update detection."""
        material = {
            "title": self.title,
            "doi": self.doi,
            "url": self.url,
            "authors": list(self.authors),
            "venue": self.venue,
            "abstract": self.abstract,
            "published_on": self.published_on.isoformat()
            if self.published_on
            else None,
            "work_type": self.work_type,
            "related_identifiers": list(self.related_identifiers),
        }
        return sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()


def is_orchid_relevant(work: DiscoveredWork) -> bool:
    """Conservative relevance gate; failures are counted, not stored."""
    return bool(
        _ORCHID_RE.search(work.text) or _ORCHID_RE.search(work.raw_title_markup)
    )


def classify_domain(work: DiscoveredWork) -> str:
    lower = work.text.lower()
    if any(signal in lower for signal in _TAXONOMY_SIGNALS) or _NOVELTY_NAME_RE.search(
        work.text
    ):
        return "taxonomy"
    if any(signal in lower for signal in _CONSERVATION_SIGNALS):
        return "conservation"
    if any(signal in lower for signal in _TECHNOLOGY_SIGNALS):
        return "technology"
    return "research"


def mentioned_names(work: DiscoveredWork) -> list[dict[str, str]]:
    """Unreconciled scientific-name mentions.  Taxonomy reconciliation decides validity."""
    names: dict[str, str] = {}
    for match in _NOVELTY_NAME_RE.finditer(work.text):
        names[f"{match.group(1)} {match.group(2)}"] = "PROPOSED_NOVELTY"
    for fragment in _ITALIC_RE.findall(work.raw_title_markup or ""):
        fragment = clean_text(fragment)
        binomial = _BINOMIAL_RE.match(fragment)
        if binomial:
            names.setdefault(f"{binomial.group(1)} {binomial.group(2)}", "MENTIONED")
        elif re.fullmatch(r"[A-Z][a-z]{2,}", fragment):
            names.setdefault(fragment, "MENTIONED_GENUS")
    return [
        {"name": name, "signal": signal, "reconciliation": "PENDING"}
        for name, signal in sorted(names.items())
    ]


def novelty(
    work: DiscoveredWork,
    *,
    discovered_at: datetime,
    new_window_days: int,
    previous_metadata_sha256: str | None,
) -> str:
    """Separate source date from discovery date; old material is never 'new'."""
    if previous_metadata_sha256 is not None:
        return (
            "ALREADY_TRACKED"
            if previous_metadata_sha256 == work.metadata_sha256()
            else "UPDATED"
        )
    if work.published_on is None:
        return "HISTORICAL_RECOVERY"
    age = (discovered_at.date() - work.published_on).days
    return "NEW_PUBLICATION" if age <= new_window_days else "HISTORICAL_RECOVERY"


def assess_verification(
    works: Iterable[DiscoveredWork],
    *,
    primary_source: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Bibliographic-identity verification across independent providers.

    ``VERIFIED`` means the source's identity is confirmed: its DOI resolved to
    a reachable publisher page whose title matches the registry title.  It does
    not mean the scientific claim is true; ``claim_verified`` stays False until
    human scientific review.
    """
    works = list(works)
    providers = sorted({work.provider for work in works})
    basis: dict[str, Any] = {
        "providers": providers,
        "claim_verified": False,
        "identity_checks": [],
        "contradictions": [],
    }
    if not works:
        return "UNVERIFIED", basis

    reference = works[0]
    for other in works[1:]:
        similarity = round(title_similarity(reference.title, other.title), 3)
        basis["identity_checks"].append(
            {
                "providers": [reference.provider, other.provider],
                "title_similarity": similarity,
            }
        )
        if similarity < 0.6:
            basis["contradictions"].append(
                {
                    "field": "title",
                    "providers": [reference.provider, other.provider],
                    "similarity": similarity,
                }
            )
        if (
            reference.published_on
            and other.published_on
            and abs(reference.published_on.year - other.published_on.year) > 1
        ):
            basis["contradictions"].append(
                {
                    "field": "publication_year",
                    "values": {
                        reference.provider: reference.published_on.year,
                        other.provider: other.published_on.year,
                    },
                }
            )

    if primary_source is not None:
        outcome = primary_source.get("outcome")
        resolved_title = primary_source.get("source_title") or ""
        basis["primary_source"] = {
            "outcome": outcome,
            "resolved_url": primary_source.get("resolved_url"),
            "evidence_sha256": primary_source.get("evidence_sha256"),
        }
        if outcome == "SOURCE_CONFIRMED" and resolved_title:
            similarity = round(title_similarity(reference.title, resolved_title), 3)
            basis["primary_source"]["title_similarity"] = similarity
            if similarity < 0.5:
                basis["contradictions"].append(
                    {"field": "primary_source_title", "similarity": similarity}
                )

    if basis["contradictions"]:
        return "CONTRADICTED", basis
    if primary_source is not None:
        ps = basis["primary_source"]
        if ps["outcome"] != "SOURCE_CONFIRMED":
            return "UNRESOLVED", basis
        if ps.get("title_similarity", 0.0) >= 0.85:
            return "VERIFIED", basis
        return "PARTIALLY_VERIFIED", basis
    if len(providers) >= 2:
        return "PARTIALLY_VERIFIED", basis
    if any(work.doi or work.url for work in works):
        return "SOURCE_LOCATED", basis
    return "UNVERIFIED", basis


def merge_works(works: Iterable[DiscoveredWork]) -> DiscoveredWork:
    """Combine provider views without inventing fields; earliest non-empty wins."""
    ordered = sorted(works, key=lambda work: (work.provider, work.provider_record_id))
    merged = ordered[0]
    for other in ordered[1:]:
        merged = replace(
            merged,
            doi=merged.doi or other.doi,
            url=merged.url or other.url,
            authors=merged.authors or other.authors,
            venue=merged.venue or other.venue,
            publisher=merged.publisher or other.publisher,
            abstract=merged.abstract
            if len(merged.abstract) >= len(other.abstract)
            else other.abstract,
            published_on=merged.published_on or other.published_on,
            published_precision=(
                merged.published_precision
                if merged.published_on
                else other.published_precision
            ),
            keywords=tuple(dict.fromkeys(merged.keywords + other.keywords)),
            raw_title_markup=merged.raw_title_markup or other.raw_title_markup,
            affiliations=tuple(dict.fromkeys(merged.affiliations + other.affiliations)),
            related_identifiers=tuple(
                dict.fromkeys(merged.related_identifiers + other.related_identifiers)
            ),
        )
    return merged


def ledger_fingerprint(work: DiscoveredWork) -> str:
    return knowledge_fingerprint(
        classify_domain(work), work.title, [work.doi] if work.doi else []
    )


def destinations(work: DiscoveredWork, domain: str) -> list[str]:
    lower = work.text.lower()
    result = {"orep"}  # literature registration through the existing route contract
    if domain == "taxonomy":
        result.add("taxonomy_reconciliation")
    if domain == "conservation":
        result.add("conservation_platform")
    if domain == "technology":
        result.add("source_registry")
    if any(signal in lower for signal in ("pollinat",)):
        result.add("pollinator_network")
    if any(signal in lower for signal in ("mycorrhiz", "fungal", "fungi", "fungus")):
        result.add("mycorrhizal_network")
    if any(
        signal in lower
        for signal in ("habitat", "distribution", "occurrence", "climate", "range")
    ):
        result.add("atlas")
    if any(
        signal in lower
        for signal in ("morpholog", "anatom", "identification key", "diagnos", "trait")
    ):
        result.add("traitbank")
    if any(signal in lower for signal in _DATASET_SIGNALS):
        result.add("source_registry")
    return sorted(result)


def follow_up_tasks(work: DiscoveredWork, domain: str) -> list[str]:
    lower = work.text.lower()
    tasks = ["VERIFY_PRIMARY_SOURCE", "COMPARE_EXISTING_KNOWLEDGE"]
    if domain == "taxonomy":
        tasks.append("RECONCILE_TAXONOMY")
    if any(signal in lower for signal in _RELATIONSHIP_SIGNALS):
        tasks.append("EVALUATE_RELATIONSHIP_EVIDENCE")
    if any(signal in lower for signal in _DATASET_SIGNALS):
        tasks.append("EVALUATE_FEDERATION")
    return tasks


def priority(
    domain: str,
    novelty_state: str,
    verification_state: str,
    names: list[dict[str, str]],
) -> str:
    if verification_state == "CONTRADICTED":
        return "HIGH"
    if novelty_state == "HISTORICAL_RECOVERY":
        return "LOW"
    if domain == "taxonomy" and any(
        name["signal"] == "PROPOSED_NOVELTY" for name in names
    ):
        return "HIGH"
    return "MEDIUM"


def _detail(work: DiscoveredWork, names: list[dict[str, str]]) -> str:
    lines = []
    if work.authors:
        authors = ", ".join(work.authors[:6]) + (
            " et al." if len(work.authors) > 6 else ""
        )
        lines.append(f"Authors: {authors}")
    if work.venue:
        lines.append(f"Venue: {work.venue}")
    if work.published_on:
        lines.append(
            f"Source date: {work.published_on.isoformat()} ({work.published_precision.lower()})"
        )
    if work.doi:
        lines.append(f"DOI: https://doi.org/{work.doi}")
    if work.url:
        lines.append(f"URL: {work.url}")
    if names:
        lines.append(
            "Name mentions (unreconciled): " + ", ".join(name["name"] for name in names)
        )
    if work.abstract:
        lines.append("Abstract (as reported by registry): " + work.abstract[:1200])
    lines.append(
        "Native registry discovery. Registry metadata locates a source; it is not evidence "
        "for the source's scientific claims."
    )
    return "\n".join(lines)


def to_intelligence_item(
    work: DiscoveredWork,
    *,
    provider_views: list[DiscoveredWork],
    novelty_state: str,
    verification_state: str,
    verification_basis: dict[str, Any],
    discovered_at: datetime,
    profile_key: str,
    existing_identity: dict[str, str] | None = None,
) -> dict[str, object]:
    """Map onto the existing intelligence-ledger item contract.

    ``existing_identity`` pins a previously discovered source to its ledger
    item, so a richer later provider view (which might classify differently)
    updates that item instead of splitting it into a duplicate.
    """
    domain = existing_identity["domain"] if existing_identity else classify_domain(work)
    names = mentioned_names(work)
    urls = sorted(
        {
            value
            for value in (work.url, f"https://doi.org/{work.doi}" if work.doi else None)
            if value
        }
    )
    observation_material = "|".join(
        sorted(
            f"{view.provider}:{view.provider_record_id}:{view.metadata_sha256()}"
            for view in provider_views
        )
    )
    native = {
        "discovery_version": DISCOVERY_VERSION,
        "profile_key": profile_key,
        "providers": sorted({view.provider for view in provider_views}),
        "provider_record_ids": sorted(
            f"{view.provider}:{view.provider_record_id}" for view in provider_views
        ),
        "discovered_at": discovered_at.isoformat(),
        "source_published_on": work.published_on.isoformat()
        if work.published_on
        else None,
        "source_date_precision": work.published_precision,
        "novelty": novelty_state,
        "verification_state": verification_state,
        "verification_basis": verification_basis,
        # The five evidence layers stay separate; only the first two exist at discovery.
        "evidence_layers": {
            "discovered_claim": {
                "title": work.title,
                "abstract_as_reported": work.abstract[:4000],
            },
            "primary_source_evidence": verification_basis.get("primary_source"),
            "independent_corroboration": {
                "providers": verification_basis.get("providers", []),
                "note": "Independent registries agreeing on identity corroborates the source, not its claims.",
            },
            "scientific_interpretation": None,
            "proposed_actions": follow_up_tasks(work, domain),
        },
        "name_mentions": names,
        "authors": list(work.authors),
        "venue": work.venue,
        "publisher": work.publisher,
        "work_type": work.work_type,
        "affiliations": list(work.affiliations),
        "related_identifiers": list(work.related_identifiers),
        "claim_verified": False,
    }
    return {
        "intelligence_id": sha256(
            f"{DISCOVERY_VERSION}|{observation_material}".encode()
        ).hexdigest(),
        "knowledge_fingerprint": (
            existing_identity["knowledge_fingerprint"]
            if existing_identity
            else ledger_fingerprint(work)
        ),
        "lifecycle": "DISCOVERED",
        "knowledge_delta": "UNASSESSED",
        "domain": domain,
        "title": work.title,
        "normalized_title": re.sub(r"\s+", " ", work.title.strip()).lower(),
        "priority": priority(domain, novelty_state, verification_state, names),
        "detail": _detail(work, names),
        "source_urls": urls,
        "dois": [work.doi] if work.doi else [],
        "verification_required": True,
        "canonical_destinations": destinations(work, domain),
        "follow_up_tasks": follow_up_tasks(work, domain),
        "automatic_actions_allowed": list(AUTO_INTERNAL_ACTIONS),
        "approval_required_for": list(APPROVAL_REQUIRED_ACTIONS),
        "external_contacted": False,
        "canonical_graph_mutated": False,
        "parser_version": DISCOVERY_VERSION,
        "native_discovery": native,
    }

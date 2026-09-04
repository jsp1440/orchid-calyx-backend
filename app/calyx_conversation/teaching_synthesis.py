"""CALYX-SYNTHESIS-001 TeachingSynthesisV1 — semantic composition contract for teaching surfaces.

Assembles a versioned, multi-domain teaching synthesis from pre-fetched domain data.
This is a COMPOSITION CONTRACT, not a second reasoning engine or evidence store.

Rules:
- Claim/relationship-first, never source-family-first.
- UNAVAILABLE distinguishes absent evidence from measured zero or biological absence.
- Evidence provenance must survive from input to output; no claim may lose its source.
- Generated explanation (LLM prose) must never enter the evidence set.
- Contradictions remain contradictions; they must not be resolved into support.
- No coordinate or fine-resolution locality may appear in output.
- Canonical species identities must be stable across rotation payloads.
- graph_mutation is always False; no KG or taxonomy writes.

See issue #1082 for the full acceptance contract.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

CONTRACT_VERSION = "CALYX-TEACHING-SYNTHESIS-001"
SCHEMA_VERSION = "teaching-synthesis/v1"

# Sentinel for absent but not measured-zero data.
_UNAVAILABLE = "UNAVAILABLE"

# Evidence domains in priority/narrative order.
ORDERED_DOMAINS = [
    "morphology_anatomy_physiology",
    "habitat",
    "geography",
    "pollination",
    "mycorrhizae",
    "literature",
    "neighboring_taxa_community",
    "conservation",
]

_DOMAIN_HEADINGS: dict[str, str] = {
    "morphology_anatomy_physiology": "Form and Function",
    "habitat": "Habitat and Ecology",
    "geography": "Geographic Range",
    "pollination": "Pollination Biology",
    "mycorrhizae": "Mycorrhizal Associations",
    "literature": "Scientific Literature",
    "neighboring_taxa_community": "Community and Neighbors",
    "conservation": "Conservation Status",
}

# Fields that must never appear in outputs (locality safety).
_FORBIDDEN_FIELDS = frozenset(
    {"latitude", "longitude", "lat", "lon", "lng", "coordinates", "coord", "exact_location"}
)

# Coordinate patterns: never emit values that look like decimal coordinates.
_COORDINATE_KEYS = frozenset({"latitude", "longitude", "lat", "lon", "lng"})


class EvidenceState(str, Enum):
    SUPPORTED = "supported"
    UNAVAILABLE = "unavailable"
    GAP = "gap"
    CONFLICT = "conflict"


class AudienceLevel(str, Enum):
    PUBLIC = "public"
    STUDENT = "student"
    RESEARCHER = "researcher"
    EDUCATOR = "educator"


class DepthLevel(str, Enum):
    OVERVIEW = "overview"
    STANDARD = "standard"
    DETAILED = "detailed"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _safe_text(value: Any, limit: int = 1200) -> str:
    """Truncate and flatten; never emit None or missing as empty evidence."""
    return " ".join(str(value or "").split())[:limit]


def _strip_locality(data: dict[str, Any]) -> dict[str, Any]:
    """Remove coordinate fields from a provenance dict before attaching to output."""
    return {k: v for k, v in data.items() if k.lower() not in _COORDINATE_KEYS}


def _build_source_ref(raw: dict[str, Any] | str) -> dict[str, Any]:
    """Normalize a source reference; strip coordinate fields."""
    if isinstance(raw, str):
        return {"source": raw, "type": _UNAVAILABLE, "review_state": _UNAVAILABLE}
    cleaned = _strip_locality(raw)
    return {
        "source": _safe_text(cleaned.get("source") or cleaned.get("provider") or "", 300),
        "type": _safe_text(cleaned.get("type") or cleaned.get("source_type") or _UNAVAILABLE, 100),
        "review_state": _safe_text(cleaned.get("review_state") or _UNAVAILABLE, 100),
        "provenance": {
            k: _safe_text(v, 400)
            for k, v in cleaned.items()
            if k not in {"source", "type", "review_state"} and isinstance(v, str)
        },
    }


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SubjectIdentity:
    """Canonical taxon identity for the synthesis subject."""

    taxon_name: str
    taxon_id: str | None
    common_names: tuple[str, ...]
    taxon_rank: str
    canonical_source: str
    synonym_names: tuple[str, ...]
    authority: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "taxon_name": self.taxon_name,
            "taxon_id": self.taxon_id,
            "common_names": list(self.common_names),
            "taxon_rank": self.taxon_rank,
            "canonical_source": self.canonical_source,
            "synonym_names": list(self.synonym_names),
            "authority": self.authority,
        }


@dataclass(frozen=True)
class RelationshipClaim:
    """One provenance-anchored claim within a domain.

    is_generated_interpretation must always be False. Generated LLM prose may
    NEVER enter the evidence set.
    """

    claim_id: str
    domain: str
    statement: str
    evidence_state: EvidenceState
    source_references: tuple[dict[str, Any], ...]
    is_generated_interpretation: bool = False

    def __post_init__(self) -> None:
        if self.is_generated_interpretation:
            raise ValueError(
                "RelationshipClaim.is_generated_interpretation must be False; "
                "generated explanation must never enter the evidence set."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "domain": self.domain,
            "statement": self.statement,
            "evidence_state": self.evidence_state.value,
            "source_references": list(self.source_references),
            "is_generated_interpretation": self.is_generated_interpretation,
        }


@dataclass
class DomainRelationship:
    """Evidence state for one scientific domain."""

    domain: str
    evidence_state: EvidenceState
    claims: list[RelationshipClaim]
    unavailable_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "evidence_state": self.evidence_state.value,
            "claims": [c.to_dict() for c in self.claims],
            "claim_count": len(self.claims),
            "unavailable_reason": self.unavailable_reason or None,
        }


@dataclass
class NarrativeSegment:
    """One teaching narrative segment, claim-first with provenance."""

    segment_id: str
    domain: str
    heading: str
    text: str
    evidence_state: EvidenceState
    source_references: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "domain": self.domain,
            "heading": self.heading,
            "text": self.text,
            "evidence_state": self.evidence_state.value,
            "source_references": self.source_references,
        }


@dataclass
class TeachingSynthesisV1:
    """Versioned teaching synthesis output for University, Atlas, Research Station surfaces.

    graph_mutation is always False. No automatic publication or KG write.
    """

    contract_version: str
    schema_version: str
    fingerprint: str
    generated_at: str
    graph_mutation: bool

    subject: SubjectIdentity
    audience: AudienceLevel
    depth: DepthLevel

    central_instructional_idea: str | None
    learning_objective: str | None

    narrative_segments: list[NarrativeSegment]
    observable_prompts: list[str]
    relationship_model: dict[str, DomainRelationship]

    knowledge_gaps: list[str]
    contradictions: list[dict[str, str]]
    evidence_provenance: list[dict[str, Any]]

    sensitive_locality_policy: dict[str, Any]
    deeper_routes: dict[str, str | None]
    source_identity: dict[str, str | None]
    publication_boundary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "schema_version": self.schema_version,
            "fingerprint": self.fingerprint,
            "generated_at": self.generated_at,
            "graph_mutation": self.graph_mutation,
            "subject": self.subject.to_dict(),
            "audience": self.audience.value,
            "depth": self.depth.value,
            "central_instructional_idea": self.central_instructional_idea,
            "learning_objective": self.learning_objective,
            "narrative_segments": [s.to_dict() for s in self.narrative_segments],
            "observable_prompts": self.observable_prompts,
            "relationship_model": {
                k: v.to_dict() for k, v in self.relationship_model.items()
            },
            "knowledge_gaps": self.knowledge_gaps,
            "contradictions": self.contradictions,
            "evidence_provenance": self.evidence_provenance,
            "sensitive_locality_policy": self.sensitive_locality_policy,
            "deeper_routes": self.deeper_routes,
            "source_identity": self.source_identity,
            "publication_boundary": self.publication_boundary,
        }


# ---------------------------------------------------------------------------
# Domain assembly
# ---------------------------------------------------------------------------


def _build_domain_relationship(domain: str, data: dict[str, Any] | None) -> DomainRelationship:
    """Assemble one domain from pre-fetched data.

    data format expected:
      {
        "claims": [{"statement": str, "source_references": [...], "is_conflict": bool}, ...],
        "conflicts": [{"statement": str, "source_references": [...]}],
        "gaps": [str],
        "gap_reason": str,
      }
    Absent data → UNAVAILABLE. Empty claims with no gaps → GAP. Conflicts present → CONFLICT.
    """
    if data is None:
        return DomainRelationship(
            domain=domain,
            evidence_state=EvidenceState.UNAVAILABLE,
            claims=[],
            unavailable_reason=(
                f"No data was provided for the {domain!r} domain. "
                "This is not a finding that evidence is absent; the domain was not queried."
            ),
        )

    raw_claims = data.get("claims") or []
    raw_conflicts = data.get("conflicts") or []

    if not raw_claims and not raw_conflicts:
        gap_reason = _safe_text(data.get("gap_reason") or "", 600)
        return DomainRelationship(
            domain=domain,
            evidence_state=EvidenceState.GAP,
            claims=[],
            unavailable_reason=gap_reason or f"No claims found for {domain!r} in provided data.",
        )

    claims: list[RelationshipClaim] = []
    has_conflict = bool(raw_conflicts)

    for idx, raw in enumerate(raw_claims[:12]):
        if not isinstance(raw, dict):
            continue
        refs = tuple(
            _build_source_ref(r)
            for r in (raw.get("source_references") or [])[:5]
        )
        claims.append(
            RelationshipClaim(
                claim_id=f"{domain}:{idx}",
                domain=domain,
                statement=_safe_text(raw.get("statement") or "", 1200),
                evidence_state=(
                    EvidenceState.CONFLICT if raw.get("is_conflict") else EvidenceState.SUPPORTED
                ),
                source_references=refs,
                is_generated_interpretation=False,
            )
        )

    for idx, raw in enumerate(raw_conflicts[:6]):
        if not isinstance(raw, dict):
            continue
        refs = tuple(
            _build_source_ref(r)
            for r in (raw.get("source_references") or [])[:5]
        )
        claims.append(
            RelationshipClaim(
                claim_id=f"{domain}:conflict:{idx}",
                domain=domain,
                statement=_safe_text(raw.get("statement") or "", 1200),
                evidence_state=EvidenceState.CONFLICT,
                source_references=refs,
                is_generated_interpretation=False,
            )
        )

    overall_state = EvidenceState.CONFLICT if has_conflict else EvidenceState.SUPPORTED

    return DomainRelationship(
        domain=domain,
        evidence_state=overall_state,
        claims=claims,
        unavailable_reason="",
    )


def _build_narrative_segment(domain: str, rel: DomainRelationship) -> NarrativeSegment:
    """Build one narrative segment from a domain relationship.

    The text is claim-first: it states what the evidence supports, gaps, or conflicts.
    It does NOT generate biological interpretation beyond what the evidence states.
    """
    heading = _DOMAIN_HEADINGS.get(domain, domain.replace("_", " ").title())

    if rel.evidence_state == EvidenceState.UNAVAILABLE:
        text = (
            f"{heading}: Evidence for this domain was not available for this synthesis. "
            "This is not a finding that evidence is absent; data was not queried or provided."
        )
        sources: list[dict[str, Any]] = []
    elif rel.evidence_state == EvidenceState.GAP:
        gap_note = rel.unavailable_reason or "No claims were found in the provided data."
        text = f"{heading}: Knowledge gap — {gap_note}"
        sources = []
    elif rel.evidence_state == EvidenceState.CONFLICT:
        conflict_claims = [c for c in rel.claims if c.evidence_state == EvidenceState.CONFLICT]
        supported_claims = [c for c in rel.claims if c.evidence_state == EvidenceState.SUPPORTED]
        parts = []
        if supported_claims:
            parts.append(
                " | ".join(c.statement for c in supported_claims[:3] if c.statement)
            )
        if conflict_claims:
            conflict_text = " | ".join(c.statement for c in conflict_claims[:3] if c.statement)
            parts.append(f"Conflicting: {conflict_text}")
        text = f"{heading}: " + (" — ".join(parts) if parts else "Conflicting evidence present.")
        sources = [
            ref
            for c in rel.claims[:6]
            for ref in c.source_references
        ]
    else:
        # SUPPORTED
        claim_texts = [c.statement for c in rel.claims[:4] if c.statement]
        text = f"{heading}: " + (" — ".join(claim_texts) if claim_texts else "Evidence available.")
        sources = [
            ref
            for c in rel.claims[:4]
            for ref in c.source_references
        ]

    return NarrativeSegment(
        segment_id=f"segment:{domain}",
        domain=domain,
        heading=heading,
        text=_safe_text(text, 1800),
        evidence_state=rel.evidence_state,
        source_references=sources[:10],
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_teaching_synthesis(
    subject: SubjectIdentity,
    domain_data: dict[str, dict[str, Any] | None],
    *,
    audience: str = "public",
    depth: str = "standard",
    central_instructional_idea: str | None = None,
    learning_objective: str | None = None,
    observable_prompts: list[str] | None = None,
    sensitive_locality_withheld: bool = True,
    taxonomy_release: str | None = None,
    kg_release: str | None = None,
    deeper_routes: dict[str, str | None] | None = None,
    generated_at: str | None = None,
) -> TeachingSynthesisV1:
    """Assemble a TeachingSynthesisV1 from pre-fetched domain data.

    Args:
        subject: Canonical taxon identity.
        domain_data: Dict keyed by domain name; None value means data was not fetched
            (UNAVAILABLE). Empty dict means fetched but nothing found (GAP).
        audience: Audience level string ("public" | "student" | "researcher" | "educator").
        depth: Depth level string ("overview" | "standard" | "detailed").
        central_instructional_idea: The central teaching idea, authored by a scientist or
            educator; must not be generated by the LLM using this synthesis as input.
        learning_objective: Similarly authored, not generated.
        observable_prompts: Pre-authored observable comparison prompts.
        sensitive_locality_withheld: Whether fine-resolution locality is withheld.
        taxonomy_release: Taxonomy release identifier.
        kg_release: Knowledge Graph release identifier.
        deeper_routes: Dict of surface → URL/identifier for deeper exploration.
        generated_at: ISO timestamp; defaults to current UTC time if None.

    Returns:
        TeachingSynthesisV1 with full provenance and no KG mutation.
    """
    import datetime

    ts = generated_at or datetime.datetime.now(datetime.timezone.utc).isoformat()

    try:
        audience_level = AudienceLevel(audience)
    except ValueError:
        audience_level = AudienceLevel.PUBLIC

    try:
        depth_level = DepthLevel(depth)
    except ValueError:
        depth_level = DepthLevel.STANDARD

    relationship_model: dict[str, DomainRelationship] = {}
    for dom in ORDERED_DOMAINS:
        data = domain_data.get(dom)
        relationship_model[dom] = _build_domain_relationship(dom, data)

    narrative_segments = [
        _build_narrative_segment(dom, relationship_model[dom])
        for dom in ORDERED_DOMAINS
    ]

    knowledge_gaps: list[str] = []
    contradictions: list[dict[str, str]] = []
    evidence_provenance: list[dict[str, Any]] = []

    for dom, rel in relationship_model.items():
        if rel.evidence_state in (EvidenceState.GAP, EvidenceState.UNAVAILABLE):
            knowledge_gaps.append(
                f"{dom}: {rel.unavailable_reason or 'Evidence not available.'}"
            )
        if rel.evidence_state == EvidenceState.CONFLICT:
            for claim in rel.claims:
                if claim.evidence_state == EvidenceState.CONFLICT:
                    contradictions.append(
                        {
                            "domain": dom,
                            "claim_id": claim.claim_id,
                            "description": claim.statement[:600],
                        }
                    )
        for claim in rel.claims:
            for ref in claim.source_references:
                evidence_provenance.append(
                    {
                        "claim_id": claim.claim_id,
                        "domain": dom,
                        **ref,
                    }
                )

    loc_policy = {
        "coordinates_withheld": sensitive_locality_withheld,
        "resolution": "coarse_only" if sensitive_locality_withheld else "full",
        "policy_statement": (
            "Fine-resolution occurrence coordinates are withheld per locality-protection policy. "
            "No coordinate data below 10 km resolution is emitted for sensitive taxa."
            if sensitive_locality_withheld
            else "Locality resolution not restricted for this synthesis."
        ),
    }

    deeper = {
        "atlas": None,
        "matrix": None,
        "literature": None,
        "university": None,
        "research_station": None,
        "calyx": None,
    }
    if deeper_routes:
        for k in deeper:
            if k in deeper_routes:
                deeper[k] = deeper_routes[k]

    source_id = {
        "taxonomy_release": taxonomy_release,
        "kg_release": kg_release,
        "generated_at": ts,
        "contract_version": CONTRACT_VERSION,
    }

    pub_boundary = {
        "read_only": True,
        "automatic_publication": False,
        "knowledge_graph_mutation": False,
        "taxonomy_activation": False,
    }

    base = {
        "contract_version": CONTRACT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "subject": subject.to_dict(),
        "audience": audience_level.value,
        "depth": depth_level.value,
        "generated_at": ts,
    }
    fp = _fingerprint(base)

    return TeachingSynthesisV1(
        contract_version=CONTRACT_VERSION,
        schema_version=SCHEMA_VERSION,
        fingerprint=fp,
        generated_at=ts,
        graph_mutation=False,
        subject=subject,
        audience=audience_level,
        depth=depth_level,
        central_instructional_idea=central_instructional_idea,
        learning_objective=learning_objective,
        narrative_segments=narrative_segments,
        observable_prompts=list(observable_prompts or [])[:20],
        relationship_model=relationship_model,
        knowledge_gaps=knowledge_gaps,
        contradictions=contradictions,
        evidence_provenance=evidence_provenance,
        sensitive_locality_policy=loc_policy,
        deeper_routes=deeper,
        source_identity=source_id,
        publication_boundary=pub_boundary,
    )


# ---------------------------------------------------------------------------
# Featured Genus rotation support
# ---------------------------------------------------------------------------


def build_featured_genus_pool(
    genus_name: str,
    species_list: list[dict[str, Any]],
    *,
    window_hours: int = 12,
    rotation_interval_seconds: int = 45,
) -> dict[str, Any]:
    """Build a deterministic, pre-ordered species pool for the Featured Genus rotation.

    The pool is ordered deterministically from canonical species data so the
    frontend can advance through it without client-side scientific inference.
    Canonical identities, deduplication, attribution, and honest no-media states
    are preserved.

    Args:
        genus_name: Canonical genus name.
        species_list: List of species dicts, each with at minimum:
            - "taxon_name": canonical binomial
            - "taxon_id": canonical DB identifier (str)
            - "has_media": bool — whether canonical media is available
            - "media_attribution": str | None
            - "sort_key": str | None — caller-supplied stable sort key
        window_hours: Duration of one Featured Genus window.
        rotation_interval_seconds: Seconds per active species display.

    Returns:
        Dict with pool, rotation plan, and metadata.
    """
    seen_ids: set[str] = set()
    deduplicated: list[dict[str, Any]] = []
    for sp in species_list:
        if not isinstance(sp, dict):
            continue
        tid = str(sp.get("taxon_id") or sp.get("taxon_name") or "")
        if not tid or tid in seen_ids:
            continue
        seen_ids.add(tid)
        deduplicated.append(sp)

    # Stable sort: caller sort_key first, then canonical name.
    deduplicated.sort(
        key=lambda s: (
            str(s.get("sort_key") or ""),
            str(s.get("taxon_name") or ""),
        )
    )

    pool = []
    for idx, sp in enumerate(deduplicated):
        pool.append(
            {
                "rotation_index": idx,
                "taxon_name": str(sp.get("taxon_name") or _UNAVAILABLE),
                "taxon_id": str(sp.get("taxon_id") or _UNAVAILABLE),
                "has_media": bool(sp.get("has_media", False)),
                "media_attribution": sp.get("media_attribution") or None,
                "sort_key_used": str(sp.get("sort_key") or sp.get("taxon_name") or ""),
            }
        )

    total = len(pool)
    window_seconds = window_hours * 3600
    slots = max(1, window_seconds // rotation_interval_seconds)

    return {
        "genus_name": genus_name,
        "pool_size": total,
        "pool": pool,
        "rotation_plan": {
            "window_hours": window_hours,
            "rotation_interval_seconds": rotation_interval_seconds,
            "slots_in_window": slots,
            "cycles_in_window": (slots / total) if total else 0,
            "deterministic": True,
            "client_side_inference_required": False,
        },
        "deduplication_applied": True,
        "media_eligible_count": sum(1 for s in pool if s["has_media"]),
        "no_media_count": sum(1 for s in pool if not s["has_media"]),
        "graph_mutation": False,
        "publication_boundary": {
            "read_only": True,
            "automatic_publication": False,
        },
    }

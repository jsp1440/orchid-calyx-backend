from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

SCHEMA_VERSION = "oc.atlas-product-path.v1"
_SOURCE_PRECEDENCE = {
    "canonical_reviewed": 0,
    "canonical_unreviewed": 1,
    "provisional": 2,
}
_SENSITIVE_KEYS = {
    "latitude",
    "longitude",
    "lat",
    "lon",
    "lng",
    "coordinates",
    "exact_coordinates",
    "exact_location",
    "private_locality",
    "locality",
    "site",
    "grid_reference",
    "gps",
    "collector",
    "catalogue_number",
}


class AtlasEvidenceState(str, Enum):
    VERIFIED = "VERIFIED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"


class AtlasTourContentState(str, Enum):
    AVAILABLE = "AVAILABLE"
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class CanonicalTaxonBinding:
    taxon_id: str
    scientific_name: str
    source_class: str
    reviewed: bool

    def __post_init__(self) -> None:
        if self.source_class not in _SOURCE_PRECEDENCE:
            raise ValueError(f"unsupported source_class: {self.source_class}")
        if self.source_class == "canonical_reviewed" and not self.reviewed:
            raise ValueError("canonical_reviewed binding must be reviewed")
        if not self.taxon_id or not self.scientific_name:
            raise ValueError("taxon_id and scientific_name are required")

    @property
    def precedence(self) -> int:
        return _SOURCE_PRECEDENCE[self.source_class]

    def to_dict(self) -> dict[str, Any]:
        return {
            "taxon_id": self.taxon_id,
            "scientific_name": self.scientific_name,
            "source_class": self.source_class,
            "reviewed": self.reviewed,
        }


def choose_taxon_binding(bindings: Iterable[CanonicalTaxonBinding]) -> CanonicalTaxonBinding | None:
    ordered = sorted(bindings, key=lambda item: (item.precedence, item.taxon_id, item.scientific_name))
    return ordered[0] if ordered else None


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _safe(item)
            for key, item in value.items()
            if str(key).casefold() not in _SENSITIVE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    return value


@dataclass(frozen=True)
class AtlasProductPath:
    entry_point: str
    taxon_binding: CanonicalTaxonBinding | None
    occurrence_context_available: bool | None
    tour_content_state: AtlasTourContentState
    evidence_state: AtlasEvidenceState
    human_review_required: bool = True
    tour_content: dict[str, Any] | None = None
    occurrence_context: dict[str, Any] | None = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.entry_point not in {"genus", "species"}:
            raise ValueError("entry_point must be genus or species")
        if not self.human_review_required:
            raise ValueError("Atlas product paths must remain human-review gated")
        if self.tour_content_state is AtlasTourContentState.AVAILABLE and self.tour_content is None:
            raise ValueError("AVAILABLE tour content requires reviewed content")
        if self.tour_content_state is not AtlasTourContentState.AVAILABLE and self.tour_content is not None:
            raise ValueError("draft or unavailable tour content cannot be exposed")
        if self.occurrence_context_available is False and self.occurrence_context is not None:
            raise ValueError("occurrence context cannot be supplied when unavailable")
        if self.occurrence_context_available is True and self.occurrence_context is None:
            raise ValueError("available occurrence context requires a payload")

    def to_dict(self) -> dict[str, Any]:
        return _safe(
            {
                "schema_version": self.schema_version,
                "entry_point": self.entry_point,
                "taxon_binding": self.taxon_binding.to_dict() if self.taxon_binding else None,
                "occurrence_context_available": self.occurrence_context_available,
                "occurrence_context": self.occurrence_context,
                "tour_content_state": self.tour_content_state.value,
                "tour_content": self.tour_content,
                "evidence_state": self.evidence_state.value,
                "human_review_required": self.human_review_required,
                "automatic_publication": False,
                "taxonomy_activation": False,
                "production_mutation": False,
            }
        )


def build_unavailable_atlas_snapshot(entry_point: str = "species") -> AtlasProductPath:
    return AtlasProductPath(
        entry_point=entry_point,
        taxon_binding=None,
        occurrence_context_available=None,
        tour_content_state=AtlasTourContentState.UNAVAILABLE,
        evidence_state=AtlasEvidenceState.UNAVAILABLE,
        human_review_required=True,
        tour_content=None,
        occurrence_context=None,
    )


@dataclass
class AtlasNavigationGateway:
    available: bool
    bindings: list[CanonicalTaxonBinding] = field(default_factory=list)
    occurrence_context_by_taxon: dict[str, dict[str, Any]] = field(default_factory=dict)
    reviewed_tour_content_by_taxon: dict[str, dict[str, Any]] = field(default_factory=dict)
    pending_tour_taxa: set[str] = field(default_factory=set)

    def get_product_path(self, *, entry_point: str, taxon_id: str | None = None) -> AtlasProductPath:
        if not self.available:
            return build_unavailable_atlas_snapshot(entry_point)

        candidates = [item for item in self.bindings if taxon_id is None or item.taxon_id == taxon_id]
        binding = choose_taxon_binding(candidates)
        if binding is None:
            return AtlasProductPath(
                entry_point=entry_point,
                taxon_binding=None,
                occurrence_context_available=None,
                tour_content_state=AtlasTourContentState.UNAVAILABLE,
                evidence_state=AtlasEvidenceState.UNKNOWN,
            )

        occurrence_context = self.occurrence_context_by_taxon.get(binding.taxon_id)
        reviewed_tour = self.reviewed_tour_content_by_taxon.get(binding.taxon_id)
        if reviewed_tour is not None:
            tour_state = AtlasTourContentState.AVAILABLE
        elif binding.taxon_id in self.pending_tour_taxa:
            tour_state = AtlasTourContentState.PENDING_REVIEW
        else:
            tour_state = AtlasTourContentState.UNAVAILABLE

        return AtlasProductPath(
            entry_point=entry_point,
            taxon_binding=binding,
            occurrence_context_available=True if occurrence_context is not None else None,
            occurrence_context=occurrence_context,
            tour_content_state=tour_state,
            tour_content=reviewed_tour,
            evidence_state=(
                AtlasEvidenceState.VERIFIED
                if binding.reviewed
                else AtlasEvidenceState.REVIEW_REQUIRED
            ),
        )

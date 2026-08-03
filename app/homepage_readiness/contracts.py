from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class MetricState(str, Enum):
    available = "available"
    unavailable = "unavailable"
    error = "error"


class ReadinessMetric(BaseModel):
    key: str
    label: str
    state: MetricState
    value: int | float | None = None
    numerator: int | None = None
    denominator: int | None = None
    unit: str | None = None
    source: str
    measured_at: datetime | None = None
    limitation: str | None = None


class DomainCoverage(BaseModel):
    domain: str
    species_with_evidence: int | None = None
    accepted_species_total: int | None = None
    percentage: float | None = Field(default=None, ge=0, le=100)
    state: MetricState
    limitation: str | None = None


class HomepageReadinessResponse(BaseModel):
    contract_version: str = "calyx-homepage-readiness-v1"
    generated_at: datetime
    homepage_ready: bool
    redesign_work_may_proceed: bool
    publication_blocked: bool
    metrics: list[ReadinessMetric]
    domain_coverage: list[DomainCoverage]
    blockers: list[str]
    unavailable_metrics: list[str]
    next_actions: list[str]
    scientific_publication_authority: bool = False
    graph_mutation: bool = False


REQUIRED_METRIC_KEYS = {
    "images.total",
    "images.linked_to_taxonomy",
    "images.unlinked",
    "images.broken_taxonomy_target",
    "images.duplicate_url",
    "images.missing_license",
    "images.missing_attribution",
    "species.accepted_total",
    "species.with_usable_image",
    "species.with_species_packet",
    "graph.image_nodes",
    "graph.image_taxon_edges",
    "captions.unique_species_pipeline",
}


def determine_homepage_ready(metrics: list[ReadinessMetric], domains: list[DomainCoverage]) -> tuple[bool, list[str]]:
    by_key = {metric.key: metric for metric in metrics}
    blockers: list[str] = []

    missing = sorted(REQUIRED_METRIC_KEYS - by_key.keys())
    blockers.extend(f"Required metric unavailable: {key}" for key in missing)

    for key in REQUIRED_METRIC_KEYS:
        metric = by_key.get(key)
        if metric is None:
            continue
        if metric.state is not MetricState.available:
            blockers.append(f"Required metric not measured: {key}")

    required_domains = {"taxonomy", "media", "occurrences", "traits", "literature", "pollinators", "mycorrhizae", "climate", "conservation"}
    domain_map = {item.domain: item for item in domains}
    for domain in sorted(required_domains):
        coverage = domain_map.get(domain)
        if coverage is None or coverage.state is not MetricState.available:
            blockers.append(f"Domain coverage unavailable: {domain}")

    unlinked = by_key.get("images.unlinked")
    broken = by_key.get("images.broken_taxonomy_target")
    captions = by_key.get("captions.unique_species_pipeline")
    if unlinked and (unlinked.value or 0) > 0:
        blockers.append("Unresolved image-to-taxonomy links remain")
    if broken and (broken.value or 0) > 0:
        blockers.append("Images reference missing taxonomy targets")
    if captions and captions.value != 1:
        blockers.append("Unique species-caption pipeline is not certified")

    return not blockers, blockers

"""Research Station dataset adapter for governed orchid propagation evidence.

This module converts CALYX-639 propagation observations into deterministic flat rows
that can be registered with the Research Station and later consumed by CALYX-617.
It does not register, publish, mutate the Knowledge Graph, or claim biological
prediction authority.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Sequence

from .recalcitrant_orchid_propagation import (
    ENGINE_VERSION,
    EvidenceAuthority,
    ProtocolObservation,
    queen_of_sheba_observations,
    queen_of_sheba_source,
)

DATASET_SCHEMA_VERSION = "calyx-propagation-evidence-dataset/v1"
RESEARCH_STATION_SCHEMA_REF = "calyx://schemas/propagation-evidence-dataset/v1"


@dataclass(frozen=True)
class SupplementalEvidence:
    evidence_id: str
    source_id: str
    evidence_level: str
    locator: str
    statement: str
    treatment_factor: str | None = None
    treatment_value: str | None = None
    treatment_unit: str | None = None
    duration_value: float | None = None
    duration_unit: str | None = None
    authority: EvidenceAuthority = EvidenceAuthority.REPORTED
    full_text_verified: bool = False
    publication_authority: bool = False

    def digest(self) -> str:
        return _sha(asdict(self))


def _normalize(value: Any) -> Any:
    if isinstance(value, EvidenceAuthority):
        return value.value
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    return value


def _stable(value: Any) -> str:
    return json.dumps(
        _normalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _sha(value: Any) -> str:
    material = value if isinstance(value, str) else _stable(value)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def queen_of_sheba_preview_evidence() -> tuple[SupplementalEvidence, ...]:
    """Bounded publisher-preview details; these do not constitute full-text review."""
    source_id = queen_of_sheba_source().source_id
    return (
        SupplementalEvidence(
            evidence_id="tv-preview-001",
            source_id=source_id,
            evidence_level="publisher_preview_figure_caption",
            locator="figure-caption: primary-protocorm PLB induction",
            statement=(
                "Early secondary-protocorm development is illustrated after 4 weeks "
                "on the 10 µM 2,4-D treatment."
            ),
            treatment_factor="2,4-D",
            treatment_value="10",
            treatment_unit="µM",
            duration_value=4.0,
            duration_unit="weeks",
        ),
        SupplementalEvidence(
            evidence_id="tv-preview-002",
            source_id=source_id,
            evidence_level="publisher_preview_figure_caption",
            locator="figure-caption: HMSAC definition",
            statement=(
                "HMSAC is defined as half-strength Murashige and Skoog medium with "
                "0.1% (w/v) activated charcoal."
            ),
            treatment_factor="activated charcoal",
            treatment_value="0.1",
            treatment_unit="% w/v",
        ),
        SupplementalEvidence(
            evidence_id="tv-preview-003",
            source_id=source_id,
            evidence_level="publisher_preview_figure_caption",
            locator="figure-caption: HMS/HMSAC plantlet comparison",
            statement="The HMS/HMSAC plantlet comparison is illustrated after 20 weeks.",
            duration_value=20.0,
            duration_unit="weeks",
        ),
        SupplementalEvidence(
            evidence_id="tv-preview-004",
            source_id=source_id,
            evidence_level="publisher_preview_figure_caption",
            locator="figure-caption: NAA+BA treatment",
            statement=(
                "The 5 µM NAA + 5 µM BA plantlet treatment is illustrated after "
                "20 weeks of culture in light."
            ),
            treatment_factor="NAA + BA",
            treatment_value="5 + 5",
            treatment_unit="µM + µM",
            duration_value=20.0,
            duration_unit="weeks",
        ),
        SupplementalEvidence(
            evidence_id="tv-preview-005",
            source_id=source_id,
            evidence_level="publisher_preview_figure_caption",
            locator="figure-caption: BA+2,4-D treatment",
            statement=(
                "The 3 µM BA + 0.1 µM 2,4-D plantlet treatment is illustrated after "
                "20 weeks of culture in light."
            ),
            treatment_factor="BA + 2,4-D",
            treatment_value="3 + 0.1",
            treatment_unit="µM + µM",
            duration_value=20.0,
            duration_unit="weeks",
        ),
        SupplementalEvidence(
            evidence_id="tv-preview-006",
            source_id=source_id,
            evidence_level="publisher_preview_figure_caption",
            locator="figure-caption: W3 attribution",
            statement=(
                "W3 is identified as a commercial medium from Western Orchid Laboratories."
            ),
            treatment_factor="W3 medium",
            treatment_value="Western Orchid Laboratories commercial medium",
        ),
    )


def _factor_map(observation: ProtocolObservation) -> dict[str, str]:
    factors: dict[str, str] = {}
    for treatment in observation.treatments:
        key = treatment.factor.strip().casefold().replace(" ", "_").replace(",", "")
        rendered = treatment.value
        if treatment.unit:
            rendered = f"{rendered} {treatment.unit}"
        factors[key] = rendered
    return factors


def propagation_dataset_rows(
    observations: Sequence[ProtocolObservation] | None = None,
) -> list[dict[str, Any]]:
    """Return flat immutable-ready rows for Research Station/analysis use.

    Missing experimental quantities remain null. No value is inferred from prose.
    """
    observations = tuple(observations or queen_of_sheba_observations())
    rows: list[dict[str, Any]] = []
    for observation in sorted(observations, key=lambda item: item.observation_id):
        rows.append(
            {
                "observation_id": observation.observation_id,
                "taxon": observation.taxon,
                "source_id": observation.source_id,
                "authority": observation.authority.value,
                "starting_material": observation.starting_material.value,
                "response_stage": observation.response_stage.value,
                "outcome": observation.outcome,
                "direction": observation.direction,
                "quantitative_value": observation.quantitative_value,
                "quantitative_unit": observation.quantitative_unit,
                "treatment_factors": _factor_map(observation),
                "missing_details": list(observation.missing_details),
                "reproducible_from_current_evidence": (
                    observation.exact_protocol_reproducible_from_current_evidence
                ),
                "observation_sha256": observation.digest(),
            }
        )
    return rows


def canonical_rows_sha256(rows: list[dict[str, Any]]) -> str:
    """Checksum compatible with CALYX-617 ResearchAnalysisWorkflowService."""
    return _sha(rows)


def dataset_package(
    observations: Sequence[ProtocolObservation] | None = None,
    supplemental: Iterable[SupplementalEvidence] | None = None,
) -> dict[str, Any]:
    rows = propagation_dataset_rows(observations)
    supplemental = tuple(supplemental or queen_of_sheba_preview_evidence())
    source = queen_of_sheba_source()
    checksum = canonical_rows_sha256(rows)
    supplemental_payload = [
        {
            **asdict(item),
            "authority": item.authority.value,
            "digest": item.digest(),
        }
        for item in sorted(supplemental, key=lambda item: item.evidence_id)
    ]
    core = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "title": "Thelymitra variegata propagation treatment evidence",
        "taxa": sorted({row["taxon"] for row in rows}),
        "source_ids": sorted({row["source_id"] for row in rows}),
        "row_count": len(rows),
        "rows_checksum_sha256": checksum,
        "rows": rows,
        "supplemental_evidence": supplemental_payload,
        "supplemental_evidence_level": "publisher_preview_not_full_text",
        "source_completeness": source.completeness.value,
        "full_text_required": source.full_text_required,
        "candidate_only": True,
        "scientific_interpretation_generated": False,
        "scientific_publication_authorized": False,
        "knowledge_graph_mutation_authorized": False,
    }
    return {**core, "package_sha256": _sha(core)}


def research_station_registration_packet() -> dict[str, Any]:
    """Return a packet accepted by ResearchStationService.add_dataset.

    This function deliberately does not call add_dataset. Registration is a separate
    authenticated project mutation. Row persistence is also separate because the
    CALYX-453 dataset record stores checksum/provenance metadata, not row bytes.
    """
    package = dataset_package()
    source = queen_of_sheba_source()
    return {
        "dataset_id": "dataset-thelymitra-variegata-propagation-v1",
        "title": package["title"],
        "checksum_sha256": package["rows_checksum_sha256"],
        "schema_ref": RESEARCH_STATION_SCHEMA_REF,
        "provenance": {
            "calyx_build": "CALYX-639",
            "engine_version": ENGINE_VERSION,
            "package_sha256": package["package_sha256"],
            "source_id": source.source_id,
            "source_doi": source.doi,
            "source_completeness": source.completeness.value,
            "full_text_required": source.full_text_required,
            "row_count": package["row_count"],
            "candidate_only": True,
            "publisher_preview_supplemental_count": len(
                package["supplemental_evidence"]
            ),
            "scientific_publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
        },
    }


def dataset_readiness() -> dict[str, Any]:
    package = dataset_package()
    packet = research_station_registration_packet()
    return {
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
        "row_count": package["row_count"],
        "rows_checksum_sha256": package["rows_checksum_sha256"],
        "registration_packet_ready": True,
        "registration_packet": packet,
        "rows_ready_for_calyx_617_analysis": True,
        "rows_persisted_in_research_station": False,
        "row_persistence_dependency": "CALYX-631 immutable registered dataset row transport",
        "full_text_required": package["full_text_required"],
        "scientific_review_required": True,
        "automatic_registration_performed": False,
        "scientific_publication_authorized": False,
        "knowledge_graph_mutation_authorized": False,
        "blockers": [
            "Acquire authorized complete Davis et al. full text before reproduction claims.",
            "Extract negative treatments and exact denominators before comparative inference.",
            "Use CALYX-631 or equivalent immutable row transport before claiming Research Station row persistence.",
        ],
    }

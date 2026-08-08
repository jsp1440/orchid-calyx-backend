"""Governed propagation-protocol intelligence for recalcitrant orchids.

CALYX-639 establishes a candidate-only evidence matrix.  It intentionally
separates observations reported by sources from hypotheses proposed by the
Orchid Continuum.  Nothing in this module is publication authority.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from enum import Enum

ENGINE_VERSION = "calyx-recalcitrant-orchid-propagation/v1"
QUEEN_OF_SHEBA_DOI = "10.1007/s11240-025-03226-9"


class EvidenceAuthority(str, Enum):
    REPORTED = "reported"
    HYPOTHESIS = "hypothesis"


class EvidenceCompleteness(str, Enum):
    ABSTRACT_VERIFIED = "abstract_verified"
    FULL_TEXT_VERIFIED = "full_text_verified"
    INCOMPLETE = "incomplete"


class MaterialClass(str, Enum):
    SEED = "seed"
    PRIMARY_PROTOCORM = "primary_protocorm"
    SECONDARY_PLB = "secondary_plb"
    PLB_DERIVED_PLANTLET = "plb_derived_plantlet"
    TUBER = "tuber"
    MERISTEM = "meristem"
    VEGETATIVE_TISSUE = "vegetative_tissue"


class ResponseStage(str, Enum):
    GERMINATION = "germination"
    PLB_INDUCTION = "plb_induction"
    PLB_REINDUCTION = "plb_reinduction"
    PLANTLET_CONVERSION = "plantlet_conversion"
    TUBERISATION = "tuberisation"
    ACCLIMATIZATION = "acclimatization"


@dataclass(frozen=True)
class SourceEvidence:
    source_id: str
    title: str
    doi: str | None
    authors: tuple[str, ...]
    year: int
    authority: EvidenceAuthority
    completeness: EvidenceCompleteness
    verified_scope: str
    full_text_required: bool
    provenance_notes: tuple[str, ...] = ()

    def digest(self) -> str:
        return _digest(asdict(self))


@dataclass(frozen=True)
class TreatmentFactor:
    factor: str
    value: str
    unit: str | None = None
    reported: bool = True


@dataclass(frozen=True)
class ProtocolObservation:
    observation_id: str
    taxon: str
    source_id: str
    authority: EvidenceAuthority
    starting_material: MaterialClass
    response_stage: ResponseStage
    treatments: tuple[TreatmentFactor, ...]
    outcome: str
    quantitative_value: float | None = None
    quantitative_unit: str | None = None
    direction: str = "reported_effect"
    exact_protocol_reproducible_from_current_evidence: bool = False
    missing_details: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def digest(self) -> str:
        return _digest(asdict(self))


@dataclass(frozen=True)
class CandidateExperiment:
    experiment_id: str
    taxon: str
    question: str
    target_material: MaterialClass
    authority: EvidenceAuthority = EvidenceAuthority.HYPOTHESIS
    evidence_observation_ids: tuple[str, ...] = ()
    direct_evidence_exists: bool = False
    evidence_gap: str = ""
    safeguards: tuple[str, ...] = ()
    suggested_measurements: tuple[str, ...] = ()
    scientific_status: str = "candidate_only_unvalidated"

    def digest(self) -> str:
        return _digest(asdict(self))


@dataclass(frozen=True)
class PropagationReadiness:
    taxon: str
    engine_version: str
    source_count: int
    observation_count: int
    full_text_required: bool
    directly_supported_entry_materials: tuple[str, ...]
    unsupported_entry_materials: tuple[str, ...]
    blockers: tuple[str, ...]
    publication_authority: bool = False
    canonical_graph_mutation_allowed: bool = False


def _normalize(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    return value


def _digest(value) -> str:
    payload = json.dumps(_normalize(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def queen_of_sheba_source() -> SourceEvidence:
    """Return the verified abstract-level Davis et al. source envelope."""
    return SourceEvidence(
        source_id="davis-2025-thelymitra-variegata-plb",
        title=(
            "Protocorm-like body induction and proliferation as a conservation "
            "tool for the threatened Queen of Sheba orchid, Thelymitra variegata"
        ),
        doi=QUEEN_OF_SHEBA_DOI,
        authors=(
            "Belinda J. Davis",
            "Digby Growns",
            "Jason C. Stevens",
            "Anthony A. Scalzo",
        ),
        year=2025,
        authority=EvidenceAuthority.REPORTED,
        completeness=EvidenceCompleteness.ABSTRACT_VERIFIED,
        verified_scope=(
            "Abstract-level methods/results only. Exact sterilization, sample sizes, "
            "complete media recipes, timing, temperature, statistics, and detailed "
            "tuber/deflasking procedures require full-text extraction."
        ),
        full_text_required=True,
        provenance_notes=(
            "Primary protocorms are the demonstrated PLB-induction starting material.",
            "The verified abstract does not demonstrate mature tuber or meristem initiation.",
        ),
    )


def queen_of_sheba_observations() -> tuple[ProtocolObservation, ...]:
    """Encode only findings explicitly available in the verified abstract."""
    source = queen_of_sheba_source()
    shared_missing = (
        "sample_size",
        "replicate_structure",
        "sterilization_protocol",
        "culture_temperature",
        "culture_duration",
        "complete_medium_recipe",
        "statistical_detail",
    )
    return (
        ProtocolObservation(
            observation_id="tv-plb-001",
            taxon="Thelymitra variegata",
            source_id=source.source_id,
            authority=EvidenceAuthority.REPORTED,
            starting_material=MaterialClass.PRIMARY_PROTOCORM,
            response_stage=ResponseStage.PLB_INDUCTION,
            treatments=(TreatmentFactor("2,4-D", "10", "µM"),),
            outcome="Primary protocorms produced secondary protocorm-like bodies.",
            quantitative_value=100.0,
            quantitative_unit="percent primary protocorms responding",
            exact_protocol_reproducible_from_current_evidence=False,
            missing_details=shared_missing,
        ),
        ProtocolObservation(
            observation_id="tv-plantlet-002",
            taxon="Thelymitra variegata",
            source_id=source.source_id,
            authority=EvidenceAuthority.REPORTED,
            starting_material=MaterialClass.SECONDARY_PLB,
            response_stage=ResponseStage.PLANTLET_CONVERSION,
            treatments=(
                TreatmentFactor("Murashige and Skoog basal salts", "half-strength"),
                TreatmentFactor("activated charcoal", "present"),
            ),
            outcome="Secondary PLBs converted to plantlets.",
            exact_protocol_reproducible_from_current_evidence=False,
            missing_details=shared_missing + ("activated_charcoal_concentration",),
        ),
        ProtocolObservation(
            observation_id="tv-plantlet-003",
            taxon="Thelymitra variegata",
            source_id=source.source_id,
            authority=EvidenceAuthority.REPORTED,
            starting_material=MaterialClass.SECONDARY_PLB,
            response_stage=ResponseStage.PLANTLET_CONVERSION,
            treatments=(
                TreatmentFactor("BA", "3", "µM"),
                TreatmentFactor("2,4-D", "0.1", "µM"),
                TreatmentFactor("light", "present"),
            ),
            outcome="Greater conversion to plantlets than activated-charcoal HMS treatment.",
            direction="greater_conversion_reported",
            exact_protocol_reproducible_from_current_evidence=False,
            missing_details=shared_missing + ("exact_conversion_rate",),
        ),
        ProtocolObservation(
            observation_id="tv-plantlet-004",
            taxon="Thelymitra variegata",
            source_id=source.source_id,
            authority=EvidenceAuthority.REPORTED,
            starting_material=MaterialClass.SECONDARY_PLB,
            response_stage=ResponseStage.PLANTLET_CONVERSION,
            treatments=(
                TreatmentFactor("NAA", "5", "µM"),
                TreatmentFactor("BA", "5", "µM"),
                TreatmentFactor("light", "present"),
            ),
            outcome="Greater conversion to plantlets than activated-charcoal HMS treatment.",
            direction="greater_conversion_reported",
            exact_protocol_reproducible_from_current_evidence=False,
            missing_details=shared_missing + ("exact_conversion_rate",),
        ),
        ProtocolObservation(
            observation_id="tv-reinduction-005",
            taxon="Thelymitra variegata",
            source_id=source.source_id,
            authority=EvidenceAuthority.REPORTED,
            starting_material=MaterialClass.PLB_DERIVED_PLANTLET,
            response_stage=ResponseStage.PLB_REINDUCTION,
            treatments=(
                TreatmentFactor("basal medium", "reported; exact recipe requires full text"),
                TreatmentFactor("2,4-D", "10", "µM"),
            ),
            outcome="PLB re-induction was optimized on basal medium with 10 µM 2,4-D.",
            exact_protocol_reproducible_from_current_evidence=False,
            missing_details=shared_missing,
        ),
        ProtocolObservation(
            observation_id="tv-tuber-006",
            taxon="Thelymitra variegata",
            source_id=source.source_id,
            authority=EvidenceAuthority.REPORTED,
            starting_material=MaterialClass.PLB_DERIVED_PLANTLET,
            response_stage=ResponseStage.TUBERISATION,
            treatments=(
                TreatmentFactor("W3 medium", "commercial proprietary"),
                TreatmentFactor("transfer", "repeated"),
            ),
            outcome="Tuberisation was optimized by repeated transfer to W3 medium.",
            exact_protocol_reproducible_from_current_evidence=False,
            missing_details=shared_missing + (
                "W3_composition",
                "transfer_interval",
                "number_of_transfers",
                "tuberisation_rate",
            ),
        ),
    )


def protocol_matrix(
    observations: Sequence[ProtocolObservation] | None = None,
) -> list[dict]:
    """Return a deterministic machine-readable treatment/outcome matrix."""
    observations = tuple(observations or queen_of_sheba_observations())
    rows: list[dict] = []
    for obs in sorted(observations, key=lambda item: item.observation_id):
        rows.append(
            {
                "observation_id": obs.observation_id,
                "taxon": obs.taxon,
                "authority": obs.authority.value,
                "starting_material": obs.starting_material.value,
                "response_stage": obs.response_stage.value,
                "treatments": [asdict(treatment) for treatment in obs.treatments],
                "outcome": obs.outcome,
                "quantitative_value": obs.quantitative_value,
                "quantitative_unit": obs.quantitative_unit,
                "direction": obs.direction,
                "reproducible_from_current_evidence": (
                    obs.exact_protocol_reproducible_from_current_evidence
                ),
                "missing_details": list(obs.missing_details),
                "digest": obs.digest(),
            }
        )
    return rows


def evidence_support_for_entry_material(
    material: MaterialClass,
    observations: Iterable[ProtocolObservation] | None = None,
) -> dict:
    observations = tuple(observations or queen_of_sheba_observations())
    direct = [obs for obs in observations if obs.starting_material == material]
    return {
        "material": material.value,
        "direct_reported_evidence": bool(direct),
        "observation_ids": [obs.observation_id for obs in direct],
        "authority": (
            EvidenceAuthority.REPORTED.value
            if direct
            else EvidenceAuthority.HYPOTHESIS.value
        ),
    }


def vegetative_entry_hypothesis() -> CandidateExperiment:
    """Represent tuber/meristem initiation as a hypothesis, never as Davis evidence."""
    observations = queen_of_sheba_observations()
    relevant = tuple(
        obs.observation_id
        for obs in observations
        if obs.response_stage in {ResponseStage.PLB_INDUCTION, ResponseStage.PLB_REINDUCTION}
    )
    return CandidateExperiment(
        experiment_id="tv-hypothesis-vegetative-entry-001",
        taxon="Thelymitra variegata",
        question=(
            "Can aseptically established meristematic or other vegetative tissue "
            "from cultivated Thelymitra be induced into PLBs and then enter the "
            "reported PLB multiplication pathway?"
        ),
        target_material=MaterialClass.MERISTEM,
        evidence_observation_ids=relevant,
        direct_evidence_exists=False,
        evidence_gap=(
            "The verified Davis et al. abstract demonstrates PLB induction from "
            "primary protocorms and re-induction from PLB-derived plantlets, not "
            "initiation from a mature tuber or meristem."
        ),
        safeguards=(
            "Do not destructively sample an irreplaceable or conservation-critical plant.",
            "Develop asepsis/explant handling on renewable, legally sourced material first.",
            "Require full-text protocol extraction before attempting reproduction.",
            "Record unsuccessful treatments and contamination, not only successes.",
        ),
        suggested_measurements=(
            "contamination_rate",
            "explant_survival_rate",
            "callus_or_plb_induction_rate",
            "time_to_response",
            "phenotypic_abnormality_rate",
            "plantlet_conversion_rate",
            "tuberisation_rate",
        ),
    )


def transfer_candidate_score(
    candidate_material: MaterialClass,
    observations: Iterable[ProtocolObservation] | None = None,
) -> dict:
    """Score evidence proximity without claiming probability of biological success.

    This is deliberately a structural evidence score, not a predictive model.
    """
    observations = tuple(observations or queen_of_sheba_observations())
    direct_count = sum(obs.starting_material == candidate_material for obs in observations)
    plb_bridge_count = sum(
        obs.response_stage in {ResponseStage.PLB_INDUCTION, ResponseStage.PLB_REINDUCTION}
        for obs in observations
    )
    if direct_count:
        score = min(1.0, 0.75 + direct_count * 0.05)
        state = "direct_reported_entry_evidence"
    elif candidate_material in {
        MaterialClass.MERISTEM,
        MaterialClass.TUBER,
        MaterialClass.VEGETATIVE_TISSUE,
    }:
        score = min(0.49, 0.15 + plb_bridge_count * 0.05)
        state = "indirect_bridge_only"
    else:
        score = 0.05
        state = "unsupported"
    return {
        "material": candidate_material.value,
        "evidence_proximity_score": round(score, 3),
        "score_semantics": "structural evidence proximity; not success probability",
        "state": state,
        "direct_evidence_count": direct_count,
        "plb_bridge_observation_count": plb_bridge_count,
        "scientific_validation": False,
    }


def queen_of_sheba_readiness() -> PropagationReadiness:
    observations = queen_of_sheba_observations()
    directly_supported = sorted({obs.starting_material.value for obs in observations})
    unsupported = [
        material.value
        for material in (
            MaterialClass.SEED,
            MaterialClass.TUBER,
            MaterialClass.MERISTEM,
            MaterialClass.VEGETATIVE_TISSUE,
        )
        if material.value not in directly_supported
    ]
    return PropagationReadiness(
        taxon="Thelymitra variegata",
        engine_version=ENGINE_VERSION,
        source_count=1,
        observation_count=len(observations),
        full_text_required=True,
        directly_supported_entry_materials=tuple(directly_supported),
        unsupported_entry_materials=tuple(unsupported),
        blockers=(
            "Acquire and extract the complete Davis et al. paper.",
            "Extract sterilization, medium recipes, sample sizes, timings, temperatures and statistics.",
            "Resolve proprietary W3 medium details or define a documented substitute study.",
            "Do not treat mature-tuber/meristem initiation as established evidence.",
        ),
    )

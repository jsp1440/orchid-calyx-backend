"""Morphological character evidence from images and formal descriptions.

Image side: :class:`ImageCharacterObservation` records what Vision AI (or a
human annotator) saw in one photograph, keeping *observed* apart from
*inferred*, and *not visible* / *cannot determine* apart from *absent*.
:func:`observations_from_vision_bundle` adapts the ``oc-vision-evidence/v1``
bundle produced by the Brain ``vision_ai`` engine and the Calyx vision
lexicon. Absolute measurements are dropped unless the bundle carries a
calibration; nothing is ever inferred from an uncalibrated pixel length.

Literature side: :class:`DescriptionCharacterState` records a state asserted
by a protologue, monograph, revision, dichotomous key, herbarium record or
Matrix trait, with its verbatim text and citation. Conflicting sources are
preserved side by side by :func:`consolidate_description_states`.

Terminology is normalised through an injected Lexicon mapping (synonym ->
canonical character id); unmapped terms are reported, never guessed.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

EVIDENCE_MODES = ("observed", "inferred", "not_visible", "cannot_determine")
MEASUREMENT_BASES = ("calibrated", "relative", "categorical", "uncalibrated", "none")
DESCRIPTION_SOURCE_KINDS = (
    "protologue",
    "monograph",
    "taxonomic_revision",
    "dichotomous_key",
    "herbarium_record",
    "morphological_study",
    "matrix_trait",
    "expert_annotation",
)
CHARACTER_GROUPS = (
    "flower_architecture",
    "sepal_petal",
    "labellum",
    "column",
    "inflorescence",
    "vegetative",
    "color_pattern",
    "surface_texture",
    "venation",
    "diagnostic_anatomy",
    "counts_proportions",
    "measurement",
)


@dataclass(frozen=True)
class ImageCharacterObservation:
    observation_id: str
    image_id: str
    character_id: str
    evidence_mode: str
    state: Any = None  # categorical state, or a number for numeric characters
    unit: str | None = None
    measurement_basis: str = "none"
    confidence: float = 0.0
    method: str = "unspecified"
    model_version: str | None = None
    region_id: str | None = None
    character_group: str | None = None
    verbatim_term: str | None = None
    limitations: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)
    review_state: str = "machine_generated"

    def validate(self) -> list[str]:
        issues = []
        if self.evidence_mode not in EVIDENCE_MODES:
            issues.append("unknown_evidence_mode")
        if self.measurement_basis not in MEASUREMENT_BASES:
            issues.append("unknown_measurement_basis")
        if not 0 <= self.confidence <= 1:
            issues.append("confidence_out_of_range")
        if (
            self.evidence_mode in {"not_visible", "cannot_determine"}
            and self.state is not None
        ):
            issues.append("undetermined_observation_carries_state")
        if (
            self.measurement_basis == "uncalibrated"
            and isinstance(self.state, (int, float))
            and self.unit in {"mm", "cm", "m"}
        ):
            issues.append("absolute_measurement_without_calibration")
        if not self.method:
            issues.append("method_required")
        return issues

    @property
    def comparable(self) -> bool:
        return self.evidence_mode in {"observed", "inferred"} and self.state is not None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["provenance"] = dict(self.provenance)
        return payload


@dataclass(frozen=True)
class DescriptionCharacterState:
    taxon_id: str
    character_id: str
    states: tuple[str, ...] = ()
    numeric_range: tuple[float, float] | None = None
    unit: str | None = None
    source_kind: str = "protologue"
    citation: str = ""
    verbatim_text: str = ""
    certainty: str = "certain"  # certain | probable | uncertain
    verbatim_term: str | None = None

    def validate(self) -> list[str]:
        issues = []
        if self.source_kind not in DESCRIPTION_SOURCE_KINDS:
            issues.append("unknown_source_kind")
        if not self.citation:
            issues.append("citation_required")
        if not self.states and self.numeric_range is None:
            issues.append("state_or_range_required")
        if self.numeric_range and self.numeric_range[0] > self.numeric_range[1]:
            issues.append("numeric_range_inverted")
        if self.certainty not in {"certain", "probable", "uncertain"}:
            issues.append("unknown_certainty")
        return issues


# -- lexicon normalisation ---------------------------------------------------


def normalize_term(term: str, lexicon: Mapping[str, str]) -> str | None:
    """Return the canonical Lexicon character id for ``term`` or ``None``."""
    key = " ".join(term.strip().casefold().replace("_", " ").split())
    if key in lexicon:
        return lexicon[key]
    # Canonical ids map to themselves.
    canonical = set(lexicon.values())
    return term if term in canonical else None


def normalize_lexicon(raw: Mapping[str, str]) -> dict[str, str]:
    return {
        " ".join(k.strip().casefold().replace("_", " ").split()): v
        for k, v in raw.items()
    }


# -- Vision AI adapter -------------------------------------------------------

_VISION_EVIDENCE_KIND = {
    "OBSERVED": "observed",
    "DIRECT": "observed",
    "MEASURED": "observed",
    "INFERRED": "inferred",
    "DERIVED": "inferred",
    "MODEL_INFERRED": "inferred",
}


def observations_from_vision_bundle(
    bundle: Mapping[str, Any],
    *,
    lexicon: Mapping[str, str] | None = None,
    aliases: Mapping[str, str] | None = None,
) -> tuple[list[ImageCharacterObservation], list[dict[str, Any]]]:
    """Adapt an ``oc-vision-evidence/v1`` bundle into character observations.

    Returns ``(observations, unmapped)``. A character id reaches Matrix only
    through an explicit alias or an exact Lexicon mapping.
    """
    lexicon = normalize_lexicon(lexicon or {})
    aliases = dict(aliases or {})
    calibration = bundle.get("calibration") or {}
    calibrated = str(
        calibration.get("state") or calibration.get("status") or ""
    ).upper() in {
        "CALIBRATED",
        "SCALE_BAR",
        "VERIFIED",
    }
    model = (bundle.get("provenance") or {}).get("engine_version") or (
        bundle.get("provenance") or {}
    ).get("model_version")
    image_id = str(
        (bundle.get("image_asset") or {}).get("image_id")
        or bundle.get("image_id")
        or ""
    )
    observations: list[ImageCharacterObservation] = []
    unmapped: list[dict[str, Any]] = []
    for raw in bundle.get("character_observations") or []:
        vision_char = str(raw.get("character_id") or "")
        target = aliases.get(vision_char) or (
            normalize_term(vision_char, lexicon) if lexicon else None
        )
        if target is None:
            unmapped.append(
                {
                    "vision_character": vision_char,
                    "observation_id": raw.get("observation_id"),
                    "reason": "no_lexicon_mapping",
                }
            )
            continue
        basis_raw = str(raw.get("measurement_basis") or "").upper()
        limitations = list(raw.get("limitations") or [])
        state: Any = raw.get("character_state_id")
        unit = raw.get("unit")
        if basis_raw == "CANNOT_DETERMINE":
            mode, basis, state = "cannot_determine", "none", None
        else:
            mode = _VISION_EVIDENCE_KIND.get(
                str(raw.get("evidence_kind") or "").upper(), "inferred"
            )
            if raw.get("numeric_value") is not None:
                if calibrated or basis_raw in {"CALIBRATED", "CALIBRATED_ABSOLUTE"}:
                    state, basis = raw["numeric_value"], "calibrated"
                else:
                    # Never turn an uncalibrated pixel measurement into mm.
                    mode, basis, state = "cannot_determine", "uncalibrated", None
                    limitations.append("UNCALIBRATED_ABSOLUTE_MEASUREMENT_WITHHELD")
            elif raw.get("relative_value") is not None:
                state, basis, unit = raw["relative_value"], "relative", unit or "ratio"
            else:
                basis = "categorical" if state is not None else "none"
                if state is None:
                    mode = "cannot_determine"
        observations.append(
            ImageCharacterObservation(
                observation_id=str(
                    raw.get("observation_id") or f"{image_id}:{vision_char}"
                ),
                image_id=image_id,
                character_id=target,
                evidence_mode=mode,
                state=state,
                unit=unit,
                measurement_basis=basis,
                confidence=float(raw.get("confidence") or 0.0),
                method=str(raw.get("method") or "vision_ai"),
                model_version=model,
                region_id=raw.get("region_id"),
                verbatim_term=vision_char,
                limitations=tuple(limitations),
                provenance={
                    "analysis_id": bundle.get("analysis_id"),
                    "vision_character": vision_char,
                },
            )
        )
    return observations, unmapped


# -- description consolidation and comparison -------------------------------


def consolidate_description_states(
    states: Iterable[DescriptionCharacterState],
) -> dict[str, dict[str, dict[str, Any]]]:
    """Group description states by taxon and character, preserving conflicts.

    For categorical characters the consolidated value is the union of states
    from every source (variation across sources is botanical information),
    and ``conflict`` is set when sources assert disjoint state sets. Numeric
    ranges are widened to the envelope and flagged when they do not overlap.
    """
    grouped: dict[str, dict[str, list[DescriptionCharacterState]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for item in states:
        grouped[item.taxon_id][item.character_id].append(item)
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for taxon_id, characters in grouped.items():
        out[taxon_id] = {}
        for character_id, items in characters.items():
            cat_sets = [
                frozenset(s.casefold() for s in i.states) for i in items if i.states
            ]
            ranges = [i.numeric_range for i in items if i.numeric_range]
            conflict = False
            if len(cat_sets) > 1:
                conflict = any(
                    not (a & b)
                    for idx, a in enumerate(cat_sets)
                    for b in cat_sets[idx + 1 :]
                )
            if len(ranges) > 1:
                conflict = conflict or any(
                    a[1] < b[0] or b[1] < a[0]
                    for idx, a in enumerate(ranges)
                    for b in ranges[idx + 1 :]
                )
            uncertain = all(i.certainty == "uncertain" for i in items)
            out[taxon_id][character_id] = {
                "states": sorted(set().union(*cat_sets)) if cat_sets else [],
                "numeric_range": [min(r[0] for r in ranges), max(r[1] for r in ranges)]
                if ranges
                else None,
                "unit": next((i.unit for i in items if i.unit), None),
                "conflict": conflict,
                "certainty": "uncertain"
                if uncertain or conflict
                else (
                    "probable"
                    if any(i.certainty != "certain" for i in items)
                    else "certain"
                ),
                "sources": [
                    {
                        "source_kind": i.source_kind,
                        "citation": i.citation,
                        "verbatim_text": i.verbatim_text,
                        "states": list(i.states),
                        "numeric_range": list(i.numeric_range)
                        if i.numeric_range
                        else None,
                        "certainty": i.certainty,
                    }
                    for i in items
                ],
            }
    return out


def compare_observation(
    observation: ImageCharacterObservation,
    consolidated: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Compare one image observation with one consolidated description entry.

    Outcomes: ``agree``, ``contradict``, ``not_comparable`` (character not
    visible / undetermined, or the description is silent). A character that
    is not visible in a photograph never contradicts a description.
    """
    base = {
        "character_id": observation.character_id,
        "observation_id": observation.observation_id,
        "observed": observation.state,
        "evidence_mode": observation.evidence_mode,
    }
    if not observation.comparable:
        return {
            **base,
            "outcome": "not_comparable",
            "reason": f"observation_{observation.evidence_mode}",
        }
    if consolidated is None:
        return {**base, "outcome": "not_comparable", "reason": "description_silent"}
    sources = [s["citation"] for s in consolidated.get("sources", [])]
    value = observation.state
    if isinstance(value, (int, float)) and consolidated.get("numeric_range"):
        lo, hi = consolidated["numeric_range"]
        outcome = "agree" if lo <= value <= hi else "contradict"
    elif consolidated.get("states"):
        observed = {
            str(v).casefold()
            for v in (value if isinstance(value, (list, tuple, set)) else [value])
        }
        outcome = "agree" if observed & set(consolidated["states"]) else "contradict"
    else:
        return {**base, "outcome": "not_comparable", "reason": "state_type_mismatch"}
    return {
        **base,
        "outcome": outcome,
        "expected": consolidated.get("states") or consolidated.get("numeric_range"),
        "description_conflict": consolidated.get("conflict", False),
        "description_certainty": consolidated.get("certainty"),
        "citations": sources,
    }

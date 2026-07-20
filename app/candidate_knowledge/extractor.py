from __future__ import annotations

import re
from typing import Any

from .models import CandidateFact, CandidateKind, EvidenceInput


KIND_ALIASES = {kind.value: kind for kind in CandidateKind}
KIND_ALIASES.update({"MORPHOLOGY": CandidateKind.MORPHOLOGY_TERM, "ECOLOGY": CandidateKind.ECOLOGICAL_RELATIONSHIP, "GEOGRAPHY": CandidateKind.GEOGRAPHIC_OCCURRENCE, "PHENOLOGY": CandidateKind.PHENOLOGY_EVENT, "CONSERVATION": CandidateKind.CONSERVATION_ASSERTION, "CULTIVATION": CandidateKind.CULTIVATION_OBSERVATION})


def _kind(value: str) -> CandidateKind:
    try:
        return KIND_ALIASES[value.strip().upper()]
    except KeyError as exc:
        raise ValueError(f"UNSUPPORTED_CANDIDATE_KIND:{value}") from exc


def _declared_facts(evidence: EvidenceInput) -> list[CandidateFact]:
    facts: list[CandidateFact] = []
    for raw in evidence.metadata.get("candidate_facts", []):
        if not isinstance(raw, dict):
            raise ValueError("INVALID_DECLARED_CANDIDATE")
        facts.append(CandidateFact(
            kind=_kind(str(raw.get("kind", ""))),
            subject=str(raw.get("subject", "")).strip(),
            predicate=str(raw.get("predicate", "")).strip(),
            object_value=None if raw.get("object_value") is None else str(raw["object_value"]).strip(),
            numeric_value=None if raw.get("numeric_value") is None else float(raw["numeric_value"]),
            unit=None if raw.get("unit") is None else str(raw["unit"]).strip(),
            qualifiers=dict(raw.get("qualifiers") or {}),
            confidence=float(raw.get("confidence", 0.75)),
            method=str(raw.get("method", "STRUCTURED_SOURCE_FIELD")),
        ))
    return facts


def extract_candidates(evidence: EvidenceInput) -> list[CandidateFact]:
    """Extract conservative candidates; structured facts are preferred over bounded rules."""
    declared = _declared_facts(evidence)
    if declared:
        return declared

    subject = str(evidence.metadata.get("subject") or evidence.metadata.get("taxon") or "").strip()
    if not subject:
        return []
    text = " ".join(evidence.text.split())
    facts: list[CandidateFact] = []
    patterns: tuple[tuple[CandidateKind, str, str], ...] = (
        (CandidateKind.MEASUREMENT, "measurement", r"\b(?:measured|measurement|length|width|height|temperature)\s*(?:was|is|of|:)\s*(-?\d+(?:\.\d+)?)\s*([A-Za-z°%]+)"),
        (CandidateKind.GEOGRAPHIC_OCCURRENCE, "occurs_in", r"\b(?:occurs?|found|distributed)\s+(?:in|at|across)\s+([^.;]{2,100})"),
        (CandidateKind.PHENOLOGY_EVENT, "phenology", r"\b(?:flowers?|flowering|blooms?)\s+(?:in|during|from)\s+([^.;]{2,80})"),
        (CandidateKind.MOLECULAR_MARKER, "molecular_marker", r"\b(?:marker|locus|barcode)\s+(?:was|is|:)\s*([A-Za-z0-9_-]{2,40})"),
        (CandidateKind.CONSERVATION_ASSERTION, "conservation_status", r"\b(?:status|assessed as|classified as)\s+(critically endangered|endangered|vulnerable|near threatened|least concern)\b"),
        (CandidateKind.CULTIVATION_OBSERVATION, "cultivation_observation", r"\b(?:cultivation|cultivated|grows best|requires)\s+([^.;]{2,100})"),
        (CandidateKind.ECOLOGICAL_RELATIONSHIP, "ecological_relationship", r"\b(?:pollinated by|associated with|hosted by|grows with)\s+([^.;]{2,100})"),
        (CandidateKind.TRAIT, "has_trait", r"\b(?:trait|characterized by|distinguished by)\s+([^.;]{2,100})"),
    )
    for kind, predicate, pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        numeric = float(match.group(1)) if kind == CandidateKind.MEASUREMENT else None
        value = None if numeric is not None else match.group(1).strip()
        unit = match.group(2) if numeric is not None and match.lastindex and match.lastindex > 1 else None
        facts.append(CandidateFact(kind, subject, predicate, value, numeric, unit, confidence=0.55))
    return facts

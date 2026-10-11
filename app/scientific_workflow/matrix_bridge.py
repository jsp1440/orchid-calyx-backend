"""Bridge from character evidence to the Matrix Identification engine.

Reuses the governed, deterministic engine in ``runtime/matrix_identification``
and the immutable, content-addressed registry in
``runtime/matrix_identification_registry``.  This bridge only *translates*
evidence into registry payloads; ranking, missing-data accounting and
explanations stay in the existing engine.

Rules kept here:

* UNKNOWN and INAPPLICABLE characters never become candidate states — missing
  data is not biological absence.
* CONTRADICTORY characters are excluded from candidate states and reported in
  candidate provenance; the disagreement is never silently resolved.
* Observation certainty is derived from review status and evidence kind, so
  unreviewed rule extractions rank below reviewed ones, and literature-derived
  evidence stays distinguishable from Vision inference.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from runtime.matrix_identification import Candidate, Observation, rank_candidates
from runtime.matrix_identification_registry import (
    RegistryCharacter,
    create_registry_version,
)

from .evidence import CharacterEvidenceStore
from .extraction import CHARACTERS, CharacterDefinition
from .models import CharacterStateView, EvidenceKind, StateKind

BRIDGE_VERSION = "scientific-workflow-matrix-bridge-001"


def registry_characters(definitions: Iterable[CharacterDefinition] = CHARACTERS) -> list[RegistryCharacter]:
    """Matrix registry characters derived from the shared character schema.

    The lexicon term id and OAO keys travel in ``provenance`` (the registry
    schema's ``concept_id`` slot is reserved for canonical oc_concepts UUIDs,
    which the offline fixture deliberately does not mint).
    """

    characters: list[RegistryCharacter] = []
    for definition in definitions:
        characters.append(
            RegistryCharacter(
                character=definition.character_id,
                label=definition.label,
                description=definition.description,
                value_type=definition.value_type,
                weight=definition.weight,
                concept_id=None,
                provenance={
                    "lexicon_term_id": definition.lexicon_term_id,
                    "oao_entity_key": definition.oao_entity_key,
                    "oao_quality_key": definition.oao_quality_key,
                    "bridge": BRIDGE_VERSION,
                },
            )
        )
    return characters


def _candidate_state(view: CharacterStateView) -> Any:
    if view.state_kind == StateKind.ABSENT:
        return "absent"
    if view.value_normalized is not None:
        return view.value_normalized
    return view.value


def candidates_from_evidence(
    store: CharacterEvidenceStore,
    definitions: Iterable[CharacterDefinition] = CHARACTERS,
    *,
    names: dict[str, str] | None = None,
) -> list[Candidate]:
    """Build Matrix candidates from the evidence store, honestly.

    Only PRESENT/ABSENT views contribute states; CONTRADICTORY characters are
    excluded and listed in the candidate's provenance.
    """

    definitions = list(definitions)
    candidates: list[Candidate] = []
    for taxon_id in store.taxa():
        views = store.views_for_taxon(taxon_id, [d.character_id for d in definitions])
        states: dict[str, Any] = {}
        excluded: list[dict[str, Any]] = []
        sources: set[str] = set()
        for view in views:
            sources.update(record.source.source_id for record in view.records)
            if view.state_kind in {StateKind.PRESENT, StateKind.ABSENT}:
                states[view.character_id] = _candidate_state(view)
            elif view.state_kind == StateKind.CONTRADICTORY:
                excluded.append(
                    {
                        "character_id": view.character_id,
                        "reason": "contradictory_sources",
                        "disagreement": list(view.disagreement),
                    }
                )
        candidates.append(
            Candidate(
                taxon_id=taxon_id,
                scientific_name=(names or {}).get(taxon_id, taxon_id),
                states=states,
                provenance={
                    "evidence_kinds": sorted({str(record.evidence_kind) for view in views for record in view.records}),
                    "source_ids": sorted(sources),
                    "excluded_characters": excluded,
                    "bridge": BRIDGE_VERSION,
                },
            )
        )
    return candidates


def observations_from_views(
    views: Iterable[CharacterStateView],
    definitions: Iterable[CharacterDefinition] = CHARACTERS,
    *,
    evidence_kind: EvidenceKind = EvidenceKind.LITERATURE,
) -> list[Observation]:
    """Turn one taxon's character views into identification observations.

    Certainty ladder: reviewed literature -> certain; unreviewed rule
    extraction -> probable; Vision inference -> uncertain.  UNKNOWN and
    INAPPLICABLE views never become observations; CONTRADICTORY views become
    ``unknown`` observations, which the engine weights at zero and reports as
    ``ignored_unknown_observation``.
    """

    weights = {definition.character_id: definition.weight for definition in definitions}
    observations: list[Observation] = []
    for view in views:
        if view.state_kind in {StateKind.UNKNOWN, StateKind.INAPPLICABLE}:
            continue
        if view.state_kind == StateKind.CONTRADICTORY:
            observations.append(
                Observation(
                    character=view.character_id,
                    value=None,
                    certainty="unknown",
                    weight=weights.get(view.character_id, 1.0),
                )
            )
            continue
        records = [record for record in view.records if record.evidence_kind == evidence_kind]
        if not records:
            records = list(view.records)
        reviewed = any(record.review_status in {"accepted", "corrected"} for record in records)
        if evidence_kind == EvidenceKind.VISION_INFERENCE:
            certainty = "uncertain"
        elif reviewed:
            certainty = "certain"
        else:
            certainty = "probable"
        observations.append(
            Observation(
                character=view.character_id,
                value=_candidate_state(view),
                certainty=certainty,
                weight=weights.get(view.character_id, 1.0),
            )
        )
    return observations


def persist_registry(
    store: CharacterEvidenceStore,
    *,
    registry_id: str,
    version: str,
    title: str,
    scope: dict[str, Any],
    actor: str,
    root: Path | None = None,
    definitions: Iterable[CharacterDefinition] = CHARACTERS,
) -> dict[str, Any]:
    """Persist an immutable registry version built from the evidence store."""

    definitions = list(definitions)
    receipt = create_registry_version(
        registry_id=registry_id,
        version=version,
        title=title,
        scope=scope,
        characters=registry_characters(definitions),
        candidates=candidates_from_evidence(store, definitions),
        provenance={
            "bridge": BRIDGE_VERSION,
            "source": "scientific_workflow evidence store (offline fixtures)",
            "evidence_policy": {
                "unknown_is_not_absence": True,
                "contradictory_characters_excluded_and_reported": True,
                "publication_state": "review_required",
            },
        },
        actor=actor,
        root=root,
    )
    return receipt


def identify(
    observations: list[Observation],
    candidates: list[Candidate],
    *,
    limit: int = 20,
) -> dict[str, Any]:
    """Rank candidates with the governed engine; results are ranking evidence,
    never a taxonomic determination (engine disclaimer preserved)."""

    return rank_candidates(observations, candidates, limit=limit)

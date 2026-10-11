"""Bridge from character evidence to Species Dossier envelopes.

Builds ``oc-species-dossier-v1`` envelopes (``app.species_dossier.models``)
from the offline evidence store.  Conventions mirror the production
Postgres-backed repository (``app.species_dossier.repository``):

* every emitted statement carries an ``EvidenceReceipt`` naming its source;
* sections without data are UNAVAILABLE with an explicit reason — never
  filled with plausible text;
* distribution stays unserved for the same reason the production repository
  gives (occurrence/locality protection), reusing its exact wording;
* fixture-derived content is PROVISIONAL and its receipts say the source is a
  synthetic test fixture, so nothing extracted here can masquerade as
  verified science.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.species_dossier.models import (
    DossierEvidenceState,
    DossierFreshness,
    DossierSection,
    EvidenceReceipt,
    SpeciesAtlasEnvelope,
    SpeciesDossierEnvelope,
    SpeciesIdentity,
)
from app.species_dossier.repository import DISTRIBUTION_REASON

from .evidence import CharacterEvidenceStore
from .extraction import CHARACTERS
from .models import CharacterStateView, StateKind
from .taxonomy import TaxonRecord

BRIDGE_VERSION = "scientific-workflow-dossier-bridge-001"

_NOT_ASSEMBLED = (
    "This section is not assembled by the offline scientific workflow; "
    "the canonical dossier service remains the governed source."
)


def _receipt(view_record: Any) -> EvidenceReceipt:
    source = view_record.source
    return EvidenceReceipt(
        source_id=source.source_id,
        source_name=source.source_name,
        source_url=source.url,
        record_id=view_record.record_id,
        license=source.license,
        attribution=source.attribution,
        evidence_state=DossierEvidenceState.PROVISIONAL,
        confidence=view_record.confidence,
        notes=(
            f"{source.source_type}; {source.notes or ''}".strip("; ")
            + f" | method={view_record.provenance_method}"
            + f" | extractor={view_record.extractor} {view_record.extractor_version}"
            + f" | review_status={view_record.review_status}"
        ),
    )


def _unavailable(reason: str) -> DossierSection:
    return DossierSection(state=DossierEvidenceState.UNAVAILABLE, unavailable_reason=reason)


def _morphology_item(view: CharacterStateView) -> dict[str, Any]:
    item: dict[str, Any] = {
        "character_id": view.character_id,
        "state_kind": str(view.state_kind),
        "value": view.value,
        "unit_normalized": view.unit_normalized,
        "value_normalized": view.value_normalized,
    }
    if view.state_kind == StateKind.CONTRADICTORY:
        item["disagreement"] = list(view.disagreement)
        item["note"] = "Sources disagree; all reports retained, none preferred."
    elif view.state_kind == StateKind.UNKNOWN:
        item["note"] = "Not reported by any loaded source; not evidence of absence."
    elif view.state_kind == StateKind.INAPPLICABLE:
        item["note"] = "Character cannot apply to this taxon given other stated characters."
    else:
        item["excerpts"] = [
            record.span.excerpt for record in view.records if record.span is not None
        ]
    return item


def build_dossier(
    taxon: TaxonRecord,
    store: CharacterEvidenceStore,
    *,
    registry_ref: dict[str, str] | None = None,
    public_base_url: str = "https://orchidcontinuum.org",
) -> SpeciesDossierEnvelope:
    views = store.views_for_taxon(taxon.taxon_id, [d.character_id for d in CHARACTERS])
    generated_at = datetime.now(UTC)

    all_receipts = [
        _receipt(record)
        for view in views
        for record in view.records
        if record.state_kind != StateKind.UNKNOWN
    ]
    # De-duplicate receipts by (source_id, record_id).
    seen: set[tuple[str, str]] = set()
    unique_receipts: list[EvidenceReceipt] = []
    for receipt in all_receipts:
        key = (receipt.source_id, receipt.record_id or "")
        if key not in seen:
            seen.add(key)
            unique_receipts.append(receipt)

    morphology_items = [_morphology_item(view) for view in views]
    morphology_receipts = [
        _receipt(record)
        for view in views
        for record in view.records
        if view.state_kind in {StateKind.PRESENT, StateKind.ABSENT, StateKind.CONTRADICTORY}
    ]

    unknown_characters = [view.character_id for view in views if view.state_kind == StateKind.UNKNOWN]
    contradictory = [view.character_id for view in views if view.state_kind == StateKind.CONTRADICTORY]

    sources = sorted(
        {
            (record.source.source_id, record.source.source_name, record.source.source_type)
            for view in views
            for record in view.records
        }
    )

    matrix_url = f"{public_base_url}/matrix?origin=species-dossier&taxon_id={taxon.taxon_id}"

    def _state_for(items: list[Any]) -> DossierEvidenceState:
        return DossierEvidenceState.PROVISIONAL if items else DossierEvidenceState.UNAVAILABLE

    morphology = DossierSection(
        state=_state_for(morphology_items),
        summary=(
            f"{sum(1 for view in views if view.state_kind == StateKind.PRESENT)} characters reported, "
            f"{sum(1 for view in views if view.state_kind == StateKind.ABSENT)} explicitly absent, "
            f"{len(unknown_characters)} unreported, {len(contradictory)} contradictory. "
            "All values are unreviewed rule extractions from the cited sources."
        ),
        items=morphology_items,
        receipts=morphology_receipts,
        unavailable_reason=None if morphology_items else "No morphology evidence loaded.",
    )

    literature = DossierSection(
        state=_state_for(sources),
        items=[
            {"source_id": source_id, "source_name": name, "source_type": kind}
            for source_id, name, kind in sources
        ],
        receipts=unique_receipts,
        unavailable_reason=None if sources else "No literature sources were loaded in this run.",
    )

    flowering = next((view for view in views if view.character_id == "flowering_period"), None)
    phenology = (
        DossierSection(
            state=DossierEvidenceState.PROVISIONAL,
            summary=f"Flowering period as stated by the source: {flowering.value}.",
            items=[{"flowering_period": flowering.value}],
            receipts=[_receipt(record) for record in flowering.records],
        )
        if flowering is not None and flowering.state_kind == StateKind.PRESENT
        else _unavailable("No phenology statement was loaded from any source.")
    )

    habit = next((view for view in views if view.character_id == "habit"), None)
    ecology = (
        DossierSection(
            state=DossierEvidenceState.PROVISIONAL,
            items=[{"habit": habit.value}],
            receipts=[_receipt(record) for record in habit.records],
        )
        if habit is not None and habit.state_kind == StateKind.PRESENT
        else _unavailable("No habit or ecology statement was loaded from any source.")
    )

    identification_matrix = (
        DossierSection(
            state=DossierEvidenceState.PROVISIONAL,
            summary="Matrix registry version built from this workflow's evidence store.",
            items=[registry_ref] if registry_ref else [],
        )
        if registry_ref
        else _unavailable("No matrix registry was persisted for this taxon in this run.")
    )

    research_gaps = DossierSection(
        state=DossierEvidenceState.AVAILABLE,
        summary="Characters with no loaded evidence, kept visible instead of being filled in.",
        items=[
            {"character_id": character_id, "status": "unreported"}
            for character_id in unknown_characters
        ]
        + [
            {"character_id": character_id, "status": "contradictory_unresolved"}
            for character_id in contradictory
        ],
    )

    identity = SpeciesIdentity(
        taxon_id=taxon.taxon_id,
        display_name=taxon.accepted_name,
        full_scientific_name=taxon.full_scientific_name,
        accepted_name=taxon.accepted_name,
        authorship=taxon.authorship,
        rank="species",
        genus=taxon.genus,
        specific_epithet=taxon.specific_epithet,
        taxonomic_status="accepted",
        synonyms=list(taxon.synonyms),
    )

    atlas = SpeciesAtlasEnvelope(
        taxon_id=taxon.taxon_id,
        generated_at=generated_at,
        layers=[],
        unavailable_layers=["occurrences", "countries", "elevation", "phenology", "habitat"],
        provenance=[],
    )

    unavailable_sections = [
        name
        for name, section in (
            ("protologue", None),
            ("type_material", None),
            ("historical_media", None),
            ("living_media", None),
            ("distribution", None),
            ("pollinators", None),
            ("mycorrhizae", None),
            ("conservation", None),
            ("cultivation", None),
            ("knowledge_graph", None),
            ("calyx_narrative", None),
            ("atlas_summary", None),
        )
    ]

    return SpeciesDossierEnvelope(
        generated_at=generated_at,
        taxon_id=taxon.taxon_id,
        display_name=taxon.accepted_name,
        full_scientific_name=taxon.full_scientific_name,
        accepted_name=taxon.accepted_name,
        identity=identity,
        nomenclature=DossierSection(
            state=DossierEvidenceState.PROVISIONAL,
            items=[
                {
                    "accepted_name": taxon.accepted_name,
                    "authorship": taxon.authorship,
                    "family": taxon.family,
                    "resolver": "curated offline fixture (no live POWO/IPNI call in this run)",
                }
            ],
        ),
        protologue=_unavailable(_NOT_ASSEMBLED),
        type_material=_unavailable(_NOT_ASSEMBLED),
        historical_media=_unavailable(_NOT_ASSEMBLED),
        living_media=_unavailable(_NOT_ASSEMBLED),
        morphology=morphology,
        distribution=_unavailable(DISTRIBUTION_REASON),
        ecology=ecology,
        phenology=phenology,
        pollinators=_unavailable(_NOT_ASSEMBLED),
        mycorrhizae=_unavailable(_NOT_ASSEMBLED),
        conservation=_unavailable(_NOT_ASSEMBLED),
        literature=literature,
        cultivation=_unavailable(_NOT_ASSEMBLED),
        knowledge_graph=_unavailable(_NOT_ASSEMBLED),
        calyx_narrative=_unavailable(_NOT_ASSEMBLED),
        research_gaps=research_gaps,
        atlas=atlas,
        atlas_summary=_unavailable("No atlas layers are served by the offline workflow."),
        identification_matrix=identification_matrix,
        freshness=DossierFreshness(state="unknown", source="offline fixture workflow"),
        unavailable_sections=unavailable_sections,
        related_species=[],
        matrix_url=matrix_url,
        partner_references=[],
        provenance=unique_receipts,
    )

"""Owner-gated shared image-intelligence API (IMAGE-INTEL-001).

Shared service surface for Matrix, Vision AI, Atlas, Featured Genus, Species
Dossiers, Lexicon, Literature, Conservation and Brain. Every endpoint is
read-only or computes over the request payload; none mutates canonical
taxonomy, the knowledge graph, or image storage, and none downloads images.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.image_characters import (
    DescriptionCharacterState,
    ImageCharacterObservation,
    consolidate_description_states,
    observations_from_vision_bundle,
)
from runtime.image_evidence_graph import (
    character_links,
    depicts_links,
    hypothesis_links,
)
from runtime.image_inventory import (
    AcceptedTaxon,
    ImageInventoryRepository,
    compute_coverage,
)
from runtime.image_training_partitions import (
    build_dataset_manifest,
    evaluate_predictions,
)
from runtime.reference_identification import (
    CalibrationTable,
    IdentificationOptions,
    QueryImage,
    identify,
)
from runtime.reference_images import (
    ORGANS,
    RECORD_KINDS,
    SCHEMA_VERSION,
    VERIFICATION_STATUSES,
    VIEWPOINTS,
    ReferenceImageRecord,
    VerificationEvent,
    apply_verification,
    group_duplicates,
)

CONTRACT_VERSION = "oc-image-intelligence-v1"

router = APIRouter(prefix="/api/image-intelligence", tags=["image-intelligence"])


class VerificationEventInput(BaseModel):
    decision: Literal["confirm", "reject", "revise", "dispute"]
    verifier: str = Field(min_length=1, max_length=200)
    verified_on: str | None = None
    revised_taxon_id: str | None = None
    revised_name: str | None = None
    basis: str | None = None
    expert: bool = True


class ReferenceImageInput(BaseModel):
    image_id: str = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1, max_length=60)
    source_record_id: str = Field(min_length=1, max_length=300)
    verbatim_name: str | None = None
    original_identification: str | None = None
    accepted_taxon_id: str | None = None
    accepted_name: str | None = None
    taxonomic_authority: str | None = None
    taxonomy_version: str | None = None
    record_kind: str = "unknown"
    specimen_id: str | None = None
    occurrence_id: str | None = None
    verification_status: str = "unverified_source_identification"
    verifier: str | None = None
    verified_on: str | None = None
    image_url: str | None = None
    storage_ref: str | None = None
    license: str | None = None
    rights_holder: str | None = None
    attribution: str | None = None
    organ: str = "unknown"
    viewpoint: str = "unknown"
    quality: str = "unassessed"
    has_scale: bool = False
    scale_basis: str | None = None
    identification_confidence: float | None = Field(default=None, ge=0, le=1)
    uncertainty_notes: list[str] = Field(default_factory=list)
    content_sha256: str | None = None
    perceptual_hash: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)

    def to_record(self) -> ReferenceImageRecord:
        data = self.model_dump()
        data["uncertainty_notes"] = tuple(data["uncertainty_notes"])
        return ReferenceImageRecord(**data)


class TaxonInput(BaseModel):
    taxon_id: str = Field(min_length=1, max_length=200)
    scientific_name: str = Field(min_length=2, max_length=300)
    genus: str = Field(min_length=1, max_length=120)
    rank: str = "species"


class CharacterObservationInput(BaseModel):
    observation_id: str = Field(min_length=1, max_length=200)
    image_id: str = Field(min_length=1, max_length=200)
    character_id: str = Field(min_length=1, max_length=200)
    evidence_mode: Literal["observed", "inferred", "not_visible", "cannot_determine"]
    state: Any = None
    unit: str | None = None
    measurement_basis: Literal[
        "calibrated", "relative", "categorical", "uncalibrated", "none"
    ] = "none"
    confidence: float = Field(default=0.0, ge=0, le=1)
    method: str = Field(default="unspecified", min_length=1)
    model_version: str | None = None
    region_id: str | None = None
    limitations: list[str] = Field(default_factory=list)


class DescriptionStateInput(BaseModel):
    taxon_id: str
    character_id: str
    states: list[str] = Field(default_factory=list)
    numeric_range: tuple[float, float] | None = None
    unit: str | None = None
    source_kind: str = "protologue"
    citation: str = Field(min_length=1)
    verbatim_text: str = ""
    certainty: Literal["certain", "probable", "uncertain"] = "certain"


class ReferencesRequest(BaseModel):
    records: list[ReferenceImageInput] = Field(min_length=1, max_length=20000)


class VerifyRequest(BaseModel):
    record: ReferenceImageInput
    event: VerificationEventInput


class CoverageRequest(BaseModel):
    records: list[ReferenceImageInput] = Field(default_factory=list, max_length=200000)
    taxa: list[TaxonInput] = Field(min_length=1, max_length=40000)
    described_taxon_ids: list[str] = Field(default_factory=list)
    keyed_taxon_ids: list[str] = Field(default_factory=list)
    taxonomy_version: str | None = None
    gap_limit: int = Field(default=100, ge=0, le=5000)
    include_species: bool = False


class IdentifyRequest(BaseModel):
    query_image_id: str = Field(min_length=1, max_length=200)
    observations: list[CharacterObservationInput] = Field(
        default_factory=list, max_length=500
    )
    vision_bundle: dict[str, Any] | None = None
    lexicon: dict[str, str] = Field(default_factory=dict)
    vision_aliases: dict[str, str] = Field(default_factory=dict)
    query_embedding: list[float] | None = Field(default=None, max_length=4096)
    query_organ: str = "unknown"
    query_viewpoint: str = "unknown"
    query_has_scale: bool = False
    taxa: list[TaxonInput] = Field(min_length=1, max_length=5000)
    description_states: list[DescriptionStateInput] = Field(
        default_factory=list, max_length=50000
    )
    references: list[ReferenceImageInput] = Field(
        default_factory=list, max_length=20000
    )
    reference_embeddings: dict[str, list[float]] = Field(default_factory=dict)
    candidate_taxon_ids: list[str] = Field(default_factory=list)
    calibration_bins: list[tuple[float, float]] | None = None
    calibration_evaluation_id: str | None = None
    include_graph_links: bool = False


class ManifestRequest(BaseModel):
    records: list[ReferenceImageInput] = Field(min_length=1, max_length=200000)
    taxonomy_version: str = Field(min_length=1)
    seed: str = "oc-image-dataset"
    ratios: tuple[float, float, float] = (0.7, 0.15, 0.15)
    min_groups_per_taxon: int = Field(default=1, ge=1, le=1000)
    open_set_taxon_ids: list[str] = Field(default_factory=list)
    dataset_name: str = "oc-reference-images"


class EvaluateRequest(BaseModel):
    manifest: dict[str, Any]
    predictions: dict[str, dict[str, Any]]
    genus_of: dict[str, str]
    split: Literal["train", "validation", "test"] = "test"


@router.get("/contract")
def contract(_: Any = Depends(verify_owner_or_api_key)) -> dict[str, Any]:  # noqa: B008
    return {
        "contract_version": CONTRACT_VERSION,
        "reference_image_schema": SCHEMA_VERSION,
        "verification_statuses": list(VERIFICATION_STATUSES),
        "organs": list(ORGANS),
        "viewpoints": list(VIEWPOINTS),
        "record_kinds": list(RECORD_KINDS),
        "endpoints": {
            "inventory": "GET /api/image-intelligence/inventory",
            "coverage": "POST /api/image-intelligence/coverage",
            "references_validate": "POST /api/image-intelligence/references/validate",
            "references_verify": "POST /api/image-intelligence/references/verify",
            "identify": "POST /api/image-intelligence/identify",
            "dataset_manifest": "POST /api/image-intelligence/datasets/manifest",
            "evaluate": "POST /api/image-intelligence/datasets/evaluate",
        },
        "consumers": [
            "matrix",
            "vision_ai",
            "atlas",
            "featured_genus",
            "species_dossier",
            "lexicon",
            "literature",
            "conservation",
            "calyx",
            "brain",
        ],
        "rules": [
            "accepted taxonomy and specimen identification verification are separate fields",
            "source identifications are never treated as ground truth",
            "only expert-verified images with allowed licenses are training labels",
            "visual similarity is supporting evidence, never an identification by itself",
            "not-visible characters never count as absent",
            "absolute measurements require calibration",
            "identification outputs are provisional and non-authoritative",
            "every image of a specimen stays in one data split",
        ],
        "governance": {
            "canonical_taxonomy_mutation": False,
            "knowledge_graph_mutation": False,
            "image_downloads": False,
            "paid_inference": False,
            "trained_model": None,
        },
    }


@router.get("/inventory")
def inventory(_: Any = Depends(verify_owner_or_api_key)) -> dict[str, Any]:  # noqa: B008
    """Read-only aggregate inventory over existing image tables."""
    try:
        from sqlalchemy import text

        from app.database import get_engine

        engine = get_engine()
    except Exception as exc:  # noqa: BLE001  # pragma: no cover - environment specific
        return {"state": "unavailable", "reason": type(exc).__name__, "read_only": True}

    if engine.dialect.name != "postgresql":
        return {
            "state": "unavailable",
            "reason": "postgres_required",
            "read_only": True,
        }

    with engine.connect() as conn:
        conn.exec_driver_sql("SET TRANSACTION READ ONLY")

        def execute(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
            return [dict(row) for row in conn.execute(text(sql), params).mappings()]

        report = ImageInventoryRepository(execute).inventory()
        conn.rollback()
    return {"state": "available", **report}


@router.post("/coverage")
def coverage(
    payload: CoverageRequest,
    _: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    report = compute_coverage(
        [r.to_record() for r in payload.records],
        [AcceptedTaxon(**t.model_dump()) for t in payload.taxa],
        described_taxon_ids=payload.described_taxon_ids,
        keyed_taxon_ids=payload.keyed_taxon_ids,
        taxonomy_version=payload.taxonomy_version,
        gap_limit=payload.gap_limit,
    )
    if not payload.include_species:
        report.pop("species")
    return report


@router.post("/references/validate")
def validate_references(
    payload: ReferencesRequest,
    _: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    records = group_duplicates([r.to_record() for r in payload.records])
    rows = [{**r.as_dict(), "issues": r.validate()} for r in records]
    return {
        "records": rows,
        "valid": sum(1 for r in rows if not r["issues"]),
        "training_label_eligible": sum(1 for r in rows if r["training_label_eligible"]),
        "duplicate_groups": len(
            {r["duplicate_group_id"] for r in rows if r["duplicate_group_id"]}
        ),
        "graph_links": [link.as_record() for link in depicts_links(records)],
    }


@router.post("/references/verify")
def verify_reference(
    payload: VerifyRequest,
    _: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    try:
        updated = apply_verification(
            payload.record.to_record(), VerificationEvent(**payload.event.model_dump())
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "record": updated.as_dict(),
        "issues": updated.validate(),
        "persisted": False,
    }


@router.post("/identify")
def identify_image(
    payload: IdentifyRequest,
    _: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    observations = [
        ImageCharacterObservation(
            **{**o.model_dump(), "limitations": tuple(o.limitations)}
        )
        for o in payload.observations
    ]
    unmapped: list[dict[str, Any]] = []
    if payload.vision_bundle:
        adapted, unmapped = observations_from_vision_bundle(
            payload.vision_bundle,
            lexicon=payload.lexicon,
            aliases=payload.vision_aliases,
        )
        observations.extend(adapted)
    descriptions = consolidate_description_states(
        DescriptionCharacterState(**{**d.model_dump(), "states": tuple(d.states)})
        for d in payload.description_states
    )
    calibration = (
        CalibrationTable(
            bins=tuple(payload.calibration_bins),
            evaluation_id=payload.calibration_evaluation_id or "unspecified",
        )
        if payload.calibration_bins
        else None
    )
    try:
        result = identify(
            QueryImage(
                image_id=payload.query_image_id,
                observations=observations,
                embedding=payload.query_embedding,
                organ=payload.query_organ,
                viewpoint=payload.query_viewpoint,
                has_scale=payload.query_has_scale,
            ),
            taxa={t.taxon_id: AcceptedTaxon(**t.model_dump()) for t in payload.taxa},
            descriptions=descriptions,
            references=[r.to_record() for r in payload.references],
            reference_embeddings=payload.reference_embeddings,
            candidate_taxon_ids=payload.candidate_taxon_ids,
            calibration=calibration,
            options=IdentificationOptions(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result["unmapped_vision_characters"] = unmapped
    if payload.include_graph_links:
        result["graph_links"] = [
            link.as_record()
            for link in (*character_links(observations), *hypothesis_links(result))
        ]
    return result


@router.post("/datasets/manifest")
def dataset_manifest(
    payload: ManifestRequest,
    _: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    try:
        return build_dataset_manifest(
            [r.to_record() for r in payload.records],
            taxonomy_version=payload.taxonomy_version,
            seed=payload.seed,
            ratios=payload.ratios,
            min_groups_per_taxon=payload.min_groups_per_taxon,
            open_set_taxon_ids=payload.open_set_taxon_ids,
            dataset_name=payload.dataset_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/datasets/evaluate")
def dataset_evaluate(
    payload: EvaluateRequest,
    _: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    try:
        return evaluate_predictions(
            payload.manifest,
            payload.predictions,
            genus_of=payload.genus_of,
            split=payload.split,
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

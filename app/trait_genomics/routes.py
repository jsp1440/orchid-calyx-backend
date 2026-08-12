from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key, verify_owner_session

from .discovery import TraitGenomicsDiscoveryEngine
from .live_sources import LiveScientificEvidenceBuilder
from .models import DiscoveryDataset, DiscoveryResult
from .release_service import ScientificArchiveReleaseService
from .repository import TraitGenomicsRepository
from .zenodo import ZenodoArchiveBridge, ZenodoConfig

router = APIRouter(
    prefix="/api/trait-genomics",
    tags=["trait-genomics"],
    dependencies=[Depends(verify_owner_or_api_key)],
)


class DiscoveryRunRequest(BaseModel):
    dataset: DiscoveryDataset
    persist: bool = True


class ArchiveRequest(BaseModel):
    dataset: DiscoveryDataset
    result: DiscoveryResult | None = None


class ZenodoDraftRequest(BaseModel):
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    creators: list[dict[str, str]] = Field(min_length=1)


class VersionedArchiveDraftRequest(BaseModel):
    dataset: DiscoveryDataset
    creators: list[dict[str, str]] = Field(min_length=1)
    title: str | None = None
    description: str | None = None


class LiveEvidenceRequest(BaseModel):
    limit_per_domain: int = Field(default=1000, ge=1, le=10000)
    taxon_ids: list[str] = Field(default_factory=list, max_length=1000)
    include_phylogenetic_context: bool = True
    persist: bool = True


class LiveArchiveDraftRequest(LiveEvidenceRequest):
    creators: list[dict[str, str]] = Field(min_length=1)
    title: str | None = None
    description: str | None = None
    require_hypotheses: bool = True


@router.get("/status")
def status():
    config = ZenodoConfig.from_env()
    return {
        "module": "calyx_trait_interaction_genomics_discovery_engine",
        "operational_store": "neon_postgres",
        "archive_store": "zenodo",
        "database_configured": bool(os.getenv("DATABASE_URL")),
        "zenodo_configured": bool(config.token),
        "zenodo_base": config.base_url,
        "zenodo_community": config.community,
        "scientific_archive_ledger": "neon_postgres",
        "archive_draft_mode": "versioned_checksums_idempotent",
        "live_evidence_adapter": "canonical_sources_schema_tolerant_strict_taxon_identity",
        "causal_policy": "hypotheses_are_non_causal_until_reviewed",
        "zenodo_publication_enabled": False,
    }


@router.post("/discover", response_model=DiscoveryResult)
def discover(payload: DiscoveryRunRequest):
    engine = TraitGenomicsDiscoveryEngine()
    result = engine.discover(payload.dataset)
    if payload.persist:
        try:
            repository = TraitGenomicsRepository()
            repository.save_dataset(payload.dataset)
            repository.save_hypotheses(payload.dataset.dataset_id, result.hypotheses)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Trait-genomics persistence failed: {exc}") from exc
    return result


@router.get("/live/readiness")
def live_readiness():
    try:
        return LiveScientificEvidenceBuilder().readiness()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Live TIG readiness failed: {exc}") from exc


def _build_live_dataset(payload: LiveEvidenceRequest):
    try:
        return LiveScientificEvidenceBuilder().build_dataset(
            limit_per_domain=payload.limit_per_domain,
            taxon_ids=payload.taxon_ids or None,
            include_phylogenetic_context=payload.include_phylogenetic_context,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Live TIG evidence build failed: {exc}") from exc


@router.post("/live/dataset")
def live_dataset(payload: LiveEvidenceRequest):
    dataset, diagnostics = _build_live_dataset(payload)
    return {
        "dataset": dataset,
        "diagnostics": diagnostics,
        "scientific_boundary": (
            "Rows without canonical taxon identifiers are skipped; raw phylogenetic "
            "sequence presence is contextual and cannot satisfy the TIG association domain."
        ),
    }


@router.post("/live/discover")
def live_discover(payload: LiveEvidenceRequest):
    dataset, diagnostics = _build_live_dataset(payload)
    result = TraitGenomicsDiscoveryEngine().discover(dataset)
    if payload.persist:
        try:
            repository = TraitGenomicsRepository()
            repository.save_dataset(dataset)
            repository.save_hypotheses(dataset.dataset_id, result.hypotheses)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Trait-genomics persistence failed: {exc}") from exc
    return {
        "dataset_id": dataset.dataset_id,
        "source_snapshot_ids": dataset.source_snapshot_ids,
        "diagnostics": diagnostics,
        "result": result,
    }


@router.post(
    "/live/archive/zenodo-draft",
    dependencies=[Depends(verify_owner_session)],
)
def live_archive_zenodo_draft(payload: LiveArchiveDraftRequest):
    dataset, diagnostics = _build_live_dataset(payload)
    if not dataset.records:
        raise HTTPException(status_code=422, detail="No valid live TIG evidence records were available")

    result = TraitGenomicsDiscoveryEngine().discover(dataset)
    if payload.require_hypotheses and not result.hypotheses:
        raise HTTPException(
            status_code=409,
            detail=(
                "Live evidence snapshot contains no cross-taxon three-domain TIG hypotheses. "
                "No Zenodo draft was created. Raw phylogenetic sequence presence is not "
                "promoted to genetic-association evidence."
            ),
        )

    if payload.persist:
        try:
            repository = TraitGenomicsRepository()
            repository.save_dataset(dataset)
            repository.save_hypotheses(dataset.dataset_id, result.hypotheses)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Trait-genomics persistence failed: {exc}") from exc

    root = os.getenv("CALYX_SCIENTIFIC_ARCHIVE_STAGING", "/var/data/scientific_archive_staging")
    try:
        release = ScientificArchiveReleaseService(staging_root=root).create_zenodo_draft(
            dataset,
            creators=payload.creators,
            title=payload.title,
            description=payload.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Scientific archive draft failed: {exc}") from exc

    return {
        "release": release,
        "diagnostics": diagnostics,
        "discovery_summary": {
            "evidence_count": result.evidence_count,
            "trait_count": result.trait_count,
            "interaction_count": result.interaction_count,
            "molecular_association_count": result.molecular_count,
            "hypothesis_count": len(result.hypotheses),
        },
    }


@router.post("/archive/build")
def build_archive(payload: ArchiveRequest):
    result = TraitGenomicsDiscoveryEngine().discover(payload.dataset)
    if payload.result is not None and payload.result.dataset_id != payload.dataset.dataset_id:
        raise HTTPException(status_code=422, detail="Archive result dataset_id does not match dataset")

    root = os.getenv("CALYX_SCIENTIFIC_ARCHIVE_STAGING", "/var/data/scientific_archive_staging")
    release_dir = ZenodoArchiveBridge().build_release(payload.dataset, result, root)
    return {
        "release_dir": str(release_dir),
        "files": sorted(p.name for p in Path(release_dir).iterdir()),
        "dataset_id": payload.dataset.dataset_id,
        "evidence_count": result.evidence_count,
        "hypothesis_count": len(result.hypotheses),
    }


@router.post("/archive/zenodo-draft")
def create_versioned_archive_draft(payload: VersionedArchiveDraftRequest):
    root = os.getenv("CALYX_SCIENTIFIC_ARCHIVE_STAGING", "/var/data/scientific_archive_staging")
    try:
        service = ScientificArchiveReleaseService(staging_root=root)
        return service.create_zenodo_draft(
            payload.dataset,
            creators=payload.creators,
            title=payload.title,
            description=payload.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Scientific archive draft failed: {exc}") from exc


@router.post(
    "/zenodo/drafts",
    dependencies=[Depends(verify_owner_session)],
)
def create_zenodo_draft(payload: ZenodoDraftRequest):
    """Low-level owner-only draft helper; scientific releases should use /archive/zenodo-draft."""
    try:
        return ZenodoArchiveBridge().create_draft(
            title=payload.title,
            description=payload.description,
            creators=payload.creators,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post(
    "/zenodo/drafts/{deposition_id}/publish",
    dependencies=[Depends(verify_owner_session)],
)
def publish_zenodo_draft(deposition_id: int):
    raise HTTPException(
        status_code=403,
        detail=(
            "Zenodo publication is disabled in Calyx. Review the draft in Zenodo and "
            "publish manually until the owner-approved release ledger is available."
        ),
    )

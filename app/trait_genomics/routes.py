from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key, verify_owner_session

from .discovery import TraitGenomicsDiscoveryEngine
from .models import DiscoveryDataset, DiscoveryResult
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


@router.post("/archive/build")
def build_archive(payload: ArchiveRequest):
    # The server derives the canonical result so a caller cannot combine evidence
    # from one dataset with hypotheses/counts from another.
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


@router.post("/zenodo/drafts")
def create_zenodo_draft(payload: ZenodoDraftRequest):
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
    # Public publication remains disabled until a durable scientific-release
    # approval record is implemented. Draft creation is intentionally separate.
    raise HTTPException(
        status_code=403,
        detail=(
            "Zenodo publication is disabled in Calyx. Review the draft in Zenodo and "
            "publish manually until the owner-approved release ledger is available."
        ),
    )

"""Owner-gated Mission Control endpoints for World Plants release intake."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.security import verify_owner_or_api_key
from runtime.world_plants_readiness_api import build_taxonomy_readiness_report
from runtime.world_plants_release_store import WorldPlantsReleaseStore


def _intake_root() -> Path:
    return Path(os.getenv("CALYX_TAXONOMY_INTAKE_DIR", "/tmp/calyx/taxonomy-releases"))


def _default_store() -> WorldPlantsReleaseStore:
    limit = int(os.getenv("CALYX_TAXONOMY_MAX_UPLOAD_BYTES", "75000000"))
    return WorldPlantsReleaseStore(_intake_root(), max_upload_bytes=limit)


def create_taxonomy_release_router(
    get_store: Callable[[], WorldPlantsReleaseStore] = _default_store,
    require_owner: Callable[..., Any] = verify_owner_or_api_key,
) -> APIRouter:
    router = APIRouter(tags=["taxonomy-releases"])
    releases = APIRouter(prefix="/api/mission-control/taxonomy/releases")

    @router.get("/api/mission-control/taxonomy/readiness")
    def taxonomy_readiness(
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        return build_taxonomy_readiness_report(intake_root=_intake_root())

    @releases.get("")
    def list_releases(
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        return {
            "releases": get_store().list_reports(),
            "automatic_promotion": False,
        }

    @releases.get("/{release_id}")
    def get_release(
        release_id: str,
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        report = get_store().get(release_id)
        if report is None:
            raise HTTPException(status_code=404, detail="taxonomy release not found")
        return report

    @router.get("/api/mission-control/occurrences/readiness")
    def occurrence_readiness(
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        from runtime.occurrence_staging import SUPPORTED_SOURCES

        return {
            "supported_sources": sorted(SUPPORTED_SOURCES),
            "staging_contract": "occurrence-staging-v1",
            "idempotency": "checksum-deduplicated per batch",
            "taxon_reconciliation": "canonical_lookup injection required for resolved state",
            "unresolved_taxa": "enter explicit review queue, not silently dropped",
            "production_mutation": False,
            "next_action": (
                "POST /api/mission-control/occurrences/stage with source and bounded records"
            ),
        }

    @releases.post("/inspect")
    async def inspect_release(
        file: UploadFile = File(...),  # noqa: B008
        version_label: str = Form(...),
        acquired_at: str = Form(...),
        notes: str | None = Form(default=None),
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        payload = await file.read()
        try:
            return get_store().inspect_and_store(
                payload,
                filename=file.filename or "world-orchids-release",
                version_label=version_label,
                acquired_at=acquired_at,
                notes=notes,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    router.include_router(releases)
    return router


router = create_taxonomy_release_router()

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

STAGING_MAX_BATCH_SIZE = 2_000


def _intake_root() -> Path:
    return Path(os.getenv("CALYX_TAXONOMY_INTAKE_DIR", "/tmp/calyx/taxonomy-releases"))


def _default_store() -> WorldPlantsReleaseStore:
    limit = int(os.getenv("CALYX_TAXONOMY_MAX_UPLOAD_BYTES", "75000000"))
    return WorldPlantsReleaseStore(_intake_root(), max_upload_bytes=limit)


def _default_staging_store() -> Any:
    from runtime.world_plants_staging import PostgresWorldPlantsStagingStore

    return PostgresWorldPlantsStagingStore()


def create_taxonomy_release_router(
    get_store: Callable[[], WorldPlantsReleaseStore] = _default_store,
    require_owner: Callable[..., Any] = verify_owner_or_api_key,
    get_staging_store: Callable[[], Any] = _default_staging_store,
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

    @releases.post("/{release_id}/stage")
    def stage_release(
        release_id: str,
        batch_size: int = Form(default=1000),
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        if not 1 <= batch_size <= STAGING_MAX_BATCH_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"batch_size must be between 1 and {STAGING_MAX_BATCH_SIZE}",
            )
        local_report = get_store().get(release_id)
        if local_report is None:
            raise HTTPException(status_code=404, detail="taxonomy release not found")
        try:
            from sqlalchemy.exc import SQLAlchemyError

            payload = get_store().source_bytes(release_id)
            snapshot = local_report.get("snapshot", {})
            staging = get_staging_store()
            durable_release_id, parsed = staging.register_release(
                payload,
                version_label=str(snapshot.get("version_label", "unknown")),
                filename=str(snapshot.get("filename", "world-orchids-release")),
                acquired_at=str(snapshot.get("acquired_at", "unknown")),
            )
            if durable_release_id != release_id:
                raise RuntimeError(
                    "durable release checksum does not match inspected release"
                )
            receipt = staging.stage_next_batch(release_id, batch_size=batch_size)
            return {
                "receipt": receipt.as_dict(),
                "inspection": parsed.summary(),
                "checkpoint": staging.checkpoint(release_id),
                "change_report": staging.change_report(release_id),
                "activation": "blocked_pending_owner_approval",
                "automatic_promotion": False,
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except SQLAlchemyError as exc:
            raise HTTPException(
                status_code=503,
                detail="durable taxonomy staging is unavailable until migration 107 is activated",
            ) from exc

    @releases.get("/{release_id}/staging")
    def staging_status(
        release_id: str,
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        try:
            from sqlalchemy.exc import SQLAlchemyError

            staging = get_staging_store()
            return {
                "release_id": release_id,
                "checkpoint": staging.checkpoint(release_id),
                "counts": staging.counts(release_id),
                "change_report": staging.change_report(release_id),
                "activation": "blocked_pending_owner_approval",
                "automatic_promotion": False,
            }
        except (KeyError, SQLAlchemyError) as exc:
            raise HTTPException(
                status_code=404, detail="durable taxonomy staging state not found"
            ) from exc

    router.include_router(releases)
    return router


router = create_taxonomy_release_router()

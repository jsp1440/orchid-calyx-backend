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


def _default_durable_store() -> Any:
    from runtime.world_plants_durable_intake import PostgresWorldPlantsIntakeStore

    return PostgresWorldPlantsIntakeStore()


def _default_migration_preflight() -> dict[str, Any]:
    from sqlalchemy.exc import SQLAlchemyError

    from runtime.world_plants_migration_preflight import inspect_world_plants_migration

    try:
        return inspect_world_plants_migration()
    except SQLAlchemyError as exc:
        raise RuntimeError(
            "taxonomy migration preflight database check failed"
        ) from exc


def _try_durable_store(factory: Callable[[], Any]) -> Any | None:
    """Return durable intake when available; fail open only to legacy local intake."""
    try:
        return factory()
    except (ModuleNotFoundError, ValueError, RuntimeError):
        return None
    except Exception as exc:
        try:
            from sqlalchemy.exc import SQLAlchemyError
        except ModuleNotFoundError:
            return None
        if isinstance(exc, SQLAlchemyError):
            return None
        raise


def create_taxonomy_release_router(
    get_store: Callable[[], WorldPlantsReleaseStore] = _default_store,
    require_owner: Callable[..., Any] = verify_owner_or_api_key,
    get_durable_store: Callable[[], Any] = _default_durable_store,
    get_migration_preflight: Callable[
        [], dict[str, Any]
    ] = _default_migration_preflight,
) -> APIRouter:
    router = APIRouter(tags=["taxonomy-releases"])
    releases = APIRouter(prefix="/api/mission-control/taxonomy/releases")

    @router.get("/api/mission-control/taxonomy/readiness")
    def taxonomy_readiness(
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        migration: dict[str, Any] | None = None
        try:
            migration = get_migration_preflight()
        except (ModuleNotFoundError, RuntimeError):
            migration = None

        durable = _try_durable_store(get_durable_store)
        durable_reports = durable.list_reports() if durable is not None else []
        latest_release = durable_reports[0] if durable_reports else None
        schema_verified = (
            bool(migration.get("schema_complete")) if migration is not None else None
        )
        return build_taxonomy_readiness_report(
            intake_root=_intake_root(),
            staging_schema_verified_override=schema_verified,
            durable_intake_available_override=(
                schema_verified if schema_verified is not None else None
            ),
            latest_release_override=latest_release,
        )

    @router.get("/api/mission-control/taxonomy/migration-preflight")
    def taxonomy_migration_preflight(
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        try:
            return get_migration_preflight()
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503,
                detail=(
                    "taxonomy migration preflight is unavailable; verify the PostgreSQL "
                    "connection before any production migration decision"
                ),
            ) from exc

    @releases.get("")
    def list_releases(
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        durable = _try_durable_store(get_durable_store)
        reports = durable.list_reports() if durable is not None else get_store().list_reports()
        return {
            "releases": reports,
            "durable_storage": "postgresql" if durable is not None else "local_compatibility",
            "automatic_promotion": False,
        }

    @releases.get("/{release_id}")
    def get_release(
        release_id: str,
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        durable = _try_durable_store(get_durable_store)
        report = durable.get_with_inspection(release_id) if durable is not None else None
        if report is None:
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
        filename = file.filename or "world-orchids-release"
        try:
            durable = _try_durable_store(get_durable_store)
            if durable is not None:
                return durable.inspect_and_store(
                    payload,
                    filename=filename,
                    version_label=version_label,
                    acquired_at=acquired_at,
                    notes=notes,
                )
            return get_store().inspect_and_store(
                payload,
                filename=filename,
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
        durable = _try_durable_store(get_durable_store)
        if durable is None:
            raise HTTPException(
                status_code=503,
                detail="durable taxonomy staging is unavailable until migration 107 is verified",
            )
        try:
            report = durable.get(release_id)
            if report is None:
                local_report = get_store().get(release_id)
                if local_report is None:
                    raise KeyError(f"taxonomy release not found: {release_id}")
                snapshot = local_report.get("snapshot", {})
                durable_release_id, _ = durable.staging.register_release(
                    get_store().source_bytes(release_id),
                    version_label=str(snapshot.get("version_label", "unknown")),
                    filename=str(snapshot.get("filename", "world-orchids-release")),
                    acquired_at=str(snapshot.get("acquired_at", "unknown")),
                )
                if durable_release_id != release_id:
                    raise RuntimeError(
                        "durable release checksum does not match inspected release"
                    )
            receipt = durable.stage_next_batch(release_id, batch_size=batch_size)
            return {
                "receipt": receipt.as_dict(),
                "checkpoint": durable.checkpoint(release_id),
                "counts": durable.counts(release_id),
                "change_report": durable.change_report(release_id),
                "activation": "blocked_pending_owner_approval",
                "automatic_promotion": False,
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @releases.get("/{release_id}/staging")
    def staging_status(
        release_id: str,
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        durable = _try_durable_store(get_durable_store)
        if durable is None:
            raise HTTPException(
                status_code=503,
                detail="durable taxonomy staging is unavailable until migration 107 is verified",
            )
        try:
            return {
                "release_id": release_id,
                "checkpoint": durable.checkpoint(release_id),
                "counts": durable.counts(release_id),
                "change_report": durable.change_report(release_id),
                "activation": "blocked_pending_owner_approval",
                "automatic_promotion": False,
            }
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="durable taxonomy staging state not found"
            ) from exc

    router.include_router(releases)
    return router


router = create_taxonomy_release_router()

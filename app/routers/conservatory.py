"""Owner-gated personal collection API for My Conservatory."""

from __future__ import annotations

import os
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.conservatory_readiness import (
    build_conservatory_readiness,
    create_restart_probe,
    verify_restart_probe,
)
from runtime.conservatory_store import ConservatoryStore


class PlantCreate(BaseModel):
    display_name: str = Field(min_length=2, max_length=300)
    accepted_scientific_name: str | None = Field(default=None, max_length=300)
    location: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=5000)


class LabelRequest(BaseModel):
    plant_ids: list[str] | None = None


class RestartProbeVerification(BaseModel):
    token: str = Field(min_length=10, max_length=100)


def _conservatory_root() -> Path:
    return Path(os.getenv("CALYX_CONSERVATORY_DIR", "/tmp/calyx/conservatory"))


def _default_store() -> ConservatoryStore:
    return ConservatoryStore(_conservatory_root())


def _qr_svg(payload: str) -> bytes:
    image = qrcode.make(payload, image_factory=qrcode.image.svg.SvgPathImage, border=2)
    buffer = BytesIO()
    image.save(buffer)
    return buffer.getvalue()


def create_conservatory_router(
    get_store: Callable[[], ConservatoryStore] = _default_store,
    require_owner: Callable[..., Any] = verify_owner_or_api_key,
    get_root: Callable[[], Path] = _conservatory_root,
) -> APIRouter:
    router = APIRouter(prefix="/api/conservatory", tags=["conservatory"])

    @router.get("/readiness")
    def readiness(_: Any = Depends(require_owner)) -> dict[str, Any]:  # noqa: B008
        return build_conservatory_readiness(get_root())

    @router.post("/readiness/restart-probe")
    def start_restart_probe(
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        return create_restart_probe(get_root())

    @router.post("/readiness/restart-probe/verify")
    def certify_restart_probe(
        payload: RestartProbeVerification,
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        try:
            return verify_restart_probe(get_root(), payload.token)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/plants")
    def list_plants(_: Any = Depends(require_owner)) -> dict[str, Any]:  # noqa: B008
        plants = get_store().list()
        return {"plants": plants, "count": len(plants)}

    @router.get("/plants/{plant_id}")
    def get_plant(
        plant_id: str,
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        plant = get_store().get(plant_id)
        if plant is None:
            raise HTTPException(status_code=404, detail="plant not found")
        return plant

    @router.get("/plants/{plant_id}/qr.svg")
    def get_plant_qr(
        plant_id: str,
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> Response:
        plant = get_store().get(plant_id)
        if plant is None:
            raise HTTPException(status_code=404, detail="plant not found")
        return Response(
            content=_qr_svg(plant["qr_identifier"]),
            media_type="image/svg+xml",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    @router.post("/plants", status_code=201)
    def create_plant(
        payload: PlantCreate,
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        try:
            return get_store().create(**payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/labels/manifest")
    def create_label_manifest(
        payload: LabelRequest,
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        return get_store().label_manifest(payload.plant_ids)

    return router


router = create_conservatory_router()

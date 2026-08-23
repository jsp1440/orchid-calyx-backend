"""Owner-gated personal collection API for My Conservatory."""

from __future__ import annotations

import os
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.conservatory_environment import (
    ConservatoryEnvironmentStore,
    EnvironmentError_,
)
from runtime.conservatory_locations import ConservatoryLocationStore, LocationError
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


class LocationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    kind: str = Field(min_length=2, max_length=40)
    #: The grower's own words. Recorded as an assessment, never as a
    #: measurement — the store stamps its origin so a later reader cannot
    #: mistake it for sensor data.
    described_conditions: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=5000)


class LocationRename(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    note: str | None = Field(default=None, max_length=2000)


class LocationRetire(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class PlacementCreate(BaseModel):
    location_id: str | None = Field(default=None, max_length=100)
    #: "move" means the plant physically went somewhere. "correction" means
    #: the record was wrong and the plant never moved. Collapsing them would
    #: invent husbandry history.
    reason: str = Field(default="move", max_length=40)
    note: str | None = Field(default=None, max_length=2000)


class EnvironmentReadingCreate(BaseModel):
    variable: str = Field(min_length=2, max_length=60)
    #: Absent means nobody has said. It is never coerced to zero.
    value: float | None = None
    #: measured | manual | inferred | unknown. Not interchangeable: only
    #: `measured` may name an instrument, and only `inferred` may cite a
    #: derivation. A recommendation is not an origin and has no place here.
    origin: str = Field(min_length=2, max_length=20)
    observed_at: str = Field(min_length=4, max_length=40)
    instrument: str | None = Field(default=None, max_length=200)
    derived_from: str | None = Field(default=None, max_length=500)
    window_end: str | None = Field(default=None, max_length=40)
    summary_kind: str | None = Field(default=None, max_length=20)
    note: str | None = Field(default=None, max_length=2000)


class LabelRequest(BaseModel):
    plant_ids: list[str] | None = None


class RestartProbeVerification(BaseModel):
    token: str = Field(min_length=10, max_length=100)


def _conservatory_root() -> Path:
    return Path(os.getenv("CALYX_CONSERVATORY_DIR", "/tmp/calyx/conservatory"))


def _default_store() -> ConservatoryStore:
    return ConservatoryStore(_conservatory_root())


def _default_location_store() -> ConservatoryLocationStore:
    return ConservatoryLocationStore(_conservatory_root())


def _default_environment_store() -> ConservatoryEnvironmentStore:
    return ConservatoryEnvironmentStore(_conservatory_root())


def _scan_base_url() -> str | None:
    """Where a scanned tag should land, or None if nobody has configured it.

    Deliberately not defaulted to a guessed host. A QR code is printed once and
    lives on the plant for years; encoding a hostname this service invented
    would produce tags that point somewhere wrong forever, and a wrong tag is
    worse than an unscannable one because it looks like it worked.
    """
    base = os.getenv("CONSERVATORY_SCAN_BASE_URL", "").strip().rstrip("/")
    return base or None


def _qr_target(qr_identifier: str) -> tuple[str, bool]:
    """What the QR image should encode, and whether a phone can follow it.

    With a base URL configured the tag carries a scan URL, which any phone
    camera resolves. Without one it carries the bare identity URN, which is
    honest but only resolvable by something that already knows what Calyx is.
    The boolean is returned rather than inferred by the caller so a label
    workflow can tell a grower their tags will not scan yet, instead of letting
    them print a hundred of them and find out in the greenhouse.
    """
    base = _scan_base_url()
    if base is None:
        return qr_identifier, False
    return f"{base}/conservatory/scan/{quote(qr_identifier, safe='')}", True


def _qr_svg(payload: str) -> bytes:
    image = qrcode.make(payload, image_factory=qrcode.image.svg.SvgPathImage, border=2)
    buffer = BytesIO()
    image.save(buffer)
    return buffer.getvalue()


def create_conservatory_router(
    get_store: Callable[[], ConservatoryStore] = _default_store,
    require_owner: Callable[..., Any] = verify_owner_or_api_key,
    get_root: Callable[[], Path] = _conservatory_root,
    get_locations: Callable[[], ConservatoryLocationStore] = _default_location_store,
    get_environment: Callable[[], ConservatoryEnvironmentStore] = _default_environment_store,
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
        target, scannable = _qr_target(plant["qr_identifier"])
        return Response(
            content=_qr_svg(target),
            media_type="image/svg+xml",
            headers={
                "Cache-Control": "private, max-age=3600",
                # Surfaced on the response so a label workflow can warn before
                # printing, rather than after the tags are on the plants.
                "X-Conservatory-Qr-Scannable": "true" if scannable else "false",
            },
        )

    @router.get("/resolve/{identifier:path}")
    def resolve_identifier(
        identifier: str,
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        """Turn a scanned tag back into the accession it names.

        Owner-scoped on purpose. A QR code on a plant is visible to anyone who
        walks past it, so an unauthenticated resolver would publish a private
        collection to any visitor with a phone. Scanning identifies the plant;
        it does not authorise reading about it.
        """
        plant = get_store().resolve(identifier)
        if plant is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "ACCESSION_NOT_RESOLVED",
                    "message": (
                        "No accession in this collection carries that identifier. "
                        "It was not matched approximately: a near miss would attach "
                        "one plant's history to another."
                    ),
                },
            )
        return plant

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
        manifest = get_store().label_manifest(payload.plant_ids)
        base = _scan_base_url()
        for label in manifest["labels"]:
            target, scannable = _qr_target(label["qr_identifier"])
            label["qr_target"] = target
            label["qr_scannable"] = scannable
        # Stated once for the batch: a grower about to print is the last person
        # who can cheaply fix unscannable tags.
        manifest["qr_scannable"] = base is not None
        manifest["qr_scan_base_url"] = base
        return manifest

    def _location_error(exc: LocationError) -> HTTPException:
        code = str(exc)
        # A name collision is a conflict with something that already exists;
        # everything else here is a malformed request. Returning one status for
        # both would make "you already have this bench" indistinguishable from
        # "that is not a kind of place".
        # A conflict is something already true of the world that the caller
        # must reconcile; 422 is a malformed request. A grower fixes them
        # differently, so they must not share a status.
        conflicts = {
            "LOCATION_NAME_ALREADY_USED",
            "LOCATION_ALREADY_RETIRED",
            "LOCATION_STILL_OCCUPIED",
            "LOCATION_RETIRED",
        }
        status = 409 if code in conflicts else 422
        if code == "LOCATION_NOT_FOUND":
            status = 404
        return HTTPException(status_code=status, detail={"code": code})

    @router.get("/locations")
    def list_locations(_: Any = Depends(require_owner)) -> dict[str, Any]:  # noqa: B008
        locations = get_locations().list_locations()
        return {"locations": locations, "count": len(locations)}

    @router.post("/locations", status_code=201)
    def create_location(
        payload: LocationCreate,
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        try:
            return get_locations().create_location(**payload.model_dump())
        except LocationError as exc:
            raise _location_error(exc) from exc

    @router.post("/locations/{location_id}/rename")
    def rename_location(
        location_id: str,
        payload: LocationRename,
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        """Rename a location. Emphatically not a plant move: the id is
        unchanged, every placement still points here, and no plant's history
        is touched."""
        try:
            return get_locations().rename_location(location_id, **payload.model_dump())
        except LocationError as exc:
            raise _location_error(exc) from exc

    @router.post("/locations/{location_id}/retire")
    def retire_location(
        location_id: str,
        payload: LocationRetire,
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        try:
            return get_locations().retire_location(location_id, **payload.model_dump())
        except LocationError as exc:
            raise _location_error(exc) from exc

    @router.get("/locations/{location_id}/history")
    def location_history(
        location_id: str,
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        locations = get_locations()
        if locations.get_location(location_id) is None:
            raise HTTPException(status_code=404, detail={"code": "LOCATION_NOT_FOUND"})
        return {
            "location_id": location_id,
            "history": locations.location_history(location_id),
        }

    def _known_location_or_404(location_id: str) -> None:
        if get_locations().get_location(location_id) is None:
            raise HTTPException(status_code=404, detail={"code": "LOCATION_NOT_FOUND"})

    @router.post("/locations/{location_id}/environment", status_code=201)
    def record_environment(
        location_id: str,
        payload: EnvironmentReadingCreate,
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        _known_location_or_404(location_id)
        try:
            return get_environment().record(location_id=location_id, **payload.model_dump())
        except EnvironmentError_ as exc:
            # Every one of these means the record would have misrepresented its
            # own origin, which is a malformed claim rather than a conflict.
            raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc

    @router.get("/locations/{location_id}/environment")
    def read_environment(
        location_id: str,
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        _known_location_or_404(location_id)
        environment = get_environment()
        context = environment.context_for(location_id)
        # Both shapes are returned: the per-variable summary a consumer reasons
        # over, and the raw readings behind it, so nothing has to trust the
        # summary without being able to check it.
        context["readings"] = environment.readings_for(location_id)
        return context

    @router.get("/locations/occupancy")
    def location_occupancy(_: Any = Depends(require_owner)) -> dict[str, Any]:  # noqa: B008
        return {"occupancy": get_locations().occupancy()}

    @router.get("/plants/{plant_id}/placement")
    def get_placement(
        plant_id: str,
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        if get_store().get(plant_id) is None:
            raise HTTPException(status_code=404, detail="plant not found")
        locations = get_locations()
        return {
            "plant_id": plant_id,
            # Derived from the log rather than stored beside it, so the two can
            # never disagree about where the plant is.
            "current": locations.current_placement(plant_id),
            "history": locations.placement_history(plant_id),
        }

    @router.post("/plants/{plant_id}/placement", status_code=201)
    def record_placement(
        plant_id: str,
        payload: PlacementCreate,
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        if get_store().get(plant_id) is None:
            raise HTTPException(status_code=404, detail="plant not found")
        try:
            return get_locations().record_placement(
                plant_id=plant_id, **payload.model_dump()
            )
        except LocationError as exc:
            raise _location_error(exc) from exc

    return router


router = create_conservatory_router()

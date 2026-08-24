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
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.conservatory_calyx_context import (
    build_cultivation_context,
    requirements_claim,
)
from runtime.conservatory_collection_review import build_collection_review
from runtime.conservatory_environment import (
    ConservatoryEnvironmentStore,
    EnvironmentError_,
)
from runtime.conservatory_events import ConservatoryEventStore, PlantEventError
from runtime.conservatory_locations import ConservatoryLocationStore, LocationError
from runtime.conservatory_photographs import (
    ConservatoryPhotographStore,
    PhotographError,
)
from runtime.conservatory_readiness import (
    build_conservatory_readiness,
    create_restart_probe,
    verify_restart_probe,
)
from runtime.conservatory_store import ConservatoryStore
from runtime.conservatory_suitability import assess_placement_suitability
from runtime.conservatory_taxon_placement import (
    MAX_TAXON_LENGTH,
    build_taxon_placement_search,
)
from runtime.conservatory_taxon_requirements import resolve_taxon_requirements
from runtime.conservatory_trait_supply import TraitSupply, supply_from_repository


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
    #: Which earlier placement this corrects. Only meaningful with
    #: reason="correction"; a correction naming nothing says the record was
    #: wrong without saying which record.
    corrects_id: str | None = Field(default=None, max_length=100)


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
    #: The reading this corrects. The original is kept and marked, never edited.
    supersedes_id: str | None = Field(default=None, max_length=100)


class PlantEventCreate(BaseModel):
    kind: str = Field(min_length=2, max_length=40)
    #: When it happened in the world. Never inferred from the request time.
    occurred_at: str = Field(min_length=4, max_length=40)
    recorder_kind: str = Field(default="grower", max_length=20)
    recorder_ref: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=5000)
    #: The event this corrects. Required when kind is "correction".
    supersedes_id: str | None = Field(default=None, max_length=100)
    detail: dict[str, Any] = Field(default_factory=dict)


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


def _default_event_store() -> ConservatoryEventStore:
    return ConservatoryEventStore(_conservatory_root())


def _default_photograph_store() -> ConservatoryPhotographStore:
    return ConservatoryPhotographStore(_conservatory_root())


def _candidate_repository() -> Any | None:
    """The candidate knowledge store, or None if this deployment has none.

    Imported inside the function because the candidate package builds its
    repository at import time and can fail there when no database is
    configured. A conservatory route must not stop serving a plant's dossier
    because a knowledge store it only consults is unreachable.
    """
    try:
        from app.candidate_knowledge.dependencies import get_candidate_components

        repository, _service = get_candidate_components()
        return repository
    except Exception:  # noqa: BLE001 - unavailable is unavailable
        return None


def _default_trait_evidence(taxon: str | None) -> TraitSupply:
    """Read trait evidence for a taxon from the candidate store.

    This is a read against evidence the Continuum already holds. It publishes
    nothing, promotes nothing, and does not screen by review state: the
    candidate store holds unreviewed extractions by design, and the resolver
    downstream is built to label each one with the strength it actually has.
    Filtering here would hide that labelling from the layer that carries it.

    When the store cannot be reached the result says so rather than coming back
    empty, so that "the literature is silent about this taxon" and "we could
    not look" stay distinguishable all the way to the grower.
    """
    return supply_from_repository(taxon, _candidate_repository())


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
    get_environment: Callable[
        [], ConservatoryEnvironmentStore
    ] = _default_environment_store,
    get_events: Callable[[], ConservatoryEventStore] = _default_event_store,
    get_photographs: Callable[
        [], ConservatoryPhotographStore
    ] = _default_photograph_store,
    get_trait_evidence: Callable[[str | None], TraitSupply] = _default_trait_evidence,
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
            "LOCATION_NOT_RETIRED",
            # Already true of the log: somebody else's correction stands, and
            # the caller has to read it before writing another.
            "PLACEMENT_ALREADY_CORRECTED",
        }
        status = 409 if code in conflicts else 422
        if code in {"LOCATION_NOT_FOUND", "CORRECTION_TARGET_NOT_FOUND"}:
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

    @router.post("/locations/{location_id}/unretire")
    def unretire_location(
        location_id: str,
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        """Bring a retired location back into use, keeping its identity."""
        try:
            return get_locations().unretire_location(location_id)
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
            return get_environment().record(
                location_id=location_id, **payload.model_dump()
            )
        except EnvironmentError_ as exc:
            code = str(exc)
            # Superseding an already-corrected reading is a conflict with the
            # store's current state; the rest are malformed claims.
            status = 409 if code == "READING_ALREADY_SUPERSEDED" else 422
            raise HTTPException(status_code=status, detail={"code": code}) from exc

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

    @router.post("/plants/{plant_id}/events", status_code=201)
    def record_plant_event(
        plant_id: str,
        payload: PlantEventCreate,
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        if get_store().get(plant_id) is None:
            raise HTTPException(status_code=404, detail="plant not found")
        try:
            return get_events().record(plant_id=plant_id, **payload.model_dump())
        except PlantEventError as exc:
            code = str(exc)
            # Superseding an already-corrected event is a conflict with the
            # ledger's current state; everything else is a malformed claim.
            status = 409 if code == "EVENT_ALREADY_SUPERSEDED" else 422
            raise HTTPException(status_code=status, detail={"code": code}) from exc

    @router.get("/plants/{plant_id}/events")
    def read_plant_events(
        plant_id: str,
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        if get_store().get(plant_id) is None:
            raise HTTPException(status_code=404, detail="plant not found")
        # The timeline states its own provenance and that it is not scientific
        # evidence, so a consumer cannot pick these up as findings by accident.
        return get_events().timeline(plant_id)

    @router.get("/plants/{plant_id}/cultivation-context")
    def cultivation_context(
        plant_id: str,
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        """Everything known about one plant, each claim labelled by class.

        This answers nothing. It exists so that whatever reasons over a plant
        is handed what is known without being handed a false impression of how
        well any of it is known. No recommendation, no scoring, no conclusion
        crosses this boundary.
        """
        plant = get_store().get(plant_id)
        if plant is None:
            raise HTTPException(status_code=404, detail="plant not found")
        locations = get_locations()
        current = locations.current_placement(plant_id)
        location = (
            locations.get_location(current["location_id"])
            if current and current.get("location_id")
            else None
        )
        environment = (
            get_environment().context_for(location["id"])
            if location is not None
            else None
        )
        trait_supply = get_trait_evidence(plant.get("accepted_scientific_name"))
        return build_cultivation_context(
            plant=plant,
            placement_current=current,
            placement_history=locations.placement_history(plant_id),
            location=location,
            environment=environment,
            events=get_events().timeline(plant_id),
            trait_candidates=trait_supply.candidates,
            trait_source_unavailable=trait_supply.unavailable_reason,
        )

    def _assessment_for(plant: dict[str, Any]) -> dict[str, Any]:
        """One plant's assessment, built the same way for both callers.

        Shared deliberately: two comparison paths disagree eventually, and the
        one a grower reads on the dossier must be the one the collection view
        summarises.
        """
        locations = get_locations()
        current = locations.current_placement(plant["id"])
        location = (
            locations.get_location(current["location_id"])
            if current and current.get("location_id")
            else None
        )
        environment = (
            get_environment().context_for(location["id"])
            if location is not None
            else None
        )
        trait_supply = get_trait_evidence(plant.get("accepted_scientific_name"))
        context = build_cultivation_context(
            plant=plant,
            placement_current=current,
            placement_history=locations.placement_history(plant["id"]),
            location=location,
            environment=environment,
            events=get_events().timeline(plant["id"]),
            trait_candidates=trait_supply.candidates,
            trait_source_unavailable=trait_supply.unavailable_reason,
        )
        return assess_placement_suitability(context)

    @router.get("/locations/suitability")
    def taxon_placement_search(
        taxon: str = Query(default="", max_length=MAX_TAXON_LENGTH),
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        """Where in this collection a candidate taxon's requirements are met.

        The buying question, answered from what the benches actually measure.
        Not advice about the purchase: whether a bench has room, and whether
        the grower can hold it there through a season, are not in this data.

        Owner-gated with the rest of the router. The response names every
        location in the collection, which is private whether or not a plant is
        standing in it.
        """
        supply = get_trait_evidence(taxon or None)
        requirements = requirements_claim(
            resolve_taxon_requirements(
                taxon or None,
                supply.candidates,
                source_unavailable=supply.unavailable_reason,
            )
        )
        environment = get_environment()
        return build_taxon_placement_search(
            taxon=taxon,
            requirements_claim=requirements,
            locations=get_locations().list_locations(),
            environment_for=environment.context_for,
        )

    def _photograph_error(exc: PhotographError) -> HTTPException:
        code = str(exc)
        # A missing imaging library is not the caller's fault and not a
        # permanent refusal: it is the service unable to guarantee the one
        # property that makes storing a photograph safe.
        if code == "IMAGE_PROCESSING_UNAVAILABLE":
            return HTTPException(status_code=503, detail={"code": code})
        if code == "PHOTOGRAPH_TOO_LARGE":
            return HTTPException(status_code=413, detail={"code": code})
        if code == "CONTENT_TYPE_NOT_ACCEPTED":
            return HTTPException(status_code=415, detail={"code": code})
        return HTTPException(status_code=422, detail={"code": code})

    @router.post("/plants/{plant_id}/photographs", status_code=201)
    async def add_photograph(
        plant_id: str,
        file: UploadFile = File(...),  # noqa: B008
        caption: str | None = Form(default=None),
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        """Store one photograph of a plant, with its EXIF removed.

        A phone photograph of an orchid on a windowsill routinely carries the
        grower's home coordinates. Stripping them is not optional here: if it
        cannot be done the upload is refused, because a photograph that reached
        disk unstripped cannot be un-written.
        """
        if get_store().get(plant_id) is None:
            raise HTTPException(status_code=404, detail="plant not found")
        content = await file.read()
        try:
            return get_photographs().store(
                plant_id=plant_id,
                content=content,
                content_type=(file.content_type or "").split(";")[0].strip(),
                caption=caption,
            )
        except PhotographError as exc:
            raise _photograph_error(exc) from exc

    @router.get("/plants/{plant_id}/photographs")
    def list_photographs(
        plant_id: str,
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        """This plant's photographs, oldest capture first."""
        if get_store().get(plant_id) is None:
            raise HTTPException(status_code=404, detail="plant not found")
        rows = get_photographs().for_plant(plant_id)
        return {
            "plant_id": plant_id,
            "photographs": rows,
            "count": len(rows),
            # Said about itself. A picture shows what somebody pointed a camera
            # at, which is not a determination, a measurement or a voucher.
            "is_scientific_evidence": False,
        }

    @router.get("/photographs/{photograph_id}")
    def get_photograph(
        photograph_id: str,
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> Response:
        """The image itself. Owner-gated: this is a private collection."""
        store = get_photographs()
        record = store.get(photograph_id)
        if record is None:
            raise HTTPException(status_code=404, detail="photograph not found")
        content = store.bytes_for(photograph_id)
        if content is None:
            # The index knows about a file that is not on disk. Reporting that
            # as "no such photograph" would hide a storage fault behind an
            # answer that looks routine.
            raise HTTPException(
                status_code=410, detail={"code": "PHOTOGRAPH_FILE_MISSING"}
            )
        return Response(content=content, media_type=record["content_type"])

    @router.get("/collection/review")
    def collection_review(_: Any = Depends(require_owner)) -> dict[str, Any]:  # noqa: B008
        """Every plant grouped by what its assessment established.

        Owner-gated like the rest of this router. A collection listing is the
        most sensitive shape here — it is the whole holding in one response —
        and it must never be reachable from the public scan route.
        """
        plants = get_store().list()
        return build_collection_review(
            [(plant, _assessment_for(plant)) for plant in plants]
        )

    @router.get("/plants/{plant_id}/placement-assessment")
    def placement_assessment(
        plant_id: str,
        _: Any = Depends(require_owner),  # noqa: B008
    ) -> dict[str, Any]:
        """Compare this plant's recorded conditions against evidence-backed
        bounds for its taxon.

        Not advice about whether to move it: that depends on what else is on
        the bench, what the grower can do, and the season, none of which are
        in this data.
        """
        plant = get_store().get(plant_id)
        if plant is None:
            raise HTTPException(status_code=404, detail="plant not found")
        return _assessment_for(plant)

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

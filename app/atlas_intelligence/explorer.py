"""Atlas explorer API: viewport occurrences, taxon search, layer catalog, capabilities.

Mounted under the existing ``/atlas`` prefix next to the planetary-intelligence
registry routes. Every route is read-only and public-safe; none authorises
publication, production mutation, or provider calls.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from .occurrences import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    BBox,
    OccurrenceQuery,
    OccurrenceQueryResponse,
    OccurrenceService,
    OccurrenceSummaryResponse,
    TaxonSearchResponse,
    repository_from_environment,
)

CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "contracts"
LAYER_CATALOG_FILE = "atlas_layer_catalog_v1.json"
CAPABILITIES_FILE = "atlas_module_capabilities_v1.json"

router = APIRouter(prefix="/atlas", tags=["atlas-explorer"])


@lru_cache(maxsize=4)
def load_contract(filename: str) -> dict[str, Any]:
    with (CONTRACTS_DIR / filename).open(encoding="utf-8") as handle:
        return json.load(handle)


_service: OccurrenceService | None = None


def get_occurrence_service() -> OccurrenceService:
    """One service per process so the bounded TTL cache is shared across requests."""
    global _service
    if _service is None:
        _service = OccurrenceService(repository_from_environment())
    return _service


def reset_occurrence_service(service: OccurrenceService | None = None) -> None:
    """Test/ops hook: replace or clear the process-wide service."""
    global _service
    _service = service


Service = Annotated[OccurrenceService, Depends(get_occurrence_service)]


def _parse_months(raw: str | None) -> tuple[int, ...]:
    if not raw:
        return ()
    try:
        return tuple(sorted({int(part) for part in raw.split(",") if part.strip()}))
    except ValueError as exc:
        raise ValueError("months must be comma-separated integers") from exc


def _build_query(
    *,
    bbox: str | None,
    zoom: float,
    taxon_id: str | None,
    genus: str | None,
    scientific_name: str | None,
    year_from: int | None,
    year_to: int | None,
    months: str | None,
    basis_of_record: str | None,
    limit: int,
    cursor: str | None,
    mode: Literal["auto", "points", "clusters"],
) -> OccurrenceQuery:
    try:
        return OccurrenceQuery(
            bbox=BBox.parse(bbox) if bbox else BBox.world(),
            zoom=zoom,
            taxon_id=taxon_id or None,
            genus=genus or None,
            scientific_name=" ".join(scientific_name.split())
            if scientific_name
            else None,
            year_from=year_from,
            year_to=year_to,
            months=_parse_months(months),
            basis_of_record=basis_of_record or None,
            limit=limit,
            cursor=cursor or None,
            mode=mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _unavailable(exc: Exception) -> HTTPException:
    # Driver or connection failure: say unavailable, never fabricate or leak internals.
    return HTTPException(
        status_code=503, detail="Atlas occurrence store is unavailable."
    )


@router.get("/occurrences/query", response_model=OccurrenceQueryResponse)
def query_occurrences(
    service: Service,
    bbox: str | None = Query(
        default=None,
        description="west,south,east,north in WGS84; west>east crosses the antimeridian",
    ),
    zoom: float = Query(default=2.0, ge=0, le=24),
    taxon_id: str | None = Query(default=None, max_length=128),
    genus: str | None = Query(default=None, max_length=64),
    scientific_name: str | None = Query(default=None, max_length=200),
    year_from: int | None = Query(default=None, ge=1600, le=2100),
    year_to: int | None = Query(default=None, ge=1600, le=2100),
    months: str | None = Query(default=None, max_length=40),
    basis_of_record: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: str | None = Query(default=None, max_length=400),
    mode: Literal["auto", "points", "clusters"] = Query(default="auto"),
) -> OccurrenceQueryResponse:
    query = _build_query(
        bbox=bbox,
        zoom=zoom,
        taxon_id=taxon_id,
        genus=genus,
        scientific_name=scientific_name,
        year_from=year_from,
        year_to=year_to,
        months=months,
        basis_of_record=basis_of_record,
        limit=limit,
        cursor=cursor,
        mode=mode,
    )
    try:
        return service.query(query)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException as exc:
        raise _unavailable(exc) from exc
    except Exception as exc:
        raise _unavailable(exc) from exc


@router.get("/occurrences/summary", response_model=OccurrenceSummaryResponse)
def summarise_occurrences(
    service: Service,
    bbox: str | None = Query(default=None),
    taxon_id: str | None = Query(default=None, max_length=128),
    genus: str | None = Query(default=None, max_length=64),
    scientific_name: str | None = Query(default=None, max_length=200),
    year_from: int | None = Query(default=None, ge=1600, le=2100),
    year_to: int | None = Query(default=None, ge=1600, le=2100),
    months: str | None = Query(default=None, max_length=40),
) -> OccurrenceSummaryResponse:
    query = _build_query(
        bbox=bbox,
        zoom=0,
        taxon_id=taxon_id,
        genus=genus,
        scientific_name=scientific_name,
        year_from=year_from,
        year_to=year_to,
        months=months,
        basis_of_record=None,
        limit=DEFAULT_LIMIT,
        cursor=None,
        mode="auto",
    )
    try:
        return service.summary(query)
    except HTTPException as exc:
        raise _unavailable(exc) from exc
    except Exception as exc:
        raise _unavailable(exc) from exc


@router.get("/taxa/search", response_model=TaxonSearchResponse)
def search_taxa(
    service: Service,
    q: str = Query(min_length=2, max_length=120),
    limit: int = Query(default=10, ge=1, le=25),
) -> TaxonSearchResponse:
    try:
        return service.search_taxa(q, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException as exc:
        raise _unavailable(exc) from exc
    except Exception as exc:
        raise _unavailable(exc) from exc


@router.get("/catalog/layers")
def layer_catalog(
    status: str | None = Query(default=None, max_length=32),
) -> dict[str, Any]:
    catalog = load_contract(LAYER_CATALOG_FILE)
    layers = [
        layer
        for layer in catalog["layers"]
        if status is None or layer["status"] == status
    ]
    return {**catalog, "layers": layers}


def _probe(capability: dict[str, Any], service_state: str) -> dict[str, Any]:
    """Live availability where this process can actually know it; otherwise say so."""
    capability_id = capability["capability_id"]
    if capability_id.startswith("atlas.occurrences."):
        return {"state": service_state, "probed": True}
    if capability_id in {"taxon.resolve", "taxon.dossier"}:
        configured = bool(os.getenv("DATABASE_URL", "").strip())
        return {
            "state": "configured" if configured else "database_not_configured",
            "probed": True,
            "note": "Configuration check only; per-request failures are reported by the module itself.",
        }
    return {"state": "not_probed", "probed": False}


@router.get("/capabilities")
def module_capabilities(
    service: Service, module_id: str | None = Query(default=None, max_length=64)
) -> dict[str, Any]:
    contract = load_contract(CAPABILITIES_FILE)
    try:
        service_state = service.repository.describe().state
    except Exception:  # noqa: BLE001
        service_state = "unavailable"
    capabilities = [
        {**capability, "availability": _probe(capability, service_state)}
        for capability in contract["capabilities"]
        if module_id is None or capability["module_id"] == module_id
    ]
    if module_id is not None and not capabilities:
        raise HTTPException(
            status_code=404, detail=f"unknown Atlas module: {module_id}"
        )
    return {
        "schema": contract["schema"],
        "api_version": contract["api_version"],
        "generated_at": datetime.now(UTC).isoformat(),
        "identifier_systems": contract["identifier_systems"],
        "capabilities": capabilities,
        "workflows": contract["workflows"],
        "statement": "Declared status is a contract, not a health check. 'not_probed' means this process cannot verify the module.",
    }

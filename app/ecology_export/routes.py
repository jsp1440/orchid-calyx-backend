from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.security import verify_owner_or_api_key

from .models import (
    EcologyExportFormat,
    EcologyExportResponse,
    EcologyRecord,
    HabitatType,
)

router = APIRouter(
    prefix="/api/ecology",
    tags=["ecology-export"],
    dependencies=[Depends(verify_owner_or_api_key)],
)

_SAMPLE_RECORDS: list[EcologyRecord] = [
    EcologyRecord(
        taxon_name="Cattleya labiata",
        common_name="Ruby Orchid",
        habitat_type=HabitatType.EPIPHYTIC,
        region_verbatim="Northeast Brazil",
        elevation_m=700.0,
        notes="Found on Atlantic Forest remnants",
        source_reference="Lindley 1821",
        exported_at=datetime.now(tz=timezone.utc),
    ),
    EcologyRecord(
        taxon_name="Dactylorhiza fuchsii",
        common_name="Common Spotted Orchid",
        habitat_type=HabitatType.TERRESTRIAL,
        region_verbatim="Western Europe",
        elevation_m=200.0,
        notes="Calcareous grasslands and woodland margins",
        source_reference="Druce 1915",
        exported_at=datetime.now(tz=timezone.utc),
    ),
    EcologyRecord(
        taxon_name="Paphiopedilum callosum",
        common_name=None,
        habitat_type=HabitatType.LITHOPHYTIC,
        region_verbatim="Thailand, Indochina",
        elevation_m=500.0,
        notes="Limestone outcrops in humid forest",
        source_reference="Stein 1892",
        exported_at=datetime.now(tz=timezone.utc),
    ),
]


@router.get("/export", response_model=EcologyExportResponse)
def export_ecology_records(
    format: Annotated[EcologyExportFormat, Query()] = EcologyExportFormat.JSON,
    habitat_type: Annotated[HabitatType | None, Query()] = None,
    region_filter: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EcologyExportResponse:
    records = list(_SAMPLE_RECORDS)

    if habitat_type is not None:
        records = [r for r in records if r.habitat_type == habitat_type]

    if region_filter is not None:
        lower_filter = region_filter.lower()
        records = [
            r
            for r in records
            if r.region_verbatim is not None
            and lower_filter in r.region_verbatim.lower()
        ]

    total = len(records)
    page = records[offset : offset + limit]

    return EcologyExportResponse(
        format=format,
        records=page,
        total=total,
        offset=offset,
        limit=limit,
        exported_at=datetime.now(tz=timezone.utc),
    )


@router.get("/export/species/{taxon_name}", response_model=EcologyRecord)
def export_single_species(taxon_name: str) -> EcologyRecord:
    for record in _SAMPLE_RECORDS:
        if record.taxon_name.lower() == taxon_name.lower():
            return record
    raise HTTPException(status_code=404, detail="Taxon not found")

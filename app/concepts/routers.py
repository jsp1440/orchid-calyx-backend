from typing import Any

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from app.routers.health import add_mission_control_cors_headers
from app.security import verify_owner_or_api_key

from .dependencies import get_concept_service
from .services import ConceptRegistryService

router = APIRouter(
    prefix="/api/concepts",
    tags=["core-concept-registry"],
    dependencies=[
        Depends(verify_owner_or_api_key),
        Depends(add_mission_control_cors_headers),
    ],
)


@router.get("/{id_or_uri:path}")
def get_concept(
    id_or_uri: str,
    service: ConceptRegistryService = Depends(get_concept_service),
) -> dict[str, Any]:
    try:
        return service.get_concept(id_or_uri)
    except LookupError as exc:
        raise HTTPException(404, detail={"code": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(422, detail={"code": str(exc)}) from exc
    except RuntimeError as exc:
        raise HTTPException(
            503,
            detail={"code": "CONCEPT_DATABASE_UNAVAILABLE"},
        ) from exc
    except psycopg.Error as exc:
        raise HTTPException(
            503,
            detail={"code": "CONCEPT_DATABASE_UNAVAILABLE"},
        ) from exc

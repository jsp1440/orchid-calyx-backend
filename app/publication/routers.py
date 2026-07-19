from typing import Any, Callable

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from app.routers.health import add_mission_control_cors_headers
from app.security import verify_owner_or_api_key

from .dependencies import get_publication_service
from .schemas import PublicationRequest, RollbackRequest
from .services import PublicationService

router = APIRouter(
    prefix="/api/publication",
    tags=["controlled-publication-gate"],
    dependencies=[Depends(verify_owner_or_api_key), Depends(add_mission_control_cors_headers)],
)


def _invoke(operation: Callable[[], Any]) -> Any:
    try:
        return operation()
    except LookupError as exc:
        raise HTTPException(404, detail={"code": str(exc)}) from exc
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(409, detail={"code": "PUBLICATION_CONFLICT"}) from exc
    except RuntimeError as exc:
        raise HTTPException(503, detail={"code": "PUBLICATION_DATABASE_UNAVAILABLE"}) from exc
    except ValueError as exc:
        code = str(exc)
        status = 409 if "CONFLICT" in code or "IN_PROGRESS" in code else 422
        raise HTTPException(status, detail={"code": code}) from exc


@router.post("/dry-run", status_code=201)
def dry_run(payload: PublicationRequest, service: PublicationService = Depends(get_publication_service)) -> dict[str, Any]:
    return _invoke(lambda: service.dry_run(payload.model_dump(mode="json")))


@router.post("/publish", status_code=201)
def publish(payload: PublicationRequest, service: PublicationService = Depends(get_publication_service)) -> dict[str, Any]:
    return _invoke(lambda: service.publish(payload.model_dump(mode="json")))


@router.post("/runs/{run_id}/rollback")
def rollback(run_id: int, payload: RollbackRequest, service: PublicationService = Depends(get_publication_service)) -> dict[str, Any]:
    return _invoke(lambda: service.rollback(run_id, payload.model_dump(mode="json")))

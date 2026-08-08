"""Protected immutable Research Station dataset-row routes for CALYX-631."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.research_dataset_rows import ResearchDatasetRowStore

router = APIRouter(
    prefix="/brain/mission-control/research",
    tags=["mission-control-research-dataset-rows"],
)
_store_instance = ResearchDatasetRowStore()
OwnerIdentity = Annotated[dict[str, object], Depends(verify_owner_or_api_key)]


def _store() -> ResearchDatasetRowStore:
    return _store_instance


def _owner(identity: dict[str, object]) -> str:
    actor = str(identity.get("actor") or "").strip()
    if not actor:
        raise HTTPException(status_code=403, detail="Research Station owner scope unavailable")
    return actor


def _translate(call):
    try:
        return call()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TypeError, ValueError, LookupError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class DatasetRowsRequest(BaseModel):
    rows: list[dict[str, Any]]
    provenance: dict[str, Any] = Field(default_factory=dict)


@router.put("/projects/{project_id}/datasets/{dataset_id}/rows")
def put_dataset_rows(
    project_id: str,
    dataset_id: str,
    request: DatasetRowsRequest,
    identity: OwnerIdentity,
) -> dict:
    return _translate(
        lambda: _store().put(
            _owner(identity), project_id, dataset_id, request.rows, request.provenance
        )
    )


@router.get("/projects/{project_id}/datasets/{dataset_id}/rows")
def get_dataset_rows(project_id: str, dataset_id: str, identity: OwnerIdentity) -> dict:
    return _translate(lambda: _store().get(_owner(identity), project_id, dataset_id))


@router.get("/projects/{project_id}/datasets/{dataset_id}/rows/readiness")
def dataset_rows_readiness(
    project_id: str, dataset_id: str, identity: OwnerIdentity
) -> dict:
    return _translate(lambda: _store().readiness(_owner(identity), project_id, dataset_id))

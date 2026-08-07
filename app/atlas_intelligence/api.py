from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .fixtures import build_vertical_slice
from .models import AtlasLayer, SpatialDataset, ThematicMapManifest
from .registry import AtlasRegistry

router = APIRouter(prefix="/atlas", tags=["atlas"])
registry = AtlasRegistry()


def load_fixture_registry() -> AtlasRegistry:
    """Load the non-production fixture set idempotently for validation/demo use."""
    result = build_vertical_slice()
    for dataset in result["datasets"]:
        registry.register_dataset(dataset)
    for layer in result["layers"]:
        registry.register_layer(layer)
    registry.register_manifest(result["manifest"])
    return registry


@router.get("/status")
def atlas_status() -> dict[str, object]:
    return {
        "service": "atlas-planetary-intelligence",
        "mode": "read-only-candidate",
        "publication_enabled": False,
        **registry.status(),
    }


@router.get("/datasets/{dataset_id}", response_model=SpatialDataset)
def get_dataset(dataset_id: str) -> SpatialDataset:
    try:
        return registry.get_dataset(dataset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/layers", response_model=list[AtlasLayer])
def list_layers(kind: str | None = Query(default=None)) -> list[AtlasLayer]:
    return registry.list_layers(kind=kind)


@router.get("/layers/{layer_id}", response_model=AtlasLayer)
def get_layer(layer_id: str) -> AtlasLayer:
    try:
        return registry.get_layer(layer_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/maps/{map_id}", response_model=ThematicMapManifest)
def get_map_manifest(map_id: str) -> ThematicMapManifest:
    try:
        return registry.get_manifest(map_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

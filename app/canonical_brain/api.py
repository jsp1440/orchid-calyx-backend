from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .fixtures import build_canonical_brain_fixture
from .models import BrainObject, BrainSnapshot, SearchHit
from .registry import CanonicalBrainRegistry


def create_brain_router(registry: CanonicalBrainRegistry | None = None) -> APIRouter:
    brain = registry or build_canonical_brain_fixture()
    router = APIRouter(prefix="/brain/canonical", tags=["canonical-brain"])

    @router.get("/status")
    def status() -> dict[str, object]:
        snapshot = brain.snapshot()
        return {
            "mode": "read-only-candidate",
            "write_enabled": False,
            "publication_enabled": False,
            "object_count": len(snapshot.objects),
            "relationship_count": len(snapshot.relationships),
            "snapshot_checksum": snapshot.snapshot_checksum,
        }

    @router.get("/objects/{object_id}", response_model=BrainObject)
    def get_object(object_id: str) -> BrainObject:
        record = brain.get(object_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Brain object not found")
        return record

    @router.get("/search", response_model=list[SearchHit])
    def search(q: str = Query(min_length=1)) -> list[SearchHit]:
        return brain.search(q)

    @router.get("/objects/{object_id}/related", response_model=list[BrainObject])
    def related(object_id: str, relationship_type: str | None = None) -> list[BrainObject]:
        if brain.get(object_id) is None:
            raise HTTPException(status_code=404, detail="Brain object not found")
        return brain.related(object_id, relationship_type)

    @router.get("/objects/{object_id}/intents", response_model=list[BrainObject])
    def intents(object_id: str) -> list[BrainObject]:
        if brain.get(object_id) is None:
            raise HTTPException(status_code=404, detail="Brain object not found")
        return brain.aligned_intents(object_id)

    @router.get("/snapshot", response_model=BrainSnapshot)
    def snapshot() -> BrainSnapshot:
        return brain.snapshot()

    return router

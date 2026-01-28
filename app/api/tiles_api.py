from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query

from app.tiles.registry import TILE_REGISTRY

router = APIRouter(tags=["tiles"])

def _filter_tiles(
    scope: Optional[str] = None,
    audience: Optional[str] = None,
    mode: Optional[str] = None,
    priority: Optional[str] = None,
) -> List[Dict[str, Any]]:
    tiles: List[Dict[str, Any]] = TILE_REGISTRY["tiles"]

    def keep(t: Dict[str, Any]) -> bool:
        if scope and t.get("scope") != scope:
            return False
        if priority and t.get("priority") != priority:
            return False
        if audience and audience not in (t.get("audiences") or []):
            return False
        if mode:
            modes = t.get("modes") or []
            # empty modes => always visible
            if modes and mode not in modes:
                return False
        return True

    return [t for t in tiles if keep(t)]

@router.get("/tiles/registry")
def get_tile_registry(
    scope: Optional[str] = Query(default=None),
    audience: Optional[str] = Query(default=None),
    mode: Optional[str] = Query(default=None),
    priority: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    return {
        "version": TILE_REGISTRY["version"],
        "tiles": _filter_tiles(scope=scope, audience=audience, mode=mode, priority=priority),
    }

@router.get("/tiles/registry/{tile_id}")
def get_tile(tile_id: str) -> Dict[str, Any]:
    for t in TILE_REGISTRY["tiles"]:
        if t.get("tile_id") == tile_id:
            return t
    raise HTTPException(status_code=404, detail="Tile not found")

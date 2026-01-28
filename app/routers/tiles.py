from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api", tags=["tiles"])

TILE_REGISTRY = {
    "version": "1.0",
    "tiles": [
        {
            "id": "select_show",
            "title": "Select Show",
            "route": "/shows/select",
            "role_visibility": ["admin", "exhibitor", "volunteer", "judge"],
            "status": "active"
        },
        {
            "id": "my_tasks",
            "title": "My Tasks",
            "route": "/me/tasks",
            "role_visibility": ["admin", "exhibitor", "volunteer", "judge"],
            "status": "active"
        },
        {
            "id": "entries",
            "title": "Entries",
            "route": "/entries",
            "role_visibility": ["admin", "exhibitor", "volunteer"],
            "status": "active"
        },
        {
            "id": "volunteers",
            "title": "Volunteers",
            "route": "/volunteers",
            "role_visibility": ["admin", "volunteer"],
            "status": "active"
        },
        {
            "id": "judging",
            "title": "Judging",
            "route": "/judging",
            "role_visibility": ["admin", "judge"],
            "status": "active"
        },
        {
            "id": "awards",
            "title": "Awards",
            "route": "/awards",
            "role_visibility": ["admin", "judge"],
            "status": "active"
        },
        {
            "id": "admin",
            "title": "Admin",
            "route": "/admin",
            "role_visibility": ["admin"],
            "status": "active"
        },
        {
            "id": "help",
            "title": "Help",
            "route": "/help",
            "role_visibility": ["admin", "exhibitor", "volunteer", "judge", "public"],
            "status": "active"
        }
    ]
}


@router.get("/tiles/registry")
def get_tile_registry(
    role: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    if role:
        filtered = [t for t in TILE_REGISTRY["tiles"] if role in t.get("role_visibility", [])]
        return {"version": TILE_REGISTRY["version"], "tiles": filtered}
    return TILE_REGISTRY

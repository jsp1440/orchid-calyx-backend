"""Featured Genus v1 API — selection and composed scientific profile.

Routes:
    GET /api/featured-genus/v1/selection        — reproducible current selection
    GET /api/featured-genus/v1/profile/{genus}  — composed genus exhibit payload

Both routes are read-only, unauthenticated public reads behind the same
CORS boundary as the existing Featured Genus media endpoint. Neither route
schedules work, writes state, or calls external providers.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request, Response

from app.featured_genus.profile import build_featured_genus_profile
from app.featured_genus.selection import select_featured_genus
from app.routers.orchid_widgets import _allow_frontend_origin, _normalize_genus

router = APIRouter(prefix="/api/featured-genus/v1", tags=["Featured Genus"])


def _options_response(request: Request, response: Response) -> Response:
    _allow_frontend_origin(request, response)
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Accept, Content-Type"
    return Response(status_code=204, headers=dict(response.headers))


@router.options("/selection")
def selection_options(request: Request, response: Response):
    return _options_response(request, response)


@router.options("/profile/{genus}")
def profile_options(genus: str, request: Request, response: Response):
    return _options_response(request, response)


@router.get("/selection")
def featured_genus_selection(
    request: Request,
    response: Response,
    at: int | None = Query(
        default=None,
        description="Optional epoch-seconds override for reproducible inspection of past/future windows.",
    ),
) -> dict[str, Any]:
    """Resolve the current Featured Genus selection (featured-genus-selection/v1).

    Deterministic given the clock; an active, reviewed, unexpired editorial
    override wins over the rotation and is always reported with its reviewer,
    reason, and expiry. `at` makes any rotation window reproducible.
    """
    _allow_frontend_origin(request, response)
    return select_featured_genus(at)


@router.get("/profile/{genus}")
def featured_genus_profile(
    genus: str,
    request: Request,
    response: Response,
    media_limit: int = Query(default=12, ge=1, le=24),
) -> dict[str, Any]:
    """Compose the Featured Genus scientific profile (featured-genus-profile/v1).

    Accepted-genus resolution, recorded species count, approved media (the
    same selection policy as /api/media/genus), habitat/elevation evidence,
    and Knowledge Graph domain coverage — each with an explicit evidence
    state. Unknown is never absence; unavailable is never a fallback claim.
    """
    _allow_frontend_origin(request, response)
    accepted_genus = _normalize_genus(genus)
    return build_featured_genus_profile(
        accepted_genus,
        requested_genus=genus,
        media_limit=media_limit,
    )

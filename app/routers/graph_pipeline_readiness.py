"""Owner-visible, read-only graph pipeline readiness endpoint."""

from typing import Any

from fastapi import APIRouter, Depends

from app.security import verify_owner_or_api_key
from runtime.graph_pipeline_readiness import build_graph_pipeline_readiness

router = APIRouter(tags=["graph-pipeline-readiness"])


@router.get("/api/mission-control/graph-pipeline/readiness")
def graph_pipeline_readiness(
    _: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    return build_graph_pipeline_readiness()

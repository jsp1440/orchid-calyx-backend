from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.design_intelligence.knowledge import EducationalClassification
from app.design_intelligence.routes import REASONING_SERVICE

router = APIRouter(prefix="/education-design", tags=["calyx-education-design"])


class EducationDesignSearch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=25)


@router.get("/readiness")
def readiness() -> dict[str, Any]:
    return {
        "status": "partially_integrated",
        "design_intelligence": {
            "corpus_search": True,
            "semantic_reasoning": True,
            "ux_ui": True,
            "accessibility": True,
            "information_architecture": True,
            "scientific_visualization": True,
        },
        "education": {
            "classifications": [item.value for item in EducationalClassification],
            "learning_sciences_indexing": True,
            "curriculum_runtime": False,
            "course_persistence": False,
            "assessment_engine": False,
            "student_progress": False,
            "virtual_lab_runtime": False,
        },
        "governance": {
            "read_only": True,
            "recommendations_prepare_only": True,
            "website_changes_require_owner_approval": True,
            "course_publication_requires_owner_approval": True,
            "scientific_publication_requires_scientific_approval": True,
        },
    }


@router.post("/search")
def search(payload: EducationDesignSearch) -> dict[str, Any]:
    try:
        result = REASONING_SERVICE.search(payload.query, limit=payload.limit)
    except ValueError as exc:
        raise HTTPException(422, detail={"code": str(exc)}) from exc
    return {
        **result,
        "brain_boundary": True,
        "read_only": True,
        "implementation_requires_approval": True,
    }

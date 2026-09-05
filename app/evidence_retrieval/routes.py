from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from app.semantic_index.provider import DeterministicLocalProvider
from app.semantic_index.repository_runtime import get_repository_runtime

from .engine import RetrievalEngine
from .models import RetrievalQuery

router = APIRouter(
    prefix="/api/evidence-retrieval",
    tags=["evidence-retrieval"],
    dependencies=[Depends(verify_owner_or_api_key)],
)


def _repo():
    return get_repository_runtime().read()


def _engine():
    return RetrievalEngine(_repo(), DeterministicLocalProvider())


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    collections: list[str] = []
    object_types: list[str] = []
    document_classes: list[str] = []
    language: str | None = None
    historical: bool = False
    limit: int = Field(10, ge=1, le=100)
    offset: int = Field(0, ge=0, le=10000)
    per_source_limit: int = Field(2, ge=1, le=20)
    parent_expansion: str = "AUTO"
    internal_access: bool = False


def run(p, mode, extra=None):
    values = p.model_dump()
    values["text"] = values.pop("query")
    values["mode"] = mode
    values["collections"] = tuple(values["collections"])
    values["object_types"] = tuple(
        (extra or {}).get("object_types", values["object_types"])
    )
    values["document_classes"] = tuple(values["document_classes"])
    try:
        return _engine().search(RetrievalQuery(**values))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(
            503, detail={"code": "SEMANTIC_INDEX_DATABASE_UNAVAILABLE"}
        ) from e


@router.post("/lexical")
def lexical(p: SearchIn):
    return run(p, "LEXICAL")


@router.post("/semantic")
def semantic(p: SearchIn):
    return run(p, "SEMANTIC")


@router.post("/hybrid")
def hybrid(p: SearchIn):
    return run(p, "HYBRID")


@router.post("/collections/{collection}")
def collection(collection: str, p: SearchIn):
    p.collections = [collection]
    return run(p, "HYBRID")


@router.post("/protocols")
def protocols(p: SearchIn):
    return run(p, "HYBRID", {"object_types": ["PROTOCOL"]})


@router.post("/results")
def results(p: SearchIn):
    return run(p, "HYBRID", {"object_types": ["RESULT"]})


@router.post("/taxonomic-treatments")
def treatments(p: SearchIn):
    return run(p, "HYBRID", {"object_types": ["TAXONOMIC_TREATMENT"]})


@router.post("/identification-keys")
def keys(p: SearchIn):
    return run(p, "HYBRID", {"object_types": ["IDENTIFICATION_KEY"]})


@router.post("/claims")
def claims(p: SearchIn):
    return run(p, "HYBRID", {"object_types": ["CLAIM"]})


@router.post("/strategic-insights")
def insights(p: SearchIn):
    return run(p, "HYBRID", {"object_types": ["STRATEGIC_INSIGHT"]})


@router.post("/candidate-events")
def events(p: SearchIn):
    return run(p, "HYBRID", {"object_types": ["CANDIDATE_EVENT"]})


@router.get("/results/{index_document_id}")
def one(index_document_id: int):
    return next(
        (x for x in _repo().documents if x["index_document_id"] == index_document_id),
        None,
    )


@router.get("/configuration")
def configuration():
    engine = _engine()
    return {
        "ranking_version": engine.ranking_version,
        "modes": ["LEXICAL", "SEMANTIC", "HYBRID"],
        "expansions": sorted(
            __import__(
                "app.evidence_retrieval.models", fromlist=["EXPANSIONS"]
            ).EXPANSIONS
        ),
        "max_query_length": 500,
        "max_results": 100,
    }


@router.get("/health")
def health():
    engine = _engine()
    return {
        "status": "ok",
        "read_only": True,
        "active_models": len(engine.repo.models),
        "ranking_version": engine.ranking_version,
    }


@router.get("/status")
def status():
    runtime = get_repository_runtime()
    try:
        runtime.read()
    except HTTPException:
        pass
    payload = runtime.status()
    payload["ranking_version"] = _engine().ranking_version if not payload["unavailable"] else None
    return payload

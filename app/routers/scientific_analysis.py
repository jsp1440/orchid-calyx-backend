"""Protected Scientific Computing & Analysis Engine routes for CALYX issue #617."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.research_analysis_workflow import ResearchAnalysisWorkflowService
from runtime.scientific_analysis import ScientificAnalysisService
from runtime.scientific_analysis_history import ScientificAnalysisHistoryService
from runtime.scientific_comparison import ScientificComparisonService
from runtime.scientific_dataset_snapshots import ScientificDatasetSnapshotService
from runtime.scientific_diagnostics import ScientificDiagnosticsService
from runtime.scientific_export_bundle import ScientificAnalysisExportService
from runtime.scientific_result_artifacts import ScientificResultArtifactService
from runtime.scientific_runtime_readiness import scientific_runtime_readiness

router = APIRouter(
    prefix="/brain/mission-control/research/analysis",
    tags=["mission-control-scientific-analysis"],
)
_service_instance = ScientificAnalysisService()
_workflow_instance = ResearchAnalysisWorkflowService(analysis=_service_instance)
_history_instance = ScientificAnalysisHistoryService(_service_instance)
_snapshot_instance = ScientificDatasetSnapshotService(_workflow_instance)
_diagnostics_instance = ScientificDiagnosticsService(_workflow_instance)
_comparison_instance = ScientificComparisonService(_service_instance)
_result_artifact_instance = ScientificResultArtifactService(
    _service_instance,
    _diagnostics_instance,
)
_export_instance = ScientificAnalysisExportService(
    _service_instance,
    _workflow_instance,
    _diagnostics_instance,
    _result_artifact_instance,
)
OwnerIdentity = Annotated[dict[str, object], Depends(verify_owner_or_api_key)]


def _service() -> ScientificAnalysisService:
    return _service_instance


def _workflow() -> ResearchAnalysisWorkflowService:
    return _workflow_instance


def _history() -> ScientificAnalysisHistoryService:
    return _history_instance


def _snapshots() -> ScientificDatasetSnapshotService:
    return _snapshot_instance


def _diagnostics() -> ScientificDiagnosticsService:
    return _diagnostics_instance


def _comparison() -> ScientificComparisonService:
    return _comparison_instance


def _result_artifacts() -> ScientificResultArtifactService:
    return _result_artifact_instance


def _exports() -> ScientificAnalysisExportService:
    return _export_instance


def _owner(identity: dict[str, object]) -> str:
    actor = str(identity.get("actor") or "").strip()
    if not actor:
        raise HTTPException(status_code=403, detail="Scientific analysis owner scope unavailable")
    return actor


def _translate(call):
    try:
        return call()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TypeError, ValueError, LookupError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class AnalysisRequest(BaseModel):
    method: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    rows: list[dict[str, Any]]
    provenance: dict[str, Any]
    dataset_ref: dict[str, Any] | None = None
    missing_policy: str = "complete_case"


class AnalysisPlanRequest(BaseModel):
    question: str
    rationale: str
    dataset_id: str
    variables: list[dict[str, Any]]
    method: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    missing_policy: str = "complete_case"
    transformations: list[dict[str, Any]] = Field(default_factory=list)
    row_filters: list[dict[str, Any]] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    created_at: str


class PlanRowsRequest(BaseModel):
    rows: list[dict[str, Any]]
    provenance: dict[str, Any]


class ExecutePlanRequest(PlanRowsRequest):
    recorded_at: str


class DatasetSnapshotRequest(BaseModel):
    rows: list[dict[str, Any]]
    provenance: dict[str, Any]
    recorded_at: str


class CompareRunsRequest(BaseModel):
    analysis_a_id: str
    analysis_b_id: str


@router.get("/capabilities")
def capabilities(identity: OwnerIdentity) -> dict:
    _owner(identity)
    return _service().capabilities()


@router.post("/projects/{project_id}/validate")
def validate(project_id: str, request: AnalysisRequest, identity: OwnerIdentity) -> dict:
    return _translate(
        lambda: _service().validate(_owner(identity), project_id, request.model_dump())
    )


@router.post("/projects/{project_id}/execute")
def execute(project_id: str, request: AnalysisRequest, identity: OwnerIdentity) -> dict:
    return _translate(
        lambda: _service().execute(_owner(identity), project_id, request.model_dump())
    )


@router.get("/projects/{project_id}/analyses")
def list_analyses(
    project_id: str,
    identity: OwnerIdentity,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    return _translate(
        lambda: _history().list(
            _owner(identity),
            project_id,
            limit=limit,
            offset=offset,
        )
    )


@router.get("/projects/{project_id}/results/{analysis_id}")
def get_result(project_id: str, analysis_id: str, identity: OwnerIdentity) -> dict:
    return _translate(lambda: _service().get(_owner(identity), project_id, analysis_id))


@router.get("/projects/{project_id}/readiness")
def readiness(project_id: str, identity: OwnerIdentity) -> dict:
    owner = _owner(identity)
    return _translate(
        lambda: {
            "engine": _service().readiness(owner, project_id),
            "workflow": _workflow().readiness(owner, project_id),
            "dataset_snapshots": _snapshots().readiness(owner, project_id),
            "runtime_environment": scientific_runtime_readiness(),
        }
    )


@router.get("/projects/{project_id}/dataset-snapshots")
def list_dataset_snapshots(project_id: str, identity: OwnerIdentity) -> dict:
    return _translate(lambda: _snapshots().list(_owner(identity), project_id))


@router.get("/projects/{project_id}/dataset-snapshots/{dataset_id}")
def get_dataset_snapshot(project_id: str, dataset_id: str, identity: OwnerIdentity) -> dict:
    return _translate(lambda: _snapshots().get(_owner(identity), project_id, dataset_id))


@router.post("/projects/{project_id}/dataset-snapshots/{dataset_id}", status_code=201)
def put_dataset_snapshot(
    project_id: str,
    dataset_id: str,
    request: DatasetSnapshotRequest,
    identity: OwnerIdentity,
) -> dict:
    owner = _owner(identity)
    payload = {**request.model_dump(), "recorded_by": owner}
    return _translate(lambda: _snapshots().put(owner, project_id, dataset_id, payload))


@router.post("/projects/{project_id}/plans", status_code=201)
def create_plan(project_id: str, request: AnalysisPlanRequest, identity: OwnerIdentity) -> dict:
    owner = _owner(identity)
    payload = {**request.model_dump(), "created_by": owner}
    return _translate(lambda: _workflow().create_plan(owner, project_id, payload))


@router.get("/projects/{project_id}/plans/{plan_id}")
def get_plan(project_id: str, plan_id: str, identity: OwnerIdentity) -> dict:
    return _translate(lambda: _workflow().get_plan(_owner(identity), project_id, plan_id))


@router.post("/projects/{project_id}/plans/{plan_id}/validate")
def validate_plan_rows(
    project_id: str,
    plan_id: str,
    request: PlanRowsRequest,
    identity: OwnerIdentity,
) -> dict:
    return _translate(
        lambda: _workflow().validate_plan_rows(
            _owner(identity), project_id, plan_id, request.rows, request.provenance
        )
    )


@router.post("/projects/{project_id}/plans/{plan_id}/execute")
def execute_plan(
    project_id: str,
    plan_id: str,
    request: ExecutePlanRequest,
    identity: OwnerIdentity,
) -> dict:
    owner = _owner(identity)
    payload = {**request.model_dump(), "recorded_by": owner}
    return _translate(lambda: _workflow().execute_plan(owner, project_id, plan_id, payload))


@router.post("/projects/{project_id}/plans/{plan_id}/results/{analysis_id}/diagnostics")
def build_diagnostics(
    project_id: str,
    plan_id: str,
    analysis_id: str,
    request: PlanRowsRequest,
    identity: OwnerIdentity,
) -> dict:
    owner = _owner(identity)
    return _translate(
        lambda: _diagnostics().build(
            owner,
            project_id,
            plan_id,
            analysis_id,
            request.rows,
            request.provenance,
        )
    )


@router.get("/projects/{project_id}/results/{analysis_id}/diagnostics")
def get_diagnostics(project_id: str, analysis_id: str, identity: OwnerIdentity) -> dict:
    return _translate(lambda: _diagnostics().get(_owner(identity), project_id, analysis_id))


@router.post("/projects/{project_id}/results/{analysis_id}/artifacts")
def build_result_artifact(project_id: str, analysis_id: str, identity: OwnerIdentity) -> dict:
    return _translate(lambda: _result_artifacts().build(_owner(identity), project_id, analysis_id))


@router.get("/projects/{project_id}/results/{analysis_id}/artifacts")
def get_result_artifact(project_id: str, analysis_id: str, identity: OwnerIdentity) -> dict:
    return _translate(lambda: _result_artifacts().get(_owner(identity), project_id, analysis_id))


@router.post("/projects/{project_id}/results/{analysis_id}/exports")
def build_analysis_export(project_id: str, analysis_id: str, identity: OwnerIdentity) -> dict:
    return _translate(lambda: _exports().build(_owner(identity), project_id, analysis_id))


@router.get("/projects/{project_id}/exports/{export_id}")
def get_analysis_export(project_id: str, export_id: str, identity: OwnerIdentity) -> dict:
    return _translate(lambda: _exports().get(_owner(identity), project_id, export_id))


@router.get("/projects/{project_id}/exports/{export_id}/integrity")
def verify_analysis_export(project_id: str, export_id: str, identity: OwnerIdentity) -> dict:
    return _translate(lambda: _exports().verify(_owner(identity), project_id, export_id))


@router.post("/projects/{project_id}/comparisons")
def compare_runs(project_id: str, request: CompareRunsRequest, identity: OwnerIdentity) -> dict:
    owner = _owner(identity)
    return _translate(
        lambda: _comparison().compare(
            owner,
            project_id,
            request.analysis_a_id,
            request.analysis_b_id,
        )
    )


@router.get("/projects/{project_id}/comparisons/{comparison_id}")
def get_comparison(project_id: str, comparison_id: str, identity: OwnerIdentity) -> dict:
    return _translate(lambda: _comparison().get(_owner(identity), project_id, comparison_id))

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BuildAdmissionRequest(StrictModel):
    build_id: str = Field(min_length=3)
    architecture_id: str = Field(min_length=3)
    intent_ids: list[str] = Field(min_length=1)
    decision_ids: list[str] = Field(min_length=1)
    source_uris: list[str] = Field(min_length=1)
    validation_plan_ids: list[str] = Field(min_length=1)
    deterministic_outputs: bool
    preserves_provenance: bool
    separates_evidence_from_inference: bool
    publication_requested: bool = False
    deployment_requested: bool = False
    merge_requested: bool = False
    production_graph_mutation_requested: bool = False


class AdmissionFinding(StrictModel):
    rule_id: str
    severity: Literal["warning", "error"]
    message: str


class BuildAdmissionDecision(StrictModel):
    build_id: str
    status: Literal["admitted", "blocked"]
    findings: list[AdmissionFinding]


CONSTITUTION_VERSION = "1.0.0"


def evaluate_build_admission(request: BuildAdmissionRequest) -> BuildAdmissionDecision:
    findings: list[AdmissionFinding] = []

    if not request.preserves_provenance:
        findings.append(AdmissionFinding(rule_id="OC-CONST-001", severity="error", message="Builds must preserve provenance."))
    if not request.separates_evidence_from_inference:
        findings.append(AdmissionFinding(rule_id="OC-CONST-002", severity="error", message="Evidence and inference must remain explicitly separated."))
    if not request.deterministic_outputs:
        findings.append(AdmissionFinding(rule_id="OC-CONST-003", severity="error", message="Repeatable builds require deterministic outputs."))
    if request.publication_requested:
        findings.append(AdmissionFinding(rule_id="OC-CONST-004", severity="error", message="Autonomous publication is not authorized at build admission."))
    if request.deployment_requested:
        findings.append(AdmissionFinding(rule_id="OC-CONST-005", severity="error", message="Autonomous deployment is not authorized at build admission."))
    if request.merge_requested:
        findings.append(AdmissionFinding(rule_id="OC-CONST-006", severity="error", message="Autonomous merge is not authorized at build admission."))
    if request.production_graph_mutation_requested:
        findings.append(AdmissionFinding(rule_id="OC-CONST-007", severity="error", message="Production Knowledge Graph mutation requires a separate governed publication path."))

    return BuildAdmissionDecision(
        build_id=request.build_id,
        status="blocked" if any(item.severity == "error" for item in findings) else "admitted",
        findings=findings,
    )

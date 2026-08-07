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
    rules = (
        (not request.preserves_provenance, "OC-CONST-001", "Builds must preserve provenance."),
        (not request.separates_evidence_from_inference, "OC-CONST-002", "Evidence and inference must remain explicitly separated."),
        (not request.deterministic_outputs, "OC-CONST-003", "Repeatable builds require deterministic outputs."),
        (request.publication_requested, "OC-CONST-004", "Autonomous publication is not authorized at build admission."),
        (request.deployment_requested, "OC-CONST-005", "Autonomous deployment is not authorized at build admission."),
        (request.merge_requested, "OC-CONST-006", "Autonomous merge is not authorized at build admission."),
        (request.production_graph_mutation_requested, "OC-CONST-007", "Production Knowledge Graph mutation requires a separate governed publication path."),
    )
    for violated, rule_id, message in rules:
        if violated:
            findings.append(AdmissionFinding(rule_id=rule_id, severity="error", message=message))
    return BuildAdmissionDecision(
        build_id=request.build_id,
        status="blocked" if findings else "admitted",
        findings=findings,
    )

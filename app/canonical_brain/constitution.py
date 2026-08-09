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
    ci_infrastructure_status: Literal["healthy", "degraded", "unavailable"] = "healthy"
    equivalent_pre_step_failures_60m: int = Field(default=0, ge=0)
    workflow_triggering_change_requested: bool = False
    infrastructure_repair_requested: bool = False
    diagnostic_recovery_probe_requested: bool = False
    material_recovery_evidence_present: bool = False


class AdmissionFinding(StrictModel):
    rule_id: str
    severity: Literal["warning", "error"]
    message: str


class BuildAdmissionDecision(StrictModel):
    build_id: str
    status: Literal["admitted", "blocked"]
    findings: list[AdmissionFinding]


CONSTITUTION_VERSION = "1.1.0"
CI_CIRCUIT_BREAKER_THRESHOLD = 3


def _ci_circuit_breaker_open(request: BuildAdmissionRequest) -> bool:
    return (
        request.ci_infrastructure_status == "unavailable"
        or request.equivalent_pre_step_failures_60m >= CI_CIRCUIT_BREAKER_THRESHOLD
    )


def evaluate_build_admission(request: BuildAdmissionRequest) -> BuildAdmissionDecision:
    findings: list[AdmissionFinding] = []
    circuit_open = _ci_circuit_breaker_open(request)
    diagnostic_probe_without_recovery_evidence = (
        request.diagnostic_recovery_probe_requested
        and circuit_open
        and not request.material_recovery_evidence_present
    )
    workflow_expansion_during_outage = (
        circuit_open
        and request.workflow_triggering_change_requested
        and not request.infrastructure_repair_requested
    )
    rules = (
        (not request.preserves_provenance, "OC-CONST-001", "Builds must preserve provenance."),
        (not request.separates_evidence_from_inference, "OC-CONST-002", "Evidence and inference must remain explicitly separated."),
        (not request.deterministic_outputs, "OC-CONST-003", "Repeatable builds require deterministic outputs."),
        (request.publication_requested, "OC-CONST-004", "Autonomous publication is not authorized at build admission."),
        (request.deployment_requested, "OC-CONST-005", "Autonomous deployment is not authorized at build admission."),
        (request.merge_requested, "OC-CONST-006", "Autonomous merge is not authorized at build admission."),
        (request.production_graph_mutation_requested, "OC-CONST-007", "Production Knowledge Graph mutation requires a separate governed publication path."),
        (
            workflow_expansion_during_outage,
            "OC-CONST-008",
            "CI circuit breaker is open: new workflow-triggering implementation expansion is blocked until executable infrastructure recovers; infrastructure repair remains allowed.",
        ),
        (
            diagnostic_probe_without_recovery_evidence,
            "OC-CONST-009",
            "Repeated CI recovery probes require material evidence that the infrastructure condition may have changed.",
        ),
    )
    for violated, rule_id, message in rules:
        if violated:
            findings.append(AdmissionFinding(rule_id=rule_id, severity="error", message=message))
    if request.ci_infrastructure_status == "degraded" and not circuit_open:
        findings.append(
            AdmissionFinding(
                rule_id="OC-CONST-W01",
                severity="warning",
                message="CI infrastructure is degraded; minimize workflow-triggering changes and avoid redundant retries.",
            )
        )
    return BuildAdmissionDecision(
        build_id=request.build_id,
        status="blocked" if any(item.severity == "error" for item in findings) else "admitted",
        findings=findings,
    )

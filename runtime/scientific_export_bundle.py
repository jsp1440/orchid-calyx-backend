"""Immutable private reproducibility export bundles for CALYX scientific analyses."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from runtime.research_analysis_workflow import ResearchAnalysisWorkflowService
from runtime.scientific_analysis import ScientificAnalysisService
from runtime.scientific_diagnostics import ScientificDiagnosticsService
from runtime.scientific_result_artifacts import ScientificResultArtifactService

EXPORT_SCHEMA_VERSION = "calyx-scientific-analysis-export/v1"


def _stable(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(payload: Any) -> str:
    return hashlib.sha256(_stable(payload).encode("utf-8")).hexdigest()


def _atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _clean_identifier(value: str, error: str) -> str:
    clean = str(value or "").strip()
    if not clean or any(token in clean for token in ("/", "\\", "..")):
        raise ValueError(error)
    return clean


class ScientificAnalysisExportService:
    def __init__(
        self,
        analysis: ScientificAnalysisService | None = None,
        workflow: ResearchAnalysisWorkflowService | None = None,
        diagnostics: ScientificDiagnosticsService | None = None,
        result_artifacts: ScientificResultArtifactService | None = None,
    ) -> None:
        self.analysis = analysis or ScientificAnalysisService()
        self.workflow = workflow or ResearchAnalysisWorkflowService(analysis=self.analysis)
        self.diagnostics = diagnostics or ScientificDiagnosticsService(self.workflow)
        self.result_artifacts = result_artifacts or ScientificResultArtifactService(
            self.analysis,
            self.diagnostics,
        )

    def _root(self, owner_id: str, project_id: str) -> Path:
        return self.analysis._project_root(owner_id, project_id)

    @staticmethod
    def _analysis_projection(analysis: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": analysis.get("schema_version"),
            "analysis_id": analysis.get("analysis_id"),
            "method": analysis.get("method"),
            "method_name": analysis.get("method_name"),
            "method_version": analysis.get("method_version"),
            "parameters": analysis.get("parameters") or {},
            "missing_policy": analysis.get("missing_policy"),
            "rows_received": analysis.get("rows_received"),
            "rows_or_values_dropped_for_missingness": analysis.get(
                "rows_or_values_dropped_for_missingness"
            ),
            "input_sha256": analysis.get("input_sha256"),
            "result_sha256": analysis.get("result_sha256"),
            "dataset_ref": analysis.get("dataset_ref"),
            "provenance": analysis.get("provenance") or {},
            "assumptions": list(analysis.get("assumptions") or []),
            "warnings": list(analysis.get("warnings") or []),
            "result": analysis.get("result") or {},
            "reproducibility": analysis.get("reproducibility") or {},
            "computed_output": analysis.get("computed_output") is True,
            "interpretation_generated": False,
            "human_review_required_for_scientific_conclusion": True,
            "scientific_publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
        }

    @staticmethod
    def _diagnostic_projection(diagnostic: dict[str, Any]) -> dict[str, Any]:
        return {
            "diagnostic_id": diagnostic.get("diagnostic_id"),
            "diagnostics_sha256": diagnostic.get("diagnostics_sha256"),
            "analysis_id": diagnostic.get("analysis_id"),
            "plan_id": diagnostic.get("plan_id"),
            "method": diagnostic.get("method"),
            "method_version": diagnostic.get("method_version"),
            "input_sha256": diagnostic.get("input_sha256"),
            "result_sha256": diagnostic.get("result_sha256"),
            "raw_dataset_checksum_sha256": diagnostic.get("raw_dataset_checksum_sha256"),
            "analytical_rows_sha256": diagnostic.get("analytical_rows_sha256"),
            "diagnostics_payload_included": False,
            "diagnostics_are_descriptive_not_inferential": True,
            "scientific_interpretation_generated": False,
        }

    @staticmethod
    def _numerical_environment(
        analysis: dict[str, Any], artifact: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        result = analysis.get("result")
        if isinstance(result, dict) and isinstance(result.get("numerical_environment"), dict):
            return dict(result["numerical_environment"])
        if artifact:
            uncertainty = artifact.get("uncertainty_artifact")
            if isinstance(uncertainty, dict) and isinstance(
                uncertainty.get("numerical_environment"), dict
            ):
                return dict(uncertainty["numerical_environment"])
        return None

    def _receipt(self, root: Path, analysis_id: str) -> dict[str, Any] | None:
        path = root / "analysis_receipts" / f"{analysis_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _validate_receipt(analysis: dict[str, Any], receipt: dict[str, Any]) -> None:
        required_pairs = (
            ("analysis_id", "analysis_id"),
            ("input_sha256", "input_sha256"),
            ("result_sha256", "result_sha256"),
            ("method", "method"),
            ("method_version", "method_version"),
        )
        for analysis_key, receipt_key in required_pairs:
            if analysis.get(analysis_key) != receipt.get(receipt_key):
                raise ValueError("ANALYSIS_EXPORT_RECEIPT_IDENTITY_MISMATCH")

    def build(self, owner_id: str, project_id: str, analysis_id: str) -> dict[str, Any]:
        clean_analysis_id = _clean_identifier(analysis_id, "ANALYSIS_EXPORT_ANALYSIS_ID_INVALID")
        analysis = self.analysis.get(owner_id, project_id, clean_analysis_id)
        root = self._root(owner_id, project_id)
        receipt = self._receipt(root, clean_analysis_id)
        plan: dict[str, Any] | None = None
        if receipt is not None:
            self._validate_receipt(analysis, receipt)
            plan_id = str(receipt.get("plan_id") or "").strip()
            if not plan_id:
                raise ValueError("ANALYSIS_EXPORT_PLAN_ID_REQUIRED")
            plan = self.workflow.get_plan(owner_id, project_id, plan_id)
            if plan.get("plan_id") != plan_id:
                raise ValueError("ANALYSIS_EXPORT_PLAN_IDENTITY_MISMATCH")

        diagnostic: dict[str, Any] | None
        try:
            diagnostic = self.diagnostics.get(owner_id, project_id, clean_analysis_id)
        except FileNotFoundError:
            diagnostic = None

        artifact: dict[str, Any] | None
        try:
            artifact = self.result_artifacts.get(owner_id, project_id, clean_analysis_id)
        except FileNotFoundError:
            artifact = None

        if diagnostic is not None:
            if diagnostic.get("analysis_id") != clean_analysis_id:
                raise ValueError("ANALYSIS_EXPORT_DIAGNOSTIC_IDENTITY_MISMATCH")
            if diagnostic.get("input_sha256") != analysis.get("input_sha256"):
                raise ValueError("ANALYSIS_EXPORT_DIAGNOSTIC_IDENTITY_MISMATCH")
            if diagnostic.get("result_sha256") != analysis.get("result_sha256"):
                raise ValueError("ANALYSIS_EXPORT_DIAGNOSTIC_IDENTITY_MISMATCH")

        if artifact is not None:
            if artifact.get("analysis_id") != clean_analysis_id:
                raise ValueError("ANALYSIS_EXPORT_ARTIFACT_IDENTITY_MISMATCH")

        core = {
            "schema_version": EXPORT_SCHEMA_VERSION,
            "profile": "private_reproducibility_bundle",
            "project_id": project_id,
            "analysis_id": clean_analysis_id,
            "analysis": self._analysis_projection(analysis),
            "analysis_plan": plan,
            "analysis_receipt": receipt,
            "result_artifact": artifact,
            "diagnostic_identity": (
                self._diagnostic_projection(diagnostic) if diagnostic is not None else None
            ),
            "numerical_environment": self._numerical_environment(analysis, artifact),
            "component_presence": {
                "analysis": True,
                "analysis_plan": plan is not None,
                "analysis_receipt": receipt is not None,
                "result_artifact": artifact is not None,
                "diagnostic_identity": diagnostic is not None,
            },
            "raw_dataset_rows_included": False,
            "diagnostic_payload_included": False,
            "private_research_artifact": True,
            "computed_output": True,
            "scientific_interpretation_generated": False,
            "human_review_required_for_scientific_conclusion": True,
            "scientific_publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
            "export_is_not_publication": True,
        }
        export_sha256 = _sha(core)
        export_id = f"analysis-export-{export_sha256[:24]}"
        bundle = {**core, "export_sha256": export_sha256, "export_id": export_id}
        path = root / "analysis_exports" / f"{export_id}.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != bundle:
                raise ValueError("ANALYSIS_EXPORT_IMMUTABLE_CONFLICT")
            return {"created": False, "export": existing}
        _atomic(path, bundle)
        return {"created": True, "export": bundle}

    def get(self, owner_id: str, project_id: str, export_id: str) -> dict[str, Any]:
        clean_export_id = _clean_identifier(export_id, "ANALYSIS_EXPORT_ID_INVALID")
        if not clean_export_id.startswith("analysis-export-"):
            raise ValueError("ANALYSIS_EXPORT_ID_INVALID")
        path = self._root(owner_id, project_id) / "analysis_exports" / f"{clean_export_id}.json"
        if not path.exists():
            raise FileNotFoundError(clean_export_id)
        bundle = json.loads(path.read_text(encoding="utf-8"))
        if bundle.get("export_id") != clean_export_id or bundle.get("project_id") != project_id:
            raise ValueError("ANALYSIS_EXPORT_IDENTITY_MISMATCH")
        return bundle

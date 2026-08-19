"""Governed Research Station analysis-plan workflow for CALYX issue #617.

This layer binds a visible immutable analysis plan to a registered Research Station
dataset before execution, verifies the raw dataset checksum, executes only declared
versioned transforms and filters, and records a non-interpretive receipt in the notebook.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from runtime.research_station import ResearchStationService
from runtime.scientific_analysis import METHOD_REGISTRY, ScientificAnalysisService
from runtime.scientific_filters import (
    FILTER_ENGINE_VERSION,
    apply_filters,
    normalize_filters,
)
from runtime.scientific_transforms import (
    apply_transformations,
    normalize_transformations,
    normalize_variables,
    transformed_rows_sha256,
    validate_method_variables,
)

PLAN_SCHEMA_VERSION = "calyx-analysis-plan/v3"
TRANSFORMATION_ENGINE_VERSION = "calyx-scientific-transforms/v1"


def _stable(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(payload: Any) -> str:
    material = payload if isinstance(payload, str) else _stable(payload)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


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


def canonical_rows_sha256(rows: list[dict[str, Any]]) -> str:
    """Return the canonical raw-row checksum used when registering a dataset."""
    return _sha(rows)


class ResearchAnalysisWorkflowService:
    def __init__(
        self,
        research: ResearchStationService | None = None,
        analysis: ScientificAnalysisService | None = None,
    ) -> None:
        self.research = research or ResearchStationService()
        self.analysis = analysis or ScientificAnalysisService(self.research)

    def _project_root(self, owner_id: str, project_id: str) -> Path:
        root, _project = self.research._project(owner_id, project_id)
        return root

    def _dataset(self, owner_id: str, project_id: str, dataset_id: str) -> dict[str, Any]:
        root = self._project_root(owner_id, project_id)
        clean = str(dataset_id or "").strip()
        if not clean or any(token in clean for token in ("/", "\\", "..")):
            raise ValueError("ANALYSIS_PLAN_DATASET_ID_INVALID")
        path = root / "datasets" / f"{clean}.json"
        if not path.exists():
            raise FileNotFoundError(clean)
        dataset = json.loads(path.read_text(encoding="utf-8"))
        if dataset.get("project_id") != project_id:
            raise ValueError("ANALYSIS_PLAN_DATASET_PROJECT_MISMATCH")
        checksum = str(dataset.get("checksum_sha256") or "").casefold()
        if len(checksum) != 64:
            raise ValueError("ANALYSIS_PLAN_DATASET_CHECKSUM_INVALID")
        return dataset

    @staticmethod
    def _method(method: Any, parameters: Any) -> tuple[str, dict[str, Any]]:
        method_name = str(method or "").strip()
        if method_name not in METHOD_REGISTRY:
            raise ValueError("ANALYSIS_METHOD_UNSUPPORTED")
        return ScientificAnalysisService._validate_method(method_name, parameters)

    def create_plan(
        self, owner_id: str, project_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        root = self._project_root(owner_id, project_id)
        question = " ".join(str(payload.get("question") or "").strip().split())
        rationale = " ".join(str(payload.get("rationale") or "").strip().split())
        dataset_id = str(payload.get("dataset_id") or "").strip()
        created_by = " ".join(str(payload.get("created_by") or "").strip().split())
        created_at = " ".join(str(payload.get("created_at") or "").strip().split())
        missing_policy = str(payload.get("missing_policy") or "complete_case").strip().casefold()
        if not question or not rationale or not dataset_id or not created_by or not created_at:
            raise ValueError("ANALYSIS_PLAN_FIELDS_REQUIRED")
        if missing_policy != "complete_case":
            raise ValueError("ANALYSIS_MISSING_POLICY_UNSUPPORTED")
        method, parameters = self._method(payload.get("method"), payload.get("parameters"))
        dataset = self._dataset(owner_id, project_id, dataset_id)
        variables = normalize_variables(payload.get("variables"))
        transformations, analytical_variables = normalize_transformations(
            payload.get("transformations"), variables
        )
        validate_method_variables(method, parameters, analytical_variables)
        row_filters = normalize_filters(payload.get("row_filters"), analytical_variables)
        legacy_exclusions = payload.get("exclusions") or []
        if not isinstance(legacy_exclusions, list) or not all(
            isinstance(item, str) for item in legacy_exclusions
        ):
            raise TypeError("ANALYSIS_PLAN_EXCLUSIONS_INVALID")
        if any(item.strip() for item in legacy_exclusions):
            raise ValueError("ANALYSIS_PLAN_LEGACY_EXCLUSIONS_FORBIDDEN_USE_ROW_FILTERS")
        plan_core = {
            "schema_version": PLAN_SCHEMA_VERSION,
            "project_id": project_id,
            "question": question,
            "rationale": rationale,
            "dataset": {
                "dataset_id": dataset["dataset_id"],
                "title": dataset["title"],
                "checksum_sha256": dataset["checksum_sha256"],
                "schema_ref": dataset.get("schema_ref"),
                "provenance": dataset["provenance"],
            },
            "variables": variables,
            "analytical_variables": analytical_variables,
            "method": method,
            "method_version": METHOD_REGISTRY[method]["version"],
            "parameters": parameters,
            "missing_policy": missing_policy,
            "transformation_engine_version": TRANSFORMATION_ENGINE_VERSION,
            "transformations": transformations,
            "filter_engine_version": FILTER_ENGINE_VERSION,
            "row_filters": row_filters,
            "exclusions": [],
            "assumptions": list(METHOD_REGISTRY[method]["assumptions"]),
            "created_by": created_by,
            "created_at": created_at,
            "plan_state": "proposed",
            "explicit_plan_required_for_execution": True,
            "method_auto_selected": False,
            "scientific_interpretation_generated": False,
            "scientific_publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
        }
        plan_id = f"analysis-plan-{_sha(plan_core)[:24]}"
        record = {"plan_id": plan_id, **plan_core}
        path = root / "analysis_plans" / f"{plan_id}.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != record:
                raise ValueError("ANALYSIS_PLAN_IMMUTABLE_CONFLICT")
            return {"created": False, "plan": existing}
        _atomic(path, record)
        return {"created": True, "plan": record}

    def get_plan(self, owner_id: str, project_id: str, plan_id: str) -> dict[str, Any]:
        root = self._project_root(owner_id, project_id)
        clean = str(plan_id or "").strip()
        if not clean or any(token in clean for token in ("/", "\\", "..")):
            raise ValueError("ANALYSIS_PLAN_ID_INVALID")
        path = root / "analysis_plans" / f"{clean}.json"
        if not path.exists():
            raise FileNotFoundError(clean)
        return json.loads(path.read_text(encoding="utf-8"))

    def validate_plan_rows(
        self,
        owner_id: str,
        project_id: str,
        plan_id: str,
        rows: list[dict[str, Any]],
        provenance: dict[str, Any],
    ) -> dict[str, Any]:
        plan = self.get_plan(owner_id, project_id, plan_id)
        dataset = self._dataset(owner_id, project_id, plan["dataset"]["dataset_id"])
        raw_rows_sha256 = canonical_rows_sha256(rows)
        if raw_rows_sha256 != dataset["checksum_sha256"]:
            raise ValueError("ANALYSIS_DATASET_CHECKSUM_MISMATCH")
        transformed_rows, transformation_receipts = apply_transformations(
            rows, plan["transformations"]
        )
        pre_filter_sha256 = transformed_rows_sha256(transformed_rows)
        filtered_rows, filter_receipt = apply_filters(
            transformed_rows,
            plan.get("row_filters", []),
            plan["analytical_variables"],
        )
        analytical_sha256 = transformed_rows_sha256(filtered_rows)
        payload = {
            "method": plan["method"],
            "parameters": plan["parameters"],
            "rows": filtered_rows,
            "provenance": {
                **provenance,
                "analysis_plan_id": plan_id,
                "registered_dataset_provenance": dataset["provenance"],
                "transformation_engine_version": plan["transformation_engine_version"],
                "transformation_receipts": transformation_receipts,
                "filter_engine_version": plan.get("filter_engine_version", FILTER_ENGINE_VERSION),
                "row_filter_receipt": filter_receipt,
            },
            "dataset_ref": {
                "dataset_id": dataset["dataset_id"],
                "raw_checksum_sha256": dataset["checksum_sha256"],
                "pre_filter_analytical_rows_sha256": pre_filter_sha256,
                "analytical_rows_sha256": analytical_sha256,
                "analysis_plan_id": plan_id,
            },
            "missing_policy": plan["missing_policy"],
        }
        validation = self.analysis.validate(owner_id, project_id, payload)
        return {
            "valid": True,
            "plan_id": plan_id,
            "dataset_id": dataset["dataset_id"],
            "dataset_checksum_sha256": dataset["checksum_sha256"],
            "submitted_raw_rows_sha256": raw_rows_sha256,
            "pre_filter_analytical_rows_sha256": pre_filter_sha256,
            "analytical_rows_sha256": analytical_sha256,
            "transformation_receipts": transformation_receipts,
            "row_filter_receipt": filter_receipt,
            "analysis_validation": validation,
        }

    def _notebook_receipt(
        self,
        owner_id: str,
        project_id: str,
        analysis_id: str,
        body: str,
        recorded_at: str,
        recorded_by: str,
    ) -> dict[str, Any]:
        root = self._project_root(owner_id, project_id)
        entry_id = f"analysis-{analysis_id}"
        latest_path = root / "notebook" / entry_id / "latest.json"
        if latest_path.exists():
            latest = json.loads(latest_path.read_text(encoding="utf-8"))
            revision_number = int(latest["revision_number"])
            revision_id = str(latest["revision_id"])
            candidates = sorted(
                (root / "notebook" / entry_id / "revisions").glob(
                    f"{revision_number:06d}-*.json"
                )
            )
            if len(candidates) != 1:
                raise ValueError("ANALYSIS_NOTEBOOK_RECEIPT_STATE_INVALID")
            existing = json.loads(candidates[0].read_text(encoding="utf-8"))
            if existing.get("revision_id") != revision_id:
                raise ValueError("ANALYSIS_NOTEBOOK_RECEIPT_STATE_INVALID")
            if existing.get("body") != body:
                raise ValueError("ANALYSIS_NOTEBOOK_RECEIPT_IMMUTABLE_CONFLICT")
            return {"created": False, "revision": existing}
        return self.research.revise_notebook(
            owner_id,
            project_id,
            entry_id,
            {"body": body, "authored_at": recorded_at, "author": recorded_by},
        )

    def execute_plan(
        self, owner_id: str, project_id: str, plan_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        rows = payload.get("rows")
        provenance = payload.get("provenance")
        recorded_at = " ".join(str(payload.get("recorded_at") or "").strip().split())
        recorded_by = " ".join(str(payload.get("recorded_by") or "").strip().split())
        if not isinstance(rows, list) or not rows:
            raise ValueError("ANALYSIS_ROWS_REQUIRED")
        if not isinstance(provenance, dict) or not provenance:
            raise ValueError("ANALYSIS_PROVENANCE_REQUIRED")
        if not recorded_at or not recorded_by:
            raise ValueError("ANALYSIS_NOTEBOOK_RECORD_FIELDS_REQUIRED")
        binding = self.validate_plan_rows(owner_id, project_id, plan_id, rows, provenance)
        analysis_payload = binding["analysis_validation"]["canonical_input"]
        executed = self.analysis.execute(owner_id, project_id, analysis_payload)
        analysis = executed["analysis"]
        receipt = {
            "schema_version": PLAN_SCHEMA_VERSION,
            "plan_id": plan_id,
            "analysis_id": analysis["analysis_id"],
            "dataset_id": binding["dataset_id"],
            "raw_dataset_checksum_sha256": binding["dataset_checksum_sha256"],
            "pre_filter_analytical_rows_sha256": binding["pre_filter_analytical_rows_sha256"],
            "analytical_rows_sha256": binding["analytical_rows_sha256"],
            "transformation_engine_version": TRANSFORMATION_ENGINE_VERSION,
            "transformation_receipts": binding["transformation_receipts"],
            "filter_engine_version": FILTER_ENGINE_VERSION,
            "row_filter_receipt": binding["row_filter_receipt"],
            "input_sha256": analysis["input_sha256"],
            "result_sha256": analysis["result_sha256"],
            "method": analysis["method"],
            "method_version": analysis["method_version"],
            "warnings": analysis["warnings"],
            "computed_output": True,
            "interpretation_generated": False,
            "human_review_required_for_scientific_conclusion": True,
            "scientific_publication_authorized": False,
        }
        receipt_sha256 = _sha(receipt)
        root = self._project_root(owner_id, project_id)
        receipt_path = root / "analysis_receipts" / f"{analysis['analysis_id']}.json"
        persisted_receipt = {**receipt, "receipt_sha256": receipt_sha256}
        if receipt_path.exists():
            existing = json.loads(receipt_path.read_text(encoding="utf-8"))
            if existing != persisted_receipt:
                raise ValueError("ANALYSIS_RECEIPT_IMMUTABLE_CONFLICT")
        else:
            _atomic(receipt_path, persisted_receipt)
        notebook_body = _stable(
            {
                "record_type": "scientific_analysis_receipt",
                **persisted_receipt,
                "note": "Computed analysis receipt only; no scientific interpretation or publication authority.",
            }
        )
        notebook = self._notebook_receipt(
            owner_id,
            project_id,
            analysis["analysis_id"],
            notebook_body,
            recorded_at,
            recorded_by,
        )
        return {
            "analysis": analysis,
            "analysis_created": executed["created"],
            "receipt": persisted_receipt,
            "notebook": notebook,
        }

    def readiness(self, owner_id: str, project_id: str) -> dict[str, Any]:
        root = self._project_root(owner_id, project_id)
        plans_dir = root / "analysis_plans"
        receipts_dir = root / "analysis_receipts"
        plans = list(plans_dir.glob("analysis-plan-*.json")) if plans_dir.exists() else []
        receipts = list(receipts_dir.glob("analysis-*.json")) if receipts_dir.exists() else []
        return {
            "schema_version": PLAN_SCHEMA_VERSION,
            "project_id": project_id,
            "analysis_plan_count": len(plans),
            "analysis_receipt_count": len(receipts),
            "registered_dataset_binding_required": True,
            "exact_raw_dataset_checksum_required": True,
            "derived_variable_units_required": True,
            "transformation_engine_version": TRANSFORMATION_ENGINE_VERSION,
            "governed_transform_execution_enabled": True,
            "filter_engine_version": FILTER_ENGINE_VERSION,
            "governed_row_filter_execution_enabled": True,
            "freeform_filter_expression_allowed": False,
            "implicit_outlier_removal_allowed": False,
            "excluded_row_identity_required": True,
            "filter_reason_code_required": True,
            "notebook_receipt_enabled": True,
            "silent_method_selection_allowed": False,
            "scientific_interpretation_generated": False,
            "scientific_publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
        }

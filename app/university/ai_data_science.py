from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from runtime.research_analysis_workflow import (
    FILTER_ENGINE_VERSION,
    PLAN_SCHEMA_VERSION,
    TRANSFORMATION_ENGINE_VERSION,
    ResearchAnalysisWorkflowService,
    canonical_rows_sha256,
)
from runtime.research_station import ResearchStationService
from runtime.scientific_analysis import (
    ANALYSIS_SCHEMA_VERSION,
    METHOD_REGISTRY,
    ScientificAnalysisService,
)
from runtime.scientific_dataset_snapshots import ScientificDatasetSnapshotService
from runtime.scientific_diagnostics import (
    DIAGNOSTICS_SCHEMA_VERSION,
    ScientificDiagnosticsService,
)

PROGRAM_ID = "OC-AI-DS-001"
MODULE_ID = "OC-AI-DS-STAT-EDA-001"
MODULE_VERSION = "1.0.0"
LAB_SCHEMA_VERSION = "orchid-continuum-university-ai-data-science/v1"
DATASET_VIEW_SCHEMA_VERSION = "orchid-continuum-occurrence-elevation-view/v1"
PROMOTION_SCHEMA_VERSION = "orchid-continuum-research-promotion/v1"
MAX_EDUCATIONAL_ROWS = 1000

_EXACT_LOCATION_KEYS = frozenset(
    {
        "latitude",
        "longitude",
        "lat",
        "lon",
        "lng",
        "decimal_latitude",
        "decimal_longitude",
        "coordinates",
        "coordinate",
        "geometry",
        "geom",
        "geopoint",
        "locality",
        "exact_locality",
        "site",
        "site_name",
        "address",
        "landowner",
        "property_name",
        "location_notes",
    }
)
_ELEVATION_KEYS = (
    "elevation_m",
    "elevation",
    "elevation_in_meters",
    "minimum_elevation_in_meters",
    "verbatim_elevation_m",
)
_RECORD_ID_KEYS = (
    "occurrence_id",
    "occurrenceid",
    "record_id",
    "id",
    "gbif_id",
    "inat_id",
    "catalog_number",
)
_NAME_KEYS = ("scientific_name", "scientificname", "accepted_name", "name")
_TAXON_ID_KEYS = ("taxon_id", "taxonid", "canonical_taxon_id")
_COUNTRY_KEYS = ("country_code", "countrycode", "country")
_STATE_KEYS = ("state_province", "stateprovince", "state", "province", "region")
_SOURCE_KEYS = ("source", "source_name", "dataset", "provider")
_LICENSE_KEYS = ("license", "rights", "rights_holder")
_BASIS_KEYS = ("basis_of_record", "basisofrecord")
_YEAR_KEYS = ("year", "event_year", "observation_year")
_MONTH_KEYS = ("month", "event_month", "observation_month")


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


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _first(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    normalized = {str(key).casefold(): value for key, value in row.items()}
    for key in keys:
        if key.casefold() in normalized:
            return normalized[key.casefold()]
    return None


def _finite_float(value: Any, *, code: str) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise TypeError(code)
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(code) from exc
    if not math.isfinite(number):
        raise ValueError(code)
    return number


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise TypeError("OC_AI_DS_INTEGER_INVALID")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("OC_AI_DS_INTEGER_INVALID") from exc
    return number


def _redact_locality(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _redact_locality(item)
            for key, item in value.items()
            if str(key).casefold() not in _EXACT_LOCATION_KEYS
        }
    if isinstance(value, list):
        return [_redact_locality(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_locality(item) for item in value]
    return value


def _counter_dict(values: list[str | None]) -> dict[str, int]:
    counts = Counter(value for value in values if value)
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


class AppliedAIDataScienceService:
    def __init__(self, research: ResearchStationService | None = None) -> None:
        self.research = research or ResearchStationService()
        self.analysis = ScientificAnalysisService(self.research)
        self.workflow = ResearchAnalysisWorkflowService(self.research, self.analysis)
        self.snapshots = ScientificDatasetSnapshotService(self.workflow)
        self.diagnostics = ScientificDiagnosticsService(self.workflow)

    @staticmethod
    def module() -> dict[str, Any]:
        return {
            "schema_version": LAB_SCHEMA_VERSION,
            "program_id": PROGRAM_ID,
            "module_id": MODULE_ID,
            "module_version": MODULE_VERSION,
            "title": "Exploratory Orchid Data Science: Occurrence and Elevation",
            "status": "executable_vertical_slice",
            "summary": (
                "A guided statistics and exploratory-data-analysis laboratory using a "
                "bounded, locality-safe Orchid Continuum occurrence and elevation view."
            ),
            "progression": ["LEARN", "APPLY", "RESEARCH"],
            "learning_objectives": [
                "Distinguish missing elevation from a measured elevation of zero.",
                "Describe the distribution and missingness of orchid elevation records.",
                "Inspect source and geographic concentration as potential sampling-bias signals.",
                "Interpret descriptive output without converting correlation or coverage into causation or biological absence.",
                "Preserve dataset identity, analysis parameters, provenance, and review state when continuing into Research Station.",
            ],
            "prerequisites": [
                "Basic familiarity with tables, variables, and descriptive statistics.",
                "Understanding that occurrence records are observations of collection/reporting, not a complete census of biological presence.",
            ],
            "scientific_cautions": [
                "Missing or unavailable data are not biological absence and are never encoded as measured zero.",
                "Occurrence density reflects sampling effort as well as biological distribution.",
                "Elevation coverage may differ among sources, taxa, regions, and time periods.",
                "The first executable slice is descriptive and does not authorize causal or taxonomic conclusions.",
            ],
            "dataset_contract": {
                "schema_version": DATASET_VIEW_SCHEMA_VERSION,
                "maximum_rows": MAX_EDUCATIONAL_ROWS,
                "exact_coordinates_in_educational_view": False,
                "exact_locality_in_educational_view": False,
                "generalized_geography": ["country_code", "state_province"],
                "missing_numeric_value": None,
                "measured_zero_preserved": True,
                "private_snapshot_required_for_execution": True,
            },
            "analysis_contract": {
                "method": "describe.v1",
                "method_version": METHOD_REGISTRY["describe.v1"]["version"],
                "arbitrary_code_execution": False,
                "deterministic_replay_required": True,
                "scientific_interpretation_generated_by_engine": False,
            },
            "calyx_tutor_contract": {
                "modes": ["beginner", "research"],
                "model_call_required_for_lab_execution": False,
                "generated_explanation_is_evidence": False,
                "must_preserve_source_evidence_distinction": True,
            },
            "research_station_contract": {
                "handoff": "by_reference",
                "copy_dataset_on_promotion": False,
                "human_review_required": True,
                "scientific_publication_authorized": False,
                "candidate_knowledge_promotion_authorized": False,
                "knowledge_graph_mutation_authorized": False,
                "taxonomy_mutation_authorized": False,
            },
        }

    @staticmethod
    def _safe_row(raw: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise TypeError("OC_AI_DS_OCCURRENCE_ROW_OBJECT_REQUIRED")
        redacted = _redact_locality(raw)
        record_id = _text(_first(redacted, _RECORD_ID_KEYS))
        source = _text(_first(redacted, _SOURCE_KEYS)) or "unknown"
        scientific_name = _text(_first(redacted, _NAME_KEYS)) or None
        taxon_id = _text(_first(redacted, _TAXON_ID_KEYS)) or None
        country = _text(_first(redacted, _COUNTRY_KEYS)) or None
        state = _text(_first(redacted, _STATE_KEYS)) or None
        license_value = _text(_first(redacted, _LICENSE_KEYS)) or None
        basis = _text(_first(redacted, _BASIS_KEYS)) or None
        year = _int_or_none(_first(redacted, _YEAR_KEYS))
        month = _int_or_none(_first(redacted, _MONTH_KEYS))
        elevation = _finite_float(
            _first(redacted, _ELEVATION_KEYS), code="OC_AI_DS_ELEVATION_INVALID"
        )
        identity_source = record_id or _sha(redacted)
        record_key = f"occ-{_sha({'source': source, 'record': identity_source})[:20]}"
        return {
            "record_key": record_key,
            "taxon_id": taxon_id,
            "scientific_name": scientific_name,
            "country_code": country,
            "state_province": state,
            "year": year,
            "month": month,
            "elevation_m": elevation,
            "source": source,
            "license": license_value,
            "basis_of_record": basis,
            "sensitive_locality_masked": True,
        }

    @staticmethod
    def _quality(rows: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(rows)
        elevations = [row["elevation_m"] for row in rows]
        complete_elevations = [value for value in elevations if value is not None]
        missing_elevation = total - len(complete_elevations)
        measured_zero = sum(value == 0 for value in complete_elevations)
        years = [row["year"] for row in rows if row["year"] is not None]
        countries = [row["country_code"] for row in rows]
        sources = [row["source"] for row in rows]
        country_counts = _counter_dict(countries)
        source_counts = _counter_dict(sources)
        warnings: list[str] = []
        missing_fraction = missing_elevation / total
        if missing_fraction >= 0.30:
            warnings.append(
                "At least 30% of records lack elevation; elevation summaries describe only records with reported values."
            )
        if country_counts and max(country_counts.values()) / total >= 0.75:
            warnings.append(
                "At least 75% of rows come from one country or country-code group; geographic concentration may affect interpretation."
            )
        if source_counts and max(source_counts.values()) / total >= 0.80:
            warnings.append(
                "At least 80% of rows come from one source; source-specific collection or reporting practices may dominate the view."
            )
        if len(years) >= 2 and max(years) - min(years) < 5:
            warnings.append(
                "The dated records span fewer than five years; they may not represent longer-term temporal variation."
            )
        if not warnings:
            warnings.append(
                "No threshold-based concentration warning was triggered; this does not establish representative sampling."
            )
        return {
            "row_count": total,
            "elevation": {
                "complete": len(complete_elevations),
                "missing": missing_elevation,
                "missing_fraction": missing_fraction,
                "measured_zero_count": measured_zero,
                "zero_is_not_used_for_missing": True,
            },
            "year": {
                "complete": len(years),
                "missing": total - len(years),
                "minimum": min(years) if years else None,
                "maximum": max(years) if years else None,
            },
            "records_by_country": country_counts,
            "records_by_source": source_counts,
            "warnings": warnings,
            "diagnostics_are_descriptive_not_biological_conclusions": True,
            "sampling_effort_not_controlled": True,
        }

    def build_dataset_view(
        self,
        rows: Any,
        provenance: Any,
        selection: Any = None,
    ) -> dict[str, Any]:
        if not isinstance(rows, list) or not rows:
            raise ValueError("OC_AI_DS_OCCURRENCE_ROWS_REQUIRED")
        if len(rows) > MAX_EDUCATIONAL_ROWS:
            raise ValueError("OC_AI_DS_EDUCATIONAL_ROW_LIMIT_EXCEEDED")
        if not isinstance(provenance, dict) or not provenance:
            raise ValueError("OC_AI_DS_PROVENANCE_REQUIRED")
        if selection is None:
            selection = {}
        if not isinstance(selection, dict):
            raise TypeError("OC_AI_DS_SELECTION_INVALID")
        safe_rows = [self._safe_row(row) for row in rows]
        if not any(row["scientific_name"] for row in safe_rows):
            raise ValueError("OC_AI_DS_TAXON_IDENTITY_REQUIRED")
        quality = self._quality(safe_rows)
        if quality["elevation"]["complete"] < 2:
            raise ValueError("OC_AI_DS_REQUIRES_TWO_ELEVATION_VALUES")
        redacted_provenance = _redact_locality(provenance)
        redacted_selection = _redact_locality(selection)
        rows_sha256 = canonical_rows_sha256(safe_rows)
        return {
            "schema_version": DATASET_VIEW_SCHEMA_VERSION,
            "dataset_view_id": f"occurrence-elevation-view-{rows_sha256[:24]}",
            "rows_sha256": rows_sha256,
            "rows": safe_rows,
            "row_count": len(safe_rows),
            "columns": [
                "record_key",
                "taxon_id",
                "scientific_name",
                "country_code",
                "state_province",
                "year",
                "month",
                "elevation_m",
                "source",
                "license",
                "basis_of_record",
                "sensitive_locality_masked",
            ],
            "selection": redacted_selection,
            "provenance": redacted_provenance,
            "quality": quality,
            "exact_coordinates_in_view": False,
            "exact_locality_in_view": False,
            "locality_generalization": "country/state-province only",
            "missing_numeric_values_are_null": True,
            "measured_zero_preserved": True,
            "private_execution_snapshot": True,
            "biological_absence_inferred_from_missing_data": False,
        }

    def _project_id(self, question: str, dataset_sha256: str) -> str:
        identity = _sha(
            {
                "program_id": PROGRAM_ID,
                "module_id": MODULE_ID,
                "question": question,
                "dataset_sha256": dataset_sha256,
            }
        )
        return f"ocu-ai-ds-{identity[:20]}"

    def _manifest_path(self, owner_id: str, project_id: str, manifest_id: str) -> Path:
        root = self.workflow._project_root(owner_id, project_id)
        clean = _text(manifest_id)
        if not clean or any(token in clean for token in ("/", "\\", "..")):
            raise ValueError("OC_AI_DS_MANIFEST_ID_INVALID")
        return root / "learning_lab_manifests" / f"{clean}.json"

    def _promotion_path(self, owner_id: str, project_id: str, promotion_id: str) -> Path:
        root = self.workflow._project_root(owner_id, project_id)
        clean = _text(promotion_id)
        if not clean or any(token in clean for token in ("/", "\\", "..")):
            raise ValueError("OC_AI_DS_PROMOTION_ID_INVALID")
        return root / "research_promotions" / f"{clean}.json"

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(path.stem)
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _persist_immutable(path: Path, record: dict[str, Any], conflict_code: str) -> bool:
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != record:
                raise ValueError(conflict_code)
            return False
        _atomic(path, record)
        return True

    def prepare(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        owner = _text(owner_id)
        recorded_at = _text(payload.get("recorded_at"))
        if not owner or not recorded_at:
            raise ValueError("OC_AI_DS_OWNER_AND_TIMESTAMP_REQUIRED")
        module = self.module()
        question = _text(payload.get("question")) or (
            "What do these bounded Orchid Continuum occurrence records show about reported elevation coverage and missingness?"
        )
        rationale = _text(payload.get("rationale")) or (
            "Begin with descriptive statistics and sampling-quality diagnostics before making any biological interpretation."
        )
        view = self.build_dataset_view(
            payload.get("rows"), payload.get("provenance"), payload.get("selection")
        )
        project_id = _text(payload.get("project_id")) or self._project_id(
            question, view["rows_sha256"]
        )
        try:
            self.research._project(owner, project_id)
        except FileNotFoundError:
            self.research.create_project(
                owner,
                {
                    "project_id": project_id,
                    "title": module["title"],
                    "objective": question,
                    "state": "active",
                    "created_at": recorded_at,
                },
            )

        manifest_identity = {
            "program_id": PROGRAM_ID,
            "module_id": MODULE_ID,
            "module_version": MODULE_VERSION,
            "project_id": project_id,
            "question": question,
            "dataset_sha256": view["rows_sha256"],
            "method": "describe.v1",
            "method_version": METHOD_REGISTRY["describe.v1"]["version"],
        }
        manifest_id = f"lab-manifest-{_sha(manifest_identity)[:24]}"
        manifest_path = self._manifest_path(owner, project_id, manifest_id)
        if manifest_path.exists():
            return {
                "created": False,
                "module": module,
                "dataset_view": view,
                "lab_manifest": self._read(manifest_path),
            }

        question_record = self.research.add_question(
            owner,
            project_id,
            {"text": question, "rationale": rationale},
        )["question"]
        dataset_id = f"dataset-ocu-occ-elev-{view['rows_sha256'][:20]}"
        dataset_provenance = {
            "program_id": PROGRAM_ID,
            "module_id": MODULE_ID,
            "dataset_view_schema_version": DATASET_VIEW_SCHEMA_VERSION,
            "source_provenance": view["provenance"],
            "selection": view["selection"],
            "exact_locality_disclosed": False,
            "educational_view_only": True,
        }
        dataset_record = self.research.add_dataset(
            owner,
            project_id,
            {
                "dataset_id": dataset_id,
                "title": "Bounded locality-safe orchid occurrence and elevation view",
                "checksum_sha256": view["rows_sha256"],
                "schema_ref": DATASET_VIEW_SCHEMA_VERSION,
                "provenance": dataset_provenance,
            },
        )["dataset"]
        snapshot = self.snapshots.put(
            owner,
            project_id,
            dataset_id,
            {
                "rows": view["rows"],
                "provenance": {
                    "program_id": PROGRAM_ID,
                    "module_id": MODULE_ID,
                    "dataset_view_id": view["dataset_view_id"],
                    "locality_safe": True,
                },
                "recorded_by": owner,
                "recorded_at": recorded_at,
            },
        )["snapshot"]
        describe_columns = ["elevation_m"]
        if view["quality"]["year"]["complete"] >= 2:
            describe_columns.append("year")
        variables = [
            {
                "name": "elevation_m",
                "kind": "numeric",
                "unit": "m",
                "role": "context",
            }
        ]
        if "year" in describe_columns:
            variables.append(
                {
                    "name": "year",
                    "kind": "numeric",
                    "unit": "year",
                    "role": "context",
                }
            )
        plan = self.workflow.create_plan(
            owner,
            project_id,
            {
                "question": question,
                "rationale": rationale,
                "dataset_id": dataset_id,
                "variables": variables,
                "method": "describe.v1",
                "parameters": {"columns": describe_columns},
                "missing_policy": "complete_case",
                "transformations": [],
                "row_filters": [],
                "exclusions": [],
                "created_by": owner,
                "created_at": recorded_at,
            },
        )["plan"]
        manifest_core = {
            "schema_version": LAB_SCHEMA_VERSION,
            "program_id": PROGRAM_ID,
            "module_id": MODULE_ID,
            "module_version": MODULE_VERSION,
            "lab_manifest_id": manifest_id,
            "project_id": project_id,
            "question_id": question_record["question_id"],
            "question": question,
            "rationale": rationale,
            "dataset": {
                "dataset_id": dataset_record["dataset_id"],
                "dataset_view_id": view["dataset_view_id"],
                "schema_ref": dataset_record["schema_ref"],
                "rows_sha256": view["rows_sha256"],
                "row_count": view["row_count"],
                "columns": view["columns"],
                "selection": view["selection"],
                "provenance": dataset_record["provenance"],
                "quality": view["quality"],
                "exact_coordinates_disclosed": False,
                "exact_locality_disclosed": False,
                "missing_numeric_values_are_null": True,
            },
            "private_snapshot": {
                "schema_version": snapshot["schema_version"],
                "dataset_id": snapshot["dataset_id"],
                "rows_sha256": snapshot["rows_sha256"],
                "row_count": snapshot["row_count"],
                "private": True,
            },
            "analysis_plan": plan,
            "execution": {
                "scientific_analysis_schema_version": ANALYSIS_SCHEMA_VERSION,
                "analysis_plan_schema_version": PLAN_SCHEMA_VERSION,
                "transformation_engine_version": TRANSFORMATION_ENGINE_VERSION,
                "filter_engine_version": FILTER_ENGINE_VERSION,
                "diagnostics_schema_version": DIAGNOSTICS_SCHEMA_VERSION,
                "method": "describe.v1",
                "method_version": METHOD_REGISTRY["describe.v1"]["version"],
                "implementation": "orchid-continuum-scientific-computing",
                "python_implementation": platform.python_implementation(),
                "python_version": platform.python_version(),
                "randomness_used": False,
                "random_seed": 0,
                "arbitrary_code_execution": False,
                "deterministic_replay_required": True,
            },
            "review_state": "unreviewed_educational_analysis",
            "generated_explanation_is_evidence": False,
            "scientific_publication_authorized": False,
            "candidate_knowledge_promotion_authorized": False,
            "knowledge_graph_mutation_authorized": False,
            "taxonomy_mutation_authorized": False,
            "recorded_at": recorded_at,
        }
        manifest = {**manifest_core, "manifest_sha256": _sha(manifest_core)}
        self._persist_immutable(
            manifest_path, manifest, "OC_AI_DS_MANIFEST_IMMUTABLE_CONFLICT"
        )
        return {
            "created": True,
            "module": module,
            "dataset_view": view,
            "lab_manifest": manifest,
        }

    def get_manifest(
        self, owner_id: str, project_id: str, manifest_id: str
    ) -> dict[str, Any]:
        return self._read(self._manifest_path(owner_id, project_id, manifest_id))

    @staticmethod
    def _assessment() -> dict[str, Any]:
        return {
            "schema_version": "orchid-continuum-university-assessment/v1",
            "assessment_type": "reflection_and_interpretation",
            "graded_automatically": False,
            "prompts": [
                {
                    "id": "missingness",
                    "prompt": "How could missing elevation values change what you can defensibly say about this dataset?",
                    "checks": ["mentions missingness", "avoids treating missing as zero or absence"],
                },
                {
                    "id": "sampling_bias",
                    "prompt": "Which source or geographic concentration in the diagnostics could indicate sampling bias, and why?",
                    "checks": ["uses a displayed diagnostic", "does not equate sampling concentration with biological distribution"],
                },
                {
                    "id": "interpretation",
                    "prompt": "State one conclusion supported by the descriptive output and one conclusion it does not support.",
                    "checks": ["separates description from causation", "states a limitation"],
                },
                {
                    "id": "next_question",
                    "prompt": "What additional evidence or analysis would you seek before making a biological claim about elevation?",
                    "checks": ["identifies additional evidence", "proposes a testable next step"],
                },
            ],
            "rubric": {
                "focus": [
                    "data quality",
                    "method appropriateness",
                    "evidence versus inference",
                    "uncertainty",
                    "reproducible next step",
                ],
                "coding_syntax_is_primary_target": False,
            },
        }

    def execute(
        self,
        owner_id: str,
        project_id: str,
        manifest_id: str,
        recorded_at: str,
    ) -> dict[str, Any]:
        owner = _text(owner_id)
        timestamp = _text(recorded_at)
        if not owner or not timestamp:
            raise ValueError("OC_AI_DS_OWNER_AND_TIMESTAMP_REQUIRED")
        manifest = self.get_manifest(owner, project_id, manifest_id)
        if manifest.get("program_id") != PROGRAM_ID or manifest.get("module_id") != MODULE_ID:
            raise ValueError("OC_AI_DS_MANIFEST_MODULE_MISMATCH")
        dataset_id = manifest["dataset"]["dataset_id"]
        snapshot = self.snapshots.get(owner, project_id, dataset_id, include_rows=True)
        if snapshot["rows_sha256"] != manifest["dataset"]["rows_sha256"]:
            raise ValueError("OC_AI_DS_SNAPSHOT_MANIFEST_DRIFT")
        if canonical_rows_sha256(snapshot["rows"]) != manifest["dataset"]["rows_sha256"]:
            raise ValueError("OC_AI_DS_SNAPSHOT_CONTENT_DRIFT")
        plan_id = manifest["analysis_plan"]["plan_id"]
        provenance = {
            "program_id": PROGRAM_ID,
            "module_id": MODULE_ID,
            "lab_manifest_id": manifest_id,
            "lab_manifest_sha256": manifest["manifest_sha256"],
            "dataset_id": dataset_id,
            "dataset_rows_sha256": manifest["dataset"]["rows_sha256"],
            "source_provenance": manifest["dataset"]["provenance"],
            "generated_explanation_is_evidence": False,
        }
        execution_payload = {
            "rows": snapshot["rows"],
            "provenance": provenance,
            "recorded_at": timestamp,
            "recorded_by": owner,
        }
        first = self.workflow.execute_plan(owner, project_id, plan_id, execution_payload)
        second = self.workflow.execute_plan(owner, project_id, plan_id, execution_payload)
        first_analysis = first["analysis"]
        second_analysis = second["analysis"]
        replay_fields = (
            first_analysis["analysis_id"] == second_analysis["analysis_id"],
            first_analysis["input_sha256"] == second_analysis["input_sha256"],
            first_analysis["result_sha256"] == second_analysis["result_sha256"],
            first["receipt"]["receipt_sha256"] == second["receipt"]["receipt_sha256"],
        )
        if not all(replay_fields):
            raise ValueError("OC_AI_DS_DETERMINISTIC_REPLAY_FAILED")
        diagnostic = self.diagnostics.build(
            owner,
            project_id,
            plan_id,
            first_analysis["analysis_id"],
            snapshot["rows"],
            provenance,
        )["diagnostic"]
        promotion_core = {
            "schema_version": PROMOTION_SCHEMA_VERSION,
            "program_id": PROGRAM_ID,
            "module_id": MODULE_ID,
            "project_id": project_id,
            "question": manifest["question"],
            "handoff": "by_reference",
            "dataset": {
                "dataset_id": dataset_id,
                "rows_sha256": manifest["dataset"]["rows_sha256"],
                "schema_ref": manifest["dataset"]["schema_ref"],
                "provenance": manifest["dataset"]["provenance"],
            },
            "lab_manifest": {
                "lab_manifest_id": manifest_id,
                "manifest_sha256": manifest["manifest_sha256"],
            },
            "analysis_plan": {
                "plan_id": plan_id,
                "method": first_analysis["method"],
                "method_version": first_analysis["method_version"],
            },
            "analysis_result": {
                "analysis_id": first_analysis["analysis_id"],
                "input_sha256": first_analysis["input_sha256"],
                "result_sha256": first_analysis["result_sha256"],
                "receipt_sha256": first["receipt"]["receipt_sha256"],
                "diagnostic_id": diagnostic["diagnostic_id"],
                "diagnostics_sha256": diagnostic["diagnostics_sha256"],
            },
            "review_state": "unreviewed_educational_analysis",
            "human_review_required": True,
            "generated_explanation_is_evidence": False,
            "scientific_publication_authorized": False,
            "candidate_knowledge_promotion_authorized": False,
            "knowledge_graph_mutation_authorized": False,
            "taxonomy_mutation_authorized": False,
        }
        promotion_sha = _sha(promotion_core)
        promotion = {
            **promotion_core,
            "promotion_id": f"research-promotion-{promotion_sha[:24]}",
            "promotion_sha256": promotion_sha,
        }
        self._persist_immutable(
            self._promotion_path(owner, project_id, promotion["promotion_id"]),
            promotion,
            "OC_AI_DS_PROMOTION_IMMUTABLE_CONFLICT",
        )
        calyx_context = {
            "schema_version": "orchid-continuum-calyx-learning-context/v1",
            "program_id": PROGRAM_ID,
            "module_id": MODULE_ID,
            "mode_options": ["beginner", "research"],
            "question": manifest["question"],
            "quality_diagnostics": manifest["dataset"]["quality"],
            "analysis": {
                "analysis_id": first_analysis["analysis_id"],
                "method": first_analysis["method"],
                "result": first_analysis["result"],
                "assumptions": first_analysis["assumptions"],
                "warnings": first_analysis["warnings"],
            },
            "evidence_refs": {
                "dataset_id": dataset_id,
                "dataset_rows_sha256": manifest["dataset"]["rows_sha256"],
                "analysis_result_sha256": first_analysis["result_sha256"],
                "lab_manifest_sha256": manifest["manifest_sha256"],
            },
            "is_evidence": False,
            "generated_explanation_is_evidence": False,
            "model_call_performed": False,
            "instruction": (
                "Explain the computed output at the requested depth, identify assumptions and limitations, "
                "and keep generated explanation separate from source evidence."
            ),
        }
        return {
            "schema_version": LAB_SCHEMA_VERSION,
            "program_id": PROGRAM_ID,
            "module_id": MODULE_ID,
            "project_id": project_id,
            "lab_manifest_id": manifest_id,
            "lab_manifest_sha256": manifest["manifest_sha256"],
            "result_table": first_analysis["result"],
            "visualization_payload": diagnostic["diagnostics"],
            "quality_diagnostics": manifest["dataset"]["quality"],
            "assumptions": first_analysis["assumptions"],
            "warnings": first_analysis["warnings"],
            "provenance": provenance,
            "calyx_context": calyx_context,
            "assessment": self._assessment(),
            "research_promotion_packet": promotion,
            "replay_proof": {
                "verified": True,
                "analysis_id": first_analysis["analysis_id"],
                "input_sha256": first_analysis["input_sha256"],
                "result_sha256": first_analysis["result_sha256"],
                "receipt_sha256": first["receipt"]["receipt_sha256"],
                "first_execution_created_analysis": first["analysis_created"],
                "second_execution_reused_analysis": not second["analysis_created"],
            },
            "scientific_interpretation_generated": False,
            "scientific_publication_authorized": False,
            "candidate_knowledge_promotion_authorized": False,
            "knowledge_graph_mutation_authorized": False,
            "taxonomy_mutation_authorized": False,
        }

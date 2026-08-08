"""Read-only project-scoped discovery of immutable CALYX scientific analyses."""
from __future__ import annotations

import json
from typing import Any

from runtime.scientific_analysis import (
    ANALYSIS_SCHEMA_VERSION,
    ScientificAnalysisService,
)

ANALYSIS_HISTORY_SCHEMA_VERSION = "calyx-scientific-analysis-history/v1"
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class ScientificAnalysisHistoryService:
    def __init__(self, analysis: ScientificAnalysisService | None = None) -> None:
        self.analysis = analysis or ScientificAnalysisService()

    @staticmethod
    def _page_value(value: Any, *, default: int, maximum: int | None = None) -> int:
        if isinstance(value, bool):
            raise TypeError("ANALYSIS_HISTORY_PAGINATION_INVALID")
        try:
            normalized = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("ANALYSIS_HISTORY_PAGINATION_INVALID") from exc
        if normalized < 0 or (maximum is not None and normalized > maximum):
            raise ValueError("ANALYSIS_HISTORY_PAGINATION_INVALID")
        return normalized if value is not None else default

    @staticmethod
    def _summary(record: dict[str, Any], project_id: str) -> dict[str, Any]:
        if record.get("schema_version") != ANALYSIS_SCHEMA_VERSION:
            raise ValueError("ANALYSIS_HISTORY_SCHEMA_UNSUPPORTED")
        if record.get("project_id") != project_id:
            raise ValueError("ANALYSIS_HISTORY_PROJECT_SCOPE_MISMATCH")
        analysis_id = str(record.get("analysis_id") or "").strip()
        method = str(record.get("method") or "").strip()
        if not analysis_id or not method:
            raise ValueError("ANALYSIS_HISTORY_RECORD_INVALID")
        return {
            "analysis_id": analysis_id,
            "method": method,
            "method_name": record.get("method_name"),
            "method_version": record.get("method_version"),
            "parameters": record.get("parameters") or {},
            "rows_received": record.get("rows_received"),
            "rows_or_values_dropped_for_missingness": record.get(
                "rows_or_values_dropped_for_missingness"
            ),
            "input_sha256": record.get("input_sha256"),
            "result_sha256": record.get("result_sha256"),
            "dataset_ref": record.get("dataset_ref"),
            "warnings": list(record.get("warnings") or []),
            "computed_output": record.get("computed_output") is True,
            "interpretation_generated": False,
            "human_review_required_for_scientific_conclusion": True,
            "scientific_publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
        }

    def list(
        self,
        owner_id: str,
        project_id: str,
        *,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> dict[str, Any]:
        normalized_limit = self._page_value(limit, default=DEFAULT_LIMIT, maximum=MAX_LIMIT)
        if normalized_limit == 0:
            raise ValueError("ANALYSIS_HISTORY_PAGINATION_INVALID")
        normalized_offset = self._page_value(offset, default=0)

        root = self.analysis._project_root(owner_id, project_id)
        analyses_dir = root / "analyses"
        paths = sorted(analyses_dir.glob("analysis-*.json")) if analyses_dir.exists() else []
        summaries = [
            self._summary(json.loads(path.read_text(encoding="utf-8")), project_id)
            for path in paths
        ]
        page = summaries[normalized_offset : normalized_offset + normalized_limit]
        return {
            "schema_version": ANALYSIS_HISTORY_SCHEMA_VERSION,
            "project_id": project_id,
            "items": page,
            "total": len(summaries),
            "limit": normalized_limit,
            "offset": normalized_offset,
            "ordering": "analysis_id_ascending_not_chronological",
            "chronology_inferred": False,
            "results_included": False,
            "immutable_records_only": True,
            "deletion_authorized": False,
            "mutation_authorized": False,
            "preferred_analysis": None,
            "scientific_superiority_determined": False,
            "scientific_interpretation_generated": False,
        }

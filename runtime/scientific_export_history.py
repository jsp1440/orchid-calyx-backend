"""Read-only discovery of immutable private scientific-analysis export identities."""
from __future__ import annotations

import json
from typing import Any

from runtime.scientific_export_bundle import ScientificAnalysisExportService

EXPORT_HISTORY_SCHEMA_VERSION = "calyx-scientific-analysis-export-history/v1"
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class ScientificAnalysisExportHistoryService:
    def __init__(self, exports: ScientificAnalysisExportService | None = None) -> None:
        self.exports = exports or ScientificAnalysisExportService()

    @staticmethod
    def _page_value(value: Any, *, default: int, maximum: int | None = None) -> int:
        if value is None:
            return default
        if isinstance(value, bool):
            raise TypeError("ANALYSIS_EXPORT_HISTORY_PAGINATION_INVALID")
        try:
            normalized = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("ANALYSIS_EXPORT_HISTORY_PAGINATION_INVALID") from exc
        if normalized < 0 or (maximum is not None and normalized > maximum):
            raise ValueError("ANALYSIS_EXPORT_HISTORY_PAGINATION_INVALID")
        return normalized

    @staticmethod
    def _analysis_filter(value: str | None) -> str | None:
        if value is None:
            return None
        clean = str(value).strip()
        if not clean or any(token in clean for token in ("/", "\\", "..")):
            raise ValueError("ANALYSIS_EXPORT_HISTORY_ANALYSIS_ID_INVALID")
        return clean

    @staticmethod
    def _summary(bundle: dict[str, Any]) -> dict[str, Any]:
        return {
            "export_id": bundle["export_id"],
            "export_sha256": bundle["export_sha256"],
            "analysis_id": bundle["analysis_id"],
            "profile": bundle["profile"],
            "component_presence": dict(bundle.get("component_presence") or {}),
            "numerical_environment_present": isinstance(bundle.get("numerical_environment"), dict),
            "raw_dataset_rows_included": False,
            "diagnostic_payload_included": False,
            "private_research_artifact": True,
            "export_is_not_publication": True,
            "scientific_publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
            "integrity_verified": True,
            "integrity_verification_is_not_publication_authority": True,
        }

    def list(
        self,
        owner_id: str,
        project_id: str,
        *,
        analysis_id: str | None = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> dict[str, Any]:
        normalized_limit = self._page_value(limit, default=DEFAULT_LIMIT, maximum=MAX_LIMIT)
        if normalized_limit == 0:
            raise ValueError("ANALYSIS_EXPORT_HISTORY_PAGINATION_INVALID")
        normalized_offset = self._page_value(offset, default=0)
        normalized_analysis_id = self._analysis_filter(analysis_id)

        root = self.exports._root(owner_id, project_id)
        exports_dir = root / "analysis_exports"
        paths = sorted(exports_dir.glob("analysis-export-*.json")) if exports_dir.exists() else []
        summaries: list[dict[str, Any]] = []
        for path in paths:
            bundle = json.loads(path.read_text(encoding="utf-8"))
            export_id = str(bundle.get("export_id") or "").strip()
            if not export_id:
                raise ValueError("ANALYSIS_EXPORT_HISTORY_RECORD_INVALID")
            self.exports._verify_integrity(bundle, project_id, export_id)
            if normalized_analysis_id is not None and bundle.get("analysis_id") != normalized_analysis_id:
                continue
            summaries.append(self._summary(bundle))

        page = summaries[normalized_offset : normalized_offset + normalized_limit]
        return {
            "schema_version": EXPORT_HISTORY_SCHEMA_VERSION,
            "project_id": project_id,
            "analysis_id_filter": normalized_analysis_id,
            "items": page,
            "total": len(summaries),
            "limit": normalized_limit,
            "offset": normalized_offset,
            "ordering": "export_id_ascending_not_chronological",
            "chronology_inferred": False,
            "bundle_payloads_included": False,
            "raw_dataset_rows_included": False,
            "diagnostic_payload_included": False,
            "immutable_records_only": True,
            "deletion_authorized": False,
            "mutation_authorized": False,
            "public_sharing_authorized": False,
            "scientific_publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
            "scientific_interpretation_generated": False,
        }

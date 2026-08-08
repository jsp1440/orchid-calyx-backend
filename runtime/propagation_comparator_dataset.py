"""Research Station adapter for independent terrestrial-orchid PLB comparators.

Keeps comparator evidence separate from the Thelymitra flagship dataset so later
analysis cannot erase source/taxon boundaries. No registration or publication occurs.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .terrestrial_orchid_propagation_comparators import (
    COMPARATOR_SCHEMA_VERSION,
    comparator_matrix,
    vegetative_plb_bridge_assessment,
)

COMPARATOR_DATASET_SCHEMA_VERSION = "calyx-propagation-comparator-dataset/v1"
COMPARATOR_SCHEMA_REF = "calyx://schemas/propagation-comparator-dataset/v1"


def _stable(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(value: Any) -> str:
    material = value if isinstance(value, str) else _stable(value)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def comparator_dataset_rows() -> list[dict[str, Any]]:
    """Flatten comparator observations without introducing cross-source inference."""
    rows: list[dict[str, Any]] = []
    for item in comparator_matrix():
        source = item["source"]
        rows.append(
            {
                "observation_id": item["observation_id"],
                "source_id": item["source_id"],
                "taxon": item["taxon"],
                "explant": item["explant"],
                "explant_origin": item["explant_origin"],
                "response": item["response"],
                "direction": item["direction"],
                "treatment_factors": item["treatment"],
                "quantitative_value": item["quantitative_value"],
                "quantitative_unit": item["quantitative_unit"],
                "response_time_days": item["response_time_days"],
                "abstract_reported": item["abstract_reported"],
                "directly_about_thelymitra": False,
                "source_title": source["title"],
                "source_year": source["year"],
                "source_doi": source["doi"],
                "source_pmid": source["pmid"],
                "evidence_completeness": source["evidence_completeness"],
                "terrestrial_orchid": source["terrestrial_orchid"],
                "conservation_context": source["conservation_context"],
                "source_sha256": source["source_sha256"],
                "observation_sha256": item["observation_sha256"],
                "prediction_authority": False,
                "publication_authority": False,
            }
        )
    return sorted(rows, key=lambda row: row["observation_id"])


def canonical_rows_sha256(rows: list[dict[str, Any]]) -> str:
    """Use the same canonical row checksum semantics as CALYX-617."""
    return _sha(rows)


def comparator_dataset_package() -> dict[str, Any]:
    rows = comparator_dataset_rows()
    bridge = vegetative_plb_bridge_assessment()
    core = {
        "schema_version": COMPARATOR_DATASET_SCHEMA_VERSION,
        "comparator_schema_version": COMPARATOR_SCHEMA_VERSION,
        "title": "Terrestrial orchid vegetative-to-PLB comparator evidence",
        "row_count": len(rows),
        "taxa": sorted({row["taxon"] for row in rows}),
        "source_ids": sorted({row["source_id"] for row in rows}),
        "rows_checksum_sha256": canonical_rows_sha256(rows),
        "rows": rows,
        "bridge_assessment": bridge,
        "candidate_comparator_only": True,
        "direct_thelymitra_evidence": False,
        "prediction_of_thelymitra_success": False,
        "scientific_publication_authorized": False,
        "knowledge_graph_mutation_authorized": False,
    }
    return {**core, "package_sha256": _sha(core)}


def comparator_registration_packet() -> dict[str, Any]:
    package = comparator_dataset_package()
    return {
        "dataset_id": "dataset-terrestrial-orchid-vegetative-plb-comparators-v1",
        "title": package["title"],
        "checksum_sha256": package["rows_checksum_sha256"],
        "schema_ref": COMPARATOR_SCHEMA_REF,
        "provenance": {
            "calyx_build": "CALYX-639B",
            "package_sha256": package["package_sha256"],
            "source_ids": package["source_ids"],
            "taxa": package["taxa"],
            "row_count": package["row_count"],
            "candidate_comparator_only": True,
            "direct_thelymitra_evidence": False,
            "prediction_of_thelymitra_success": False,
            "scientific_publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
        },
    }


def comparator_dataset_readiness() -> dict[str, Any]:
    package = comparator_dataset_package()
    return {
        "dataset_schema_version": COMPARATOR_DATASET_SCHEMA_VERSION,
        "row_count": package["row_count"],
        "taxon_count": len(package["taxa"]),
        "source_count": len(package["source_ids"]),
        "rows_checksum_sha256": package["rows_checksum_sha256"],
        "registration_packet_ready": True,
        "registration_packet": comparator_registration_packet(),
        "rows_ready_for_calyx_617_analysis": True,
        "rows_persisted_in_research_station": False,
        "row_persistence_dependency": "CALYX-631 immutable registered dataset row transport",
        "scientific_review_required": True,
        "automatic_registration_performed": False,
        "direct_thelymitra_evidence": False,
        "prediction_of_thelymitra_success": False,
        "scientific_publication_authorized": False,
        "knowledge_graph_mutation_authorized": False,
    }

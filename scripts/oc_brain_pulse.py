"""Provider-free metacognitive intake for Orchid Continuum.

This pulse turns unresolved facts already emitted by the deterministic Cognitive
Integration reasoning map into bounded canonical work candidates. It never
creates scientific conclusions, changes governance, or calls a model provider.

The output intentionally uses the same oc.work-discovery.v1 contract consumed by
scripts.oc_work_materialize, so the existing fingerprint lineage, bounded filing,
queue, lease, execution, validation and settlement machinery remains the only
scheduler.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from app.calyx_advisory import pipeline as calyx_pipeline
from app.calyx_advisory.product_artifact import (
    UNIVERSITY_MODULE_PATH,
    from_university_module,
)
from app.cognitive_integration.executor import CognitiveIntegrationError, execute
from app.cognitive_integration.improvement_discovery import Deficiency, discover
from app.cognitive_integration.routes import SUPPORTED_QUESTIONS
from app.missions.registry import MISSION_TYPES
from app.university.ai_data_science import AppliedAIDataScienceService
from runtime.knowledge_graph.source_registry import SOURCE_QUERIES
from scripts.oc_product_lanes import LANES_BY_KEY, lane_for_path

SCHEMA = "oc.work-discovery.v1"
SOURCE = "brain-reasoning-gap"
MISSION_SOURCE = "brain-mission-capability-gap"
CALYX_PRODUCT_SOURCE = "calyx-product-advisory"

MISSION_GAP_LANES = {
    "source_registry_refresh": "literature",
    "literature_ingestion_review": "literature",
    "ontology_resolution": "lexicon",
    "evidence_readiness_evaluation": "research-station",
}

SOURCE_DOMAIN_LANES = {
    "geography": "atlas",
    "habitat": "atlas",
    "elevation": "atlas",
    "glossary": "lexicon",
    "evidence": "research-station",
    "molecular": "research-station",
    "education": "university-education",
}

LANE_FOR_DEFICIENCY = {
    Deficiency.MISSING_SOURCE: "literature",
    Deficiency.MISSING_INGESTION: "literature",
    Deficiency.MISSING_EVIDENCE: "research-station",
    Deficiency.MISSING_ONTOLOGY_TERM: "lexicon",
    Deficiency.MISSING_RELATIONSHIP: "interaction-graph",
    Deficiency.MISSING_MODULE_HANDOFF: "improvement-discovery",
    Deficiency.MISSING_VALIDATOR: "improvement-discovery",
    Deficiency.MISSING_CAPABILITY: "improvement-discovery",
    Deficiency.MISSING_REASONING_OPERATION: "improvement-discovery",
}


def fingerprint(question: str, deficiency: str, statement: str) -> str:
    material = (
        f"{SOURCE}\x1f{question.strip()}\x1f{deficiency.strip()}\x1f{statement.strip()}"
    )
    return hashlib.sha256(material.encode()).hexdigest()[:16]


def candidate_record(question: str, item: Any) -> dict[str, Any]:
    lane_key = LANE_FOR_DEFICIENCY[item.deficiency]
    lane = LANES_BY_KEY[lane_key]
    fp = fingerprint(question, item.deficiency.value, item.statement)
    title = f"[Brain] {item.deficiency.value.replace('_', ' ')}"
    summary = (
        "Continuous Brain pulse found an unresolved reasoning gap in deterministic "
        f"Cognitive Integration while evaluating: {question}\n\n"
        f"Gap: {item.statement}\n\n"
        f"Why it matters: {item.why_it_matters}\n\n"
        f"Bounded next step: {item.bounded_next_step}\n\n"
        "This is a research/engineering task, not a scientific conclusion. "
        "Execution may gather evidence, improve retrieval, add ingestion or repair "
        "reasoning infrastructure, but it may not self-approve a taxonomic or "
        "scientific claim."
    )
    return {
        "schema": "oc.work-candidate.v1",
        "source": SOURCE,
        "title": title,
        "summary": summary,
        "lane": lane.key,
        "lane_name": lane.name,
        "rank": lane.rank,
        "analysis_only": False,
        "fingerprint": fp,
        "semantic_key": f"{SOURCE}:{question}:{item.deficiency.value}:{item.statement}",
        "proposed_remedy": item.bounded_next_step,
        "remedy": {},
        "capabilities": [],
        "validation_command": "",
        "labels": ["oc-queued", lane.priority_label, "oc-discovered", lane.lane_label],
        "evidence": [
            {
                "kind": "cognitive-integration-gap",
                "where": "app/cognitive_integration/improvement_discovery.py",
                "detail": item.statement,
            },
            {
                "kind": "reasoning-question",
                "where": "app/cognitive_integration/routes.py::SUPPORTED_QUESTIONS",
                "detail": question,
            },
        ],
    }


def mission_gap_candidates() -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for mission_type, lane_key in MISSION_GAP_LANES.items():
        definition = MISSION_TYPES[mission_type]
        if definition.handler != "not_implemented_safe_block":
            continue
        lane = LANES_BY_KEY[lane_key]
        fp = hashlib.sha256(
            f"{MISSION_SOURCE}\x1f{mission_type}\x1f{definition.handler}".encode()
        ).hexdigest()[:16]
        candidates.append(
            {
                "schema": "oc.work-candidate.v1",
                "source": MISSION_SOURCE,
                "title": f"[Brain] implement {mission_type.replace('_', ' ')}",
                "summary": (
                    f"Continuous Brain pulse found mission capability {mission_type!r} "
                    "registered with the explicit fail-closed handler "
                    "'not_implemented_safe_block'. The bounded next step is to "
                    "implement and validate that existing governed mission contract; "
                    "do not bypass the safe block or broaden its authority."
                ),
                "lane": lane.key,
                "lane_name": lane.name,
                "rank": lane.rank,
                "analysis_only": False,
                "fingerprint": fp,
                "semantic_key": f"{MISSION_SOURCE}:{mission_type}:{definition.handler}",
                "proposed_remedy": (
                    "Implement the registered mission handler with provider, write-scope, "
                    "approval and scientific-authority limits preserved; add deterministic "
                    "tests before the safe block is removed."
                ),
                "remedy": {},
                "capabilities": [],
                "validation_command": "",
                "labels": ["oc-queued", lane.priority_label, "oc-discovered", lane.lane_label],
                "evidence": [
                    {
                        "kind": "registered-safe-block",
                        "where": "app/missions/registry.py::MISSION_TYPES",
                        "detail": f"{mission_type} -> {definition.handler}",
                    }
                ],
            }
        )
    return candidates


def source_registry_gap_candidates() -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for source in SOURCE_QUERIES:
        if source.enabled or source.domain not in SOURCE_DOMAIN_LANES:
            continue
        lane = LANES_BY_KEY[SOURCE_DOMAIN_LANES[source.domain]]
        reason = source.blocked_reason or source.notes or "source contract disabled fail-closed"
        fp = hashlib.sha256(
            f"brain-source-contract-gap\x1f{source.domain}\x1f{source.query_id}\x1f{reason}".encode()
        ).hexdigest()[:16]
        candidates.append(
            {
                "schema": "oc.work-candidate.v1",
                "source": "brain-source-contract-gap",
                "title": f"[Brain] resolve blocked {source.domain} source contract",
                "summary": (
                    f"Continuous Brain pulse found Knowledge Graph domain {source.domain!r} "
                    f"disabled fail-closed under query {source.query_id!r}. "
                    f"Registry evidence: {reason} The task is to identify or verify a "
                    "citable, rights-compatible source and taxon crosswalk, then prove "
                    "the projection before enabling it. Absence of a source must remain "
                    "explicit; do not substitute invented data."
                ),
                "lane": lane.key,
                "lane_name": lane.name,
                "rank": lane.rank,
                "analysis_only": False,
                "fingerprint": fp,
                "semantic_key": f"brain-source-contract-gap:{source.domain}:{source.query_id}:{reason}",
                "proposed_remedy": (
                    "Discover or verify an authoritative source, identifier strategy and "
                    "taxon crosswalk; retain provenance and disagreements; add a bounded "
                    "read-only validation before changing enabled state."
                ),
                "remedy": {},
                "capabilities": [],
                "validation_command": "",
                "labels": ["oc-queued", lane.priority_label, "oc-discovered", lane.lane_label],
                "evidence": [
                    {
                        "kind": "blocked-source-contract",
                        "where": "runtime/knowledge_graph/source_registry.py::SOURCE_QUERIES",
                        "detail": f"{source.domain}/{source.query_id}: {reason}",
                    }
                ],
            }
        )
    return candidates


def calyx_product_operation() -> dict[str, Any]:
    """Evaluate the current real University module and route findings to its lane."""
    module = AppliedAIDataScienceService.module()
    artifact = from_university_module(module)
    result = calyx_pipeline.run(artifact)
    receipt = result["receipt"]
    if not receipt["passed"]:
        raise RuntimeError("CALYX_PRODUCT_RECEIPT_FAILED")

    lane = lane_for_path(UNIVERSITY_MODULE_PATH)
    if lane is None:
        raise RuntimeError("CALYX_PRODUCT_MODULE_LANE_UNBOUND")

    candidates: list[dict[str, Any]] = []
    for finding in result["candidates"]:
        advisory_route = finding["target_module"]
        evidence = [
            {
                "kind": "university-module-artifact",
                "where": UNIVERSITY_MODULE_PATH,
                "detail": (
                    f"{module['module_id']}@{module['module_version']}; "
                    f"artifact_sha256={receipt['artifact_checksum']}"
                ),
            },
            {
                "kind": "calyx-advisory-finding",
                "where": "app/calyx_advisory/evaluator.py",
                "detail": f"{finding['finding_kind']}: {finding['statement']}",
            },
            {
                "kind": "registered-product-lane",
                "where": "scripts/oc_product_lanes.py::lane_for_path",
                "detail": f"{UNIVERSITY_MODULE_PATH} -> {lane.key}",
            },
        ]
        candidates.append(
            {
                "schema": "oc.work-candidate.v1",
                "source": CALYX_PRODUCT_SOURCE,
                "title": f"[Calyx] {finding['finding_kind'].replace('_', ' ')}: {module['title']}",
                "summary": (
                    "The provider-free Calyx pipeline evaluated the current University "
                    f"module artifact {module['module_id']}@{module['module_version']}. "
                    f"Finding: {finding['statement']} "
                    f"Bounded next step: {finding['bounded_next_step']} "
                    "This is a presentation-only product advisory; it makes no scientific "
                    "claim and does not authorize publication or deployment."
                ),
                "lane": lane.key,
                "lane_name": lane.name,
                "rank": lane.rank,
                "analysis_only": False,
                "fingerprint": finding["fingerprint"],
                "semantic_key": (
                    f"{CALYX_PRODUCT_SOURCE}:{artifact['artifact_id']}:"
                    f"{finding['fingerprint']}"
                ),
                "proposed_remedy": finding["bounded_next_step"],
                "remedy": {},
                "capabilities": [],
                "validation_command": "",
                "labels": [
                    "oc-queued",
                    lane.priority_label,
                    "oc-discovered",
                    lane.lane_label,
                ],
                "evidence": evidence,
                "advisory_target_module": advisory_route,
                "requires_human_review": finding["requires_human_review"],
                "scientific_effect": "none",
            }
        )

    return {
        "status": "ready",
        "artifact_id": artifact["artifact_id"],
        "artifact_checksum": receipt["artifact_checksum"],
        "advisory_checksum": receipt["advisory_checksum"],
        "finding_kinds": [item["kind"] for item in result["advisory"]["findings"]],
        "candidate_count": len(candidates),
        "candidates": candidates,
        "receipt": receipt,
    }


def calyx_product_materialization_report(report: dict[str, Any]) -> dict[str, Any]:
    """Reserve the bounded product-admission pass for Calyx findings only."""
    operation = report.get("calyx_product")
    if not isinstance(operation, dict) or operation.get("status") != "ready":
        error = (
            operation.get("error")
            if isinstance(operation, dict)
            else {"code": "CALYX_PRODUCT_RESULT_UNAVAILABLE", "detail": ""}
        )
        if not isinstance(error, dict):
            error = {
                "code": "CALYX_PRODUCT_FAILURE_REPORTED",
                "detail": str(error),
            }
        return {
            "schema": SCHEMA,
            "source": CALYX_PRODUCT_SOURCE,
            "status": "blocked",
            "errors": [{"source": CALYX_PRODUCT_SOURCE, **error}],
            "authority": report["authority"],
        }

    candidates = [
        candidate
        for candidate in report.get("candidates") or []
        if candidate.get("source") == CALYX_PRODUCT_SOURCE
    ]
    return {
        "schema": SCHEMA,
        "source": CALYX_PRODUCT_SOURCE,
        "status": "ready",
        "outcome": "actionable" if candidates else "no_action",
        "sources_evaluated": [CALYX_PRODUCT_SOURCE],
        "candidate_count": len(candidates),
        "candidates": candidates,
        "receipt": operation["receipt"],
        "authority": report["authority"],
    }


def build_report() -> dict[str, Any]:
    candidates: list[dict[str, Any]] = [
        *mission_gap_candidates(),
        *source_registry_gap_candidates(),
    ]
    errors: list[dict[str, str]] = []
    try:
        calyx_product = calyx_product_operation()
        candidates.extend(calyx_product["candidates"])
    except Exception as exc:  # noqa: BLE001 - isolate this independent advisory lane
        error = {
            "code": type(exc).__name__,
            "detail": str(exc),
        }
        calyx_product = {"status": "blocked", "error": error}
        errors.append(
            {
                "source": CALYX_PRODUCT_SOURCE,
                "error": error["code"],
                "detail": error["detail"],
            }
        )

    questions_evaluated: list[str] = []

    for question in SUPPORTED_QUESTIONS:
        try:
            reasoning_map = execute(question)
            questions_evaluated.append(question)
            for item in discover(reasoning_map):
                # Optional prose rendering is deliberately not queue-worthy:
                # structured reasoning is already complete and the candidate
                # explicitly says it blocks nothing scientific.
                if (
                    item.deficiency is Deficiency.MISSING_CAPABILITY
                    and item.blocks_question.startswith("none")
                ):
                    continue
                candidates.append(candidate_record(question, item))
        except CognitiveIntegrationError as exc:
            errors.append({"question": question, "error": type(exc).__name__})

    candidates.sort(key=lambda row: (int(row["rank"]), str(row["fingerprint"])))
    return {
        "schema": SCHEMA,
        "source": SOURCE,
        "candidate_count": len(candidates),
        "questions_evaluated": questions_evaluated,
        "sources_evaluated": [
            SOURCE,
            MISSION_SOURCE,
            "brain-source-contract-gap",
            *(
                [CALYX_PRODUCT_SOURCE]
                if calyx_product["status"] == "ready"
                else []
            ),
        ],
        "observers": {
            "reasoning_gap": {"questions_evaluated": len(questions_evaluated)},
            "mission_capability_gap": {"missions_evaluated": len(MISSION_GAP_LANES)},
            "source_contract_gap": {"source_domains_evaluated": len(SOURCE_QUERIES)},
        },
        "calyx_product": {
            key: value for key, value in calyx_product.items() if key != "candidates"
        },
        "candidates": candidates,
        "errors": errors,
        "authority": {
            "may_queue_research_or_engineering_work": True,
            "may_call_provider": False,
            "may_modify_governance": False,
            "may_promote_hypothesis": False,
            "may_activate_scientific_conclusion": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--calyx-product-output", type=Path)
    parser.add_argument("--verify-calyx-product", action="store_true")
    args = parser.parse_args()
    if args.verify_calyx_product:
        if args.output or args.calyx_product_output:
            parser.error("--verify-calyx-product cannot be combined with output paths")
        product = calyx_product_operation()
        outcome = (
            "actionable"
            if product["candidate_count"] > 0
            else "no_action"
            if product["finding_kinds"] == ["no_action"]
            else "invalid"
        )
        verification = {
            "schema": "calyx_product_operation_validation.v1",
            "artifact_id": product["artifact_id"],
            "artifact_checksum": product["artifact_checksum"],
            "advisory_checksum": product["advisory_checksum"],
            "finding_kinds": product["finding_kinds"],
            "candidate_count": product["candidate_count"],
            "outcome": outcome,
            "receipt": product["receipt"],
            "passed": product["receipt"]["passed"] and outcome != "invalid",
        }
        print(json.dumps(verification, sort_keys=True))
        return 0 if verification["passed"] else 1

    report = build_report()
    if args.calyx_product_output:
        try:
            calyx_report = calyx_product_materialization_report(report)
            args.calyx_product_output.write_text(
                json.dumps(calyx_report, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
        except (KeyError, OSError, TypeError, ValueError) as exc:
            error = {
                "code": type(exc).__name__,
                "detail": str(exc),
            }
            report["calyx_product"] = {"status": "blocked", "error": error}
            report["errors"].append(
                {
                    "source": CALYX_PRODUCT_SOURCE,
                    "error": error["code"],
                    "detail": error["detail"],
                }
            )

    rendered = json.dumps(report, sort_keys=True, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

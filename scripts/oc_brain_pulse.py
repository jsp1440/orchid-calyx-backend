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

from app.cognitive_integration.executor import execute
from app.cognitive_integration.improvement_discovery import Deficiency, discover
from app.cognitive_integration.routes import SUPPORTED_QUESTIONS
from scripts.oc_product_lanes import LANES_BY_KEY

SCHEMA = "oc.work-discovery.v1"
SOURCE = "brain-reasoning-gap"

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
    material = "\x1f".join((SOURCE, question.strip(), deficiency.strip(), statement.strip()))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


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


def build_report() -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    questions_evaluated: list[str] = []
    errors: list[dict[str, str]] = []

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
        except Exception as exc:  # fail closed per question; preserve the pulse
            errors.append({"question": question, "error": type(exc).__name__})

    candidates.sort(key=lambda row: (int(row["rank"]), str(row["fingerprint"])))
    return {
        "schema": SCHEMA,
        "source": SOURCE,
        "candidate_count": len(candidates),
        "questions_evaluated": questions_evaluated,
        "sources_evaluated": [SOURCE],
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
    args = parser.parse_args()
    report = build_report()
    rendered = json.dumps(report, sort_keys=True, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

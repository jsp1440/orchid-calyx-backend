"""Read-only operator projections over durable evolve memory.

Everything here reads.  There is no transition, approval, activation or
publication call in this module, which is what makes it safe to expose to
Mission Control and the Verification Workbench.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from runtime.calyx_evolve.analysis import ANALYZER_VERSION, FINDING_COUNTEREVIDENCE
from runtime.calyx_evolve.candidates import Candidate
from runtime.calyx_evolve.memory import ExperimentMemory
from runtime.calyx_evolve.metrics import (
    EVALUATOR_VERSION,
    METRIC_FALSE_MERGE_COUNT,
    SCORING_VERSION,
    metric_catalogue,
)


def _lineage(candidate_id: str, index: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """Ancestor ids nearest-first, tolerant of records that predate a parent."""

    seen = {candidate_id}
    ordered: list[str] = []
    frontier = list(index.get(candidate_id, {}).get("parent_ids", []))
    while frontier:
        parent_id = str(frontier.pop(0))
        if parent_id in seen:
            continue
        seen.add(parent_id)
        ordered.append(parent_id)
        frontier.extend(index.get(parent_id, {}).get("parent_ids", []))
    return ordered


def campaign_status(memory: ExperimentMemory, campaign_id: str) -> dict[str, Any] | None:
    """Full inspectable status for one campaign, or ``None`` when unknown."""

    campaign = memory.get_campaign(campaign_id)
    if campaign is None:
        return None

    candidates = memory.list_candidates(campaign_id)
    candidate_index = {str(row["candidate_id"]): row for row in candidates}
    runs = memory.list_runs(campaign_id)
    proposals = memory.list_proposals(campaign_id)
    proposals_by_run = {str(row["run_id"]): row for row in proposals}

    baseline_id = str(campaign.get("baseline_candidate_id", ""))
    baseline_run = next(
        (run for run in runs if str(run.get("candidate_id")) == baseline_id), None
    )
    baseline_score = (baseline_run or {}).get("aggregate_score") or {}

    run_views: list[dict[str, Any]] = []
    for run in sorted(runs, key=lambda row: str(row.get("run_id"))):
        run_id = str(run["run_id"])
        candidate_id = str(run.get("candidate_id"))
        findings = memory.list_findings(run_id)
        metrics = memory.list_metrics(run_id)
        score = run.get("aggregate_score") or {}
        false_merge = next(
            (row for row in metrics if row.get("key") == METRIC_FALSE_MERGE_COUNT), None
        )
        run_views.append(
            {
                "run_id": run_id,
                "candidate_id": candidate_id,
                "is_baseline": candidate_id == baseline_id,
                "terminal_state": run.get("terminal_state"),
                "eligible": run.get("eligible"),
                "promotable": run.get("promotable"),
                "replay_key": run.get("replay_key"),
                "replay_deterministic": run.get("replay_deterministic"),
                "artifact_digest": run.get("artifact_digest"),
                "replay_artifact_digest": run.get("replay_artifact_digest"),
                "record_hash": run.get("record_hash"),
                "runtime_seconds": run.get("runtime_seconds"),
                "lineage": _lineage(candidate_id, candidate_index),
                "aggregate_score": score,
                "score_delta_vs_baseline": (
                    round(score["value"] - baseline_score["value"], 9)
                    if score.get("value") is not None and baseline_score.get("value") is not None
                    else None
                ),
                "false_merge_count": (false_merge or {}).get("value"),
                "metric_vector": metrics,
                "safety_violations": run.get("safety_violations", []),
                "resolutions": run.get("resolutions", []),
                "findings": findings,
                "counterevidence": [
                    row for row in findings if row.get("finding_type") == FINDING_COUNTEREVIDENCE
                ],
                "promotion": proposals_by_run.get(run_id),
            }
        )

    return {
        "campaign": campaign,
        "governance": {
            "governance_state": campaign.get("governance_state"),
            "execution_scope": campaign.get("execution_scope"),
            "requires_human_scientific_review": True,
            "taxonomy_activation_permitted": False,
            "knowledge_graph_publication_permitted": False,
            "external_publication_permitted": False,
        },
        "versions": {
            "evaluator_version": EVALUATOR_VERSION,
            "scoring_version": SCORING_VERSION,
            "analyzer_version": ANALYZER_VERSION,
        },
        "metric_catalogue": metric_catalogue(),
        "cognition": memory.list_cognition(campaign_id),
        "candidates": candidates,
        "baseline_candidate_id": baseline_id,
        "runs": run_views,
        "promotion_proposals": proposals,
        "persistence_mode": getattr(memory, "persistence_mode", "unknown"),
    }


def campaign_index(memory: ExperimentMemory) -> dict[str, Any]:
    """A compact listing of every known campaign."""

    campaigns = memory.list_campaigns()
    rows = []
    for campaign in campaigns:
        campaign_id = str(campaign["campaign_id"])
        runs = memory.list_runs(campaign_id)
        rows.append(
            {
                "campaign_id": campaign_id,
                "title": campaign.get("title"),
                "governance_state": campaign.get("governance_state"),
                "execution_scope": campaign.get("execution_scope"),
                "baseline_candidate_id": campaign.get("baseline_candidate_id"),
                "cognition_bundle_hash": campaign.get("cognition_bundle_hash"),
                "run_count": len(runs),
                "promotion_proposals": len(memory.list_proposals(campaign_id)),
            }
        )
    return {
        "campaigns": rows,
        "persistence_mode": getattr(memory, "persistence_mode", "unknown"),
        "versions": {
            "evaluator_version": EVALUATOR_VERSION,
            "scoring_version": SCORING_VERSION,
            "analyzer_version": ANALYZER_VERSION,
        },
    }


def candidate_comparison(
    memory: ExperimentMemory, campaign_id: str, candidate_id: str
) -> dict[str, Any] | None:
    """Baseline-versus-candidate metric comparison for one candidate."""

    status = campaign_status(memory, campaign_id)
    if status is None:
        return None
    baseline_id = status["baseline_candidate_id"]
    baseline_run = next((row for row in status["runs"] if row["candidate_id"] == baseline_id), None)
    candidate_run = next(
        (row for row in status["runs"] if row["candidate_id"] == candidate_id), None
    )
    if candidate_run is None:
        return None
    return {
        "campaign_id": campaign_id,
        "baseline": baseline_run,
        "candidate": candidate_run,
        "versions": status["versions"],
        "governance": status["governance"],
    }


def candidate_record(candidate: Candidate) -> dict[str, Any]:
    return candidate.to_dict()

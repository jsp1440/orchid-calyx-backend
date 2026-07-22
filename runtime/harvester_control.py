"""BUILD-049 governed harvester registry and adaptive source router."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from runtime.constitutional_orchestrator import orchestrator

OPERATIONAL_STATES = {
    "active",
    "paused",
    "run_once",
    "draining",
    "exhausted",
    "needs_review",
    "redirect_pending",
    "failed",
    "retired",
}

LOW_RISK_ACTIONS = {"run_once", "pause", "resume", "reassess"}
HIGH_RISK_ACTIONS = {"retire", "restore", "update_schedule", "approve_target_change", "reject_target_change"}


def authorized_action_contract(action: str, reason: str, *, risk: str) -> dict[str, Any]:
    return {
        "action": action,
        "allowed": False,
        "state": "requires_owner_authorization",
        "auth": "api_key_required",
        "risk": risk,
        "reason": reason,
    }


def harvester_allowed_actions() -> dict[str, dict[str, Any]]:
    return {
        "runOnce": authorized_action_contract("run_once", "Queues a harvester run and writes run history.", risk="low"),
        "pause": authorized_action_contract("pause", "Changes harvester operational state.", risk="low"),
        "resume": authorized_action_contract("resume", "Changes harvester operational state.", risk="low"),
        "retire": authorized_action_contract("retire", "Removes a source from active harvesting until restored.", risk="high"),
        "restore": authorized_action_contract("restore", "Returns a retired source to active harvesting.", risk="high"),
        "changeTarget": authorized_action_contract("propose_target_change", "Creates a reviewed source-target change proposal.", risk="high"),
        "changeSchedule": authorized_action_contract("update_schedule", "Changes harvester frequency.", risk="high"),
        "approve": authorized_action_contract("approve_target_change", "Approves a target change proposal.", risk="high"),
        "reject": authorized_action_contract("reject_target_change", "Rejects a target change proposal.", risk="high"),
        "reassess": authorized_action_contract("reassess", "Refreshes recommendation state from available telemetry.", risk="low"),
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ScientificTarget:
    target_type: str
    target_value: str
    taxon: str | None = None
    geography: str | None = None
    elevation_band: str | None = None
    habitat: str | None = None
    pollinator_group: str | None = None
    mycorrhizal_group: str | None = None
    literature_topic: str | None = None
    publication_date_range: str | None = None
    occurrence_freshness_window: str | None = None
    image_media_gap: str | None = None
    conservation_status_gap: str | None = None
    relationship_gap_query: str | None = None
    entity_ref: dict[str, Any] = field(default_factory=dict)


@dataclass
class Harvester:
    harvester_id: str
    display_name: str
    scientific_purpose: str
    connector_source_id: str
    source_type: str
    target: ScientificTarget
    query_scope: str
    schedule: str
    enabled: bool = True
    operational_state: str = "active"
    checkpoint_cursor: str | None = None
    last_attempted_run: str | None = None
    last_successful_run: str | None = None
    next_scheduled_run: str | None = None
    rows_examined: int | None = None
    rows_inserted: int | None = None
    rows_updated: int | None = None
    duplicates_detected: int | None = None
    rows_rejected: int | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    run_duration_ms: int | None = None
    estimated_cost: float | None = None
    freshness: str = "unknown"
    novelty_yield_rate: float | None = None
    source_exhaustion_score: float | None = None
    downstream_relationships_created: int | None = None
    current_recommendation: str = "continue_unchanged"
    recommendation_rationale: str = "Seeded from current known harvester inventory; live telemetry is not yet available."
    required_approval_level: str = "owner"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class HarvesterRun:
    harvester_id: str
    run_id: str
    starting_checkpoint: str | None
    ending_checkpoint: str | None
    trigger_type: str
    started_at: str
    ended_at: str | None
    status: str
    records_examined: int | None = None
    inserted: int | None = None
    updated: int | None = None
    duplicated: int | None = None
    rejected: int | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    novelty_rate: float | None = None
    relationship_yield: int | None = None
    source_response_metadata: dict[str, Any] = field(default_factory=dict)
    execution_log_reference: str | None = None
    decision_approval_reference: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class TargetProposal:
    proposal_id: str
    harvester_id: str
    current_assignment: dict[str, Any]
    proposed_assignment: dict[str, Any]
    scientific_rationale: str
    evidence_considered: list[str]
    expected_value: str
    confidence: float
    risk_level: str
    approval_requirement: str
    status: str = "pending"
    decision_reference: str | None = None
    created_at: str = field(default_factory=utc_now)
    decided_at: str | None = None


SEED_HARVESTERS = [
    ("inaturalist", "iNaturalist", "Occurrence and community media freshness", "inat", "observations", "taxon", "Orchidaceae", "orchid observations and usable media", "daily"),
    ("gbif", "GBIF", "Occurrence backbone and range evidence", "gbif", "occurrences", "taxon", "Orchidaceae", "occurrence backbone, coordinates, dates", "daily"),
    ("world_plants_hassler", "World Plants / Hassler", "Taxonomic synonym and accepted-name backbone", "world-plants", "taxonomy", "taxon", "Orchidaceae", "taxonomic backbone reconciliation", "weekly"),
    ("eol_traitbank", "EOL / TraitBank", "Trait and ecology evidence", "eol-traitbank", "traits", "evidence_type", "traits", "trait and ecology records", "weekly"),
    ("image_media", "Image/media harvesters", "Species and genus media coverage", "media", "images", "image_media_gap", "species pages without media", "image/media gap coverage", "daily"),
    ("literature", "Literature harvesters", "Citation-backed relationship extraction", "literature", "literature", "literature_topic", "orchid ecology relationships", "literature query and citation extraction", "weekly"),
    ("mycorrhizal_data", "Mycorrhizal harvesters", "Orchid-fungal relationship coverage", "mycorrhiza", "relationships", "relationship_gap_query", "orchid mycorrhizal gaps", "fungal relationship evidence", "weekly"),
    ("climate_elevation", "Climate/elevation enrichment", "Climate and elevation context enrichment", "climate", "enrichment", "elevation_band", "unknown", "climate and elevation enrichment", "weekly"),
    ("conservation_status", "Conservation enrichment", "Conservation status and threat context", "conservation", "enrichment", "conservation_status_gap", "unknown", "conservation gap enrichment", "weekly"),
]


class HarvesterControlPlane:
    def __init__(self) -> None:
        self.harvesters = self._seed_registry()
        self.runs: dict[str, list[HarvesterRun]] = {hid: [] for hid in self.harvesters}
        self.proposals: dict[str, TargetProposal] = {}

    def _seed_registry(self) -> dict[str, Harvester]:
        registry: dict[str, Harvester] = {}
        for hid, name, purpose, source_id, source_type, target_type, target_value, scope, schedule in SEED_HARVESTERS:
            registry[hid] = Harvester(
                harvester_id=hid,
                display_name=name,
                scientific_purpose=purpose,
                connector_source_id=source_id,
                source_type=source_type,
                target=ScientificTarget(target_type=target_type, target_value=target_value),
                query_scope=scope,
                schedule=schedule,
                rows_examined=None,
                rows_inserted=None,
                rows_updated=None,
                duplicates_detected=None,
                rows_rejected=None,
                provenance={"source": "BUILD-049 idempotent seed", "historical_telemetry": "unknown"},
            )
        return registry

    def list_harvesters(self) -> list[dict[str, Any]]:
        return [self.serialize_harvester(item) for item in self.harvesters.values()]

    def get_harvester(self, harvester_id: str) -> dict[str, Any]:
        return self.serialize_harvester(self._require_harvester(harvester_id))

    def get_runs(self, harvester_id: str) -> list[dict[str, Any]]:
        self._require_harvester(harvester_id)
        return [asdict(run) for run in self.runs.get(harvester_id, [])]

    def run_once(self, harvester_id: str, actor: str, execute: bool = False) -> dict[str, Any]:
        harvester = self._transition(harvester_id, "run_once", actor, "run_once", risk="low")
        # Real execution is opt-in (worker path passes execute=True). The API
        # run-once path and unintegrated ids keep the governed queued-stub
        # behavior. Governance denial (needs_review) also falls back to stub.
        if execute and harvester.operational_state != "needs_review":
            from harvesters.execution import is_integrated
            if is_integrated(harvester_id):
                return self._execute_run(harvester, actor)
        run = HarvesterRun(
            harvester_id=harvester_id,
            run_id=f"HRUN-{uuid4().hex[:10].upper()}",
            starting_checkpoint=harvester.checkpoint_cursor,
            ending_checkpoint=harvester.checkpoint_cursor,
            trigger_type="owner_run_once",
            started_at=utc_now(),
            ended_at=None,
            status="queued",
            execution_log_reference="oc_admin.ocp_execution_jobs pending integration",
            provenance={"actor": actor, "source": "BUILD-049 control API"},
        )
        self.runs[harvester_id].insert(0, run)
        return {"status": "queued", "harvester": self.serialize_harvester(harvester), "run": asdict(run)}

    def _execute_run(self, harvester: Harvester, actor: str) -> dict[str, Any]:
        """Execute an integrated harvester via the BUILD-093 adapter and record
        real run telemetry (checkpoints, rows, status) on the HarvesterRun."""
        from harvesters.execution import run_harvester

        started = utc_now()
        errors: list[str] = []
        try:
            telemetry = run_harvester(harvester.harvester_id)
            status = "success"
        except Exception as exc:  # execution failures are recorded, not raised
            telemetry = {}
            status = "failed"
            errors = [str(exc)]
        ended = utc_now()

        run = HarvesterRun(
            harvester_id=harvester.harvester_id,
            run_id=f"HRUN-{uuid4().hex[:10].upper()}",
            starting_checkpoint=telemetry.get("starting_checkpoint", harvester.checkpoint_cursor),
            ending_checkpoint=telemetry.get("ending_checkpoint", harvester.checkpoint_cursor),
            trigger_type="worker_dispatch",
            started_at=started,
            ended_at=ended,
            status=status,
            records_examined=telemetry.get("records_examined"),
            inserted=telemetry.get("inserted"),
            errors=errors,
            source_response_metadata=telemetry.get("source_response_metadata", {}),
            execution_log_reference="harvesters.execution.run_harvester",
            provenance={"actor": actor, "source": "BUILD-093 execution adapter"},
        )
        self.runs[harvester.harvester_id].insert(0, run)

        harvester.last_attempted_run = started
        if status == "success":
            harvester.last_successful_run = ended
            if run.ending_checkpoint is not None:
                harvester.checkpoint_cursor = run.ending_checkpoint
            harvester.rows_inserted = telemetry.get("inserted")
            harvester.rows_examined = telemetry.get("records_examined")
        else:
            harvester.errors = list(harvester.errors) + errors
        harvester.updated_at = utc_now()
        return {"status": status, "harvester": self.serialize_harvester(harvester), "run": asdict(run)}

    def pause(self, harvester_id: str, actor: str) -> dict[str, Any]:
        return {"status": "paused", "harvester": self.serialize_harvester(self._transition(harvester_id, "paused", actor, "pause", risk="low"))}

    def resume(self, harvester_id: str, actor: str) -> dict[str, Any]:
        harvester = self._transition(harvester_id, "active", actor, "resume", risk="low")
        return {"status": "active", "harvester": self.serialize_harvester(harvester)}

    def retire(self, harvester_id: str, actor: str) -> dict[str, Any]:
        return {"status": "retired", "harvester": self.serialize_harvester(self._transition(harvester_id, "retired", actor, "retire", risk="high"))}

    def restore(self, harvester_id: str, actor: str) -> dict[str, Any]:
        return {"status": "active", "harvester": self.serialize_harvester(self._transition(harvester_id, "active", actor, "restore", risk="high"))}

    def cancel_run(self, harvester_id: str, actor: str) -> dict[str, Any]:
        """Cancel the most recent queued or running job run for a harvester."""
        self._require_harvester(harvester_id)
        decision = self._evaluate("cancel_run", "low", evidence=[f"actor={actor}", f"harvester={harvester_id}"])
        run_list = self.runs.get(harvester_id, [])
        cancelled = None
        for run in run_list:
            if run.status in {"queued", "running"}:
                run.status = "cancelled"
                run.ended_at = utc_now()
                run.provenance["cancelled_by"] = actor
                run.provenance["cancel_decision"] = decision["decision"]["decision_id"]
                cancelled = run
                break
        harvester = self._require_harvester(harvester_id)
        return {
            "status": "cancelled" if cancelled else "no_active_run",
            "run": asdict(cancelled) if cancelled else None,
            "harvester": self.serialize_harvester(harvester),
            "decision": decision["decision"],
        }

    def reschedule(self, harvester_id: str, schedule: str, actor: str) -> dict[str, Any]:
        """Reschedule a harvester — alias for update_schedule with reschedule semantics."""
        result = self.update_schedule(harvester_id, schedule, actor)
        if result.get("status") == "updated":
            result["status"] = "rescheduled"
        return result

    def update_schedule(self, harvester_id: str, schedule: str, actor: str) -> dict[str, Any]:
        decision = self._evaluate("update_schedule", "high", evidence=[f"schedule={schedule}"])
        harvester = self._require_harvester(harvester_id)
        if decision["decision"]["status"] != "approved":
            return {"status": "review_required", "decision": decision["decision"], "harvester": self.serialize_harvester(harvester)}
        harvester.schedule = schedule
        harvester.updated_at = utc_now()
        harvester.provenance["last_actor"] = actor
        return {"status": "updated", "decision": decision["decision"], "harvester": self.serialize_harvester(harvester)}

    def propose_target_change(self, harvester_id: str, proposed: dict[str, Any], rationale: str) -> dict[str, Any]:
        harvester = self._require_harvester(harvester_id)
        decision = self._evaluate("propose_target_change", "high", evidence=[rationale, f"harvester={harvester_id}"])
        proposal = TargetProposal(
            proposal_id=f"HTP-{uuid4().hex[:10].upper()}",
            harvester_id=harvester_id,
            current_assignment=asdict(harvester.target),
            proposed_assignment=proposed,
            scientific_rationale=rationale,
            evidence_considered=["current assignment", "source productivity signals", "knowledge-gap relevance"],
            expected_value="Potentially improves scientific coverage without silently changing the source target.",
            confidence=0.62,
            risk_level="high",
            approval_requirement="owner_review",
            decision_reference=decision["decision"]["decision_id"],
        )
        self.proposals[proposal.proposal_id] = proposal
        harvester.operational_state = "redirect_pending"
        harvester.current_recommendation = "redirect_pending"
        harvester.recommendation_rationale = rationale
        harvester.updated_at = utc_now()
        return {"status": "pending", "decision": decision["decision"], "proposal": asdict(proposal), "harvester": self.serialize_harvester(harvester)}

    def approve_proposal(self, harvester_id: str, proposal_id: str, actor: str) -> dict[str, Any]:
        proposal = self._require_proposal(harvester_id, proposal_id)
        decision = self._evaluate("approve_target_change", "high", evidence=proposal.evidence_considered)
        if decision["decision"]["status"] != "approved":
            proposal.decision_reference = decision["decision"]["decision_id"]
            return {"status": "review_required", "decision": decision["decision"], "proposal": asdict(proposal)}
        harvester = self._require_harvester(harvester_id)
        proposal.status = "approved"
        proposal.decided_at = utc_now()
        proposal.decision_reference = decision["decision"]["decision_id"]
        harvester.target = ScientificTarget(**{**asdict(harvester.target), **proposal.proposed_assignment})
        harvester.operational_state = "active"
        harvester.updated_at = utc_now()
        harvester.provenance["last_actor"] = actor
        return {"status": "approved", "decision": decision["decision"], "proposal": asdict(proposal), "harvester": self.serialize_harvester(harvester)}

    def reject_proposal(self, harvester_id: str, proposal_id: str, actor: str) -> dict[str, Any]:
        proposal = self._require_proposal(harvester_id, proposal_id)
        decision = self._evaluate("reject_target_change", "high", evidence=proposal.evidence_considered)
        proposal.status = "rejected"
        proposal.decided_at = utc_now()
        proposal.decision_reference = decision["decision"]["decision_id"]
        harvester = self._require_harvester(harvester_id)
        harvester.operational_state = "needs_review"
        harvester.updated_at = utc_now()
        harvester.provenance["last_actor"] = actor
        return {"status": "rejected", "decision": decision["decision"], "proposal": asdict(proposal), "harvester": self.serialize_harvester(harvester)}

    def reassess(self, harvester_id: str) -> dict[str, Any]:
        harvester = self._require_harvester(harvester_id)
        recommendation = self.recommend(harvester)
        harvester.current_recommendation = recommendation["recommendation"]
        harvester.recommendation_rationale = recommendation["scientific_rationale"]
        harvester.source_exhaustion_score = recommendation["source_exhaustion_score"]
        harvester.updated_at = utc_now()
        return {"status": "assessed", "recommendation": recommendation, "harvester": self.serialize_harvester(harvester)}

    def recommendation(self, harvester_id: str) -> dict[str, Any]:
        return self.recommend(self._require_harvester(harvester_id))

    def recommend(self, harvester: Harvester) -> dict[str, Any]:
        examined = harvester.rows_examined or 0
        inserted = harvester.rows_inserted or 0
        duplicates = harvester.duplicates_detected or 0
        errors = len(harvester.errors)
        novelty = harvester.novelty_yield_rate
        if novelty is None and examined:
            novelty = inserted / examined
        duplicate_rate = duplicates / examined if examined else None
        error_rate = errors / max(1, examined) if examined else 0
        unchanged_checkpoint = harvester.last_attempted_run and harvester.last_successful_run and harvester.checkpoint_cursor == "unchanged"
        exhaustion = harvester.source_exhaustion_score
        if exhaustion is None:
            exhaustion = 0.15
            if novelty is not None and novelty < 0.02:
                exhaustion += 0.45
            if duplicate_rate is not None and duplicate_rate > 0.8:
                exhaustion += 0.25
            if unchanged_checkpoint:
                exhaustion += 0.15
            if errors:
                exhaustion += 0.1
        exhaustion = min(1.0, exhaustion)
        if error_rate > 0.2:
            recommendation = "pause_for_review"
            risk = "medium"
        elif exhaustion >= 0.85:
            recommendation = "retire_as_exhausted"
            risk = "high"
        elif duplicate_rate is not None and duplicate_rate > 0.7:
            recommendation = "reduce_frequency"
            risk = "medium"
        elif novelty is not None and novelty > 0.25:
            recommendation = "increase_frequency"
            risk = "medium"
        else:
            recommendation = "continue_unchanged"
            risk = "low"
        return {
            "current_assignment": asdict(harvester.target),
            "evidence_considered": {
                "novelty_rate": novelty,
                "duplicate_rate": duplicate_rate,
                "error_rate": error_rate,
                "freshness": harvester.freshness,
                "source_exhaustion_score": exhaustion,
                "downstream_relationships_created": harvester.downstream_relationships_created,
            },
            "proposed_assignment": asdict(harvester.target),
            "recommendation": recommendation,
            "scientific_rationale": "Recommendation is conservative and based only on available telemetry; unknown historical values are not treated as zero.",
            "expected_value": "Improve harvest yield while preserving provenance, checkpoints, and source terms.",
            "confidence": 0.45 if examined == 0 else 0.72,
            "risk_level": risk,
            "approval_requirement": "owner_review" if risk in {"medium", "high"} else "none_for_observation",
            "source_exhaustion_score": exhaustion,
        }

    def serialize_harvester(self, harvester: Harvester) -> dict[str, Any]:
        data = asdict(deepcopy(harvester))
        data["id"] = harvester.harvester_id
        data["name"] = harvester.display_name
        data["source"] = harvester.connector_source_id
        data["state"] = harvester.operational_state
        data["lastRun"] = harvester.last_successful_run or "unknown"
        data["nextRun"] = harvester.next_scheduled_run or "unknown"
        data["rowsProcessed"] = harvester.rows_examined
        data["rowsInserted"] = harvester.rows_inserted
        data["warningCount"] = len(harvester.warnings)
        data["checkpoint"] = harvester.checkpoint_cursor or "unknown"
        data["runNow"] = "requires_owner_authorization"
        data["pauseResume"] = "requires_owner_authorization"
        data["allowedActions"] = harvester_allowed_actions()
        data["logSummary"] = harvester.recommendation_rationale
        data["target"] = asdict(harvester.target)
        return data

    def _transition(self, harvester_id: str, next_state: str, actor: str, action: str, *, risk: str) -> Harvester:
        if next_state not in OPERATIONAL_STATES:
            raise ValueError("unsupported operational state")
        decision = self._evaluate(action, risk, evidence=[f"actor={actor}", f"harvester={harvester_id}"])
        harvester = self._require_harvester(harvester_id)
        if decision["decision"]["status"] not in {"approved", "approved_limited"}:
            harvester.operational_state = "needs_review"
            return harvester
        if harvester.operational_state == "retired" and next_state not in {"active", "retired"}:
            harvester.operational_state = "needs_review"
            return harvester
        harvester.operational_state = next_state
        harvester.updated_at = utc_now()
        harvester.provenance["last_actor"] = actor
        harvester.provenance["last_decision"] = decision["decision"]["decision_id"]
        return harvester

    def _evaluate(self, action: str, risk: str, evidence: list[str]) -> dict[str, Any]:
        requested = 4 if risk == "high" else 1
        return orchestrator.evaluate_action(
            mission_id="science",
            action=f"harvester_control:{action}",
            requested_autonomy_level=requested,
            evidence=evidence,
            reversible=True,
            provenance_available=True,
        )

    def _require_harvester(self, harvester_id: str) -> Harvester:
        if harvester_id not in self.harvesters:
            raise KeyError(harvester_id)
        return self.harvesters[harvester_id]

    def _require_proposal(self, harvester_id: str, proposal_id: str) -> TargetProposal:
        proposal = self.proposals.get(proposal_id)
        if proposal is None or proposal.harvester_id != harvester_id:
            raise KeyError(proposal_id)
        return proposal


control_plane = HarvesterControlPlane()

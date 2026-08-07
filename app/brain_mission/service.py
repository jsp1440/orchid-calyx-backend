from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

MissionStep = Callable[[dict[str, Any]], Any]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _identifier(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class MissionComponents:
    """Adapters around existing Brain services; absent adapters fail closed."""

    retrieve: MissionStep | None = None
    aggregate: MissionStep | None = None
    analyze: MissionStep | None = None
    interpret: MissionStep | None = None
    create_ledger: MissionStep | None = None
    validate: MissionStep | None = None
    review_state: MissionStep | None = None
    publication_eligibility: MissionStep | None = None


class MemoryMissionRepository:
    def __init__(self) -> None:
        self._missions: dict[str, dict[str, Any]] = {}

    def save(self, mission: dict[str, Any]) -> None:
        self._missions[mission["mission_id"]] = deepcopy(mission)

    def get(self, mission_id: str) -> dict[str, Any] | None:
        value = self._missions.get(mission_id)
        return deepcopy(value) if value else None


class BrainMissionService:
    LIFECYCLE = (
        "question",
        "bounded_plan",
        "evidence_retrieval",
        "evidence_aggregation",
        "contradiction_and_gap_analysis",
        "scientific_interpretation",
        "reasoning_ledger_creation",
        "validation",
        "human_review_state",
        "eligible_for_publication_state",
    )

    def __init__(
        self,
        components: MissionComponents,
        repository: MemoryMissionRepository | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.components = components
        self.repository = repository or MemoryMissionRepository()
        self.clock = clock

    def start(
        self,
        *,
        question: str,
        tenant_id: str,
        project_id: str,
        actor: str,
        max_sources: int = 20,
        max_steps: int = 10,
        timeout_seconds: float = 30.0,
    ) -> dict[str, Any]:
        question = " ".join(question.split())
        if not question:
            raise ValueError("QUESTION_REQUIRED")
        if not tenant_id.strip() or not project_id.strip() or not actor.strip():
            raise ValueError("MISSION_SCOPE_REQUIRED")
        if not 1 <= max_sources <= 100:
            raise ValueError("INVALID_MAX_SOURCES")
        if not 1 <= max_steps <= len(self.LIFECYCLE):
            raise ValueError("INVALID_MAX_STEPS")
        if not 0.1 <= timeout_seconds <= 300:
            raise ValueError("INVALID_TIMEOUT")

        signature = {
            "question": question,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "limits": {
                "max_sources": max_sources,
                "max_steps": max_steps,
                "timeout_seconds": timeout_seconds,
            },
        }
        mission_id = _identifier(signature)
        mission = {
            "mission_id": mission_id,
            "question": question,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "state": "RUNNING",
            "current_stage": "question",
            "limits": signature["limits"],
            "steps_executed": 1,
            "plan": self._plan(question, max_sources),
            "sources": [],
            "supporting_evidence": [],
            "contradicting_evidence": [],
            "missing_evidence": [],
            "confidence": None,
            "conclusions": [],
            "reasoning_ledger": None,
            "artifacts": {},
            "validation": {"valid": False, "blockers": []},
            "review_status": "HUMAN_REVIEW_REQUIRED",
            "publication_eligibility": {
                "eligible": False,
                "automatic_publication": False,
                "blockers": ["HUMAN_REVIEW_REQUIRED"],
            },
            "blockers": [],
            "partial": False,
            "created_at": _now(),
            "updated_at": _now(),
        }
        self.repository.save(mission)
        started = self.clock()
        context = {**mission, "actor": actor}
        stages = (
            ("evidence_retrieval", "retrieve"),
            ("evidence_aggregation", "aggregate"),
            ("contradiction_and_gap_analysis", "analyze"),
            ("scientific_interpretation", "interpret"),
            ("reasoning_ledger_creation", "create_ledger"),
            ("validation", "validate"),
            ("human_review_state", "review_state"),
            ("eligible_for_publication_state", "publication_eligibility"),
        )
        for stage, component_name in stages:
            if mission["steps_executed"] >= max_steps:
                self._block(mission, "MAX_EXECUTION_STEPS_REACHED", stage)
                break
            if self.clock() - started >= timeout_seconds:
                self._block(mission, "MISSION_TIMEOUT", stage)
                break
            component = getattr(self.components, component_name)
            if component is None:
                self._block(
                    mission, f"{component_name.upper()}_COMPONENT_UNAVAILABLE", stage
                )
                break
            mission["current_stage"] = stage
            mission["steps_executed"] += 1
            try:
                output = component({**context, **deepcopy(mission)})
                self._apply(stage, output or {}, mission, max_sources)
            except Exception as exc:  # noqa: BLE001 - adapter boundary fails closed
                self._block(
                    mission, f"{component_name.upper()}_FAILED", stage, str(exc)
                )
                break
            self.repository.save(mission)

        if (
            not mission["blockers"]
            and mission["current_stage"] == "eligible_for_publication_state"
        ):
            mission["state"] = (
                "AWAITING_HUMAN_REVIEW"
                if mission["review_status"] != "APPROVED"
                else "COMPLETE"
            )
        mission["partial"] = bool(mission["blockers"])
        mission["updated_at"] = _now()
        self.repository.save(mission)
        return mission

    def status(self, mission_id: str) -> dict[str, Any]:
        mission = self.repository.get(mission_id)
        if mission is None:
            raise LookupError("MISSION_NOT_FOUND")
        return mission

    @staticmethod
    def _plan(question: str, max_sources: int) -> dict[str, Any]:
        domains = [
            "taxonomy",
            "geographic_distribution",
            "pollination_biology",
            "conservation",
            "mycorrhiza",
        ]
        return {
            "question": question,
            "domains": domains,
            "retrieval_queries": [
                f"{question} {domain.replace('_', ' ')}" for domain in domains
            ],
            "source_budget": max_sources,
            "per_domain_source_budget": max(1, max_sources // len(domains)),
            "claims_and_inferences_separated": True,
        }

    @staticmethod
    def _block(
        mission: dict[str, Any], code: str, stage: str, detail: str | None = None
    ) -> None:
        blocker = {"code": code, "stage": stage}
        if detail:
            blocker["detail"] = detail[:500]
        mission["blockers"].append(blocker)
        mission["validation"] = {
            "valid": False,
            "blockers": [item["code"] for item in mission["blockers"]],
        }
        mission["publication_eligibility"] = {
            "eligible": False,
            "automatic_publication": False,
            "blockers": [item["code"] for item in mission["blockers"]]
            + ["HUMAN_REVIEW_REQUIRED"],
        }
        mission["state"] = "BLOCKED"
        mission["partial"] = True

    @staticmethod
    def _apply(
        stage: str, output: Any, mission: dict[str, Any], max_sources: int
    ) -> None:
        if not isinstance(output, dict):
            raise TypeError("MISSION_COMPONENT_OUTPUT_MUST_BE_MAPPING")
        mission["artifacts"].update(deepcopy(output.get("artifacts", {})))
        if stage == "evidence_retrieval":
            results = output.get("results", [])
            mission["sources"] = list(results)[:max_sources]
        elif stage == "evidence_aggregation":
            mission["supporting_evidence"] = list(output.get("supporting_evidence", []))
            mission["contradicting_evidence"] = list(
                output.get("contradicting_evidence", [])
            )
        elif stage == "contradiction_and_gap_analysis":
            mission["contradicting_evidence"] = list(
                output.get("contradicting_evidence", mission["contradicting_evidence"])
            )
            mission["missing_evidence"] = list(output.get("missing_evidence", []))
        elif stage == "scientific_interpretation":
            mission["confidence"] = output.get("confidence")
            mission["conclusions"] = list(output.get("conclusions", []))
        elif stage == "reasoning_ledger_creation":
            ledger_id = output.get("ledger_id")
            version = output.get("version")
            if not ledger_id or version is None:
                raise ValueError("REASONING_LEDGER_ID_AND_VERSION_REQUIRED")
            mission["reasoning_ledger"] = {
                "ledger_id": str(ledger_id),
                "version": version,
            }
        elif stage == "validation":
            mission["validation"] = {
                "valid": bool(output.get("valid")),
                "blockers": list(output.get("blockers", [])),
            }
        elif stage == "human_review_state":
            mission["review_status"] = str(
                output.get("status") or "HUMAN_REVIEW_REQUIRED"
            )
        elif stage == "eligible_for_publication_state":
            eligible = (
                bool(output.get("eligible"))
                and mission["review_status"] == "APPROVED"
                and mission["validation"]["valid"]
            )
            mission["publication_eligibility"] = {
                "eligible": eligible,
                "automatic_publication": False,
                "blockers": []
                if eligible
                else list(output.get("blockers", [])) or ["HUMAN_REVIEW_REQUIRED"],
            }

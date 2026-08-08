"""Governed Mission Control harvester command-center adapter for CALYX issue #455.

This module projects the existing BUILD-049 harvester control plane into a stable,
iPad-safe operator contract. Preview is strictly read-only. Mutating adapters require
explicit confirmation and continue to rely on the control plane's constitutional
authorization checks.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Protocol

from runtime.harvester_control import (
    HarvesterControlPlane,
    control_plane,
    harvester_allowed_actions,
)

COMMAND_CENTER_SCHEMA = "calyx-harvester-command-center/v1"
ACTIONS = {"run_once", "pause", "resume", "cancel", "reschedule", "retire", "restore", "reassess"}
HIGH_RISK = {"reschedule", "retire", "restore"}


class Plane(Protocol):
    def list_harvesters(self) -> list[dict[str, Any]]: ...
    def get_harvester(self, harvester_id: str) -> dict[str, Any]: ...
    def get_runs(self, harvester_id: str) -> list[dict[str, Any]]: ...
    def run_once(self, harvester_id: str, actor: str, execute: bool = False) -> dict[str, Any]: ...
    def pause(self, harvester_id: str, actor: str) -> dict[str, Any]: ...
    def resume(self, harvester_id: str, actor: str) -> dict[str, Any]: ...
    def cancel_run(self, harvester_id: str, actor: str) -> dict[str, Any]: ...
    def reschedule(self, harvester_id: str, schedule: str, actor: str) -> dict[str, Any]: ...
    def retire(self, harvester_id: str, actor: str) -> dict[str, Any]: ...
    def restore(self, harvester_id: str, actor: str) -> dict[str, Any]: ...
    def reassess(self, harvester_id: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class CommandError(Exception):
    code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def _confirmation(action: str) -> dict[str, Any]:
    high = action in HIGH_RISK
    return {
        "required": True,
        "risk": "high" if high else "low",
        "phrase_required": f"CONFIRM {action.upper()}" if high else None,
    }


def _last_outcomes(runs: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    success = next((run for run in runs if run.get("status") == "success"), None)
    failure = next((run for run in runs if run.get("status") == "failed"), None)
    return success, failure


def _card(record: dict[str, Any], runs: list[dict[str, Any]]) -> dict[str, Any]:
    success, failure = _last_outcomes(runs)
    examined = record.get("rows_examined")
    inserted = record.get("rows_inserted")
    progress = None
    if isinstance(examined, int) and examined > 0 and isinstance(inserted, int):
        progress = {"examined": examined, "inserted": inserted, "yield_rate": round(inserted / examined, 6)}
    return {
        "harvester_id": record.get("harvester_id") or record.get("id"),
        "name": record.get("display_name") or record.get("name"),
        "source": record.get("connector_source_id") or record.get("source"),
        "state": record.get("operational_state") or record.get("state"),
        "enabled": bool(record.get("enabled", True)),
        "schedule": record.get("schedule"),
        "checkpoint": record.get("checkpoint_cursor") or record.get("checkpoint") or "unknown",
        "next_run": record.get("next_scheduled_run") or record.get("nextRun") or "unknown",
        "last_attempt": record.get("last_attempted_run"),
        "last_success": (success or {}).get("ended_at") or record.get("last_successful_run"),
        "last_failure": (failure or {}).get("ended_at"),
        "progress": progress,
        "recommendation": record.get("current_recommendation"),
        "recommendation_rationale": record.get("recommendation_rationale"),
        "warnings": list(record.get("warnings") or []),
        "errors": list(record.get("errors") or []),
        "allowed_actions": {
            action: {**contract, "confirmation": _confirmation(_wire_action(action))}
            for action, contract in harvester_allowed_actions().items()
            if _wire_action(action) in ACTIONS
        },
    }


def _wire_action(action: str) -> str:
    aliases = {"runOnce": "run_once", "changeSchedule": "reschedule"}
    return aliases.get(action, action)


class HarvesterCommandCenter:
    def __init__(self, plane: Plane | None = None) -> None:
        self.plane = plane or control_plane

    def list_state(self) -> dict[str, Any]:
        cards = []
        for record in self.plane.list_harvesters():
            harvester_id = str(record.get("harvester_id") or record.get("id"))
            cards.append(_card(record, self.plane.get_runs(harvester_id)))
        cards.sort(key=lambda item: (str(item["name"]).casefold(), str(item["harvester_id"])))
        return self._envelope({"harvesters": cards, "count": len(cards)})

    def detail(self, harvester_id: str) -> dict[str, Any]:
        record = self.plane.get_harvester(harvester_id)
        runs = self.plane.get_runs(harvester_id)
        return self._envelope({"harvester": _card(record, runs), "recent_runs": runs[:10]})

    def preview(self, harvester_id: str, action: str, *, schedule: str | None = None) -> dict[str, Any]:
        action = action.strip().casefold()
        if action not in ACTIONS:
            raise CommandError("ACTION_UNSUPPORTED", f"Unsupported harvester action: {action}")
        before = copy.deepcopy(self.plane.get_harvester(harvester_id))
        runs_before = copy.deepcopy(self.plane.get_runs(harvester_id))
        proposed = self._proposed_effect(before, action, schedule=schedule)
        after = self.plane.get_harvester(harvester_id)
        runs_after = self.plane.get_runs(harvester_id)
        no_write = before == after and runs_before == runs_after
        if not no_write:
            raise CommandError("PREVIEW_WRITE_DETECTED", "Preview changed harvester state; operation aborted")
        return self._envelope({
            "preview": True,
            "no_write_proof": {"verified": True, "state_unchanged": True, "run_history_unchanged": True},
            "harvester_id": harvester_id,
            "action": action,
            "current_state": _card(before, runs_before),
            "proposed_effect": proposed,
            "confirmation": _confirmation(action),
        })

    def execute(
        self,
        harvester_id: str,
        action: str,
        actor: str,
        *,
        confirmed: bool,
        confirmation_phrase: str | None = None,
        schedule: str | None = None,
    ) -> dict[str, Any]:
        action = action.strip().casefold()
        if action not in ACTIONS:
            raise CommandError("ACTION_UNSUPPORTED", f"Unsupported harvester action: {action}")
        if not confirmed:
            raise CommandError("CONFIRMATION_REQUIRED", f"Explicit confirmation is required for {action}")
        required = _confirmation(action)["phrase_required"]
        if required and confirmation_phrase != required:
            raise CommandError("CONFIRMATION_PHRASE_REQUIRED", f"Confirmation phrase must be exactly: {required}")
        if action == "reschedule" and not (schedule or "").strip():
            raise CommandError("SCHEDULE_REQUIRED", "A non-empty schedule is required for reschedule")
        try:
            result = self._invoke(harvester_id, action, actor, schedule=schedule)
        except KeyError as exc:
            raise CommandError("HARVESTER_NOT_FOUND", f"Unknown harvester: {exc.args[0]}") from exc
        except ValueError as exc:
            raise CommandError("ACTION_REJECTED", str(exc)) from exc
        return self._envelope({
            "preview": False,
            "harvester_id": harvester_id,
            "action": action,
            "result": result,
            "confirmation_recorded": True,
            "production_provider_scrape_performed": False,
        })

    def readiness(self) -> dict[str, Any]:
        state = self.list_state()
        warnings = sum(len(item["warnings"]) for item in state["data"]["harvesters"])
        return self._envelope({
            "decision": "HARVESTER_COMMAND_CENTER_REVIEW_READY",
            "harvester_count": state["data"]["count"],
            "warning_count": warnings,
            "preview_no_write_enforced": True,
            "explicit_confirmation_enforced": True,
            "high_risk_phrase_confirmation_enforced": True,
            "authorization_required": True,
            "ipad_safe_contract": True,
            "secrets_exposed": False,
            "provider_scraping_from_command_center": False,
            "production_deployment_authorized": False,
            "production_data_test_mutation_authorized": False,
        })

    def _invoke(self, harvester_id: str, action: str, actor: str, *, schedule: str | None) -> dict[str, Any]:
        if action == "run_once":
            return self.plane.run_once(harvester_id, actor, execute=False)
        if action == "pause":
            return self.plane.pause(harvester_id, actor)
        if action == "resume":
            return self.plane.resume(harvester_id, actor)
        if action == "cancel":
            return self.plane.cancel_run(harvester_id, actor)
        if action == "reschedule":
            return self.plane.reschedule(harvester_id, str(schedule), actor)
        if action == "retire":
            return self.plane.retire(harvester_id, actor)
        if action == "restore":
            return self.plane.restore(harvester_id, actor)
        return self.plane.reassess(harvester_id)

    @staticmethod
    def _proposed_effect(record: dict[str, Any], action: str, *, schedule: str | None) -> dict[str, Any]:
        states = {"pause": "paused", "resume": "active", "retire": "retired", "restore": "active"}
        effect: dict[str, Any] = {"state": states.get(action, record.get("state") or record.get("operational_state"))}
        if action == "run_once":
            effect.update({"run_history": "append_queued_run", "provider_execution": False})
        elif action == "cancel":
            effect.update({"run_history": "cancel_most_recent_queued_or_running"})
        elif action == "reschedule":
            effect.update({"schedule": schedule})
        elif action == "reassess":
            effect.update({"recommendation": "recompute_from_existing_telemetry"})
        return effect

    @staticmethod
    def _envelope(data: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": COMMAND_CENTER_SCHEMA,
            "surface": "mission_control.harvesters",
            "display_contract": "ipad_safe_v1",
            "data": data,
        }


__all__ = ["COMMAND_CENTER_SCHEMA", "CommandError", "HarvesterCommandCenter", "HarvesterControlPlane"]

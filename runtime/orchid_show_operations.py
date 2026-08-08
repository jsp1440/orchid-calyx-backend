"""Owner-scoped orchid show, entry, judging, award, and event operations.

All judging and award decisions are human-authored. Entered label text is preserved
separately from canonical accepted-name display, and personal data remains private.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from runtime.volunteer_service import VolunteerService

SCHEMA_VERSION = "calyx-orchid-show/v1"
DECISION_TYPES = {"ribbon", "trophy", "special_award", "no_award"}
ENTRY_STATES = {"entered", "checked_in", "withdrawn", "judged"}


def show_root() -> Path:
    return Path(os.environ.get("CALYX_SHOW_WORKSPACE", "/tmp/calyx/orchid-shows"))


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _text(value: object) -> str:
    return str(value or "").strip()


def _record_id(value: object, code: str) -> str:
    record_id = _text(value)
    if (
        not record_id
        or record_id in {".", ".."}
        or "/" in record_id
        or "\\" in record_id
        or "\x00" in record_id
    ):
        raise ValueError(code)
    return record_id


def _owner_key(owner_id: str) -> str:
    owner = _text(owner_id)
    if not owner:
        raise ValueError("SHOW_OWNER_REQUIRED")
    return hashlib.sha256(owner.casefold().encode()).hexdigest()[:20]


def _stable(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(payload: Any) -> str:
    return hashlib.sha256(_stable(payload).encode("utf-8")).hexdigest()


class OrchidShowOperations:
    def __init__(
        self,
        workspace: Path | None = None,
        *,
        volunteers: VolunteerService | None = None,
    ) -> None:
        self.workspace = workspace or show_root()
        self.volunteers = volunteers or VolunteerService()

    def _owner_root(self, owner_id: str) -> Path:
        root = self.workspace / "owners" / _owner_key(owner_id)
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _show_root(self, owner_id: str, show_id: str) -> Path:
        safe_id = _record_id(show_id, "SHOW_ID_INVALID")
        return self._owner_root(owner_id) / "shows" / safe_id

    @staticmethod
    def _write(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )
        return payload

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(path.stem)
        return json.loads(path.read_text(encoding="utf-8"))

    def _audit(
        self,
        owner_id: str,
        show_id: str,
        *,
        actor: str,
        event_type: str,
        subject_id: str,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        root = self._show_root(owner_id, show_id)
        path = root / "audit.json"
        payload = self._read(path) if path.exists() else {"events": []}
        event = {
            "event_type": event_type,
            "subject_id": subject_id,
            "actor": _text(actor),
            "at": _now(),
            "details": details,
        }
        event["event_hash"] = _digest(event)
        payload["events"].append(event)
        self._write(path, payload)
        return event

    def create_show(
        self,
        owner_id: str,
        payload: dict[str, Any],
        *,
        actor: str,
    ) -> dict[str, Any]:
        show_id = _record_id(payload.get("show_id"), "SHOW_ID_INVALID")
        name = _text(payload.get("name"))
        if not name:
            raise ValueError("SHOW_NAME_REQUIRED")
        record = {
            "schema_version": SCHEMA_VERSION,
            "show_id": show_id,
            "name": name,
            "organization_name": _text(payload.get("organization_name")) or None,
            "venue": _text(payload.get("venue")) or None,
            "starts_at": _text(payload.get("starts_at")) or None,
            "ends_at": _text(payload.get("ends_at")) or None,
            "status": "planning",
            "public_personal_data_authorized": False,
            "autonomous_awards_authorized": False,
            "payment_processing_authorized": False,
            "created_at": _now(),
        }
        self._write(self._show_root(owner_id, show_id) / "show.json", record)
        self._audit(
            owner_id,
            show_id,
            actor=actor,
            event_type="show_created",
            subject_id=show_id,
            details={"name": name},
        )
        return record

    def get_show(self, owner_id: str, show_id: str) -> dict[str, Any]:
        return self._read(self._show_root(owner_id, show_id) / "show.json")

    def add_exhibitor(
        self,
        owner_id: str,
        show_id: str,
        payload: dict[str, Any],
        *,
        actor: str,
    ) -> dict[str, Any]:
        self.get_show(owner_id, show_id)
        exhibitor_id = _record_id(payload.get("exhibitor_id"), "EXHIBITOR_ID_INVALID")
        display_name = _text(payload.get("display_name"))
        if not display_name:
            raise ValueError("EXHIBITOR_DISPLAY_NAME_REQUIRED")
        record = {
            "schema_version": SCHEMA_VERSION,
            "exhibitor_id": exhibitor_id,
            "display_name": display_name,
            "organization": _text(payload.get("organization")) or None,
            "contact": dict(payload.get("contact") or {}),
            "public_contact_authorized": False,
            "created_at": _now(),
        }
        self._write(
            self._show_root(owner_id, show_id) / "exhibitors" / f"{exhibitor_id}.json",
            record,
        )
        self._audit(
            owner_id,
            show_id,
            actor=actor,
            event_type="exhibitor_added",
            subject_id=exhibitor_id,
            details={"display_name": display_name},
        )
        return record

    def add_entry_class(
        self,
        owner_id: str,
        show_id: str,
        payload: dict[str, Any],
        *,
        actor: str,
    ) -> dict[str, Any]:
        self.get_show(owner_id, show_id)
        class_id = _record_id(payload.get("class_id"), "ENTRY_CLASS_ID_INVALID")
        name = _text(payload.get("name"))
        if not name:
            raise ValueError("ENTRY_CLASS_NAME_REQUIRED")
        record = {
            "schema_version": SCHEMA_VERSION,
            "class_id": class_id,
            "name": name,
            "description": _text(payload.get("description")) or None,
            "eligibility_rules": list(payload.get("eligibility_rules") or []),
            "created_at": _now(),
        }
        self._write(
            self._show_root(owner_id, show_id) / "classes" / f"{class_id}.json",
            record,
        )
        self._audit(
            owner_id,
            show_id,
            actor=actor,
            event_type="entry_class_added",
            subject_id=class_id,
            details={"name": name},
        )
        return record

    def add_entry(
        self,
        owner_id: str,
        show_id: str,
        payload: dict[str, Any],
        *,
        actor: str,
    ) -> dict[str, Any]:
        self.get_show(owner_id, show_id)
        entry_id = _record_id(payload.get("entry_id"), "SHOW_ENTRY_ID_INVALID")
        exhibitor_id = _record_id(
            payload.get("exhibitor_id"),
            "EXHIBITOR_ID_INVALID",
        )
        class_id = _record_id(payload.get("class_id"), "ENTRY_CLASS_ID_INVALID")
        self._read(
            self._show_root(owner_id, show_id) / "exhibitors" / f"{exhibitor_id}.json"
        )
        self._read(self._show_root(owner_id, show_id) / "classes" / f"{class_id}.json")
        entered_label = _text(payload.get("entered_label_text"))
        if not entered_label:
            raise ValueError("SHOW_ENTRY_LABEL_REQUIRED")
        canonical_taxon_id = _text(payload.get("canonical_taxon_id")) or None
        accepted_display = _text(payload.get("accepted_name_display")) or None
        taxonomy_state = "resolved" if canonical_taxon_id and accepted_display else "review_required"
        record = {
            "schema_version": SCHEMA_VERSION,
            "entry_id": entry_id,
            "exhibitor_id": exhibitor_id,
            "class_id": class_id,
            "entered_label_text": entered_label,
            "canonical_taxon_id": canonical_taxon_id,
            "accepted_name_display": accepted_display,
            "taxonomy_state": taxonomy_state,
            "cultivar_or_clone": _text(payload.get("cultivar_or_clone")) or None,
            "media_artifact_ids": sorted(
                {_text(item) for item in payload.get("media_artifact_ids", []) if _text(item)}
            ),
            "media_review_state": _text(payload.get("media_review_state")) or "not_supplied",
            "state": "entered",
            "created_at": _now(),
            "autonomous_identification_authorized": False,
        }
        self._write(
            self._show_root(owner_id, show_id) / "entries" / f"{entry_id}.json",
            record,
        )
        self._audit(
            owner_id,
            show_id,
            actor=actor,
            event_type="entry_added",
            subject_id=entry_id,
            details={
                "entered_label_text": entered_label,
                "accepted_name_display": accepted_display,
                "taxonomy_state": taxonomy_state,
            },
        )
        return record

    def update_entry_state(
        self,
        owner_id: str,
        show_id: str,
        entry_id: str,
        state: str,
        *,
        actor: str,
        rationale: str,
    ) -> dict[str, Any]:
        if state not in ENTRY_STATES:
            raise ValueError("SHOW_ENTRY_STATE_INVALID")
        if not _text(rationale):
            raise ValueError("SHOW_ENTRY_STATE_RATIONALE_REQUIRED")
        safe_id = _record_id(entry_id, "SHOW_ENTRY_ID_INVALID")
        path = self._show_root(owner_id, show_id) / "entries" / f"{safe_id}.json"
        record = self._read(path)
        previous = record["state"]
        record["state"] = state
        self._write(path, record)
        self._audit(
            owner_id,
            show_id,
            actor=actor,
            event_type="entry_state_changed",
            subject_id=safe_id,
            details={"from": previous, "to": state, "rationale": rationale.strip()},
        )
        return record

    def add_judging_team(
        self,
        owner_id: str,
        show_id: str,
        payload: dict[str, Any],
        *,
        actor: str,
    ) -> dict[str, Any]:
        self.get_show(owner_id, show_id)
        team_id = _record_id(payload.get("team_id"), "JUDGING_TEAM_ID_INVALID")
        judges = sorted({_text(item) for item in payload.get("judge_ids", []) if _text(item)})
        if not judges:
            raise ValueError("JUDGING_TEAM_JUDGE_REQUIRED")
        record = {
            "schema_version": SCHEMA_VERSION,
            "team_id": team_id,
            "judge_ids": judges,
            "class_ids": sorted(
                {_text(item) for item in payload.get("class_ids", []) if _text(item)}
            ),
            "conflicts": list(payload.get("conflicts") or []),
            "human_judging_required": True,
            "created_at": _now(),
        }
        self._write(
            self._show_root(owner_id, show_id) / "judging_teams" / f"{team_id}.json",
            record,
        )
        self._audit(
            owner_id,
            show_id,
            actor=actor,
            event_type="judging_team_added",
            subject_id=team_id,
            details={"judge_count": len(judges)},
        )
        return record

    def record_judging_decision(
        self,
        owner_id: str,
        show_id: str,
        payload: dict[str, Any],
        *,
        actor: str,
    ) -> dict[str, Any]:
        decision_id = _record_id(
            payload.get("decision_id"),
            "JUDGING_DECISION_ID_INVALID",
        )
        entry_id = _record_id(payload.get("entry_id"), "SHOW_ENTRY_ID_INVALID")
        team_id = _record_id(payload.get("team_id"), "JUDGING_TEAM_ID_INVALID")
        decision_type = _text(payload.get("decision_type"))
        if decision_type not in DECISION_TYPES:
            raise ValueError("JUDGING_DECISION_TYPE_INVALID")
        if payload.get("human_decision") is not True:
            raise ValueError("HUMAN_JUDGING_DECISION_REQUIRED")
        rationale = _text(payload.get("rationale"))
        if not rationale:
            raise ValueError("JUDGING_DECISION_RATIONALE_REQUIRED")
        entry = self._read(
            self._show_root(owner_id, show_id) / "entries" / f"{entry_id}.json"
        )
        team = self._read(
            self._show_root(owner_id, show_id)
            / "judging_teams"
            / f"{team_id}.json"
        )
        deciding_judges = sorted(
            {_text(item) for item in payload.get("deciding_judge_ids", []) if _text(item)}
        )
        if not deciding_judges or not set(deciding_judges).issubset(set(team["judge_ids"])):
            raise ValueError("JUDGING_DECISION_JUDGE_INVALID")
        conflicts = list(payload.get("conflicts") or [])
        conflict_resolution = _text(payload.get("conflict_resolution")) or None
        if conflicts and not conflict_resolution:
            raise ValueError("JUDGING_CONFLICT_RESOLUTION_REQUIRED")
        award_name = _text(payload.get("award_name")) or None
        if decision_type != "no_award" and not award_name:
            raise ValueError("JUDGING_AWARD_NAME_REQUIRED")
        record = {
            "schema_version": SCHEMA_VERSION,
            "decision_id": decision_id,
            "entry_id": entry_id,
            "team_id": team_id,
            "decision_type": decision_type,
            "award_name": award_name,
            "placement": _text(payload.get("placement")) or None,
            "deciding_judge_ids": deciding_judges,
            "rationale": rationale,
            "conflicts": conflicts,
            "conflict_resolution": conflict_resolution,
            "human_decision": True,
            "autonomous_award_authorized": False,
            "decided_at": _now(),
            "entered_label_text": entry["entered_label_text"],
            "accepted_name_display": entry.get("accepted_name_display"),
        }
        record["decision_hash"] = _digest(record)
        self._write(
            self._show_root(owner_id, show_id) / "decisions" / f"{decision_id}.json",
            record,
        )
        self.update_entry_state(
            owner_id,
            show_id,
            entry_id,
            "judged",
            actor=actor,
            rationale=f"Human judging decision {decision_id} recorded.",
        )
        self._audit(
            owner_id,
            show_id,
            actor=actor,
            event_type="judging_decision_recorded",
            subject_id=decision_id,
            details={
                "entry_id": entry_id,
                "decision_type": decision_type,
                "award_name": award_name,
                "decision_hash": record["decision_hash"],
            },
        )
        return record

    def add_schedule_item(
        self,
        owner_id: str,
        show_id: str,
        payload: dict[str, Any],
        *,
        actor: str,
    ) -> dict[str, Any]:
        item_id = _record_id(payload.get("item_id"), "SHOW_SCHEDULE_ITEM_ID_INVALID")
        title = _text(payload.get("title"))
        if not title:
            raise ValueError("SHOW_SCHEDULE_TITLE_REQUIRED")
        record = {
            "schema_version": SCHEMA_VERSION,
            "item_id": item_id,
            "title": title,
            "starts_at": _text(payload.get("starts_at")) or None,
            "ends_at": _text(payload.get("ends_at")) or None,
            "location": _text(payload.get("location")) or None,
            "notes": _text(payload.get("notes")) or None,
        }
        self._write(
            self._show_root(owner_id, show_id) / "schedule" / f"{item_id}.json",
            record,
        )
        self._audit(
            owner_id,
            show_id,
            actor=actor,
            event_type="schedule_item_added",
            subject_id=item_id,
            details={"title": title},
        )
        return record

    def add_vendor(
        self,
        owner_id: str,
        show_id: str,
        payload: dict[str, Any],
        *,
        actor: str,
    ) -> dict[str, Any]:
        vendor_id = _record_id(payload.get("vendor_id"), "SHOW_VENDOR_ID_INVALID")
        name = _text(payload.get("name"))
        if not name:
            raise ValueError("SHOW_VENDOR_NAME_REQUIRED")
        record = {
            "schema_version": SCHEMA_VERSION,
            "vendor_id": vendor_id,
            "name": name,
            "contact": dict(payload.get("contact") or {}),
            "booth": _text(payload.get("booth")) or None,
            "payment_state": "not_managed_by_calyx",
            "payment_processing_authorized": False,
            "public_contact_authorized": False,
        }
        self._write(
            self._show_root(owner_id, show_id) / "vendors" / f"{vendor_id}.json",
            record,
        )
        self._audit(
            owner_id,
            show_id,
            actor=actor,
            event_type="vendor_added",
            subject_id=vendor_id,
            details={"name": name},
        )
        return record

    def assign_volunteer(
        self,
        owner_id: str,
        show_id: str,
        payload: dict[str, Any],
        *,
        actor: str,
    ) -> dict[str, Any]:
        assignment_id = _record_id(
            payload.get("assignment_id"),
            "SHOW_VOLUNTEER_ASSIGNMENT_ID_INVALID",
        )
        volunteer_id = _record_id(
            payload.get("volunteer_id"),
            "VOLUNTEER_ID_INVALID",
        )
        profile = self.volunteers.get_profile(owner_id, volunteer_id)
        role = _text(payload.get("role"))
        if not role:
            raise ValueError("SHOW_VOLUNTEER_ROLE_REQUIRED")
        record = {
            "schema_version": SCHEMA_VERSION,
            "assignment_id": assignment_id,
            "volunteer_id": volunteer_id,
            "volunteer_display_name": profile["display_name"],
            "role": role,
            "starts_at": _text(payload.get("starts_at")) or None,
            "ends_at": _text(payload.get("ends_at")) or None,
            "location": _text(payload.get("location")) or None,
            "binding_commitment_authorized": False,
        }
        self._write(
            self._show_root(owner_id, show_id)
            / "volunteer_assignments"
            / f"{assignment_id}.json",
            record,
        )
        self._audit(
            owner_id,
            show_id,
            actor=actor,
            event_type="show_volunteer_assigned",
            subject_id=assignment_id,
            details={"volunteer_id": volunteer_id, "role": role},
        )
        return record

    def printable_entry_label(
        self,
        owner_id: str,
        show_id: str,
        entry_id: str,
    ) -> dict[str, Any]:
        safe_id = _record_id(entry_id, "SHOW_ENTRY_ID_INVALID")
        entry = self._read(
            self._show_root(owner_id, show_id) / "entries" / f"{safe_id}.json"
        )
        exhibitor = self._read(
            self._show_root(owner_id, show_id)
            / "exhibitors"
            / f"{entry['exhibitor_id']}.json"
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "entry_id": safe_id,
            "class_id": entry["class_id"],
            "entered_label_text": entry["entered_label_text"],
            "accepted_name_display": entry.get("accepted_name_display"),
            "exhibitor_display_name": exhibitor["display_name"],
            "printable": True,
            "contains_private_contact": False,
        }

    def results_export(self, owner_id: str, show_id: str) -> dict[str, Any]:
        root = self._show_root(owner_id, show_id)
        show = self.get_show(owner_id, show_id)
        entries = (
            [self._read(path) for path in sorted((root / "entries").glob("*.json"))]
            if (root / "entries").exists()
            else []
        )
        decisions = (
            [self._read(path) for path in sorted((root / "decisions").glob("*.json"))]
            if (root / "decisions").exists()
            else []
        )
        exhibitors: dict[str, dict[str, Any]] = {}
        exhibitor_dir = root / "exhibitors"
        if exhibitor_dir.exists():
            for path in sorted(exhibitor_dir.glob("*.json")):
                item = self._read(path)
                exhibitors[item["exhibitor_id"]] = {
                    "exhibitor_id": item["exhibitor_id"],
                    "display_name": item["display_name"],
                    "organization": item.get("organization"),
                }
        public_entries = []
        for entry in entries:
            public_entries.append(
                {
                    "entry_id": entry["entry_id"],
                    "class_id": entry["class_id"],
                    "entered_label_text": entry["entered_label_text"],
                    "accepted_name_display": entry.get("accepted_name_display"),
                    "taxonomy_state": entry["taxonomy_state"],
                    "exhibitor": exhibitors.get(entry["exhibitor_id"]),
                }
            )
        return {
            "schema_version": SCHEMA_VERSION,
            "show": {
                "show_id": show["show_id"],
                "name": show["name"],
                "starts_at": show.get("starts_at"),
            },
            "entries": public_entries,
            "judging_decisions": decisions,
            "public_personal_data_included": False,
            "payment_data_included": False,
            "autonomous_awards": False,
        }

    def audit_history(self, owner_id: str, show_id: str) -> dict[str, Any]:
        path = self._show_root(owner_id, show_id) / "audit.json"
        payload = self._read(path) if path.exists() else {"events": []}
        return {
            "schema_version": SCHEMA_VERSION,
            "show_id": _record_id(show_id, "SHOW_ID_INVALID"),
            "events": payload["events"],
            "read_only": True,
        }

    def readiness(self, owner_id: str, show_id: str) -> dict[str, Any]:
        root = self._show_root(owner_id, show_id)
        self.get_show(owner_id, show_id)
        entries = (
            [self._read(path) for path in (root / "entries").glob("*.json")]
            if (root / "entries").exists()
            else []
        )
        decisions = (
            [self._read(path) for path in (root / "decisions").glob("*.json")]
            if (root / "decisions").exists()
            else []
        )
        unresolved_taxonomy = [
            item["entry_id"] for item in entries if item["taxonomy_state"] != "resolved"
        ]
        return {
            "schema_version": SCHEMA_VERSION,
            "show_id": _record_id(show_id, "SHOW_ID_INVALID"),
            "entry_count": len(entries),
            "human_judging_decision_count": len(decisions),
            "taxonomy_review_required_entry_ids": sorted(unresolved_taxonomy),
            "human_judging_required": True,
            "autonomous_awards_authorized": False,
            "payment_processing_authorized": False,
            "public_personal_data_authorized": False,
            "production_deployment_authorized": False,
        }

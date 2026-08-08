"""Owner-scoped volunteer service, hours, skills, training, and recognition for CALYX #472.

The service is private-by-default, preserves supervisor verification and audit history,
registers certificates as immutable artifacts, and never makes autonomous disciplinary
or binding personnel decisions.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.calyx_orchestrator.artifact_registry import ArtifactRegistration, ImmutableArtifactRegistry

SCHEMA_VERSION = "calyx-volunteer-service/v1"
HOUR_STATES = {"submitted", "verified", "rejected_for_correction"}
ASSIGNMENT_STATES = {"planned", "active", "completed", "cancelled"}
PRIVACY_LEVELS = {"private", "organization_internal"}


def volunteer_root() -> Path:
    return Path(os.environ.get("CALYX_VOLUNTEER_WORKSPACE", "/tmp/calyx/volunteers"))


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _text(value: object) -> str:
    return str(value or "").strip()


def _owner_key(owner_id: str) -> str:
    owner = _text(owner_id)
    if not owner:
        raise ValueError("VOLUNTEER_OWNER_REQUIRED")
    return hashlib.sha256(owner.casefold().encode()).hexdigest()[:20]


def _stable(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(payload: Any) -> str:
    return hashlib.sha256(_stable(payload).encode("utf-8")).hexdigest()


class VolunteerService:
    def __init__(self, workspace: Path | None = None, *, artifacts: ImmutableArtifactRegistry | None = None) -> None:
        self.workspace = workspace or volunteer_root()
        self.artifacts = artifacts or ImmutableArtifactRegistry()

    def _root(self, owner_id: str) -> Path:
        root = self.workspace / "owners" / _owner_key(owner_id)
        root.mkdir(parents=True, exist_ok=True)
        return root

    @staticmethod
    def _write(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
        return payload

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(path.stem)
        return json.loads(path.read_text(encoding="utf-8"))

    def save_profile(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        volunteer_id = _text(payload.get("volunteer_id"))
        display_name = _text(payload.get("display_name"))
        if not volunteer_id or not display_name:
            raise ValueError("VOLUNTEER_PROFILE_REQUIRED_FIELDS")
        privacy = _text(payload.get("privacy_level")) or "private"
        if privacy not in PRIVACY_LEVELS:
            raise ValueError("VOLUNTEER_PRIVACY_LEVEL_INVALID")
        record = {
            "schema_version": SCHEMA_VERSION,
            "volunteer_id": volunteer_id,
            "display_name": display_name,
            "contact": payload.get("contact") or {},
            "roles": sorted({_text(item) for item in payload.get("roles", []) if _text(item)}),
            "skills": sorted({_text(item) for item in payload.get("skills", []) if _text(item)}),
            "availability": list(payload.get("availability") or []),
            "accessibility_or_support_notes": _text(payload.get("accessibility_or_support_notes")) or None,
            "privacy_level": privacy,
            "public_profile_authorized": False,
            "autonomous_disciplinary_decision_authorized": False,
            "updated_at": _now(),
        }
        return self._write(self._root(owner_id) / "profiles" / f"{volunteer_id}.json", record)

    def get_profile(self, owner_id: str, volunteer_id: str) -> dict[str, Any]:
        return self._read(self._root(owner_id) / "profiles" / f"{volunteer_id}.json")

    def create_assignment(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        assignment_id = _text(payload.get("assignment_id"))
        volunteer_id = _text(payload.get("volunteer_id"))
        role = _text(payload.get("role"))
        title = _text(payload.get("title"))
        if not all((assignment_id, volunteer_id, role, title)):
            raise ValueError("VOLUNTEER_ASSIGNMENT_FIELDS_REQUIRED")
        profile = self.get_profile(owner_id, volunteer_id)
        required_skills = sorted({_text(item) for item in payload.get("required_skills", []) if _text(item)})
        missing_skills = sorted(set(required_skills) - set(profile["skills"]))
        record = {
            "schema_version": SCHEMA_VERSION,
            "assignment_id": assignment_id,
            "volunteer_id": volunteer_id,
            "title": title,
            "role": role,
            "description": _text(payload.get("description")) or None,
            "required_skills": required_skills,
            "missing_skills": missing_skills,
            "starts_at": _text(payload.get("starts_at")) or None,
            "ends_at": _text(payload.get("ends_at")) or None,
            "supervisor_id": _text(payload.get("supervisor_id")) or None,
            "state": "planned",
            "conflicts": list(payload.get("conflicts") or []),
            "binding_commitment_authorized": False,
            "created_at": _now(),
        }
        if missing_skills:
            record["readiness"] = "training_or_review_required"
        else:
            record["readiness"] = "assignment_ready"
        return self._write(self._root(owner_id) / "assignments" / f"{assignment_id}.json", record)

    def update_assignment_state(self, owner_id: str, assignment_id: str, state: str, *, actor: str, rationale: str) -> dict[str, Any]:
        if state not in ASSIGNMENT_STATES:
            raise ValueError("VOLUNTEER_ASSIGNMENT_STATE_INVALID")
        if not _text(rationale):
            raise ValueError("VOLUNTEER_ASSIGNMENT_RATIONALE_REQUIRED")
        path = self._root(owner_id) / "assignments" / f"{assignment_id}.json"
        record = self._read(path)
        history = list(record.get("state_history") or [])
        history.append({"from": record["state"], "to": state, "actor": actor, "rationale": rationale.strip(), "at": _now()})
        record["state"] = state
        record["state_history"] = history
        return self._write(path, record)

    def log_hours(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        log_id = _text(payload.get("log_id"))
        volunteer_id = _text(payload.get("volunteer_id"))
        assignment_id = _text(payload.get("assignment_id"))
        service_date = _text(payload.get("service_date"))
        hours = float(payload.get("hours", 0))
        if not all((log_id, volunteer_id, assignment_id, service_date)) or hours <= 0 or hours > 24:
            raise ValueError("VOLUNTEER_HOUR_LOG_INVALID")
        assignment = self._read(self._root(owner_id) / "assignments" / f"{assignment_id}.json")
        if assignment["volunteer_id"] != volunteer_id:
            raise ValueError("VOLUNTEER_ASSIGNMENT_PROFILE_MISMATCH")
        record = {
            "schema_version": SCHEMA_VERSION,
            "log_id": log_id,
            "volunteer_id": volunteer_id,
            "assignment_id": assignment_id,
            "service_date": service_date,
            "hours": round(hours, 2),
            "activity": _text(payload.get("activity")) or assignment["title"],
            "state": "submitted",
            "submitted_at": _now(),
            "verification": None,
            "autonomous_verification_authorized": False,
        }
        return self._write(self._root(owner_id) / "hours" / f"{log_id}.json", record)

    def verify_hours(self, owner_id: str, log_id: str, *, supervisor_id: str, decision: str, rationale: str) -> dict[str, Any]:
        if decision not in {"verified", "rejected_for_correction"}:
            raise ValueError("VOLUNTEER_HOUR_VERIFICATION_DECISION_INVALID")
        if not _text(supervisor_id) or not _text(rationale):
            raise ValueError("VOLUNTEER_HOUR_VERIFICATION_FIELDS_REQUIRED")
        path = self._root(owner_id) / "hours" / f"{log_id}.json"
        record = self._read(path)
        record["state"] = decision
        record["verification"] = {
            "supervisor_id": supervisor_id,
            "decision": decision,
            "rationale": rationale.strip(),
            "verified_at": _now(),
            "disciplinary_action": False,
        }
        return self._write(path, record)

    def record_training(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        training_id = _text(payload.get("training_id"))
        volunteer_id = _text(payload.get("volunteer_id"))
        title = _text(payload.get("title"))
        if not all((training_id, volunteer_id, title)):
            raise ValueError("VOLUNTEER_TRAINING_FIELDS_REQUIRED")
        self.get_profile(owner_id, volunteer_id)
        record = {
            "schema_version": SCHEMA_VERSION,
            "training_id": training_id,
            "volunteer_id": volunteer_id,
            "title": title,
            "completed_at": _text(payload.get("completed_at")) or _now(),
            "instructor_or_source": _text(payload.get("instructor_or_source")) or None,
            "skills_awarded": sorted({_text(item) for item in payload.get("skills_awarded", []) if _text(item)}),
            "evidence": list(payload.get("evidence") or []),
            "reviewed": bool(payload.get("reviewed", False)),
        }
        return self._write(self._root(owner_id) / "training" / f"{training_id}.json", record)

    def issue_certificate(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        certificate_id = _text(payload.get("certificate_id"))
        volunteer_id = _text(payload.get("volunteer_id"))
        title = _text(payload.get("title"))
        if not all((certificate_id, volunteer_id, title)):
            raise ValueError("VOLUNTEER_CERTIFICATE_FIELDS_REQUIRED")
        profile = self.get_profile(owner_id, volunteer_id)
        evidence_uris = tuple(_text(item) for item in payload.get("evidence_uris", []) if _text(item))
        if not evidence_uris:
            raise ValueError("VOLUNTEER_CERTIFICATE_EVIDENCE_REQUIRED")
        certificate = {
            "certificate_id": certificate_id,
            "volunteer_id": volunteer_id,
            "display_name": profile["display_name"],
            "title": title,
            "issued_at": _text(payload.get("issued_at")) or _now(),
            "issuer": _text(payload.get("issuer")) or "Calyx Volunteer Service",
            "recognition_basis": _text(payload.get("recognition_basis")) or None,
            "public_display_authorized": False,
        }
        content = _stable(certificate).encode("utf-8")
        result = self.artifacts.register(
            ArtifactRegistration(
                artifact_id=f"volunteer-certificate:{certificate_id}",
                content=content,
                media_type="application/json",
                source_uri=f"calyx://volunteer/certificates/{certificate_id}",
                producer_assignment_id="CALYX-472-volunteer-service",
                evidence_uris=evidence_uris,
                metadata={"volunteer_id": volunteer_id, "private": True, "public_display_authorized": False},
            )
        )
        certificate["artifact"] = {
            "artifact_id": result.record.artifact_id,
            "checksum": result.record.checksum,
            "created": result.created,
        }
        return self._write(self._root(owner_id) / "certificates" / f"{certificate_id}.json", certificate)

    def record_recognition(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        recognition_id = _text(payload.get("recognition_id"))
        volunteer_id = _text(payload.get("volunteer_id"))
        category = _text(payload.get("category"))
        if not all((recognition_id, volunteer_id, category)):
            raise ValueError("VOLUNTEER_RECOGNITION_FIELDS_REQUIRED")
        self.get_profile(owner_id, volunteer_id)
        record = {
            "schema_version": SCHEMA_VERSION,
            "recognition_id": recognition_id,
            "volunteer_id": volunteer_id,
            "category": category,
            "citation": _text(payload.get("citation")) or None,
            "basis": list(payload.get("basis") or []),
            "approved_by": _text(payload.get("approved_by")) or None,
            "created_at": _now(),
            "public_display_authorized": False,
            "binding_commitment_authorized": False,
        }
        return self._write(self._root(owner_id) / "recognition" / f"{recognition_id}.json", record)

    def disclose_conflict(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        conflict_id = _text(payload.get("conflict_id"))
        volunteer_id = _text(payload.get("volunteer_id"))
        if not conflict_id or not volunteer_id:
            raise ValueError("VOLUNTEER_CONFLICT_FIELDS_REQUIRED")
        self.get_profile(owner_id, volunteer_id)
        record = {
            "schema_version": SCHEMA_VERSION,
            "conflict_id": conflict_id,
            "volunteer_id": volunteer_id,
            "type": _text(payload.get("type")) or "other",
            "description": _text(payload.get("description")) or None,
            "mitigation": _text(payload.get("mitigation")) or None,
            "review_state": "human_review_required",
            "disciplinary_decision_authorized": False,
            "created_at": _now(),
        }
        return self._write(self._root(owner_id) / "conflicts" / f"{conflict_id}.json", record)

    def export(self, owner_id: str, volunteer_id: str, *, include_private_contact: bool = False) -> dict[str, Any]:
        profile = self.get_profile(owner_id, volunteer_id)
        hours_dir = self._root(owner_id) / "hours"
        hour_logs = [self._read(path) for path in sorted(hours_dir.glob("*.json"))] if hours_dir.exists() else []
        hour_logs = [item for item in hour_logs if item["volunteer_id"] == volunteer_id]
        verified_hours = round(sum(float(item["hours"]) for item in hour_logs if item["state"] == "verified"), 2)
        training_dir = self._root(owner_id) / "training"
        training = [self._read(path) for path in sorted(training_dir.glob("*.json"))] if training_dir.exists() else []
        training = [item for item in training if item["volunteer_id"] == volunteer_id]
        certificates_dir = self._root(owner_id) / "certificates"
        certificates = [self._read(path) for path in sorted(certificates_dir.glob("*.json"))] if certificates_dir.exists() else []
        certificates = [item for item in certificates if item["volunteer_id"] == volunteer_id]
        exported_profile = dict(profile)
        if not include_private_contact:
            exported_profile["contact"] = {}
            exported_profile["accessibility_or_support_notes"] = None
        return {
            "schema_version": SCHEMA_VERSION,
            "profile": exported_profile,
            "verified_hours": verified_hours,
            "hour_logs": hour_logs,
            "training": training,
            "certificates": certificates,
            "contains_private_contact": include_private_contact,
            "public_export": False,
        }

    def readiness(self, owner_id: str) -> dict[str, Any]:
        root = self._root(owner_id)
        profiles = list((root / "profiles").glob("*.json")) if (root / "profiles").exists() else []
        assignments = [self._read(path) for path in sorted((root / "assignments").glob("*.json"))] if (root / "assignments").exists() else []
        hours = [self._read(path) for path in sorted((root / "hours").glob("*.json"))] if (root / "hours").exists() else []
        pending_hours = [item for item in hours if item["state"] == "submitted"]
        training_needed = [item for item in assignments if item.get("missing_skills")]
        return {
            "schema_version": SCHEMA_VERSION,
            "decision": "OPERATIONAL_REVIEW_READY" if profiles else "NO_VOLUNTEER_PROFILES",
            "profile_count": len(profiles),
            "assignment_count": len(assignments),
            "pending_hour_verification_count": len(pending_hours),
            "training_or_skill_review_count": len(training_needed),
            "public_personal_data_authorized": False,
            "autonomous_disciplinary_decisions_authorized": False,
            "binding_commitments_authorized": False,
            "production_deployment_authorized": False,
        }

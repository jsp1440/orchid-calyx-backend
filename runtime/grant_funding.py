"""Governed grant and funding opportunity intelligence for CALYX issue #456.

This bounded service records source-grounded opportunities, organization/project profiles,
deterministic fit assessments, and review-only draft artifacts. It never submits a grant,
contacts a funder, fabricates eligibility, or stores credentials/secrets.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.calyx_orchestrator.artifact_registry import (
    ArtifactRegistration,
    ImmutableArtifactRegistry,
)

SCHEMA_VERSION = "calyx-grant-funding/v1"
SENSITIVE_KEYS = {"password", "secret", "token", "api_key", "ssn", "bank_account", "routing_number"}


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _text(value: object) -> str:
    return str(value or "").strip()


def _slug(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return digest


def funding_root() -> Path:
    return Path(os.environ.get("CALYX_FUNDING_WORKSPACE", "/tmp/calyx/funding"))


def _reject_sensitive(value: Any, *, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if normalized in SENSITIVE_KEYS or normalized.endswith(("_secret", "_token")):
                raise ValueError(f"FUNDING_SENSITIVE_FIELD_REJECTED:{path}.{key}")
            _reject_sensitive(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_sensitive(item, path=f"{path}[{index}]")


@dataclass(frozen=True)
class FitAssessment:
    opportunity_id: str
    score: int
    status: str
    explanation: list[str]
    missing_information: list[str]
    eligibility_state: str


class GrantFundingService:
    """File-backed, owner-scoped funding workspace with immutable draft artifacts."""

    def __init__(self, workspace: Path | None = None, artifact_registry: ImmutableArtifactRegistry | None = None) -> None:
        self.workspace = workspace or funding_root()
        self.artifacts = artifact_registry or ImmutableArtifactRegistry()

    @staticmethod
    def _owner_key(owner_id: str) -> str:
        owner = _text(owner_id)
        if not owner:
            raise ValueError("FUNDING_OWNER_REQUIRED")
        return _slug(owner.casefold())

    def _root(self, owner_id: str) -> Path:
        root = self.workspace / "owners" / self._owner_key(owner_id)
        root.mkdir(parents=True, exist_ok=True)
        return root

    @staticmethod
    def _write(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return payload

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(path.stem)
        return json.loads(path.read_text(encoding="utf-8"))

    def save_profile(self, owner_id: str, profile: dict[str, Any]) -> dict[str, Any]:
        _reject_sensitive(profile)
        profile_id = _text(profile.get("profile_id"))
        if not profile_id:
            raise ValueError("FUNDING_PROFILE_ID_REQUIRED")
        clean = {
            "schema_version": SCHEMA_VERSION,
            "profile_id": profile_id,
            "organization": _text(profile.get("organization")),
            "organization_type": _text(profile.get("organization_type")),
            "jurisdiction": _text(profile.get("jurisdiction")),
            "mission": _text(profile.get("mission")),
            "project_name": _text(profile.get("project_name")),
            "project_summary": _text(profile.get("project_summary")),
            "focus_areas": sorted({_text(item) for item in profile.get("focus_areas", []) if _text(item)}),
            "geographies": sorted({_text(item) for item in profile.get("geographies", []) if _text(item)}),
            "eligible_entity_types": sorted({_text(item) for item in profile.get("eligible_entity_types", []) if _text(item)}),
            "requested_currency": _text(profile.get("requested_currency")) or "USD",
            "requested_amount": profile.get("requested_amount"),
            "updated_at": _now(),
            "sensitive_data_stored": False,
        }
        if not clean["organization"] or not clean["project_name"]:
            raise ValueError("FUNDING_PROFILE_REQUIRED_FIELDS")
        return self._write(self._root(owner_id) / "profiles" / f"{profile_id}.json", clean)

    def get_profile(self, owner_id: str, profile_id: str) -> dict[str, Any]:
        return self._read(self._root(owner_id) / "profiles" / f"{profile_id}.json")

    def record_opportunity(self, owner_id: str, opportunity: dict[str, Any]) -> dict[str, Any]:
        _reject_sensitive(opportunity)
        opportunity_id = _text(opportunity.get("opportunity_id"))
        source_url = _text(opportunity.get("source_url"))
        retrieved_at = _text(opportunity.get("retrieved_at"))
        if not opportunity_id or not source_url or not retrieved_at:
            raise ValueError("FUNDING_OPPORTUNITY_PROVENANCE_REQUIRED")
        eligibility = opportunity.get("eligibility") or {}
        if not isinstance(eligibility, dict):
            raise TypeError("FUNDING_ELIGIBILITY_INVALID")
        clean = {
            "schema_version": SCHEMA_VERSION,
            "opportunity_id": opportunity_id,
            "funder": _text(opportunity.get("funder")),
            "title": _text(opportunity.get("title")),
            "description": _text(opportunity.get("description")),
            "source_url": source_url,
            "retrieved_at": retrieved_at,
            "jurisdiction": _text(opportunity.get("jurisdiction")),
            "currency": _text(opportunity.get("currency")) or "USD",
            "amount_min": opportunity.get("amount_min"),
            "amount_max": opportunity.get("amount_max"),
            "deadline": _text(opportunity.get("deadline")) or None,
            "deadline_confidence": opportunity.get("deadline_confidence"),
            "eligibility": eligibility,
            "requirements": list(opportunity.get("requirements") or []),
            "focus_areas": sorted({_text(item) for item in opportunity.get("focus_areas", []) if _text(item)}),
            "geographies": sorted({_text(item) for item in opportunity.get("geographies", []) if _text(item)}),
            "contact": opportunity.get("contact") or {},
            "provenance": opportunity.get("provenance") or {"source_url": source_url, "retrieved_at": retrieved_at},
            "submission_performed": False,
            "outreach_performed": False,
        }
        if not clean["funder"] or not clean["title"]:
            raise ValueError("FUNDING_OPPORTUNITY_REQUIRED_FIELDS")
        confidence = clean["deadline_confidence"]
        if confidence is not None and not (0 <= float(confidence) <= 1):
            raise ValueError("FUNDING_DEADLINE_CONFIDENCE_INVALID")
        return self._write(self._root(owner_id) / "opportunities" / f"{opportunity_id}.json", clean)

    def get_opportunity(self, owner_id: str, opportunity_id: str) -> dict[str, Any]:
        return self._read(self._root(owner_id) / "opportunities" / f"{opportunity_id}.json")

    def assess_fit(self, owner_id: str, profile_id: str, opportunity_id: str) -> dict[str, Any]:
        profile = self.get_profile(owner_id, profile_id)
        opportunity = self.get_opportunity(owner_id, opportunity_id)
        explanation: list[str] = []
        missing: list[str] = []
        score = 0

        entity_types = {item.casefold() for item in profile["eligible_entity_types"]}
        allowed_types = {str(item).casefold() for item in opportunity["eligibility"].get("entity_types", [])}
        if allowed_types:
            if entity_types & allowed_types:
                score += 35
                explanation.append("Entity type matches a stated eligibility category (+35).")
                eligibility_state = "supported"
            else:
                explanation.append("No entity-type match was found in the supplied profile (0/35).")
                eligibility_state = "not_supported"
        else:
            missing.append("opportunity.eligibility.entity_types")
            eligibility_state = "unknown"

        profile_focus = {item.casefold() for item in profile["focus_areas"]}
        opportunity_focus = {item.casefold() for item in opportunity["focus_areas"]}
        overlap = profile_focus & opportunity_focus
        if opportunity_focus:
            focus_points = round(30 * len(overlap) / len(opportunity_focus))
            score += focus_points
            explanation.append(f"Focus-area overlap contributes {focus_points}/30 points.")
        else:
            missing.append("opportunity.focus_areas")

        profile_geo = {item.casefold() for item in profile["geographies"]}
        opportunity_geo = {item.casefold() for item in opportunity["geographies"]}
        if opportunity_geo:
            if profile_geo & opportunity_geo:
                score += 20
                explanation.append("Geography overlaps the stated funding area (+20).")
            else:
                explanation.append("No stated geography overlap was found (0/20).")
        else:
            missing.append("opportunity.geographies")

        amount = profile.get("requested_amount")
        low, high = opportunity.get("amount_min"), opportunity.get("amount_max")
        if amount is not None and (low is not None or high is not None):
            within_low = low is None or float(amount) >= float(low)
            within_high = high is None or float(amount) <= float(high)
            if within_low and within_high:
                score += 10
                explanation.append("Requested amount falls within the stated funding range (+10).")
            else:
                explanation.append("Requested amount falls outside the stated funding range (0/10).")
        else:
            missing.append("amount_range_or_requested_amount")

        if opportunity.get("deadline") and opportunity.get("deadline_confidence") is not None:
            score += 5
            explanation.append("A deadline with explicit confidence is present (+5).")
        else:
            missing.append("deadline_or_deadline_confidence")

        if eligibility_state == "not_supported":
            status = "not_ready"
        elif missing:
            status = "needs_information"
        elif score >= 75:
            status = "strong_fit"
        elif score >= 50:
            status = "possible_fit"
        else:
            status = "weak_fit"

        assessment = FitAssessment(
            opportunity_id=opportunity_id,
            score=min(score, 100),
            status=status,
            explanation=explanation,
            missing_information=sorted(set(missing)),
            eligibility_state=eligibility_state,
        )
        payload = {"schema_version": SCHEMA_VERSION, "profile_id": profile_id, **asdict(assessment), "assessed_at": _now()}
        return self._write(self._root(owner_id) / "assessments" / f"{profile_id}--{opportunity_id}.json", payload)

    def create_draft(self, owner_id: str, profile_id: str, opportunity_id: str) -> dict[str, Any]:
        profile = self.get_profile(owner_id, profile_id)
        opportunity = self.get_opportunity(owner_id, opportunity_id)
        assessment = self.assess_fit(owner_id, profile_id, opportunity_id)
        draft_id = f"grant-draft-{profile_id}-{opportunity_id}"
        narrative = (
            f"DRAFT FOR HUMAN REVIEW\n\nProject: {profile['project_name']}\nFunder opportunity: {opportunity['title']}\n\n"
            f"Project summary: {profile['project_summary']}\n\n"
            f"Fit assessment: {assessment['status']} ({assessment['score']}/100).\n"
            f"Missing information: {', '.join(assessment['missing_information']) or 'none identified by deterministic checks'}.\n\n"
            "This draft does not assert eligibility beyond the supplied source record and must be reviewed against the official funding notice before use."
        )
        budget = {
            "currency": opportunity["currency"],
            "requested_amount": profile.get("requested_amount"),
            "outline": [
                {"category": "personnel", "amount": None, "review_required": True},
                {"category": "equipment_or_services", "amount": None, "review_required": True},
                {"category": "travel_or_fieldwork", "amount": None, "review_required": True},
                {"category": "indirect_or_administration", "amount": None, "review_required": True},
            ],
        }
        content = json.dumps({"narrative": narrative, "budget_outline": budget}, sort_keys=True).encode("utf-8")
        registration = ArtifactRegistration(
            artifact_id=draft_id,
            content=content,
            media_type="application/json",
            source_uri=opportunity["source_url"],
            producer_assignment_id="CALYX-456-grant-funding-agent",
            evidence_uris=(opportunity["source_url"],),
            metadata={"review_required": True, "submission_authorized": False, "profile_id": profile_id, "opportunity_id": opportunity_id},
        )
        record = self.artifacts.register(registration).record
        payload = {
            "schema_version": SCHEMA_VERSION,
            "draft_id": draft_id,
            "profile_id": profile_id,
            "opportunity_id": opportunity_id,
            "narrative": narrative,
            "budget_outline": budget,
            "artifact": {"artifact_id": record.artifact_id, "checksum": record.checksum, "source_uri": record.source_uri},
            "human_review_required": True,
            "submission_authorized": False,
            "outreach_authorized": False,
        }
        return self._write(self._root(owner_id) / "drafts" / f"{draft_id}.json", payload)

    def readiness(self, owner_id: str, profile_id: str, opportunity_id: str) -> dict[str, Any]:
        assessment = self.assess_fit(owner_id, profile_id, opportunity_id)
        return {
            "schema_version": SCHEMA_VERSION,
            "decision": "REVIEW_READY" if not assessment["missing_information"] and assessment["eligibility_state"] == "supported" else "INFORMATION_REQUIRED",
            "fit": assessment,
            "human_review_required": True,
            "eligibility_fabrication_authorized": False,
            "grant_submission_authorized": False,
            "autonomous_outreach_authorized": False,
            "binding_commitment_authorized": False,
            "secret_storage_authorized": False,
            "production_deployment_authorized": False,
        }

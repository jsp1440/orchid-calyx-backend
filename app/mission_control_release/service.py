from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.mission_control_access import AccessPrincipal, CapabilityService, MissionControlRole
from app.review_tasks.operations import ReviewQueueOperations
from app.review_tasks.service import GovernedReviewTaskService
from app.review_tasks.workforce import frontend_contract


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MissionControlReleaseReadiness:
    """End-to-end governance validation for Mission Control role-aware release readiness."""

    REQUIRED_SLICES = tuple(f"MISSION-CONTROL-ROLE-001{suffix}" for suffix in "ABCDEFGHI")

    def __init__(
        self,
        review_service: GovernedReviewTaskService,
        capability_service: CapabilityService | None = None,
    ) -> None:
        self.review_service = review_service
        self.capability_service = capability_service or CapabilityService()

    def evaluate(self, principal: AccessPrincipal) -> dict[str, Any]:
        contract = frontend_contract(principal, self.capability_service)
        metrics = ReviewQueueOperations(self.review_service).metrics()
        controls = {
            "authenticated_principal": principal.authenticated,
            "public_visibility_available": self.capability_service.evaluate(
                principal, "mission_control.view.public"
            ).allowed,
            "administrator_science_separation": self._administrator_science_separation(),
            "publication_explicitly_gated": contract["governance"][
                "publication_requires_explicit_capability"
            ],
            "embargo_policy_declared": True,
            "workforce_import_governed": contract["governance"][
                "external_results_are_reconciled_as_review_evidence"
            ],
            "review_persistence_configured": self.review_service.repository.__class__.__name__
            != "MemoryReviewTaskRepository",
        }
        blockers: list[str] = []
        if not controls["authenticated_principal"]:
            blockers.append("Authenticated principal resolution is required for release operations.")
        if not controls["administrator_science_separation"]:
            blockers.append("Administrator and scientific approval capabilities are not separated.")
        if not controls["publication_explicitly_gated"]:
            blockers.append("Publication is not explicitly capability-gated.")
        if not controls["workforce_import_governed"]:
            blockers.append("External workforce results are not governed review evidence.")
        if not controls["review_persistence_configured"]:
            blockers.append("Durable review persistence is not configured for this runtime.")

        return {
            "build": "MISSION-CONTROL-ROLE-001J",
            "generated_at": _now(),
            "principal_id": principal.principal_id,
            "required_slices": list(self.REQUIRED_SLICES),
            "controls": controls,
            "queue_metrics": metrics,
            "frontend_contract": contract,
            "release_ready": not blockers,
            "blockers": blockers,
            "governance": {
                "read_only_assessment": True,
                "does_not_publish": True,
                "does_not_promote_canonical_knowledge": True,
                "does_not_grant_scientific_authority": True,
            },
        }

    def _administrator_science_separation(self) -> bool:
        administrator = AccessPrincipal(
            principal_id="release-readiness-administrator",
            roles=(MissionControlRole.ADMINISTRATOR,),
            authenticated=True,
        )
        effective = set(self.capability_service.effective_capabilities(administrator))
        return not bool({"review.science", "review.expert", "review.publish"} & effective)

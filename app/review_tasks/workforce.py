from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from app.mission_control_access import AccessPrincipal, CapabilityService

from .models import ReviewDecisionInput, ReviewDecisionType
from .service import GovernedReviewTaskService, ReviewTaskError


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


class WorkforceImportError(ValueError):
    def __init__(self, code: str, details: dict[str, Any] | None = None) -> None:
        self.code = code
        self.details = details or {}
        super().__init__(code)


class WorkforceResultReconciler:
    """Governed import and reconciliation for external workforce results."""

    def __init__(
        self,
        service: GovernedReviewTaskService,
        capability_service: CapabilityService | None = None,
    ) -> None:
        self.service = service
        self.capability_service = capability_service or CapabilityService()

    def import_results(
        self,
        principal: AccessPrincipal,
        *,
        source: str,
        batch_id: str,
        results: list[dict[str, Any]],
        dry_run: bool = False,
    ) -> dict[str, Any]:
        decision = self.capability_service.evaluate(principal, "review.external.import")
        if not decision.allowed:
            raise WorkforceImportError(
                decision.reason_code,
                self.capability_service.audit_payload(decision),
            )
        if not source.strip() or not batch_id.strip():
            raise WorkforceImportError("INVALID_WORKFORCE_BATCH")

        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        seen: set[str] = set()

        for raw in results:
            item = deepcopy(raw)
            task_id = str(item.get("task_id") or "").strip()
            external_result_id = str(item.get("external_result_id") or "").strip()
            fingerprint = external_result_id or _fingerprint(
                {"source": source, "batch_id": batch_id, "result": item}
            )
            if fingerprint in seen:
                rejected.append({"task_id": task_id or None, "code": "DUPLICATE_RESULT"})
                continue
            seen.add(fingerprint)
            if not task_id:
                rejected.append({"task_id": None, "code": "TASK_ID_REQUIRED"})
                continue
            task = self.service.repository.get(task_id)
            if not task:
                rejected.append({"task_id": task_id, "code": "TASK_NOT_FOUND"})
                continue
            if task.get("embargoed"):
                rejected.append({"task_id": task_id, "code": "EMBARGOED_TASK"})
                continue
            try:
                imported_decision = ReviewDecisionType(str(item.get("decision") or ""))
            except ValueError:
                rejected.append({"task_id": task_id, "code": "INVALID_DECISION"})
                continue

            reconciliation = {
                "task_id": task_id,
                "external_result_id": external_result_id or fingerprint,
                "source": source,
                "batch_id": batch_id,
                "decision": imported_decision.value,
                "reviewer_id": str(item.get("reviewer_id") or principal.principal_id),
                "received_at": _now(),
                "status": "VALIDATED",
            }
            if not dry_run:
                imported = ReviewDecisionInput(
                    decision=imported_decision,
                    reviewer_id=principal.principal_id,
                    reviewer_capabilities=(),
                    comment=item.get("comment"),
                    modified_value=item.get("modified_value"),
                    provenance={
                        **deepcopy(item.get("provenance") or {}),
                        "workforce_source": source,
                        "workforce_batch_id": batch_id,
                        "external_result_id": reconciliation["external_result_id"],
                        "external_reviewer_id": item.get("reviewer_id"),
                        "imported_by": principal.principal_id,
                    },
                )
                try:
                    reconciled_task = self.service.decide_for_principal(task_id, principal, imported)
                except ReviewTaskError as exc:
                    rejected.append({"task_id": task_id, "code": exc.code, "details": exc.details})
                    continue
                reconciliation["task_state"] = reconciled_task["state"]
                reconciliation["authoritative_decision"] = reconciled_task.get("authoritative_decision")
                self.service.repository.append_event(
                    task_id,
                    "WORKFORCE_RESULT_IMPORTED",
                    reconciliation,
                )
            accepted.append(reconciliation)

        return {
            "source": source,
            "batch_id": batch_id,
            "dry_run": dry_run,
            "received": len(results),
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "accepted": accepted,
            "rejected": rejected,
            "authorization": self.capability_service.audit_payload(decision),
        }


def frontend_contract(principal: AccessPrincipal, capability_service: CapabilityService | None = None) -> dict[str, Any]:
    service = capability_service or CapabilityService()
    capabilities = set(service.effective_capabilities(principal))
    roles = [role.value for role in principal.roles]
    return {
        "contract_version": "MISSION-CONTROL-ROLE-001I",
        "principal": {
            "id": principal.principal_id,
            "authenticated": principal.authenticated,
            "roles": roles,
            "qualifications": list(principal.qualifications),
            "specialties": list(principal.specialties),
        },
        "navigation": {
            "public_dashboard": "mission_control.view.public" in capabilities,
            "review_queue": bool({"review.science", "review.expert", "review.publish"} & capabilities),
            "operations": "mission_control.view.operations" in capabilities,
            "workforce_export": "review.external.export" in capabilities,
            "workforce_import": "review.external.import" in capabilities,
            "audit": "governance.audit.view" in capabilities,
        },
        "actions": {
            "reserve_task": bool({"review.science", "review.expert", "review.publish"} & capabilities),
            "submit_decision": bool({"review.science", "review.expert", "review.publish"} & capabilities),
            "expire_reservations": "review.assignments.manage" in capabilities,
            "import_workforce_results": "review.external.import" in capabilities,
            "publish": "review.publish" in capabilities,
        },
        "effective_capabilities": sorted(capabilities),
        "governance": {
            "administrator_role_does_not_imply_scientific_authority": True,
            "publication_requires_explicit_capability": True,
            "external_results_are_reconciled_as_review_evidence": True,
        },
    }

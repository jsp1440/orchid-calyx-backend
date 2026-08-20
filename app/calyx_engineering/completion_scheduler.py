from __future__ import annotations

import json
import os
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.calyx_orchestrator.models import CalyxJob, utcnow

from .completion_loop import CompletionState, GovernedAutonomousCompletionLoop
from .github import GitHubEngineeringClient

ENGINEERING_COMPLETION_JOB_TYPE = "engineering_completion"
ENGINEERING_COMPLETION_POLICY = "owner_only"
_MUTATION_LEASE_SECONDS = 900


class EngineeringCompletionScheduler:
    """Persist and advance governed PR completion cycles using CalyxJob leases."""

    def __init__(
        self,
        db: Session,
        client: GitHubEngineeringClient,
        *,
        loop_factory=None,
    ) -> None:
        self.db = db
        self.client = client
        self.loop_factory = loop_factory or GovernedAutonomousCompletionLoop

    @staticmethod
    def poll_seconds() -> int:
        value = int(os.getenv("CALYX_ENGINEERING_COMPLETION_POLL_SECONDS", "30"))
        return max(10, min(value, 900))

    def enqueue(
        self,
        *,
        owner: str,
        pull_request_number: int,
        repair_paths: list[str],
        objective: str,
        repairs_authorized: bool,
        required_checks: list[str],
        priority: int = 20,
    ) -> CalyxJob:
        normalized_owner = owner.strip()
        normalized_checks = sorted(
            {str(name).strip() for name in required_checks if str(name).strip()}
        )
        if not normalized_owner:
            raise ValueError("ENGINEERING_COMPLETION_OWNER_REQUIRED")
        if pull_request_number < 1:
            raise ValueError("ENGINEERING_COMPLETION_PR_INVALID")
        if not repair_paths:
            raise ValueError("ENGINEERING_COMPLETION_PATHS_REQUIRED")
        if not objective.strip():
            raise ValueError("ENGINEERING_COMPLETION_OBJECTIVE_REQUIRED")
        if not repairs_authorized:
            raise PermissionError("ENGINEERING_COMPLETION_REPAIR_AUTHORIZATION_REQUIRED")
        if not normalized_checks:
            raise ValueError("ENGINEERING_COMPLETION_REQUIRED_CHECKS_REQUIRED")

        payload = {
            "pull_request_number": pull_request_number,
            "repair_paths": repair_paths,
            "objective": objective.strip(),
            "repairs_authorized": True,
            "required_checks": normalized_checks,
        }
        request_text = json.dumps(payload, sort_keys=True)

        existing = self.db.scalar(
            select(CalyxJob).where(
                CalyxJob.owner == normalized_owner,
                CalyxJob.job_type == ENGINEERING_COMPLETION_JOB_TYPE,
                CalyxJob.status.in_(("queued", "running")),
                CalyxJob.title == f"Complete PR #{pull_request_number}",
            )
        )
        if existing is not None:
            # A repeated enqueue is allowed to correct stale parameters only while the
            # job is safely queued. Previously we returned the first queued job unchanged,
            # which could trap a completion cycle forever on a placeholder check roster.
            if existing.status == "running":
                if existing.request_text != request_text:
                    raise ValueError("ENGINEERING_COMPLETION_RUNNING_JOB_CONFLICT")
                return existing
            existing.request_text = request_text
            existing.priority = priority
            existing.next_attempt_at = None
            existing.error_code = None
            existing.approval_required = False
            existing.approval_class = None
            self.db.commit()
            self.db.refresh(existing)
            return existing

        job = CalyxJob(
            job_type=ENGINEERING_COMPLETION_JOB_TYPE,
            title=f"Complete PR #{pull_request_number}",
            request_text=request_text,
            owner=normalized_owner,
            status="queued",
            priority=priority,
            policy_class=ENGINEERING_COMPLETION_POLICY,
            approval_required=False,
            attempt_count=0,
            max_attempts=3,
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def claim(self, *, worker_id: str, lease_seconds: int = 180) -> CalyxJob | None:
        normalized_worker = worker_id.strip()
        if not normalized_worker:
            raise ValueError("ENGINEERING_COMPLETION_WORKER_REQUIRED")
        if not 30 <= lease_seconds <= 3600:
            raise ValueError("ENGINEERING_COMPLETION_LEASE_OUT_OF_RANGE")

        now = utcnow()
        claimable = or_(
            CalyxJob.status == "queued",
            and_(
                CalyxJob.status == "running",
                CalyxJob.lease_expires_at.is_not(None),
                CalyxJob.lease_expires_at <= now,
            ),
        )
        candidate = self.db.scalar(
            select(CalyxJob)
            .where(
                CalyxJob.job_type == ENGINEERING_COMPLETION_JOB_TYPE,
                CalyxJob.policy_class == ENGINEERING_COMPLETION_POLICY,
                CalyxJob.approval_required.is_(False),
                claimable,
                or_(CalyxJob.next_attempt_at.is_(None), CalyxJob.next_attempt_at <= now),
                or_(CalyxJob.deadline_at.is_(None), CalyxJob.deadline_at > now),
            )
            .order_by(CalyxJob.priority.asc(), CalyxJob.created_at.asc())
            .limit(1)
        )
        if candidate is None:
            return None

        token = str(uuid4())
        updated = (
            self.db.query(CalyxJob)
            .filter(
                CalyxJob.job_id == candidate.job_id,
                claimable,
                or_(CalyxJob.next_attempt_at.is_(None), CalyxJob.next_attempt_at <= now),
            )
            .update(
                {
                    CalyxJob.status: "running",
                    CalyxJob.lease_owner: normalized_worker,
                    CalyxJob.lease_token: token,
                    CalyxJob.lease_expires_at: now + timedelta(seconds=lease_seconds),
                    CalyxJob.next_attempt_at: None,
                    CalyxJob.error_code: None,
                },
                synchronize_session=False,
            )
        )
        if not updated:
            self.db.rollback()
            return None
        self.db.commit()
        return self.db.get(CalyxJob, candidate.job_id)

    def _renew_lease(
        self,
        job: CalyxJob,
        *,
        worker_id: str,
        lease_token: str,
        lease_seconds: int = _MUTATION_LEASE_SECONDS,
    ) -> None:
        updated = (
            self.db.query(CalyxJob)
            .filter(
                CalyxJob.job_id == job.job_id,
                CalyxJob.status == "running",
                CalyxJob.lease_owner == worker_id,
                CalyxJob.lease_token == lease_token,
            )
            .update(
                {CalyxJob.lease_expires_at: utcnow() + timedelta(seconds=lease_seconds)},
                synchronize_session=False,
            )
        )
        if not updated:
            self.db.rollback()
            raise PermissionError("STALE_ENGINEERING_COMPLETION_LEASE")
        self.db.commit()
        job.lease_expires_at = utcnow() + timedelta(seconds=lease_seconds)

    def _finish(
        self,
        job: CalyxJob,
        *,
        worker_id: str,
        lease_token: str,
        receipt: dict,
    ) -> CalyxJob:
        state = str(receipt.get("state") or "")
        now = utcnow()
        values: dict = {
            CalyxJob.result_json: json.dumps(receipt, sort_keys=True, default=str),
            CalyxJob.lease_owner: None,
            CalyxJob.lease_token: None,
            CalyxJob.lease_expires_at: None,
            CalyxJob.error_code: None,
        }

        if state == CompletionState.WAITING_FOR_CI.value:
            values.update(
                {
                    CalyxJob.status: "queued",
                    CalyxJob.next_attempt_at: now + timedelta(seconds=self.poll_seconds()),
                }
            )
        elif state == CompletionState.REPAIR_COMMITTED.value:
            values.update(
                {
                    CalyxJob.status: "queued",
                    CalyxJob.attempt_count: job.attempt_count + 1,
                    CalyxJob.next_attempt_at: now + timedelta(seconds=self.poll_seconds()),
                }
            )
        elif state == CompletionState.READY_FOR_MERGE.value:
            values.update(
                {
                    CalyxJob.status: "completed",
                    CalyxJob.next_attempt_at: None,
                    CalyxJob.completed_at: now,
                }
            )
        elif state == CompletionState.FAILED_REPAIRABLE.value:
            values.update(
                {
                    CalyxJob.status: "blocked_approval",
                    CalyxJob.approval_required: True,
                    CalyxJob.approval_class: "engineering_repair",
                    CalyxJob.next_attempt_at: None,
                    CalyxJob.error_code: "ENGINEERING_COMPLETION_REPAIR_AUTHORIZATION_REQUIRED",
                }
            )
        else:
            values.update(
                {
                    CalyxJob.status: "dead_letter",
                    CalyxJob.next_attempt_at: None,
                    CalyxJob.error_code: state or "ENGINEERING_COMPLETION_HALTED",
                }
            )

        updated = (
            self.db.query(CalyxJob)
            .filter(
                CalyxJob.job_id == job.job_id,
                CalyxJob.status == "running",
                CalyxJob.lease_owner == worker_id,
                CalyxJob.lease_token == lease_token,
            )
            .update(values, synchronize_session=False)
        )
        if not updated:
            self.db.rollback()
            raise PermissionError("STALE_ENGINEERING_COMPLETION_LEASE")
        self.db.commit()
        current = self.db.get(CalyxJob, job.job_id)
        if current is None:
            raise LookupError("ENGINEERING_COMPLETION_JOB_NOT_FOUND")
        self.db.refresh(current)
        return current

    def advance_claimed(self, job: CalyxJob, *, worker_id: str, lease_token: str) -> CalyxJob:
        if job.job_type != ENGINEERING_COMPLETION_JOB_TYPE:
            raise ValueError("ENGINEERING_COMPLETION_JOB_TYPE_REQUIRED")
        if job.lease_owner != worker_id or job.lease_token != lease_token:
            raise PermissionError("STALE_ENGINEERING_COMPLETION_LEASE")

        payload = json.loads(job.request_text)
        repair_attempt = job.attempt_count + 1
        if job.attempt_count >= job.max_attempts:
            repair_attempt = job.max_attempts + 1

        # Fence the lease across provider and GitHub mutation calls. The completion
        # loop can spend up to 120 seconds in the provider plus bounded GitHub calls;
        # a 15-minute fenced lease prevents another worker reclaiming the same job.
        self._renew_lease(job, worker_id=worker_id, lease_token=lease_token)
        receipt = self.loop_factory(self.client).advance(
            pull_request_number=int(payload["pull_request_number"]),
            repair_paths=list(payload["repair_paths"]),
            objective=str(payload["objective"]),
            attempt=repair_attempt,
            repairs_authorized=bool(payload.get("repairs_authorized")),
            required_checks=list(payload.get("required_checks") or []),
        ).to_dict()
        receipt["completion_job_id"] = job.job_id
        receipt["repair_attempts_used"] = job.attempt_count
        if receipt.get("state") == CompletionState.REPAIR_COMMITTED.value:
            receipt["repair_attempts_used"] = job.attempt_count + 1
        return self._finish(
            job,
            worker_id=worker_id,
            lease_token=lease_token,
            receipt=receipt,
        )

    def run_once(self, *, worker_id: str, lease_seconds: int = 180) -> dict:
        job = self.claim(worker_id=worker_id, lease_seconds=lease_seconds)
        if job is None:
            return {"executed": False, "reason": "idle"}
        token = str(job.lease_token or "")
        if not token:
            raise RuntimeError("ENGINEERING_COMPLETION_LEASE_TOKEN_MISSING")
        completed = self.advance_claimed(job, worker_id=worker_id, lease_token=token)
        result = json.loads(completed.result_json or "{}")
        return {
            "executed": True,
            "job_id": completed.job_id,
            "status": completed.status,
            "attempt_count": completed.attempt_count,
            "result": result,
        }

"""Deterministic, provider-free worker for DeepOrchestrate TaskLeaves.

This module is the execution layer of the autonomous research loop after
blueprint decomposition (app/scientific_synthesis/blueprint.py):

    DeepOrchestrate.lease(key)
    → DeterministicResearchWorker.execute(leaf)
    → TaskExecutionResult
    → DeepOrchestrate.complete(key, evidence=result.output)
       OR DeepOrchestrate.block(key, reason=result.error_reason)

No model inference, no network calls, no paid provider APIs.
All execution is deterministic given the TaskLeaf.key and evidence fields.
The goal is to prove orchestration contracts — not model intelligence.

Authority class enforcement:
    AUTH_READ_ONLY   → read evidence; no writes
    AUTH_WORKSPACE   → normalize, assess, produce, verify, submit — bounded workspace
    AUTH_PRODUCTION / AUTH_SCIENCE_PUB / AUTH_SECURITY / AUTH_GOVERNANCE →
        these should NEVER reach execute() because DeepOrchestrate auto-gates
        them to OWNER_GATED and BoundedDispatcher skips owner-gated tasks.
        If somehow reached, the worker rejects them with OWNER_GATE_REQUIRED.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .deep_orchestrate import (
    AUTH_GOVERNANCE,
    AUTH_PRODUCTION,
    AUTH_SCIENCE_PUB,
    AUTH_SECURITY,
    TaskLeaf,
)

# Authority classes that must never auto-execute.
_NEVER_AUTO_EXECUTE = frozenset({AUTH_PRODUCTION, AUTH_SCIENCE_PUB, AUTH_SECURITY, AUTH_GOVERNANCE})

WORKER_ID = "deterministic-research-worker-v1"


@dataclass(frozen=True, slots=True)
class TaskExecutionResult:
    """Typed execution result with full provenance.

    Every result carries:
    - task/leaf identity (task_key)
    - blueprint_id / run_fingerprint from leaf evidence (when available)
    - worker identity
    - execution status ("completed" | "blocked")
    - started_at / completed_at (ISO-8601 UTC)
    - deterministic output
    - provenance metadata
    - error_reason when blocked
    """

    task_key: str
    worker_id: str
    status: str  # "completed" | "blocked"
    started_at: str
    completed_at: str
    duration_seconds: float
    output: dict[str, Any]
    blueprint_id: str | None = None
    run_fingerprint: str | None = None
    error_reason: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    def as_evidence(self) -> dict[str, Any]:
        """Serializable evidence dict for DeepOrchestrate.complete()."""
        return {
            "task_key": self.task_key,
            "worker_id": self.worker_id,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "output": self.output,
            "blueprint_id": self.blueprint_id,
            "run_fingerprint": self.run_fingerprint,
            "error_reason": self.error_reason,
            "provenance": self.provenance,
        }


class DeterministicResearchWorker:
    """Provider-free worker for scientific/research TaskLeaves.

    Dispatches by step name embedded in the task key:
        retrieve-evidence, normalize-evidence, assess-contradictions,
        produce-synthesis-artifact, run-verification, submit-for-human-review,
        retrieve-evidence (read_evidence action),
        submit-human-review-record, build-run-manifest,
        canonical-knowledge-mutation  → REJECTED (owner-gate)
        scientific-publication        → REJECTED (owner-gate)
        canonical-activation          → REJECTED (owner-gate)

    Unknown step keys are blocked with UNKNOWN_TASK_STEP.
    """

    def __init__(self, worker_id: str = WORKER_ID) -> None:
        self.worker_id = worker_id

    def execute(self, leaf: TaskLeaf) -> TaskExecutionResult:
        """Execute one TaskLeaf deterministically. Never calls a paid API.

        A LEASED leaf is expected; the caller (BoundedDispatcher) is responsible
        for leasing before calling this and for calling complete()/block() on the
        reservoir after.
        """
        started = time.monotonic()
        started_at = datetime.now(timezone.utc).isoformat()

        # Hard safety check — owner-gated classes must never auto-execute.
        if leaf.authority_class in _NEVER_AUTO_EXECUTE:
            return self._result(
                leaf,
                status="blocked",
                output={},
                error_reason="OWNER_GATE_REQUIRED",
                started_at=started_at,
                elapsed=time.monotonic() - started,
            )

        try:
            output = self._dispatch(leaf)
            status = "completed"
            error_reason = None
        except ValueError as exc:
            output = {}
            status = "blocked"
            error_reason = str(exc)

        return self._result(
            leaf,
            status=status,
            output=output,
            error_reason=error_reason,
            started_at=started_at,
            elapsed=time.monotonic() - started,
        )

    # ── Step dispatch ─────────────────────────────────────────────────────────

    def _dispatch(self, leaf: TaskLeaf) -> dict[str, Any]:
        key = leaf.key
        if "retrieve-evidence" in key:
            return self._retrieve_evidence(leaf)
        if "normalize-evidence" in key:
            return self._normalize_evidence(leaf)
        if "assess-contradictions" in key:
            return self._assess_contradictions(leaf)
        if "produce-synthesis-artifact" in key:
            return self._produce_synthesis_artifact(leaf)
        if "run-verification" in key:
            return self._run_verification(leaf)
        if "submit-for-human-review" in key:
            return self._submit_for_human_review(leaf)
        if "submit-human-review-record" in key:
            return self._submit_human_review_record(leaf)
        if "build-run-manifest" in key:
            return self._build_run_manifest_step(leaf)
        # Owner-gated steps caught earlier; unknown step blocked.
        raise ValueError(f"UNKNOWN_TASK_STEP:{key}")

    # ── Step implementations — deterministic, no network ──────────────────────

    def _retrieve_evidence(self, leaf: TaskLeaf) -> dict[str, Any]:
        run_id = leaf.evidence.get("run_id", "")
        taxon_id = leaf.evidence.get("taxon_id", "")
        return {
            "step": "retrieve_evidence",
            "run_id": run_id,
            "taxon_id": taxon_id,
            "retrieved": [],  # deterministic stub — no live retrieval
            "missing": [],
            "unavailable_marked": True,
            "fabrication_attempted": False,
            "provider_api_called": False,
        }

    def _normalize_evidence(self, leaf: TaskLeaf) -> dict[str, Any]:
        return {
            "step": "normalize_evidence",
            "run_id": leaf.evidence.get("run_id", ""),
            "normalized_count": 0,
            "schema": "EvidenceMatrixRow",
            "uncertainty_preserved": True,
            "provider_api_called": False,
        }

    def _assess_contradictions(self, leaf: TaskLeaf) -> dict[str, Any]:
        return {
            "step": "assess_contradictions",
            "run_id": leaf.evidence.get("run_id", ""),
            "contradictions_found": 0,
            "knowledge_gaps": 0,
            "contradictions_suppressed": False,
            "provider_api_called": False,
        }

    def _produce_synthesis_artifact(self, leaf: TaskLeaf) -> dict[str, Any]:
        return {
            "step": "produce_synthesis_artifact",
            "run_id": leaf.evidence.get("run_id", ""),
            "artifact_type": "synthesis_draft",
            "automatic_publication_attempted": False,
            "kg_mutation_attempted": False,
            "provider_api_called": False,
        }

    def _run_verification(self, leaf: TaskLeaf) -> dict[str, Any]:
        return {
            "step": "run_verification",
            "run_id": leaf.evidence.get("run_id", ""),
            "verification_passed": True,
            "defects_suppressed": False,
            "automatic_publication_triggered": False,
            "provider_api_called": False,
        }

    def _submit_for_human_review(self, leaf: TaskLeaf) -> dict[str, Any]:
        return {
            "step": "submit_for_human_review",
            "run_id": leaf.evidence.get("run_id", ""),
            "submitted": True,
            "automatic_publication_attempted": False,
            "review_queue": "pending",
            "provider_api_called": False,
        }

    def _submit_human_review_record(self, leaf: TaskLeaf) -> dict[str, Any]:
        return {
            "step": "submit_human_review_record",
            "run_id": leaf.evidence.get("run_id", ""),
            "record_stored": True,
            "automatic_downstream_action": False,
            "provider_api_called": False,
        }

    def _build_run_manifest_step(self, leaf: TaskLeaf) -> dict[str, Any]:
        return {
            "step": "build_run_manifest",
            "run_id": leaf.evidence.get("run_id", ""),
            "manifest_type": "oc-run-evidence-manifest-v1",
            "immutable": True,
            "human_review_gated": True,
            "provider_api_called": False,
        }

    # ── Result builder ────────────────────────────────────────────────────────

    def _result(
        self,
        leaf: TaskLeaf,
        *,
        status: str,
        output: dict[str, Any],
        error_reason: str | None,
        started_at: str,
        elapsed: float,
    ) -> TaskExecutionResult:
        completed_at = datetime.now(timezone.utc).isoformat()
        return TaskExecutionResult(
            task_key=leaf.key,
            blueprint_id=leaf.evidence.get("blueprint_id"),
            run_fingerprint=leaf.evidence.get("run_fingerprint"),
            worker_id=self.worker_id,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=max(0.0, elapsed),
            output=output,
            error_reason=error_reason,
            provenance={
                "authority_class": leaf.authority_class,
                "consequence_risk": leaf.consequence_risk,
                "task_state_at_execution": leaf.state,
            },
        )

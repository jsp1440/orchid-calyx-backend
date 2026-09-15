"""Paid API Worker — integrates budget-governed AI provider calls with BoundedDispatcher.

SEPARATE EXECUTION PATH from the ChatGPT Business subscription worker.
- Uses OPENAI_API_KEY or ANTHROPIC_API_KEY (not the Business subscription token).
- Budget reserved BEFORE every provider call; confirmed/released after.
- MAX_RETRIES = 2 — no unbounded retry loops.
- Owner-gated authority classes remain blocked.
- Tier 0 (no-API) path remains available independently.
- Main merge, production deployment, taxonomy, publication gates remain closed.

Work product: AI-generated structured analysis + implementation plan for the issue,
recorded as durable evidence in the receipt. Not full autonomous code + PR (that
requires Codex CLI integration or additional agentic tooling).
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .deep_orchestrate import (
    AUTH_GOVERNANCE,
    AUTH_PRODUCTION,
    AUTH_SCIENCE_PUB,
    AUTH_SECURITY,
    TaskLeaf,
)
from .paid_api_budget_governor import BudgetExhaustedError, PaidAPIBudgetGovernor
from .paid_api_provider import (
    MockPaidProvider,
    PaidAPICallResult,
    PaidAPIProvider,
    build_cheapest_provider_from_env,
)

MAX_RETRIES = 2  # no unbounded retry loops

_NEVER_AUTO_EXECUTE = frozenset(
    {AUTH_PRODUCTION, AUTH_SCIENCE_PUB, AUTH_SECURITY, AUTH_GOVERNANCE}
)

DEFAULT_MAX_OUTPUT_TOKENS = 512
DEFAULT_RESERVATION_MULTIPLIER = 3.0


@dataclass(frozen=True, slots=True)
class PaidAPIWorkerReceipt:
    task_key: str
    worker_id: str
    status: str
    provider: str
    model: str
    run_id: str | None
    input_tokens: int
    output_tokens: int
    estimated_usd: float
    actual_usd: float
    analysis_excerpt: str
    receipt_ledger_line: str | None
    error_reason: str | None
    started_at: str
    completed_at: str
    duration_seconds: float
    automatic_merge: bool = False
    automatic_deployment: bool = False
    production_mutation: bool = False
    publication: bool = False

    def as_evidence(self) -> dict[str, Any]:
        return {
            "task_key": self.task_key,
            "worker_id": self.worker_id,
            "status": self.status,
            "provider": self.provider,
            "model": self.model,
            "run_id": self.run_id,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_usd": self.estimated_usd,
            "actual_usd": self.actual_usd,
            "analysis_excerpt": self.analysis_excerpt,
            "receipt_ledger_line": self.receipt_ledger_line,
            "error_reason": self.error_reason,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "automatic_merge": self.automatic_merge,
            "automatic_deployment": self.automatic_deployment,
            "production_mutation": self.production_mutation,
            "publication": self.publication,
        }


def _build_analysis_prompt(leaf: TaskLeaf) -> tuple[str, str]:
    ev = leaf.evidence or {}
    objective = str(ev.get("objective") or leaf.key)
    criteria = ev.get("acceptance_criteria") or []
    criteria_text = "\n".join(f"- {c}" for c in criteria) if criteria else "(none listed)"
    validation = ev.get("validation_commands") or []
    validation_text = "\n".join(f"- {v}" for v in validation) if validation else "(none listed)"

    system_prompt = (
        "You are a precise software engineering assistant for Orchid Continuum. "
        "Provide a concise, structured analysis and implementation plan. "
        "Be specific. No merge, deployment, production mutation, publication, "
        "credential creation, spending, or force-push."
    )
    user_prompt = (
        f"Issue: {leaf.key}\n"
        f"Title: {leaf.title}\n"
        f"Repository: {ev.get('repository', 'orchid-calyx-backend')}\n\n"
        f"Objective:\n{objective}\n\n"
        f"Acceptance criteria:\n{criteria_text}\n\n"
        f"Validation commands:\n{validation_text}\n\n"
        "Provide: (1) root cause / gap analysis, (2) implementation steps, "
        "(3) test strategy. Be concise — max 400 words."
    )
    return system_prompt, user_prompt


class PaidAPIWorker:
    WORKER_ID = "paid-api-worker-v1"

    def __init__(
        self,
        *,
        provider: PaidAPIProvider,
        governor: PaidAPIBudgetGovernor,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> None:
        self._provider = provider
        self._governor = governor
        self._max_output_tokens = max_output_tokens

    def execute(self, leaf: TaskLeaf) -> PaidAPIWorkerReceipt:
        started = time.monotonic()
        started_at = datetime.now(timezone.utc).isoformat()

        if leaf.authority_class in _NEVER_AUTO_EXECUTE:
            return self._blocked(leaf, "OWNER_GATE_REQUIRED", started_at, started, 0.0)

        system_prompt, user_prompt = _build_analysis_prompt(leaf)
        prompt_chars = len(system_prompt) + len(user_prompt)
        estimated_usd = (
            self._provider.estimate_usd(prompt_chars=prompt_chars)
            * DEFAULT_RESERVATION_MULTIPLIER
        )

        try:
            reservation = self._governor.reserve(
                leaf.key,
                estimated_usd,
                provider_hint=self._provider.provider_name,
            )
        except BudgetExhaustedError as exc:
            return self._blocked(
                leaf,
                f"BUDGET_EXHAUSTED: {exc}",
                started_at,
                started,
                estimated_usd,
            )

        call_result: PaidAPICallResult | None = None
        last_error: str | None = None
        attempts = 0

        while attempts < MAX_RETRIES:
            attempts += 1
            try:
                active_reservation = (
                    reservation
                    if attempts == 1
                    else self._governor.reserve(
                        leaf.key,
                        estimated_usd,
                        provider_hint=self._provider.provider_name,
                    )
                )
                call_result = self._provider.call(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_output_tokens=self._max_output_tokens,
                    governor=self._governor,
                    reservation=active_reservation,
                )
                break
            except BudgetExhaustedError as exc:
                last_error = f"BUDGET_EXHAUSTED: {exc}"
                break
            except Exception as exc:  # noqa: BLE001 - provider SDK boundary
                last_error = str(exc)
                if attempts < MAX_RETRIES:
                    time.sleep(1.0)

        elapsed = time.monotonic() - started
        completed_at = datetime.now(timezone.utc).isoformat()

        if call_result is None:
            try:
                self._governor.release_reservation(reservation.reservation_id)
            except Exception as exc:  # noqa: BLE001 - cleanup must not mask primary failure
                suffix = f"reservation_release_failed={exc}"
                last_error = f"{last_error}; {suffix}" if last_error else suffix
            return PaidAPIWorkerReceipt(
                task_key=leaf.key,
                worker_id=self.WORKER_ID,
                status="failed",
                provider=self._provider.provider_name,
                model=self._provider.model,
                run_id=None,
                input_tokens=0,
                output_tokens=0,
                estimated_usd=estimated_usd,
                actual_usd=0.0,
                analysis_excerpt="",
                receipt_ledger_line=None,
                error_reason=last_error,
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=max(0.0, elapsed),
            )

        receipt_line = call_result.receipt.ledger_line() if call_result.receipt else None
        return PaidAPIWorkerReceipt(
            task_key=leaf.key,
            worker_id=self.WORKER_ID,
            status="completed",
            provider=call_result.provider,
            model=call_result.model,
            run_id=call_result.run_id,
            input_tokens=call_result.input_tokens,
            output_tokens=call_result.output_tokens,
            estimated_usd=estimated_usd,
            actual_usd=call_result.actual_usd,
            analysis_excerpt=call_result.content[:200],
            receipt_ledger_line=receipt_line,
            error_reason=None,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=max(0.0, elapsed),
        )

    def _blocked(
        self,
        leaf: TaskLeaf,
        reason: str,
        started_at: str,
        started_mono: float,
        estimated_usd: float,
    ) -> PaidAPIWorkerReceipt:
        elapsed = time.monotonic() - started_mono
        return PaidAPIWorkerReceipt(
            task_key=leaf.key,
            worker_id=self.WORKER_ID,
            status="blocked",
            provider=(
                self._provider.provider_name
                if hasattr(self._provider, "provider_name")
                else "none"
            ),
            model=self._provider.model if hasattr(self._provider, "model") else "none",
            run_id=None,
            input_tokens=0,
            output_tokens=0,
            estimated_usd=estimated_usd,
            actual_usd=0.0,
            analysis_excerpt="",
            receipt_ledger_line=None,
            error_reason=reason,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc).isoformat(),
            duration_seconds=max(0.0, elapsed),
        )


def build_paid_api_worker_from_env(
    environ: Mapping[str, str] | None = None,
    ceiling_usd: float = 50.0,
) -> tuple[PaidAPIWorker, PaidAPIBudgetGovernor]:
    import os

    env = dict(environ) if environ is not None else dict(os.environ)
    provider = build_cheapest_provider_from_env(env)
    governor = PaidAPIBudgetGovernor(ceiling_usd=ceiling_usd)
    return PaidAPIWorker(provider=provider, governor=governor), governor


def build_paid_api_worker_with_mock(
    responses: list[str] | None = None,
) -> tuple[PaidAPIWorker, PaidAPIBudgetGovernor, MockPaidProvider]:
    provider = MockPaidProvider(responses=list(responses or ["mock-analysis"]))
    governor = PaidAPIBudgetGovernor(ceiling_usd=50.0)
    worker = PaidAPIWorker(provider=provider, governor=governor)
    return worker, governor, provider

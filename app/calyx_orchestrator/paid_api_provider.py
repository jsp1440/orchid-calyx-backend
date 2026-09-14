"""Paid API provider adapters — Anthropic and OpenAI, with cost tracking.

SEPARATE EXECUTION PATH from the ChatGPT Business subscription worker.
- Uses ANTHROPIC_API_KEY or OPENAI_API_KEY (not CALYX_CHATGPT_BUSINESS_CODEX_TOKEN).
- Every call pre-reserves budget; confirms actual cost after.
- Mock provider for deterministic tests (zero real calls, zero cost).

Cheapest models (as of 2026-09):
    Anthropic: claude-haiku-4-5-20251001 — $0.80/M input, $4.00/M output
    OpenAI:    gpt-4o-mini              — $0.15/M input, $0.60/M output

Selection: prefer cheapest configured provider. If both present, use OpenAI gpt-4o-mini.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence

from .paid_api_budget_governor import BudgetReceipt, BudgetReservation, PaidAPIBudgetGovernor

# ── Model constants ───────────────────────────────────────────────────────────

CHEAPEST_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
CHEAPEST_OPENAI_MODEL = "gpt-4o-mini"

# Per-million-token pricing (USD)
ANTHROPIC_INPUT_COST_PER_M = 0.80
ANTHROPIC_OUTPUT_COST_PER_M = 4.00
OPENAI_INPUT_COST_PER_M = 0.15
OPENAI_OUTPUT_COST_PER_M = 0.60


# ── Result ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PaidAPICallResult:
    """Result of one paid provider API call with full cost accounting."""

    run_id: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    actual_usd: float
    content: str
    receipt: BudgetReceipt | None = None

    @property
    def succeeded(self) -> bool:
        return bool(self.content)

    def as_evidence(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "provider": self.provider,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "actual_usd": self.actual_usd,
            "receipt_ledger_line": (
                self.receipt.ledger_line() if self.receipt else None
            ),
        }


# ── Protocol ──────────────────────────────────────────────────────────────────


class PaidAPIProvider(Protocol):
    """Injected provider. Call with pre-reserved budget; returns cost receipt."""

    provider_name: str
    model: str

    def estimate_usd(self, *, prompt_chars: int) -> float:
        """Conservative cost estimate for budget pre-reservation."""
        ...

    def call(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
        governor: PaidAPIBudgetGovernor,
        reservation: BudgetReservation,
    ) -> PaidAPICallResult: ...


# ── Anthropic provider ────────────────────────────────────────────────────────


class AnthropicPaidProvider:
    """Calls Anthropic API with pre-reserved budget and confirmed cost receipt."""

    provider_name = "anthropic"
    model = CHEAPEST_ANTHROPIC_MODEL

    def __init__(self, api_key: str) -> None:
        import anthropic as _anthropic
        self._client = _anthropic.Anthropic(api_key=api_key)

    def estimate_usd(self, *, prompt_chars: int) -> float:
        estimated_input_tokens = max(100, prompt_chars // 4)
        estimated_output_tokens = 600
        return (
            (estimated_input_tokens * ANTHROPIC_INPUT_COST_PER_M / 1_000_000)
            + (estimated_output_tokens * ANTHROPIC_OUTPUT_COST_PER_M / 1_000_000)
        ) * 2  # 2× safety margin

    def call(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
        governor: PaidAPIBudgetGovernor,
        reservation: BudgetReservation,
    ) -> PaidAPICallResult:
        run_id = f"anthro-{uuid.uuid4().hex[:12]}"
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=max_output_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            content = response.content[0].text if response.content else ""
            actual_usd = (
                (input_tokens * ANTHROPIC_INPUT_COST_PER_M / 1_000_000)
                + (output_tokens * ANTHROPIC_OUTPUT_COST_PER_M / 1_000_000)
            )
        except Exception:
            governor.release_reservation(reservation.reservation_id)
            raise

        receipt = governor.confirm(
            reservation.reservation_id,
            actual_usd=actual_usd,
            run_id=run_id,
            provider=self.provider_name,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        return PaidAPICallResult(
            run_id=run_id,
            provider=self.provider_name,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            actual_usd=actual_usd,
            content=content,
            receipt=receipt,
        )


# ── OpenAI provider ───────────────────────────────────────────────────────────


class OpenAIPaidProvider:
    """Calls OpenAI API with pre-reserved budget and confirmed cost receipt."""

    provider_name = "openai"
    model = CHEAPEST_OPENAI_MODEL

    def __init__(self, api_key: str) -> None:
        import openai as _openai
        self._client = _openai.OpenAI(api_key=api_key)

    def estimate_usd(self, *, prompt_chars: int) -> float:
        estimated_input_tokens = max(100, prompt_chars // 4)
        estimated_output_tokens = 600
        return (
            (estimated_input_tokens * OPENAI_INPUT_COST_PER_M / 1_000_000)
            + (estimated_output_tokens * OPENAI_OUTPUT_COST_PER_M / 1_000_000)
        ) * 2  # 2× safety margin

    def call(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
        governor: PaidAPIBudgetGovernor,
        reservation: BudgetReservation,
    ) -> PaidAPICallResult:
        run_id = f"oai-{uuid.uuid4().hex[:12]}"
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                max_tokens=max_output_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            usage = response.usage
            input_tokens = usage.prompt_tokens if usage else 0
            output_tokens = usage.completion_tokens if usage else 0
            content = (
                response.choices[0].message.content
                if response.choices
                else ""
            ) or ""
            actual_usd = (
                (input_tokens * OPENAI_INPUT_COST_PER_M / 1_000_000)
                + (output_tokens * OPENAI_OUTPUT_COST_PER_M / 1_000_000)
            )
        except Exception:
            governor.release_reservation(reservation.reservation_id)
            raise

        receipt = governor.confirm(
            reservation.reservation_id,
            actual_usd=actual_usd,
            run_id=run_id,
            provider=self.provider_name,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        return PaidAPICallResult(
            run_id=run_id,
            provider=self.provider_name,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            actual_usd=actual_usd,
            content=content,
            receipt=receipt,
        )


# ── Mock provider (deterministic tests) ──────────────────────────────────────


@dataclass
class MockPaidProvider:
    """Deterministic mock. Zero real API calls. Zero cost."""

    provider_name: str = "mock"
    model: str = "mock-free-001"
    responses: list[str] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    mock_input_tokens: int = 150
    mock_output_tokens: int = 80
    mock_cost_usd: float = 0.0

    def estimate_usd(self, *, prompt_chars: int) -> float:
        return 0.01  # nominal for pre-reservation

    def call(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
        governor: PaidAPIBudgetGovernor,
        reservation: BudgetReservation,
    ) -> PaidAPICallResult:
        self.calls.append({
            "system_len": len(system_prompt),
            "user_len": len(user_prompt),
            "reservation_id": reservation.reservation_id,
            "task_key": reservation.task_key,
        })
        content = self.responses.pop(0) if self.responses else "mock-analysis-complete"
        run_id = f"mock-{uuid.uuid4().hex[:8]}"
        receipt = governor.confirm(
            reservation.reservation_id,
            actual_usd=self.mock_cost_usd,
            run_id=run_id,
            provider=self.provider_name,
            model=self.model,
            input_tokens=self.mock_input_tokens,
            output_tokens=self.mock_output_tokens,
        )
        return PaidAPICallResult(
            run_id=run_id,
            provider=self.provider_name,
            model=self.model,
            input_tokens=self.mock_input_tokens,
            output_tokens=self.mock_output_tokens,
            actual_usd=self.mock_cost_usd,
            content=content,
            receipt=receipt,
        )


# ── Provider factory ──────────────────────────────────────────────────────────


def build_cheapest_provider_from_env(
    environ: dict[str, str] | None = None,
) -> AnthropicPaidProvider | OpenAIPaidProvider:
    """Return the cheapest configured provider.

    Preference: OpenAI gpt-4o-mini (cheaper) if OPENAI_API_KEY set;
    else Anthropic claude-haiku if ANTHROPIC_API_KEY set.
    Raises RuntimeError if neither key is present.
    The Business token (CALYX_CHATGPT_BUSINESS_CODEX_TOKEN) is NOT used here.
    """
    import os
    env = environ if environ is not None else dict(os.environ)

    # OpenAI gpt-4o-mini is cheaper; prefer it
    openai_key = env.get("OPENAI_API_KEY", "").strip()
    if openai_key:
        return OpenAIPaidProvider(api_key=openai_key)

    anthropic_key = env.get("ANTHROPIC_API_KEY", "").strip()
    if anthropic_key:
        return AnthropicPaidProvider(api_key=anthropic_key)

    raise RuntimeError(
        "PAID_API_NO_KEY_CONFIGURED: Neither OPENAI_API_KEY nor "
        "ANTHROPIC_API_KEY is set. Set one in the environment to enable "
        "paid API dispatch. These are separate from the Business subscription "
        "token (CALYX_CHATGPT_BUSINESS_CODEX_TOKEN)."
    )

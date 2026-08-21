from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import DataAccessContext, DataPolicy, DataPolicyDecision
from .policy import DataPolicyEngine


class ModelProcessingDenied(PermissionError):
    """Raised before protected evidence can be sent to an external model."""


@dataclass(frozen=True)
class ModelProcessingAuthorization:
    provider: str
    policy_ids: tuple[str, ...]
    decisions: tuple[DataPolicyDecision, ...]


def authorize_model_processing(
    policies: Iterable[DataPolicy],
    context: DataAccessContext,
    *,
    engine: DataPolicyEngine | None = None,
) -> ModelProcessingAuthorization:
    """Require every contributing policy to authorize the requested model use.

    A synthesis can combine evidence from many sources.  The most permissive
    source must never widen the restrictions of a more restrictive source, so
    model processing proceeds only when *all* contributing policies allow it.
    """

    if not context.requests_model_processing:
        raise ModelProcessingDenied("MODEL_PROCESSING_NOT_DECLARED")
    if not context.model_provider:
        raise ModelProcessingDenied("MODEL_PROVIDER_REQUIRED")

    evaluator = engine or DataPolicyEngine()
    decisions: list[DataPolicyDecision] = []
    policy_ids: list[str] = []

    for policy in policies:
        decision = evaluator.evaluate(policy, context)
        if not decision.allowed:
            reason = decision.reason_codes[0] if decision.reason_codes else "POLICY_DENIED"
            raise ModelProcessingDenied(f"{policy.policy_id}:{reason}")
        decisions.append(decision)
        policy_ids.append(policy.policy_id)

    if not decisions:
        raise ModelProcessingDenied("MODEL_POLICY_REQUIRED")

    return ModelProcessingAuthorization(
        provider=context.model_provider,
        policy_ids=tuple(policy_ids),
        decisions=tuple(decisions),
    )

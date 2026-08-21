from __future__ import annotations

from .models import (
    DataAccessContext,
    DataPolicy,
    DataPolicyDecision,
    DataSensitivity,
    DisclosureMode,
)


class DataPolicyEngine:
    """Fail-closed policy evaluator for restricted scientific data.

    The engine answers two separate questions:
    1. may this principal use the record for the requested purpose?
    2. if yes, what is the maximum disclosure permitted for the record,
       its locality, and its images?

    Storage, graph traversal, search, and Calyx output layers are expected to
    enforce the returned disclosure limits.  Unknown or incomplete policies
    are denied rather than silently treated as public.
    """

    def evaluate(self, policy: DataPolicy, context: DataAccessContext) -> DataPolicyDecision:
        reasons: list[str] = []

        if policy.sensitivity == DataSensitivity.PUBLIC:
            return DataPolicyDecision(
                allowed=True,
                disclosure=DisclosureMode.FULL,
                location_disclosure=policy.location_disclosure,
                image_disclosure=policy.image_disclosure,
                reason_codes=("PUBLIC_DATA",),
                policy_id=policy.policy_id,
                authority_org=policy.authority_org,
                attribution_required=policy.attribution_required,
            )

        if not context.authenticated:
            return self._deny(policy, "AUTHENTICATION_REQUIRED")

        missing = tuple(
            capability
            for capability in policy.required_capabilities
            if capability not in context.capabilities
        )
        if missing:
            return self._deny(policy, "CAPABILITY_REQUIRED")

        if policy.allowed_purposes:
            if not context.purpose or context.purpose not in policy.allowed_purposes:
                return self._deny(policy, "PURPOSE_NOT_ALLOWED")
            reasons.append("PURPOSE_ALLOWED")

        if context.requests_export and not policy.allow_export:
            return self._deny(policy, "EXPORT_PROHIBITED")

        if context.requests_model_processing:
            if not policy.allow_model_processing:
                return self._deny(policy, "MODEL_PROCESSING_PROHIBITED")
            if policy.approved_model_providers:
                if not context.model_provider or context.model_provider not in policy.approved_model_providers:
                    return self._deny(policy, "MODEL_PROVIDER_NOT_APPROVED")
            reasons.append("MODEL_PROCESSING_ALLOWED")

        reasons.append("POLICY_REQUIREMENTS_SATISFIED")
        return DataPolicyDecision(
            allowed=True,
            disclosure=policy.default_disclosure,
            location_disclosure=policy.location_disclosure,
            image_disclosure=policy.image_disclosure,
            reason_codes=tuple(reasons),
            policy_id=policy.policy_id,
            authority_org=policy.authority_org,
            attribution_required=policy.attribution_required,
        )

    @staticmethod
    def _deny(policy: DataPolicy, reason: str) -> DataPolicyDecision:
        return DataPolicyDecision(
            allowed=False,
            disclosure=DisclosureMode.DENY,
            location_disclosure=DisclosureMode.DENY,
            image_disclosure=DisclosureMode.DENY,
            reason_codes=(reason,),
            policy_id=policy.policy_id,
            authority_org=policy.authority_org,
            attribution_required=policy.attribution_required,
        )

from __future__ import annotations

from dataclasses import asdict

from .models import AccessDecision, AccessPrincipal
from .policy import (
    QUALIFICATION_CAPABILITIES,
    ROLE_CAPABILITIES,
    SCIENTIFIC_APPROVAL_CAPABILITIES,
)


class AccessDenied(PermissionError):
    def __init__(self, decision: AccessDecision) -> None:
        self.decision = decision
        super().__init__(decision.reason_code)


class CapabilityService:
    """Server-side capability resolver for Mission Control and review services."""

    def effective_capabilities(self, principal: AccessPrincipal) -> tuple[str, ...]:
        capabilities = set(principal.direct_capabilities)
        for role in principal.roles:
            capabilities.update(ROLE_CAPABILITIES.get(role, ()))
        for qualification in principal.qualifications:
            capabilities.update(QUALIFICATION_CAPABILITIES.get(qualification, ()))

        # Administrative status never implies scientific approval authority.
        if not principal.qualifications:
            capabilities.difference_update(SCIENTIFIC_APPROVAL_CAPABILITIES)
        return tuple(sorted(capabilities))

    def evaluate(self, principal: AccessPrincipal, capability: str) -> AccessDecision:
        effective = self.effective_capabilities(principal)
        if capability == "mission_control.view.public":
            return AccessDecision(
                allowed=True,
                capability=capability,
                principal_id=principal.principal_id,
                reason_code="PUBLIC_CAPABILITY",
                effective_capabilities=effective,
            )
        if not principal.authenticated:
            return AccessDecision(
                allowed=False,
                capability=capability,
                principal_id=principal.principal_id,
                reason_code="AUTHENTICATION_REQUIRED",
                effective_capabilities=effective,
            )
        allowed = capability in effective
        return AccessDecision(
            allowed=allowed,
            capability=capability,
            principal_id=principal.principal_id,
            reason_code="CAPABILITY_GRANTED" if allowed else "CAPABILITY_REQUIRED",
            effective_capabilities=effective,
        )

    def require(self, principal: AccessPrincipal, capability: str) -> AccessDecision:
        decision = self.evaluate(principal, capability)
        if not decision.allowed:
            raise AccessDenied(decision)
        return decision

    def allowed_actions(
        self,
        principal: AccessPrincipal,
        action_capabilities: dict[str, str],
    ) -> tuple[str, ...]:
        return tuple(
            sorted(
                action
                for action, capability in action_capabilities.items()
                if self.evaluate(principal, capability).allowed
            )
        )

    def audit_payload(self, decision: AccessDecision) -> dict[str, object]:
        return asdict(decision)

"""Authorized society CRM operations.

``SocietyCRMService`` is the only supported entry point for society administration.
For every call it:

1. resolves the caller's roles *in the target organization*, fresh from the database
   (no cache, so a revoked role stops working on the very next request);
2. requires the minimum capability (default deny);
3. calls the tenant-scoped repository.

Principals:

* ``CRMPrincipal(subject="supabase:<uuid>")`` -- a verified person. Authority comes
  only from active staff roles reached through an active identity binding in that
  organization. Being a member grants nothing.
* ``CRMPrincipal(subject=..., platform_operator=True)`` -- the Orchid Continuum
  platform operator (owner session / backend API key). It may create organizations
  and bootstrap or recover an organization's admin, and nothing else: it does not get
  implicit roster, payment, or audit access to any society. Support access means an
  explicit, audited role grant.

Cross-tenant requests for a resource return ``None`` / ``NotFound`` exactly as a
nonexistent resource does, so another tenant's resource existence is not disclosed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .authorization import (
    SocietyAccessDenied,
    SocietyCapability,
    SocietyRole,
    capabilities_for_roles,
    require_capability,
)
from .domain import MembershipStatus, normalize_auth_subject
from .postgres_repository import PostgresSocietyCRMRepository


class PlatformOperatorRequired(PermissionError):
    code = "PLATFORM_OPERATOR_REQUIRED"

    def __init__(self) -> None:
        super().__init__(self.code)


class NotFound(LookupError):
    """Resource absent in this organization (or present only in another one)."""


@dataclass(frozen=True)
class CRMPrincipal:
    subject: str
    platform_operator: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject", normalize_auth_subject(self.subject))


class SocietyCRMService:
    def __init__(self, repository: PostgresSocietyCRMRepository) -> None:
        self._repo = repository

    # -- authorization ------------------------------------------------------------------

    def roles(self, organization_id: int, principal: CRMPrincipal) -> frozenset[SocietyRole]:
        return self._repo.staff_roles_for_subject(organization_id=organization_id, auth_subject=principal.subject)

    def capabilities(self, organization_id: int, principal: CRMPrincipal) -> frozenset[SocietyCapability]:
        return capabilities_for_roles(self.roles(organization_id, principal))

    def _require(self, organization_id: int, principal: CRMPrincipal, capability: SocietyCapability) -> None:
        require_capability(self.roles(organization_id, principal), capability)

    @staticmethod
    def _require_platform(principal: CRMPrincipal) -> None:
        if not principal.platform_operator:
            raise PlatformOperatorRequired()

    # -- platform -------------------------------------------------------------------------

    def create_organization(self, principal: CRMPrincipal, *, slug: str, display_name: str) -> dict[str, Any]:
        self._require_platform(principal)
        return self._repo.create_organization(slug=slug, display_name=display_name, kind="society")

    def bootstrap_admin(
        self,
        principal: CRMPrincipal,
        organization_id: int,
        *,
        display_name: str,
        auth_subject: str,
        email: str | None = None,
    ) -> dict[str, Any]:
        """Platform operator seeds (or recovers) an organization administrator."""
        self._require_platform(principal)
        subject = normalize_auth_subject(auth_subject)
        with self._repo.atomic(organization_id):
            constituent_id = self._repo.bound_constituent_id(organization_id=organization_id, auth_subject=subject)
            if constituent_id is None:
                person = self._repo.create_person(
                    organization_id=organization_id, display_name=display_name, actor_subject=principal.subject
                )
                constituent_id = int(person["id"])
                self._repo.bind_identity(
                    organization_id=organization_id,
                    constituent_id=constituent_id,
                    auth_subject=subject,
                    verification_method="platform_operator",
                    actor_subject=principal.subject,
                )
            if email:
                self._repo.set_primary_email(
                    organization_id=organization_id, constituent_id=constituent_id, email=email,
                    actor_subject=principal.subject,
                )
            return self._repo.grant_staff_role(
                organization_id=organization_id,
                constituent_id=constituent_id,
                role=SocietyRole.ADMIN,
                granted_by_subject=principal.subject,
                metadata={"via": "platform_operator_bootstrap"},
            )

    # -- roles and identity ---------------------------------------------------------------

    def my_access(self, organization_id: int, principal: CRMPrincipal) -> dict[str, Any]:
        roles = self.roles(organization_id, principal)
        return {
            "roles": sorted(role.value for role in roles),
            "capabilities": sorted(cap.value for cap in capabilities_for_roles(roles)),
            "platform_operator": principal.platform_operator,
        }

    def grant_role(
        self, principal: CRMPrincipal, organization_id: int, *, constituent_id: int, role: SocietyRole
    ) -> dict[str, Any]:
        self._require(organization_id, principal, SocietyCapability.ROLE_ADMIN)
        try:
            return self._repo.grant_staff_role(
                organization_id=organization_id, constituent_id=constituent_id, role=role,
                granted_by_subject=principal.subject,
            )
        except LookupError as exc:
            raise NotFound("CONSTITUENT_NOT_FOUND") from exc

    def revoke_role(
        self, principal: CRMPrincipal, organization_id: int, *, constituent_id: int, role: SocietyRole
    ) -> dict[str, Any]:
        self._require(organization_id, principal, SocietyCapability.ROLE_ADMIN)
        row = self._repo.revoke_staff_role(
            organization_id=organization_id, constituent_id=constituent_id, role=role,
            actor_subject=principal.subject, require_remaining_admin=True,
        )
        if row is None:
            raise NotFound("STAFF_ROLE_NOT_FOUND")
        return row

    def list_staff(self, principal: CRMPrincipal, organization_id: int) -> list[dict[str, Any]]:
        self._require(organization_id, principal, SocietyCapability.ROLE_ADMIN)
        return self._repo.list_staff(organization_id=organization_id)

    def bind_identity(
        self, principal: CRMPrincipal, organization_id: int, *, constituent_id: int, auth_subject: str
    ) -> dict[str, Any]:
        self._require(organization_id, principal, SocietyCapability.ROLE_ADMIN)
        try:
            return self._repo.bind_identity(
                organization_id=organization_id, constituent_id=constituent_id, auth_subject=auth_subject,
                verification_method="admin_attested", actor_subject=principal.subject,
            )
        except LookupError as exc:
            raise NotFound("CONSTITUENT_NOT_FOUND") from exc

    def revoke_identity(self, principal: CRMPrincipal, organization_id: int, *, auth_subject: str) -> dict[str, Any]:
        self._require(organization_id, principal, SocietyCapability.ROLE_ADMIN)
        row = self._repo.revoke_identity_binding(
            organization_id=organization_id, auth_subject=auth_subject, actor_subject=principal.subject
        )
        if row is None:
            raise NotFound("IDENTITY_BINDING_NOT_FOUND")
        return row

    # -- membership level catalog --------------------------------------------------------

    def list_levels(self, principal: CRMPrincipal, organization_id: int, *, include_inactive: bool = False):
        self._require(organization_id, principal, SocietyCapability.ROSTER_READ)
        return self._repo.list_membership_levels(organization_id=organization_id, include_inactive=include_inactive)

    def create_level(self, principal: CRMPrincipal, organization_id: int, **fields: Any) -> dict[str, Any]:
        self._require(organization_id, principal, SocietyCapability.SETTINGS_WRITE)
        return self._repo.create_membership_level(
            organization_id=organization_id, actor_subject=principal.subject, **fields
        )

    def update_level(
        self, principal: CRMPrincipal, organization_id: int, code: str, changes: dict[str, Any]
    ) -> dict[str, Any]:
        self._require(organization_id, principal, SocietyCapability.SETTINGS_WRITE)
        row = self._repo.update_membership_level(
            organization_id=organization_id, code=code, changes=changes, actor_subject=principal.subject
        )
        if row is None:
            raise NotFound("MEMBERSHIP_LEVEL_NOT_FOUND")
        return row

    # -- members ---------------------------------------------------------------------------

    def create_member(
        self,
        principal: CRMPrincipal,
        organization_id: int,
        *,
        display_name: str,
        level_code: str,
        first_name: str | None = None,
        last_name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        allow_duplicate_email: bool = False,
        source_kind: str = "manual",
    ) -> dict[str, Any]:
        """Create a person and a pending membership. Activation happens through renewal."""
        self._require(organization_id, principal, SocietyCapability.MEMBER_WRITE)
        self._require(organization_id, principal, SocietyCapability.MEMBERSHIP_WRITE)
        with self._repo.atomic(organization_id):
            if email and not allow_duplicate_email:
                if self._repo.find_constituents_by_email(organization_id=organization_id, email=email):
                    raise ValueError("DUPLICATE_MEMBER_EMAIL")
            person = self._repo.create_person(
                organization_id=organization_id, display_name=display_name, first_name=first_name,
                last_name=last_name, actor_subject=principal.subject,
            )
            constituent_id = int(person["id"])
            if email:
                self._repo.set_primary_email(
                    organization_id=organization_id, constituent_id=constituent_id, email=email,
                    actor_subject=principal.subject,
                )
            if phone:
                self._repo.set_primary_phone(
                    organization_id=organization_id, constituent_id=constituent_id, phone=phone,
                    actor_subject=principal.subject,
                )
            membership = self._repo.create_membership(
                organization_id=organization_id, constituent_id=constituent_id, level_code=level_code,
                actor_subject=principal.subject, source_kind=source_kind,
            )
        return self._member(organization_id, int(membership["id"]))

    def get_member(self, principal: CRMPrincipal, organization_id: int, membership_id: int) -> dict[str, Any]:
        self._require(organization_id, principal, SocietyCapability.ROSTER_READ)
        return self._member(organization_id, membership_id)

    def list_members(self, principal: CRMPrincipal, organization_id: int, **filters: Any):
        self._require(organization_id, principal, SocietyCapability.ROSTER_READ)
        return self._repo.list_members(organization_id=organization_id, **filters)

    def update_profile(
        self, principal: CRMPrincipal, organization_id: int, membership_id: int, changes: dict[str, Any]
    ) -> dict[str, Any]:
        self._require(organization_id, principal, SocietyCapability.MEMBER_WRITE)
        member = self._member(organization_id, membership_id)
        if changes:
            self._repo.update_person(
                organization_id=organization_id, constituent_id=member["constituent_id"], changes=changes,
                actor_subject=principal.subject,
            )
        return self._member(organization_id, membership_id)

    def change_email(self, principal: CRMPrincipal, organization_id: int, membership_id: int, email: str):
        self._require(organization_id, principal, SocietyCapability.MEMBER_WRITE)
        member = self._member(organization_id, membership_id)
        self._repo.set_primary_email(
            organization_id=organization_id, constituent_id=member["constituent_id"], email=email,
            actor_subject=principal.subject,
        )
        return self._member(organization_id, membership_id)

    def change_phone(self, principal: CRMPrincipal, organization_id: int, membership_id: int, phone: str):
        self._require(organization_id, principal, SocietyCapability.MEMBER_WRITE)
        member = self._member(organization_id, membership_id)
        self._repo.set_primary_phone(
            organization_id=organization_id, constituent_id=member["constituent_id"], phone=phone,
            actor_subject=principal.subject,
        )
        return self._member(organization_id, membership_id)

    def change_address(self, principal: CRMPrincipal, organization_id: int, membership_id: int, **address: Any):
        self._require(organization_id, principal, SocietyCapability.MEMBER_WRITE)
        member = self._member(organization_id, membership_id)
        self._repo.set_mailing_address(
            organization_id=organization_id, constituent_id=member["constituent_id"],
            actor_subject=principal.subject, **address,
        )
        return self._member(organization_id, membership_id)

    def change_status(
        self,
        principal: CRMPrincipal,
        organization_id: int,
        membership_id: int,
        status: MembershipStatus,
        *,
        reason: str | None = None,
        as_of: datetime | None = None,
    ) -> dict[str, Any]:
        self._require(organization_id, principal, SocietyCapability.MEMBERSHIP_WRITE)
        row = self._repo.update_membership_status(
            organization_id=organization_id, membership_id=membership_id, status=status,
            actor_subject=principal.subject, reason=reason, as_of=as_of,
        )
        if row is None:
            raise NotFound("MEMBERSHIP_NOT_FOUND")
        return self._member(organization_id, membership_id)

    def renew(
        self,
        principal: CRMPrincipal,
        organization_id: int,
        membership_id: int,
        *,
        renewal_key: str,
        level_code: str | None = None,
        as_of: datetime | None = None,
    ) -> dict[str, Any]:
        """Administrative (complimentary or already-reconciled) renewal.

        Payment-backed renewals are applied by the payment ledger with source
        ``offline_payment`` / ``online_payment`` under ``payment.write``.
        """
        self._require(organization_id, principal, SocietyCapability.MEMBERSHIP_WRITE)
        try:
            result = self._repo.renew_membership(
                organization_id=organization_id, membership_id=membership_id, renewal_key=renewal_key,
                source_kind="admin", actor_subject=principal.subject, level_code=level_code, as_of=as_of,
            )
        except LookupError as exc:
            raise NotFound("MEMBERSHIP_NOT_FOUND") from exc
        return {**result, "member": self._member(organization_id, membership_id)}

    def change_level(
        self, principal: CRMPrincipal, organization_id: int, membership_id: int, level_code: str,
        *, reason: str | None = None,
    ) -> dict[str, Any]:
        self._require(organization_id, principal, SocietyCapability.MEMBERSHIP_WRITE)
        row = self._repo.change_membership_level(
            organization_id=organization_id, membership_id=membership_id, level_code=level_code,
            actor_subject=principal.subject, reason=reason,
        )
        if row is None:
            raise NotFound("MEMBERSHIP_NOT_FOUND")
        return self._member(organization_id, membership_id)

    def add_household_member(
        self,
        principal: CRMPrincipal,
        organization_id: int,
        membership_id: int,
        *,
        display_name: str,
        relationship: str = "household",
        email: str | None = None,
    ) -> dict[str, Any]:
        self._require(organization_id, principal, SocietyCapability.MEMBER_WRITE)
        self._require(organization_id, principal, SocietyCapability.MEMBERSHIP_WRITE)
        self._member(organization_id, membership_id)
        with self._repo.atomic(organization_id):
            person = self._repo.create_person(
                organization_id=organization_id, display_name=display_name, actor_subject=principal.subject
            )
            if email:
                self._repo.set_primary_email(
                    organization_id=organization_id, constituent_id=int(person["id"]), email=email,
                    actor_subject=principal.subject,
                )
            self._repo.add_household_member(
                organization_id=organization_id, membership_id=membership_id, constituent_id=int(person["id"]),
                relationship=relationship, actor_subject=principal.subject,
            )
        return self._member(organization_id, membership_id)

    def run_lifecycle(self, principal: CRMPrincipal, organization_id: int, *, as_of: datetime | None = None):
        self._require(organization_id, principal, SocietyCapability.MEMBERSHIP_WRITE)
        return self._repo.apply_lifecycle(organization_id=organization_id, as_of=as_of)

    def duplicate_candidates(self, principal: CRMPrincipal, organization_id: int) -> list[dict[str, Any]]:
        self._require(organization_id, principal, SocietyCapability.ROSTER_READ)
        return self._repo.duplicate_candidates(organization_id=organization_id)

    def member_history(self, principal: CRMPrincipal, organization_id: int, membership_id: int) -> dict[str, Any]:
        self._require(organization_id, principal, SocietyCapability.AUDIT_READ)
        member = self._member(organization_id, membership_id)
        return {
            "renewals": self._repo.list_renewals(organization_id=organization_id, membership_id=membership_id),
            "audit": sorted(
                self._repo.list_audit_events(
                    organization_id=organization_id, entity_type="membership", entity_id=str(membership_id)
                )
                + self._repo.list_audit_events(
                    organization_id=organization_id, entity_type="constituent",
                    entity_id=str(member["constituent_id"]),
                ),
                key=lambda event: event["id"],
            ),
        }

    def audit_events(self, principal: CRMPrincipal, organization_id: int, *, limit: int = 200, offset: int = 0):
        self._require(organization_id, principal, SocietyCapability.AUDIT_READ)
        return self._repo.list_audit_events(organization_id=organization_id, limit=limit, offset=offset)

    # -- internals ------------------------------------------------------------------------

    def _member(self, organization_id: int, membership_id: int) -> dict[str, Any]:
        row = self._repo.get_member(organization_id=organization_id, membership_id=membership_id)
        if row is None:
            raise NotFound("MEMBERSHIP_NOT_FOUND")
        return row


__all__ = [
    "CRMPrincipal",
    "NotFound",
    "PlatformOperatorRequired",
    "SocietyAccessDenied",
    "SocietyCRMService",
]

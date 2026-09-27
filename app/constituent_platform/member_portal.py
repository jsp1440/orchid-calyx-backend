"""Member self-service portal for one society.

A signed-in person (verified Supabase subject) sees only their own record in a
society, and only after their login has been linked to that record:

* an administrator (or membership editor, for people without staff roles) issues a
  single-use invite code for the member's record;
* the member redeems the code while signed in, creating an audited
  ``member_invite`` identity binding in that society only.

Linking is per society: a member of two societies links twice, and nothing in one
society's portal reveals the other.

Self-service fields are deliberately narrow: name, phone and mailing address.
Changing the login email or membership state is not self-service (email changes need
verification; status/level changes go through renewal or an administrator).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from .authorization import SocietyAccessDenied, SocietyCapability
from .postgres_repository import PostgresSocietyCRMRepository
from .society_service import CRMPrincipal, NotFound, SocietyCRMService

INVITE_TTL_DAYS = 30
SELF_SERVICE_PROFILE_FIELDS = frozenset({"display_name", "first_name", "last_name"})

_MEMBER_VIEW_FIELDS = (
    "membership_id", "level_code", "level_name", "status", "starts_at", "expires_at", "last_renewed_at",
    "display_name", "first_name", "last_name", "primary_email", "primary_phone", "mailing_line1",
    "mailing_line2", "mailing_locality", "mailing_administrative_area", "mailing_postal_code",
    "mailing_country_code",
)


def _code_hash(code: str) -> str:
    return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()


class MemberPortalService:
    def __init__(self, repository: PostgresSocietyCRMRepository, crm: SocietyCRMService | None = None) -> None:
        self._repo = repository
        self._crm = crm or SocietyCRMService(repository)

    # -- administrator side ------------------------------------------------------------

    def issue_invite(
        self, principal: CRMPrincipal, organization_id: int, membership_id: int, *,
        ttl_days: int = INVITE_TTL_DAYS, as_of: datetime | None = None,
    ) -> dict[str, Any]:
        """Return a one-time code (shown once) for the member to link their login.

        Linking a login to someone who holds a staff role would hand that login staff
        authority, so for staff records this requires ``role.admin``; for ordinary
        members ``member.write`` is enough.
        """
        member = self._crm.get_member(principal, organization_id, membership_id)
        constituent_id = int(member["constituent_id"])
        staff = [row for row in self._repo.list_staff(organization_id=organization_id)
                 if row["constituent_id"] == constituent_id and row["status"] == "active"]
        required = SocietyCapability.ROLE_ADMIN if staff else SocietyCapability.MEMBER_WRITE
        caps = self._crm.capabilities(organization_id, principal)
        if required not in caps:
            raise SocietyAccessDenied(required)
        if not 1 <= ttl_days <= 90:
            raise ValueError("INVALID_INVITE_TTL")
        code = secrets.token_urlsafe(24)
        now = as_of or datetime.now(timezone.utc)
        invite = self._repo.create_portal_invite(
            organization_id=organization_id, constituent_id=constituent_id, code_sha256=_code_hash(code),
            expires_at=now + timedelta(days=ttl_days), actor_subject=principal.subject,
            issued_with_role_admin=SocietyCapability.ROLE_ADMIN in caps,
        )
        return {"code": code, "expires_at": invite["expires_at"], "membership_id": membership_id}

    # -- member side -------------------------------------------------------------------

    def redeem_invite(self, principal: CRMPrincipal, organization_id: int, code: str, *,
                      as_of: datetime | None = None) -> dict[str, Any]:
        if principal.platform_operator:
            raise ValueError("PORTAL_REQUIRES_MEMBER_LOGIN")
        if not code or len(code) > 200:
            raise ValueError("INVITE_INVALID_OR_EXPIRED")
        self._repo.redeem_portal_invite(
            organization_id=organization_id, code_sha256=_code_hash(code), auth_subject=principal.subject,
            as_of=as_of,
        )
        return self.my_membership(principal, organization_id)

    def my_membership(self, principal: CRMPrincipal, organization_id: int) -> dict[str, Any]:
        constituent_id = self._constituent(principal, organization_id)
        member = self._repo.get_member_by_constituent(organization_id=organization_id, constituent_id=constituent_id)
        if member is None:
            raise NotFound("MEMBERSHIP_NOT_FOUND")
        detail = self._repo.get_member(organization_id=organization_id, membership_id=int(member["membership_id"]))
        view = {field: detail.get(field) for field in _MEMBER_VIEW_FIELDS}
        view["household_members"] = [
            {"display_name": h["display_name"], "relationship": h["relationship"]}
            for h in detail.get("household_members", [])
        ]
        view["renewals"] = [
            {"renewed_at": r["created_at"], "new_expires_at": r["new_expires_at"], "level_code": r["level_code"],
             "source_kind": r["source_kind"]}
            for r in self._repo.list_renewals(organization_id=organization_id,
                                              membership_id=int(member["membership_id"]))
        ]
        view["can_renew"] = view["status"] in ("active", "grace", "lapsed")
        return view

    def update_my_profile(self, principal: CRMPrincipal, organization_id: int, changes: dict[str, Any]):
        constituent_id = self._constituent(principal, organization_id)
        unknown = set(changes) - SELF_SERVICE_PROFILE_FIELDS
        if unknown:
            raise ValueError(f"MEMBER_FIELD_NOT_EDITABLE:{sorted(unknown)[0]}")
        if changes:
            self._repo.update_person(organization_id=organization_id, constituent_id=constituent_id,
                                     changes=changes, actor_subject=principal.subject)
        return self.my_membership(principal, organization_id)

    def update_my_phone(self, principal: CRMPrincipal, organization_id: int, phone: str):
        constituent_id = self._constituent(principal, organization_id)
        self._repo.set_primary_phone(organization_id=organization_id, constituent_id=constituent_id,
                                     phone=phone, actor_subject=principal.subject)
        return self.my_membership(principal, organization_id)

    def update_my_address(self, principal: CRMPrincipal, organization_id: int, **address: Any):
        constituent_id = self._constituent(principal, organization_id)
        self._repo.set_mailing_address(organization_id=organization_id, constituent_id=constituent_id,
                                       actor_subject=principal.subject, **address)
        return self.my_membership(principal, organization_id)

    def _constituent(self, principal: CRMPrincipal, organization_id: int) -> int:
        constituent_id = self._repo.bound_constituent_id(organization_id=organization_id,
                                                         auth_subject=principal.subject)
        if constituent_id is None:
            raise NotFound("PORTAL_NOT_LINKED")
        return constituent_id

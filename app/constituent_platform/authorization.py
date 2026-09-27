"""Organization-scoped authorization policy for the society CRM.

Ordinary society membership is intentionally not an administrative role.
Authorization is capability based so routes can require the minimum privilege.

Least-privilege notes:

* ``viewer`` sees the roster but not money, donations, or the audit trail.
* ``treasurer`` records and reads payments/donations and may export the roster for
  reconciliation, but cannot edit people, change membership records directly,
  import, change settings, grant roles, or take a full organization export.
* ``membership_editor`` maintains people and memberships and may import/export the
  roster, but never sees payments or donations and cannot grant roles.
* Only ``admin`` holds ``role.admin``, ``settings.write``, ``organization.export``
  and ``diagnostics.read``.

No capability here reaches private Conservatory, OASIS, Calyx, research, donor
financial-system, restricted-locality, or collection data: those systems are not
part of this policy, and the CRM runtime database role has no grants on them.
"""

from __future__ import annotations

from enum import Enum


class SocietyRole(str, Enum):
    ADMIN = "admin"
    TREASURER = "treasurer"
    MEMBERSHIP_EDITOR = "membership_editor"
    COMMUNICATIONS_MANAGER = "communications_manager"
    EVENT_MANAGER = "event_manager"
    VIEWER = "viewer"


class SocietyCapability(str, Enum):
    ROSTER_READ = "roster.read"
    MEMBER_WRITE = "member.write"
    MEMBERSHIP_WRITE = "membership.write"
    PAYMENT_READ = "payment.read"
    PAYMENT_WRITE = "payment.write"
    DONATION_READ = "donation.read"
    DONATION_WRITE = "donation.write"
    COMMUNICATION_READ = "communication.read"
    COMMUNICATION_WRITE = "communication.write"
    EVENT_READ = "event.read"
    EVENT_WRITE = "event.write"
    MEMBER_IMPORT = "member.import"
    ROSTER_EXPORT = "roster.export"
    ORGANIZATION_EXPORT = "organization.export"
    AUDIT_READ = "audit.read"
    ROLE_ADMIN = "role.admin"
    SETTINGS_WRITE = "settings.write"
    DIAGNOSTICS_READ = "diagnostics.read"


_ROLE_CAPABILITIES: dict[SocietyRole, frozenset[SocietyCapability]] = {
    SocietyRole.ADMIN: frozenset(SocietyCapability),
    SocietyRole.TREASURER: frozenset(
        {
            SocietyCapability.ROSTER_READ,
            SocietyCapability.PAYMENT_READ,
            SocietyCapability.PAYMENT_WRITE,
            SocietyCapability.DONATION_READ,
            SocietyCapability.DONATION_WRITE,
            SocietyCapability.ROSTER_EXPORT,
            SocietyCapability.AUDIT_READ,
        }
    ),
    SocietyRole.MEMBERSHIP_EDITOR: frozenset(
        {
            SocietyCapability.ROSTER_READ,
            SocietyCapability.MEMBER_WRITE,
            SocietyCapability.MEMBERSHIP_WRITE,
            SocietyCapability.MEMBER_IMPORT,
            SocietyCapability.ROSTER_EXPORT,
            SocietyCapability.AUDIT_READ,
        }
    ),
    SocietyRole.COMMUNICATIONS_MANAGER: frozenset(
        {
            SocietyCapability.ROSTER_READ,
            SocietyCapability.COMMUNICATION_READ,
            SocietyCapability.COMMUNICATION_WRITE,
        }
    ),
    SocietyRole.EVENT_MANAGER: frozenset(
        {
            SocietyCapability.ROSTER_READ,
            SocietyCapability.EVENT_READ,
            SocietyCapability.EVENT_WRITE,
        }
    ),
    SocietyRole.VIEWER: frozenset(
        {
            SocietyCapability.ROSTER_READ,
            SocietyCapability.COMMUNICATION_READ,
            SocietyCapability.EVENT_READ,
        }
    ),
}


class SocietyAccessDenied(PermissionError):
    """The caller holds no role in this organization granting the capability."""

    def __init__(self, capability: SocietyCapability) -> None:
        self.capability = capability
        self.code = f"SOCIETY_CAPABILITY_REQUIRED:{capability.value}"
        super().__init__(self.code)


def capabilities_for_roles(roles: set[SocietyRole] | frozenset[SocietyRole]) -> frozenset[SocietyCapability]:
    capabilities: set[SocietyCapability] = set()
    for role in roles:
        capabilities.update(_ROLE_CAPABILITIES[role])
    return frozenset(capabilities)


def is_authorized(
    roles: set[SocietyRole] | frozenset[SocietyRole],
    capability: SocietyCapability,
) -> bool:
    return capability in capabilities_for_roles(roles)


def require_capability(
    roles: set[SocietyRole] | frozenset[SocietyRole],
    capability: SocietyCapability,
) -> None:
    if not is_authorized(roles, capability):
        raise SocietyAccessDenied(capability)

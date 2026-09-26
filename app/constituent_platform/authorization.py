"""Organization-scoped authorization policy for the society CRM.

Ordinary society membership is intentionally not an administrative role.
Authorization is capability based so routes can require the minimum privilege.
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
    COMMUNICATION_READ = "communication.read"
    COMMUNICATION_WRITE = "communication.write"
    EVENT_READ = "event.read"
    EVENT_WRITE = "event.write"
    IMPORT_EXPORT = "import_export"
    AUDIT_READ = "audit.read"
    ROLE_ADMIN = "role.admin"


_ROLE_CAPABILITIES: dict[SocietyRole, frozenset[SocietyCapability]] = {
    SocietyRole.ADMIN: frozenset(SocietyCapability),
    SocietyRole.TREASURER: frozenset(
        {
            SocietyCapability.ROSTER_READ,
            SocietyCapability.PAYMENT_READ,
            SocietyCapability.PAYMENT_WRITE,
            SocietyCapability.IMPORT_EXPORT,
            SocietyCapability.AUDIT_READ,
        }
    ),
    SocietyRole.MEMBERSHIP_EDITOR: frozenset(
        {
            SocietyCapability.ROSTER_READ,
            SocietyCapability.MEMBER_WRITE,
            SocietyCapability.MEMBERSHIP_WRITE,
            SocietyCapability.IMPORT_EXPORT,
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
            SocietyCapability.PAYMENT_READ,
            SocietyCapability.COMMUNICATION_READ,
            SocietyCapability.EVENT_READ,
            SocietyCapability.AUDIT_READ,
        }
    ),
}


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
        raise PermissionError(f"SOCIETY_CAPABILITY_REQUIRED:{capability.value}")

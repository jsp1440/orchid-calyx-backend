from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .models import AccessPrincipal, MissionControlRole


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class AuthenticatedIdentity:
    subject_id: str | None
    authenticated: bool
    role_names: tuple[str, ...] = ()
    direct_capabilities: tuple[str, ...] = ()
    qualifications: tuple[str, ...] = ()
    qualification_expires_at: dict[str, str] = field(default_factory=dict)
    specialties: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)


class PrincipalResolutionError(ValueError):
    def __init__(self, code: str, details: dict[str, Any] | None = None) -> None:
        self.code = code
        self.details = details or {}
        super().__init__(code)


class PrincipalResolver:
    """Resolve authentication-layer identity claims into a governed principal."""

    def resolve(
        self,
        identity: AuthenticatedIdentity | None,
        *,
        at: datetime | None = None,
    ) -> AccessPrincipal:
        if identity is None or not identity.authenticated:
            return AccessPrincipal(
                principal_id="anonymous",
                roles=(MissionControlRole.PUBLIC,),
                authenticated=False,
                metadata={"resolution": "anonymous"},
            )
        if not identity.subject_id:
            raise PrincipalResolutionError("AUTHENTICATED_SUBJECT_REQUIRED")

        roles: list[MissionControlRole] = []
        for role_name in identity.role_names:
            try:
                roles.append(MissionControlRole(role_name))
            except ValueError as exc:
                raise PrincipalResolutionError(
                    "UNKNOWN_ROLE", {"role": role_name}
                ) from exc
        if MissionControlRole.PUBLIC not in roles:
            roles.append(MissionControlRole.PUBLIC)

        resolved_at = at or _now()
        active_qualifications: list[str] = []
        expired_qualifications: list[str] = []
        for qualification in identity.qualifications:
            expires_at = identity.qualification_expires_at.get(qualification)
            if expires_at is None:
                active_qualifications.append(qualification)
                continue
            try:
                expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise PrincipalResolutionError(
                    "INVALID_QUALIFICATION_EXPIRY",
                    {"qualification": qualification, "expires_at": expires_at},
                ) from exc
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry > resolved_at:
                active_qualifications.append(qualification)
            else:
                expired_qualifications.append(qualification)

        metadata = dict(identity.metadata)
        metadata.update(
            {
                "resolution": "authenticated",
                "expired_qualifications": ",".join(sorted(expired_qualifications)),
            }
        )
        return AccessPrincipal(
            principal_id=identity.subject_id,
            roles=tuple(sorted(set(roles), key=lambda item: item.value)),
            direct_capabilities=tuple(sorted(set(identity.direct_capabilities))),
            qualifications=tuple(sorted(set(active_qualifications))),
            specialties=tuple(sorted(set(identity.specialties))),
            authenticated=True,
            metadata=metadata,
        )

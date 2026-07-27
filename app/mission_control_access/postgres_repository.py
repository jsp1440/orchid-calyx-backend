from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .models import AccessPrincipal, MissionControlRole
from app.review_tasks.postgres_repository import ConnectionFactory, _decode, _json, _row, _transaction


class PostgresAccessPrincipalRepository:
    """Persistent, auditable snapshot store for resolved access principals."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self.connection_factory = connection_factory

    def save(
        self,
        principal: AccessPrincipal,
        *,
        source_identity: dict[str, Any] | None = None,
        resolved_at: str | None = None,
    ) -> AccessPrincipal:
        timestamp = resolved_at or datetime.now(timezone.utc).isoformat()
        with _transaction(self.connection_factory) as (_, cursor):
            cursor.execute(
                """
                INSERT INTO oc_review.access_principal (
                    principal_id, authenticated, roles, direct_capabilities,
                    qualifications, specialties, metadata, source_identity, resolved_at
                ) VALUES (%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s)
                ON CONFLICT (principal_id) DO UPDATE SET
                    authenticated = EXCLUDED.authenticated,
                    roles = EXCLUDED.roles,
                    direct_capabilities = EXCLUDED.direct_capabilities,
                    qualifications = EXCLUDED.qualifications,
                    specialties = EXCLUDED.specialties,
                    metadata = EXCLUDED.metadata,
                    source_identity = EXCLUDED.source_identity,
                    resolved_at = EXCLUDED.resolved_at,
                    updated_at = now()
                RETURNING *
                """,
                (
                    principal.principal_id,
                    principal.authenticated,
                    _json([role.value for role in principal.roles]),
                    _json(list(principal.direct_capabilities)),
                    _json(list(principal.qualifications)),
                    _json(list(principal.specialties)),
                    _json(principal.metadata),
                    _json(source_identity or {}),
                    timestamp,
                ),
            )
            stored = _row(cursor, cursor.fetchone())
            assert stored is not None
            return self._principal(stored)

    def get(self, principal_id: str) -> AccessPrincipal | None:
        with _transaction(self.connection_factory) as (_, cursor):
            cursor.execute(
                "SELECT * FROM oc_review.access_principal WHERE principal_id = %s",
                (principal_id,),
            )
            stored = _row(cursor, cursor.fetchone())
            return self._principal(stored) if stored else None

    @staticmethod
    def _principal(stored: dict[str, Any]) -> AccessPrincipal:
        roles = tuple(MissionControlRole(item) for item in _decode(stored.get("roles", [])))
        return AccessPrincipal(
            principal_id=str(stored["principal_id"]),
            roles=roles,
            direct_capabilities=tuple(_decode(stored.get("direct_capabilities", []))),
            qualifications=tuple(_decode(stored.get("qualifications", []))),
            specialties=tuple(_decode(stored.get("specialties", []))),
            authenticated=bool(stored["authenticated"]),
            metadata=dict(_decode(stored.get("metadata", {}))),
        )

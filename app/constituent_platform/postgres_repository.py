"""Canonical PostgreSQL repository for society CRM pilot operations.

This module deliberately scopes every society-owned read/write by organization_id.
It is the first application consumer of the canonical oc_constituent schema.

It does not implement database RLS by itself; deployed role/RLS enforcement remains
a separate production gate. Service-level organization scoping here is explicit and
covered by cross-tenant tests.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .domain import MembershipStatus, normalize_email

_LEVEL_CODE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


def database_url() -> str:
    value = os.environ.get("DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL is required for society CRM operations")
    return value


class PostgresSocietyCRMRepository:
    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn or database_url()

    def _connect(self):
        return psycopg.connect(self._dsn, row_factory=dict_row)

    def create_organization(
        self,
        *,
        slug: str,
        display_name: str,
        kind: str = "society",
    ) -> dict[str, Any]:
        normalized_slug = slug.strip().lower()
        if not normalized_slug:
            raise ValueError("ORGANIZATION_SLUG_REQUIRED")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oc_constituent.organizations (slug, display_name, kind)
                VALUES (%s, %s, %s)
                RETURNING id, slug, display_name, kind, status, created_at, updated_at
                """,
                (normalized_slug, display_name.strip(), kind),
            )
            return dict(cur.fetchone())

    def create_membership_level(
        self,
        *,
        organization_id: int,
        code: str,
        display_name: str,
        dues_amount_cents: int = 0,
        currency: str = "USD",
        term_months: int = 12,
        description: str | None = None,
        benefits: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_code = code.strip().lower()
        if not _LEVEL_CODE.fullmatch(normalized_code):
            raise ValueError("INVALID_MEMBERSHIP_LEVEL_CODE")
        if dues_amount_cents < 0:
            raise ValueError("INVALID_DUES_AMOUNT")
        if term_months < 1:
            raise ValueError("INVALID_MEMBERSHIP_TERM")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oc_constituent.membership_levels
                    (organization_id, code, display_name, description,
                     dues_amount_cents, currency, term_months, benefits)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    organization_id,
                    normalized_code,
                    display_name.strip(),
                    description,
                    dues_amount_cents,
                    currency.strip().upper(),
                    term_months,
                    Jsonb(benefits or {}),
                ),
            )
            return dict(cur.fetchone())

    def create_person(
        self,
        *,
        display_name: str,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oc_constituent.constituents
                    (kind, display_name, first_name, last_name)
                VALUES ('person', %s, %s, %s)
                RETURNING *
                """,
                (display_name.strip(), first_name, last_name),
            )
            return dict(cur.fetchone())

    def add_email(
        self,
        *,
        organization_id: int,
        constituent_id: int,
        email: str,
        is_primary: bool = True,
        verification_state: str = "unverified",
    ) -> dict[str, Any]:
        normalized = normalize_email(email)
        verified_at = datetime.utcnow() if verification_state == "verified" else None
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oc_constituent.email_addresses
                    (constituent_id, organization_id, normalized_email,
                     is_primary, verification_state, verified_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    constituent_id,
                    organization_id,
                    normalized,
                    is_primary,
                    verification_state,
                    verified_at,
                ),
            )
            return dict(cur.fetchone())

    def create_membership(
        self,
        *,
        organization_id: int,
        constituent_id: int,
        level_code: str,
        status: MembershipStatus = MembershipStatus.PENDING,
        starts_at: datetime | None = None,
        expires_at: datetime | None = None,
        source_kind: str = "manual",
        source_ref: str | None = None,
        actor_subject: str,
    ) -> dict[str, Any]:
        normalized_level = level_code.strip().lower()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM oc_constituent.membership_levels
                WHERE organization_id = %s AND code = %s AND is_active
                """,
                (organization_id, normalized_level),
            )
            if cur.fetchone() is None:
                raise ValueError("UNKNOWN_MEMBERSHIP_LEVEL")
            cur.execute(
                """
                INSERT INTO oc_constituent.memberships
                    (organization_id, constituent_id, level_code, status,
                     starts_at, expires_at, source_kind, source_ref)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    organization_id,
                    constituent_id,
                    normalized_level,
                    status.value,
                    starts_at,
                    expires_at,
                    source_kind,
                    source_ref,
                ),
            )
            membership = dict(cur.fetchone())
            self._audit(
                cur,
                organization_id=organization_id,
                actor_subject=actor_subject,
                action="membership.created",
                entity_type="membership",
                entity_id=str(membership["id"]),
                before_state=None,
                after_state=membership,
            )
            return membership

    def get_member(self, *, organization_id: int, membership_id: int) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    m.id AS membership_id,
                    m.organization_id,
                    m.constituent_id,
                    m.level_code,
                    m.status,
                    m.starts_at,
                    m.expires_at,
                    c.display_name,
                    c.first_name,
                    c.last_name,
                    e.normalized_email AS primary_email
                FROM oc_constituent.memberships m
                JOIN oc_constituent.constituents c ON c.id = m.constituent_id
                LEFT JOIN oc_constituent.email_addresses e
                    ON e.constituent_id = c.id
                   AND e.organization_id = m.organization_id
                   AND e.is_primary
                WHERE m.organization_id = %s AND m.id = %s
                """,
                (organization_id, membership_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def list_members(self, *, organization_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    m.id AS membership_id,
                    m.constituent_id,
                    m.level_code,
                    m.status,
                    m.starts_at,
                    m.expires_at,
                    c.display_name,
                    e.normalized_email AS primary_email
                FROM oc_constituent.memberships m
                JOIN oc_constituent.constituents c ON c.id = m.constituent_id
                LEFT JOIN oc_constituent.email_addresses e
                    ON e.constituent_id = c.id
                   AND e.organization_id = m.organization_id
                   AND e.is_primary
                WHERE m.organization_id = %s
                ORDER BY lower(c.display_name), m.id
                """,
                (organization_id,),
            )
            return [dict(row) for row in cur.fetchall()]

    def update_membership_status(
        self,
        *,
        organization_id: int,
        membership_id: int,
        status: MembershipStatus,
        actor_subject: str,
    ) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM oc_constituent.memberships
                WHERE organization_id = %s AND id = %s
                FOR UPDATE
                """,
                (organization_id, membership_id),
            )
            before = cur.fetchone()
            if before is None:
                return None
            cur.execute(
                """
                UPDATE oc_constituent.memberships
                SET status = %s, updated_at = NOW()
                WHERE organization_id = %s AND id = %s
                RETURNING *
                """,
                (status.value, organization_id, membership_id),
            )
            after = dict(cur.fetchone())
            self._audit(
                cur,
                organization_id=organization_id,
                actor_subject=actor_subject,
                action="membership.status_changed",
                entity_type="membership",
                entity_id=str(membership_id),
                before_state=dict(before),
                after_state=after,
            )
            return after

    def list_audit_events(self, *, organization_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM oc_constituent.crm_audit_events
                WHERE organization_id = %s
                ORDER BY id
                """,
                (organization_id,),
            )
            return [dict(row) for row in cur.fetchall()]

    @staticmethod
    def _audit(
        cur,
        *,
        organization_id: int,
        actor_subject: str,
        action: str,
        entity_type: str,
        entity_id: str,
        before_state: dict[str, Any] | None,
        after_state: dict[str, Any] | None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        cur.execute(
            """
            INSERT INTO oc_constituent.crm_audit_events
                (organization_id, actor_subject, action, entity_type, entity_id,
                 before_state, after_state, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                organization_id,
                actor_subject,
                action,
                entity_type,
                entity_id,
                Jsonb(before_state) if before_state is not None else None,
                Jsonb(after_state) if after_state is not None else None,
                Jsonb(metadata or {}),
            ),
        )

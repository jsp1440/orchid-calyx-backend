"""Canonical PostgreSQL repository for society CRM operations.

Every society-owned read/write:

* runs inside ``tenant_transaction`` (RLS runtime role + transaction-local tenant),
  so a missing filter still cannot see another tenant, and pooled connections carry
  no tenant between requests;
* also filters explicitly by ``organization_id`` (belt and braces);
* writes its audit event in the same transaction as the change, so a mutation and
  its audit record commit or roll back together.

Composite foreign keys in ``20260927_society_crm_p1_tenant_isolation.sql`` make it
structurally impossible for a Society A row to reference a Society B person, level
or membership.

This repository does not authorize callers. ``society_service.SocietyCRMService``
resolves the caller's roles in the target organization and requires the capability
before calling it; nothing outside that service should call the mutating methods.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .authorization import SocietyRole
from .domain import (
    MembershipStatus,
    lifecycle_status_at,
    normalize_auth_subject,
    normalize_email,
    renewal_term,
    validate_membership_transition,
    validate_society_entitlement_code,
)
from .tenant_db import (
    ConnectionFactory,
    database_url,
    dsn_connection_factory,
    platform_transaction,
    tenant_transaction,
)

__all__ = ["PostgresSocietyCRMRepository", "database_url"]

_LEVEL_CODE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
_ORG_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
_RESERVED_SLUGS = frozenset({"webhooks", "platform", "api", "admin", "orchid-continuum"})
_RENEWAL_SOURCES = frozenset({"admin", "offline_payment", "online_payment", "import"})
_IDENTITY_METHODS = frozenset({"platform_operator", "admin_attested", "verified_email_match", "member_invite"})
_LEVEL_MUTABLE = frozenset(
    {"display_name", "description", "dues_amount_cents", "currency", "term_months", "grace_days",
     "household_max_members", "benefits", "is_active"}
)
_PERSON_MUTABLE = frozenset({"display_name", "first_name", "last_name"})
_MAX_PAGE = 500


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_text(value: str | None, *, limit: int, required: bool = False, code: str = "INVALID_TEXT") -> str | None:
    if value is None:
        if required:
            raise ValueError(code)
        return None
    cleaned = " ".join(str(value).split())[:limit]
    if required and not cleaned:
        raise ValueError(code)
    return cleaned or None


def _actor(subject: str) -> str:
    return normalize_auth_subject(subject)


class PostgresSocietyCRMRepository:
    def __init__(self, dsn: str | None = None, *, connect: ConnectionFactory | None = None) -> None:
        self._connect = connect or dsn_connection_factory(dsn)
        self._unit: ContextVar[tuple[int, psycopg.Connection] | None] = ContextVar(
            f"oc_crm_unit_{id(self)}", default=None
        )

    # -- transactions -------------------------------------------------------------------

    @contextmanager
    def atomic(self, organization_id: int) -> Iterator[None]:
        """Run several repository calls for one tenant as a single transaction.

        Inner calls become savepoints on the same connection; any exception rolls the
        whole unit back, so a multi-step workflow never leaves partial rows.
        """
        bound = self._unit.get()
        if bound is not None:
            if bound[0] != organization_id:
                raise RuntimeError("CRM_UNIT_TENANT_MISMATCH")
            yield
            return
        conn = self._connect()
        token = self._unit.set((organization_id, conn))
        try:
            with conn.transaction():
                yield
        finally:
            self._unit.reset(token)
            conn.close()

    def _tenant(self, organization_id: int, connection: psycopg.Connection | None = None):
        bound = self._unit.get()
        if connection is None and bound is not None:
            if bound[0] != organization_id:
                raise RuntimeError("CRM_UNIT_TENANT_MISMATCH")
            connection = bound[1]
        return tenant_transaction(organization_id, connect=self._connect, connection=connection)

    def _platform(self):
        return platform_transaction(connect=self._connect)

    # -- platform (non-tenant) operations ----------------------------------------------

    def create_organization(self, *, slug: str, display_name: str, kind: str = "society") -> dict[str, Any]:
        normalized_slug = slug.strip().lower()
        if not _ORG_SLUG.fullmatch(normalized_slug) or normalized_slug in _RESERVED_SLUGS:
            raise ValueError("INVALID_ORGANIZATION_SLUG")
        name = _clean_text(display_name, limit=200, required=True, code="ORGANIZATION_NAME_REQUIRED")
        with self._platform() as cur:
            cur.execute(
                """
                INSERT INTO oc_constituent.organizations (slug, display_name, kind)
                VALUES (%s, %s, %s)
                ON CONFLICT (slug) DO NOTHING
                RETURNING id, slug, display_name, kind, status, created_at, updated_at
                """,
                (normalized_slug, name, kind),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError("ORGANIZATION_SLUG_TAKEN")
            return dict(row)

    def get_organization_by_slug(self, slug: str) -> dict[str, Any] | None:
        with self._platform() as cur:
            cur.execute(
                """
                SELECT id, slug, display_name, kind, status
                FROM oc_constituent.organizations
                WHERE slug = %s
                """,
                (slug.strip().lower(),),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def link_identity(self, *, constituent_id: int, auth_subject: str) -> dict[str, Any]:
        """Platform-account identity link (global). Society authority never uses it."""
        normalized = normalize_auth_subject(auth_subject)
        with self._platform() as cur:
            cur.execute(
                """
                INSERT INTO oc_constituent.identity_links (constituent_id, auth_subject)
                VALUES (%s, %s)
                ON CONFLICT (auth_subject) DO NOTHING
                RETURNING *
                """,
                (constituent_id, normalized),
            )
            row = cur.fetchone()
            if row is not None:
                return dict(row)
            cur.execute("SELECT * FROM oc_constituent.identity_links WHERE auth_subject = %s", (normalized,))
            existing = cur.fetchone()
            if existing is None:
                raise RuntimeError("IDENTITY_LINK_CONFLICT_NOT_READABLE")
            if existing["constituent_id"] != constituent_id:
                raise ValueError("AUTH_SUBJECT_ALREADY_LINKED")
            return dict(existing)

    # -- identity bindings ---------------------------------------------------------------

    def bind_identity(
        self,
        *,
        organization_id: int,
        constituent_id: int,
        auth_subject: str,
        verification_method: str,
        actor_subject: str,
    ) -> dict[str, Any]:
        subject = normalize_auth_subject(auth_subject)
        actor = _actor(actor_subject)
        if verification_method not in _IDENTITY_METHODS:
            raise ValueError("INVALID_IDENTITY_VERIFICATION_METHOD")
        with self._tenant(organization_id) as cur:
            self._require_constituent(cur, organization_id, constituent_id)
            cur.execute(
                """
                SELECT * FROM oc_constituent.organization_identity_bindings
                WHERE organization_id = %s AND status = 'active'
                  AND (auth_subject = %s OR constituent_id = %s)
                FOR UPDATE
                """,
                (organization_id, subject, constituent_id),
            )
            for existing in cur.fetchall():
                if existing["auth_subject"] == subject and existing["constituent_id"] == constituent_id:
                    return dict(existing)
                if existing["auth_subject"] == subject:
                    raise ValueError("AUTH_SUBJECT_ALREADY_BOUND")
                raise ValueError("CONSTITUENT_ALREADY_BOUND")
            cur.execute(
                """
                INSERT INTO oc_constituent.organization_identity_bindings
                    (organization_id, constituent_id, auth_subject, verification_method, bound_by_subject)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
                """,
                (organization_id, constituent_id, subject, verification_method, actor),
            )
            row = dict(cur.fetchone())
            self._audit(cur, organization_id=organization_id, actor_subject=actor,
                        action="identity_binding.created", entity_type="identity_binding",
                        entity_id=str(row["id"]), before_state=None, after_state=row)
            return row

    def revoke_identity_binding(
        self, *, organization_id: int, auth_subject: str, actor_subject: str
    ) -> dict[str, Any] | None:
        subject = normalize_auth_subject(auth_subject)
        actor = _actor(actor_subject)
        with self._tenant(organization_id) as cur:
            cur.execute(
                """
                SELECT * FROM oc_constituent.organization_identity_bindings
                WHERE organization_id = %s AND auth_subject = %s AND status = 'active'
                FOR UPDATE
                """,
                (organization_id, subject),
            )
            before = cur.fetchone()
            if before is None:
                return None
            cur.execute(
                """
                UPDATE oc_constituent.organization_identity_bindings
                SET status = 'revoked', revoked_at = NOW(), revoked_by_subject = %s
                WHERE organization_id = %s AND id = %s
                RETURNING *
                """,
                (actor, organization_id, before["id"]),
            )
            after = dict(cur.fetchone())
            self._audit(cur, organization_id=organization_id, actor_subject=actor,
                        action="identity_binding.revoked", entity_type="identity_binding",
                        entity_id=str(after["id"]), before_state=dict(before), after_state=after)
            return after

    def bound_constituent_id(self, *, organization_id: int, auth_subject: str) -> int | None:
        subject = normalize_auth_subject(auth_subject)
        with self._tenant(organization_id) as cur:
            cur.execute(
                """
                SELECT constituent_id FROM oc_constituent.organization_identity_bindings
                WHERE organization_id = %s AND auth_subject = %s AND status = 'active'
                """,
                (organization_id, subject),
            )
            row = cur.fetchone()
            return int(row["constituent_id"]) if row else None

    # -- staff roles --------------------------------------------------------------------

    def grant_staff_role(
        self,
        *,
        organization_id: int,
        constituent_id: int,
        role: SocietyRole,
        granted_by_subject: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        actor = _actor(granted_by_subject)
        with self._tenant(organization_id) as cur:
            self._require_constituent(cur, organization_id, constituent_id)
            cur.execute(
                """
                SELECT * FROM oc_constituent.organization_staff_roles
                WHERE organization_id = %s AND constituent_id = %s AND role_code = %s
                FOR UPDATE
                """,
                (organization_id, constituent_id, role.value),
            )
            before = cur.fetchone()
            if before is not None and before["status"] == "active":
                return dict(before)
            cur.execute(
                """
                INSERT INTO oc_constituent.organization_staff_roles
                    (organization_id, constituent_id, role_code, status,
                     granted_by_subject, granted_at, revoked_at)
                VALUES (%s, %s, %s, 'active', %s, NOW(), NULL)
                ON CONFLICT (organization_id, constituent_id, role_code)
                DO UPDATE SET
                    status = 'active',
                    granted_by_subject = EXCLUDED.granted_by_subject,
                    granted_at = NOW(),
                    revoked_at = NULL
                RETURNING *
                """,
                (organization_id, constituent_id, role.value, actor),
            )
            role_row = dict(cur.fetchone())
            self._audit(cur, organization_id=organization_id, actor_subject=actor,
                        action="staff_role.granted", entity_type="staff_role",
                        entity_id=str(role_row["id"]),
                        before_state=dict(before) if before else None, after_state=role_row,
                        metadata=metadata)
            return role_row

    def revoke_staff_role(
        self,
        *,
        organization_id: int,
        constituent_id: int,
        role: SocietyRole,
        actor_subject: str,
        require_remaining_admin: bool = False,
    ) -> dict[str, Any] | None:
        actor = _actor(actor_subject)
        with self._tenant(organization_id) as cur:
            cur.execute(
                """
                SELECT * FROM oc_constituent.organization_staff_roles
                WHERE organization_id = %s AND constituent_id = %s AND role_code = %s
                  AND status <> 'revoked'
                FOR UPDATE
                """,
                (organization_id, constituent_id, role.value),
            )
            before = cur.fetchone()
            if before is None:
                return None
            if require_remaining_admin and role is SocietyRole.ADMIN:
                cur.execute(
                    """
                    SELECT count(*) AS n FROM oc_constituent.organization_staff_roles
                    WHERE organization_id = %s AND role_code = 'admin' AND status = 'active'
                      AND constituent_id <> %s
                    """,
                    (organization_id, constituent_id),
                )
                if cur.fetchone()["n"] < 1:
                    raise ValueError("LAST_ADMIN_REQUIRED")
            cur.execute(
                """
                UPDATE oc_constituent.organization_staff_roles
                SET status = 'revoked', revoked_at = NOW()
                WHERE organization_id = %s AND id = %s
                RETURNING *
                """,
                (organization_id, before["id"]),
            )
            after = dict(cur.fetchone())
            self._audit(cur, organization_id=organization_id, actor_subject=actor,
                        action="staff_role.revoked", entity_type="staff_role",
                        entity_id=str(after["id"]), before_state=dict(before), after_state=after)
            return after

    def staff_roles_for_subject(self, *, organization_id: int, auth_subject: str) -> frozenset[SocietyRole]:
        """Active roles reached only through an active identity binding in this organization."""
        normalized = normalize_auth_subject(auth_subject)
        with self._tenant(organization_id) as cur:
            cur.execute(
                """
                SELECT r.role_code
                FROM oc_constituent.organization_staff_roles r
                JOIN oc_constituent.organization_identity_bindings b
                  ON b.organization_id = r.organization_id
                 AND b.constituent_id = r.constituent_id
                 AND b.status = 'active'
                WHERE r.organization_id = %s
                  AND b.auth_subject = %s
                  AND r.status = 'active'
                ORDER BY r.role_code
                """,
                (organization_id, normalized),
            )
            return frozenset(SocietyRole(row["role_code"]) for row in cur.fetchall())

    def list_staff(self, *, organization_id: int) -> list[dict[str, Any]]:
        with self._tenant(organization_id) as cur:
            cur.execute(
                """
                SELECT r.id, r.constituent_id, r.role_code, r.status, r.granted_by_subject,
                       r.granted_at, r.revoked_at, c.display_name
                FROM oc_constituent.organization_staff_roles r
                JOIN oc_constituent.constituents c
                  ON c.id = r.constituent_id AND c.owner_organization_id = r.organization_id
                WHERE r.organization_id = %s
                ORDER BY lower(c.display_name), r.role_code
                """,
                (organization_id,),
            )
            return [dict(row) for row in cur.fetchall()]

    # -- membership levels --------------------------------------------------------------

    def create_membership_level(
        self,
        *,
        organization_id: int,
        code: str,
        display_name: str,
        dues_amount_cents: int = 0,
        currency: str = "USD",
        term_months: int = 12,
        grace_days: int = 30,
        household_max_members: int = 1,
        description: str | None = None,
        benefits: dict[str, Any] | None = None,
        actor_subject: str = "system:society-crm",
    ) -> dict[str, Any]:
        actor = _actor(actor_subject)
        normalized_code = code.strip().lower()
        if not _LEVEL_CODE.fullmatch(normalized_code):
            raise ValueError("INVALID_MEMBERSHIP_LEVEL_CODE")
        values = self._validated_level_values(
            {
                "display_name": display_name,
                "description": description,
                "dues_amount_cents": dues_amount_cents,
                "currency": currency,
                "term_months": term_months,
                "grace_days": grace_days,
                "household_max_members": household_max_members,
                "benefits": benefits or {},
            }
        )
        with self._tenant(organization_id) as cur:
            cur.execute(
                """
                INSERT INTO oc_constituent.membership_levels
                    (organization_id, code, display_name, description, dues_amount_cents,
                     currency, term_months, grace_days, household_max_members, benefits)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (organization_id, code) DO NOTHING
                RETURNING *
                """,
                (
                    organization_id, normalized_code, values["display_name"], values["description"],
                    values["dues_amount_cents"], values["currency"], values["term_months"],
                    values["grace_days"], values["household_max_members"], Jsonb(values["benefits"]),
                ),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError("MEMBERSHIP_LEVEL_EXISTS")
            level = dict(row)
            self._audit(cur, organization_id=organization_id, actor_subject=actor,
                        action="membership_level.created", entity_type="membership_level",
                        entity_id=normalized_code, before_state=None, after_state=level)
            return level

    def update_membership_level(
        self, *, organization_id: int, code: str, changes: dict[str, Any], actor_subject: str
    ) -> dict[str, Any] | None:
        actor = _actor(actor_subject)
        unknown = set(changes) - _LEVEL_MUTABLE
        if unknown:
            raise ValueError(f"MEMBERSHIP_LEVEL_FIELD_NOT_EDITABLE:{sorted(unknown)[0]}")
        with self._tenant(organization_id) as cur:
            cur.execute(
                "SELECT * FROM oc_constituent.membership_levels WHERE organization_id = %s AND code = %s FOR UPDATE",
                (organization_id, code.strip().lower()),
            )
            before = cur.fetchone()
            if before is None:
                return None
            merged = self._validated_level_values({**{k: before[k] for k in _LEVEL_MUTABLE}, **changes})
            cur.execute(
                """
                UPDATE oc_constituent.membership_levels
                SET display_name = %s, description = %s, dues_amount_cents = %s, currency = %s,
                    term_months = %s, grace_days = %s, household_max_members = %s, benefits = %s,
                    is_active = %s, updated_at = NOW()
                WHERE organization_id = %s AND id = %s
                RETURNING *
                """,
                (
                    merged["display_name"], merged["description"], merged["dues_amount_cents"],
                    merged["currency"], merged["term_months"], merged["grace_days"],
                    merged["household_max_members"], Jsonb(merged["benefits"]),
                    bool(merged["is_active"]), organization_id, before["id"],
                ),
            )
            after = dict(cur.fetchone())
            self._audit(cur, organization_id=organization_id, actor_subject=actor,
                        action="membership_level.updated", entity_type="membership_level",
                        entity_id=after["code"], before_state=dict(before), after_state=after)
            return after

    def list_membership_levels(self, *, organization_id: int, include_inactive: bool = False) -> list[dict[str, Any]]:
        with self._tenant(organization_id) as cur:
            cur.execute(
                """
                SELECT * FROM oc_constituent.membership_levels
                WHERE organization_id = %s AND (is_active OR %s)
                ORDER BY dues_amount_cents, code
                """,
                (organization_id, include_inactive),
            )
            return [dict(row) for row in cur.fetchall()]

    @staticmethod
    def _validated_level_values(values: dict[str, Any]) -> dict[str, Any]:
        out = dict(values)
        out["display_name"] = _clean_text(values.get("display_name"), limit=120, required=True,
                                          code="MEMBERSHIP_LEVEL_NAME_REQUIRED")
        out["description"] = _clean_text(values.get("description"), limit=2000)
        dues = values.get("dues_amount_cents")
        if isinstance(dues, bool) or not isinstance(dues, int) or dues < 0:
            raise ValueError("INVALID_DUES_AMOUNT")
        currency = str(values.get("currency") or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError("INVALID_CURRENCY")
        out["currency"] = currency
        term = values.get("term_months")
        if isinstance(term, bool) or not isinstance(term, int) or not 1 <= term <= 1200:
            raise ValueError("INVALID_MEMBERSHIP_TERM")
        grace = values.get("grace_days")
        if isinstance(grace, bool) or not isinstance(grace, int) or not 0 <= grace <= 366:
            raise ValueError("INVALID_GRACE_DAYS")
        household = values.get("household_max_members")
        if isinstance(household, bool) or not isinstance(household, int) or not 1 <= household <= 20:
            raise ValueError("INVALID_HOUSEHOLD_SIZE")
        benefits = values.get("benefits") or {}
        if not isinstance(benefits, dict):
            raise ValueError("INVALID_LEVEL_BENEFITS")
        entitlements = benefits.get("entitlements", [])
        if not isinstance(entitlements, list):
            raise ValueError("INVALID_LEVEL_BENEFITS")
        out["benefits"] = {
            **benefits,
            "entitlements": sorted({validate_society_entitlement_code(str(code)) for code in entitlements}),
        }
        out["is_active"] = values.get("is_active", True)
        return out

    # -- people and contact points ------------------------------------------------------

    def create_person(
        self,
        *,
        organization_id: int,
        display_name: str,
        first_name: str | None = None,
        last_name: str | None = None,
        actor_subject: str = "system:society-crm",
    ) -> dict[str, Any]:
        actor = _actor(actor_subject)
        name = _clean_text(display_name, limit=200, required=True, code="MEMBER_NAME_REQUIRED")
        with self._tenant(organization_id) as cur:
            cur.execute(
                """
                INSERT INTO oc_constituent.constituents
                    (kind, display_name, first_name, last_name, owner_organization_id)
                VALUES ('person', %s, %s, %s, %s)
                RETURNING *
                """,
                (name, _clean_text(first_name, limit=100), _clean_text(last_name, limit=100), organization_id),
            )
            person = dict(cur.fetchone())
            self._audit(cur, organization_id=organization_id, actor_subject=actor,
                        action="person.created", entity_type="constituent",
                        entity_id=str(person["id"]), before_state=None, after_state=person)
            return person

    def update_person(
        self, *, organization_id: int, constituent_id: int, changes: dict[str, Any], actor_subject: str
    ) -> dict[str, Any] | None:
        actor = _actor(actor_subject)
        unknown = set(changes) - _PERSON_MUTABLE
        if unknown:
            raise ValueError(f"MEMBER_FIELD_NOT_EDITABLE:{sorted(unknown)[0]}")
        with self._tenant(organization_id) as cur:
            cur.execute(
                """
                SELECT * FROM oc_constituent.constituents
                WHERE owner_organization_id = %s AND id = %s
                FOR UPDATE
                """,
                (organization_id, constituent_id),
            )
            before = cur.fetchone()
            if before is None:
                return None
            display_name = _clean_text(changes.get("display_name", before["display_name"]), limit=200,
                                       required=True, code="MEMBER_NAME_REQUIRED")
            first = _clean_text(changes.get("first_name", before["first_name"]), limit=100)
            last = _clean_text(changes.get("last_name", before["last_name"]), limit=100)
            cur.execute(
                """
                UPDATE oc_constituent.constituents
                SET display_name = %s, first_name = %s, last_name = %s, updated_at = NOW()
                WHERE owner_organization_id = %s AND id = %s
                RETURNING *
                """,
                (display_name, first, last, organization_id, constituent_id),
            )
            after = dict(cur.fetchone())
            self._audit(cur, organization_id=organization_id, actor_subject=actor,
                        action="person.updated", entity_type="constituent",
                        entity_id=str(constituent_id), before_state=dict(before), after_state=after)
            return after

    def add_email(
        self,
        *,
        organization_id: int,
        constituent_id: int,
        email: str,
        is_primary: bool = True,
        verification_state: str = "unverified",
        actor_subject: str = "system:society-crm",
    ) -> dict[str, Any]:
        if is_primary:
            return self.set_primary_email(
                organization_id=organization_id,
                constituent_id=constituent_id,
                email=email,
                verification_state=verification_state,
                actor_subject=actor_subject,
            )
        actor = _actor(actor_subject)
        normalized = normalize_email(email)
        verified_at = _now() if verification_state == "verified" else None
        with self._tenant(organization_id) as cur:
            self._require_constituent(cur, organization_id, constituent_id)
            cur.execute(
                """
                INSERT INTO oc_constituent.email_addresses
                    (constituent_id, organization_id, normalized_email, is_primary,
                     verification_state, verified_at)
                VALUES (%s, %s, %s, FALSE, %s, %s)
                ON CONFLICT (constituent_id, organization_id, normalized_email) DO NOTHING
                RETURNING *
                """,
                (constituent_id, organization_id, normalized, verification_state, verified_at),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    """
                    SELECT * FROM oc_constituent.email_addresses
                    WHERE organization_id = %s AND constituent_id = %s AND normalized_email = %s
                    """,
                    (organization_id, constituent_id, normalized),
                )
                return dict(cur.fetchone())
            email_row = dict(row)
            self._audit(cur, organization_id=organization_id, actor_subject=actor,
                        action="email.added", entity_type="constituent",
                        entity_id=str(constituent_id), before_state=None, after_state=email_row)
            return email_row

    def set_primary_email(
        self,
        *,
        organization_id: int,
        constituent_id: int,
        email: str,
        actor_subject: str,
        verification_state: str = "unverified",
    ) -> dict[str, Any]:
        actor = _actor(actor_subject)
        normalized = normalize_email(email)
        verified_at = _now() if verification_state == "verified" else None
        with self._tenant(organization_id) as cur:
            self._require_constituent(cur, organization_id, constituent_id)
            cur.execute(
                """
                SELECT * FROM oc_constituent.email_addresses
                WHERE organization_id = %s AND constituent_id = %s AND is_primary
                FOR UPDATE
                """,
                (organization_id, constituent_id),
            )
            before = cur.fetchone()
            if before is not None and before["normalized_email"] == normalized:
                return dict(before)
            cur.execute(
                """
                UPDATE oc_constituent.email_addresses SET is_primary = FALSE
                WHERE organization_id = %s AND constituent_id = %s AND is_primary
                """,
                (organization_id, constituent_id),
            )
            cur.execute(
                """
                INSERT INTO oc_constituent.email_addresses
                    (constituent_id, organization_id, normalized_email, is_primary,
                     verification_state, verified_at)
                VALUES (%s, %s, %s, TRUE, %s, %s)
                ON CONFLICT (constituent_id, organization_id, normalized_email)
                DO UPDATE SET is_primary = TRUE
                RETURNING *
                """,
                (constituent_id, organization_id, normalized, verification_state, verified_at),
            )
            after = dict(cur.fetchone())
            self._audit(cur, organization_id=organization_id, actor_subject=actor,
                        action="email.primary_changed", entity_type="constituent",
                        entity_id=str(constituent_id),
                        before_state=dict(before) if before else None, after_state=after)
            return after

    def set_primary_phone(
        self, *, organization_id: int, constituent_id: int, phone: str, actor_subject: str, label: str = "mobile"
    ) -> dict[str, Any]:
        actor = _actor(actor_subject)
        normalized = re.sub(r"[^0-9+]", "", phone or "")
        if not re.fullmatch(r"\+?[0-9]{7,15}", normalized):
            raise ValueError("INVALID_PHONE")
        with self._tenant(organization_id) as cur:
            self._require_constituent(cur, organization_id, constituent_id)
            cur.execute(
                """
                SELECT * FROM oc_constituent.phone_numbers
                WHERE organization_id = %s AND constituent_id = %s AND is_primary FOR UPDATE
                """,
                (organization_id, constituent_id),
            )
            before = cur.fetchone()
            cur.execute(
                "UPDATE oc_constituent.phone_numbers SET is_primary = FALSE "
                "WHERE organization_id = %s AND constituent_id = %s AND is_primary",
                (organization_id, constituent_id),
            )
            cur.execute(
                """
                INSERT INTO oc_constituent.phone_numbers
                    (constituent_id, organization_id, normalized_phone, label, is_primary)
                VALUES (%s, %s, %s, %s, TRUE)
                ON CONFLICT (constituent_id, organization_id, normalized_phone)
                DO UPDATE SET is_primary = TRUE, label = EXCLUDED.label
                RETURNING *
                """,
                (constituent_id, organization_id, normalized, _clean_text(label, limit=30) or "mobile"),
            )
            after = dict(cur.fetchone())
            self._audit(cur, organization_id=organization_id, actor_subject=actor,
                        action="phone.primary_changed", entity_type="constituent",
                        entity_id=str(constituent_id),
                        before_state=dict(before) if before else None, after_state=after)
            return after

    def set_mailing_address(
        self,
        *,
        organization_id: int,
        constituent_id: int,
        line1: str,
        country_code: str,
        actor_subject: str,
        line2: str | None = None,
        locality: str | None = None,
        administrative_area: str | None = None,
        postal_code: str | None = None,
    ) -> dict[str, Any]:
        actor = _actor(actor_subject)
        country = (country_code or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", country):
            raise ValueError("INVALID_COUNTRY_CODE")
        first_line = _clean_text(line1, limit=200, required=True, code="ADDRESS_LINE1_REQUIRED")
        with self._tenant(organization_id) as cur:
            self._require_constituent(cur, organization_id, constituent_id)
            cur.execute(
                """
                SELECT * FROM oc_constituent.postal_addresses
                WHERE organization_id = %s AND constituent_id = %s AND address_type = 'mailing'
                  AND is_primary FOR UPDATE
                """,
                (organization_id, constituent_id),
            )
            before = cur.fetchone()
            cur.execute(
                """
                UPDATE oc_constituent.postal_addresses SET is_primary = FALSE, updated_at = NOW()
                WHERE organization_id = %s AND constituent_id = %s AND address_type = 'mailing' AND is_primary
                """,
                (organization_id, constituent_id),
            )
            cur.execute(
                """
                INSERT INTO oc_constituent.postal_addresses
                    (constituent_id, organization_id, address_type, line1, line2, locality,
                     administrative_area, postal_code, country_code, is_primary)
                VALUES (%s, %s, 'mailing', %s, %s, %s, %s, %s, %s, TRUE)
                RETURNING *
                """,
                (
                    constituent_id, organization_id, first_line, _clean_text(line2, limit=200),
                    _clean_text(locality, limit=120), _clean_text(administrative_area, limit=120),
                    _clean_text(postal_code, limit=20), country,
                ),
            )
            after = dict(cur.fetchone())
            self._audit(cur, organization_id=organization_id, actor_subject=actor,
                        action="address.mailing_changed", entity_type="constituent",
                        entity_id=str(constituent_id),
                        before_state=dict(before) if before else None, after_state=after)
            return after

    # -- memberships --------------------------------------------------------------------

    def create_membership(
        self,
        *,
        organization_id: int,
        constituent_id: int,
        level_code: str,
        actor_subject: str,
        status: MembershipStatus = MembershipStatus.PENDING,
        starts_at: datetime | None = None,
        expires_at: datetime | None = None,
        source_kind: str = "manual",
        source_ref: str | None = None,
    ) -> dict[str, Any]:
        actor = _actor(actor_subject)
        normalized_level = level_code.strip().lower()
        if status is MembershipStatus.CANCELLED:
            raise ValueError("MEMBERSHIP_CANNOT_START_CANCELLED")
        if status in (MembershipStatus.ACTIVE, MembershipStatus.GRACE) and expires_at is None:
            raise ValueError("MEMBERSHIP_EXPIRY_REQUIRED")
        with self._tenant(organization_id) as cur:
            self._require_constituent(cur, organization_id, constituent_id)
            level = self._level(cur, organization_id, normalized_level, require_active=True)
            cur.execute(
                """
                INSERT INTO oc_constituent.memberships
                    (organization_id, constituent_id, level_code, status, starts_at, expires_at,
                     source_kind, source_ref, status_changed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (organization_id, constituent_id) DO NOTHING
                RETURNING *
                """,
                (organization_id, constituent_id, normalized_level, status.value, starts_at, expires_at,
                 source_kind, source_ref),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError("MEMBERSHIP_ALREADY_EXISTS")
            membership = dict(row)
            self._sync_entitlements(cur, organization_id, membership, level)
            self._audit(cur, organization_id=organization_id, actor_subject=actor,
                        action="membership.created", entity_type="membership",
                        entity_id=str(membership["id"]), before_state=None, after_state=membership)
            return membership

    _MEMBER_SELECT = """
        SELECT
            m.id AS membership_id,
            m.organization_id,
            m.constituent_id,
            m.level_code,
            l.display_name AS level_name,
            m.status,
            m.starts_at,
            m.expires_at,
            m.last_renewed_at,
            m.cancelled_at,
            m.source_kind,
            c.display_name,
            c.first_name,
            c.last_name,
            e.normalized_email AS primary_email,
            p.normalized_phone AS primary_phone,
            a.line1 AS mailing_line1,
            a.line2 AS mailing_line2,
            a.locality AS mailing_locality,
            a.administrative_area AS mailing_administrative_area,
            a.postal_code AS mailing_postal_code,
            a.country_code AS mailing_country_code
        FROM oc_constituent.memberships m
        JOIN oc_constituent.constituents c
          ON c.id = m.constituent_id AND c.owner_organization_id = m.organization_id
        JOIN oc_constituent.membership_levels l
          ON l.organization_id = m.organization_id AND l.code = m.level_code
        LEFT JOIN oc_constituent.email_addresses e
          ON e.constituent_id = c.id AND e.organization_id = m.organization_id AND e.is_primary
        LEFT JOIN oc_constituent.phone_numbers p
          ON p.constituent_id = c.id AND p.organization_id = m.organization_id AND p.is_primary
        LEFT JOIN oc_constituent.postal_addresses a
          ON a.constituent_id = c.id AND a.organization_id = m.organization_id
         AND a.address_type = 'mailing' AND a.is_primary
    """

    def get_member(self, *, organization_id: int, membership_id: int) -> dict[str, Any] | None:
        with self._tenant(organization_id) as cur:
            cur.execute(self._MEMBER_SELECT + " WHERE m.organization_id = %s AND m.id = %s",
                        (organization_id, membership_id))
            row = cur.fetchone()
            if row is None:
                return None
            member = dict(row)
            cur.execute(
                """
                SELECT h.id, h.constituent_id, h.relationship, h.added_at, c.display_name
                FROM oc_constituent.membership_household_members h
                JOIN oc_constituent.constituents c
                  ON c.id = h.constituent_id AND c.owner_organization_id = h.organization_id
                WHERE h.organization_id = %s AND h.membership_id = %s AND h.status = 'active'
                ORDER BY h.id
                """,
                (organization_id, membership_id),
            )
            member["household_members"] = [dict(item) for item in cur.fetchall()]
            return member

    def get_member_by_constituent(self, *, organization_id: int, constituent_id: int) -> dict[str, Any] | None:
        with self._tenant(organization_id) as cur:
            cur.execute(self._MEMBER_SELECT + " WHERE m.organization_id = %s AND m.constituent_id = %s",
                        (organization_id, constituent_id))
            row = cur.fetchone()
            return dict(row) if row else None

    def list_members(
        self,
        *,
        organization_id: int,
        status: MembershipStatus | None = None,
        level_code: str | None = None,
        search: str | None = None,
        expires_before: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        clauses = ["m.organization_id = %s"]
        params: list[Any] = [organization_id]
        if status is not None:
            clauses.append("m.status = %s")
            params.append(status.value)
        if level_code:
            clauses.append("m.level_code = %s")
            params.append(level_code.strip().lower())
        if expires_before is not None:
            clauses.append("m.expires_at < %s")
            params.append(expires_before)
        if search and search.strip():
            pattern = "%" + search.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            clauses.append(
                "(lower(c.display_name) LIKE %s OR lower(coalesce(c.first_name,'')) LIKE %s "
                "OR lower(coalesce(c.last_name,'')) LIKE %s OR e.normalized_email LIKE %s)"
            )
            params.extend([pattern] * 4)
        where = " WHERE " + " AND ".join(clauses)
        page = max(1, min(int(limit), _MAX_PAGE))
        with self._tenant(organization_id) as cur:
            cur.execute(
                "SELECT count(*) AS n FROM (" + self._MEMBER_SELECT + where + ") AS q", params
            )
            total = int(cur.fetchone()["n"])
            cur.execute(
                self._MEMBER_SELECT + where + " ORDER BY lower(c.display_name), m.id LIMIT %s OFFSET %s",
                [*params, page, max(0, int(offset))],
            )
            return [dict(row) for row in cur.fetchall()], total

    def find_constituents_by_email(self, *, organization_id: int, email: str) -> list[int]:
        normalized = normalize_email(email)
        with self._tenant(organization_id) as cur:
            cur.execute(
                """
                SELECT DISTINCT constituent_id FROM oc_constituent.email_addresses
                WHERE organization_id = %s AND normalized_email = %s
                ORDER BY constituent_id
                """,
                (organization_id, normalized),
            )
            return [int(row["constituent_id"]) for row in cur.fetchall()]

    def update_membership_status(
        self,
        *,
        organization_id: int,
        membership_id: int,
        status: MembershipStatus,
        actor_subject: str,
        reason: str | None = None,
        as_of: datetime | None = None,
    ) -> dict[str, Any] | None:
        actor = _actor(actor_subject)
        now = as_of or _now()
        with self._tenant(organization_id) as cur:
            before = self._lock_membership(cur, organization_id, membership_id)
            if before is None:
                return None
            current = MembershipStatus(before["status"])
            if current is status:
                return dict(before)
            validate_membership_transition(current, status, reason=reason)
            if status is MembershipStatus.ACTIVE and (before["expires_at"] is None or before["expires_at"] <= now):
                # Activation without a paid-through date must go through renewal so the
                # term, the ledger and the audit trail agree.
                raise ValueError("MEMBERSHIP_RENEWAL_REQUIRED")
            after = self._write_status(cur, organization_id, before, status, reason)
            self._audit(cur, organization_id=organization_id, actor_subject=actor,
                        action="membership.status_changed", entity_type="membership",
                        entity_id=str(membership_id), before_state=dict(before), after_state=after,
                        metadata={"reason": _clean_text(reason, limit=500)} if reason else None)
            return after

    def renew_membership(
        self,
        *,
        organization_id: int,
        membership_id: int,
        renewal_key: str,
        source_kind: str,
        actor_subject: str,
        source_ref: str | None = None,
        level_code: str | None = None,
        as_of: datetime | None = None,
        connection: psycopg.Connection | None = None,
    ) -> dict[str, Any]:
        """Apply one renewal exactly once per ``renewal_key``.

        Returns ``{"applied": bool, "renewal": row, "membership": row}``. A retry with the
        same key returns ``applied=False`` and changes nothing. The same key used for a
        different membership is refused, never silently re-applied.
        """
        actor = _actor(actor_subject)
        key = (renewal_key or "").strip()
        if not key or len(key) > 200:
            raise ValueError("RENEWAL_KEY_REQUIRED")
        if source_kind not in _RENEWAL_SOURCES:
            raise ValueError("INVALID_RENEWAL_SOURCE")
        now = as_of or _now()
        with self._tenant(organization_id, connection) as cur:
            before = self._lock_membership(cur, organization_id, membership_id)
            if before is None:
                raise LookupError("MEMBERSHIP_NOT_FOUND")
            cur.execute(
                "SELECT * FROM oc_constituent.membership_renewals WHERE organization_id = %s AND renewal_key = %s",
                (organization_id, key),
            )
            existing = cur.fetchone()
            if existing is not None:
                if existing["membership_id"] != membership_id:
                    raise ValueError("RENEWAL_KEY_CONFLICT")
                return {"applied": False, "renewal": dict(existing), "membership": dict(before)}
            target_level = (level_code or before["level_code"]).strip().lower()
            level = self._level(cur, organization_id, target_level, require_active=True)
            current = MembershipStatus(before["status"])
            new_starts, new_expires = renewal_term(current, before["expires_at"], level["term_months"], now)
            if current is not MembershipStatus.ACTIVE:
                validate_membership_transition(current, MembershipStatus.ACTIVE, reason=f"renewal:{key}")
            cur.execute(
                """
                INSERT INTO oc_constituent.membership_renewals
                    (organization_id, membership_id, renewal_key, level_code, term_months,
                     previous_status, previous_expires_at, new_starts_at, new_expires_at,
                     source_kind, source_ref, actor_subject)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (organization_id, membership_id, key, target_level, level["term_months"], current.value,
                 before["expires_at"], new_starts, new_expires, source_kind, source_ref, actor),
            )
            renewal = dict(cur.fetchone())
            cur.execute(
                """
                UPDATE oc_constituent.memberships
                SET status = 'active',
                    level_code = %s,
                    starts_at = COALESCE(starts_at, %s),
                    expires_at = %s,
                    last_renewed_at = %s,
                    status_changed_at = CASE WHEN status <> 'active' THEN NOW() ELSE status_changed_at END,
                    cancelled_at = NULL,
                    cancellation_reason = NULL,
                    updated_at = NOW()
                WHERE organization_id = %s AND id = %s
                RETURNING *
                """,
                (target_level, new_starts, new_expires, now, organization_id, membership_id),
            )
            after = dict(cur.fetchone())
            self._sync_entitlements(cur, organization_id, after, level)
            self._audit(cur, organization_id=organization_id, actor_subject=actor,
                        action="membership.renewed", entity_type="membership",
                        entity_id=str(membership_id), before_state=dict(before), after_state=after,
                        metadata={"renewal_key": key, "source_kind": source_kind, "renewal_id": renewal["id"]})
            return {"applied": True, "renewal": renewal, "membership": after}

    def change_membership_level(
        self,
        *,
        organization_id: int,
        membership_id: int,
        level_code: str,
        actor_subject: str,
        reason: str | None = None,
    ) -> dict[str, Any] | None:
        actor = _actor(actor_subject)
        target = level_code.strip().lower()
        with self._tenant(organization_id) as cur:
            before = self._lock_membership(cur, organization_id, membership_id)
            if before is None:
                return None
            if before["level_code"] == target:
                return dict(before)
            level = self._level(cur, organization_id, target, require_active=True)
            cur.execute(
                """
                SELECT count(*) AS n FROM oc_constituent.membership_household_members
                WHERE organization_id = %s AND membership_id = %s AND status = 'active'
                """,
                (organization_id, membership_id),
            )
            if int(cur.fetchone()["n"]) + 1 > level["household_max_members"]:
                raise ValueError("HOUSEHOLD_CAPACITY_EXCEEDED")
            cur.execute(
                """
                UPDATE oc_constituent.memberships SET level_code = %s, updated_at = NOW()
                WHERE organization_id = %s AND id = %s RETURNING *
                """,
                (target, organization_id, membership_id),
            )
            after = dict(cur.fetchone())
            self._sync_entitlements(cur, organization_id, after, level)
            self._audit(cur, organization_id=organization_id, actor_subject=actor,
                        action="membership.level_changed", entity_type="membership",
                        entity_id=str(membership_id), before_state=dict(before), after_state=after,
                        metadata={"reason": _clean_text(reason, limit=500)} if reason else None)
            return after

    def apply_lifecycle(
        self, *, organization_id: int, as_of: datetime | None = None,
        actor_subject: str = "system:membership-lifecycle",
    ) -> list[dict[str, Any]]:
        """Move memberships whose dates have passed: active -> grace -> lapsed. Idempotent."""
        actor = _actor(actor_subject)
        now = as_of or _now()
        changes: list[dict[str, Any]] = []
        with self._tenant(organization_id) as cur:
            cur.execute(
                """
                SELECT m.*, l.grace_days
                FROM oc_constituent.memberships m
                JOIN oc_constituent.membership_levels l
                  ON l.organization_id = m.organization_id AND l.code = m.level_code
                WHERE m.organization_id = %s AND m.status IN ('active', 'grace')
                  AND m.expires_at IS NOT NULL AND m.expires_at <= %s
                ORDER BY m.id
                FOR UPDATE OF m
                """,
                (organization_id, now),
            )
            for row in cur.fetchall():
                before = {k: v for k, v in dict(row).items() if k != "grace_days"}
                current = MembershipStatus(before["status"])
                target = lifecycle_status_at(current, before["expires_at"], int(row["grace_days"]), now)
                if target is current:
                    continue
                validate_membership_transition(current, target)
                after = self._write_status(cur, organization_id, before, target, None)
                self._audit(cur, organization_id=organization_id, actor_subject=actor,
                            action="membership.lifecycle_transition", entity_type="membership",
                            entity_id=str(before["id"]), before_state=before, after_state=after,
                            metadata={"as_of": now.isoformat()})
                changes.append({"membership_id": before["id"], "from": current.value, "to": target.value})
        return changes

    def add_household_member(
        self,
        *,
        organization_id: int,
        membership_id: int,
        constituent_id: int,
        actor_subject: str,
        relationship: str = "household",
    ) -> dict[str, Any]:
        actor = _actor(actor_subject)
        with self._tenant(organization_id) as cur:
            membership = self._lock_membership(cur, organization_id, membership_id)
            if membership is None:
                raise LookupError("MEMBERSHIP_NOT_FOUND")
            self._require_constituent(cur, organization_id, constituent_id)
            if membership["constituent_id"] == constituent_id:
                raise ValueError("HOUSEHOLD_MEMBER_IS_PRIMARY")
            level = self._level(cur, organization_id, membership["level_code"], require_active=False)
            cur.execute(
                """
                SELECT count(*) AS n FROM oc_constituent.membership_household_members
                WHERE organization_id = %s AND membership_id = %s AND status = 'active'
                """,
                (organization_id, membership_id),
            )
            if int(cur.fetchone()["n"]) + 1 >= level["household_max_members"]:
                raise ValueError("HOUSEHOLD_CAPACITY_EXCEEDED")
            try:
                cur.execute(
                    """
                    INSERT INTO oc_constituent.membership_household_members
                        (organization_id, membership_id, constituent_id, relationship)
                    VALUES (%s, %s, %s, %s) RETURNING *
                    """,
                    (organization_id, membership_id, constituent_id, relationship),
                )
            except psycopg.errors.UniqueViolation as exc:
                raise ValueError("PERSON_ALREADY_IN_HOUSEHOLD") from exc
            row = dict(cur.fetchone())
            self._audit(cur, organization_id=organization_id, actor_subject=actor,
                        action="household_member.added", entity_type="membership",
                        entity_id=str(membership_id), before_state=None, after_state=row)
            return row

    def remove_household_member(
        self, *, organization_id: int, membership_id: int, constituent_id: int, actor_subject: str
    ) -> dict[str, Any] | None:
        actor = _actor(actor_subject)
        with self._tenant(organization_id) as cur:
            cur.execute(
                """
                UPDATE oc_constituent.membership_household_members
                SET status = 'removed', removed_at = NOW()
                WHERE organization_id = %s AND membership_id = %s AND constituent_id = %s
                  AND status = 'active'
                RETURNING *
                """,
                (organization_id, membership_id, constituent_id),
            )
            row = cur.fetchone()
            if row is None:
                return None
            after = dict(row)
            self._audit(cur, organization_id=organization_id, actor_subject=actor,
                        action="household_member.removed", entity_type="membership",
                        entity_id=str(membership_id), before_state=None, after_state=after)
            return after

    def list_renewals(self, *, organization_id: int, membership_id: int) -> list[dict[str, Any]]:
        with self._tenant(organization_id) as cur:
            cur.execute(
                """
                SELECT * FROM oc_constituent.membership_renewals
                WHERE organization_id = %s AND membership_id = %s ORDER BY id
                """,
                (organization_id, membership_id),
            )
            return [dict(row) for row in cur.fetchall()]

    def list_entitlements(self, *, organization_id: int, constituent_id: int) -> list[dict[str, Any]]:
        with self._tenant(organization_id) as cur:
            cur.execute(
                """
                SELECT * FROM oc_constituent.entitlements
                WHERE organization_id = %s AND constituent_id = %s ORDER BY entitlement_code
                """,
                (organization_id, constituent_id),
            )
            return [dict(row) for row in cur.fetchall()]

    def duplicate_candidates(self, *, organization_id: int) -> list[dict[str, Any]]:
        """People in this organization sharing an email address or an identical name."""
        with self._tenant(organization_id) as cur:
            cur.execute(
                """
                SELECT 'email' AS match_kind, normalized_email AS match_value,
                       array_agg(DISTINCT constituent_id ORDER BY constituent_id) AS constituent_ids
                FROM oc_constituent.email_addresses
                WHERE organization_id = %s
                GROUP BY normalized_email
                HAVING count(DISTINCT constituent_id) > 1
                UNION ALL
                SELECT 'name', lower(display_name), array_agg(id ORDER BY id)
                FROM oc_constituent.constituents
                WHERE owner_organization_id = %s
                GROUP BY lower(display_name)
                HAVING count(*) > 1
                ORDER BY 1, 2
                """,
                (organization_id, organization_id),
            )
            return [dict(row) for row in cur.fetchall()]

    # -- external record links ---------------------------------------------------------

    def get_external_link(
        self, *, organization_id: int, source_system: str, source_record_type: str, source_record_id: str
    ) -> dict[str, Any] | None:
        with self._tenant(organization_id) as cur:
            cur.execute(
                """
                SELECT * FROM oc_constituent.external_record_links
                WHERE organization_id = %s AND source_system = %s AND source_record_type = %s
                  AND source_record_id = %s
                """,
                (organization_id, source_system, source_record_type, source_record_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def link_external_record(
        self,
        *,
        organization_id: int,
        source_system: str,
        source_record_type: str,
        source_record_id: str,
        actor_subject: str,
        constituent_id: int | None = None,
        membership_id: int | None = None,
        source_payload_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Idempotently record where a CRM row came from. A different target is a conflict."""
        actor = _actor(actor_subject)
        with self._tenant(organization_id) as cur:
            cur.execute(
                """
                INSERT INTO oc_constituent.external_record_links
                    (organization_id, constituent_id, membership_id, source_system,
                     source_record_type, source_record_id, source_payload_sha256)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (organization_id, source_system, source_record_type, source_record_id)
                DO NOTHING
                RETURNING *
                """,
                (organization_id, constituent_id, membership_id, source_system, source_record_type,
                 source_record_id, source_payload_sha256),
            )
            row = cur.fetchone()
            if row is not None:
                link = dict(row)
                self._audit(cur, organization_id=organization_id, actor_subject=actor,
                            action="external_link.created", entity_type="external_record_link",
                            entity_id=str(link["id"]), before_state=None, after_state=link)
                return link
            cur.execute(
                """
                SELECT * FROM oc_constituent.external_record_links
                WHERE organization_id = %s AND source_system = %s AND source_record_type = %s
                  AND source_record_id = %s
                """,
                (organization_id, source_system, source_record_type, source_record_id),
            )
            existing = dict(cur.fetchone())
            if (constituent_id is not None and existing["constituent_id"] not in (None, constituent_id)) or (
                membership_id is not None and existing["membership_id"] not in (None, membership_id)
            ):
                raise ValueError("EXTERNAL_LINK_CONFLICT")
            return existing

    # -- member portal invites -----------------------------------------------------------

    def create_portal_invite(
        self, *, organization_id: int, constituent_id: int, code_sha256: str, expires_at: datetime,
        actor_subject: str,
    ) -> dict[str, Any]:
        actor = _actor(actor_subject)
        with self._tenant(organization_id) as cur:
            self._require_constituent(cur, organization_id, constituent_id)
            # One open invite per person: issuing a new one revokes the previous code.
            cur.execute(
                """
                UPDATE oc_constituent.member_portal_invites SET revoked_at = NOW()
                WHERE organization_id = %s AND constituent_id = %s
                  AND redeemed_at IS NULL AND revoked_at IS NULL
                """,
                (organization_id, constituent_id),
            )
            cur.execute(
                """
                INSERT INTO oc_constituent.member_portal_invites
                    (organization_id, constituent_id, code_sha256, created_by_subject, expires_at)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, organization_id, constituent_id, created_by_subject, created_at, expires_at
                """,
                (organization_id, constituent_id, code_sha256, actor, expires_at),
            )
            invite = dict(cur.fetchone())
            self._audit(cur, organization_id=organization_id, actor_subject=actor,
                        action="portal_invite.created", entity_type="constituent",
                        entity_id=str(constituent_id), before_state=None, after_state=invite)
            return invite

    def redeem_portal_invite(
        self, *, organization_id: int, code_sha256: str, auth_subject: str, as_of: datetime | None = None
    ) -> dict[str, Any]:
        """Single-use redemption; any failure is the same INVITE_INVALID_OR_EXPIRED."""
        subject = normalize_auth_subject(auth_subject)
        now = as_of or _now()
        with self.atomic(organization_id):
            with self._tenant(organization_id) as cur:
                cur.execute(
                    """
                    SELECT * FROM oc_constituent.member_portal_invites
                    WHERE organization_id = %s AND code_sha256 = %s
                    FOR UPDATE
                    """,
                    (organization_id, code_sha256),
                )
                invite = cur.fetchone()
                if (
                    invite is None or invite["redeemed_at"] is not None or invite["revoked_at"] is not None
                    or invite["expires_at"] <= now
                ):
                    raise ValueError("INVITE_INVALID_OR_EXPIRED")
                cur.execute(
                    """
                    UPDATE oc_constituent.member_portal_invites
                    SET redeemed_at = %s, redeemed_by_subject = %s
                    WHERE organization_id = %s AND id = %s
                    """,
                    (now, subject, organization_id, invite["id"]),
                )
            binding = self.bind_identity(
                organization_id=organization_id, constituent_id=int(invite["constituent_id"]),
                auth_subject=subject, verification_method="member_invite", actor_subject=subject,
            )
            return binding

    # -- job runs (platform-level) -------------------------------------------------------

    def start_job_run(self, *, job_name: str, organization_id: int | None = None) -> int:
        with self._platform() as cur:
            cur.execute(
                """
                INSERT INTO oc_constituent.crm_job_runs (job_name, organization_id, status)
                VALUES (%s, %s, 'running') RETURNING id
                """,
                (job_name, organization_id),
            )
            return int(cur.fetchone()["id"])

    def finish_job_run(
        self, run_id: int, *, succeeded: bool, summary: dict[str, Any] | None = None, error_code: str | None = None
    ) -> None:
        with self._platform() as cur:
            cur.execute(
                """
                UPDATE oc_constituent.crm_job_runs
                SET status = %s, finished_at = NOW(), summary = %s, error_code = %s
                WHERE id = %s
                """,
                ("succeeded" if succeeded else "failed", Jsonb(_jsonable(summary or {})), error_code, run_id),
            )

    def latest_job_runs(self, *, job_name: str, organization_id: int | None = None, limit: int = 5):
        with self._platform() as cur:
            cur.execute(
                """
                SELECT id, job_name, organization_id, status, started_at, finished_at, summary, error_code
                FROM oc_constituent.crm_job_runs
                WHERE job_name = %s AND (%s::bigint IS NULL OR organization_id = %s OR organization_id IS NULL)
                ORDER BY started_at DESC, id DESC LIMIT %s
                """,
                (job_name, organization_id, organization_id, limit),
            )
            return [dict(row) for row in cur.fetchall()]

    def list_organizations(self) -> list[dict[str, Any]]:
        with self._platform() as cur:
            cur.execute(
                "SELECT id, slug, display_name, kind, status FROM oc_constituent.organizations ORDER BY id"
            )
            return [dict(row) for row in cur.fetchall()]

    # -- audit ---------------------------------------------------------------------------

    def list_audit_events(
        self, *, organization_id: int, entity_type: str | None = None, entity_id: str | None = None,
        limit: int = 200, offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses = ["organization_id = %s"]
        params: list[Any] = [organization_id]
        if entity_type:
            clauses.append("entity_type = %s")
            params.append(entity_type)
        if entity_id:
            clauses.append("entity_id = %s")
            params.append(entity_id)
        with self._tenant(organization_id) as cur:
            cur.execute(
                "SELECT * FROM oc_constituent.crm_audit_events WHERE " + " AND ".join(clauses)
                + " ORDER BY id LIMIT %s OFFSET %s",
                [*params, max(1, min(int(limit), _MAX_PAGE)), max(0, int(offset))],
            )
            return [dict(row) for row in cur.fetchall()]

    def record_audit_event(
        self,
        *,
        organization_id: int,
        actor_subject: str,
        action: str,
        entity_type: str,
        entity_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Audit a non-mutating but sensitive action (e.g. an export)."""
        with self._tenant(organization_id) as cur:
            self._audit(cur, organization_id=organization_id, actor_subject=_actor(actor_subject),
                        action=action, entity_type=entity_type, entity_id=entity_id,
                        before_state=None, after_state=None, metadata=metadata)

    # -- internals -----------------------------------------------------------------------

    @staticmethod
    def _require_constituent(cur, organization_id: int, constituent_id: int) -> None:
        cur.execute(
            "SELECT 1 FROM oc_constituent.constituents WHERE owner_organization_id = %s AND id = %s",
            (organization_id, constituent_id),
        )
        if cur.fetchone() is None:
            raise LookupError("CONSTITUENT_NOT_FOUND")

    @staticmethod
    def _level(cur, organization_id: int, code: str, *, require_active: bool) -> dict[str, Any]:
        cur.execute(
            "SELECT * FROM oc_constituent.membership_levels WHERE organization_id = %s AND code = %s",
            (organization_id, code),
        )
        row = cur.fetchone()
        if row is None or (require_active and not row["is_active"]):
            raise ValueError("UNKNOWN_MEMBERSHIP_LEVEL")
        return dict(row)

    @staticmethod
    def _lock_membership(cur, organization_id: int, membership_id: int) -> dict[str, Any] | None:
        cur.execute(
            "SELECT * FROM oc_constituent.memberships WHERE organization_id = %s AND id = %s FOR UPDATE",
            (organization_id, membership_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def _write_status(
        self, cur, organization_id: int, before: dict[str, Any], status: MembershipStatus, reason: str | None
    ) -> dict[str, Any]:
        cancelled = status is MembershipStatus.CANCELLED
        cur.execute(
            """
            UPDATE oc_constituent.memberships
            SET status = %s,
                status_changed_at = NOW(),
                cancelled_at = CASE WHEN %s THEN NOW() ELSE NULL END,
                cancellation_reason = CASE WHEN %s THEN %s ELSE NULL END,
                updated_at = NOW()
            WHERE organization_id = %s AND id = %s
            RETURNING *
            """,
            (status.value, cancelled, cancelled, _clean_text(reason, limit=500), organization_id, before["id"]),
        )
        after = dict(cur.fetchone())
        level = self._level(cur, organization_id, after["level_code"], require_active=False)
        self._sync_entitlements(cur, organization_id, after, level)
        return after

    @staticmethod
    def _sync_entitlements(cur, organization_id: int, membership: dict[str, Any], level: dict[str, Any]) -> None:
        """Society-gated entitlements follow the membership: granted while active/grace only."""
        status = MembershipStatus(membership["status"])
        codes = {validate_society_entitlement_code(code) for code in (level.get("benefits") or {}).get("entitlements", [])}
        source_ref = str(membership["id"])
        target_state = {
            MembershipStatus.ACTIVE: "active",
            MembershipStatus.GRACE: "active",
            MembershipStatus.PENDING: "pending",
            MembershipStatus.LAPSED: "expired",
            MembershipStatus.CANCELLED: "cancelled",
        }[status]
        cur.execute(
            """
            SELECT id, entitlement_code, status FROM oc_constituent.entitlements
            WHERE organization_id = %s AND constituent_id = %s
              AND source_kind = 'society_membership' AND source_ref = %s
            FOR UPDATE
            """,
            (organization_id, membership["constituent_id"], source_ref),
        )
        existing = {row["entitlement_code"]: row for row in cur.fetchall()}
        for code, row in existing.items():
            desired = target_state if code in codes else "cancelled"
            if row["status"] != desired:
                cur.execute(
                    """
                    UPDATE oc_constituent.entitlements
                    SET status = %s, expires_at = %s, updated_at = NOW()
                    WHERE organization_id = %s AND id = %s
                    """,
                    (desired, membership["expires_at"], organization_id, row["id"]),
                )
            elif desired == "active":
                cur.execute(
                    "UPDATE oc_constituent.entitlements SET expires_at = %s, updated_at = NOW() "
                    "WHERE organization_id = %s AND id = %s",
                    (membership["expires_at"], organization_id, row["id"]),
                )
        if status in (MembershipStatus.ACTIVE, MembershipStatus.GRACE):
            for code in sorted(codes - set(existing)):
                cur.execute(
                    """
                    INSERT INTO oc_constituent.entitlements
                        (constituent_id, organization_id, entitlement_code, status, source_kind,
                         source_ref, starts_at, expires_at)
                    VALUES (%s, %s, %s, 'active', 'society_membership', %s, %s, %s)
                    """,
                    (membership["constituent_id"], organization_id, code, source_ref,
                     membership["starts_at"], membership["expires_at"]),
                )

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
                Jsonb(_jsonable(before_state)) if before_state is not None else None,
                Jsonb(_jsonable(after_state)) if after_state is not None else None,
                Jsonb(_jsonable(metadata or {})),
            ),
        )

    # -- read helpers for import reconciliation and organization export --------------
    #
    # Added for issue #1655 (Neon import / reconciliation / export). Both are
    # read-only and tenant-scoped: they run under ``self._tenant`` (RLS runtime role
    # + transaction-local tenant) and also filter explicitly by the tenant column.

    def list_external_links(
        self, *, organization_id: int, source_system: str | None = None, source_record_type: str | None = None
    ) -> list[dict[str, Any]]:
        clauses = ["organization_id = %s"]
        params: list[Any] = [organization_id]
        if source_system is not None:
            clauses.append("source_system = %s")
            params.append(source_system)
        if source_record_type is not None:
            clauses.append("source_record_type = %s")
            params.append(source_record_type)
        with self._tenant(organization_id) as cur:
            cur.execute(
                "SELECT * FROM oc_constituent.external_record_links WHERE " + " AND ".join(clauses) + " ORDER BY id",
                params,
            )
            return [dict(row) for row in cur.fetchall()]

    # Fixed allowlist: (export key, qualified table, tenant column). Identifiers are
    # never taken from callers.
    TENANT_EXPORT_TABLES: tuple[tuple[str, str, str], ...] = (
        ("organizations", "oc_constituent.organizations", "id"),
        ("membership_levels", "oc_constituent.membership_levels", "organization_id"),
        ("constituents", "oc_constituent.constituents", "owner_organization_id"),
        ("email_addresses", "oc_constituent.email_addresses", "organization_id"),
        ("phone_numbers", "oc_constituent.phone_numbers", "organization_id"),
        ("postal_addresses", "oc_constituent.postal_addresses", "organization_id"),
        ("memberships", "oc_constituent.memberships", "organization_id"),
        ("membership_renewals", "oc_constituent.membership_renewals", "organization_id"),
        ("membership_household_members", "oc_constituent.membership_household_members", "organization_id"),
        ("organization_staff_roles", "oc_constituent.organization_staff_roles", "organization_id"),
        ("organization_identity_bindings", "oc_constituent.organization_identity_bindings", "organization_id"),
        ("entitlements", "oc_constituent.entitlements", "organization_id"),
        ("communication_preferences", "oc_constituent.communication_preferences", "organization_id"),
        ("suppressions", "oc_constituent.suppressions", "organization_id"),
        ("external_record_links", "oc_constituent.external_record_links", "organization_id"),
        ("crm_audit_events", "oc_constituent.crm_audit_events", "organization_id"),
        ("communication_intents", "oc_communications.intents", "organization_id"),
        ("audience_snapshots", "oc_communications.audience_snapshots", "organization_id"),
        ("audience_members", "oc_communications.audience_members", "organization_id"),
        ("approval_events", "oc_communications.approval_events", "organization_id"),
        ("delivery_attempts", "oc_communications.delivery_attempts", "organization_id"),
        ("delivery_events", "oc_communications.delivery_events", "organization_id"),
        ("payments", "oc_constituent.payments", "organization_id"),
        ("payment_events", "oc_constituent.payment_events", "organization_id"),
        ("refunds", "oc_constituent.refunds", "organization_id"),
        ("donations", "oc_constituent.donations", "organization_id"),
        ("provider_webhook_events", "oc_constituent.provider_webhook_events", "organization_id"),
    )

    def snapshot_tenant_tables(self, *, organization_id: int) -> dict[str, list[dict[str, Any]]]:
        """Every row of every tenant-owned CRM table for one organization.

        One REPEATABLE READ transaction under the tenant context, so the tables are a
        mutually consistent snapshot and RLS guarantees no other tenant's rows.
        """
        bound = self._unit.get()
        if bound is not None:
            raise RuntimeError("CRM_SNAPSHOT_NOT_ALLOWED_IN_UNIT")
        conn = self._connect()
        try:
            conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
            out: dict[str, list[dict[str, Any]]] = {}
            with tenant_transaction(organization_id, connect=self._connect, connection=conn) as cur:
                for key, table, column in self.TENANT_EXPORT_TABLES:
                    cur.execute(f"SELECT * FROM {table} WHERE {column} = %s ORDER BY id", (organization_id,))
                    out[key] = [dict(row) for row in cur.fetchall()]
            return out
        finally:
            conn.close()

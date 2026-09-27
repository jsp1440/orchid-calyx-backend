"""Society settings (admin) and the public society profile (anonymous).

Settings are data, validated here, so any society configures its own name, branding
and join page without code changes. The public profile exposes only an explicit
allow-list of fields plus the active membership level catalog (names, dues, terms)
that a join page needs -- never members, staff, money, or audit data.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from psycopg.types.json import Jsonb

from .authorization import SocietyCapability
from .domain import normalize_email
from .postgres_repository import PostgresSocietyCRMRepository
from .society_service import CRMPrincipal, NotFound, SocietyCRMService

PUBLIC_SETTING_KEYS = (
    "tagline", "description", "website_url", "logo_url", "primary_color", "accent_color",
    "public_contact_email", "location_label", "join_enabled", "meeting_schedule",
)
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_URL_FORBIDDEN = re.compile(r"[\s\"'<>\\`]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _plain(value: Any, limit: int, key: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"INVALID_SETTING:{key}")
    cleaned = _CONTROL.sub("", value).strip()
    if len(cleaned) > limit:
        raise ValueError(f"INVALID_SETTING:{key}")
    return cleaned or None


def _https_url(value: Any, key: str) -> str | None:
    text = _plain(value, 500, key)
    if text is None:
        return None
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.netloc or _URL_FORBIDDEN.search(text):
        raise ValueError(f"INVALID_SETTING:{key}")
    return text


def validate_settings(values: dict[str, Any]) -> dict[str, Any]:
    unknown = set(values) - set(PUBLIC_SETTING_KEYS)
    if unknown:
        raise ValueError(f"INVALID_SETTING:{sorted(unknown)[0]}")
    out: dict[str, Any] = {}
    for key, value in values.items():
        if key in ("tagline", "location_label"):
            out[key] = _plain(value, 160, key)
        elif key in ("description", "meeting_schedule"):
            out[key] = _plain(value, 2000, key)
        elif key in ("website_url", "logo_url"):
            out[key] = _https_url(value, key)
        elif key in ("primary_color", "accent_color"):
            if value is not None and (not isinstance(value, str) or not _COLOR.fullmatch(value)):
                raise ValueError(f"INVALID_SETTING:{key}")
            out[key] = value.lower() if value else None
        elif key == "public_contact_email":
            out[key] = normalize_email(value) if value else None
        elif key == "join_enabled":
            if not isinstance(value, bool):
                raise ValueError(f"INVALID_SETTING:{key}")
            out[key] = value
    return out


class SocietyProfileService:
    def __init__(self, repository: PostgresSocietyCRMRepository, crm: SocietyCRMService | None = None) -> None:
        self._repo = repository
        self._crm = crm or SocietyCRMService(repository)

    def get_settings(self, principal: CRMPrincipal, organization_id: int) -> dict[str, Any]:
        self._crm._require(organization_id, principal, SocietyCapability.ROSTER_READ)
        with self._repo._tenant(organization_id) as cur:
            cur.execute("SELECT id, slug, display_name, settings FROM oc_constituent.organizations WHERE id = %s",
                        (organization_id,))
            return dict(cur.fetchone())

    def update_settings(
        self, principal: CRMPrincipal, organization_id: int, *, display_name: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._crm._require(organization_id, principal, SocietyCapability.SETTINGS_WRITE)
        changes = validate_settings(settings or {})
        name = _plain(display_name, 200, "display_name") if display_name is not None else None
        if display_name is not None and not name:
            raise ValueError("ORGANIZATION_NAME_REQUIRED")
        with self._repo._tenant(organization_id) as cur:
            cur.execute(
                "SELECT id, slug, display_name, settings FROM oc_constituent.organizations WHERE id = %s FOR UPDATE",
                (organization_id,),
            )
            before = dict(cur.fetchone())
            merged = {**(before["settings"] or {}), **changes}
            merged = {k: v for k, v in merged.items() if v is not None}
            cur.execute(
                """
                UPDATE oc_constituent.organizations
                SET display_name = %s, settings = %s, updated_at = NOW()
                WHERE id = %s
                RETURNING id, slug, display_name, settings
                """,
                (name or before["display_name"], Jsonb(merged), organization_id),
            )
            after = dict(cur.fetchone())
            self._repo._audit(cur, organization_id=organization_id, actor_subject=principal.subject,
                              action="organization.settings_changed", entity_type="organization",
                              entity_id=str(organization_id), before_state=before, after_state=after)
            return after

    def public_profile(self, slug: str) -> dict[str, Any]:
        """Anonymous, read-only: allow-listed settings and the active level catalog."""
        org = self._repo.get_organization_by_slug(slug)
        if org is None or org["kind"] != "society" or org["status"] != "active":
            raise NotFound("ORGANIZATION_NOT_FOUND")
        with self._repo._tenant(int(org["id"])) as cur:
            cur.execute("SELECT display_name, settings FROM oc_constituent.organizations WHERE id = %s", (org["id"],))
            row = cur.fetchone()
            cur.execute(
                """
                SELECT code, display_name, description, dues_amount_cents, currency, term_months,
                       household_max_members
                FROM oc_constituent.membership_levels
                WHERE organization_id = %s AND is_active
                ORDER BY dues_amount_cents, code
                """,
                (org["id"],),
            )
            levels = [dict(level) for level in cur.fetchall()]
        settings = row["settings"] or {}
        return {
            "slug": org["slug"],
            "display_name": row["display_name"],
            **{key: settings.get(key) for key in PUBLIC_SETTING_KEYS},
            "membership_levels": levels,
        }

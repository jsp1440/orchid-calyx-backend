"""Society CRM administration API: ``/api/society/{org_slug}/...``.

Authentication (who you are):

* verified Supabase member bearer -> ``CRMPrincipal("supabase:<uuid>")``;
* owner session / backend API key -> platform operator principal.

Authorization (what you may do) is entirely ``SocietyCRMService``: roles in the
target organization, resolved fresh per request, default deny. A platform operator
only creates societies and bootstraps admins.

The router is mounted but answers 503 ``SOCIETY_CRM_DISABLED`` until
``OC_SOCIETY_CRM_API_ENABLED`` is true. Enabling it in production is an owner
decision (it requires the CRM migrations to be applied to the production database).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Security
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from app.member_auth import _OWNER_TOKEN_SHAPE, _bearer, verify_member_access_token
from app.security import OWNER_SESSION_COOKIE, api_key_header, verify_owner_or_api_key

from .authorization import SocietyAccessDenied, SocietyRole
from .domain import MembershipStatus
from .crm_diagnostics import organization_diagnostics, platform_diagnostics
from .errors import CONFLICT_CODES, error_body
from .member_portal import MemberPortalService
from .postgres_repository import PostgresSocietyCRMRepository
from .society_service import CRMPrincipal, NotFound, PlatformOperatorRequired, SocietyCRMService

API_ENABLED_ENV = "OC_SOCIETY_CRM_API_ENABLED"


def society_api_enabled() -> bool:
    return (os.getenv(API_ENABLED_ENV) or "").strip().lower() in {"1", "true", "yes", "on"}


def _raise(status: int, code: str) -> None:
    raise HTTPException(status_code=status, detail=error_body(code))


def require_enabled() -> None:
    if not society_api_enabled():
        _raise(503, "SOCIETY_CRM_DISABLED")


def get_society_service() -> SocietyCRMService:
    if not os.environ.get("DATABASE_URL"):
        _raise(503, "CRM_DATABASE_UNAVAILABLE")
    return SocietyCRMService(PostgresSocietyCRMRepository())


async def society_principal(request: Request, api_key: str | None = Security(api_key_header)) -> CRMPrincipal:
    """Authenticate the caller. Authority is decided later, per organization."""
    has_authorization, bearer = _bearer(request)
    owner_path = bool(api_key) or bool(request.cookies.get(OWNER_SESSION_COOKIE)) or bool(
        bearer and _OWNER_TOKEN_SHAPE.fullmatch(bearer)
    )
    if owner_path:
        principal = await verify_owner_or_api_key(request, api_key)
        if principal.get("auth_type") == "api_key":
            return CRMPrincipal("system:backend_api_key", platform_operator=True)
        return CRMPrincipal(f"owner:{principal.get('actor') or 'owner'}", platform_operator=True)
    if bearer:
        member = await run_in_threadpool(verify_member_access_token, bearer)
        return CRMPrincipal(str(member["subject"]))
    if has_authorization:
        raise HTTPException(status_code=401, detail={"code": "UNSUPPORTED_AUTHORIZATION", "message": "Sign in again."})
    raise HTTPException(status_code=401, detail={"code": "SIGN_IN_REQUIRED", "message": "Sign in to manage this society."})


Service = Annotated[SocietyCRMService, Depends(get_society_service)]
Principal = Annotated[CRMPrincipal, Depends(society_principal)]


def _call(fn, *args: Any, **kwargs: Any) -> Any:
    """Run a service call and translate domain failures into actionable HTTP errors."""
    try:
        return fn(*args, **kwargs)
    except (SocietyAccessDenied, PlatformOperatorRequired) as exc:
        raise HTTPException(status_code=403, detail=error_body(exc.code)) from None
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=error_body(str(exc))) from None
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=error_body(str(exc))) from None
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=error_body(str(exc) or "MEMBERSHIP_NOT_FOUND")) from None
    except ValueError as exc:
        code = str(exc).split("\n", 1)[0]
        base = code.split(":", 1)[0]
        raise HTTPException(status_code=409 if base in CONFLICT_CODES else 422, detail=error_body(code)) from None
    except psycopg.errors.UndefinedTable:
        raise HTTPException(status_code=503, detail=error_body("CRM_SCHEMA_NOT_READY")) from None
    except psycopg.errors.UndefinedObject:
        raise HTTPException(status_code=503, detail=error_body("CRM_SCHEMA_NOT_READY")) from None
    except psycopg.OperationalError:
        raise HTTPException(status_code=503, detail=error_body("CRM_DATABASE_UNAVAILABLE")) from None


def organization_id(
    org_slug: Annotated[str, Path(min_length=2, max_length=63, pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")],
    service: Service,
) -> int:
    org = _call(service._repo.get_organization_by_slug, org_slug)
    if org is None:
        _raise(404, "ORGANIZATION_NOT_FOUND")
    return int(org["id"])


OrgId = Annotated[int, Depends(organization_id)]

router = APIRouter(prefix="/api/society/{org_slug}", tags=["society-crm"], dependencies=[Depends(require_enabled)])
platform_router = APIRouter(
    prefix="/api/society-platform", tags=["society-crm-platform"], dependencies=[Depends(require_enabled)]
)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OrganizationIn(_Strict):
    slug: str = Field(..., min_length=2, max_length=63)
    display_name: str = Field(..., min_length=1, max_length=200)


class BootstrapAdminIn(_Strict):
    display_name: str = Field(..., min_length=1, max_length=200)
    auth_subject: str = Field(..., min_length=3, max_length=200)
    email: str | None = Field(None, max_length=320)


class LevelIn(_Strict):
    code: str = Field(..., min_length=1, max_length=40)
    display_name: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(None, max_length=2000)
    dues_amount_cents: int = Field(0, ge=0)
    currency: str = Field("USD", min_length=3, max_length=3)
    term_months: int = Field(12, ge=1, le=1200)
    grace_days: int = Field(30, ge=0, le=366)
    household_max_members: int = Field(1, ge=1, le=20)
    entitlements: list[str] = Field(default_factory=list, max_length=20)


class LevelPatch(_Strict):
    display_name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=2000)
    dues_amount_cents: int | None = Field(None, ge=0)
    currency: str | None = Field(None, min_length=3, max_length=3)
    term_months: int | None = Field(None, ge=1, le=1200)
    grace_days: int | None = Field(None, ge=0, le=366)
    household_max_members: int | None = Field(None, ge=1, le=20)
    is_active: bool | None = None
    entitlements: list[str] | None = Field(None, max_length=20)


class MemberIn(_Strict):
    display_name: str = Field(..., min_length=1, max_length=200)
    first_name: str | None = Field(None, max_length=100)
    last_name: str | None = Field(None, max_length=100)
    email: str | None = Field(None, max_length=320)
    phone: str | None = Field(None, max_length=40)
    level_code: str = Field(..., min_length=1, max_length=40)
    allow_duplicate_email: bool = False


class ProfilePatch(_Strict):
    display_name: str | None = Field(None, min_length=1, max_length=200)
    first_name: str | None = Field(None, max_length=100)
    last_name: str | None = Field(None, max_length=100)


class EmailIn(_Strict):
    email: str = Field(..., max_length=320)


class PhoneIn(_Strict):
    phone: str = Field(..., max_length=40)


class AddressIn(_Strict):
    line1: str = Field(..., min_length=1, max_length=200)
    line2: str | None = Field(None, max_length=200)
    locality: str | None = Field(None, max_length=120)
    administrative_area: str | None = Field(None, max_length=120)
    postal_code: str | None = Field(None, max_length=20)
    country_code: str = Field(..., min_length=2, max_length=2)


class StatusIn(_Strict):
    status: Literal["active", "grace", "lapsed", "cancelled"]
    reason: str | None = Field(None, max_length=500)


class RenewalIn(_Strict):
    renewal_key: str = Field(..., min_length=1, max_length=200)
    level_code: str | None = Field(None, max_length=40)


class LevelChangeIn(_Strict):
    level_code: str = Field(..., min_length=1, max_length=40)
    reason: str | None = Field(None, max_length=500)


class HouseholdMemberIn(_Strict):
    display_name: str = Field(..., min_length=1, max_length=200)
    relationship: Literal["household", "partner", "child", "other"] = "household"
    email: str | None = Field(None, max_length=320)


class RoleIn(_Strict):
    constituent_id: int = Field(..., ge=1)
    role: SocietyRole


class IdentityIn(_Strict):
    constituent_id: int = Field(..., ge=1)
    auth_subject: str = Field(..., min_length=3, max_length=200)


class IdentityRevokeIn(_Strict):
    auth_subject: str = Field(..., min_length=3, max_length=200)


# ---------------------------------------------------------------------------
# Platform operator
# ---------------------------------------------------------------------------


@platform_router.post("/organizations", status_code=201)
def create_organization(payload: OrganizationIn, service: Service, principal: Principal) -> dict[str, Any]:
    return _call(service.create_organization, principal, slug=payload.slug, display_name=payload.display_name)


@platform_router.post("/organizations/{org_slug}/admins", status_code=201)
def bootstrap_admin(payload: BootstrapAdminIn, org: OrgId, service: Service, principal: Principal) -> dict[str, Any]:
    return _call(service.bootstrap_admin, principal, org, display_name=payload.display_name,
                 auth_subject=payload.auth_subject, email=payload.email)


# ---------------------------------------------------------------------------
# Society administration
# ---------------------------------------------------------------------------


@router.get("/me")
def my_access(org: OrgId, service: Service, principal: Principal) -> dict[str, Any]:
    return _call(service.my_access, org, principal)


@router.get("/levels")
def list_levels(org: OrgId, service: Service, principal: Principal,
                include_inactive: bool = False) -> list[dict[str, Any]]:
    return _call(service.list_levels, principal, org, include_inactive=include_inactive)


@router.post("/levels", status_code=201)
def create_level(payload: LevelIn, org: OrgId, service: Service, principal: Principal) -> dict[str, Any]:
    fields = payload.model_dump(exclude={"entitlements"})
    return _call(service.create_level, principal, org, benefits={"entitlements": payload.entitlements}, **fields)


@router.patch("/levels/{code}")
def update_level(code: str, payload: LevelPatch, org: OrgId, service: Service, principal: Principal) -> dict[str, Any]:
    changes = payload.model_dump(exclude_none=True, exclude={"entitlements"})
    if payload.entitlements is not None:
        changes["benefits"] = {"entitlements": payload.entitlements}
    return _call(service.update_level, principal, org, code, changes)


@router.get("/members")
def list_members(
    org: OrgId,
    service: Service,
    principal: Principal,
    status: Annotated[MembershipStatus | None, Query()] = None,
    level: Annotated[str | None, Query(max_length=40)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    rows, total = _call(service.list_members, principal, org, status=status, level_code=level, search=q,
                        limit=limit, offset=offset)
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


@router.post("/members", status_code=201)
def create_member(payload: MemberIn, org: OrgId, service: Service, principal: Principal) -> dict[str, Any]:
    return _call(service.create_member, principal, org, **payload.model_dump())


@router.get("/members/{membership_id}")
def get_member(membership_id: int, org: OrgId, service: Service, principal: Principal) -> dict[str, Any]:
    return _call(service.get_member, principal, org, membership_id)


@router.get("/members/{membership_id}/history")
def member_history(membership_id: int, org: OrgId, service: Service, principal: Principal) -> dict[str, Any]:
    return _call(service.member_history, principal, org, membership_id)


@router.patch("/members/{membership_id}/profile")
def update_profile(membership_id: int, payload: ProfilePatch, org: OrgId, service: Service,
                   principal: Principal) -> dict[str, Any]:
    return _call(service.update_profile, principal, org, membership_id, payload.model_dump(exclude_none=True))


@router.put("/members/{membership_id}/email")
def change_email(membership_id: int, payload: EmailIn, org: OrgId, service: Service,
                 principal: Principal) -> dict[str, Any]:
    return _call(service.change_email, principal, org, membership_id, payload.email)


@router.put("/members/{membership_id}/phone")
def change_phone(membership_id: int, payload: PhoneIn, org: OrgId, service: Service,
                 principal: Principal) -> dict[str, Any]:
    return _call(service.change_phone, principal, org, membership_id, payload.phone)


@router.put("/members/{membership_id}/address")
def change_address(membership_id: int, payload: AddressIn, org: OrgId, service: Service,
                   principal: Principal) -> dict[str, Any]:
    return _call(service.change_address, principal, org, membership_id, **payload.model_dump())


@router.post("/members/{membership_id}/status")
def change_status(membership_id: int, payload: StatusIn, org: OrgId, service: Service,
                  principal: Principal) -> dict[str, Any]:
    return _call(service.change_status, principal, org, membership_id, MembershipStatus(payload.status),
                 reason=payload.reason)


@router.post("/members/{membership_id}/renewals")
def renew(membership_id: int, payload: RenewalIn, org: OrgId, service: Service,
          principal: Principal) -> dict[str, Any]:
    return _call(service.renew, principal, org, membership_id, renewal_key=payload.renewal_key,
                 level_code=payload.level_code)


@router.post("/members/{membership_id}/level")
def change_level(membership_id: int, payload: LevelChangeIn, org: OrgId, service: Service,
                 principal: Principal) -> dict[str, Any]:
    return _call(service.change_level, principal, org, membership_id, payload.level_code, reason=payload.reason)


@router.post("/members/{membership_id}/household", status_code=201)
def add_household_member(membership_id: int, payload: HouseholdMemberIn, org: OrgId, service: Service,
                         principal: Principal) -> dict[str, Any]:
    return _call(service.add_household_member, principal, org, membership_id, **payload.model_dump())


@router.post("/lifecycle/run")
def run_lifecycle(org: OrgId, service: Service, principal: Principal) -> dict[str, Any]:
    return {"changes": _call(service.run_lifecycle, principal, org)}


@router.get("/duplicates")
def duplicates(org: OrgId, service: Service, principal: Principal) -> dict[str, Any]:
    return {"candidates": _call(service.duplicate_candidates, principal, org)}


@router.get("/audit")
def audit(org: OrgId, service: Service, principal: Principal,
          limit: Annotated[int, Query(ge=1, le=500)] = 200,
          offset: Annotated[int, Query(ge=0)] = 0) -> dict[str, Any]:
    return {"items": _call(service.audit_events, principal, org, limit=limit, offset=offset)}


@router.get("/staff")
def list_staff(org: OrgId, service: Service, principal: Principal) -> dict[str, Any]:
    return {"items": _call(service.list_staff, principal, org)}


@router.post("/staff/roles", status_code=201)
def grant_role(payload: RoleIn, org: OrgId, service: Service, principal: Principal) -> dict[str, Any]:
    return _call(service.grant_role, principal, org, constituent_id=payload.constituent_id, role=payload.role)


@router.post("/staff/roles/revoke")
def revoke_role(payload: RoleIn, org: OrgId, service: Service, principal: Principal) -> dict[str, Any]:
    return _call(service.revoke_role, principal, org, constituent_id=payload.constituent_id, role=payload.role)


@router.post("/identities", status_code=201)
def bind_identity(payload: IdentityIn, org: OrgId, service: Service, principal: Principal) -> dict[str, Any]:
    return _call(service.bind_identity, principal, org, constituent_id=payload.constituent_id,
                 auth_subject=payload.auth_subject)


@router.post("/identities/revoke")
def revoke_identity(payload: IdentityRevokeIn, org: OrgId, service: Service, principal: Principal) -> dict[str, Any]:
    return _call(service.revoke_identity, principal, org, auth_subject=payload.auth_subject)


class InviteRedeemIn(_Strict):
    code: str = Field(..., min_length=8, max_length=200)


class InviteIssueIn(_Strict):
    ttl_days: int = Field(30, ge=1, le=90)


def _portal(service: SocietyCRMService) -> MemberPortalService:
    return MemberPortalService(service._repo, service)


@router.post("/members/{membership_id}/portal-invite", status_code=201)
def issue_portal_invite(membership_id: int, payload: InviteIssueIn, org: OrgId, service: Service,
                        principal: Principal) -> dict[str, Any]:
    """One-time code for the member to link their login. Shown once; only its hash is stored."""
    return _call(_portal(service).issue_invite, principal, org, membership_id, ttl_days=payload.ttl_days)


@router.get("/diagnostics")
def society_diagnostics(org: OrgId, service: Service, principal: Principal) -> dict[str, Any]:
    return {"checks": _call(organization_diagnostics, service, principal, org)}


@platform_router.get("/diagnostics")
def platform_status(service: Service, principal: Principal) -> dict[str, Any]:
    return {"checks": _call(platform_diagnostics, service._repo, principal)}


# ---------------------------------------------------------------------------
# Member portal (the signed-in member's own record only)
# ---------------------------------------------------------------------------


@router.post("/portal/link")
def portal_link(payload: InviteRedeemIn, org: OrgId, service: Service, principal: Principal) -> dict[str, Any]:
    return _call(_portal(service).redeem_invite, principal, org, payload.code)


@router.get("/portal/me")
def portal_me(org: OrgId, service: Service, principal: Principal) -> dict[str, Any]:
    return _call(_portal(service).my_membership, principal, org)


@router.patch("/portal/me/profile")
def portal_profile(payload: ProfilePatch, org: OrgId, service: Service, principal: Principal) -> dict[str, Any]:
    return _call(_portal(service).update_my_profile, principal, org, payload.model_dump(exclude_none=True))


@router.put("/portal/me/phone")
def portal_phone(payload: PhoneIn, org: OrgId, service: Service, principal: Principal) -> dict[str, Any]:
    return _call(_portal(service).update_my_phone, principal, org, payload.phone)


@router.put("/portal/me/address")
def portal_address(payload: AddressIn, org: OrgId, service: Service, principal: Principal) -> dict[str, Any]:
    return _call(_portal(service).update_my_address, principal, org, **payload.model_dump())


def iter_routers() -> Iterator[APIRouter]:
    from .payment_routes import router as payment_webhook_router  # these import this module; keep lazy
    from .society_data_routes import router as data_router

    yield platform_router
    yield payment_webhook_router
    yield router
    yield data_router

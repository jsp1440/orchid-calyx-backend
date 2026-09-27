"""Society CRM data movement and communications API.

Same authentication, tenant resolution, feature flag and error translation as
``society_routes``. Import/reconcile take CSV text plus an explicit column mapping
in the JSON body; dry run is the default. Exports are audited by the services.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from .crm_export import export_organization, export_roster_csv
from .crm_import import ColumnMapping, import_members
from .crm_reconcile import reconcile
from .domain import MembershipStatus, MessagePurpose, PreferenceState
from .society_communications import SocietyCommunicationsService
from .society_routes import OrgId, Principal, Service, _call, require_enabled

router = APIRouter(prefix="/api/society/{org_slug}", tags=["society-crm-data"], dependencies=[Depends(require_enabled)])

MAX_CSV_BYTES = 5_000_000


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MappingIn(_Strict):
    columns: dict[str, str] = Field(..., max_length=60)
    level_value_map: dict[str, str] | None = None
    status_value_map: dict[str, str] | None = None
    country_value_map: dict[str, str] | None = None
    date_formats: list[str] = Field(default_factory=lambda: ["%Y-%m-%d"], max_length=10)

    def to_mapping(self) -> ColumnMapping:
        return ColumnMapping(
            columns=self.columns,
            level_value_map=self.level_value_map,
            status_value_map=self.status_value_map,
            country_value_map=self.country_value_map,
            date_formats=tuple(self.date_formats),
        )


class ImportIn(_Strict):
    csv_text: str = Field(..., max_length=MAX_CSV_BYTES)
    mapping: MappingIn
    dry_run: bool = True
    source_system: str = Field("neon", max_length=40)
    import_id: str | None = Field(None, max_length=100)


class ReconcileIn(_Strict):
    csv_text: str = Field(..., max_length=MAX_CSV_BYTES)
    mapping: MappingIn
    source_system: str = Field("neon", max_length=40)


class IntentIn(_Strict):
    purpose: MessagePurpose
    subject: str = Field(..., min_length=1, max_length=300)
    template_ref: str | None = Field(None, max_length=120)
    content_sha256: str | None = Field(None, pattern=r"^[0-9a-f]{64}$")
    statuses: list[MembershipStatus] | None = None
    level_codes: list[str] | None = Field(None, max_length=20)


class ApproveIn(_Strict):
    audience_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    rationale: str | None = Field(None, max_length=500)


class PreferenceIn(_Strict):
    constituent_id: int = Field(..., ge=1)
    purpose: MessagePurpose
    state: Literal["subscribed", "unsubscribed"]
    source_kind: str = Field(..., min_length=2, max_length=60)
    evidence_ref: str | None = Field(None, max_length=200)


class MyPreferenceIn(_Strict):
    purpose: MessagePurpose
    subscribed: bool


def _comms(service) -> SocietyCommunicationsService:
    return SocietyCommunicationsService(service._repo, service)


# -- import / reconcile / export ----------------------------------------------------------


@router.post("/imports")
def run_import(payload: ImportIn, org: OrgId, service: Service, principal: Principal) -> dict[str, Any]:
    report = _call(import_members, service, principal, org, payload.csv_text, payload.mapping.to_mapping(),
                   dry_run=payload.dry_run, source_system=payload.source_system, import_id=payload.import_id)
    return report.to_dict()


@router.post("/reconciliation")
def run_reconciliation(payload: ReconcileIn, org: OrgId, service: Service, principal: Principal) -> dict[str, Any]:
    report = _call(reconcile, service, principal, org, payload.csv_text, payload.mapping.to_mapping(),
                   source_system=payload.source_system)
    return report.to_dict()


@router.get("/exports/roster.csv")
def roster_csv(org: OrgId, service: Service, principal: Principal,
               status: Annotated[MembershipStatus | None, Query()] = None) -> Response:
    body = _call(export_roster_csv, service, principal, org, status=status)
    return Response(content=body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="roster.csv"', "Cache-Control": "no-store"})


@router.get("/exports/organization")
def organization_export(org: OrgId, service: Service, principal: Principal) -> Response:
    import json

    document = _call(export_organization, service, principal, org)
    return Response(content=json.dumps(document, default=str), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="organization-export.json"',
                             "Cache-Control": "no-store"})


# -- communications -----------------------------------------------------------------------


@router.post("/communications", status_code=201)
def create_intent(payload: IntentIn, org: OrgId, service: Service, principal: Principal) -> dict[str, Any]:
    return _call(_comms(service).create_intent, principal, org, **payload.model_dump())


@router.post("/communications/{intent_id}/freeze")
def freeze(intent_id: int, org: OrgId, service: Service, principal: Principal) -> dict[str, Any]:
    return _call(_comms(service).freeze_audience, principal, org, intent_id)


@router.post("/communications/{intent_id}/approve")
def approve(intent_id: int, payload: ApproveIn, org: OrgId, service: Service, principal: Principal) -> dict[str, Any]:
    return _call(_comms(service).approve, principal, org, intent_id, audience_sha256=payload.audience_sha256,
                 rationale=payload.rationale)


@router.get("/communications/{intent_id}/delivery")
def delivery(intent_id: int, org: OrgId, service: Service, principal: Principal) -> dict[str, Any]:
    return _call(_comms(service).delivery_status, principal, org, intent_id)


@router.post("/preferences", status_code=201)
def record_preference(payload: PreferenceIn, org: OrgId, service: Service, principal: Principal) -> dict[str, Any]:
    return _call(_comms(service).set_preference, principal, org, constituent_id=payload.constituent_id,
                 purpose=payload.purpose, state=PreferenceState(payload.state), source_kind=payload.source_kind,
                 evidence_ref=payload.evidence_ref)


@router.get("/portal/me/preferences")
def my_preferences(org: OrgId, service: Service, principal: Principal) -> dict[str, Any]:
    return _call(_comms(service).my_preferences, principal, org)


@router.put("/portal/me/preferences")
def set_my_preference(payload: MyPreferenceIn, org: OrgId, service: Service, principal: Principal) -> dict[str, Any]:
    return _call(_comms(service).set_my_preference, principal, org, purpose=payload.purpose,
                 subscribed=payload.subscribed)

"""Judge-device routes, authenticated by a per-judge bearer credential.

Nothing here accepts or needs the owner key. The judge is taken from the
verified credential (``app/judge_auth.py``), never from ``X-Judge-Id`` or a
request body, and every response is shaped by the blind projection there.
Anything outside the judge's assigned events and categories is 404, another
judge's scorecard is 404 (its existence is not confirmed), and every action,
refused or not, is written to the append-only judge audit.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import get_db
from app.judge_auth import (
    AuditRef,
    JudgeContext,
    authenticate_judge_token,
    bearer_judge_token,
    blind_safe_text,
    credential_scope,
    judge_action,
    judge_event_view,
    judge_plant_view,
    judge_scope,
    judge_scorecard_view,
    plant_in_scope,
    require_judge_secret,
    scorecard_handle,
    write_judge_audit,
)
from app.models import (
    JudgeCredential,
    JudgingAward,
    JudgingCriterion,
    JudgingEvent,
    Plant,
    PlantCategory,
    Scorecard,
)
from app.rate_limit import client_key
from app.routers.judging import apply_scorecard_autosave, apply_scorecard_submit
from app.routers.show_day import is_legacy_qr_token
from app.schemas import ScorecardSaveRequest, ScorecardSubmitRequest

DbSession = Annotated[Session, Depends(get_db)]


def require_judge_context(request: Request, db: DbSession) -> JudgeContext:
    require_judge_secret()
    token = bearer_judge_token(request.headers.get("authorization"))
    if token is None:
        raise HTTPException(
            status_code=401,
            detail="A judge credential (Authorization: Bearer ocj_...) is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    ctx = authenticate_judge_token(db, token, client_key(request))
    request.state.judge_context = ctx
    return ctx


Judge = Annotated[JudgeContext, Depends(require_judge_context)]


def _audit_rejected_request(request: Request, action: str) -> None:
    """Audit a request FastAPI rejected before the route ran (422).

    Only for a caller whose judge credential verifies: the context the
    dependency stored, or, when the body was unreadable and dependencies never
    ran, the bearer token verified here. The rejected input is never recorded.
    """
    provider = request.app.dependency_overrides.get(get_db, get_db)
    sessions = provider()
    db = next(sessions)
    try:
        ctx = getattr(request.state, "judge_context", None)
        if ctx is None:
            token = bearer_judge_token(request.headers.get("authorization"))
            if token is None:
                return
            try:
                ctx = authenticate_judge_token(db, token, client_key(request))
            except HTTPException:
                return
        write_judge_audit(
            db,
            ctx,
            action=action,
            outcome="invalid",
            http_status=422,
            ref=AuditRef(),
            detail="request validation failed",
        )
    finally:
        sessions.close()


class JudgeAuditedRoute(APIRoute):
    """Also audits requests refused by request validation (422)."""

    def get_route_handler(self):
        handler = super().get_route_handler()
        action = self.name.removeprefix("judge_")

        async def audited(request: Request):
            try:
                return await handler(request)
            except RequestValidationError:
                await run_in_threadpool(_audit_rejected_request, request, action)
                raise

        return audited


router = APIRouter(
    prefix="/api/judge-portal", tags=["Judge Portal"], route_class=JudgeAuditedRoute
)


def _validated(model: type[BaseModel], body: Any) -> BaseModel:
    """Validate a judge's body inside the audited action, so a 422 is recorded."""
    try:
        return model.model_validate(body if body is not None else {})
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=exc.errors(
                include_url=False, include_input=False, include_context=False
            ),
        ) from None


_NOT_FOUND = "Not found in your judging assignments"


def _event_in_scope(
    db: Session, scope: dict[str, set[str]], event_id: str
) -> JudgingEvent:
    event = db.get(JudgingEvent, event_id) if event_id in scope else None
    if event is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return event


def _own_scorecards(db: Session, ctx: JudgeContext, scope: dict[str, set[str]]):
    """(scorecard, event, plant) for this judge's in-scope cards, ordered by handle."""
    if not scope:
        return []
    cards = (
        db.execute(
            select(Scorecard).where(
                Scorecard.judge_id == ctx.judge_id,
                Scorecard.judging_event_id.in_(list(scope)),
            )
        )
        .scalars()
        .all()
    )
    rows = []
    for card in cards:
        plant = db.get(Plant, card.plant_id)
        if (
            plant is None
            or plant.judging_event_id != card.judging_event_id
            or not plant_in_scope(scope, plant)
        ):
            continue
        rows.append((card, db.get(JudgingEvent, card.judging_event_id), plant))
    return sorted(
        rows,
        key=lambda row: scorecard_handle(ctx.secret, ctx.judge_id, row[1], row[0].id),
    )


def _resolve_scorecard(db: Session, ctx: JudgeContext, handle: str):
    scope = judge_scope(db, ctx)
    for card, event, plant in _own_scorecards(db, ctx, scope):
        if scorecard_handle(ctx.secret, ctx.judge_id, event, card.id) == handle:
            return card, event, plant
    raise HTTPException(status_code=404, detail=_NOT_FOUND)


@router.get("/me")
def judge_me(ctx: Judge, db: DbSession):
    with judge_action(db, ctx, "me"):
        credential = db.get(JudgeCredential, ctx.credential_id)
        return {
            "judge_id": ctx.judge_id,
            "judge_name": ctx.judge_name,
            "show_id": ctx.show_id,
            "credential_id": ctx.credential_id,
            "expires_at": ctx.expires_at.isoformat(),
            "scope": credential_scope(credential),
        }


@router.get("/events")
def judge_events(ctx: Judge, db: DbSession):
    with judge_action(db, ctx, "list_events"):
        scope = judge_scope(db, ctx)
        events = [db.get(JudgingEvent, event_id) for event_id in scope]
        return [
            judge_event_view(e)
            for e in sorted(events, key=lambda e: ((e.name or ""), e.id))
        ]


@router.get("/events/{event_id}/categories")
def judge_event_categories(event_id: str, ctx: Judge, db: DbSession):
    with judge_action(db, ctx, "list_categories", judging_event_id=event_id):
        scope = judge_scope(db, ctx)
        event = _event_in_scope(db, scope, event_id)
        categories = [
            db.get(PlantCategory, category_id) for category_id in scope[event_id]
        ]
        categories.sort(key=lambda c: (c.sort_order or 0, c.name, c.id))
        return [
            {
                "id": c.id,
                "name": c.name,
                # Class text is schedule-level, not per plant; in a blind
                # event it is still withheld if it mentions an exhibitor.
                "description": blind_safe_text(db, event, c.description),
                "sort_order": c.sort_order,
            }
            for c in categories
        ]


@router.get("/events/{event_id}/plants")
def judge_event_plants(
    event_id: str,
    ctx: Judge,
    db: DbSession,
    category_id: Annotated[str | None, Query()] = None,
):
    with judge_action(
        db, ctx, "list_plants", judging_event_id=event_id, category_id=category_id
    ):
        scope = judge_scope(db, ctx)
        event = _event_in_scope(db, scope, event_id)
        if category_id is not None and category_id not in scope[event_id]:
            raise HTTPException(status_code=404, detail=_NOT_FOUND)
        plants = (
            db.execute(select(Plant).where(Plant.judging_event_id == event_id))
            .scalars()
            .all()
        )
        own = {plant.id: card for card, _, plant in _own_scorecards(db, ctx, scope)}
        views = []
        for plant in plants:
            if not plant_in_scope(scope, plant) or (
                category_id and plant.category_id != category_id
            ):
                continue
            view = judge_plant_view(db, ctx, event, plant)
            card = own.get(plant.id)
            view["scorecard_handle"] = (
                scorecard_handle(ctx.secret, ctx.judge_id, event, card.id)
                if card
                else None
            )
            views.append(view)
        return sorted(views, key=lambda v: v["plant_handle"])


@router.get("/events/{event_id}/scorecards")
def judge_event_scorecards(event_id: str, ctx: Judge, db: DbSession):
    with judge_action(db, ctx, "list_scorecards", judging_event_id=event_id):
        scope = judge_scope(db, ctx)
        _event_in_scope(db, scope, event_id)
        return [
            judge_scorecard_view(db, ctx, card, event, plant)
            for card, event, plant in _own_scorecards(db, ctx, scope)
            if card.judging_event_id == event_id
        ]


@router.get("/scorecards/{handle}")
def judge_get_scorecard(handle: str, ctx: Judge, db: DbSession):
    with judge_action(db, ctx, "get_scorecard") as ref:
        card, event, plant = _resolve_scorecard(db, ctx, handle)
        ref.plant(ctx, event, plant)
        ref.scorecard_id = card.id
        return judge_scorecard_view(db, ctx, card, event, plant, include_scores=True)


@router.put("/scorecards/{handle}")
def judge_autosave_scorecard(
    handle: str, ctx: Judge, db: DbSession, body: Annotated[Any, Body()] = None
):
    with judge_action(db, ctx, "autosave_scorecard") as ref:
        card, event, plant = _resolve_scorecard(db, ctx, handle)
        ref.plant(ctx, event, plant)
        ref.scorecard_id = card.id
        data = _validated(ScorecardSaveRequest, body)
        card = apply_scorecard_autosave(db, card, ctx.judge_id, data)
        return judge_scorecard_view(db, ctx, card, event, plant, include_scores=True)


@router.post("/scorecards/{handle}/submit")
def judge_submit_scorecard(
    handle: str, ctx: Judge, db: DbSession, body: Annotated[Any, Body()] = None
):
    with judge_action(db, ctx, "submit_scorecard") as ref:
        card, event, plant = _resolve_scorecard(db, ctx, handle)
        ref.plant(ctx, event, plant)
        ref.scorecard_id = card.id
        data = _validated(ScorecardSubmitRequest, body)
        card = apply_scorecard_submit(db, card, ctx.judge_id, data)
        return judge_scorecard_view(db, ctx, card, event, plant, include_scores=True)


@router.get("/scan/{qr_token}")
def judge_scan(qr_token: str, ctx: Judge, db: DbSession):
    """Resolve a scanned tag to the judge's view of that plant and their own card.

    A tag outside the judge's assignments is 404, like an unknown tag. In a
    blind event a tag still carrying an id-derived (legacy) token is refused
    with 409 until the owner re-issues the event's tags.
    """
    with judge_action(db, ctx, "scan") as ref:
        scope = judge_scope(db, ctx)
        plant = (
            db.execute(select(Plant).where(Plant.qr_code == qr_token)).scalars().first()
        )
        if plant is None or not plant_in_scope(scope, plant):
            raise HTTPException(status_code=404, detail=_NOT_FOUND)
        event = db.get(JudgingEvent, plant.judging_event_id)
        ref.plant(ctx, event, plant)
        if event.is_blind and is_legacy_qr_token(plant):
            raise HTTPException(
                status_code=409,
                detail="This tag uses a retired id-derived token. Ask the show owner to re-issue tags.",
            )
        card = next(
            (c for c, _, p in _own_scorecards(db, ctx, scope) if p.id == plant.id), None
        )
        if card is not None:
            ref.scorecard_id = card.id
        return {
            "plant": judge_plant_view(db, ctx, event, plant),
            "judging_event": judge_event_view(event),
            "scorecard": judge_scorecard_view(db, ctx, card, event, plant)
            if card
            else None,
        }


@router.get("/criteria")
def judge_criteria(ctx: Judge, db: DbSession):
    """Scoring criteria (award rubrics); no show or exhibitor data."""
    with judge_action(db, ctx, "list_criteria"):
        awards = (
            db.execute(select(JudgingAward).order_by(JudgingAward.award_id))
            .scalars()
            .all()
        )
        out = []
        for award in awards:
            criteria = (
                db.execute(
                    select(JudgingCriterion)
                    .where(JudgingCriterion.award_id == award.award_id)
                    .order_by(
                        JudgingCriterion.criteria_name, JudgingCriterion.criteria_id
                    )
                )
                .scalars()
                .all()
            )
            out.append(
                {
                    "award_id": award.award_id,
                    "award_name": award.award_name,
                    "criteria": [
                        {
                            "criteria_id": c.criteria_id,
                            "criteria_name": c.criteria_name,
                            "criteria_description": c.criteria_description,
                            "points_min": c.points_min,
                            "points_max": c.points_max,
                            "weighting": c.weighting,
                            "scoring_type": c.scoring_type,
                            "choices_json": c.choices_json,
                        }
                        for c in criteria
                    ],
                }
            )
        return out

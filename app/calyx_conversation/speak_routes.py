from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.brain_mission.routes import SERVICE as BRAIN_MISSION_SERVICE
from app.security import verify_owner_or_api_key

from .provider import DeterministicGovernedReplyProvider, configured_reply_provider
from .routes import STORE, _retrieval

AuthDependency = Annotated[dict[str, Any], Depends(verify_owner_or_api_key)]
router = APIRouter(prefix="/calyx/speak", tags=["calyx-speak"])


class ConversationCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    project_id: str | None = Field(default=None, max_length=200)
    context: dict[str, Any] = Field(default_factory=dict)


class ConversationTurnRequest(BaseModel):
    message: str = Field(min_length=1, max_length=5000)
    project_id: str | None = Field(default=None, max_length=200)
    context: dict[str, Any] = Field(default_factory=dict)
    research_mode: Literal["auto", "always", "never"] = "auto"
    retrieval_limit: int = Field(default=8, ge=1, le=25)


def _subject(auth: dict[str, Any]) -> str:
    subject = str(auth.get("subject") or auth.get("actor") or "").strip()
    if not subject:
        raise HTTPException(401, detail={"code": "AUTHENTICATED_SUBJECT_REQUIRED"})
    return subject


def _is_casual(message: str) -> bool:
    normalized = " ".join(message.casefold().split()).strip(" .!?,")
    if len(normalized) > 120:
        return False
    casual = {
        "hi",
        "hello",
        "hey",
        "good morning",
        "good afternoon",
        "good evening",
        "thanks",
        "thank you",
        "hello calyx",
        "hi calyx",
        "hey calyx",
    }
    if normalized in casual:
        return True
    if re.match(r"^(hello|hi|hey)\s+calyx(?:[.!?,;:]|\s|$)", normalized):
        capability_phrases = {
            "what are you able to help me with",
            "what can you help me with",
            "what can you do",
            "how can you help",
        }
        remainder = re.sub(
            r"^(hello|hi|hey)\s+calyx(?:[.!?,;:]|\s)*",
            "",
            normalized,
            count=1,
        ).strip(" .!?,;:")
        return not remainder or remainder in capability_phrases
    return False


def _mission_question(history: str, message: str) -> str:
    if not history:
        return message[:1000]
    text = (
        "Use this conversation context only to resolve references; do not treat prior assistant text as scientific evidence.\n"
        + history[-650:]
        + "\nCurrent question: "
        + message
    )
    return text[-1000:]


def _safe_retrieval(message: str, retrieval_limit: int) -> dict[str, Any]:
    try:
        result = _retrieval(message, "HYBRID", retrieval_limit, True)
        result.setdefault("status", "available")
        return result
    except (ValueError, TypeError, RuntimeError) as exc:
        return {
            "results": [],
            "total_eligible_results": 0,
            "retrieval_mode": "HYBRID",
            "status": "unavailable",
            "error": str(exc),
        }


def _run_governed_turn(
    *,
    owner: str,
    conversation_id: str,
    project_id: str,
    message: str,
    research_mode: str,
    retrieval_limit: int,
) -> tuple[dict[str, Any], dict[str, Any] | None, str | None, bool]:
    casual = _is_casual(message) and research_mode != "always"
    if casual:
        return {
            "results": [],
            "total_eligible_results": 0,
            "retrieval_mode": "HYBRID",
            "status": "not_requested",
        }, None, None, True

    retrieval = _safe_retrieval(message, retrieval_limit)
    mission: dict[str, Any] | None = None
    mission_error: str | None = None
    should_run_mission = research_mode == "always" or (
        research_mode == "auto" and len(message.split()) >= 5
    )
    if should_run_mission:
        history = STORE.history_text(
            conversation_id,
            owner=owner,
            turns=6,
            max_chars=1800,
        )
        try:
            mission = BRAIN_MISSION_SERVICE.start(
                question=_mission_question(history, message),
                tenant_id=owner,
                project_id=project_id,
                actor=owner,
                max_sources=20,
                max_steps=10,
                timeout_seconds=30,
            )
        except (ValueError, RuntimeError) as exc:
            mission_error = str(exc)
    return retrieval, mission, mission_error, False


@router.get("/status")
def speak_status(auth: AuthDependency) -> dict[str, Any]:
    _subject(auth)
    return {
        "release": "CALYX-SPEAK-003",
        "conversation_persistence": STORE.persistence_mode,
        "semantic_retrieval_degraded_mode": True,
        "automatic_publication": False,
        "knowledge_graph_mutation": False,
    }


@router.post("/conversations", status_code=201)
def create_conversation(
    payload: ConversationCreateRequest,
    auth: AuthDependency,
) -> dict[str, Any]:
    owner = _subject(auth)
    conversation_id = STORE.create_or_touch(
        None,
        owner=owner,
        project_id=payload.project_id,
        title=payload.title,
        context=payload.context,
    )
    conversation = STORE.get(conversation_id, owner=owner)
    if conversation is None:
        raise HTTPException(500, detail={"code": "CONVERSATION_CREATE_FAILED"})
    conversation["persistence_mode"] = STORE.persistence_mode
    return conversation


@router.get("/conversations")
def list_conversations(
    auth: AuthDependency,
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    owner = _subject(auth)
    resolved_limit = limit if isinstance(limit, int) else 20
    return {
        "conversations": STORE.recent(owner=owner, limit=resolved_limit),
        "persistence_mode": STORE.persistence_mode,
    }


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    auth: AuthDependency,
    message_limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    owner = _subject(auth)
    resolved_limit = message_limit if isinstance(message_limit, int) else 100
    try:
        conversation = STORE.get(
            conversation_id,
            owner=owner,
            message_limit=resolved_limit,
        )
    except Exception as exc:
        raise HTTPException(
            422,
            detail={"code": "INVALID_CONVERSATION_IDENTIFIER"},
        ) from exc
    if conversation is None:
        raise HTTPException(404, detail={"code": "CONVERSATION_NOT_FOUND"})
    conversation["persistence_mode"] = STORE.persistence_mode
    return conversation


@router.post("/conversations/{conversation_id}/turns")
def append_turn(
    conversation_id: str,
    payload: ConversationTurnRequest,
    auth: AuthDependency,
) -> dict[str, Any]:
    owner = _subject(auth)
    existing = STORE.get(conversation_id, owner=owner)
    if existing is None:
        raise HTTPException(404, detail={"code": "CONVERSATION_NOT_FOUND"})
    project_id = (
        payload.project_id
        or str(existing.get("project_id") or "").strip()
        or f"calyx-speak:{conversation_id}"
    )
    STORE.create_or_touch(
        conversation_id,
        owner=owner,
        project_id=project_id,
        title=None,
        context=payload.context,
    )
    operator_message = STORE.append(
        conversation_id,
        "operator",
        payload.message,
        {"context": payload.context, "research_mode": payload.research_mode},
        owner=owner,
    )

    retrieval, mission, mission_error, casual = _run_governed_turn(
        owner=owner,
        conversation_id=conversation_id,
        project_id=project_id,
        message=payload.message,
        research_mode=payload.research_mode,
        retrieval_limit=payload.retrieval_limit,
    )

    if mission is not None:
        STORE.append(
            conversation_id,
            "tool",
            f"Governed Brain mission {mission.get('mission_id', 'unknown')} completed for this turn.",
            {
                "tool": "brain_mission",
                "mission_id": mission.get("mission_id"),
                "state": mission.get("state"),
                "review_status": mission.get("review_status"),
                "publication_eligibility": mission.get("publication_eligibility"),
            },
            owner=owner,
        )

    governed_context = {
        "casual": casual,
        "conversation_id": conversation_id,
        "project_id": project_id,
        "retrieval": retrieval,
        "mission": mission,
        "mission_error": mission_error,
        "epistemic_policy": {
            "continuum_first": True,
            "provider_memory_is_evidence": False,
            "conversation_does_not_publish_knowledge": True,
            "candidate_knowledge_auto_promotion": False,
            "knowledge_graph_mutation": False,
        },
    }
    messages = STORE.provider_messages(conversation_id, owner=owner, turns=8)
    provider = configured_reply_provider()
    provider_error: str | None = None
    try:
        reply = provider.generate(
            messages=messages,
            governed_context=governed_context,
        )
    except Exception as exc:  # noqa: BLE001
        provider_error = str(exc)
        fallback = DeterministicGovernedReplyProvider()
        reply = fallback.generate(
            messages=messages,
            governed_context=governed_context,
        )

    calyx_message = STORE.append(
        conversation_id,
        "calyx",
        reply.text,
        {
            "provider": reply.provider,
            "model": reply.model,
            "provider_response_id": reply.provider_response_id,
            "request_hash": reply.request_hash,
            "provider_error": provider_error,
            "mission_id": mission.get("mission_id") if mission else None,
            "mission_state": mission.get("state") if mission else None,
            "review_status": mission.get("review_status") if mission else None,
            "retrieval_eligible_results": retrieval.get("total_eligible_results"),
            "retrieval_status": retrieval.get("status"),
            "retrieval_error": retrieval.get("error"),
            "research_mode": payload.research_mode,
            "publication_boundary": (
                "human-review-governed; no automatic publication or graph mutation"
            ),
        },
        owner=owner,
    )
    return {
        "conversation_id": conversation_id,
        "operator_message": operator_message,
        "calyx_message": calyx_message,
        "answer": reply.text,
        "provider": {
            "name": reply.provider,
            "model": reply.model,
            "request_hash": reply.request_hash,
            "provider_response_id": reply.provider_response_id,
            "fallback_error": provider_error,
        },
        "research": {
            "casual": casual,
            "mission": mission,
            "mission_error": mission_error,
            "retrieval": retrieval,
        },
        "persistence_mode": STORE.persistence_mode,
        "epistemic_policy": governed_context["epistemic_policy"],
    }

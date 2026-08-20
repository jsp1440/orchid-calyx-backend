from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.brain_mission.routes import SERVICE as BRAIN_MISSION_SERVICE
from app.security import verify_owner_or_api_key

from .climate_context import build_seasonal_climate_context
from .conversational_synthesis import is_follow_up, resolve_subject
from .continuum_context import build_continuum_context
from .external_literature import augment_retrieval_with_external_literature
from .interaction_context import sanitize_interaction_context
from .provider import DeterministicGovernedReplyProvider
from .provider_runtime import (
    configured_runtime_provider,
    runtime_provider_configuration,
)
from .routes import STORE, _retrieval

configured_reply_provider = configured_runtime_provider

AuthDependency = Annotated[dict[str, Any], Depends(verify_owner_or_api_key)]
router = APIRouter(prefix="/calyx/speak", tags=["calyx-speak"])

MAX_USER_TURN_CHARS = 100000
DEEP_RESEARCH_RETRIEVAL_LIMIT = 20


class ConversationCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    project_id: str | None = Field(default=None, max_length=200)
    context: dict[str, Any] = Field(default_factory=dict)


class ConversationTurnRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_USER_TURN_CHARS)
    project_id: str | None = Field(default=None, max_length=200)
    context: dict[str, Any] = Field(default_factory=dict)
    research_mode: Literal["auto", "always", "never"] = "auto"
    retrieval_limit: int = Field(default=12, ge=1, le=50)


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
        "hi", "hello", "hey", "good morning", "good afternoon", "good evening",
        "thanks", "thank you", "hello calyx", "hi calyx", "hey calyx",
    }
    if normalized in casual:
        return True
    if re.match(r"^(hello|hi|hey)\s+calyx(?:[.!?,;:]|\s|$)", normalized):
        capability_phrases = {
            "what are you able to help me with", "what can you help me with",
            "what can you do", "how can you help",
        }
        remainder = re.sub(
            r"^(hello|hi|hey)\s+calyx(?:[.!?,;:]|\s)*", "", normalized, count=1,
        ).strip(" .!?,;:")
        return not remainder or remainder in capability_phrases
    return False


def _deep_research_requested(message: str) -> bool:
    normalized = " ".join(message.casefold().split())
    phrases = (
        "literature review", "scientific literature", "peer-reviewed", "peer reviewed",
        "primary scientific", "annotated bibliography", "doi", "pmid",
        "formal review", "evidence-grounded", "evidence grounded", "research article",
    )
    return len(message.split()) >= 80 and any(phrase in normalized for phrase in phrases)


def _effective_retrieval_limit(message: str, requested: int) -> int:
    if _deep_research_requested(message):
        return max(requested, DEEP_RESEARCH_RETRIEVAL_LIMIT)
    return requested


def _mission_question(history: str, message: str) -> str:
    """Preserve the scientific subject of long turns instead of only their tail.

    ``history`` is a reference-resolution trail built from prior USER turns, not
    a raw transcript. A character-truncated transcript lets a verbose assistant
    reply evict the earlier question the follow-up depends on, which silently
    detaches the mission from the investigation. Prior assistant statements are
    excluded on the same principle that keeps them out of the evidence set.
    """

    current = " ".join(message.split())
    if len(current) > 900:
        current = current[:650] + " … " + current[-240:]
    if not history or len(message) > 700:
        return current[:1000]
    context = " ".join(history.split())[-350:]
    return (
        "Conversation context for reference resolution only, not scientific evidence: "
        + context + " Current question: " + current
    )[:1000]


def _reference_trail(conversation_id: str, owner: str) -> str:
    """Prior user questions, newest last, for follow-up reference resolution."""

    turns = STORE.user_turns(conversation_id, owner=owner, turns=6)
    return " ".join(
        " ".join(str(turn.get("content") or "").split()) for turn in turns
    ).strip()


def _safe_retrieval(message: str, retrieval_limit: int) -> dict[str, Any]:
    try:
        result = _retrieval(message, "HYBRID", retrieval_limit, True)
        result.setdefault("status", "available")
    except (ValueError, TypeError, RuntimeError) as exc:
        result = {
            "results": [], "total_eligible_results": 0, "retrieval_mode": "HYBRID",
            "status": "unavailable", "error": str(exc),
        }
    return augment_retrieval_with_external_literature(result, message, limit=retrieval_limit)


def _safe_continuum_context(message: str) -> dict[str, Any]:
    try:
        return build_continuum_context(message)
    except Exception as exc:  # noqa: BLE001
        return {
            "candidate_genera": [], "resolved_genera": [], "taxa": [],
            "diagnostics": [{"source": "continuum_context", "query": message[:120], "error": str(exc)}],
            "read_only": True, "automatic_publication": False, "knowledge_graph_mutation": False,
        }


def _safe_climate_context(message: str) -> dict[str, Any]:
    try:
        return build_seasonal_climate_context(message)
    except Exception as exc:  # noqa: BLE001
        return {
            "requested": True, "status": "unavailable",
            "provider": "NOAA/NWS Climate Prediction Center", "products": [],
            "diagnostics": [{"source": "climate_context", "error": str(exc)}],
            "external": True, "time_sensitive": True,
            "automatic_publication": False, "knowledge_graph_mutation": False,
        }


def _external_citations(retrieval: dict[str, Any]) -> list[dict[str, Any]]:
    records = (retrieval.get("external_literature") or {}).get("results") or []
    citations: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        title = str(record.get("title") or "").strip()
        doi = str(record.get("doi") or "").strip()
        pmid = str(record.get("pmid") or "").strip()
        key = (title.casefold(), doi.casefold(), pmid.casefold())
        if not title or key in seen:
            continue
        seen.add(key)
        citations.append({
            "title": title,
            "authors": str(record.get("authors") or "").strip() or None,
            "publication_date": str(record.get("publication_date") or "").strip() or None,
            "journal": str(record.get("journal") or "").strip() or None,
            "doi": doi or None,
            "pmid": pmid or None,
            "pmcid": str(record.get("pmcid") or "").strip() or None,
            "provider": str(record.get("source") or "Europe PMC"),
            "review_state": str(record.get("review_state") or "REVIEW_REQUIRED"),
            "canonical_evidence": bool(record.get("canonical_evidence", False)),
        })
    return citations


def _deliverable_capabilities() -> dict[str, Any]:
    return {
        "downloadable_conversation_export": True,
        "export_format": "markdown",
        "structured_citations": True,
        "chart_ready_tables": True,
        "chart_specification": True,
        "map_ready_occurrence_data": True,
        "image_media_provenance": True,
        "native_chart_rendering_from_answer": True,
        "native_map_rendering_from_answer": True,
        "map_rendering_mode": "latitude_longitude_occurrence_plot",
        "sourced_image_rendering_from_answer": True,
        "native_image_generation": False,
        "artifact_block_formats": ["calyx-chart", "calyx-map", "calyx-image"],
        "rule": (
            "The workspace can render chart blocks, latitude/longitude occurrence plots, and sourced HTTPS images. "
            "Never claim a generated photograph or basemap was created unless a runtime capability actually produced it. "
            "All rendered research media must preserve the supplied data or provenance."
        ),
    }


def _workspace_outputs(
    *,
    mission: dict[str, Any] | None,
    citations: list[dict[str, Any]],
    calyx_message: dict[str, Any],
) -> list[dict[str, Any]]:
    """Server-derived workspace outputs, grounded only in this turn's actual
    retrieval/mission evidence - never fabricated. Only ``table``/``text``
    kinds are produced here: nothing available at this point in a turn is
    verified chart or image data, and CALYX-MULTIMODAL-WORKSPACE-001
    requires outputs be "derived only from actual tool/module results," not
    invented to fill a visual slot. Shape matches the frontend's
    ``WorkspaceOutput`` contract (workspaceOutputBus.ts) field-for-field so
    no client-side reshaping is required.
    """
    outputs: list[dict[str, Any]] = []
    message_id = str(calyx_message.get("message_id") or "")
    created_at = str(calyx_message.get("created_at") or "")

    sources = (mission or {}).get("sources") or []
    if sources:
        outputs.append({
            "id": f"{message_id}:mission-sources",
            "kind": "table",
            "title": "Retrieved canonical sources",
            "subtitle": (
                f"{len(sources)} source(s) from governed Brain mission "
                f"{(mission or {}).get('mission_id', 'unknown')}"
            ),
            "provenance": {
                "source_module": "brain_mission",
                "source_id": (mission or {}).get("mission_id"),
                "generated": False,
                # These are the actual canonical sources the mission retrieved
                # and used as evidence, not an inference over them.
                "evidence_status": "evidence",
            },
            "payload": {
                "columns": [
                    {"key": "title", "label": "Title"},
                    {"key": "object_type", "label": "Type"},
                    {"key": "excerpt", "label": "Excerpt"},
                ],
                "rows": [
                    {
                        "title": str(source.get("title") or "Untitled source"),
                        "object_type": str(source.get("object_type") or ""),
                        "excerpt": str(source.get("authorized_excerpt") or ""),
                    }
                    for source in sources
                ],
            },
            "created_at": created_at,
        })

    missing_evidence = (mission or {}).get("missing_evidence") or []
    if missing_evidence:
        outputs.append({
            "id": f"{message_id}:missing-evidence",
            "kind": "text",
            "title": "Evidence gaps for this turn",
            "subtitle": None,
            "provenance": {
                "source_module": "brain_mission",
                "source_id": (mission or {}).get("mission_id"),
                "generated": False,
                # Explicit missing-evidence output: this is neither evidence
                # nor a derived claim - it is a disclosed gap.
                "evidence_status": "unknown",
            },
            "payload": {"body": "\n".join(f"- {item}" for item in missing_evidence)},
            "created_at": created_at,
        })

    if citations:
        outputs.append({
            "id": f"{message_id}:external-citations",
            "kind": "table",
            "title": "External literature citations",
            "subtitle": f"{len(citations)} review-required record(s) from Europe PMC",
            "provenance": {
                "source_module": "external_literature",
                "source_id": None,
                "generated": False,
                # Real bibliographic records, but not canonical Orchid
                # Continuum evidence until reviewed (see epistemic_policy's
                # external_literature_requires_review) - "derived" rather
                # than "evidence" reflects that honestly.
                "evidence_status": "derived",
            },
            "payload": {
                "columns": [
                    {"key": "title", "label": "Title"},
                    {"key": "authors", "label": "Authors"},
                    {"key": "journal", "label": "Journal"},
                    {"key": "doi", "label": "DOI"},
                ],
                "rows": [
                    {
                        "title": str(citation.get("title") or ""),
                        "authors": str(citation.get("authors") or ""),
                        "journal": str(citation.get("journal") or ""),
                        "doi": str(citation.get("doi") or ""),
                    }
                    for citation in citations
                ],
            },
            "created_at": created_at,
        })

    return outputs


def _run_governed_turn(
    *, owner: str, conversation_id: str, project_id: str, message: str,
    research_mode: str, retrieval_limit: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any] | None, str | None, bool]:
    casual = _is_casual(message) and research_mode != "always"
    if casual:
        return {
            "results": [], "total_eligible_results": 0, "retrieval_mode": "HYBRID", "status": "not_requested",
        }, {
            "candidate_genera": [], "resolved_genera": [], "taxa": [], "diagnostics": [],
            "read_only": True, "automatic_publication": False, "knowledge_graph_mutation": False,
        }, {
            "requested": False, "status": "not_relevant", "products": [],
            "external": True, "time_sensitive": True,
        }, None, None, True

    # A follow-up turn ("Why?", "What evidence is that based on?") carries its
    # subject only by reference. Retrieving on the literal words finds nothing
    # and the answer silently regresses to a generic evidence dump, so the
    # investigation subject is recovered from server-side conversation state
    # and used for retrieval, graph context and the governed mission.
    #
    # The resolved subject is INTERACTION CONTEXT: it decides what to retrieve.
    # It is never itself treated as scientific evidence.
    follow_up = is_follow_up(message)
    retrieval_subject = message
    resolved_subject: str | None = None
    if follow_up:
        prior = STORE.user_turns(conversation_id, owner=owner, turns=12)
        resolved = resolve_subject(message, prior)
        if resolved and resolved != message:
            # Retrieval widens to subject + follow-up wording; the composer is
            # given the clean subject alone so the reply can name what it is
            # continuing without echoing the follow-up back at the user.
            resolved_subject = resolved
            retrieval_subject = f"{resolved} {message}".strip()

    retrieval_limit = _effective_retrieval_limit(message, retrieval_limit)
    retrieval = _safe_retrieval(retrieval_subject, retrieval_limit)
    continuum = _safe_continuum_context(retrieval_subject)
    climate = _safe_climate_context(retrieval_subject)
    mission: dict[str, Any] | None = None
    mission_error: str | None = None

    local_results = retrieval.get("results") or []
    external_records = (retrieval.get("external_literature") or {}).get("results") or []
    canonical_empty = not bool(local_results)
    external_only = bool(external_records) and canonical_empty
    if canonical_empty:
        retrieval["conversation_synthesis_mode"] = (
            "external_review_literature" if external_only else "general_knowledge_with_retrieval_gap"
        )
        retrieval["canonical_mission_deferred"] = research_mode == "auto"
        retrieval["canonical_mission_deferred_reason"] = (
            "No canonical retrieval evidence was available for this turn. In automatic mode, Calyx must not launch "
            "a canonical Brain mission that can only block with zero sources. The conversational synthesis may use "
            "review-required external literature when present and otherwise must disclose the retrieval gap."
        )

    # A one-word follow-up is not a trivial turn -- it continues a substantive
    # question -- so the word-count gate is applied to the RESOLVED subject.
    should_run_mission = research_mode == "always" or (
        research_mode == "auto"
        and len(retrieval_subject.split()) >= 5
        and not canonical_empty
    )
    if should_run_mission:
        history = _reference_trail(conversation_id, owner)
        mission_question = _mission_question(history, retrieval_subject)
        evidence_set_id = str((retrieval.get("research_index_ingest") or {}).get("evidence_set_id") or "").strip()
        if evidence_set_id:
            mission_question += f"\nGoverned research evidence set: {evidence_set_id}"
        try:
            mission = BRAIN_MISSION_SERVICE.start(
                question=mission_question, tenant_id=owner, project_id=project_id, actor=owner,
                max_sources=20, max_steps=10, timeout_seconds=30,
            )
        except (ValueError, RuntimeError) as exc:
            mission_error = str(exc)
    retrieval["resolved_subject"] = resolved_subject
    return retrieval, continuum, climate, mission, mission_error, False


@router.get("/status")
def speak_status(auth: AuthDependency) -> dict[str, Any]:
    _subject(auth)
    provider = configured_reply_provider()
    provider_configuration = runtime_provider_configuration()
    return {
        "release": "CALYX-SPEAK-004-CONTEXT",
        "integration_release": "CALYX-SPEAK-012-DEEP-RESEARCH-DELIVERABLES",
        "conversation_persistence": STORE.persistence_mode,
        "semantic_retrieval_degraded_mode": True,
        "provider": {
            "name": getattr(provider, "provider_name", "openai-compatible"),
            "model": getattr(provider, "model_name", getattr(provider, "model", "unknown")),
            "generative": not isinstance(provider, DeterministicGovernedReplyProvider),
            "configuration": provider_configuration,
        },
        "continuum_context": {
            "automatic_taxon_resolution": True, "knowledge_graph_read": True, "brain_graph_read": True,
            "climate_provider": True, "climate_provider_name": "NOAA/NWS Climate Prediction Center",
            "external_literature_fallback": True, "external_literature_provider": "Europe PMC",
            "external_literature_relevance_ranking": True, "research_index_evidence_bridge": True,
            "external_review_synthesis_without_canonical_mission": True,
            "empty_canonical_retrieval_defers_auto_mission": True,
            "authorized_external_research_continues_without_reconfirmation": True,
            "deep_research_retrieval_limit": DEEP_RESEARCH_RETRIEVAL_LIMIT,
            "max_user_turn_chars": MAX_USER_TURN_CHARS,
        },
        "deliverables": _deliverable_capabilities(),
        "interaction_context": {"supported": True, "evidence": False, "max_session_trail": 8},
        "automatic_publication": False, "knowledge_graph_mutation": False,
    }


@router.post("/conversations", status_code=201)
def create_conversation(payload: ConversationCreateRequest, auth: AuthDependency) -> dict[str, Any]:
    owner = _subject(auth)
    interaction_context = sanitize_interaction_context(payload.context)
    conversation_id = STORE.create_or_touch(
        None, owner=owner, project_id=payload.project_id, title=payload.title, context=interaction_context,
    )
    conversation = STORE.get(conversation_id, owner=owner)
    if conversation is None:
        raise HTTPException(500, detail={"code": "CONVERSATION_CREATE_FAILED"})
    conversation["persistence_mode"] = STORE.persistence_mode
    return conversation


@router.get("/conversations")
def list_conversations(auth: AuthDependency, limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    owner = _subject(auth)
    resolved_limit = limit if isinstance(limit, int) else 20
    return {"conversations": STORE.recent(owner=owner, limit=resolved_limit), "persistence_mode": STORE.persistence_mode}


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str, auth: AuthDependency, message_limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    owner = _subject(auth)
    resolved_limit = message_limit if isinstance(message_limit, int) else 100
    try:
        conversation = STORE.get(conversation_id, owner=owner, message_limit=resolved_limit)
    except Exception as exc:
        raise HTTPException(422, detail={"code": "INVALID_CONVERSATION_IDENTIFIER"}) from exc
    if conversation is None:
        raise HTTPException(404, detail={"code": "CONVERSATION_NOT_FOUND"})
    conversation["persistence_mode"] = STORE.persistence_mode
    return conversation


@router.post("/conversations/{conversation_id}/turns")
def append_turn(conversation_id: str, payload: ConversationTurnRequest, auth: AuthDependency) -> dict[str, Any]:
    owner = _subject(auth)
    existing = STORE.get(conversation_id, owner=owner)
    if existing is None:
        raise HTTPException(404, detail={"code": "CONVERSATION_NOT_FOUND"})
    project_id = payload.project_id or str(existing.get("project_id") or "").strip() or f"calyx-speak:{conversation_id}"
    interaction_context = sanitize_interaction_context(payload.context)
    STORE.create_or_touch(
        conversation_id, owner=owner, project_id=project_id, title=None, context=interaction_context,
    )
    operator_message = STORE.append(
        conversation_id, "operator", payload.message,
        {"context": interaction_context, "research_mode": payload.research_mode}, owner=owner,
    )

    retrieval, continuum, climate, mission, mission_error, casual = _run_governed_turn(
        owner=owner, conversation_id=conversation_id, project_id=project_id, message=payload.message,
        research_mode=payload.research_mode, retrieval_limit=payload.retrieval_limit,
    )

    if mission is not None:
        STORE.append(
            conversation_id, "tool",
            f"Governed Brain mission {mission.get('mission_id', 'unknown')} finished with state {mission.get('state', 'unknown')}.",
            {"tool": "brain_mission", "mission_id": mission.get("mission_id"), "state": mission.get("state"),
             "review_status": mission.get("review_status"), "publication_eligibility": mission.get("publication_eligibility")},
            owner=owner,
        )

    if continuum.get("resolved_genera"):
        STORE.append(
            conversation_id, "tool",
            "Canonical Continuum graph context resolved for: " + ", ".join(continuum["resolved_genera"]),
            {"tool": "continuum_context", "resolved_genera": continuum.get("resolved_genera"),
             "read_only": True, "knowledge_graph_mutation": False}, owner=owner,
        )

    external_literature = retrieval.get("external_literature") or {}
    citations = _external_citations(retrieval)
    if external_literature.get("results"):
        STORE.append(
            conversation_id, "tool",
            f"Europe PMC external literature discovery returned {len(external_literature['results'])} relevance-ranked records.",
            {"tool": "external_literature", "provider": "Europe PMC", "review_required": True,
             "canonical_evidence": False, "conversation_synthesis_mode": retrieval.get("conversation_synthesis_mode"),
             "canonical_mission_deferred": retrieval.get("canonical_mission_deferred", False),
             "research_index_ingest": retrieval.get("research_index_ingest"), "citation_count": len(citations)},
            owner=owner,
        )

    if climate.get("products"):
        STORE.append(
            conversation_id, "tool",
            f"NOAA CPC climate context returned {len(climate['products'])} current discussion products.",
            {"tool": "seasonal_climate_context", "provider": climate.get("provider"), "time_sensitive": True,
             "canonical_orchid_evidence": False}, owner=owner,
        )

    governed_context = {
        "casual": casual, "conversation_id": conversation_id, "project_id": project_id,
        "interaction_context": interaction_context, "retrieval": retrieval, "continuum": continuum,
        "climate": climate, "mission": mission, "mission_error": mission_error,
        # The investigation subject this turn continues, resolved server-side
        # from persistent conversation state. Interaction context, not evidence.
        "resolved_subject": retrieval.get("resolved_subject"),
        "provider_configuration": runtime_provider_configuration(),
        "deliverable_capabilities": _deliverable_capabilities(),
        "epistemic_policy": {
            "continuum_first": True, "provider_memory_is_evidence": False,
            "interaction_context_is_evidence": False, "external_literature_requires_review": True,
            "external_literature_may_support_provisional_conversational_synthesis": True,
            "external_literature_may_enter_research_index_unverified": True,
            "authorized_external_research_continues_without_reconfirmation": True,
            "only_claim_available_research_providers": True,
            "climate_products_are_time_sensitive_external_context": True,
            "climate_claims_must_be_supported_by_retrieved_product_text": True,
            "conversation_does_not_publish_knowledge": True,
            "candidate_knowledge_auto_promotion": False, "knowledge_graph_mutation": False,
        },
    }
    messages = STORE.provider_messages(conversation_id, owner=owner, turns=8)
    provider = configured_reply_provider()
    provider_error: str | None = None
    try:
        reply = provider.generate(messages=messages, governed_context=governed_context)
    except Exception as exc:  # noqa: BLE001
        provider_error = str(exc)
        fallback = DeterministicGovernedReplyProvider()
        reply = fallback.generate(messages=messages, governed_context=governed_context)

    calyx_message = STORE.append(
        conversation_id, "calyx", reply.text,
        {
            "provider": reply.provider, "model": reply.model,
            "synthesis_structure": reply.synthesis_structure,
            "provider_response_id": reply.provider_response_id, "request_hash": reply.request_hash,
            "provider_error": provider_error, "provider_configuration": runtime_provider_configuration(),
            "mission_id": mission.get("mission_id") if mission else None,
            "mission_state": mission.get("state") if mission else None,
            "review_status": mission.get("review_status") if mission else None,
            "retrieval_eligible_results": retrieval.get("total_eligible_results"),
            "retrieval_status": retrieval.get("status"), "retrieval_error": retrieval.get("error"),
            "conversation_synthesis_mode": retrieval.get("conversation_synthesis_mode"),
            "canonical_mission_deferred": retrieval.get("canonical_mission_deferred", False),
            "external_literature_count": external_literature.get("result_count", 0),
            "external_literature_status": external_literature.get("status"),
            "citations": citations,
            "research_index_ingest": retrieval.get("research_index_ingest"),
            "climate_status": climate.get("status"), "climate_product_count": len(climate.get("products") or []),
            "continuum_resolved_genera": continuum.get("resolved_genera"),
            "continuum_diagnostics": continuum.get("diagnostics"), "interaction_context": interaction_context,
            "research_mode": payload.research_mode,
            "publication_boundary": "human-review-governed; no automatic publication or graph mutation",
        }, owner=owner,
    )
    return {
        "conversation_id": conversation_id, "operator_message": operator_message,
        "calyx_message": calyx_message, "answer": reply.text,
        "provider": {
            "name": reply.provider, "model": reply.model, "request_hash": reply.request_hash,
            "provider_response_id": reply.provider_response_id, "fallback_error": provider_error,
            "configuration": runtime_provider_configuration(),
        },
        "interaction_context": interaction_context,
        "synthesis_structure": reply.synthesis_structure,
        "research": {
            "casual": casual, "mission": mission, "mission_error": mission_error,
            "retrieval": retrieval, "continuum": continuum, "climate": climate,
            "citations": citations,
        },
        "workspace_outputs": _workspace_outputs(
            mission=mission, citations=citations, calyx_message=calyx_message,
        ),
        "deliverables": _deliverable_capabilities(),
        "persistence_mode": STORE.persistence_mode,
        "epistemic_policy": governed_context["epistemic_policy"],
    }
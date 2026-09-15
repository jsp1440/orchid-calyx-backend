"""Kalix API routes — GET /kalix/status, POST /kalix/speak.

All generative turns delegate to the same provider infrastructure
as Calyx (configured_runtime_provider). Knowledge retrieval delegates to
build_kalix_context → build_knowledge_context. No additional provider
cost is introduced; NO_API_MODE remains the default.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.calyx_conversation.provider import DeterministicGovernedReplyProvider
from app.calyx_conversation.provider_runtime import (
    configured_runtime_provider,
    runtime_provider_configuration,
)
from app.security import verify_owner_or_api_key

from .context_bridge import build_kalix_context
from .persona import DEPTH_LEVELS, KALIX_PERSONA, OPERATIONAL_DOMAINS

AuthDependency = Annotated[dict[str, Any], Depends(verify_owner_or_api_key)]
router = APIRouter(prefix="/kalix", tags=["kalix"])

MAX_MESSAGE_CHARS = 8000


class KalixSpeakRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    depth_hint: str = Field(default="", max_length=200)
    oc_modules: list[str] = Field(default_factory=list)


def _subject(auth: dict[str, Any]) -> str:
    subject = str(auth.get("subject") or auth.get("actor") or "").strip()
    if not subject:
        raise HTTPException(401, detail={"code": "AUTHENTICATED_SUBJECT_REQUIRED"})
    return subject


@router.get("/status")
def kalix_status(auth: AuthDependency) -> dict[str, Any]:
    """Kalix operational status — persona version, domains, provider."""
    _subject(auth)
    provider = configured_runtime_provider()
    return {
        "release": KALIX_PERSONA.version,
        "persona_version": KALIX_PERSONA.version,
        "operational_domains": OPERATIONAL_DOMAINS,
        "domain_count": len(OPERATIONAL_DOMAINS),
        "depth_levels": list(DEPTH_LEVELS.keys()),
        "provider": {
            "name": getattr(provider, "provider_name", "deterministic"),
            "model": getattr(provider, "model_name", getattr(provider, "model", "governed")),
            "generative": not isinstance(provider, DeterministicGovernedReplyProvider),
            "configuration": runtime_provider_configuration(),
        },
        "knowledge_bridge": "KALIX-CONTEXT-001",
        "calyx_constitution": "CALYX-PERSONA-005",
        "canonical_graph_mutated": False,
        "engineering_dispatch_authorized": False,
        "provider_calls": 0,
    }


@router.post("/speak")
def kalix_speak(payload: KalixSpeakRequest, auth: AuthDependency) -> dict[str, Any]:
    """Single-turn Kalix speak — returns knowledge context + provider answer."""
    owner = _subject(auth)
    depth_level = KALIX_PERSONA.adapt_depth(payload.depth_hint) if payload.depth_hint else "grower"
    system_context = KALIX_PERSONA.build_system_context(depth_level, payload.oc_modules)
    kalix_context = build_kalix_context(
        payload.message,
        depth_level=depth_level,
        oc_modules=payload.oc_modules,
    )

    provider = configured_runtime_provider()
    messages = [{"role": "user", "content": payload.message}]
    governed_context: dict[str, Any] = {
        **kalix_context,
        "system": system_context,
        "owner": owner,
    }

    provider_error: str | None = None
    try:
        reply = provider.generate(messages=messages, governed_context=governed_context)
    except Exception:  # noqa: BLE001
        provider_error_obj = None
        try:
            provider_error_obj = Exception("provider unavailable")
            fallback = DeterministicGovernedReplyProvider()
            reply = fallback.generate(messages=messages, governed_context=governed_context)
            provider_error = "primary provider unavailable; deterministic fallback used"
        except Exception:  # noqa: BLE001
            raise HTTPException(503, detail={"code": "PROVIDER_UNAVAILABLE"}) from provider_error_obj

    return {
        "answer": reply.text,
        "kalix_context": kalix_context,
        "persona_version": KALIX_PERSONA.version,
        "depth_level": depth_level,
        "provider": {
            "name": reply.provider,
            "model": reply.model,
            "fallback_error": provider_error,
            "configuration": runtime_provider_configuration(),
        },
        "canonical_graph_mutated": False,
        "engineering_dispatch_authorized": False,
        "provider_calls": 0,
    }

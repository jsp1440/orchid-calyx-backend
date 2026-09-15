"""Kalix API routes — GET /kalix/status, POST /kalix/speak.

All generative turns delegate to the same provider infrastructure
as Calyx (configured_runtime_provider). Knowledge retrieval delegates to
build_kalix_context → build_knowledge_context. NO_API_MODE remains the default,
and provider-call accounting reflects whether a generative provider was attempted.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal

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
DepthLevel = Literal["grower", "student", "scientist", "researcher"]
router = APIRouter(prefix="/kalix", tags=["kalix"])

MAX_MESSAGE_CHARS = 8000


class KalixSpeakRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    depth: DepthLevel | None = None
    depth_hint: str = Field(default="", max_length=200)
    project_id: str | None = Field(default=None, max_length=200)
    oc_modules: list[str] = Field(default_factory=list)


def _subject(auth: dict[str, Any]) -> str:
    subject = str(auth.get("subject") or auth.get("actor") or "").strip()
    if not subject:
        raise HTTPException(401, detail={"code": "AUTHENTICATED_SUBJECT_REQUIRED"})
    return subject


def _is_generative_provider(provider: Any) -> bool:
    if isinstance(provider, DeterministicGovernedReplyProvider):
        return False
    provider_name = str(getattr(provider, "provider_name", "")).strip().casefold()
    return provider_name not in {"", "deterministic", "governed", "no_api", "no-api"}


@router.get("/status")
def kalix_status(auth: AuthDependency) -> dict[str, Any]:
    """Kalix operational status — persona version, domains, provider."""
    _subject(auth)
    provider = configured_runtime_provider()
    return {
        "release": KALIX_PERSONA.version,
        "persona": "Kalix",
        "persona_version": KALIX_PERSONA.version,
        "operational_domains": OPERATIONAL_DOMAINS,
        "domain_count": len(OPERATIONAL_DOMAINS),
        "depth_levels": list(DEPTH_LEVELS.keys()),
        "provider": {
            "name": getattr(provider, "provider_name", "deterministic"),
            "model": getattr(provider, "model_name", getattr(provider, "model", "governed")),
            "generative": _is_generative_provider(provider),
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
    """Single-turn Kalix speak — returns grounded knowledge + provider answer."""
    owner = _subject(auth)
    depth_level: str = payload.depth or (
        KALIX_PERSONA.adapt_depth(payload.depth_hint) if payload.depth_hint else "grower"
    )
    system_context = KALIX_PERSONA.build_system_context(depth_level, payload.oc_modules)
    kalix_context = build_kalix_context(
        payload.message,
        persona_config={"project_id": payload.project_id} if payload.project_id else None,
        depth_level=depth_level,
        oc_modules=payload.oc_modules,
    )

    provider = configured_runtime_provider()
    provider_calls = 1 if _is_generative_provider(provider) else 0
    messages = [{"role": "user", "content": payload.message}]
    governed_context: dict[str, Any] = {
        **kalix_context,
        "system": system_context,
        "owner": owner,
        "project_id": payload.project_id,
    }

    provider_error: str | None = None
    try:
        reply = provider.generate(messages=messages, governed_context=governed_context)
    except Exception:  # noqa: BLE001
        try:
            fallback = DeterministicGovernedReplyProvider()
            reply = fallback.generate(messages=messages, governed_context=governed_context)
            provider_error = "primary provider unavailable; deterministic fallback used"
        except Exception as fallback_error:
            raise HTTPException(
                503,
                detail={"code": "PROVIDER_UNAVAILABLE"},
            ) from fallback_error

    return {
        "persona": "Kalix",
        "knowledge": kalix_context,
        "answer": reply.text,
        "kalix_context": kalix_context,
        "persona_version": KALIX_PERSONA.version,
        "depth_used": depth_level,
        "depth_level": depth_level,
        "project_id": payload.project_id,
        "provider": {
            "name": reply.provider,
            "model": reply.model,
            "fallback_error": provider_error,
            "configuration": runtime_provider_configuration(),
        },
        "canonical_graph_mutated": False,
        "engineering_dispatch_authorized": False,
        "provider_calls": provider_calls,
    }

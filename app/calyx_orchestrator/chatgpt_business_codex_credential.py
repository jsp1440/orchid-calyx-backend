"""Credential loader for ChatGPT Business / Codex programmatic access token.

Exactly one environment variable is read:

    CALYX_CHATGPT_BUSINESS_CODEX_TOKEN

This is a ChatGPT Business workspace access token obtained through the
Business settings UI — NOT an OpenAI Platform API key, NOT OPENAI_API_KEY,
NOT any fallback credential path.

Design intent (mirrors github_agent_credential.py):
- No fallback to OPENAI_API_KEY — its presence is treated as a misconfiguration
  and causes the loader to raise, not silently succeed.
- _load_token takes the exact variable name as a keyword argument so a future
  edit cannot quietly add a fallback without it being an obvious, reviewable
  change to a single line.
- The credential value is never included in exception messages, logs, or
  execution receipts. Receipts record AUTH_MODE, not the secret.
- Missing or blank token parks the lane safely (raises CodexCredentialError).
"""

from __future__ import annotations

import os
from collections.abc import Mapping

CODEX_BUSINESS_TOKEN_ENV_VAR = "CALYX_CHATGPT_BUSINESS_CODEX_TOKEN"
# Presence of OPENAI_API_KEY indicates wrong credential path; fail closed.
OPENAI_API_KEY_ENV_VAR = "OPENAI_API_KEY"

AUTH_MODE_BUSINESS_TOKEN = "chatgpt_business_codex_token"
AUTH_MODE_MISSING = "missing"


class CodexCredentialError(RuntimeError):
    """Raised when the Business Codex credential is absent, blank, or superseded.

    Never includes the attempted value — there is nothing to include when
    this fires, by construction.
    """


class CodexApiKeyFallbackError(CodexCredentialError):
    """Raised when OPENAI_API_KEY is present, because that path is prohibited.

    The correct path is CALYX_CHATGPT_BUSINESS_CODEX_TOKEN only.
    """


def _load_token(environ: Mapping[str, str], *, variable_name: str) -> str:
    """Load and validate one credential variable. Raises if absent or blank.

    Takes variable_name as an explicit keyword to prevent silent fallback by
    callers who might otherwise write ``or os.getenv(other_var)``.
    """
    value = (environ.get(variable_name) or "").strip()
    if not value:
        raise CodexCredentialError(
            f"{variable_name} is not configured. "
            "The ChatGPT Business Codex execution path fails closed rather than "
            "falling back to any other credential. "
            "AUTH_MODE=missing. Lane parked safely."
        )
    return value


def check_no_openai_api_key_fallback(environ: Mapping[str, str]) -> None:
    """Raise CodexApiKeyFallbackError if OPENAI_API_KEY is present.

    OPENAI_API_KEY is the paid Platform billing path and is explicitly
    prohibited for this execution lane. Its presence indicates misconfiguration;
    we fail closed rather than silently accepting the wrong credential.
    """
    if (environ.get(OPENAI_API_KEY_ENV_VAR) or "").strip():
        raise CodexApiKeyFallbackError(
            f"{OPENAI_API_KEY_ENV_VAR} is present. "
            "This is the paid OpenAI Platform billing path and is prohibited for "
            "ChatGPT Business Codex programmatic execution. "
            "Unset OPENAI_API_KEY and provide CALYX_CHATGPT_BUSINESS_CODEX_TOKEN. "
            "AUTH_MODE=api_key_fallback_prohibited. Lane parked safely."
        )


class CodexBusinessCredential:
    """Validated credential container. Never exposes the token value in repr."""

    def __init__(self, token: str, auth_mode: str = AUTH_MODE_BUSINESS_TOKEN) -> None:
        if not token.strip():
            raise CodexCredentialError("CodexBusinessCredential requires a non-blank token")
        self._token = token.strip()
        self.auth_mode = auth_mode

    @property
    def bearer_value(self) -> str:
        """The raw token value for use in Authorization headers only."""
        return self._token

    def __repr__(self) -> str:
        return f"CodexBusinessCredential(auth_mode={self.auth_mode!r}, token=<redacted>)"


def load_codex_business_credential(
    *, environ: Mapping[str, str] | None = None
) -> CodexBusinessCredential:
    """Load and validate the ChatGPT Business Codex programmatic token.

    Execution order (fail-closed on each step):
    1. Reject if OPENAI_API_KEY is present (wrong path).
    2. Load CALYX_CHATGPT_BUSINESS_CODEX_TOKEN; raise if absent or blank.

    Returns a CodexBusinessCredential whose bearer_value is available for
    Authorization headers only. The credential value is never recorded in
    logs, receipts, or exception messages.

    ``environ`` defaults to ``os.environ`` and exists for test isolation.
    """
    source: Mapping[str, str] = os.environ if environ is None else environ
    check_no_openai_api_key_fallback(source)
    token = _load_token(source, variable_name=CODEX_BUSINESS_TOKEN_ENV_VAR)
    return CodexBusinessCredential(token)

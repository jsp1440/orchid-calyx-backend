"""Guards that keep evolve records concise, inspectable, and secret-free.

CALYX-EVOLVE-001 persists analysis *summaries*, never private chain-of-thought
or full provider transcripts, and never credentials.  These checks run at record
construction time so an unsafe record cannot reach durable memory at all.

The checks are deliberately conservative and structural: they look for the
marker keys a transcript-shaped payload carries, for credential-shaped keys and
values, and for the protected-locality fields the taxonomy pipelines already
treat as restricted.  They are a fail-closed backstop, not a content classifier.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

#: Keys that indicate a transcript or private reasoning trace rather than a summary.
FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {
        "chain_of_thought",
        "chainofthought",
        "cot",
        "reasoning_trace",
        "thinking",
        "thought",
        "thoughts",
        "scratchpad",
        "transcript",
        "messages",
        "conversation",
        "raw_completion",
        "raw_response",
        "provider_transcript",
        "prompt",
        "system_prompt",
        "completion_text",
    }
)

#: Keys that carry credentials or secrets.
CREDENTIAL_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "access_token",
        "refresh_token",
        "bearer",
        "client_secret",
        "database_url",
        "dsn",
        "password",
        "passwd",
        "private_key",
        "secret",
        "secret_key",
        "session_token",
        "token",
    }
)

#: Keys that expose protected collection locality.
PROTECTED_LOCALITY_KEYS: frozenset[str] = frozenset(
    {
        "exact_latitude",
        "exact_longitude",
        "decimal_latitude",
        "decimal_longitude",
        "precise_locality",
        "protected_locality",
        "collection_site",
        "grower_address",
        "site_address",
        "gps",
        "coordinates",
    }
)

#: Values shaped like a credential regardless of the key they sit under.
_SECRET_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]{16,}", re.IGNORECASE),
    re.compile(r"\b(?:postgres|postgresql)://[^\s/@]+:[^\s/@]+@", re.IGNORECASE),
)

#: Maximum characters allowed in any single free-text field of a durable record.
FREE_TEXT_MAX_CHARS = 2000


class RedactionViolation(ValueError):
    """Raised when a record would persist forbidden content."""

    def __init__(self, reason: str, path: str) -> None:
        super().__init__(f"{reason} at {path}")
        self.reason = reason
        self.path = path


def _normalise_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _walk(payload: Any, path: str) -> Iterable[tuple[str, Any, Any]]:
    """Yield ``(path, key, value)`` for every member of ``payload``."""

    if isinstance(payload, dict):
        for key, value in payload.items():
            child = f"{path}.{key}" if path else str(key)
            yield child, key, value
            yield from _walk(value, child)
    elif isinstance(payload, (list, tuple)):
        for index, value in enumerate(payload):
            child = f"{path}[{index}]"
            yield child, None, value
            yield from _walk(value, child)


_NORMALISED_FORBIDDEN = {_normalise_key(key) for key in FORBIDDEN_KEYS}
_NORMALISED_CREDENTIAL = {_normalise_key(key) for key in CREDENTIAL_KEYS}
_NORMALISED_LOCALITY = {_normalise_key(key) for key in PROTECTED_LOCALITY_KEYS}


def find_violations(payload: Any) -> tuple[RedactionViolation, ...]:
    """Return every redaction violation found in ``payload``."""

    violations: list[RedactionViolation] = []
    for path, key, value in _walk(payload, ""):
        if key is not None:
            normalised = _normalise_key(key)
            if normalised in _NORMALISED_FORBIDDEN:
                violations.append(RedactionViolation("private reasoning or transcript field", path))
            if normalised in _NORMALISED_CREDENTIAL:
                violations.append(RedactionViolation("credential field", path))
            if normalised in _NORMALISED_LOCALITY:
                violations.append(RedactionViolation("protected locality field", path))
        if isinstance(value, str):
            if len(value) > FREE_TEXT_MAX_CHARS:
                violations.append(
                    RedactionViolation(
                        f"free text exceeds {FREE_TEXT_MAX_CHARS} characters", path
                    )
                )
            for pattern in _SECRET_VALUE_PATTERNS:
                if pattern.search(value):
                    violations.append(RedactionViolation("secret-shaped value", path))
                    break
    return tuple(violations)


def assert_inspectable(payload: Any) -> None:
    """Raise :class:`RedactionViolation` if ``payload`` may not be persisted."""

    violations = find_violations(payload)
    if violations:
        raise violations[0]


def locality_violations(payload: Any) -> tuple[str, ...]:
    """Return paths where ``payload`` exposes protected locality."""

    return tuple(
        violation.path
        for violation in find_violations(payload)
        if violation.reason == "protected locality field"
    )

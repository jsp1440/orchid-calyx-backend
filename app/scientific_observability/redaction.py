"""Defense-in-depth redaction for observation telemetry.

The observation envelope is designed to never carry protected values, but
telemetry is written from many call sites and free-form ``extensions``/``raw``
bags are easy to misuse. This pass reuses the canonical
``app.data_governance.disclosure`` key-sets (single source of truth for what
counts as protected locality / imagery) and adds secret/credential key
detection. It recursively strips offending keys and reports what it removed so
the anomaly layer can raise ``PROTECTED_LOCALITY_EXPOSURE``.

Redaction never mutates authoritative scientific state; it only sanitizes the
observation copy before it is stored or exported.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.data_governance.disclosure import (
    _EXACT_LOCATION_KEYS,
    _GENERALIZED_LOCATION_KEYS,
    _IMAGE_KEYS,
)

# Reuse canonical locality/image key-sets. Generalized location keys (country,
# region) are NOT redacted — they are the safe, generalized disclosure level.
_PROTECTED_LOCATION_KEYS = frozenset(_EXACT_LOCATION_KEYS)
_PROTECTED_IMAGE_BYTE_KEYS = frozenset({"image_bytes", "media_bytes"})

# Secret/credential key fragments. Matched as case-insensitive substrings.
_SECRET_KEY_FRAGMENTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "auth_token",
    "access_key",
    "private_key",
    "credential",
    "session_secret",
    "cookie",
    "bearer",
    "raw_prompt",
    "prompt_text",
    "prompt_contents",
)

REDACTION_PLACEHOLDER = "__REDACTED__"


@dataclass(slots=True)
class RedactionReport:
    """What the redaction pass removed, by category, with dotted paths."""

    protected_locality_paths: list[str] = field(default_factory=list)
    secret_paths: list[str] = field(default_factory=list)
    image_byte_paths: list[str] = field(default_factory=list)

    @property
    def protected_locality_detected(self) -> bool:
        return bool(self.protected_locality_paths)

    @property
    def secret_detected(self) -> bool:
        return bool(self.secret_paths)

    @property
    def any_redacted(self) -> bool:
        return bool(
            self.protected_locality_paths or self.secret_paths or self.image_byte_paths
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "protected_locality_detected": self.protected_locality_detected,
            "protected_locality_paths": list(self.protected_locality_paths),
            "secret_detected": self.secret_detected,
            "secret_paths": list(self.secret_paths),
            "image_byte_paths": list(self.image_byte_paths),
        }


def _is_secret_key(key: str) -> bool:
    normalized = key.casefold()
    return any(fragment in normalized for fragment in _SECRET_KEY_FRAGMENTS)


def redact_payload(payload: Any, report: RedactionReport | None = None, _path: str = "") -> Any:
    """Return a deep-copied, redacted version of ``payload``.

    Removes protected exact-locality keys, raw image/media bytes, and
    secret-like keys anywhere in the structure. ``report`` accumulates the
    dotted paths of everything redacted.
    """

    if report is None:
        report = RedactionReport()

    if isinstance(payload, Mapping):
        result: dict[str, Any] = {}
        for key, value in payload.items():
            path = f"{_path}.{key}" if _path else str(key)
            normalized = str(key).casefold()
            if normalized in _PROTECTED_LOCATION_KEYS:
                report.protected_locality_paths.append(path)
                continue
            if normalized in _PROTECTED_IMAGE_BYTE_KEYS:
                report.image_byte_paths.append(path)
                continue
            if _is_secret_key(str(key)):
                report.secret_paths.append(path)
                result[key] = REDACTION_PLACEHOLDER
                continue
            result[key] = redact_payload(value, report, path)
        return result

    if isinstance(payload, (list, tuple)) and not isinstance(payload, (str, bytes)):
        return [redact_payload(item, report, f"{_path}[{i}]") for i, item in enumerate(payload)]

    return payload


def redact_event_dict(event: Mapping[str, Any]) -> tuple[dict[str, Any], RedactionReport]:
    """Redact a serialized observation event, returning (clean_event, report)."""

    report = RedactionReport()
    clean = redact_payload(event, report)
    return clean, report


__all__ = [
    "RedactionReport",
    "redact_payload",
    "redact_event_dict",
    "REDACTION_PLACEHOLDER",
]

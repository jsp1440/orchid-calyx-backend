"""Output-safety helpers for the show-management routes in ``app.routers.calyx_core``.

* ``redact_config_json`` -- integration ``config_json`` is stored as the owner sent it
  (so providers keep working) but every response masks values under secret-looking
  keys (password, secret, token, api_key, key, authorization, credential, ...) as
  ``"***"`` and, inside URL strings, masks the password of ``scheme://user:pw@host``
  and the value of secret-looking query parameters (``?token=...``). A
  stored value that is not valid JSON is opaque, so it is masked entirely (fail
  closed).
* ``ics_text_line`` -- builds one iCalendar content line with RFC 5545 TEXT escaping
  (backslash, ``;``, ``,``, CR/LF as ``\\n``) and 75-octet line folding, so a title,
  location or note can never start a new calendar line (``BEGIN:VEVENT`` injection).
* ``render_template_text`` -- replaces ``{name}`` placeholders from a flat context.
  It never calls ``str.format``: no format specs (``{x:>50000000}``), no attribute or
  index access (``{x.__class__}``, ``{x[0]}``). ``{{`` / ``}}`` are literal braces as
  before; any other brace text is left as written. Output size is bounded while it is
  built.
"""

from __future__ import annotations

import json
import re
from typing import Any

from fastapi import HTTPException

REDACTED = "***"

_SECRET_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "apikey",
    "authorization",
    "credential",
    "privatekey",
    "signature",
    "cookie",
)
_SECRET_KEY_EXACT = {"key", "pass", "pwd", "auth", "bearer"}
_URL_USERINFO_PASSWORD = re.compile(
    r"(?P<prefix>[A-Za-z][A-Za-z0-9+.-]*://[^/\s:@]*:)[^/\s@]+@"
)
_URL_QUERY_PARAM = re.compile(
    r"(?P<prefix>[?&;](?P<name>[^=&;#\s]+)=)(?P<value>[^&;#\s]*)"
)


def _is_secret_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
    if normalized in _SECRET_KEY_EXACT or normalized.endswith("key"):
        return True
    return any(part in normalized for part in _SECRET_KEY_PARTS)


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: REDACTED if _is_secret_key(key) else _redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, str) and "://" in value:
        value = _URL_USERINFO_PASSWORD.sub(
            lambda match: f"{match.group('prefix')}{REDACTED}@", value
        )
        return _URL_QUERY_PARAM.sub(
            lambda match: (
                f"{match.group('prefix')}{REDACTED}"
                if _is_secret_key(match.group("name"))
                else match.group(0)
            ),
            value,
        )
    return value


def redact_config_json(config_json: str | None) -> str | None:
    """Return ``config_json`` with secret values masked; the stored value is untouched."""
    if config_json is None or config_json.strip() == "":
        return config_json
    try:
        parsed = json.loads(config_json)
    except (TypeError, ValueError):
        return REDACTED
    return json.dumps(_redact_value(parsed), ensure_ascii=False)


# --- iCalendar -------------------------------------------------------------------------

ICS_LINE_OCTETS = 75


def ics_escape_text(value: object) -> str:
    """RFC 5545 section 3.3.11 TEXT escaping; every CR/LF form becomes a literal ``\\n``."""
    text = str(value)
    text = text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")
    # Other control characters are not allowed in TEXT values (RFC 5545 3.1, 3.3.11).
    return "".join(
        ch for ch in text if ch == "\t" or ord(ch) >= 0x20 and ord(ch) != 0x7F
    )


def ics_fold(line: str) -> list[str]:
    """Fold a content line into chunks of at most 75 octets (RFC 5545 section 3.1).

    Continuation chunks start with one space, which counts toward their 75 octets.
    A multi-octet UTF-8 character is never split.
    """
    chunks: list[str] = []
    current = ""
    current_octets = 0
    for ch in line:
        width = len(ch.encode("utf-8"))
        if current_octets + width > ICS_LINE_OCTETS:
            chunks.append(current)
            current, current_octets = " ", 1
        current += ch
        current_octets += width
    chunks.append(current)
    return chunks


def ics_text_line(name: str, value: object) -> list[str]:
    return ics_fold(f"{name}:{ics_escape_text(value)}")


def ics_strip_line_breaks(value: object) -> str:
    """For non-TEXT values (UID): remove CR/LF and other control characters outright."""
    return "".join(ch for ch in str(value) if ord(ch) >= 0x20 and ord(ch) != 0x7F)


# --- message templates -----------------------------------------------------------------

MAX_TEMPLATE_CHARS = 20_000
MAX_RENDERED_CHARS = 50_000
MAX_CONTEXT_KEYS = 100
MAX_CONTEXT_VALUE_CHARS = 5_000

_PLACEHOLDER = re.compile(r"\{\{|\}\}|\{([A-Za-z_][A-Za-z0-9_]{0,63})\}")
_SCALARS = (str, int, float, bool)


def _unprocessable(message: str, **extra: object) -> HTTPException:
    return HTTPException(status_code=422, detail={"message": message, **extra})


def check_template_size(
    subject_template: str | None, body_template: str | None
) -> None:
    for field, value in (
        ("subject_template", subject_template),
        ("body_template", body_template),
    ):
        if value is not None and len(value) > MAX_TEMPLATE_CHARS:
            raise _unprocessable(
                f"{field} exceeds {MAX_TEMPLATE_CHARS} characters", field=field
            )


def normalize_render_context(context: dict) -> dict[str, str]:
    """Accept a flat mapping of placeholder names to scalar values only."""
    if len(context) > MAX_CONTEXT_KEYS:
        raise _unprocessable(f"context has more than {MAX_CONTEXT_KEYS} keys")
    normalized: dict[str, str] = {}
    for key, value in context.items():
        if not isinstance(key, str):
            raise _unprocessable("context keys must be strings")
        if value is None:
            text = ""
        elif isinstance(value, _SCALARS):
            text = str(value)
        else:
            raise _unprocessable(
                "context values must be strings, numbers, booleans or null", key=key
            )
        if len(text) > MAX_CONTEXT_VALUE_CHARS:
            raise _unprocessable(
                f"context value exceeds {MAX_CONTEXT_VALUE_CHARS} characters", key=key
            )
        normalized[key] = text
    return normalized


def render_template_text(
    template: str | None, context: dict[str, str], *, field: str
) -> str:
    """Substitute ``{name}`` placeholders; bounded, no ``str.format`` semantics."""
    if not template:
        return ""
    parts: list[str] = []
    size = 0
    position = 0
    missing: set[str] = set()
    for match in _PLACEHOLDER.finditer(template):
        token = match.group(0)
        name = match.group(1)
        if name is None:
            replacement = token[0]  # "{{" -> "{", "}}" -> "}"
        elif name in context:
            replacement = context[name]
        else:
            missing.add(name)
            replacement = ""
        piece = template[position : match.start()] + replacement
        size += len(piece)
        if size > MAX_RENDERED_CHARS:
            raise _unprocessable(
                f"rendered {field} exceeds {MAX_RENDERED_CHARS} characters", field=field
            )
        parts.append(piece)
        position = match.end()
    tail = template[position:]
    if size + len(tail) > MAX_RENDERED_CHARS:
        raise _unprocessable(
            f"rendered {field} exceeds {MAX_RENDERED_CHARS} characters", field=field
        )
    if missing:
        raise _unprocessable(
            "context is missing template variables",
            field=field,
            missing=sorted(missing),
        )
    parts.append(tail)
    return "".join(parts)

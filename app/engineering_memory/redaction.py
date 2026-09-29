"""Deterministic secret and protected-locality redaction for engineering memory.

This is a last-mile, fail-closed guard applied to *every* free-text field
before persistence.  It is deliberately conservative: it prefers to over-redact
rather than let a secret or a precise protected coordinate reach the database.

Two concerns are handled:

1. **Secrets** — API tokens, keys, credentials, connection strings,
   ``Authorization`` headers, and common dotenv-style assignments.  Matched
   spans are replaced with ``[REDACTED_SECRET:<label>]``.

2. **Protected locality** — precise decimal-degree coordinate pairs.  By policy
   these are reduced to ``[REDACTED_COORDINATES]`` (the default) or, when the
   caller requests strict handling, cause the write to be rejected.  Structured
   payloads explicitly flagged as protected locality always fail closed.

The redaction *report* records labels and counts only.  Raw secret values are
never placed in the report, in logs, in errors, or in test fixtures.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import REDACTION_CLEAN, REDACTION_REDACTED

# Placeholders deliberately avoid ``:``/``=`` so they can never be re-matched by
# the assignment heuristic below.  This keeps redaction idempotent, which the
# residual-secret guard relies on.
SECRET_PLACEHOLDER = "[REDACTED_SECRET_{label}]"
COORDINATE_PLACEHOLDER = "[REDACTED_COORDINATES]"


class ProtectedLocalityError(ValueError):
    """Raised when strict policy rejects a payload carrying protected locality."""


# ---------------------------------------------------------------------------
# Secret patterns.  Ordered; earlier, more specific rules run first.
# Each rule is (label, compiled-regex).  The *entire* match is redacted unless a
# single capturing group is present, in which case only that group is redacted
# (used for assignments so the key/context is preserved for readability).
# ---------------------------------------------------------------------------

_SECRET_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private_key_block",
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"
            r".*?-----END (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----",
            re.DOTALL,
        ),
    ),
    (
        "connection_string",
        re.compile(
            r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp|amqps)://"
            r"[^\s:@/]+:[^\s:@/]+@[^\s/]+",
            re.IGNORECASE,
        ),
    ),
    ("aws_access_key_id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("stripe_key", re.compile(r"\b[sr]k_(?:live|test)_[0-9A-Za-z]{16,}\b")),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b"),
    ),
    (
        "authorization_header",
        re.compile(
            r"(?i)\bAuthorization\b\s*[:=]\s*(?:Bearer|Basic|Token)\s+[A-Za-z0-9._\-+/=]+"
        ),
    ),
    (
        "bearer_token",
        re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-+/=]{16,}"),
    ),
)

# Dotenv / assignment style: KEY_WITH_SECRETY_NAME = value.  Only the value is
# redacted so the key name remains legible.
# The value group uses a negative lookahead so an already-inserted placeholder
# is not re-matched (which would make the residual guard recurse forever).
_SECRETY_KEY = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|API[_-]?KEY|ACCESS[_-]?KEY|"
    r"PRIVATE[_-]?KEY|CLIENT[_-]?SECRET|CREDENTIAL|AUTH[_-]?TOKEN|PASS)[A-Z0-9_]*)"
    r"\s*[:=]\s*(['\"]?)(?!\[REDACTED)([^\s'\"]{4,})(\2)"
)

# ---------------------------------------------------------------------------
# Protected-locality patterns: decimal-degree coordinate pairs.
# Examples: "-0.1807, -78.4678", "lat: 4.5709 lon: -74.2973".
# ---------------------------------------------------------------------------

_COORD_PAIR = re.compile(r"[-+]?\d{1,3}\.\d{3,}\s*[,;/ ]\s*[-+]?\d{1,3}\.\d{3,}")
_LABELED_COORD = re.compile(
    r"(?i)\b(?:lat(?:itude)?)\b\s*[:=]?\s*[-+]?\d{1,3}\.\d{3,}"
    r".{0,40}?\b(?:lon(?:gitude)?|lng)\b\s*[:=]?\s*[-+]?\d{1,3}\.\d{3,}"
)


@dataclass
class RedactionResult:
    """Outcome of redacting a text payload."""

    text: str
    status: str  # REDACTION_CLEAN | REDACTION_REDACTED
    secret_labels: tuple[str, ...] = ()
    secret_count: int = 0
    locality_count: int = 0

    @property
    def clean(self) -> bool:
        return self.status == REDACTION_CLEAN


def _redact_secrets(text: str) -> tuple[str, list[str]]:
    labels: list[str] = []
    out = text
    for label, pattern in _SECRET_RULES:

        def _sub(match: re.Match[str], _label: str = label) -> str:
            labels.append(_label)
            return SECRET_PLACEHOLDER.format(label=_label)

        out = pattern.sub(_sub, out)

    def _assign_sub(match: re.Match[str]) -> str:
        labels.append("assignment")
        key, quote, _value, _endquote = match.groups()
        return f"{key}={quote}{SECRET_PLACEHOLDER.format(label='assignment')}{quote}"

    out = _SECRETY_KEY.sub(_assign_sub, out)
    return out, labels


def _redact_locality(text: str, *, strict: bool) -> tuple[str, int]:
    count = 0

    def _count_and_replace(pattern: re.Pattern[str], value: str) -> str:
        nonlocal count

        def _sub(_match: re.Match[str]) -> str:
            nonlocal count
            count += 1
            return COORDINATE_PLACEHOLDER

        return pattern.sub(_sub, value)

    out = _count_and_replace(_LABELED_COORD, text)
    out = _count_and_replace(_COORD_PAIR, out)

    if count and strict:
        raise ProtectedLocalityError(
            "payload contains precise protected-locality coordinates"
        )
    return out, count


def redact_text(value: str | None, *, strict_locality: bool = False) -> RedactionResult:
    """Redact secrets and protected locality from a single text value.

    ``strict_locality=True`` rejects the write instead of reducing coordinates.
    """

    if value is None:
        return RedactionResult(text="", status=REDACTION_CLEAN)

    original = value
    redacted, secret_labels = _redact_secrets(value)
    redacted, locality_count = _redact_locality(redacted, strict=strict_locality)

    changed = redacted != original
    return RedactionResult(
        text=redacted,
        status=REDACTION_REDACTED if changed else REDACTION_CLEAN,
        secret_labels=tuple(sorted(set(secret_labels))),
        secret_count=len(secret_labels),
        locality_count=locality_count,
    )


@dataclass
class PayloadRedaction:
    """Aggregate redaction across a multi-field payload."""

    fields: dict[str, str] = field(default_factory=dict)
    status: str = REDACTION_CLEAN
    report: dict = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        return self.status == REDACTION_CLEAN


def redact_payload(
    fields: dict[str, str | None],
    *,
    strict_locality: bool = False,
) -> PayloadRedaction:
    """Redact a mapping of field name -> text.

    Returns the redacted fields plus an aggregate, value-free report suitable
    for persistence.  The report records per-field labels and counts only.
    """

    out_fields: dict[str, str] = {}
    per_field: dict[str, dict] = {}
    total_secrets = 0
    total_locality = 0
    all_labels: set[str] = set()

    for name, raw in fields.items():
        result = redact_text(raw, strict_locality=strict_locality)
        out_fields[name] = result.text
        if not result.clean:
            per_field[name] = {
                "secret_labels": list(result.secret_labels),
                "secret_count": result.secret_count,
                "locality_count": result.locality_count,
            }
        total_secrets += result.secret_count
        total_locality += result.locality_count
        all_labels.update(result.secret_labels)

    status = (
        REDACTION_REDACTED if (total_secrets or total_locality) else REDACTION_CLEAN
    )
    report = {
        "status": status,
        "secret_count": total_secrets,
        "locality_count": total_locality,
        "secret_labels": sorted(all_labels),
        "fields": per_field,
    }
    return PayloadRedaction(fields=out_fields, status=status, report=report)


def assert_no_residual_secret(*values: str) -> None:
    """Fail closed if any residual secret survives redaction.

    Used as a defence-in-depth check right before persistence.  Never includes
    the offending value in the raised error.
    """

    for value in values:
        if value is None:
            continue
        probe = redact_text(value)
        if probe.secret_count:
            raise ValueError(
                "residual secret detected after redaction; refusing to persist"
            )

"""The record that must survive a provider request, especially a denied one.

Issue #1502 is the reason this exists. Its receipt reads, in full:

    {"reason": "BLOCKED_MONTHLY_BUDGET_EXCEEDED", "provider_called": false,
     "state": "oc-blocked"}

Nothing there says what capability was wanted, why the repository's own
deterministic executors could not supply it, what it would have cost, or what
would become possible if it were granted. The request became unrecoverable at
the moment it was denied: the only way to recover the reasoning is to run the
routing again and hope it reaches the same conclusion.

A :class:`ProviderIntentRecord` is written **before** admission is asked for, so
a denial preserves the reasoning rather than discarding it.

Two things may never enter one of these records, because they are persisted to a
public issue: a credential, and a protected orchid locality.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

INTENT_SCHEMA = "oc.provider-intent.v1"

#: Substrings that make an environment variable name credential-shaped. Matching
#: is on the name, so a value is never inspected to decide whether to keep it.
_SECRET_NAME_PARTS = (
    "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "API_KEY", "APIKEY",
    "PRIVATE_KEY", "SESSION", "AUTH", "PAT", "COOKIE", "SIGNATURE", "WEBHOOK",
)

#: Value shapes that are credential-like wherever they appear. A record carrying
#: one of these is refused rather than scrubbed, because a scrubbed record hides
#: that something tried to put a credential in it.
_SECRET_VALUE_PATTERNS = (
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bsk-[A-Za-z0-9-]{20,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{20,}", re.IGNORECASE),
    re.compile(r"-----BEGIN[A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)

#: Coordinate and locality shapes. Orchid locality is protected by default, so
#: these are redacted on the way in rather than trusted not to appear.
_COORDINATE_PATTERNS = (
    # Decimal pairs: "-8.1234, -35.6789" and "lat=-8.1 lng=-35.6".
    re.compile(r"[-+]?\d{1,3}\.\d{3,}\s*[,;]\s*[-+]?\d{1,3}\.\d{3,}"),
    re.compile(r"\b(?:lat|latitude|lng|lon|long|longitude)\s*[=:]\s*[-+]?\d+(?:\.\d+)?",
               re.IGNORECASE),
    # Degrees-minutes-seconds: 8°07'30"S
    re.compile(r"\d{1,3}\s*°\s*\d{1,2}\s*['′]\s*[\d.]+\s*[\"″]?\s*[NSEW]",
               re.IGNORECASE),
    # Grid references and plus codes.
    re.compile(r"\b[0-9]{1,2}[A-Z]{3}\s?[0-9]{4,}\b"),
)

REDACTED = "[locality withheld]"


def redact(text: str) -> str:
    """Remove coordinate-shaped content from text bound for a provider payload.

    Deliberately blunt. A false positive costs a reviewer one confusing field; a
    false negative publishes a wild orchid's position. The repository's rule is
    that locality fails closed, so this errs toward withholding.
    """
    cleaned = str(text or "")
    for pattern in _COORDINATE_PATTERNS:
        cleaned = pattern.sub(REDACTED, cleaned)
    return cleaned


def _contains_secret(text: str) -> str | None:
    for pattern in _SECRET_VALUE_PATTERNS:
        if pattern.search(text):
            return pattern.pattern
    return None


def is_secret_name(name: str) -> bool:
    upper = str(name).upper()
    return any(part in upper for part in _SECRET_NAME_PARTS)


@dataclass(frozen=True)
class ProviderIntentRecord:
    """Why a provider was asked for, preserved whether or not it was granted.

    Every field is required reasoning rather than bookkeeping. ``blocking`` is
    the one that decides behaviour: an optional request must never stop the
    deterministic work around it, and a blocking one parks only the subtask that
    named it.
    """

    objective: str
    capability: str
    why_deterministic_insufficient: str
    provider: str
    alternatives_considered: list[str]
    expected_gain: str
    urgency: str
    blocking: bool
    deterministic_fallback: str
    affected_tasks: list[int]
    estimated_cost_usd: str | None = None
    schema: str = INTENT_SCHEMA
    _text_fields: tuple[str, ...] = field(
        default=(
            "objective",
            "why_deterministic_insufficient",
            "expected_gain",
            "deterministic_fallback",
        ),
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self.schema != INTENT_SCHEMA:
            raise ValueError(f"intent schema must be {INTENT_SCHEMA}")
        for name in (
            "objective",
            "capability",
            "why_deterministic_insufficient",
            "provider",
            "expected_gain",
            "urgency",
            "deterministic_fallback",
        ):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(
                    f"provider intent requires {name!r}: a denied request must stay "
                    "re-examinable, which it cannot be with this field empty"
                )
        if not self.alternatives_considered:
            raise ValueError(
                "provider intent requires alternatives_considered: recording what was "
                "ruled out is what lets a later pass resolve this without spending"
            )
        if self.urgency not in ("routine", "elevated", "critical"):
            raise ValueError("urgency must be routine, elevated or critical")

        # A credential must never reach a persisted record. Refuse rather than
        # scrub: scrubbing would hide that something tried.
        for name in ("objective", "why_deterministic_insufficient", "expected_gain",
                     "deterministic_fallback", "provider", "capability"):
            found = _contains_secret(str(getattr(self, name)))
            if found:
                raise ValueError(
                    f"provider intent field {name!r} contains credential-shaped content "
                    f"matching {found!r}; intent records are persisted to a public issue"
                )
        for alternative in self.alternatives_considered:
            found = _contains_secret(str(alternative))
            if found:
                raise ValueError(
                    "provider intent alternatives_considered contains credential-shaped "
                    f"content matching {found!r}"
                )

    @property
    def consolidation_key(self) -> str:
        """Requests equal under this key are the same question asked twice.

        Keyed on capability and objective rather than on the asking task, so two
        tasks that need the same thing consolidate into one request instead of
        buying the same answer twice.
        """
        material = json.dumps(
            {"capability": self.capability, "objective": redact(self.objective).strip().lower()},
            sort_keys=True,
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]

    def to_record(self) -> dict[str, Any]:
        """The persisted form, with locality redacted from every free-text field."""
        data = asdict(self)
        data.pop("_text_fields", None)
        for name in self._text_fields:
            data[name] = redact(str(data[name]))
        data["alternatives_considered"] = [redact(str(a)) for a in self.alternatives_considered]
        data["consolidation_key"] = self.consolidation_key
        return data

    def payload_for_provider(self) -> dict[str, Any]:
        """What may actually be sent outward.

        Narrower than the record: it carries the capability and the redacted
        objective, and nothing that identifies the submitter or the place.
        """
        return {
            "capability": self.capability,
            "objective": redact(self.objective),
            "expected_gain": redact(self.expected_gain),
        }

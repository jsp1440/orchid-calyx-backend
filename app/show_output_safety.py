"""Output-safety helpers for the show-management routes in ``app.routers.calyx_core``.

* ``redact_config_json`` -- integration ``config_json`` is stored as the owner sent it
  (so providers keep working) but every response masks secrets as ``"***"``. It
  prefers over-redaction: the owner list view never needs the secret itself.

  - Keys: a key is secret when its normalized form (NFKC, Cyrillic/Greek look-alikes
    and digit look-alikes mapped to Latin, casefolded, split into words) contains a
    secret word (``password``, ``passphrase``, ``secret``, ``token``, ``api_key``,
    ``private_key``, ``credential``, ``signature``, ``cookie``, ``bearer``,
    ``webhook``, ``jwt``, ``session``, ...), is a short secret word (``pass``,
    ``pwd``, ``auth``, ``key``, ``keys``, ``sid``, ``sig``, ``pin``, ``otp``, ...) or
    ends in ``key``/``keys``/``pass``/``pwd``. Header pair lists
    (``[["Authorization", "Bearer x"]]``) and name/value objects
    (``{"name": "Authorization", "value": "..."}``) are masked the same way.
  - Values, in any string under any key: JSON documents embedded as strings (and a
    double-encoded top-level string) are parsed and redacted recursively; URL
    passwords (including raw ``@``/``/`` inside the password), token usernames of
    http(s)/ws(s) URLs, secret query and fragment parameters, SAS ``sig=``, Slack,
    Discord, Telegram, Teams and Zapier webhook path secrets, ``Bearer``/``Basic``
    style authorization values, ``name=value``/``name: value`` pairs such as
    connection strings (``User ID=u;Password=p;``) and any run of 20 or more
    base64/hex characters that looks random.
  - Bounds: nesting deeper than ``MAX_REDACT_DEPTH`` (containers plus embedded JSON
    layers) is masked as a whole, so a deeply nested stored value can never raise
    ``RecursionError``. A stored value that is not valid JSON, is larger than
    ``MAX_CONFIG_JSON_CHARS`` or cannot be redacted is masked entirely (fail closed).
* ``ics_text_line`` -- builds one iCalendar content line with RFC 5545 TEXT escaping
  (backslash, ``;``, ``,``, every line-break form as ``\\n``) and 75-octet line
  folding, so a title, location or note can never start a new calendar line
  (``BEGIN:VEVENT`` injection), even for parsers that split on U+2028/U+2029/NEL.
* ``render_template_text`` -- replaces ``{name}`` placeholders from a flat context.
  It never calls ``str.format``: no format specs (``{x:>50000000}``), no attribute or
  index access (``{x.__class__}``, ``{x[0]}``). ``{{`` / ``}}`` are literal braces as
  before; any other brace text is left as written. Output size is bounded while it is
  built.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from typing import Any

from fastapi import HTTPException

REDACTED = "***"

# --- integration config redaction -------------------------------------------------------

MAX_CONFIG_JSON_CHARS = 64 * 1024
MAX_REDACT_DEPTH = 32

# Substrings of the compact normalized key (letters and digits only).
_SECRET_KEY_PARTS = (
    "password",
    "passwd",
    "passphrase",
    "secret",
    "token",
    "apikey",
    "authorization",
    "credential",
    "privatekey",
    "signature",
    "cookie",
    "bearer",
    "webhook",
    "jwt",
    "session",
    "otpseed",
)
# Whole words of the key (``smtp_pass``, ``db_pwd``, ``basic_auth``, ``otp_seed``).
_SECRET_KEY_WORDS = {
    "key",
    "keys",
    "pass",
    "pwd",
    "pw",
    "auth",
    "sid",
    "sig",
    "pin",
    "otp",
    "jwt",
    "session",
    "bearer",
    "cookie",
    "secret",
    "token",
    "credential",
    "credentials",
}
_SECRET_KEY_SUFFIXES = ("key", "keys", "pass", "pwd", "passwd")

# Latin look-alikes that NFKC does not fold (Cyrillic and Greek), plus digit
# substitutions, so ``раssword`` (Cyrillic ``р``/``а``) or ``passw0rd`` still match.
_CONFUSABLES = str.maketrans(
    {
        "а": "a", "в": "b", "е": "e", "ё": "e", "к": "k", "м": "m", "н": "h",
        "о": "o", "р": "p", "с": "c", "т": "t", "у": "y", "х": "x", "ѕ": "s",
        "і": "i", "ї": "i", "ј": "j", "ԁ": "d", "ԛ": "q", "ԝ": "w", "һ": "h",
        "ӏ": "l", "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H",
        "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X", "Ѕ": "S", "І": "I",
        "Ј": "J", "α": "a", "β": "b", "ε": "e", "ι": "i", "κ": "k", "ν": "v",
        "ο": "o", "ρ": "p", "τ": "t", "υ": "u", "χ": "x", "Α": "A", "Β": "B",
        "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N",
        "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
    }
)  # fmt: skip
_DIGIT_LOOKALIKES = str.maketrans(
    {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t"}
)

_URL_USERINFO_PASSWORD = re.compile(
    # Greedy password: it runs to the LAST ``@`` that is followed by a host, so a raw
    # ``@`` or ``/`` inside the password is still masked (over-redaction is preferred).
    r"(?P<prefix>(?<![A-Za-z0-9+.-])[A-Za-z][A-Za-z0-9+.-]{0,31}://[^\s/?#@:]{0,256}:)"
    r"\S{0,256}@"
    r"(?=[A-Za-z0-9.\-\[\]]+(?:[:/?#\"'<>\s]|$))"
)
_URL_USERINFO_USERNAME = re.compile(
    r"(?P<prefix>(?:https?|wss?)://)[^\s/?#@:]{1,256}@", re.IGNORECASE
)
_URL_QUERY_PARAM = re.compile(
    r"(?P<prefix>[?&;#](?P<name>[^=&;#?\s]{1,128})=)(?P<value>\{[^}]{0,1024}\}|[^&;#\s]*)"
)
_WEBHOOK_PATHS = re.compile(
    r"(?P<prefix>(?:hooks\.slack\.com/(?:services|workflows|triggers)/"
    r"|discord(?:app)?\.com/api/webhooks/"
    r"|\.webhook\.office\.com/webhookb2/"
    r"|hooks\.zapier\.com/hooks/catch/))"
    r"[^\s?#\"'<>]+",
    re.IGNORECASE,
)
_TELEGRAM_BOT_TOKEN = re.compile(
    r"(?P<prefix>api\.telegram\.org/(?:file/)?bot)[^/\s?#\"'<>]+", re.IGNORECASE
)
_AUTH_SCHEME_VALUE = re.compile(
    r"(?P<prefix>\b(?P<scheme>bearer|basic|digest|token|bot|ssws|sso-key|api-?key)\s+)"
    r"(?P<cred>[A-Za-z0-9\-._~+/=:]+)",
    re.IGNORECASE,
)
_NAME_VALUE_PAIR = re.compile(
    r"(?P<prefix>(?P<q>[\"']?)(?P<name>[A-Za-z_][A-Za-z0-9_.\- ]{0,40}?)(?P=q)\s*[:=]\s*)"
    r"(?P<value>\"(?:[^\"\\]|\\.){0,1024}(?:\"|$)|'[^']{0,1024}(?:'|$)|\{[^}]{0,1024}\}|[^;&,\s\"'#]+)"
)
_TOKEN_RUN = re.compile(r"[A-Za-z0-9_\-+=~]{20,}")
_PAIR_NAME_FIELDS = {"name", "key", "header", "field", "param", "parameter"}
_PAIR_VALUE_FIELDS = {"value", "val", "content", "data"}
_HEADER_NAME = re.compile(r"[A-Za-z][A-Za-z_.\- ]{0,63}")


def _key_words(key: object) -> list[str]:
    text = unicodedata.normalize("NFKC", str(key))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    text = text.translate(_CONFUSABLES)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)
    return [word for word in re.split(r"[^a-z0-9]+", text.casefold()) if word]


def _is_secret_key(key: object) -> bool:
    words = _key_words(key)
    compact = "".join(words)
    if not compact:
        return False
    for variant_words, variant in (
        (words, compact),
        (
            [word.translate(_DIGIT_LOOKALIKES) for word in words],
            compact.translate(_DIGIT_LOOKALIKES),
        ),
    ):
        if any(word in _SECRET_KEY_WORDS for word in variant_words):
            return True
        if variant.endswith(_SECRET_KEY_SUFFIXES):
            return True
        if any(part in variant for part in _SECRET_KEY_PARTS):
            return True
    return False


def _looks_random(run: str) -> bool:
    counts = Counter(run)
    entropy = -sum(n / len(run) * math.log2(n / len(run)) for n in counts.values())
    has_digit = any(ch.isdigit() for ch in run)
    has_letter = any(ch.isalpha() for ch in run)
    if has_digit and has_letter:
        return entropy >= 3.0
    upper = sum(ch.isupper() for ch in run[1:])
    lower = sum(ch.islower() for ch in run)
    return upper >= 3 and lower >= 3 and entropy >= 4.0


def _looks_like_credential(scheme: str, cred: str) -> bool:
    if scheme.lower() == "bearer":
        return True
    if len(cred) < 8:
        return False
    return any(ch.isdigit() or ch in "=+/" for ch in cred) or any(
        ch.isupper() for ch in cred[1:]
    )


def _redact_string(value: str, depth: int) -> Any:
    stripped = value.strip()
    if stripped[:1] in {"{", "[", '"'}:
        try:
            embedded = json.loads(stripped)
        except RecursionError:
            return REDACTED
        except ValueError:
            embedded = None
        else:
            if isinstance(embedded, (dict, list, str)):
                # Keep the encoding: the result is again a JSON document in a string.
                return json.dumps(
                    _redact_value(embedded, depth + 1), ensure_ascii=False
                )
    text = _URL_USERINFO_PASSWORD.sub(
        lambda m: f"{m.group('prefix')}{REDACTED}@", value
    )
    text = _URL_USERINFO_USERNAME.sub(lambda m: f"{m.group('prefix')}{REDACTED}@", text)
    text = _WEBHOOK_PATHS.sub(lambda m: f"{m.group('prefix')}{REDACTED}", text)
    text = _TELEGRAM_BOT_TOKEN.sub(lambda m: f"{m.group('prefix')}{REDACTED}", text)
    text = _URL_QUERY_PARAM.sub(
        lambda m: (
            f"{m.group('prefix')}{REDACTED}"
            if _is_secret_key(m.group("name"))
            else m.group(0)
        ),
        text,
    )
    text = _AUTH_SCHEME_VALUE.sub(
        lambda m: (
            f"{m.group('prefix')}{REDACTED}"
            if _looks_like_credential(m.group("scheme"), m.group("cred"))
            else m.group(0)
        ),
        text,
    )
    text = _NAME_VALUE_PAIR.sub(
        lambda m: (
            f"{m.group('prefix')}{REDACTED}"
            if _is_secret_key(m.group("name"))
            else m.group(0)
        ),
        text,
    )
    return _TOKEN_RUN.sub(
        lambda m: REDACTED if _looks_random(m.group(0)) else m.group(0), text
    )


def _redact_dict(value: dict, depth: int) -> dict:
    name_fields = [
        key
        for key, item in value.items()
        if isinstance(key, str)
        and key.casefold() in _PAIR_NAME_FIELDS
        and isinstance(item, str)
    ]
    value_fields = {
        key
        for key in value
        if isinstance(key, str) and key.casefold() in _PAIR_VALUE_FIELDS
    }
    pair_secret = bool(value_fields) and any(
        _is_secret_key(value[key]) for key in name_fields
    )
    out: dict = {}
    for key, item in value.items():
        if value_fields and key in name_fields and _HEADER_NAME.fullmatch(item):
            out[key] = item  # a header/field name such as "Authorization"
        elif (pair_secret and key in value_fields) or _is_secret_key(key):
            out[key] = REDACTED
        else:
            out[key] = _redact_value(item, depth + 1)
    return out


def _redact_list(value: list, depth: int) -> list:
    if len(value) == 2 and isinstance(value[0], str) and _is_secret_key(value[0]):
        return [value[0], REDACTED]  # ["Authorization", "Bearer ..."]
    return [_redact_value(item, depth + 1) for item in value]


def _redact_value(value: Any, depth: int = 0) -> Any:
    if depth > MAX_REDACT_DEPTH:
        return REDACTED
    if isinstance(value, dict):
        return _redact_dict(value, depth)
    if isinstance(value, list):
        return _redact_list(value, depth)
    if isinstance(value, str):
        return _redact_string(value, depth)
    return value


def redact_config_json(config_json: str | None) -> str | None:
    """Return ``config_json`` with secret values masked; the stored value is untouched.

    Never raises for a stored value: anything that cannot be parsed or redacted within
    the size and depth bounds is masked entirely.
    """
    if config_json is None or config_json.strip() == "":
        return config_json
    if len(config_json) > MAX_CONFIG_JSON_CHARS:
        return REDACTED
    try:
        parsed = json.loads(config_json)
        return json.dumps(_redact_value(parsed), ensure_ascii=False)
    except (TypeError, ValueError, RecursionError):
        return REDACTED


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

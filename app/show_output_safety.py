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
  - Also masked: the whole credential after an auth scheme (``Authorization: token
    x``), space-separated secrets (netrc ``password x``, ``--password x``), a token
    username in any URL scheme, and short header tuples such as
    ``["Authorization", "Bearer", "x"]``.
  - Header lists of any length: the whole value of a secret-named ``Name: value``
    header line (in a string or as a list element) and of a quoted ``curl -H``
    argument, and every value after a secret name in a flat name/value list
    (``["Accept", "a", "X-Api-Key", "k", ...]``). A list element that is a whole
    header line is never kept verbatim as a header-tuple name.
  - Command-line credentials: the password of ``curl -u``/``--user``/``--user=``/
    ``--proxy-user``/``-U`` ``user:password`` (quoted or not; the username stays),
    or the username when the password is empty (``-u sk_key:``). HTTP Digest
    ``response`` and ``cnonce`` values, whatever their length, once a ``Digest
    <param>=`` credential appears in the text.
  - Bounds: nesting deeper than ``MAX_REDACT_DEPTH`` (containers plus embedded JSON
    layers) is masked as a whole, so a deeply nested stored value can never raise
    ``RecursionError``. A stored value that is not valid JSON, is larger than
    ``MAX_CONFIG_JSON_CHARS`` or cannot be redacted is masked entirely (fail closed).
  - Time: linear in the input. A key longer than ``MAX_KEY_CHARS`` is treated as
    secret-shaped without being normalized, a free-text string longer than
    ``MAX_SCAN_CHARS`` is masked whole instead of scanned, and every pattern has
    bounded repetition. A worst-case 64 KiB config redacts in under 0.1 s on the
    reference sandbox; ``tests/test_show_output_safety_timing.py`` asserts a 1 s
    bound and near-linear scaling for each rule's adversarial input.
  - ``validate_config_json`` refuses (422) an oversized or too deeply nested value on
    create, before anything is committed.
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

import functools
import json
import math
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

REDACTED = "***"

# --- integration config redaction -------------------------------------------------------

MAX_CONFIG_JSON_CHARS = 64 * 1024
MAX_CONFIG_DEPTH = 32
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

# Linear-time bounds. A key longer than MAX_KEY_CHARS is never normalized: it is
# treated as secret-shaped and its value is masked. A string longer than
# MAX_SCAN_CHARS that is not an embedded JSON document is masked whole instead of
# being scanned. Every pattern below has bounded repetition around its anchors, starts
# only at a word/scheme boundary, and cannot fail after an unbounded scan, so the
# work per string is linear in its length (tests/test_show_output_safety_redaction.py
# asserts the bound and the scaling).
MAX_KEY_CHARS = 256
MAX_SCAN_CHARS = 4096

_AUTH_SCHEMES = (
    r"bearer|basic|digest|token|bot|ssws|sso-key|api-?key|negotiate|ntlm|hoba"
    r"|mutual|vapid|aws4-hmac-sha256|scram-sha-(?:1|256)"
)
_URL_SCHEME = r"(?<![A-Za-z0-9+.-])[A-Za-z][A-Za-z0-9+.-]{0,31}://"
_URL_USERINFO_PASSWORD = re.compile(
    # Greedy password: it runs to the LAST ``@`` (within 256 characters) that is
    # followed by a host character, so a raw ``@`` or ``/`` inside the password is
    # still masked (over-redaction is preferred).
    rf"(?P<prefix>{_URL_SCHEME}[^\s/?#@:]{{0,256}}:)\S{{0,256}}@(?=[A-Za-z0-9.\-\[\]])"
)
# A username alone (``https://ghp_x@host``, ``ftp://token@host``) in any scheme.
_URL_USERINFO_USERNAME = re.compile(rf"(?P<prefix>{_URL_SCHEME})[^\s/?#@:]{{1,256}}@")
_URL_QUERY_PARAM = re.compile(
    r"(?P<prefix>[?&;#](?P<name>[^=&;#?\s]{1,128})=)"
    r"(?P<value>\{[^}]{0,256}\}?|[^&;#\s]*)"
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
    rf"(?P<prefix>\b(?P<scheme>{_AUTH_SCHEMES})\s{{1,8}})(?P<cred>[^\s\"'<>,;]+)",
    re.IGNORECASE,
)
# A quoted value never has to find its closing quote (it is optional), so a match
# attempt cannot fail after a long scan.
_QUOTED_VALUE = r"\"(?:[^\"\\]|\\.){0,256}\"?|'[^']{0,256}'?|\{[^}]{0,256}\}?"
_NAME_VALUE_PAIR = re.compile(
    r"(?P<prefix>(?P<q>[\"']?)(?<![A-Za-z0-9_.\-])"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_.\- ]{0,40}?)(?P=q)\s{0,8}[:=]\s{0,8})"
    rf"(?P<value>(?i:(?:{_AUTH_SCHEMES})\s{{1,8}}[^\s;&,\"'#]+)|{_QUOTED_VALUE}"
    r"|[^;&,\s\"'#]+)"
)
# ``password hunter2`` (netrc), ``--password hunter2`` / ``-token x`` (command lines).
# Only the name and its whitespace are consumed per match, so every word is a
# candidate name; the value is matched separately (see ``_mask_spaced_values``).
_SPACED_NAME = re.compile(
    r"(?<![A-Za-z0-9_\-])-{0,2}(?P<name>[A-Za-z][A-Za-z0-9_\-]{0,40})\s{1,8}(?=\S)"
)
_SPACED_VALUE = re.compile(rf"{_QUOTED_VALUE}|[^\s\"']+")
# A value that runs to its closing quote, or (unquoted) to the next separator. Each
# branch always matches (the closing quote is optional), so a match attempt cannot fail
# after a long scan, and a match consumes what it scanned.
_QUOTED_TO_CLOSE = r"\"(?:[^\"\\\r\n]|\\.)*\"?|'[^'\r\n]*'?"
# One ``Name: value`` header line. A secret-named header masks the whole rest of the
# line, so a multi-word value (``X-Api-Key: two words``, ``Authorization: Digest
# ...``) never leaks its tail. Tried only at line starts, with a bounded name part.
_HEADER_LINE = re.compile(
    r"^(?P<prefix>[ \t]{0,8}(?P<name>[A-Za-z][A-Za-z0-9_.\-]{0,63})[ \t]{0,8}:)"
    r"(?P<value>[^\r\n]*)",
    re.MULTILINE,
)
# ``curl -H 'X-Api-Key: two words'``: a quoted header argument, to its closing quote.
_CLI_HEADER_PREFIX = (
    r"(?<![A-Za-z0-9_\-])(?P<prefix>(?:-H|--header)(?:\s{1,8}|=){quote}[ \t]{0,8}"
    r"(?P<name>[A-Za-z][A-Za-z0-9_.\-]{0,63})[ \t]{0,8}:)"
)
_CLI_HEADERS = (
    re.compile(
        _CLI_HEADER_PREFIX.replace("{quote}", '"') + r"(?P<value>(?:[^\"\\\r\n]|\\.)*)"
    ),
    re.compile(_CLI_HEADER_PREFIX.replace("{quote}", "'") + r"(?P<value>[^'\r\n]*)"),
)
# ``curl -u user:password``, ``--user user:pw``, ``--user=user:pw``, ``-ualice:pw``,
# ``-su user:pw``, ``--proxy-user`` / ``-U`` and quoted forms.
_CLI_USER = re.compile(
    r"(?<![A-Za-z0-9_\-])(?P<flag>--(?:proxy-)?user(?:\s{1,8}|=)"
    r"|-[A-Za-z]{0,6}[uU]\s{1,8}|-[uU]=?)"
    rf"(?P<value>{_QUOTED_TO_CLOSE}|[^\s\"']+)"
)
# HTTP Digest (RFC 7616): ``response`` and ``cnonce`` are masked whatever their length
# once a ``Digest <param>=`` credential appears; only the text from there on is scanned.
_DIGEST_SCHEME = re.compile(
    r"\bdigest\s{1,8}[A-Za-z_][A-Za-z0-9_\-]{0,40}\s{0,8}=", re.IGNORECASE
)
_DIGEST_SECRET_PARAM = re.compile(
    r"(?<![A-Za-z0-9_\-])(?P<prefix>(?:response|cnonce)\s{0,8}=\s{0,8})"
    rf"(?P<value>{_QUOTED_TO_CLOSE}|[^\s,;\"']+)",
    re.IGNORECASE,
)
_TOKEN_RUN = re.compile(r"[A-Za-z0-9_\-+=~]{20,}")
_CAMEL_LOWER_UPPER = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_CAMEL_UPPER_WORD = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
_PAIR_NAME_FIELDS = {"name", "key", "header", "field", "param", "parameter"}
_PAIR_VALUE_FIELDS = {"value", "val", "content", "data"}
_HEADER_NAME = re.compile(r"[A-Za-z][A-Za-z_.\- ]{0,63}")
# A bare header/field name as a list element: no ``:``/``=``, so a whole header line
# such as ``"Authorization: Bearer x"`` is never mistaken for a name and kept verbatim.
_LIST_HEADER_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.\- ]{0,63}")
_MAX_HEADER_TUPLE = 4
_MAX_HEADER_NAME_CHARS = 64


def _key_words(key: str) -> list[str]:
    text = unicodedata.normalize("NFKC", key)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    text = text.translate(_CONFUSABLES)
    text = _CAMEL_LOWER_UPPER.sub(" ", text)
    text = _CAMEL_UPPER_WORD.sub(" ", text)
    return [word for word in re.split(r"[^a-z0-9]+", text.casefold()) if word]


def _is_secret_key(key: object) -> bool:
    key = str(key)
    if len(key) > MAX_KEY_CHARS:
        return True  # secret-shaped; never normalized (bounded work per key)
    return _is_secret_key_name(key)


@functools.lru_cache(maxsize=4096)
def _is_secret_key_name(key: str) -> bool:
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


def _mask_if_secret_name(match: re.Match) -> str:
    if _is_secret_key(match.group("name")):
        return f"{match.group('prefix')}{REDACTED}"
    return match.group(0)


def _mask_spaced_values(text: str) -> str:
    """Mask the word after a secret-named word: ``password x``, ``--token x``."""
    parts: list[str] = []
    position = 0
    for match in _SPACED_NAME.finditer(text):
        if match.start() < position or not _is_secret_key(match.group("name")):
            continue
        value = _SPACED_VALUE.match(text, match.end())
        if value is None:
            continue
        parts.append(text[position : match.end()])
        parts.append(REDACTED)
        position = value.end()
    parts.append(text[position:])
    return "".join(parts)


def _mask_keeping_quotes(value: str) -> str:
    """``"x"`` -> ``"***"``, ``'x`` -> ``'***``, ``x`` -> ``***``."""
    quote = value[:1] if value[:1] in {'"', "'"} else ""
    closing = quote if quote and len(value) > 1 and value.endswith(quote) else ""
    return f"{quote}{REDACTED}{closing}"


def _mask_header_value(match: re.Match) -> str:
    if _is_secret_key(match.group("name")) and match.group("value").strip():
        return f"{match.group('prefix')} {REDACTED}"
    return match.group(0)


def _mask_cli_user(match: re.Match) -> str:
    """``-u user:pw`` -> ``-u user:***``; ``-u sk_key:`` (key as username) -> ``***:``."""
    value = match.group("value")
    quote = value[:1] if value[:1] in {'"', "'"} else ""
    inner = value[1:] if quote else value
    closing = ""
    if quote and inner.endswith(quote):
        inner, closing = inner[:-1], quote
    user, separator, password = inner.partition(":")
    if not separator:
        return match.group(0)  # no password on the command line
    masked = f"{user}:{REDACTED}" if password else f"{REDACTED}:"
    return f"{match.group('flag')}{quote}{masked}{closing}"


def _mask_digest_params(text: str) -> str:
    scheme = _DIGEST_SCHEME.search(text)
    if scheme is None:
        return text
    start = scheme.start()
    return text[:start] + _DIGEST_SECRET_PARAM.sub(
        lambda m: f"{m.group('prefix')}{_mask_keeping_quotes(m.group('value'))}",
        text[start:],
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
    if len(value) > MAX_SCAN_CHARS:
        return REDACTED  # long free text is masked whole rather than scanned
    text = _HEADER_LINE.sub(_mask_header_value, value)
    for pattern in _CLI_HEADERS:
        text = pattern.sub(_mask_header_value, text)
    text = _CLI_USER.sub(_mask_cli_user, text)
    text = _mask_digest_params(text)
    text = _URL_USERINFO_PASSWORD.sub(lambda m: f"{m.group('prefix')}{REDACTED}@", text)
    text = _URL_USERINFO_USERNAME.sub(lambda m: f"{m.group('prefix')}{REDACTED}@", text)
    text = _WEBHOOK_PATHS.sub(lambda m: f"{m.group('prefix')}{REDACTED}", text)
    text = _TELEGRAM_BOT_TOKEN.sub(lambda m: f"{m.group('prefix')}{REDACTED}", text)
    text = _URL_QUERY_PARAM.sub(_mask_if_secret_name, text)
    text = _AUTH_SCHEME_VALUE.sub(
        lambda m: (
            f"{m.group('prefix')}{REDACTED}"
            if _looks_like_credential(m.group("scheme"), m.group("cred"))
            else m.group(0)
        ),
        text,
    )
    text = _NAME_VALUE_PAIR.sub(_mask_if_secret_name, text)
    text = _mask_spaced_values(text)
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


def _is_list_header_name(item: object) -> bool:
    return (
        isinstance(item, str)
        and len(item) <= _MAX_HEADER_NAME_CHARS
        and _LIST_HEADER_NAME.fullmatch(item) is not None
    )


def _redact_list(value: list, depth: int) -> list:
    scalars = all(isinstance(item, (str, int, float)) for item in value)
    # ["Authorization", "Bearer x"] and ["Authorization", "Bearer", "x"]: a short
    # header tuple whose first element names a secret keeps only that name. A whole
    # header line (``"Authorization: Bearer x"``) is not a name: each element of such
    # a list is redacted on its own below, so the line's value is masked.
    if (
        2 <= len(value) <= _MAX_HEADER_TUPLE
        and scalars
        and _is_list_header_name(value[0])
        and _is_secret_key(value[0])
    ):
        return [_redact_value(value[0], depth + 1), *([REDACTED] * (len(value) - 1))]
    # A flat name/value header list of any length (Node ``rawHeaders``:
    # ["Accept", "a", "X-Api-Key", "k", ...]): every value after a secret name is
    # masked, wherever the name sits in the list.
    masked: set[int] = set()
    if (
        scalars
        and len(value) >= 2
        and len(value) % 2 == 0
        and all(_is_list_header_name(name) for name in value[0::2])
    ):
        masked = {i + 1 for i in range(0, len(value), 2) if _is_secret_key(value[i])}
    return [
        REDACTED if i in masked else _redact_value(item, depth + 1)
        for i, item in enumerate(value)
    ]


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


def json_nesting_depth(text: str) -> int:
    """Deepest ``[``/``{`` nesting of ``text``, scanned iteratively (never recurses).

    Brackets inside JSON strings are ignored; the text need not be valid JSON.
    """
    depth = deepest = 0
    in_string = escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "[{":
            depth += 1
            deepest = max(deepest, depth)
        elif ch in "]}":
            depth = max(depth - 1, 0)
    return deepest


def validate_config_json(config_json: str | None) -> None:
    """Refuse (422) an oversized or too deeply nested ``config_json`` before commit."""
    if config_json is None:
        return
    if len(config_json) > MAX_CONFIG_JSON_CHARS:
        raise _unprocessable(
            f"config_json exceeds {MAX_CONFIG_JSON_CHARS} characters",
            field="config_json",
        )
    if json_nesting_depth(config_json) > MAX_CONFIG_DEPTH:
        raise _unprocessable(
            f"config_json nests deeper than {MAX_CONFIG_DEPTH} levels",
            field="config_json",
        )


# --- iCalendar -------------------------------------------------------------------------

ICS_LINE_OCTETS = 75
ICS_MEDIA_TYPE = "text/calendar; charset=utf-8"

# Every character ``str.splitlines`` treats as a line boundary (CR, LF, VT, FF, FS,
# GS, RS, NEL, LINE SEPARATOR, PARAGRAPH SEPARATOR): a consumer that splits on any of
# them must never see a new content line, so each one is escaped as ``\n``.
_ICS_LINE_BREAKS = re.compile("\r\n|[\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]")


def _ics_allowed(ch: str) -> bool:
    """Not a C0 control (except TAB), DEL or a C1 control (RFC 5545 3.1, 3.3.11)."""
    code = ord(ch)
    if ch == "\t":
        return True
    return code >= 0x20 and not 0x7F <= code <= 0x9F


def ics_escape_text(value: object) -> str:
    """RFC 5545 section 3.3.11 TEXT escaping; every line-break form becomes ``\\n``."""
    text = str(value)
    text = text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    text = _ICS_LINE_BREAKS.sub("\\\\n", text)
    return "".join(ch for ch in text if _ics_allowed(ch))


def ics_utc_timestamp(moment: datetime) -> str:
    """RFC 5545 DATE-TIME in UTC form (``19970714T173000Z``), as DTSTAMP requires."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


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
    """For non-TEXT values (UID): remove every line break and control character."""
    text = _ICS_LINE_BREAKS.sub("", str(value))
    return "".join(ch for ch in text if ch != "\t" and _ics_allowed(ch))


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

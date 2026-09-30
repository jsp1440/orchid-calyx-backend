"""Member-shaped Matrix identification responses (explicit schemas, fail closed).

A member receives the identification output -- ranked candidate taxa, per-character
ranking explanations, the registry identity/checksum the ranking is bound to, and the
deterministic next observation -- and nothing else.

Every member payload is BUILT field by field: each field has an explicit shaper
(identifier, label, prose, number, enum, timestamp, matrix state). Nothing is copied
through wholesale, and no nested ``Any`` value is ever passed through:

* Matrix states (``candidate_state``, observation ``value``) must be a bool, a finite
  number, a short screened string token, a bounded list of those, or a numeric
  ``{"min", "max"}`` range. A range is rebuilt from ``min``/``max`` alone, so extra
  keys planted inside it (specimen, locality, coordinates) are dropped; any other
  shape becomes the explicit marker ``"withheld"``.
* Every string is length-bounded and screened for locality/specimen/submitter
  material (coordinate-shaped numbers, degree marks, ASCII minute/second marks,
  hemisphere-letter coordinates, UTM/MGRS grid references, Open Location Codes,
  locality/elevation/specimen/collector vocabulary and abbreviations in English,
  Spanish, Portuguese and French, e-mail marks). A string that fails the screen
  becomes ``"withheld"``.
* Elevation and altitude stay withheld in every form, including banded characters:
  the member view carries no per-taxon sensitivity signal, so whether a coarse band
  is safe is an owner/science decision. An explanation row whose character id is
  withheld also has its ``candidate_state`` withheld.
* No account identifier is returned (session ``actor``, observation ``recorded_by``,
  registry ``created_by``) -- sessions carry ``mine: true`` instead.
* Registry ``scope`` keeps taxonomic-rank keys only; candidate provenance keeps a
  short citation allow-list; character provenance, session ``metadata`` and
  observation ``source`` fields beyond ``kind``/``interface`` are never returned.

Owner and API-key callers keep receiving the unmodified runtime payloads.
"""

from __future__ import annotations

import math
import re
import unicodedata
import uuid
from collections.abc import Callable
from typing import Any

WITHHELD = "withheld"
MEMBER_SOURCE_KIND = "user_observation"

MAX_IDENTIFIER = 200
MAX_LABEL = 300
MAX_PROSE = 2000
MAX_STATE_TEXT = 120
MAX_STATE_ITEMS = 50

# Registry scope: taxonomic ranks only, screened string values.
SCOPE_KEYS = (
    "kingdom",
    "family",
    "subfamily",
    "tribe",
    "subtribe",
    "clade",
    "genus",
    "section",
    "species",
    "rank",
    "taxon",
)
# Candidate provenance: citation-style keys only, scalar values.
PROVENANCE_KEYS = (
    "source",
    "citation",
    "reference",
    "publication",
    "doi",
    "dataset",
    "license",
    "release",
    "authority",
)
CERTAINTIES = frozenset({"certain", "probable", "uncertain", "unknown"})
EXPLANATION_STATUSES = frozenset(
    {
        "matched",
        "partial",
        "conflict",
        "candidate_state_missing",
        "ignored_unknown_observation",
    }
)
VALUE_TYPES = frozenset({"categorical", "multi_state", "numeric", "numeric_range"})

# --- screens ---------------------------------------------------------------------

# Every pattern below is linear-time: each alternative uses bounded quantifiers only
# (no nested or unbounded repetition), so a search costs O(len(text)) whatever the
# input. tests/test_member_matrix_screen_broadened.py times each one on 64K inputs.
#
# "Unambiguous" words only: ``long.``, ``alt.``, ``site`` and ``station`` are ordinary
# words in morphology prose ("Spur 12 cm long.", "leaves alt.", "attachment site"),
# so they are withheld only in the shapes that carry a locality value.
_SENSITIVE_WORDS = re.compile(
    # locality / coordinate vocabulary (English, Spanish, Portuguese, French)
    r"latitud|longitud|localit|localidad|localiza[cç]|localisation|coordinat"
    r"|coordenad|coordonn|georef|\bgps|\blat\b|\blon\b|\blng\b|\bfundort"
    r"|\blong\.?\s?[:=]\s?[-+−]?\d|\blong\.\s{0,2}[-+−]?\d{1,3}(?:[.,]\d|\s?[EW]\b)"
    r"|\bwgs|\bdatum\b|\bnad\s?-?(?:27|83)\b|\bsirgas|\butm\b|\bmgrs\b|geohash"
    r"|plus\s?codes?\b|open\s{1,3}location\s{1,3}code|grid\s{0,2}ref"
    # elevation / altitude, including abbreviations and "metres above sea level"
    r"|elevation|elevaci|elevaç|elevacao|altitud|\belev\.|\belevs?\b"
    r"|\balt\.?\s{0,2}\(\s{0,2}(?:m|ft|metres?|meters?)\s{0,2}\)"
    # alt m / Alt [m] / alt<TAB>m / alt. ft: a unit, never a following word
    r"|\balt\.?\s{0,2}\[\s{0,2}(?:m|ft|metres?|meters?|feet)\s{0,2}\]"
    r"|\balt\.?\s{1,2}(?:m|ft|metres?|meters?|feet)\b(?![-'])"
    r"|\balt\.?\s{0,2}[:=]?\s{0,2}(?:ca?\.\s{0,2})?\d"
    r"|\bm\.?\s?s\.?\s?n\.?\s?m\b|\bs\.\s?n\.\s?m\b"
    r"|\bm\.?\s?a\.?\s?s\.?\s?l\b|\ba\.\s?s\.\s?l\b|\basl\b"
    r"|sea\s{1,3}level|nivel\s{1,3}del\s{1,3}mar|n[ií]vel\s{1,3}do\s{1,3}mar"
    r"|niveau\s{1,3}de\s{1,3}la\s{1,3}mer|au-dessus\s{1,3}du\s{1,3}niveau"
    r"|livello\s{1,3}del\s{1,3}mare|meeresspiegel"
    # German Höhe (altitude; also height -- withheld either way, fail closed)
    r"|(?<![a-zäöüß])h(?:ö|oe)he(?![a-zäöüß])"
    r"|h(?:ö|oe)henlage|(?:meeres|see)h(?:ö|oe)he"
    # Spanish altura means plant height too: withheld only with an elevation unit
    # (a three-digit-or-more metre value, s.n.m., "sobre el nivel") -- "altura de
    # la planta 30 cm" and "altura 1,5 m" stay readable.
    r"|\baltura\s{0,3}[:=]?\s{0,3}(?:(?:ca?\.|aprox\.?|de|entre)\s{0,3})?"
    r"(?:\d{3,5}|\d{1,2}[.,]\d{3})\s{0,3}"
    r"(?:[-–a]\s{0,3}(?:\d{3,5}|\d{1,2}[.,]\d{3})\s{0,3})?"
    r"(?:m\b|mts?\b|metros\b|msnm|s\.?\s?n\.?\s?m)"
    r"|\baltura\s{0,3}(?:s\.\s?n\.\s?m|sobre\s{1,3}el\s{1,3}nivel)"
    r"|\b(?:\d{3,5}|\d{1,2}[.,]\d{3})\s{0,3}(?:m|mts?|metros)\.?\s{0,3}de\s{1,3}altura\b"
    # specimen / collector / collecting-event vocabulary
    r"|specimen|voucher|collector|herbari|herbier|exsiccat|\bejemplar"
    r"|sp[eé]cimen|esp[eé]cime|\bleg\.|\bcoll\.|\bcollected\b"
    r"|\bcollecting\b|\bcollection\s{1,3}(?:site|number|no\.|data|place|point)"
    r"|colect|coletad|coletor|recolet"
    # site / station only in labelled or collecting-event shapes
    r"|\b(?:collection|collecting|type|study|sampling|field|survey|plot)\s{1,3}site\b"
    r"|\bsite\s{0,2}(?:[:=#]|no\.|number\b|\d)"
    r"|\b(?:field|collection|collecting|sampling|research|survey|weather)\s{1,3}station\b"
    r"|\bstation\s{0,2}(?:[:=#]|no\.|number\b|\d)"
    r"|@",
    re.IGNORECASE,
)
_OLC = "23456789CFGHJMPQRVWX"  # Open Location Code alphabet
_COORDINATE_SHAPES = re.compile(
    r"\d\.\d{3,}"  # coordinate-precision decimals
    r"|-?\d{1,3}\.\d+\s*[,;]\s*-?\d{1,3}\.\d+"  # decimal pairs
    # signed pairs: -18.91 47.52 / -18,91; 47,52 / –18.91, –47.52 (en dash, minus)
    r"|(?<![\d.,])[-−–]\d{1,3}[.,]\d{2,6}[\s,;/]{1,16}[-−–]?\d{1,3}[.,]\d{2,6}"
    r"|[°º˚′″]"  # degree / minute / second marks
    r"|\b\d{1,3}\s*deg(?:rees?)?\b"
    # degrees written out: 18 grados / 18 graus / 18 degrés (degres after folding)
    r"|\b\d{1,3}(?:[.,]\d{1,6})?\s{0,2}(?:grados?|graus?|degr[eé]s?)\b"
    # minutes written out then a hemisphere: 55 minutos S / 55 minutes sud
    r"|\b\d{1,2}(?:[.,]\d{1,4})?\s{0,2}(?:minutos?|minutes?)\b\s{0,3}"
    r"(?:\d{1,2}(?:[.,]\d{1,4})?\s{0,2}(?:segundos?|secondes?|seconds?)\b\s{0,3})?"
    r"(?:[NSEW]|norte|sur|sul|nord|sud|este|leste|est|oeste|ouest|north|south|east|west)\b"
    # degrees-minutes with an ASCII minute mark: 12 34' / 12 34.5'
    r"|\b\d{1,3}\s{1,2}\d{1,2}(?:[.,]\d{1,4})?\s{0,2}'"
    # minutes-seconds with ASCII marks: 34' 56" / 34'56'' / 34' 56.7"
    r"|\b\d{1,2}(?:[.,]\d{1,4})?\s{0,2}'\s{0,2}\d{1,2}(?:[.,]\d{1,4})?\s{0,2}(?:\"|'')"
    # 12d34m / 12d 34m 56s / 18d55mS / 18d55m12sS
    r"|\b\d{1,3}\s?d\s?\d{1,2}(?:[.,]\d{1,4})?\s?m"
    r"(?:\s?\d{1,2}(?:[.,]\d{1,4})?\s?s)?\s?[NSEW]?(?![a-z])"
    # Paired hemisphere coordinates are unambiguous even in lower case.
    r"|\b\d{1,3}(?:[.,]\d{2,6})?\s?[NS][\s,;/]{1,3}\d{1,3}(?:[.,]\d{2,6})?\s?[EW]\b"
    r"|\b[NS]\s?\d{1,3}(?:[.,]\d{2,6})?[\s,;/]{1,3}[EW]\s?\d{1,3}(?:[.,]\d{2,6})?\b"
    # Open Location Codes are case-insensitive, including shortened codes.
    rf"|\b[2-9C][2-9CFGHJMPQRV][{_OLC}0]{{6}}\+"
    rf"|\b[{_OLC}]{{4,6}}\+[{_OLC}]{{2,3}}\b",
    re.IGNORECASE,
)
# Lower-case forms kept apart from _COORDINATE_CASED: a lower-case hemisphere letter
# counts only after a decimal or a spaced degrees-minutes value (18.9s, 18 55 s), so
# "2n = 40" and "S 12.5 mm" stay readable; e/w need two decimals ("47.52e").
_COORDINATE_LOWER = re.compile(
    r"\b\d{1,3}(?:[.,]\d{1,6}|(?:[\s:]{1,2}\d{1,2}(?:[.,]\d{1,4})?){1,2})\s?[ns]\b"
    r"|\b\d{1,3}[.,]\d{2,6}\s?[ew]\b"
    # lower-case MGRS: 33twn1234567890 / 33t wn 12345 67890
    r"|\b\d{1,2}[c-hj-np-x]\s?[a-hj-np-z][a-hj-np-v]\s?\d{2,5}\s?\d{2,5}\b"
)
# Case-sensitive shapes: single hemisphere letters and UTM/MGRS grid references
# are upper case; matching them case-insensitively would catch "2n", "5 s", etc.
_COORDINATE_CASED = re.compile(
    # 12.34S / 12,345 N / 18 55 S / 18:55:30 S
    r"\b\d{1,3}(?:[.,]\d{1,6}|(?:[\s:]{1,2}\d{1,2}(?:[.,]\d{1,4})?){1,2})\s?[NSEW]\b"
    # N 12.34 / S18.91 (two or more decimals: "S 12.5" may be a sepal measurement)
    r"|\b[NS]\s?\d{1,3}[.,]\d{2,6}"
    # N 18 E 47 / S18.9, E47.5 (latitude then longitude)
    r"|\b[NS]\s?\d{1,3}(?:[.,]\d{1,6})?[\s,;/]{1,3}[EW]\s?\d{1,3}\b"
    # UTM: 17N 630084 4833438 / 17 N 630084mE 4833438mN
    r"|\b\d{1,2}\s?[C-HJ-NP-X]\s{1,3}\d{6}(?:\.\d{1,3})?\s?m?E?[\s,;]{1,3}\d{7}\b"
    # UTM easting/northing pair without zone: 630084 4833438 / 630084mE 4833438mN
    r"|\b\d{6}(?:\.\d{1,3})?\s?(?:mE)?[\s,;]{1,3}\d{7}(?:\.\d{1,3})?\s?(?:mN\b)?(?!\d)"
    # MGRS: 33TWN1234567890 / 33T WN 12345 67890
    r"|\b\d{1,2}[C-HJ-NP-X]\s?[A-HJ-NP-Z][A-HJ-NP-V]\s?\d{2,5}\s?\d{2,5}\b"
    # collector abbreviation "col." followed by an initial, a name or a number
    r"|\b[Cc]ol\.\s{0,2}(?:[A-Z]\.|[A-Z][a-z]{1,30}\b|\d)"
)
# Identifier-like strings (character ids such as ``min_elev``, ``hab_alt``, ``elevM``):
# ``\b`` does not split at ``_``, so text is re-tokenised at ``_``, ``-``, ``.``, ``/``,
# ``:``, camelCase and letter/digit boundaries before elevation tokens are looked up.
# The token ``alt`` counts only in a string with no whitespace (an id): in prose it is
# the botanical abbreviation for "alternate" ("leaves alt."), which stays readable.
_TOKEN_SPLIT = re.compile(
    r"[_\-./:]|(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])"
)
_ELEVATION_TOKENS = re.compile(r"\b(?:elevs?|m?asl|msnm|snm)\b", re.IGNORECASE)
# Run-together ids: elevm, altm, aslm, elevft, ELEVmax, ALTmin, ASLrange. A known
# unit/qualifier suffix is required, so "Altensteinia" and "Altmann" stay readable.
_ELEVATION_COMPOUND = re.compile(
    r"\b(?:elevs?|alts?|m?asl|msnm|snm)"
    r"(?:m|ft|feet|meters?|metres?|min|max|range|band|low|high|lo|hi|mean|avg|top)\b",
    re.IGNORECASE,
)
_ALT_TOKEN = re.compile(r"\balts?\b", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s")
_IDENTIFIER = re.compile(r"[\w.:/+()'&× -]{1,200}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?"
)
_DOI = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]{1,200}")


# A small confusables fold, screening only: Cyrillic and Greek letters that render
# like the Latin letters of the locality vocabulary, and apostrophe/quote look-alikes
# that stand in for the ASCII minute/second marks (the modifier apostrophe U+02BC).
_CONFUSABLES = str.maketrans(
    # Cyrillic lower case, Cyrillic upper case, Greek, then quote look-alikes ...
    "авеһіјкӏмнорԛгѕтухсԁԝёїАВЕНІЈКМОРСЅТХУԀԚԜαεικνορτυχΑΒΕΗΙΚΜΝΟΡΤΧΥΖʼʹ’‘ʻˈ`´ʺ“”˝",
    # ... and the ASCII each one is screened as.
    "abehijklmhopqrstyxcdwei"
    "ABEHIJKMOPCSTXYDQW"
    "aeikvoptuxABEHIKMNOPTXYZ" + "'" * 8 + '"' * 4,
)


def _screen_form(value: str) -> str:
    """NFKC with Unicode format (Cf) characters removed: zero-width, bidi, soft hyphen,
    then the confusables fold above.

    Used for screening only; the returned text is never altered. Full-width digits
    and letters fold to ASCII, a zero-width space can no longer split a pattern, and a
    Cyrillic ``а`` inside ``locаlity`` is screened as ``a``.
    """
    folded = unicodedata.normalize("NFKC", value)
    stripped = "".join(ch for ch in folded if unicodedata.category(ch) != "Cf")
    return stripped.translate(_CONFUSABLES)


def _strip_marks(value: str) -> str:
    """The screen form with combining marks removed (``élev_m`` -> ``elev_m``).

    Needed because ``\\b`` does not fall between ``é`` and ``l``: an accented id is
    otherwise one word that no ASCII elevation token can match.
    """
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def _screen_hit(text: str) -> bool:
    if (
        _SENSITIVE_WORDS.search(text)
        or _COORDINATE_SHAPES.search(text)
        or _COORDINATE_CASED.search(text)
        or _COORDINATE_LOWER.search(text)
    ):
        return True
    tokens = _TOKEN_SPLIT.sub(" ", text)
    if _ELEVATION_TOKENS.search(tokens) or _ELEVATION_COMPOUND.search(tokens):
        return True
    return _WHITESPACE.search(text) is None and _ALT_TOKEN.search(tokens) is not None


def screened_text(value: Any, max_len: int = MAX_LABEL) -> str | None:
    """A bounded string with no locality/specimen/submitter material, else WITHHELD.

    The text as given, its normalised screen form and that form without combining
    marks are all screened, so normalising can only add hits: a mark NFKC rewrites
    (``º`` becomes ``o``) is still seen raw, and ``höhe`` is still seen with its
    umlaut.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return WITHHELD
    if len(value) > max_len or _screen_hit(value):
        return WITHHELD
    # A form identical to one already screened cannot add a hit; skipping it keeps
    # plain ASCII text at one pass.
    form = _screen_form(value)
    if form != value and _screen_hit(form):
        return WITHHELD
    bare = _strip_marks(form)
    if bare != form and _screen_hit(bare):
        return WITHHELD
    return value


def _uuid(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return str(uuid.UUID(str(value))) if isinstance(value, str) else WITHHELD
    except ValueError:
        return WITHHELD


def _identifier(value: Any) -> str | None:
    text = screened_text(value, MAX_IDENTIFIER)
    if text in (None, WITHHELD):
        return text
    return text if _IDENTIFIER.fullmatch(text) else WITHHELD


def _label(value: Any) -> str | None:
    return screened_text(value, MAX_LABEL)


def _prose(value: Any) -> str | None:
    return screened_text(value, MAX_PROSE)


def _number(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def _enum(allowed: frozenset[str]) -> Callable[[Any], str | None]:
    def shape(value: Any) -> str | None:
        if value is None:
            return None
        return value if isinstance(value, str) and value in allowed else WITHHELD

    return shape


def _hex64(value: Any) -> str | None:
    return value if isinstance(value, str) and _HEX64.fullmatch(value) else None


def _timestamp(value: Any) -> str | None:
    return value if isinstance(value, str) and _TIMESTAMP.fullmatch(value) else None


def _state_scalar(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) else WITHHELD
    if isinstance(value, str):
        return screened_text(value, MAX_STATE_TEXT)
    return WITHHELD


def member_state(value: Any) -> Any:
    """Shape a Matrix state or observation value against the explicit state schema."""
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_STATE_ITEMS:
            return WITHHELD
        return [_state_scalar(item) for item in value]
    if isinstance(value, dict):
        low, high = _number(value.get("min")), _number(value.get("max"))
        if low is None or high is None:
            return WITHHELD
        return {"min": low, "max": high}
    return _state_scalar(value)


def _shape(record: Any, schema: dict[str, Callable[[Any], Any]]) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {}
    return {key: shaper(record[key]) for key, shaper in schema.items() if key in record}


def _text_map(value: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {key: _label(value[key]) for key in keys if isinstance(value.get(key), str)}


# --- registry ----------------------------------------------------------------------


def member_scope(scope: Any) -> dict[str, Any]:
    return _text_map(scope, SCOPE_KEYS)


def member_provenance(provenance: Any) -> dict[str, Any] | None:
    if provenance is None:
        return None
    if not isinstance(provenance, dict):
        return {}
    shaped: dict[str, Any] = {}
    for key in PROVENANCE_KEYS:
        value = provenance.get(key)
        if key == "doi" and isinstance(value, str) and _DOI.fullmatch(value):
            shaped[key] = value
        elif isinstance(value, str):
            shaped[key] = _label(value)
        elif isinstance(value, bool) or _number(value) is not None:
            shaped[key] = value
    return shaped


_REGISTRY_REF: dict[str, Callable[[Any], Any]] = {
    "registry_id": _identifier,
    "version": _identifier,
    "checksum_sha256": _hex64,
    "publication_state": _identifier,
}


def member_registry_ref(registry: Any) -> dict[str, Any]:
    ref = _shape(registry, _REGISTRY_REF)
    if isinstance(registry, dict) and "scope" in registry:
        ref["scope"] = member_scope(registry.get("scope"))
    return ref


_REGISTRY_SUMMARY: dict[str, Callable[[Any], Any]] = {
    **_REGISTRY_REF,
    "title": _label,
    "candidate_count": _number,
    "character_count": _number,
    "created_at": _timestamp,
}


def member_registry_summary(summary: dict[str, Any]) -> dict[str, Any]:
    item = _shape(summary, _REGISTRY_SUMMARY)
    item["scope"] = member_scope(summary.get("scope"))
    return item


def member_registry_listing(versions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "versions": [member_registry_summary(item) for item in versions],
        "read_only_listing": True,
    }


_CHARACTER: dict[str, Callable[[Any], Any]] = {
    "character": _identifier,
    "label": _label,
    "description": _prose,
    "value_type": _enum(VALUE_TYPES),
    "weight": _number,
    "concept_id": _uuid,
}


def member_registry_detail(record: dict[str, Any]) -> dict[str, Any]:
    """Character definitions for the guided flow; candidate states and provenance withheld."""
    characters = [
        _shape(item, _CHARACTER)
        for item in record.get("characters", [])
        if isinstance(item, dict)
    ]
    return {
        "schema_version": _identifier(record.get("schema_version")),
        "registry_id": _identifier(record.get("registry_id")),
        "version": _identifier(record.get("version")),
        "title": _label(record.get("title")),
        "scope": member_scope(record.get("scope")),
        "checksum_sha256": _hex64(record.get("checksum_sha256")),
        "publication_state": _identifier(record.get("publication_state")),
        "character_count": len(characters),
        "candidate_count": len(record.get("candidates", []) or []),
        "characters": characters,
        "member_view": True,
    }


# --- sessions and rankings ---------------------------------------------------------

_NEXT_OBSERVATION: dict[str, Callable[[Any], Any]] = {
    "character": _identifier,
    "label": _label,
    "description": _prose,
    "value_type": _enum(VALUE_TYPES),
    "concept_id": _uuid,
    "matrix_weight": _number,
    "candidate_coverage": _number,
    "distinct_state_count": _number,
    "candidate_count": _number,
    "selection_score": _number,
    "reason_code": _identifier,
    "explanation_boundary": _prose,
}


def member_next_observation(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return _shape(value, _NEXT_OBSERVATION)


_OBSERVATION: dict[str, Callable[[Any], Any]] = {
    "observation_id": _uuid,
    "revision": _number,
    "character": _identifier,
    "value": member_state,
    "certainty": _enum(CERTAINTIES),
    "weight": _number,
    "review_state": _identifier,
    "created_at": _timestamp,
}


def member_observation(item: dict[str, Any]) -> dict[str, Any]:
    observation = _shape(item, _OBSERVATION)
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    observation["source"] = {
        key: _identifier(source[key])
        for key in ("kind", "interface")
        if isinstance(source.get(key), str)
    }
    return observation


def member_session(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": _uuid(record.get("session_id")),
        "schema_version": _identifier(record.get("schema_version")),
        "registry": member_registry_ref(record.get("registry")),
        "observations": [
            member_observation(item)
            for item in record.get("observations", [])
            if isinstance(item, dict)
        ],
        "revision": _number(record.get("revision", 0)),
        "status": _identifier(record.get("status")),
        "created_at": _timestamp(record.get("created_at")),
        "updated_at": _timestamp(record.get("updated_at")),
        "next_observation": member_next_observation(record.get("next_observation")),
        "mine": True,
    }


_EXPLANATION: dict[str, Callable[[Any], Any]] = {
    "character": _identifier,
    "observation": member_state,
    "candidate_state": member_state,
    "certainty": _enum(CERTAINTIES),
    "effective_weight": _number,
    "similarity": _number,
    "contribution": _number,
    "status": _enum(EXPLANATION_STATUSES),
}
_CANDIDATE: dict[str, Callable[[Any], Any]] = {
    "taxon_id": _identifier,
    "scientific_name": _label,
    "score": _number,
    "coverage": _number,
    "compared_weight": _number,
    "possible_weight": _number,
}


def member_explanation(explanation: dict[str, Any]) -> dict[str, Any]:
    """One per-character explanation row.

    A character whose id is withheld or absent (for example ``elevation_m``) has its
    registry-authored ``candidate_state`` withheld: a numeric range such as
    ``{"min": 1520, "max": 1530}`` is not safe merely because its label is hidden.
    """
    shaped = _shape(explanation, _EXPLANATION)
    # Fail closed: a row with no character (missing key, None) is treated as withheld.
    if shaped.get("character") in (None, WITHHELD) and "candidate_state" in shaped:
        shaped["candidate_state"] = WITHHELD
    return shaped


def member_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    item = _shape(candidate, _CANDIDATE)
    item["explanations"] = [
        member_explanation(explanation)
        for explanation in candidate.get("explanations", []) or []
        if isinstance(explanation, dict)
    ]
    item["provenance"] = member_provenance(candidate.get("provenance"))
    return item


_REPORT: dict[str, Callable[[Any], Any]] = {
    "observation_count": _number,
    "compared_character_count": _number,
    "disclaimer": _prose,
    "session_id": _uuid,
    "revision": _number,
}


def member_report(report: dict[str, Any]) -> dict[str, Any]:
    shaped = _shape(report, _REPORT)
    shaped["candidates"] = [
        member_candidate(item)
        for item in report.get("candidates", []) or []
        if isinstance(item, dict)
    ]
    if "registry" in report:
        shaped["registry"] = member_registry_ref(report.get("registry"))
    return shaped


def member_evaluation(evaluation: dict[str, Any]) -> dict[str, Any]:
    """Member view of an evaluation; also the only input a member explanation sees."""
    return {
        "session": member_session(evaluation.get("session") or {}),
        "report": member_report(evaluation.get("report") or {}),
        "next_observation": member_next_observation(evaluation.get("next_observation")),
    }


# --- member inputs -----------------------------------------------------------------


def member_session_metadata(metadata: Any) -> dict[str, Any]:
    """Persist only the guided-flow markers a member client sends."""
    if not isinstance(metadata, dict):
        return {}
    return {
        key: metadata[key][:64]
        for key in ("input_mode", "client")
        if isinstance(metadata.get(key), str) and metadata[key]
    }


def member_observation_source(source: Any) -> dict[str, Any]:
    """Members record their own observations; the source kind is not caller-chosen."""
    interface = source.get("interface") if isinstance(source, dict) else None
    shaped: dict[str, Any] = {"kind": MEMBER_SOURCE_KIND}
    if isinstance(interface, str) and interface:
        shaped["interface"] = interface[:64]
    return shaped

"""Redaction applied to responses served to MEMBER principals only.

Owner and API-key responses are never touched: ``MemberRedactingRoute`` returns the
original response object unchanged unless the authenticated principal recorded by
``app.member_auth`` has ``role == "member"``.

The member view is built by construction from POSITIVE rules, not a blocklist:

* **Strings.** A string value reaches a member only if it is (a) a token that
  appears as a string literal in the candidate-knowledge / evidence-aggregation
  service source (enum values, states, version ids, schema words), (b) an ISO
  timestamp, a hex digest or an ``<id>:<version>`` pair, or (c) a field with its own
  exact positive pattern below. Every other string -- i.e. anything a caller typed --
  is replaced with ``null`` and flagged ``<field>_redacted: true``.
* **Extracted values** (``object_value`` / ``normalized_object`` / ``object_text``)
  are kept only for three kinds with an exact grammar: CONSERVATION_ASSERTION (IUCN
  vocabulary), TAXON (binomial / genus pattern) and MEASUREMENT (number + allowlisted
  unit, bounded so elevations cannot pass). TRAIT, MORPHOLOGY_TERM, MOLECULAR_MARKER
  and every other or unknown kind are always redacted: members see kinds, counts,
  statuses and structure, not extracted text. All kind fields present on a record
  must agree, otherwise the value is redacted.
* **Keys.** Dict keys must be identifier-shaped (``^[a-z_][a-z0-9_]*$``) or service
  literals; other keys are dropped and counted in ``keys_redacted``. Distribution
  maps keep only service-vocabulary keys and fold every other key into ``OTHER``.
* **Caller free-form structures** (contexts, metadata, qualifiers, policies, filters,
  lineage, taxon links, reviewer notes, error messages) are redacted whole.
"""

from __future__ import annotations

import ast
import builtins
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.candidate_knowledge.models import CandidateKind
from app.evidence_aggregation.models import CANDIDATE_TYPE_MAP

PRINCIPAL_STATE_ATTR = "oc_principal"

# --- service vocabulary (built from source code, never from data) --------------------

_APP_DIR = Path(__file__).resolve().parent
_VOCAB_MODULES = ("candidate_knowledge", "evidence_aggregation")
_TOKEN_SHAPE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}")


def _source_literals() -> frozenset[str]:
    """Space-free string literals in the two service packages (enum values, states...)."""
    tokens: set[str] = set()
    for module in _VOCAB_MODULES:
        for path in sorted((_APP_DIR / module).glob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and _TOKEN_SHAPE.fullmatch(node.value)
                ):
                    tokens.add(node.value)
    return frozenset(tokens)


KNOWN_KINDS = frozenset({kind.value for kind in CandidateKind} | set(CANDIDATE_TYPE_MAP))
# Built-in exception class names: the services record ``type(exc).__name__`` as a code.
_EXCEPTION_NAMES = frozenset(
    name for name, obj in vars(builtins).items() if isinstance(obj, type) and issubclass(obj, BaseException)
)
SERVICE_LITERALS = (
    _source_literals() | KNOWN_KINDS | {t.value for t in CANDIDATE_TYPE_MAP.values()} | _EXCEPTION_NAMES
)

_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(?:Z|[+-]\d{2}:\d{2})?)?", re.ASCII
)
_HEX_DIGEST = re.compile(r"[0-9a-f]{16,128}")
_ID_PAIR = re.compile(r"\d{1,12}:\d{1,12}", re.ASCII)
_IDENT_KEY = re.compile(r"[a-z_][a-z0-9_]*")


def _safe_string(value: str) -> bool:
    return (
        value in SERVICE_LITERALS
        or bool(_TIMESTAMP.fullmatch(value))
        or bool(_HEX_DIGEST.fullmatch(value))
        or bool(_ID_PAIR.fullmatch(value))
    )


def _safe_key(key: Any) -> bool:
    return isinstance(key, str) and (bool(_IDENT_KEY.fullmatch(key)) or key in SERVICE_LITERALS)


# --- extracted values: exact positive grammar per kind -------------------------------


def _normalized_kind(value: Any) -> str:
    return str(value).strip().upper()


IUCN_NAMES = frozenset(
    {
        "critically endangered",
        "endangered",
        "vulnerable",
        "near threatened",
        "least concern",
        "data deficient",
        "extinct",
        "extinct in the wild",
        "not evaluated",
    }
)
IUCN_CODES = frozenset({"CR", "EN", "VU", "NT", "LC", "DD", "EX", "EW", "NE"})
_TAXON_BINOMIAL = re.compile(r"[A-Z][a-z]+ [a-z][a-z-]+(?: (?:var\.|subsp\.|f\.) [a-z][a-z-]+)?")
_TAXON_GENUS = re.compile(r"[A-Z][a-z]+")
_MEASUREMENT = re.compile(r"(-?\d+(?:\.\d+)?) ?(mm|cm|m|µm|um|mg|g|kg|ml|l|%|°c)", re.IGNORECASE | re.ASCII)
_AGGREGATED_MEASUREMENT = re.compile(r"(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?):(length|temperature):base", re.ASCII)
# Upper bounds (absolute value) per allowlisted unit. Lengths are capped at 50 m so an
# elevation or a distance can never pass as a morphological measurement.
UNIT_BOUNDS = {
    "µm": 50_000_000.0,
    "um": 50_000_000.0,
    "mm": 50_000.0,
    "cm": 5_000.0,
    "m": 50.0,
    "mg": 1_000_000.0,
    "g": 100_000.0,
    "kg": 1_000.0,
    "ml": 100_000.0,
    "l": 1_000.0,
    "%": 100.0,
    "°c": 100.0,
}
BASE_DIMENSION_BOUNDS = {"length": 50_000.0, "temperature": 100.0}  # base units: mm, °C


def _measurement_ok(number: float, unit: str) -> bool:
    bound = UNIT_BOUNDS.get(unit.strip().lower())
    return bound is not None and abs(number) <= bound


def _conservation_ok(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    return text.lower() in IUCN_NAMES or text.upper() in IUCN_CODES


def _taxon_ok(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.isascii()
        and bool(_TAXON_BINOMIAL.fullmatch(value) or _TAXON_GENUS.fullmatch(value))
    )


def _measurement_value_ok(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    match = _MEASUREMENT.fullmatch(value)
    if match:
        return _measurement_ok(float(match.group(1)), match.group(2))
    aggregated = _AGGREGATED_MEASUREMENT.fullmatch(value)
    if aggregated:
        return abs(float(aggregated.group(1))) <= BASE_DIMENSION_BOUNDS[aggregated.group(2)]
    return False


# The only kinds whose extracted value a member may see, each with an exact grammar.
# TRAIT, MORPHOLOGY_TERM and MOLECULAR_MARKER are deliberately absent: their values are
# free text, so members see the kind, counts and status but never the text.
VALUE_VALIDATORS: dict[str, Callable[[Any], bool]] = {
    "CONSERVATION_ASSERTION": _conservation_ok,
    "TAXON": _taxon_ok,
    "MEASUREMENT": _measurement_value_ok,
}
_AGGREGATE_TO_KIND = {CANDIDATE_TYPE_MAP[kind].value: kind for kind in VALUE_VALIDATORS}
KIND_FIELDS = ("kind", "candidate_type")
VALUE_FIELDS = ("object_value", "normalized_object", "object_text")
UNIT_FIELDS = ("unit", "original_unit")
SUBJECT_FIELDS = ("normalized_subject", "subject")
# A subject is a genus or binomial with an optional infraspecific rank, ASCII only.
# The first letter may be lower-case because aggregation casefolds subjects.
_SUBJECT = re.compile(r"[A-Za-z][a-z]+(?: [a-z][a-z-]+(?: (?:var\.|subsp\.|f\.) [a-z][a-z-]+)?)?")


def _record_value_kind(record: dict[str, Any]) -> str | None:
    """The single allowlisted value kind that every kind field on the record agrees on."""
    kinds = {_normalized_kind(record[field]) for field in KIND_FIELDS if field in record}
    if "aggregate_type" in record:
        kinds.add(_AGGREGATE_TO_KIND.get(_normalized_kind(record["aggregate_type"]), "\0mismatch"))
    if len(kinds) != 1:
        return None
    (kind,) = kinds
    return kind if kind in VALUE_VALIDATORS else None


# --- structural rules -------------------------------------------------------------

# Caller-supplied free-form structures, redacted whole.
FREE_FORM_CONTEXT_KEYS = (
    "geographic_context",
    "temporal_context",
    "method_context",
    "population_context",
    "measurement_context",
    "metadata",
    "qualifiers",
)
ALWAYS_REDACTED_KEYS = (
    "rationale",
    "resolution_rationale",
    "reason",
    "dependence",
    "message",
    "source_name",
    "source_names",
    "match_candidates",
    "taxon_links",
    "cluster_key",
    "lineage_root",
    "shared_citation_lineage",
    "source_lineage",
    "citation_lineage",
    "document_hash",
    "source_document_id",
    "policies",
    "filters",
)
DISTRIBUTION_MAP_KEYS = frozenset(
    {"candidate_types", "source_classes", "review_states", "confidence_bands", "plan_counts", "counts"}
)
GEOGRAPHIC_SUMMARY_KEYS = frozenset({"contexts", "scopes", "universalized"})
TEMPORAL_SUMMARY_KEYS = frozenset(
    {"contexts", "earliest_evidence_date", "latest_evidence_date", "superseded_candidate_ids", "trend_conclusion"}
)
MEASUREMENT_AGGREGATE_NUMBERS = ("observed_min", "observed_max", "unweighted_mean")


def _is_distribution_map(key: str) -> bool:
    return key.endswith("_distribution") or key in DISTRIBUTION_MAP_KEYS


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _collapse_distribution(value: dict[str, Any]) -> dict[str, Any]:
    """Keep service-vocabulary keys; fold every other key's count into ``OTHER``."""
    kept: dict[str, Any] = {}
    other: float = 0
    folded = False
    for key, count in value.items():
        if not _is_number(count):
            folded = True
            continue
        if isinstance(key, str) and key in SERVICE_LITERALS and key != "OTHER":
            kept[key] = count
        else:
            other += count
            folded = True
    if folded:
        kept["OTHER"] = other
    return kept


# A summary block is recognised only by its exact service-generated key set, so a
# caller-supplied context dict that mimics the shape but adds a key is redacted whole.
def _is_geographic_summary(value: Any) -> bool:
    return isinstance(value, dict) and set(value.keys()) == GEOGRAPHIC_SUMMARY_KEYS


def _is_temporal_summary(value: Any) -> bool:
    return isinstance(value, dict) and set(value.keys()) == TEMPORAL_SUMMARY_KEYS


def _redact_field(out: dict[str, Any], key: str) -> None:
    out[key] = None
    out[f"{key}_redacted"] = True


def _strings_safe(value: Any) -> bool:
    """True when every string in a scalar/list value is service vocabulary."""
    if isinstance(value, str):
        return _safe_string(value)
    if isinstance(value, list):
        return all(_strings_safe(item) for item in value if not isinstance(item, dict))
    return True


def redact_member_locality(value: Any) -> Any:
    """Return a copy of a JSON-compatible payload reduced to the member view."""
    if isinstance(value, list):
        return [redact_member_locality(item) for item in value]
    if not isinstance(value, dict):
        return value

    out: dict[str, Any] = {}
    handled: set[str] = set()
    dropped = 0
    for key, item in value.items():
        if not _safe_key(key):
            dropped += 1
            continue
        if _is_distribution_map(key) and isinstance(item, dict):
            out[key] = _collapse_distribution(item)
            handled.add(key)
        else:
            out[key] = redact_member_locality(item)
    if dropped:
        out["keys_redacted"] = dropped
    present = {key for key in value if _safe_key(key)}

    if _is_geographic_summary(value):
        out["contexts"] = None
        out["scopes"] = None
        if not isinstance(value["universalized"], bool):
            out["universalized"] = None
        out["geographic_context_redacted"] = True
        handled |= GEOGRAPHIC_SUMMARY_KEYS
    elif _is_temporal_summary(value):
        out["contexts"] = None
        out["temporal_context_redacted"] = True
        handled.add("contexts")

    for key in FREE_FORM_CONTEXT_KEYS:
        if key in present and not _is_geographic_summary(value[key]) and not _is_temporal_summary(value[key]):
            _redact_field(out, key)
            handled.add(key)
    for key in ALWAYS_REDACTED_KEYS:
        if key in present:
            _redact_field(out, key)
            handled.add(key)

    # Kind fields: known kind vocabulary only.
    for key in KIND_FIELDS:
        if key in present:
            handled.add(key)
            if _normalized_kind(value[key]) not in KNOWN_KINDS:
                _redact_field(out, key)

    # Extracted values: exact grammar for the one kind all kind fields agree on.
    value_kind = _record_value_kind(value)
    validator = VALUE_VALIDATORS.get(value_kind) if value_kind else None
    for key in VALUE_FIELDS:
        if key in present:
            handled.add(key)
            if value[key] is not None and not (validator and validator(value[key])):
                _redact_field(out, key)

    # Numeric measurement values travel with a unit; both must pass the bounds.
    for number_key, unit_key in (("numeric_value", "unit"), ("original_value", "original_unit")):
        if number_key in present:
            handled.add(number_key)
            number, unit = value[number_key], value.get(unit_key)
            allowed = number_key == "original_value" or value_kind == "MEASUREMENT"
            if number is not None and not (
                allowed and _is_number(number) and isinstance(unit, str) and _measurement_ok(number, unit)
            ):
                _redact_field(out, number_key)
    for key in UNIT_FIELDS:
        if key in present:
            handled.add(key)
            unit = value[key]
            if unit is not None and not (isinstance(unit, str) and unit.strip().lower() in UNIT_BOUNDS):
                _redact_field(out, key)
    if "normalized_value" in present and "dimension" in present:
        handled.add("normalized_value")
        dimension = value["dimension"]
        bound = BASE_DIMENSION_BOUNDS.get(dimension) if isinstance(dimension, str) else None
        number = value["normalized_value"]
        if number is not None and not (bound is not None and _is_number(number) and abs(number) <= bound):
            _redact_field(out, "normalized_value")
    for key in MEASUREMENT_AGGREGATE_NUMBERS:
        if key in present:
            handled.add(key)
            number = value[key]
            if number is not None and not (_is_number(number) and abs(number) <= BASE_DIMENSION_BOUNDS["length"]):
                _redact_field(out, key)

    for key in SUBJECT_FIELDS:
        if key in present:
            handled.add(key)
            subject = value[key]
            if subject is not None and not (
                isinstance(subject, str) and subject.isascii() and _SUBJECT.fullmatch(subject)
            ):
                _redact_field(out, key)

    # Measurement summaries echo the caller's method context as "method".
    if "conversion_rule_version" in present and "method" in present:
        _redact_field(out, "method")
        handled.add("method")

    # Every remaining string must be service vocabulary, a timestamp, digest or id pair.
    for key in present - handled:
        if out.get(f"{key}_redacted"):
            continue
        if not _strings_safe(value[key]):
            _redact_field(out, key)
    return out


def _is_member(request: Request) -> bool:
    principal = getattr(request.state, PRINCIPAL_STATE_ATTR, None)
    return isinstance(principal, dict) and principal.get("role") == "member"


class MemberRedactingRoute(APIRoute):
    """APIRoute that redacts JSON responses for member principals only."""

    def get_route_handler(self) -> Callable[[Request], Any]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            response = await original(request)
            if not _is_member(request) or not isinstance(response, JSONResponse):
                return response
            redacted = redact_member_locality(json.loads(response.body))
            replacement = JSONResponse(
                content=redacted,
                status_code=response.status_code,
                background=response.background,
            )
            for key, header in response.headers.items():
                if key.lower() not in {"content-length", "content-type"}:
                    replacement.headers[key] = header
            return replacement

        return handler

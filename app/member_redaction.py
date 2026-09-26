"""Locality/prose redaction applied to responses served to MEMBER principals only.

Evidence-aggregation and candidate-knowledge read views pass through context that
callers supplied when submitting evidence: geographic context dicts, region/country
scopes, method/population/measurement context, free-form metadata and qualifiers,
extracted "occurs in/found at ..." locality values, and reviewer/tombstone prose.
Any of these can carry site or locality text, so a member never receives them.

Extracted values (``object_value`` / ``normalized_object`` / ``object_text``) are
redacted FAIL-CLOSED: they reach a member only for an allowlisted, structured,
non-locality kind AND a bounded value shape free of locality markers. Reviewer notes,
dependence decisions, tombstone reasons, free-text error messages and caller-supplied
source/taxon labels are redacted wherever they appear.

Owner and API-key responses are never touched: ``MemberRedactingRoute`` returns the
original response object unchanged unless the authenticated principal recorded by
``app.member_auth`` has ``role == "member"``.

Every redacted field is replaced with ``null`` and flagged ``<field>_redacted: true``
at the same level. Geographic/temporal summary blocks keep their shape and gain
``geographic_context_redacted`` / ``temporal_context_redacted`` inside the block.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

PRINCIPAL_STATE_ATTR = "oc_principal"

# Caller-supplied free-form dicts that may carry site/locality prose.
FREE_FORM_CONTEXT_KEYS = (
    "geographic_context",
    "temporal_context",
    "method_context",
    "population_context",
    "measurement_context",
    "metadata",
    "qualifiers",
)
_PLAIN_DATE = re.compile(r"\d{4}(-\d{2}){0,2}([T ][0-9:.]+(Z|[+-][0-9:]+)?)?")

# --- extracted value allowlist (fail closed) ----------------------------------------
#
# ``object_value`` / ``normalized_object`` / ``object_text`` reach a member only when
# the record's kind is in this allowlist AND the value passes the bounded shape and
# locality-marker screen below. Every kind not listed -- including unknown kinds and
# kinds the aggregation service silently folds into TRAIT_AGGREGATE -- is redacted.
# Kinds are compared after ``str(kind).strip().upper()``.
MEMBER_VALUE_KINDS = frozenset(
    {
        # Numeric morphological measurement (value + unit), e.g. "4.5 mm".
        "MEASUREMENT",
        # Categorical morphological character term, e.g. "saccate", "fimbriate".
        "MORPHOLOGY_TERM",
        # Categorical trait state, e.g. "hairy sepals"; free-text trait prose is
        # still caught by the shape/marker screen.
        "TRAIT",
        # Molecular marker/locus token, e.g. "ITS", "matK" (extractor bounds it to
        # [A-Za-z0-9_-]{2,40}); names a locus, never a place.
        "MOLECULAR_MARKER",
        # Controlled threat-category token, e.g. "endangered"; a category, not a site.
        "CONSERVATION_ASSERTION",
        # Taxon identity value: a scientific name.
        "TAXON",
    }
)
# Deliberately OUT: GEOGRAPHIC_OCCURRENCE, OCCURRENCE, SPECIMEN_REFERENCE, HABITAT,
# ENVIRONMENTAL_TOLERANCE (elevation/climate ranges), ECOLOGICAL_RELATIONSHIP,
# POLLINATOR_ASSOCIATION, MYCORRHIZAL_ASSOCIATION, CULTIVATION_OBSERVATION,
# PHENOLOGY_EVENT ("flowers in March near <ridge>"), CONSERVATION_ACTION,
# MECHANISTIC_RELATIONSHIP, MOLECULAR_RESULT, GLOSSARY, TAXON_NAME_USAGE and anything
# unknown.
# Aggregate types that correspond one-to-one to the allowed kinds (CANDIDATE_TYPE_MAP).
MEMBER_VALUE_AGGREGATE_TYPES = frozenset(
    {
        "MEASUREMENT_AGGREGATE",
        "MORPHOLOGICAL_CHARACTER_AGGREGATE",
        "TRAIT_AGGREGATE",
        "DNA_MARKER_AGGREGATE",
        "CONSERVATION_THREAT_AGGREGATE",
        "TAXON_IDENTITY_AGGREGATE",
    }
)
KIND_FIELDS = ("kind", "candidate_type")
VALUE_FIELDS = ("object_value", "normalized_object", "object_text")
UNIT_FIELDS = ("unit", "original_unit")
# Caller-supplied labels screened for locality markers (kept when clean).
SCREENED_LABEL_FIELDS = ("normalized_subject", "normalized_predicate", "predicate")

# Ported from the frontend morphology citation screen
# (orchid-continuum-frontend scripts/oc-morphology-source-lookup.mjs,
# CITATION_LOCALITY_MARKERS) plus explicit site/coordinate words.
LOCALITY_MARKERS = tuple(
    re.compile(pattern, flags)
    for pattern, flags in (
        (r"\d+\s?m\b", re.IGNORECASE),  # elevation / distance in metres
        (r"\d+\s?(?:ft|feet)\b", re.IGNORECASE),
        (r"\balt\.|\baltitude\b|\belev", re.IGNORECASE),
        (r"\bkm\b", re.IGNORECASE),
        (r"\bnear\b", re.IGNORECASE),
        (r"\bcoll\.|\bleg\.|\bcollect(?:ed|or|ing)\b|\bholotype\b|\bspecimens?\b", re.IGNORECASE),
        (r"\btype locality\b|\blocality\b|\blocalities\b", re.IGNORECASE),
        (r"[°º]|\bdeg(?:rees?)?\b", re.IGNORECASE),  # degrees
        (r"\d\s*['′’\"″]", 0),  # minutes / seconds
        (r"\b\d{1,3}(?:[\s.:]\d{1,2}){0,2}\s*[NSEW]\b", 0),  # 12 30 N, 77.15 W
        (r"-?\b\d{1,3}\.\d{3,}\b", 0),  # decimal coordinates
        (r"\bmi(?:les?)?\b", re.IGNORECASE),  # distance in miles
        (r"\b[NSEW]\s+of\b", 0),  # "15 mi E of ...", "S of ..."
        (r"\blat\b|\blong?\b", re.IGNORECASE),  # lat / lon / long
        (
            r"\b(?:ridges?|trails?|roads?|villages?|summits?|streams?|rivers?|valleys?|mountains?|hills?)\b",
            re.IGNORECASE,
        ),
        (
            (
                r"\b(?:sites?|gps|coordinates?|reserves?|parks?|stations?|lakes?|slopes?|cliffs?|peaks?|creeks?"
                r"|towns?|province|district|county|municipality|locations?|located|found at|occurs? (?:in|at))\b"
            ),
            re.IGNORECASE,
        ),
    )
)
_NUMBER_WITH_UNIT = re.compile(
    r"-?\d+(?:\.\d+)?(?:\s*(?:-|–|to)\s*-?\d+(?:\.\d+)?)?(?:\s*[A-Za-zµ%]{1,6})?"
)
_AGGREGATED_NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:e[+-]?\d+)?:[a-z_]+:base")
_CONTROLLED_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9 _/+-]{0,39}")
_UNIT_TOKEN = re.compile(r"[A-Za-zµ%/^0-9.-]{1,10}")


def _normalized_kind(value: Any) -> str:
    return str(value).strip().upper()


def _has_locality_marker(text: str) -> bool:
    return any(marker.search(text) for marker in LOCALITY_MARKERS)


def _value_shape_ok(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text or len(text) > 40 or _has_locality_marker(text):
        return False
    if _NUMBER_WITH_UNIT.fullmatch(text) or _AGGREGATED_NUMBER.fullmatch(text):
        return True
    return bool(_CONTROLLED_TOKEN.fullmatch(text)) and len(text.split()) <= 4


def _kind_allows_value(record: dict[str, Any]) -> bool:
    """True only when every kind/type field present is allowlisted, and one is present."""
    seen = False
    for field_name in KIND_FIELDS:
        if field_name in record:
            seen = True
            if _normalized_kind(record[field_name]) not in MEMBER_VALUE_KINDS:
                return False
    if "aggregate_type" in record:
        seen = True
        if _normalized_kind(record["aggregate_type"]) not in MEMBER_VALUE_AGGREGATE_TYPES:
            return False
    return seen


GEOGRAPHIC_SUMMARY_KEYS = frozenset({"contexts", "scopes", "universalized"})
TEMPORAL_SUMMARY_KEYS = frozenset(
    {"contexts", "earliest_evidence_date", "latest_evidence_date", "superseded_candidate_ids", "trend_conclusion"}
)
# Reviewer notes, tombstone reasons, dependence decisions, free-text error echoes
# (e.g. EXTRACTION_FAILURE ``str(exc)``) and caller-supplied source/taxon labels are
# redacted wherever they appear, at any depth.
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
)


# A summary block is recognised only by its exact service-generated key set, so a
# caller-supplied context dict that mimics the shape but adds a key (for example a
# "site") is treated as raw context and redacted whole.
def _is_geographic_summary(value: Any) -> bool:
    return isinstance(value, dict) and set(value.keys()) == GEOGRAPHIC_SUMMARY_KEYS


def _is_temporal_summary(value: Any) -> bool:
    return isinstance(value, dict) and set(value.keys()) == TEMPORAL_SUMMARY_KEYS


def _redact_field(out: dict[str, Any], key: str) -> None:
    out[key] = None
    out[f"{key}_redacted"] = True


def redact_member_locality(value: Any) -> Any:
    """Return a copy of a JSON-compatible payload with locality/prose fields removed."""
    if isinstance(value, list):
        return [redact_member_locality(item) for item in value]
    if not isinstance(value, dict):
        return value

    out = {key: redact_member_locality(item) for key, item in value.items()}

    if _is_geographic_summary(value):
        out["contexts"] = None
        out["scopes"] = None
        if not isinstance(value["universalized"], bool):
            out["universalized"] = None
        out["geographic_context_redacted"] = True
    elif _is_temporal_summary(value):
        out["contexts"] = None
        # Earliest/latest dates are echoed caller values: keep plain dates only.
        for key in ("earliest_evidence_date", "latest_evidence_date"):
            if value[key] is not None and not (isinstance(value[key], str) and _PLAIN_DATE.fullmatch(value[key])):
                out[key] = None
        out["temporal_context_redacted"] = True

    for key in FREE_FORM_CONTEXT_KEYS:
        if key in value and not _is_geographic_summary(value[key]) and not _is_temporal_summary(value[key]):
            _redact_field(out, key)

    for key in ALWAYS_REDACTED_KEYS:
        if key in value:
            _redact_field(out, key)

    # Extracted values: fail-closed allowlist by kind AND bounded value shape.
    kind_ok = _kind_allows_value(value)
    for key in VALUE_FIELDS:
        if key in value and value[key] is not None and not (kind_ok and _value_shape_ok(value[key])):
            _redact_field(out, key)
    for key in UNIT_FIELDS:
        unit = value.get(key)
        if unit is not None and not (
            isinstance(unit, str) and _UNIT_TOKEN.fullmatch(unit.strip()) and not _has_locality_marker(unit)
        ):
            _redact_field(out, key)
    for key in SCREENED_LABEL_FIELDS:
        label = value.get(key)
        if label is not None and not (isinstance(label, str) and len(label) <= 120 and not _has_locality_marker(label)):
            _redact_field(out, key)

    # Measurement summaries echo the caller's method context as "method".
    if "conversion_rule_version" in value and "method" in value:
        _redact_field(out, "method")
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

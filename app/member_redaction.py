"""Locality/prose redaction applied to responses served to MEMBER principals only.

Evidence-aggregation and candidate-knowledge read views pass through context that
callers supplied when submitting evidence: geographic context dicts, region/country
scopes, method/population/measurement context, free-form metadata and qualifiers,
extracted "occurs in/found at ..." locality values, and reviewer/tombstone prose.
Any of these can carry site or locality text, so a member never receives them.

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
GEOGRAPHIC_KINDS = frozenset({"GEOGRAPHIC_OCCURRENCE"})
GEOGRAPHIC_AGGREGATE_TYPES = frozenset({"GEOGRAPHIC_DISTRIBUTION_AGGREGATE"})


GEOGRAPHIC_SUMMARY_KEYS = frozenset({"contexts", "scopes", "universalized"})
TEMPORAL_SUMMARY_KEYS = frozenset(
    {"contexts", "earliest_evidence_date", "latest_evidence_date", "superseded_candidate_ids", "trend_conclusion"}
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

    # Extracted locality values: "occurs in / found at <prose>".
    kind = value.get("kind") or value.get("candidate_type")
    if kind in GEOGRAPHIC_KINDS and "object_value" in value:
        _redact_field(out, "object_value")
    if value.get("aggregate_type") in GEOGRAPHIC_AGGREGATE_TYPES and "normalized_object" in value:
        _redact_field(out, "normalized_object")

    # Aggregation cluster keys embed the region/country string at index 3.
    cluster_key = value.get("cluster_key")
    if isinstance(cluster_key, list) and len(cluster_key) > 3:
        out["cluster_key"] = [None if index == 3 else item for index, item in enumerate(out["cluster_key"])]
        out["cluster_key_redacted"] = True

    # Measurement summaries echo the caller's method context as "method".
    if "conversion_rule_version" in value and "method" in value:
        _redact_field(out, "method")

    # Reviewer and tombstone prose is caller-supplied free text.
    if "review_id" in value and "rationale" in value:
        _redact_field(out, "rationale")
    if "resolution_rationale" in value:
        _redact_field(out, "resolution_rationale")
    if "tombstone_id" in value and "reason" in value:
        _redact_field(out, "reason")
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

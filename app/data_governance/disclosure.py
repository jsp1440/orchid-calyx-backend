from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .models import DataPolicyDecision, DisclosureMode


class DataDisclosureDenied(PermissionError):
    """Raised when a governed payload is not authorized for disclosure."""


_EXACT_LOCATION_KEYS = frozenset(
    {
        "latitude",
        "longitude",
        "lat",
        "lon",
        "lng",
        "decimal_latitude",
        "decimal_longitude",
        "coordinates",
        "coordinate",
        "geometry",
        "geom",
        "geopoint",
        "locality",
        "exact_locality",
        "site",
        "site_name",
        "address",
        "landowner",
        "property_name",
        "location_notes",
    }
)

_GENERALIZED_LOCATION_KEYS = frozenset(
    {
        "country",
        "country_code",
        "state",
        "state_province",
        "province",
        "region",
    }
)

_IMAGE_KEYS = frozenset(
    {
        "image",
        "image_url",
        "image_uri",
        "media_url",
        "media_uri",
        "thumbnail_url",
        "original_url",
        "file_url",
        "storage_key",
        "object_key",
        "image_bytes",
        "media_bytes",
    }
)

_SAFE_PROVENANCE_KEYS = frozenset(
    {
        "source",
        "source_id",
        "source_org",
        "authority_org",
        "citation",
        "doi",
        "license",
        "attribution",
        "dataset",
        "dataset_id",
        "record_id",
        "taxon_id",
        "scientific_name",
    }
)


def apply_disclosure(
    decision: DataPolicyDecision,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the maximum structured payload permitted by a policy decision.

    This is deliberately conservative.  Raw records are never returned for
    `AGGREGATE_ONLY` or `EXISTENCE_ONLY` decisions because a generic application
    layer cannot safely manufacture an aggregate from a single protected record.
    Callers that need aggregate outputs must compute those inside the protected
    boundary and pass only the already-approved aggregate onward.
    """

    if not decision.allowed or decision.disclosure == DisclosureMode.DENY:
        raise DataDisclosureDenied("DATA_POLICY_DENIED")

    if decision.disclosure == DisclosureMode.EXISTENCE_ONLY:
        return _existence_envelope(decision, payload)

    if decision.disclosure == DisclosureMode.AGGREGATE_ONLY:
        return _aggregate_envelope(decision, payload)

    materialized = deepcopy(dict(payload))

    if decision.disclosure == DisclosureMode.GENERALIZED:
        materialized = _generalize_generic_payload(materialized)

    materialized = _apply_location_disclosure(
        materialized,
        decision.location_disclosure,
    )
    materialized = _apply_image_disclosure(
        materialized,
        decision.image_disclosure,
    )
    materialized["_governance"] = _governance_metadata(decision)
    return materialized


def _generalize_generic_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove fields commonly capable of identifying a protected site/person."""

    for key in list(payload):
        normalized = key.casefold()
        if normalized in _EXACT_LOCATION_KEYS or normalized in _IMAGE_KEYS:
            payload.pop(key, None)
    return payload


def _apply_location_disclosure(
    payload: dict[str, Any],
    mode: DisclosureMode,
) -> dict[str, Any]:
    location_present = _contains_any_key(payload, _EXACT_LOCATION_KEYS | _GENERALIZED_LOCATION_KEYS)

    if mode == DisclosureMode.FULL:
        return payload

    if mode == DisclosureMode.GENERALIZED:
        for key in list(payload):
            if key.casefold() in _EXACT_LOCATION_KEYS:
                payload.pop(key, None)
        if location_present:
            payload["location_disclosure"] = "GENERALIZED"
        return payload

    for key in list(payload):
        if key.casefold() in _EXACT_LOCATION_KEYS | _GENERALIZED_LOCATION_KEYS:
            payload.pop(key, None)

    if mode == DisclosureMode.EXISTENCE_ONLY and location_present:
        payload["location_present"] = True
    return payload


def _apply_image_disclosure(
    payload: dict[str, Any],
    mode: DisclosureMode,
) -> dict[str, Any]:
    image_present = _contains_any_key(payload, _IMAGE_KEYS)
    if mode == DisclosureMode.FULL:
        return payload

    for key in list(payload):
        if key.casefold() in _IMAGE_KEYS:
            payload.pop(key, None)

    if mode == DisclosureMode.EXISTENCE_ONLY and image_present:
        payload["image_present"] = True
    return payload


def _existence_envelope(
    decision: DataPolicyDecision,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "exists": True,
        "provenance": _safe_provenance(payload),
        "_governance": _governance_metadata(decision),
    }


def _aggregate_envelope(
    decision: DataPolicyDecision,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "raw_record_disclosed": False,
        "aggregate_required": True,
        "provenance": _safe_provenance(payload),
        "_governance": _governance_metadata(decision),
    }


def _safe_provenance(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(value)
        for key, value in payload.items()
        if key.casefold() in _SAFE_PROVENANCE_KEYS
    }


def _contains_any_key(payload: Mapping[str, Any], keys: frozenset[str]) -> bool:
    return any(key.casefold() in keys for key in payload)


def _governance_metadata(decision: DataPolicyDecision) -> dict[str, Any]:
    return {
        "policy_id": decision.policy_id,
        "authority_org": decision.authority_org,
        "attribution_required": decision.attribution_required,
        "disclosure": decision.disclosure.value,
        "location_disclosure": decision.location_disclosure.value,
        "image_disclosure": decision.image_disclosure.value,
        "reason_codes": list(decision.reason_codes),
    }

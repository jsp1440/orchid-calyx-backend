from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

APPLICABILITY_DIMENSIONS = (
    "taxa",
    "organs",
    "tissues",
    "cell_types",
    "developmental_stages",
    "environments",
    "treatments",
    "cultivation_context",
    "population_context",
)


def _norm_string(value: str) -> str:
    return " ".join(value.casefold().split())


def _norm_list(values: list[str]) -> list[str]:
    return sorted({_norm_string(value) for value in values if value.strip()})


def _norm_nested(value: Any) -> Any:
    """Canonicalize categorical applicability values and drop semantic emptiness."""
    if value is None:
        return None
    if isinstance(value, str):
        normalized = _norm_string(value)
        return normalized or None
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = _norm_string(str(raw_key))
            if not key:
                continue
            child = _norm_nested(raw_value)
            if child is None or child == {} or child == []:
                continue
            normalized[key] = child
        return dict(sorted(normalized.items()))
    if isinstance(value, (list, tuple, set)):
        normalized_items = []
        for item in value:
            child = _norm_nested(item)
            if child is None or child == {} or child == []:
                continue
            normalized_items.append(child)
        return sorted(
            normalized_items,
            key=lambda item: json.dumps(item, sort_keys=True, default=str),
        )
    return value


def _norm_mapping(value: dict[str, Any]) -> dict[str, Any]:
    normalized = _norm_nested(value)
    return normalized if isinstance(normalized, dict) else {}


class CausalScope(BaseModel):
    """Applicability bounds for a mechanistic claim.

    ``scope_class="global"`` is explicit and requires justification. Absence of
    applicability evidence is ``unknown`` and is never silently global.
    """

    model_config = ConfigDict(extra="forbid")

    scope_class: Literal["unknown", "bounded", "global"] = "unknown"
    taxa: list[str] = Field(default_factory=list)
    organs: list[str] = Field(default_factory=list)
    tissues: list[str] = Field(default_factory=list)
    cell_types: list[str] = Field(default_factory=list)
    developmental_stages: list[str] = Field(default_factory=list)
    environments: dict[str, Any] = Field(default_factory=dict)
    treatments: dict[str, Any] = Field(default_factory=dict)
    cultivation_context: dict[str, Any] = Field(default_factory=dict)
    population_context: dict[str, Any] = Field(default_factory=dict)
    applicability_notes: str | None = Field(default=None, max_length=4000)
    global_justification: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_scope(self) -> CausalScope:
        material_lists = (
            self.taxa,
            self.organs,
            self.tissues,
            self.cell_types,
            self.developmental_stages,
        )
        has_list_bounds = any(
            any(item.strip() for item in values) for values in material_lists
        )
        has_mapping_bounds = any(
            bool(_norm_mapping(value))
            for value in (
                self.environments,
                self.treatments,
                self.cultivation_context,
                self.population_context,
            )
        )
        has_bounds = has_list_bounds or has_mapping_bounds
        if self.scope_class == "bounded" and not has_bounds:
            raise ValueError("BOUNDED_CAUSAL_SCOPE_REQUIRES_APPLICABILITY_BOUNDS")
        if (
            self.scope_class == "global"
            and not (self.global_justification or "").strip()
        ):
            raise ValueError("GLOBAL_CAUSAL_SCOPE_REQUIRES_JUSTIFICATION")
        if self.scope_class == "global" and has_bounds:
            raise ValueError("GLOBAL_CAUSAL_SCOPE_CANNOT_DECLARE_LOCAL_BOUNDS")
        return self


def _normalized_dimensions(model: CausalScope) -> dict[str, Any]:
    return {
        "taxa": _norm_list(model.taxa),
        "organs": _norm_list(model.organs),
        "tissues": _norm_list(model.tissues),
        "cell_types": _norm_list(model.cell_types),
        "developmental_stages": _norm_list(model.developmental_stages),
        "environments": _norm_mapping(model.environments),
        "treatments": _norm_mapping(model.treatments),
        "cultivation_context": _norm_mapping(model.cultivation_context),
        "population_context": _norm_mapping(model.population_context),
    }


def _has_applicability_bounds(dimensions: dict[str, Any]) -> bool:
    return any(bool(dimensions[field]) for field in APPLICABILITY_DIMENSIONS)


def normalize_causal_scope(
    scope: CausalScope | dict[str, Any] | None,
) -> dict[str, Any]:
    if isinstance(scope, CausalScope):
        model = scope
    else:
        raw = dict(scope or {})
        raw.pop("scope_id", None)
        model = CausalScope.model_validate(raw)

    dimensions = _normalized_dimensions(model)
    has_bounds = _has_applicability_bounds(dimensions)
    if model.scope_class == "bounded" and not has_bounds:
        raise ValueError("BOUNDED_CAUSAL_SCOPE_REQUIRES_APPLICABILITY_BOUNDS")
    if model.scope_class == "global" and has_bounds:
        raise ValueError("GLOBAL_CAUSAL_SCOPE_CANNOT_DECLARE_LOCAL_BOUNDS")

    normalized = {
        "scope_class": model.scope_class,
        **dimensions,
        "applicability_notes": (model.applicability_notes or "").strip() or None,
        "global_justification": (model.global_justification or "").strip() or None,
    }
    normalized["scope_id"] = causal_scope_id(normalized)
    return normalized


def causal_scope_identity(
    scope: CausalScope | dict[str, Any] | None,
) -> dict[str, Any]:
    """Return only dimensions that define applicability identity."""
    normalized = normalize_causal_scope(scope)
    return {
        "scope_class": normalized["scope_class"],
        **{field: normalized[field] for field in APPLICABILITY_DIMENSIONS},
    }


def causal_scope_id(scope: dict[str, Any]) -> str:
    payload = {key: value for key, value in scope.items() if key != "scope_id"}
    stable = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(stable.encode()).hexdigest()


def publication_scope_blockers(scope: dict[str, Any] | None) -> list[str]:
    try:
        normalized = normalize_causal_scope(scope)
    except ValueError as exc:
        return [f"invalid_causal_scope:{exc}"]
    if normalized["scope_class"] == "unknown":
        return ["causal_scope_unknown"]
    return []

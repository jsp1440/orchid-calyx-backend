from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CausalScope(BaseModel):
    """Normalized applicability bounds for a mechanistic claim.

    `scope_class="global"` is deliberately explicit and requires a justification.
    Absence of evidence bounds is represented as `unknown`, never silently as global.
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
    def validate_scope(self) -> "CausalScope":
        bounded_fields = (
            self.taxa,
            self.organs,
            self.tissues,
            self.cell_types,
            self.developmental_stages,
            self.environments,
            self.treatments,
            self.cultivation_context,
            self.population_context,
        )
        has_bounds = any(bool(value) for value in bounded_fields)
        if self.scope_class == "bounded" and not has_bounds:
            raise ValueError("BOUNDED_CAUSAL_SCOPE_REQUIRES_APPLICABILITY_BOUNDS")
        if self.scope_class == "global" and not (self.global_justification or "").strip():
            raise ValueError("GLOBAL_CAUSAL_SCOPE_REQUIRES_JUSTIFICATION")
        if self.scope_class == "global" and has_bounds:
            raise ValueError("GLOBAL_CAUSAL_SCOPE_CANNOT_DECLARE_LOCAL_BOUNDS")
        return self


def _norm_string(value: str) -> str:
    return " ".join(value.casefold().split())


def _norm_list(values: list[str]) -> list[str]:
    return sorted({_norm_string(value) for value in values if value.strip()})


def _norm_mapping(value: dict[str, Any]) -> dict[str, Any]:
    # JSON roundtrip gives deterministic primitive structure while retaining numbers.
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def normalize_causal_scope(scope: CausalScope | dict[str, Any] | None) -> dict[str, Any]:
    model = scope if isinstance(scope, CausalScope) else CausalScope.model_validate(scope or {})
    normalized = {
        "scope_class": model.scope_class,
        "taxa": _norm_list(model.taxa),
        "organs": _norm_list(model.organs),
        "tissues": _norm_list(model.tissues),
        "cell_types": _norm_list(model.cell_types),
        "developmental_stages": _norm_list(model.developmental_stages),
        "environments": _norm_mapping(model.environments),
        "treatments": _norm_mapping(model.treatments),
        "cultivation_context": _norm_mapping(model.cultivation_context),
        "population_context": _norm_mapping(model.population_context),
        "applicability_notes": (model.applicability_notes or "").strip() or None,
        "global_justification": (model.global_justification or "").strip() or None,
    }
    normalized["scope_id"] = causal_scope_id(normalized)
    return normalized


def causal_scope_id(scope: dict[str, Any]) -> str:
    payload = {key: value for key, value in scope.items() if key != "scope_id"}
    stable = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def publication_scope_blockers(scope: dict[str, Any] | None) -> list[str]:
    try:
        normalized = normalize_causal_scope(scope)
    except ValueError as exc:
        return [f"invalid_causal_scope:{exc}"]
    if normalized["scope_class"] == "unknown":
        return ["causal_scope_unknown"]
    return []

"""Governed variable metadata and deterministic transformations for CALYX-617."""
from __future__ import annotations

import hashlib
import json
import math
from statistics import fmean, stdev
from typing import Any

VARIABLE_KINDS = {"numeric", "categorical", "ordinal", "datetime", "identifier", "boolean"}
VARIABLE_ROLES = {"outcome", "predictor", "covariate", "group", "identifier", "context"}
TRANSFORM_OPERATIONS = {"log10", "sqrt", "center", "zscore", "scale"}


def _stable(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(payload: Any) -> str:
    material = payload if isinstance(payload, str) else _stable(payload)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _finite(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise TypeError("TRANSFORM_BOOLEAN_NOT_NUMERIC")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("TRANSFORM_NON_NUMERIC_VALUE") from exc
    if not math.isfinite(number):
        raise ValueError("TRANSFORM_NON_FINITE_VALUE")
    return number


def normalize_variables(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ValueError("ANALYSIS_VARIABLES_REQUIRED")
    variables: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise TypeError("ANALYSIS_VARIABLE_INVALID")
        name = _text(raw.get("name"))
        kind = _text(raw.get("kind")).casefold()
        role = _text(raw.get("role")).casefold()
        unit = _text(raw.get("unit"))
        if not name or kind not in VARIABLE_KINDS or role not in VARIABLE_ROLES:
            raise ValueError("ANALYSIS_VARIABLE_FIELDS_INVALID")
        if name in seen:
            raise ValueError("ANALYSIS_VARIABLE_DUPLICATE")
        if kind == "numeric" and not unit:
            raise ValueError("ANALYSIS_NUMERIC_VARIABLE_UNIT_REQUIRED")
        if kind != "numeric" and not unit:
            unit = "1"
        seen.add(name)
        variables.append({"name": name, "kind": kind, "role": role, "unit": unit})
    return variables


def normalize_transformations(value: Any, variables: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    if value in (None, []):
        return [], list(variables)
    if not isinstance(value, list):
        raise TypeError("ANALYSIS_PLAN_TRANSFORMATIONS_INVALID")
    metadata = {item["name"]: dict(item) for item in variables}
    normalized: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, dict):
            raise TypeError("ANALYSIS_TRANSFORMATION_INVALID")
        operation = _text(raw.get("operation")).casefold()
        source = _text(raw.get("source"))
        target = _text(raw.get("target"))
        unit = _text(raw.get("unit"))
        if operation not in TRANSFORM_OPERATIONS or not source or not target or not unit:
            raise ValueError("ANALYSIS_TRANSFORMATION_FIELDS_INVALID")
        if source not in metadata:
            raise ValueError(f"ANALYSIS_TRANSFORMATION_SOURCE_NOT_FOUND:{source}")
        if metadata[source]["kind"] != "numeric":
            raise ValueError("ANALYSIS_TRANSFORMATION_SOURCE_NOT_NUMERIC")
        if target in metadata:
            raise ValueError(f"ANALYSIS_TRANSFORMATION_TARGET_EXISTS:{target}")
        item: dict[str, Any] = {
            "operation": operation,
            "source": source,
            "target": target,
            "unit": unit,
        }
        if operation == "scale":
            factor = _finite(raw.get("factor"))
            if factor is None or factor == 0:
                raise ValueError("ANALYSIS_TRANSFORMATION_SCALE_FACTOR_INVALID")
            item["factor"] = factor
        metadata[target] = {
            "name": target,
            "kind": "numeric",
            "role": _text(raw.get("role")).casefold() or metadata[source]["role"],
            "unit": unit,
        }
        if metadata[target]["role"] not in VARIABLE_ROLES:
            raise ValueError("ANALYSIS_TRANSFORMATION_ROLE_INVALID")
        normalized.append(item)
    return normalized, list(metadata.values())


def validate_method_variables(method: str, parameters: dict[str, Any], variables: list[dict[str, str]]) -> None:
    metadata = {item["name"]: item for item in variables}
    names = parameters["columns"] if method == "describe.v1" else [parameters["x"], parameters["y"]]
    missing = [name for name in names if name not in metadata]
    if missing:
        raise ValueError(f"ANALYSIS_METHOD_VARIABLE_NOT_DECLARED:{','.join(missing)}")
    non_numeric = [name for name in names if metadata[name]["kind"] != "numeric"]
    if non_numeric:
        raise ValueError(f"ANALYSIS_METHOD_VARIABLE_NOT_NUMERIC:{','.join(non_numeric)}")


def apply_transformations(rows: list[dict[str, Any]], transformations: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    transformed = [dict(row) for row in rows]
    receipts: list[dict[str, Any]] = []
    for transform in transformations:
        operation = transform["operation"]
        source = transform["source"]
        target = transform["target"]
        numeric = [_finite(row.get(source)) for row in transformed]
        complete = [value for value in numeric if value is not None]
        if not complete:
            raise ValueError(f"ANALYSIS_TRANSFORMATION_NO_COMPLETE_VALUES:{source}")
        context: dict[str, Any] = {}
        if operation == "center":
            context["mean"] = fmean(complete)
        elif operation == "zscore":
            if len(complete) < 2:
                raise ValueError("ANALYSIS_TRANSFORMATION_ZSCORE_REQUIRES_TWO_VALUES")
            scale = stdev(complete)
            if scale == 0:
                raise ValueError("ANALYSIS_TRANSFORMATION_ZSCORE_ZERO_VARIANCE")
            context.update({"mean": fmean(complete), "sample_sd": scale})
        elif operation == "scale":
            context["factor"] = transform["factor"]

        for row, value in zip(transformed, numeric):
            if value is None:
                row[target] = None
            elif operation == "log10":
                if value <= 0:
                    raise ValueError("ANALYSIS_TRANSFORMATION_LOG10_DOMAIN")
                row[target] = math.log10(value)
            elif operation == "sqrt":
                if value < 0:
                    raise ValueError("ANALYSIS_TRANSFORMATION_SQRT_DOMAIN")
                row[target] = math.sqrt(value)
            elif operation == "center":
                row[target] = value - context["mean"]
            elif operation == "zscore":
                row[target] = (value - context["mean"]) / context["sample_sd"]
            elif operation == "scale":
                row[target] = value * context["factor"]
            else:  # pragma: no cover - normalization is fail closed
                raise ValueError("ANALYSIS_TRANSFORMATION_UNSUPPORTED")

        receipts.append(
            {
                **transform,
                "complete_values": len(complete),
                "missing_values": len(numeric) - len(complete),
                "execution_context": context,
                "output_sha256": _sha([row.get(target) for row in transformed]),
            }
        )
    return transformed, receipts


def transformed_rows_sha256(rows: list[dict[str, Any]]) -> str:
    return _sha(rows)

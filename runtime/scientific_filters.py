"""Governed deterministic row filtering for CALYX-617.

Filters are explicit inclusion predicates. A row is retained only when every declared
predicate evaluates true. No arbitrary expressions, Python, SQL, regex, or implicit
outlier removal are accepted.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

FILTER_ENGINE_VERSION = "calyx-scientific-filters/v1"
FILTER_OPERATORS = {
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "in",
    "not_in",
    "is_missing",
    "not_missing",
}
NUMERIC_OPERATORS = {"gt", "gte", "lt", "lte"}
SET_OPERATORS = {"in", "not_in"}
MISSING_OPERATORS = {"is_missing", "not_missing"}


def _stable(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(payload: Any) -> str:
    return hashlib.sha256(_stable(payload).encode("utf-8")).hexdigest()


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _missing(value: Any) -> bool:
    return value is None or value == ""


def _finite(value: Any, error: str) -> float:
    if isinstance(value, bool):
        raise TypeError(error)
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(error) from exc
    if not math.isfinite(number):
        raise ValueError(error)
    return number


def _json_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def normalize_filters(value: Any, variables: list[dict[str, str]]) -> list[dict[str, Any]]:
    if value in (None, []):
        return []
    if not isinstance(value, list):
        raise TypeError("ANALYSIS_ROW_FILTERS_INVALID")
    metadata = {item["name"]: item for item in variables}
    normalized: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, dict):
            raise TypeError("ANALYSIS_ROW_FILTER_INVALID")
        variable = _text(raw.get("variable"))
        operator = _text(raw.get("operator")).casefold()
        reason_code = _text(raw.get("reason_code"))
        if not variable or variable not in metadata:
            raise ValueError(f"ANALYSIS_ROW_FILTER_VARIABLE_NOT_FOUND:{variable}")
        if operator not in FILTER_OPERATORS:
            raise ValueError("ANALYSIS_ROW_FILTER_OPERATOR_UNSUPPORTED")
        if not reason_code:
            raise ValueError("ANALYSIS_ROW_FILTER_REASON_REQUIRED")
        item: dict[str, Any] = {
            "variable": variable,
            "operator": operator,
            "reason_code": reason_code,
        }
        if operator in MISSING_OPERATORS:
            if "value" in raw or "values" in raw:
                raise ValueError("ANALYSIS_ROW_FILTER_MISSING_OPERATOR_VALUE_FORBIDDEN")
        elif operator in SET_OPERATORS:
            values = raw.get("values")
            if not isinstance(values, list) or not values or not all(_json_scalar(v) for v in values):
                raise ValueError("ANALYSIS_ROW_FILTER_VALUES_INVALID")
            item["values"] = values
        else:
            if "value" not in raw or not _json_scalar(raw.get("value")):
                raise ValueError("ANALYSIS_ROW_FILTER_VALUE_INVALID")
            item["value"] = raw.get("value")
        if operator in NUMERIC_OPERATORS:
            if metadata[variable]["kind"] != "numeric":
                raise ValueError("ANALYSIS_ROW_FILTER_NUMERIC_OPERATOR_REQUIRES_NUMERIC_VARIABLE")
            item["value"] = _finite(item["value"], "ANALYSIS_ROW_FILTER_NUMERIC_VALUE_INVALID")
        normalized.append(item)
    return normalized


def _matches(row: dict[str, Any], rule: dict[str, Any], kind: str) -> bool:
    value = row.get(rule["variable"])
    operator = rule["operator"]
    if operator == "is_missing":
        return _missing(value)
    if operator == "not_missing":
        return not _missing(value)
    if _missing(value):
        return False
    if operator in NUMERIC_OPERATORS:
        observed = _finite(value, "ANALYSIS_ROW_FILTER_NON_NUMERIC_OBSERVATION")
        expected = rule["value"]
        if operator == "gt":
            return observed > expected
        if operator == "gte":
            return observed >= expected
        if operator == "lt":
            return observed < expected
        return observed <= expected
    if operator in SET_OPERATORS:
        present = value in rule["values"]
        return present if operator == "in" else not present
    if kind == "numeric" and isinstance(rule.get("value"), (int, float)) and not isinstance(rule.get("value"), bool):
        observed: Any = _finite(value, "ANALYSIS_ROW_FILTER_NON_NUMERIC_OBSERVATION")
    else:
        observed = value
    return observed == rule.get("value") if operator == "eq" else observed != rule.get("value")


def apply_filters(
    rows: list[dict[str, Any]],
    filters: list[dict[str, Any]],
    variables: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply an AND-list of inclusion predicates and return retained rows plus receipt."""
    metadata = {item["name"]: item for item in variables}
    if not filters:
        receipt = {
            "engine_version": FILTER_ENGINE_VERSION,
            "predicate_mode": "all_declared_predicates_must_match",
            "rows_before": len(rows),
            "rows_after": len(rows),
            "rows_excluded": 0,
            "excluded_rows": [],
            "filters": [],
            "receipt_sha256": "",
        }
        receipt["receipt_sha256"] = _sha({k: v for k, v in receipt.items() if k != "receipt_sha256"})
        return [dict(row) for row in rows], receipt

    retained: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        failed: list[str] = []
        for rule in filters:
            kind = metadata[rule["variable"]]["kind"]
            if not _matches(row, rule, kind):
                failed.append(rule["reason_code"])
        if failed:
            excluded.append(
                {
                    "row_identity": f"row-{index + 1}-{_sha(row)[:12]}",
                    "source_position": index + 1,
                    "reason_codes": failed,
                }
            )
        else:
            retained.append(dict(row))
    if not retained:
        raise ValueError("ANALYSIS_ROW_FILTER_REMOVED_ALL_ROWS")
    receipt_core = {
        "engine_version": FILTER_ENGINE_VERSION,
        "predicate_mode": "all_declared_predicates_must_match",
        "rows_before": len(rows),
        "rows_after": len(retained),
        "rows_excluded": len(excluded),
        "excluded_rows": excluded,
        "filters": filters,
    }
    return retained, {**receipt_core, "receipt_sha256": _sha(receipt_core)}

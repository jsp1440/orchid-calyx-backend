"""Fail-closed validation of the cross-repository completion receipt contract.

The contract lives in ``contracts/oc-completion-receipt.v1.json`` and is mirrored
byte-for-byte in the frontend repository. A completion receipt is only evidence
when it names the exact implementation revision (40-hex commit SHA) and a digest
of the test evidence it summarises; a consumer must reject anything else rather
than treat it as "probably done".
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "contracts" / "oc-completion-receipt.v1.json"
RECEIPT_SCHEMA = "oc.completion-receipt.v1"

_TYPE_CHECKS: dict[str, Any] = {
    "string": lambda value: isinstance(value, str),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "number": lambda value: (
        isinstance(value, (int, float)) and not isinstance(value, bool)
    ),
    "object": lambda value: isinstance(value, (Mapping, list)),
}

_FRONTEND_REQUIRED_FIELDS = re.compile(r"requiredFields:\s*\[([^\]]*)\]")
_FRONTEND_QUOTED = re.compile(r"['\"]([A-Za-z0-9_]+)['\"]")
_FRONTEND_SHA_REGEX = re.compile(r"/\^\[a-f0-9\]\{40\}\$/")


class CompletionReceiptError(ValueError):
    """A receipt that must not be treated as completion evidence."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    if contract.get("schema") != RECEIPT_SCHEMA:
        raise CompletionReceiptError(
            "contract_schema_mismatch", str(contract.get("schema"))
        )
    return contract


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def evidence_digest(evidence: Any) -> str:
    """sha256 of the canonical JSON form of the evidence a receipt summarises."""
    return hashlib.sha256(canonical_json(evidence).encode("utf-8")).hexdigest()


def _check_field(name: str, spec: Mapping[str, Any], value: Any) -> None:
    type_name = spec.get("type", "string")
    if not _TYPE_CHECKS[type_name](value):
        raise CompletionReceiptError("wrong_type", f"{name} must be {type_name}")
    if "min_length" in spec and len(value) < spec["min_length"]:
        raise CompletionReceiptError("empty_field", name)
    if "pattern" in spec and re.fullmatch(spec["pattern"], value) is None:
        raise CompletionReceiptError(
            "pattern_mismatch", f"{name} must match {spec['pattern']}"
        )
    if "enum" in spec and value not in spec["enum"]:
        raise CompletionReceiptError("not_in_enum", f"{name}={value!r}")
    if "minimum" in spec and value < spec["minimum"]:
        raise CompletionReceiptError("below_minimum", f"{name}={value!r}")


def validate_completion_receipt(
    payload: Any, *, contract: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Return the validated receipt fields or raise ``CompletionReceiptError``.

    Nothing is inferred or defaulted: a missing or malformed field is a rejection,
    because the point of the receipt is to be checkable, not plausible.
    """
    contract = contract or load_contract()
    if not isinstance(payload, Mapping):
        raise CompletionReceiptError("receipt_not_object", type(payload).__name__)
    if payload.get("schema") != RECEIPT_SCHEMA:
        raise CompletionReceiptError(
            "receipt_schema_mismatch", str(payload.get("schema"))
        )

    fields: Mapping[str, Mapping[str, Any]] = contract["receipt_fields"]
    validated: dict[str, Any] = {"schema": RECEIPT_SCHEMA}
    for name, spec in fields.items():
        if name not in payload:
            if spec.get("required", False):
                raise CompletionReceiptError("missing_field", name)
            continue
        _check_field(name, spec, payload[name])
        validated[name] = payload[name]

    for name, rule in contract.get("conditional_fields", {}).items():
        states = rule.get("required_when_terminal_state_in", [])
        if validated.get("terminal_state") in states and name not in validated:
            raise CompletionReceiptError(
                "missing_field",
                f"{name} is required when terminal_state={validated['terminal_state']}",
            )
    return validated


def frontend_required_field_sets(source_text: str) -> list[list[str]]:
    """Every ``requiredFields: [...]`` literal in a frontend TypeScript source."""
    return [
        _FRONTEND_QUOTED.findall(match.group(1))
        for match in _FRONTEND_REQUIRED_FIELDS.finditer(source_text)
    ]


def frontend_declares_full_sha_pattern(source_text: str) -> bool:
    """Whether a frontend source validates SHAs with the contract's 40-hex pattern."""
    return _FRONTEND_SHA_REGEX.search(source_text) is not None

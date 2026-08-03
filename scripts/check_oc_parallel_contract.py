from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class ContractError(RuntimeError):
    pass


def load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data.get("contract_version"):
        raise ContractError(f"INVALID_CONTRACT_MANIFEST:{path}")
    return data


def compare_contracts(canonical: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if candidate.get("contract_version") != canonical.get("contract_version"):
        errors.append("contract_version_mismatch")

    canonical_routes = canonical.get("routes", {})
    candidate_routes = candidate.get("routes", {})
    for route, requirements in canonical_routes.items():
        if route not in candidate_routes:
            errors.append(f"missing_route:{route}")
            continue
        candidate_requirements = candidate_routes[route]
        for field_group in ("request_required", "response_required"):
            expected = set(requirements.get(field_group, []))
            actual = set(candidate_requirements.get(field_group, []))
            for missing in sorted(expected - actual):
                errors.append(f"missing_{field_group}:{route}:{missing}")

    canonical_enums = canonical.get("enums", {})
    candidate_enums = candidate.get("enums", {})
    for enum_name, expected_values in canonical_enums.items():
        actual_values = set(candidate_enums.get(enum_name, []))
        for missing in sorted(set(expected_values) - actual_values):
            errors.append(f"missing_enum_value:{enum_name}:{missing}")

    for key, expected in canonical.get("governance", {}).items():
        if candidate.get("governance", {}).get(key) != expected:
            errors.append(f"governance_mismatch:{key}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("canonical", type=Path)
    parser.add_argument("candidates", nargs="+", type=Path)
    args = parser.parse_args()

    canonical = load_manifest(args.canonical)
    failed = False
    for path in args.candidates:
        errors = compare_contracts(canonical, load_manifest(path))
        if errors:
            failed = True
            print(f"FAIL {path}: {errors}")
        else:
            print(f"PASS {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

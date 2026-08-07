"""Safely create, update, and inspect AZURE-001 external-gate attestations.

This module manages a single canonical attestation register. Updates are atomic,
deterministic, and fail closed. It never grants Azure, publication, database, or
production-migration authority.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from runtime.taxonomy_preflight import atomic_write_text
from runtime.taxonomy_preflight_attestations import (
    ATTESTATION_SCHEMA_VERSION,
    GATES,
    GateAttestation,
    load_and_evaluate,
)

REGISTER_VERSION = "0.1.0"


def _load_register(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": ATTESTATION_SCHEMA_VERSION, "attestations": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("attestation register must be a JSON object")
    if set(payload) - {"schema_version", "attestations"}:
        raise ValueError("attestation register contains unknown top-level fields")
    if payload.get("schema_version") != ATTESTATION_SCHEMA_VERSION:
        raise ValueError("unsupported attestation schema version")
    if not isinstance(payload.get("attestations"), list):
        raise ValueError("attestations must be a list")
    return payload


def _load_attestation(path: Path) -> GateAttestation:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("attestation input must be a JSON object")
    unknown = sorted(set(payload) - set(GateAttestation.__dataclass_fields__))
    if unknown:
        raise ValueError(f"unknown attestation fields: {', '.join(unknown)}")
    try:
        item = GateAttestation(**payload)
    except TypeError as exc:
        raise ValueError(f"invalid attestation structure: {exc}") from exc
    if item.gate not in GATES:
        raise ValueError(f"unknown readiness gate: {item.gate}")
    return item


def upsert(register_path: Path, attestation_path: Path, *, replace: bool = False) -> dict[str, Any]:
    register = _load_register(register_path)
    item = _load_attestation(attestation_path)
    existing = [entry for entry in register["attestations"] if isinstance(entry, dict) and entry.get("gate") == item.gate]
    if existing and not replace:
        raise ValueError(f"attestation already exists for gate {item.gate}; use --replace")
    retained = [entry for entry in register["attestations"] if not (isinstance(entry, dict) and entry.get("gate") == item.gate)]
    retained.append(asdict(item))
    retained.sort(key=lambda entry: str(entry.get("gate", "")))
    candidate = {"schema_version": ATTESTATION_SCHEMA_VERSION, "attestations": retained}

    # Validate through the canonical evaluator before replacing the register.
    temporary = register_path.with_name(f".{register_path.name}.candidate")
    atomic_write_text(temporary, json.dumps(candidate, indent=2, sort_keys=True) + "\n")
    try:
        evaluation = load_and_evaluate(temporary)
    finally:
        temporary.unlink(missing_ok=True)
    atomic_write_text(register_path, json.dumps(candidate, indent=2, sort_keys=True) + "\n")
    return {
        "register_version": REGISTER_VERSION,
        "gate": item.gate,
        "replaced": bool(existing),
        "register_valid": evaluation.valid,
        "evidence_digest": evaluation.evidence_digest,
        "gates": evaluation.gates,
        "reasons": list(evaluation.reasons),
        "azure_provisioning_authorized": False,
        "taxonomy_publication_authorized": False,
        "database_mutation_authorized": False,
        "production_migration_authorized": False,
    }


def initialize(path: Path) -> dict[str, Any]:
    if path.exists():
        raise ValueError(f"refusing to overwrite existing register: {path}")
    payload = {"schema_version": ATTESTATION_SCHEMA_VERSION, "attestations": []}
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return {"initialized": True, "path": str(path), "register_version": REGISTER_VERSION}


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage AZURE-001 external-gate attestations.")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("register", type=Path)
    add = sub.add_parser("upsert")
    add.add_argument("register", type=Path)
    add.add_argument("attestation", type=Path)
    add.add_argument("--replace", action="store_true")
    show = sub.add_parser("evaluate")
    show.add_argument("register", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "init":
            result = initialize(args.register)
        elif args.command == "upsert":
            result = upsert(args.register, args.attestation, replace=args.replace)
        else:
            result = load_and_evaluate(args.register).to_dict()
        print(json.dumps(result, indent=2, sort_keys=True))
        if args.command == "evaluate" and not result["valid"]:
            return 2
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True))
        return 4


if __name__ == "__main__":
    raise SystemExit(main())

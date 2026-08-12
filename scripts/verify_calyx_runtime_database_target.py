"""Fail-closed release guard for CALYX-CONV runtime/migration database identity.

This script performs no database connection and no mutation. It compares the
explicitly supplied deployed-runtime DSN with the guarded migration target DSN
and emits only non-secret fingerprints.
"""

from __future__ import annotations

import hashlib
import json
import os
from urllib.parse import unquote, urlparse


def _identity(database_url: str) -> tuple[str, int, str]:
    parsed = urlparse(database_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError("POSTGRESQL_DATABASE_URL_REQUIRED")
    if not parsed.hostname:
        raise ValueError("DATABASE_HOST_REQUIRED")
    database = unquote(parsed.path.lstrip("/"))
    if not database:
        raise ValueError("DATABASE_NAME_REQUIRED")
    return parsed.hostname.lower(), parsed.port or 5432, database


def _fingerprint(identity: tuple[str, int, str]) -> str:
    canonical = f"{identity[0]}:{identity[1]}/{identity[2]}".encode()
    return hashlib.sha256(canonical).hexdigest()


def verify_targets(runtime_url: str, migration_url: str) -> dict[str, object]:
    runtime_identity = _identity(runtime_url)
    migration_identity = _identity(migration_url)
    matches = runtime_identity == migration_identity
    return {
        "schema_version": "1.0",
        "runtime_database_fingerprint": _fingerprint(runtime_identity),
        "migration_database_fingerprint": _fingerprint(migration_identity),
        "database_target_match": matches,
        "database_mutation_attempted": False,
        "production_database_mutation_attempted": False,
    }


def main() -> int:
    runtime_url = os.environ.get("CALYX_RUNTIME_DATABASE_URL", "").strip()
    migration_url = os.environ.get("DATABASE_URL", "").strip()
    if not runtime_url:
        print(json.dumps({"status": "blocked", "blocker": "CALYX_RUNTIME_DATABASE_URL_REQUIRED"}))
        return 2
    if not migration_url:
        print(json.dumps({"status": "blocked", "blocker": "DATABASE_URL_REQUIRED"}))
        return 2
    try:
        result = verify_targets(runtime_url, migration_url)
    except ValueError as exc:
        print(json.dumps({"status": "blocked", "blocker": str(exc)}))
        return 2
    result["status"] = "passed" if result["database_target_match"] else "blocked"
    if not result["database_target_match"]:
        result["blocker"] = "CALYX_RUNTIME_MIGRATION_DATABASE_TARGET_MISMATCH"
    print(json.dumps(result, sort_keys=True))
    return 0 if result["database_target_match"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

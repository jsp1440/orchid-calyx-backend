from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

EXPECTED_CONTRACTS = {
    "state": "MISSION-CONTROL-TELEMETRY-001A",
    "harvesters": "MISSION-CONTROL-TELEMETRY-001B",
    "intelligence": "MISSION-CONTROL-TELEMETRY-001D",
    "frontend_contract": "MISSION-CONTROL-TELEMETRY-001E",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_release_readiness(
    state: dict[str, Any],
    harvesters: dict[str, Any],
    intelligence: dict[str, Any],
    frontend_contract: dict[str, Any],
) -> dict[str, Any]:
    checks = [
        {
            "id": "executive_state_contract",
            "status": "passed" if state.get("contract_version") == EXPECTED_CONTRACTS["state"] else "failed",
            "observed": state.get("contract_version") or "unavailable",
            "expected": EXPECTED_CONTRACTS["state"],
        },
        {
            "id": "harvester_contract",
            "status": "passed" if harvesters.get("contract_version") == EXPECTED_CONTRACTS["harvesters"] else "failed",
            "observed": harvesters.get("contract_version") or "unavailable",
            "expected": EXPECTED_CONTRACTS["harvesters"],
        },
        {
            "id": "dependency_intelligence_contract",
            "status": "passed" if intelligence.get("contract_version") == EXPECTED_CONTRACTS["intelligence"] else "failed",
            "observed": intelligence.get("contract_version") or "unavailable",
            "expected": EXPECTED_CONTRACTS["intelligence"],
        },
        {
            "id": "frontend_contract",
            "status": "passed" if frontend_contract.get("contract_version") == EXPECTED_CONTRACTS["frontend_contract"] else "failed",
            "observed": frontend_contract.get("contract_version") or "unavailable",
            "expected": EXPECTED_CONTRACTS["frontend_contract"],
        },
        {
            "id": "frontend_placeholder_replacement",
            "status": "passed" if frontend_contract.get("readiness", {}).get("direct_field_population_supported") is True else "failed",
            "observed": frontend_contract.get("readiness", {}).get("direct_field_population_supported", "unavailable"),
            "expected": True,
        },
        {
            "id": "governance_boundaries",
            "status": "passed" if all(
                payload.get("governance", {}).get("does_not_publish") is True
                and payload.get("governance", {}).get("does_not_grant_scientific_authority") is True
                for payload in (state, harvesters, intelligence, frontend_contract)
            ) else "failed",
            "observed": "preserved",
            "expected": "preserved",
        },
    ]
    failed = [check["id"] for check in checks if check["status"] != "passed"]
    degraded_sources = [
        item.get("source_id")
        for item in harvesters.get("harvesters", [])
        if item.get("status") in {"failed", "unavailable", "warning"}
    ]
    return {
        "contract_version": "MISSION-CONTROL-TELEMETRY-001F",
        "generated_at": _now(),
        "release_ready": not failed,
        "deployment_state": "ready" if not failed else "blocked",
        "blocking_checks": failed,
        "checks": checks,
        "runtime_advisories": {
            "degraded_sources": [source for source in degraded_sources if source],
            "degraded_source_count": len([source for source in degraded_sources if source]),
            "advisories_do_not_override_contract_readiness": True,
        },
        "smoke_test_manifest": {
            "health": "/health",
            "authenticated_endpoints": [
                "/api/executive/state",
                "/api/executive/harvesters",
                "/api/executive/intelligence",
                "/api/executive/frontend-contract",
                "/api/executive/release-readiness",
            ],
            "production_base_url_env": "MISSION_CONTROL_BASE_URL",
            "authentication_token_env": "MISSION_CONTROL_SMOKE_TOKEN",
        },
        "governance": {
            "read_only": True,
            "does_not_publish": True,
            "does_not_grant_scientific_authority": True,
            "production_smoke_tests_require_explicit_credentials": True,
        },
    }

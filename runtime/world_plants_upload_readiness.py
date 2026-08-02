"""Fail-closed readiness evaluation for World Plants uploads."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class UploadReadiness:
    ready: bool
    checks: tuple[ReadinessCheck, ...]
    instruction: str

    def as_dict(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "checks": [asdict(check) for check in self.checks],
            "instruction": self.instruction,
        }


def evaluate_upload_readiness(
    *,
    intake_root: Path,
    owner_auth_configured: bool,
    database_configured: bool,
    staging_schema_confirmed: bool,
    deployed_route_confirmed: bool,
    smoke_fixture_confirmed: bool,
) -> UploadReadiness:
    checks = (
        ReadinessCheck(
            "owner_authentication",
            owner_auth_configured,
            "Signed owner session or server API key is configured.",
        ),
        ReadinessCheck(
            "intake_storage",
            intake_root.exists() and intake_root.is_dir(),
            f"Immutable intake directory is available at {intake_root}.",
        ),
        ReadinessCheck(
            "database_connection",
            database_configured,
            "DATABASE_URL is configured for versioned staging.",
        ),
        ReadinessCheck(
            "staging_schema",
            staging_schema_confirmed,
            "World Plants release, row, photo, delta, and receipt tables are present.",
        ),
        ReadinessCheck(
            "deployed_routes",
            deployed_route_confirmed,
            "Mission Control taxonomy release routes are deployed and reachable.",
        ),
        ReadinessCheck(
            "smoke_fixture",
            smoke_fixture_confirmed,
            "A harmless Hassler-format fixture uploaded, persisted, and read back successfully.",
        ),
    )
    ready = all(check.passed for check in checks)
    instruction = (
        "Upload Michael Hassler's file through /mission-control?view=taxonomy-releases."
        if ready
        else "Do not upload the production taxonomy file yet; resolve every failed readiness check."
    )
    return UploadReadiness(ready=ready, checks=checks, instruction=instruction)

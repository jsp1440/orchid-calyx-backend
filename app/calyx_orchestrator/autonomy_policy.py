from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _bounded_int(
    environ: Mapping[str, str],
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = str(environ.get(key, default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{key}_INVALID") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{key}_OUT_OF_RANGE")
    return value


@dataclass(frozen=True, slots=True)
class ProgramAutonomyPolicy:
    enabled: bool = False
    owner: str = ""
    worker_id: str = "calyx-program-autonomy"
    poll_seconds: int = 60
    max_jobs_per_cycle: int = 10
    lease_seconds: int = 300
    timeout_seconds: int = 300

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> ProgramAutonomyPolicy:
        source = environ or os.environ
        policy = cls(
            enabled=_enabled(source.get("CALYX_PROGRAM_AUTONOMY_ENABLED")),
            owner=str(source.get("CALYX_PROGRAM_AUTONOMY_OWNER", "")).strip(),
            worker_id=str(source.get("CALYX_PROGRAM_AUTONOMY_WORKER_ID", "calyx-program-autonomy")).strip(),
            poll_seconds=_bounded_int(
                source,
                "CALYX_PROGRAM_AUTONOMY_POLL_SECONDS",
                default=60,
                minimum=15,
                maximum=3600,
            ),
            max_jobs_per_cycle=_bounded_int(
                source,
                "CALYX_PROGRAM_AUTONOMY_MAX_JOBS_PER_CYCLE",
                default=10,
                minimum=1,
                maximum=50,
            ),
            lease_seconds=_bounded_int(
                source,
                "CALYX_PROGRAM_AUTONOMY_LEASE_SECONDS",
                default=300,
                minimum=60,
                maximum=3600,
            ),
            timeout_seconds=_bounded_int(
                source,
                "CALYX_PROGRAM_AUTONOMY_TIMEOUT_SECONDS",
                default=300,
                minimum=1,
                maximum=3600,
            ),
        )
        return policy.validated()

    def validated(self) -> ProgramAutonomyPolicy:
        if self.enabled and not self.owner:
            raise ValueError("CALYX_PROGRAM_AUTONOMY_OWNER_REQUIRED")
        if not self.worker_id:
            raise ValueError("CALYX_PROGRAM_AUTONOMY_WORKER_ID_REQUIRED")
        return self

    def status(self) -> dict[str, object]:
        return {
            **asdict(self),
            "authorized": self.enabled and bool(self.owner),
            "mode": "deterministic_dry_run_only",
            "automatic_claim": self.enabled,
            "automatic_execution": self.enabled,
            "automatic_merge": False,
            "automatic_deployment": False,
            "automatic_publication": False,
            "external_execution": False,
            "credential_access": False,
            "production_knowledge_graph_mutation": False,
        }


def program_autonomy_status(environ: Mapping[str, str] | None = None) -> dict[str, object]:
    try:
        return {"valid": True, "error": None, **ProgramAutonomyPolicy.from_environ(environ).status()}
    except ValueError as exc:
        return {
            "valid": False,
            "error": str(exc),
            "enabled": False,
            "authorized": False,
            "mode": "deterministic_dry_run_only",
            "automatic_claim": False,
            "automatic_execution": False,
            "automatic_merge": False,
            "automatic_deployment": False,
            "automatic_publication": False,
            "external_execution": False,
            "credential_access": False,
            "production_knowledge_graph_mutation": False,
        }

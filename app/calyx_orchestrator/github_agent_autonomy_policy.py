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
class GitHubCodingAgentAutonomyPolicy:
    """Governs only whether an automatic loop is permitted to call
    `GitHubCodingAgentDispatchCycle.run_once()` on a timer - not whether that
    call is allowed to mutate anything. That remains entirely governed by the
    separate, already-existing `GitHubCodingRuntimePolicy` (enabled flag,
    owner allowlist, repository allowlist, exact execute confirmation
    string), which this policy never touches or bypasses.

    Deliberately narrower than `ProgramAutonomyPolicy`: this worker only ever
    calls `run_once(execute=False)` - preflight only. There is no
    "automatic_execute" mode here and no environment variable can produce
    one; a future, separately owner-authorized change would be required to
    add live automatic dispatch, not a flag on this class.
    """

    enabled: bool = False
    owner: str = ""
    poll_seconds: int = 300

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> GitHubCodingAgentAutonomyPolicy:
        source = os.environ if environ is None else environ
        policy = cls(
            enabled=_enabled(source.get("CALYX_GITHUB_CODING_AUTONOMY_ENABLED")),
            owner=str(source.get("CALYX_GITHUB_CODING_AUTONOMY_OWNER", "")).strip(),
            poll_seconds=_bounded_int(
                source,
                "CALYX_GITHUB_CODING_AUTONOMY_POLL_SECONDS",
                default=300,
                minimum=60,
                maximum=3600,
            ),
        )
        return policy.validated()

    def validated(self) -> GitHubCodingAgentAutonomyPolicy:
        if self.enabled and not self.owner:
            raise ValueError("CALYX_GITHUB_CODING_AUTONOMY_OWNER_REQUIRED")
        return self

    def status(self) -> dict[str, object]:
        return {
            **asdict(self),
            "authorized": self.enabled and bool(self.owner),
            "mode": "preflight_only_never_executes",
            "automatic_claim": self.enabled,
            "automatic_preflight": self.enabled,
            "automatic_execute": False,
            "automatic_merge": False,
            "automatic_deployment": False,
            "automatic_publication": False,
            "external_execution": False,
            "credential_access": False,
            "production_knowledge_graph_mutation": False,
        }


def github_coding_agent_autonomy_status(environ: Mapping[str, str] | None = None) -> dict[str, object]:
    try:
        return {"valid": True, "error": None, **GitHubCodingAgentAutonomyPolicy.from_environ(environ).status()}
    except ValueError as exc:
        return {
            "valid": False,
            "error": str(exc),
            "enabled": False,
            "authorized": False,
            "mode": "preflight_only_never_executes",
            "automatic_claim": False,
            "automatic_preflight": False,
            "automatic_execute": False,
            "automatic_merge": False,
            "automatic_deployment": False,
            "automatic_publication": False,
            "external_execution": False,
            "credential_access": False,
            "production_knowledge_graph_mutation": False,
        }

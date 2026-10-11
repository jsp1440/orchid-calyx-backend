"""Deployable entrypoint: the program-autonomy worker with the Brain pulse.

This is ``runtime.program_autonomy_worker.run_forever`` (the one scheduler)
with the Brain work-selection pulse as its per-cycle replenishment step,
durable cycle receipts and graceful SIGTERM. It adds no scheduler, queue or
executor. ``python -m runtime.program_autonomy_worker`` remains the worker
without Brain replenishment.

Configuration (all required unless marked optional):

* ``CALYX_PROGRAM_AUTONOMY_ENABLED`` / ``_OWNER`` / ``_*``: worker policy. The
  owner must be the identity that submits work; for API-key submission that
  is ``backend_api_key``.
* ``OC_BRAIN_CHECKOUT``: an Orchid-Continuum-Brain checkout providing
  ``calyx_brain.autonomy_pulse``.
* ``OC_BRAIN_WORK_MANIFEST``: reviewed work manifest (``{"work": [...]}``).
* ``OC_BRAIN_PULSE_LEDGER``: durable pulse ledger path.
* ``CALYX_BACKEND_BASE_URL`` / ``CALYX_API_KEY``: the Calyx API the pulse
  submits to (https, or http on loopback only).
* ``CALYX_PROGRAM_AUTONOMY_WORKSPACE`` (optional): read-only checkout the
  registered executors verify; defaults to the executors' own resolution.
* ``OC_BRAIN_PULSE_MAX_IN_FLIGHT`` (optional, default 1, 1-50).
* ``OC_BRAIN_PULSE_BACKOFF_BASE_SECONDS`` / ``_MAX_SECONDS`` (optional,
  default 30 / 900): bounded backoff after a backend failure.

Missing configuration exits 0 after printing one ``configuration_unavailable``
record. It never starts a partially configured loop.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.calyx_orchestrator.autonomy_policy import ProgramAutonomyPolicy
from app.calyx_orchestrator.executor_registry import AuthoritativeExecutorRegistry
from runtime.program_autonomy_worker import (
    Recorder,
    Replenisher,
    database_recorder,
    install_stop_handlers,
    run_forever,
)

REQUIRED = (
    "OC_BRAIN_CHECKOUT",
    "OC_BRAIN_WORK_MANIFEST",
    "OC_BRAIN_PULSE_LEDGER",
    "CALYX_BACKEND_BASE_URL",
    "CALYX_API_KEY",
)


@dataclass(frozen=True)
class BrainWorker:
    policy: ProgramAutonomyPolicy
    replenish: Replenisher
    registry: AuthoritativeExecutorRegistry
    recorder: Recorder


def configuration_problems(env: Mapping[str, str]) -> list[str]:
    problems = [f"{key}_UNSET" for key in REQUIRED if not str(env.get(key, "")).strip()]
    checkout = str(env.get("OC_BRAIN_CHECKOUT", "")).strip()
    if (
        checkout
        and not (Path(checkout) / "calyx_brain" / "autonomy_pulse.py").is_file()
    ):
        problems.append("OC_BRAIN_CHECKOUT_MISSING_AUTONOMY_PULSE")
    manifest = str(env.get("OC_BRAIN_WORK_MANIFEST", "")).strip()
    if manifest and not Path(manifest).is_file():
        problems.append("OC_BRAIN_WORK_MANIFEST_NOT_FOUND")
    return problems


def build_worker(env: Mapping[str, str]) -> BrainWorker:
    """Wire policy, Brain pulse, executor registry and receipt recorder."""
    problems = configuration_problems(env)
    if problems:
        raise ValueError(",".join(problems))
    policy = ProgramAutonomyPolicy.from_environ(env)
    if not policy.status()["authorized"]:
        raise PermissionError("PROGRAM_AUTONOMY_NOT_AUTHORIZED")
    max_in_flight = int(env.get("OC_BRAIN_PULSE_MAX_IN_FLIGHT", "1"))
    if not 1 <= max_in_flight <= 50:
        raise ValueError("OC_BRAIN_PULSE_MAX_IN_FLIGHT_OUT_OF_RANGE")
    backoff_base = float(env.get("OC_BRAIN_PULSE_BACKOFF_BASE_SECONDS", "30"))
    backoff_max = float(env.get("OC_BRAIN_PULSE_BACKOFF_MAX_SECONDS", "900"))
    if not 0 < backoff_base <= backoff_max <= 3600:
        raise ValueError("OC_BRAIN_PULSE_BACKOFF_OUT_OF_RANGE")
    # Appended, never prepended: the Brain checkout must not shadow Calyx
    # top-level packages of the same name (config, schemas, scripts, ...).
    checkout = str(Path(env["OC_BRAIN_CHECKOUT"]).resolve())
    if checkout not in sys.path:
        sys.path.append(checkout)
    from calyx_brain.autonomy_pulse import (
        PulseLedger,
        load_manifest,
        run_pulse,
        urllib_status_transport,
    )
    from calyx_brain.canonical_handoff import urllib_transport

    manifest = load_manifest(Path(env["OC_BRAIN_WORK_MANIFEST"]))
    ledger = PulseLedger(Path(env["OC_BRAIN_PULSE_LEDGER"]))
    post, get = urllib_transport(timeout=30), urllib_status_transport(timeout=30)
    pulse_env = {key: env[key] for key in ("CALYX_BACKEND_BASE_URL", "CALYX_API_KEY")}

    def replenish() -> dict[str, Any]:
        return run_pulse(
            manifest,
            ledger=ledger,
            transport=post,
            status_transport=get,
            env=pulse_env,
            max_in_flight=max_in_flight,
            backoff_base_seconds=backoff_base,
            backoff_max_seconds=backoff_max,
        )

    workspace = str(env.get("CALYX_PROGRAM_AUTONOMY_WORKSPACE", "")).strip()
    registry = AuthoritativeExecutorRegistry(
        workspace_root=Path(workspace) if workspace else None,
        repository_name=str(env.get("GITHUB_REPOSITORY", "")).strip() or None,
    )
    return BrainWorker(policy, replenish, registry, database_recorder(policy.owner))


def main() -> int:
    try:
        worker = build_worker(os.environ)
    except (ValueError, PermissionError) as exc:
        print(
            json.dumps(
                {
                    "worker": "calyx-program-autonomy-brain",
                    "started": False,
                    "zero_reason": "configuration_unavailable",
                    "detail": str(exc),
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return 0

    def emit(result: dict[str, Any]) -> None:
        print(json.dumps(result, sort_keys=True, default=str), flush=True)

    stop = threading.Event()
    install_stop_handlers(stop)
    run_forever(
        worker.policy,
        on_cycle=emit,
        replenish=worker.replenish,
        registry=worker.registry,
        recorder=worker.recorder,
        stop=stop,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

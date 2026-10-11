"""Brain-to-Calyx autonomy acceptance: ten consecutive productive scheduled cycles.

Every component is the real runtime component, wired against disposable
infrastructure:

* A real ``uvicorn`` server hosting the real canonical Brain router
  (``POST /brain/canonical/builds/submit``) and the real program router
  (``GET /brain/orchestrator/programs/{id}``), with real ``CALYX_API_KEY``
  authentication (no dependency overrides) and a disposable PostgreSQL schema.
* Scheduler processes running ``runtime.program_autonomy_worker.run_forever``.
  Each cycle is started only by that loop's own sleep timer. The harness never
  calls ``run_once`` or the program cycle.
* The Brain pulse (``calyx_brain.autonomy_pulse.run_pulse`` from the Brain
  checkout) is the scheduler's per-cycle replenishment step. It selects work
  from a manifest of real Brain ``build_verification_program`` packets, checks
  dependencies, and submits over real HTTP with the Brain ``urllib_transport``.
* The registered read-only executors (``repository_evidence_reader`` and
  ``isolated_workspace_static_validator``) execute against a disposable git
  checkout. The validator re-hashes and parses each Brain-declared Python file.
  No provider, no network beyond loopback (a socket guard enforces this in the
  scheduler processes).

Phase A requires ten consecutive productive cycles from one scheduler. Phase B
(recovery) SIGKILLs a scheduler mid-execution. It then runs two contending
schedulers that must recover the expired lease without duplicate delivery,
drain the manifest, and report truthful zero-work cycles.

The report is written as JSON to ``--output``; exit status 0 only if every
assertion passed. Local acceptance does not verify a deployed environment.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import itertools
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
REPOSITORY = "jsp1440/orchid-calyx-backend"
BRANCH = "autonomy/brain-calyx-acceptance"
API_KEY_OWNER = "backend_api_key"  # identity app.security assigns to the API key
ISOLATION_MARKER = ".calyx-isolated-workspace.json"
ISOLATION_SCHEMA = "calyx-isolated-workspace-v1"


# --------------------------------------------------------------------------
# Child: API server
# --------------------------------------------------------------------------


def serve() -> int:
    import uvicorn
    from fastapi import FastAPI

    from app.calyx_orchestrator.program_routes import router as program_router
    from app.canonical_brain.api import create_brain_router

    app = FastAPI()
    app.include_router(create_brain_router(prefix="/brain/canonical"))
    app.include_router(program_router, prefix="/brain/orchestrator")
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ["OC_ACCEPT_PORT"]),
        log_level="warning",
    )
    return 0


# --------------------------------------------------------------------------
# Child: scheduler (the real run_forever loop)
# --------------------------------------------------------------------------


def _append(path: str, record: dict[str, Any]) -> None:
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _install_loopback_guard(log_path: str) -> None:
    original = socket.socket.connect

    def guarded(self: socket.socket, address: Any) -> Any:
        host = address[0] if isinstance(address, tuple) else None
        if self.family in (socket.AF_INET, socket.AF_INET6) and host not in {
            "127.0.0.1",
            "::1",
            "localhost",
        }:
            _append(log_path, {"event": "blocked_network", "address": str(address)})
            raise PermissionError("ACCEPTANCE_NON_LOOPBACK_NETWORK_BLOCKED")
        return original(self, address)

    socket.socket.connect = guarded  # type: ignore[method-assign]


def scheduler() -> int:
    env = os.environ
    _install_loopback_guard(env["OC_ACCEPT_EVENTS"])
    sys.path.append(env["OC_ACCEPT_BRAIN_REPO"])
    from calyx_brain.autonomy_pulse import (
        PulseLedger,
        load_manifest,
        run_pulse,
        urllib_status_transport,
    )
    from calyx_brain.canonical_handoff import urllib_transport

    from app.calyx_orchestrator.autonomy_policy import ProgramAutonomyPolicy
    from app.calyx_orchestrator.executor_registry import AuthoritativeExecutorRegistry
    from runtime.program_autonomy_worker import run_forever

    worker = env["CALYX_PROGRAM_AUTONOMY_WORKER_ID"]
    events = env["OC_ACCEPT_EVENTS"]
    hang_prefix = env.get("OC_ACCEPT_HANG_BUILD_ID") or None

    registry = AuthoritativeExecutorRegistry(
        workspace_root=Path(env["OC_ACCEPT_SOURCE_REPO"]),
        repository_name=REPOSITORY,
    )

    class Observed:
        """Ledger-only wrapper; execution is the registered executor's own."""

        def __init__(self, inner: Any) -> None:
            self.inner = inner
            self.executor_key = inner.executor_key

        def execute(self, assignment: Any) -> Any:
            meta = {
                "worker": worker,
                "pid": os.getpid(),
                "job_key": assignment.job_key,
                "program_job_id": assignment.assignment_id,
                "role_key": assignment.role_key,
                "attempt_count": assignment.inputs["job"]["attempt_count"],
            }
            _append(events, {"event": "execution_started", "ts": time.time(), **meta})
            if hang_prefix and assignment.job_key.startswith(hang_prefix):
                time.sleep(3600)  # killed by the harness while holding the lease
            receipt = self.inner.execute(assignment)
            _append(
                events,
                {
                    "event": "execution_finished",
                    "ts": time.time(),
                    "state": receipt.state.value,
                    "output_checksum": receipt.output_checksum,
                    **meta,
                },
            )
            return receipt

    for role, registered in list(registry._by_role.items()):
        registry._by_role[role] = dataclasses.replace(
            registered, executor=Observed(registered.executor)
        )

    manifest = load_manifest(Path(env["OC_ACCEPT_MANIFEST"]))
    ledger = PulseLedger(Path(env["OC_ACCEPT_LEDGER"]))
    post, get = urllib_transport(timeout=10), urllib_status_transport(timeout=10)

    def replenish() -> dict[str, Any]:
        return run_pulse(
            manifest,
            ledger=ledger,
            transport=post,
            status_transport=get,
            env=env,
            max_in_flight=1,
            backoff_base_seconds=1,
            backoff_max_seconds=4,
        )

    def on_cycle(result: dict[str, Any]) -> None:
        _append(env["OC_ACCEPT_CYCLES"], {"pid": os.getpid(), **result})

    policy = ProgramAutonomyPolicy.from_environ(env)
    # Test acceleration only: production bounds poll_seconds to >= 15. The
    # loop still sleeps a real interval between cycles.
    policy = dataclasses.replace(policy, poll_seconds=int(env["OC_ACCEPT_POLL"]))
    run_forever(policy, on_cycle=on_cycle, replenish=replenish, registry=registry)
    return 0


# --------------------------------------------------------------------------
# Parent: harness
# --------------------------------------------------------------------------


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a child killed mid-write leaves a partial last line
    return rows


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _with_search_path(dsn: str, schema: str) -> str:
    joiner = "&" if "?" in dsn else "?"
    return f"{dsn}{joiner}options={quote(f'-csearch_path={schema}')}"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


class Harness:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.cycles = args.cycles
        self.total_work = args.cycles + (2 if args.recovery else 0)
        self.work = Path(tempfile.mkdtemp(prefix="oc-brain-calyx-acceptance-"))
        self.schema = "bc_accept_" + uuid.uuid4().hex[:16]
        self.api_key = secrets.token_hex(24)
        self.port = _free_port()
        self.assertions: list[dict[str, Any]] = []
        self.processes: dict[str, subprocess.Popen] = {}
        self.cycles_log = self.work / "cycles.jsonl"
        self.events_log = self.work / "events.jsonl"
        self.ledger = self.work / "brain-ledger.json"
        self.manifest = self.work / "work-manifest.json"
        self.source = self.work / "source"
        self.build_to_work: dict[str, str] = {}
        self.work_order: list[str] = []

    # -- setup ---------------------------------------------------------------

    def check(self, name: str, passed: bool, detail: Any = None) -> bool:
        self.assertions.append({"name": name, "passed": bool(passed), "detail": detail})
        return bool(passed)

    def engine(self):
        from sqlalchemy import create_engine

        return create_engine(_with_search_path(self.args.dsn, self.schema))

    def setup_schema(self) -> None:
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import Session

        from app.calyx_orchestrator.schema import ensure_orchestrator_schema

        admin = create_engine(self.args.dsn)
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        admin.dispose()
        engine = self.engine()
        with Session(engine) as db:
            ensure_orchestrator_schema(db)
        engine.dispose()

    def drop_schema(self) -> None:
        from sqlalchemy import create_engine, text

        admin = create_engine(self.args.dsn)
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE'))
        admin.dispose()

    def setup_source(self) -> list[dict[str, str]]:
        repo = self.source
        repo.mkdir()
        _git(repo, "init", "-q", "-b", BRANCH)
        _git(repo, "config", "user.email", "acceptance@example.invalid")
        _git(repo, "config", "user.name", "Brain-Calyx acceptance")
        (repo / "AGENTS.md").write_text("Provider-free acceptance fixture.\n")
        (repo / "requirements.txt").write_text("")
        (repo / ISOLATION_MARKER).write_text(
            json.dumps(
                {
                    "schema": ISOLATION_SCHEMA,
                    "repository": REPOSITORY,
                    "branch": BRANCH,
                    "disposable": True,
                    "workspace_write_authorized": True,
                }
            )
        )
        files = []
        (repo / "app" / "acceptance").mkdir(parents=True)
        for index in range(self.total_work):
            path = f"app/acceptance/module_{index:02d}.py"
            body = f'"""Acceptance source {index}."""\n\nVALUE = {index}\n'
            (repo / path).write_text(body)
            files.append(
                {"path": path, "sha256": hashlib.sha256(body.encode()).hexdigest()}
            )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "acceptance source")
        self.commit = _git(repo, "rev-parse", "HEAD")
        return files

    def setup_manifest(self, files: list[dict[str, str]]) -> None:
        sys.path.append(str(self.args.brain_repo))
        from calyx_brain.reasoning_contracts import (
            CandidateKnowledge,
            build_verification_program,
        )

        work = []
        previous: str | None = None
        for index, record in enumerate(files):
            candidate = CandidateKnowledge(
                candidate_id=f"candidate:acceptance:{index:02d}",
                subject_id=f"source:{record['path']}",
                predicate="has_verified_repository_source",
                object_id=f"git:{self.commit}:{record['path']}",
                evidence_ids=(f"git:{self.commit}:{record['path']}",),
                confidence=0.5,
            )
            packet = build_verification_program(
                candidate, repository=REPOSITORY, branch=BRANCH, files=[record]
            )
            work_id = f"work-{index:02d}"
            self.build_to_work[packet["idempotency_key"]] = work_id
            self.work_order.append(work_id)
            work.append(
                {
                    "work_id": work_id,
                    "packet": packet,
                    "depends_on": [previous] if previous else [],
                }
            )
            previous = work_id
        self.manifest.write_text(json.dumps({"work": work}, indent=1))

    def work_of(self, job_key: str) -> str | None:
        build = job_key.rsplit(":", 1)[0]
        return self.build_to_work.get(build)

    def build_of(self, work_id: str) -> str:
        return next(b for b, w in self.build_to_work.items() if w == work_id)

    # -- processes -----------------------------------------------------------

    def base_env(self) -> dict[str, str]:
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("PG", "CALYX_", "OC_ACCEPT_"))
        }
        env.update(
            {
                "PYTHONPATH": str(REPO_ROOT),
                "PYTHONDONTWRITEBYTECODE": "1",
                "DATABASE_URL": _with_search_path(self.args.dsn, self.schema),
                "CALYX_API_KEY": self.api_key,
                "NO_API_MODE": "true",
                "OC_GOVERNOR_PAID_EXECUTION_ENABLED": "false",
                "PROVIDER_LAUNCH_AUTHORIZED": "false",
                "OC_ACCEPT_PORT": str(self.port),
            }
        )
        return env

    def spawn(self, name: str, mode: str, env: dict[str, str]) -> subprocess.Popen:
        log = (self.work / f"{name}.log").open("w")
        proc = subprocess.Popen(
            [sys.executable, "-B", str(Path(__file__).resolve()), mode],
            cwd=REPO_ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        self.processes[name] = proc
        return proc

    def start_server(self) -> None:
        self.spawn("api", "--serve", self.base_env())
        url = f"http://127.0.0.1:{self.port}/brain/canonical/status"
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    if response.status == 200:
                        return
            except OSError:
                time.sleep(0.25)
        raise RuntimeError("ACCEPTANCE_API_SERVER_DID_NOT_START")

    def start_scheduler(self, worker: str, hang_build: str | None = None) -> None:
        env = self.base_env()
        env.update(
            {
                "CALYX_PROGRAM_AUTONOMY_ENABLED": "true",
                "CALYX_PROGRAM_AUTONOMY_OWNER": API_KEY_OWNER,
                "CALYX_PROGRAM_AUTONOMY_WORKER_ID": worker,
                "CALYX_PROGRAM_AUTONOMY_MAX_JOBS_PER_CYCLE": "2",
                "CALYX_PROGRAM_AUTONOMY_LEASE_SECONDS": "60",
                "CALYX_PROGRAM_AUTONOMY_TIMEOUT_SECONDS": "30",
                "CALYX_BACKEND_BASE_URL": f"http://127.0.0.1:{self.port}",
                "OC_ACCEPT_BRAIN_REPO": str(self.args.brain_repo),
                "OC_ACCEPT_SOURCE_REPO": str(self.source),
                "OC_ACCEPT_MANIFEST": str(self.manifest),
                "OC_ACCEPT_LEDGER": str(self.ledger),
                "OC_ACCEPT_CYCLES": str(self.cycles_log),
                "OC_ACCEPT_EVENTS": str(self.events_log),
                "OC_ACCEPT_POLL": str(self.args.poll_seconds),
            }
        )
        if hang_build:
            env["OC_ACCEPT_HANG_BUILD_ID"] = hang_build
        self.spawn(worker, "--scheduler", env)

    def stop(self, name: str, sig: int = signal.SIGTERM) -> None:
        proc = self.processes.get(name)
        if proc is None or proc.poll() is not None:
            return
        proc.send_signal(sig)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=15)

    def stop_all(self) -> None:
        for name in list(self.processes):
            self.stop(name)

    def cycles_of(self, worker: str) -> list[dict[str, Any]]:
        return [
            row
            for row in _read_jsonl(self.cycles_log)
            if (row.get("scheduler") or {}).get("worker_id") == worker
        ]

    def wait_for(self, predicate, timeout: float, watch: list[str]) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            for name in watch:
                if self.processes[name].poll() is not None:
                    return predicate()
            time.sleep(0.25)
        return predicate()

    # -- database ------------------------------------------------------------

    def jobs(self) -> list[dict[str, Any]]:
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        from app.calyx_orchestrator.program_models import CalyxProgram, CalyxProgramJob

        engine = self.engine()
        try:
            with Session(engine) as db:
                rows = db.execute(
                    select(CalyxProgramJob, CalyxProgram).join(
                        CalyxProgram,
                        CalyxProgram.program_id == CalyxProgramJob.program_id,
                    )
                ).all()
                return [
                    {
                        "job_key": job.job_key,
                        "program_job_id": job.program_job_id,
                        "program_id": job.program_id,
                        "program_status": program.status,
                        "owner": program.owner,
                        "role_key": job.role_key,
                        "status": job.status,
                        "outcome": job.outcome,
                        "attempt_count": job.attempt_count,
                        "lease_owner": job.lease_owner,
                        "lease_token": job.lease_token,
                        "evidence": json.loads(job.evidence_json or "null"),
                        "inputs": json.loads(job.input_json or "{}"),
                    }
                    for job, program in rows
                ]
        finally:
            engine.dispose()

    # -- phase A -------------------------------------------------------------

    def phase_a(self) -> dict[str, Any]:
        self.start_scheduler("scheduler-a")
        reached = self.wait_for(
            lambda: len(self.cycles_of("scheduler-a")) >= self.cycles,
            timeout=self.cycles * (self.args.poll_seconds + 20) + 60,
            watch=["scheduler-a", "api"],
        )
        self.stop("scheduler-a")
        cycles = self.cycles_of("scheduler-a")[: self.cycles]
        self.check("phase_a_cycle_count_reached", reached, len(cycles))
        self.check(
            "scheduler_sequence_is_consecutive",
            [c["scheduler"]["sequence"] for c in cycles]
            == list(range(1, self.cycles + 1)),
            [c["scheduler"]["sequence"] for c in cycles],
        )
        self.check(
            "single_scheduler_process_drove_every_cycle",
            len({c["pid"] for c in cycles}) == 1,
            sorted({c["pid"] for c in cycles}),
        )
        starts = [c.get("started_at") for c in cycles]
        from datetime import datetime

        gaps = [
            (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds()
            for a, b in itertools.pairwise(starts)
        ]
        self.check(
            "cycles_spaced_by_the_scheduler_timer",
            bool(gaps) and min(gaps) >= self.args.poll_seconds,
            {"poll_seconds": self.args.poll_seconds, "min_gap": min(gaps or [0])},
        )

        per_cycle = []
        for index, cycle in enumerate(cycles):
            expected_work = self.work_order[index]
            replenishment = cycle.get("replenishment") or {}
            submissions = replenishment.get("submissions") or []
            reconciled = replenishment.get("reconciled") or []
            jobs = (cycle.get("cycle") or {}).get("jobs") or []
            job_work = sorted({self.work_of(j["job_key"]) or "?" for j in jobs})
            record = {
                "sequence": cycle["scheduler"]["sequence"],
                "started_at": cycle.get("started_at"),
                "classification": cycle.get("classification"),
                "submitted": [(s["work_id"], s["outcome"]) for s in submissions],
                "reconciled": [(r["work_id"], r["state"]) for r in reconciled],
                "executed_work": job_work,
                "jobs": [
                    {
                        k: j[k]
                        for k in (
                            "job_key",
                            "program_job_id",
                            "outcome",
                            "receipt_state",
                        )
                    }
                    for j in jobs
                ],
            }
            per_cycle.append(record)
            ok = (
                (cycle.get("classification") or {}).get("productive") is True
                and submissions
                == [s for s in submissions if s["outcome"] == "submitted"]
                and [s["work_id"] for s in submissions] == [expected_work]
                and job_work == [expected_work]
                and len(jobs) == 2
                and all(j["productive"] for j in jobs)
                and (
                    index == 0
                    or [
                        (r["work_id"], r["state"], r["all_delivered"])
                        for r in reconciled
                    ]
                    == [(self.work_order[index - 1], "completed", True)]
                )
            )
            self.check(f"cycle_{index + 1:02d}_productive_and_attributed", ok, record)

        db_jobs = [
            j
            for j in self.jobs()
            if self.work_of(j["job_key"]) in self.work_order[: self.cycles]
        ]
        self.check(
            "every_admitted_job_persisted_delivered_once",
            len(db_jobs) == 2 * self.cycles
            and all(
                j["status"] == "completed"
                and j["outcome"] == "DELIVERED"
                and j["attempt_count"] == 1
                and j["lease_token"] is None
                and j["owner"] == API_KEY_OWNER
                and j["program_status"] == "completed"
                for j in db_jobs
            ),
            [
                {k: j[k] for k in ("job_key", "status", "outcome", "attempt_count")}
                for j in db_jobs
                if j["outcome"] != "DELIVERED" or j["attempt_count"] != 1
            ],
        )
        self.check(
            "results_persisted_with_verified_receipt_and_brain_provenance",
            all(
                (j["evidence"] or {}).get("state") == "delivered"
                and (j["evidence"] or {}).get("output_checksum")
                and "brain_request_provenance" in j["inputs"]
                and j["inputs"]["brain_request_provenance"]["admission_request"][
                    "build_id"
                ]
                == j["job_key"]
                for j in db_jobs
            ),
        )
        validated = [
            (
                j["inputs"].get("files"),
                ((j["evidence"] or {}).get("output") or {}).get("results"),
            )
            for j in db_jobs
            if j["role_key"] == "isolated_workspace_static_validator"
        ]
        self.check(
            "static_validator_verified_brain_declared_hashes",
            len(validated) == self.cycles
            and all(
                isinstance(results, list)
                and [(r["path"], r["sha256"], r["syntax"]) for r in results]
                == [(f["path"], f["sha256"], "passed") for f in declared]
                for declared, results in validated
            ),
            validated[:1],
        )
        events = [
            e for e in _read_jsonl(self.events_log) if e.get("worker") == "scheduler-a"
        ]
        finished = Counter(
            e["job_key"] for e in events if e["event"] == "execution_finished"
        )
        self.check(
            "zero_duplicate_executions_phase_a",
            sorted(finished) == sorted(j["job_key"] for j in db_jobs)
            and set(finished.values()) == {1},
            {k: v for k, v in finished.items() if v != 1},
        )
        pulses = _read_jsonl(self.ledger.with_suffix(".json.receipts.jsonl"))
        submitted = Counter(
            s["work_id"]
            for p in pulses
            for s in p.get("submissions", [])
            if s["outcome"] in {"submitted", "idempotent_replay"}
        )
        self.check(
            "each_work_item_submitted_exactly_once",
            all(submitted[w] == 1 for w in self.work_order[: self.cycles]),
            dict(submitted),
        )
        return {"cycles": per_cycle}

    # -- phase B -------------------------------------------------------------

    def phase_b(self) -> dict[str, Any]:
        victim_work = self.work_order[self.cycles]
        victim_build = self.build_of(victim_work)

        def victim_started() -> bool:
            return any(
                e.get("event") == "execution_started"
                and e.get("worker") == "scheduler-b"
                and e["job_key"].startswith(victim_build)
                for e in _read_jsonl(self.events_log)
            )

        self.start_scheduler("scheduler-b", hang_build=victim_build)
        started = self.wait_for(victim_started, 90, ["scheduler-b", "api"])
        self.stop("scheduler-b", signal.SIGKILL)
        killed_at = time.time()
        self.check("victim_killed_mid_execution_holding_lease", started)
        held = [
            j
            for j in self.jobs()
            if j["job_key"].startswith(victim_build)
            and j["lease_owner"] == "scheduler-b"
        ]
        self.check(
            "dead_worker_left_an_unsettled_lease",
            len(held) == 1
            and held[0]["status"] == "running"
            and held[0]["outcome"] is None,
            [{k: j[k] for k in ("job_key", "status", "lease_owner")} for j in held],
        )

        # Restart with two contending schedulers sharing the DB and Brain ledger.
        self.start_scheduler("scheduler-c")
        self.start_scheduler("scheduler-d")

        def drained() -> bool:
            jobs = self.jobs()
            done = len(jobs) == 2 * self.total_work and all(
                j["outcome"] == "DELIVERED" for j in jobs
            )
            if not done:
                return False
            ledger = json.loads(self.ledger.read_text())
            if any(
                ledger["work"].get(w, {}).get("state") != "completed"
                for w in self.work_order
            ):
                return False
            idle = [
                c
                for c in self.cycles_of("scheduler-c") + self.cycles_of("scheduler-d")
                if (c.get("classification") or {}).get("category") == "no_eligible_work"
            ]
            return bool(idle)

        finished = self.wait_for(drained, 300, ["scheduler-c", "scheduler-d", "api"])
        self.stop("scheduler-c")
        self.stop("scheduler-d")
        self.check("manifest_drained_after_restart", finished)

        jobs = self.jobs()
        events = _read_jsonl(self.events_log)
        started_by = [
            (e["worker"], e["attempt_count"])
            for e in events
            if e["event"] == "execution_started"
            and e["job_key"].startswith(victim_build + ":0")
        ]
        victim = next(j for j in jobs if j["job_key"] == victim_build + ":0")
        self.check(
            "expired_lease_recovered_by_a_live_worker",
            victim["outcome"] == "DELIVERED"
            and victim["attempt_count"] == 2
            and victim["lease_owner"] in (None, "scheduler-c", "scheduler-d")
            and started_by[0][0] == "scheduler-b"
            and started_by[-1][0] in {"scheduler-c", "scheduler-d"},
            {"attempts": victim["attempt_count"], "started_by": started_by},
        )
        finished_count = Counter(
            e["job_key"] for e in events if e["event"] == "execution_finished"
        )
        self.check(
            "zero_duplicate_deliveries_across_restart_and_contention",
            len(finished_count) == 2 * self.total_work
            and set(finished_count.values()) == {1}
            and all(j["outcome"] == "DELIVERED" for j in jobs),
            {k: v for k, v in finished_count.items() if v != 1},
        )
        self.check(
            "no_more_than_one_unfinished_start_per_kill",
            sum(1 for e in events if e["event"] == "execution_started")
            - sum(finished_count.values())
            == 1,
        )
        recovery_cycles = self.cycles_of("scheduler-c") + self.cycles_of("scheduler-d")
        categories = Counter(
            (c.get("classification") or {}).get("category") or "productive"
            for c in recovery_cycles
        )
        waiting = [
            c
            for c in recovery_cycles
            if (c.get("classification") or {}).get("category") == "capacity_exhausted"
        ]
        self.check(
            "lease_wait_reported_as_healthy_capacity_wait_not_productive",
            bool(waiting)
            and all(
                c["classification"]["productive"] is False
                and c["classification"]["healthy"]
                for c in waiting
            ),
            {"categories": dict(categories)},
        )
        self.check(
            "zero_work_cycle_classified_no_eligible_work",
            categories.get("no_eligible_work", 0) >= 1,
            dict(categories),
        )
        self.check(
            "no_cycle_reported_a_scheduler_defect_or_false_productivity",
            all(
                (c.get("classification") or {}).get("category")
                not in {"scheduler_defect", "execution_not_delivered", "no_executor"}
                for c in recovery_cycles
            )
            and all(
                (c.get("classification") or {}).get("productive")
                == bool((c.get("cycle") or {}).get("productive_jobs"))
                for c in recovery_cycles
            ),
            dict(categories),
        )
        self.check(
            "dead_worker_never_settled",
            not any(
                e["event"] == "execution_finished" and e["worker"] == "scheduler-b"
                for e in events
            ),
        )
        pulses = _read_jsonl(self.ledger.with_suffix(".json.receipts.jsonl"))
        submitted = Counter(
            s["work_id"]
            for p in pulses
            for s in p.get("submissions", [])
            if s["outcome"] in {"submitted", "idempotent_replay"}
        )
        self.check(
            "brain_submitted_each_work_item_once_across_restarts",
            sorted(submitted) == sorted(self.work_order)
            and set(submitted.values()) == {1},
            dict(submitted),
        )
        return {
            "victim_work": victim_work,
            "recovery_seconds_after_kill": round(time.time() - killed_at, 1),
            "recovery_cycle_categories": dict(categories),
            "pulse_lock_refusals": sum(
                1 for p in pulses if p.get("detail") == "PULSE_ALREADY_RUNNING"
            ),
        }

    # -- run -----------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        report: dict[str, Any] = {
            "schema": "brain-calyx-autonomy-acceptance.v1",
            "started_at": time.time(),
            "cycles_required": self.cycles,
            "poll_seconds": self.args.poll_seconds,
            "brain_repo": str(self.args.brain_repo),
            "calyx_head": _git(REPO_ROOT, "rev-parse", "HEAD"),
            "brain_head": _git(self.args.brain_repo, "rev-parse", "HEAD"),
            "evidence_scope": "local disposable infrastructure; not a deployed run",
        }
        try:
            self.setup_schema()
            self.setup_manifest(self.setup_source())
            self.start_server()
            report["phase_a"] = self.phase_a()
            if self.args.recovery and all(a["passed"] for a in self.assertions):
                report["phase_b"] = self.phase_b()
            elif self.args.recovery:
                self.check("phase_b_requires_phase_a", False, "skipped")
            blocked = [
                e
                for e in _read_jsonl(self.events_log)
                if e.get("event") == "blocked_network"
            ]
            self.check("no_non_loopback_network_attempted", not blocked, blocked)
        except Exception as exc:  # noqa: BLE001 - report, never mask
            self.check("harness_completed", False, f"{type(exc).__name__}: {exc}")
        finally:
            self.stop_all()
            report["process_logs"] = {
                name: (self.work / f"{name}.log").read_text()[-2000:]
                for name in self.processes
            }
            self.drop_schema()
        report["assertions"] = self.assertions
        report["passed"] = bool(self.assertions) and all(
            a["passed"] for a in self.assertions
        )
        report["finished_at"] = time.time()
        if report["passed"] and not self.args.keep:
            shutil.rmtree(self.work, ignore_errors=True)
        else:
            report["workdir"] = str(self.work)
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--scheduler", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--dsn")
    parser.add_argument("--brain-repo", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cycles", type=int, default=10)
    parser.add_argument("--poll-seconds", type=int, default=2)
    parser.add_argument("--no-recovery", dest="recovery", action="store_false")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    if args.serve:
        return serve()
    if args.scheduler:
        return scheduler()
    if not (args.dsn and args.brain_repo and args.output):
        parser.error("--dsn, --brain-repo and --output are required")
    if args.cycles < 10:
        parser.error("acceptance requires at least ten cycles")
    if not (args.brain_repo / "calyx_brain" / "autonomy_pulse.py").is_file():
        parser.error(
            "--brain-repo must be an Orchid-Continuum-Brain checkout with the pulse"
        )
    report = Harness(args).run()
    args.output.write_text(json.dumps(report, indent=1, sort_keys=True, default=str))
    failed = [a["name"] for a in report["assertions"] if not a["passed"]]
    print(json.dumps({"passed": report["passed"], "failed": failed}, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Run the actual worker image via a fake Azure transport, never a cloud job."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.assignment_factory import (
    governed_assignment_from_claimed_job,
)
from app.calyx_orchestrator.azure_execution_adapter import (
    AZURE_ROLE,
    AzureContainerAppsExecutor,
    AzureExecutionGrant,
    _decode_receipt,
)
from app.calyx_orchestrator.azure_execution_models import AzureExecutionRecord
from app.calyx_orchestrator.azure_job_client import FakeAzureJobClient
from app.calyx_orchestrator.executor import canonical_checksum
from app.calyx_orchestrator.program_models import (
    CalyxProgram,
    CalyxProgramDependency,
    CalyxProgramJob,
)
from app.calyx_orchestrator.program_repository import (
    PersistentProgramRepository,
    ProgramJobSpec,
)
from app.calyx_orchestrator.program_worker import PersistentProgramWorker
from app.canonical_brain.build_queue import GovernedBuildQueue
from app.canonical_brain.constitution import BuildAdmissionRequest
from app.database import Base
from scripts.oc_azure_execution_demo import demo_config


class ContainerAzureClient(FakeAzureJobClient):
    """Only the injected bounded subprocess executes; Azure operations remain fake."""

    def __init__(self, runner):
        super().__init__()
        self.runner = runner
        self.receipt = None

    def start(self, config, payload, timeout):
        reference = super().start(config, payload, timeout)
        encoded = self.runner(payload, reference, timeout)
        self.receipt = _decode_receipt(encoded)
        return reference

    def result(self, config, reference, assignment_id, digest, timeout):
        if self.receipt is None:
            raise RuntimeError("CONTAINER_RECEIPT_MISSING")
        return self.receipt


class DockerWorkerRunner:
    def __init__(self, image: str) -> None:
        if not shutil.which("docker"):
            raise RuntimeError("LOCAL_CONTAINER_ENGINE_MISSING")
        self.image = image

    def __call__(self, payload, reference, timeout):
        # --pull=never prevents accidental remote image download or registry auth.
        name = f"calyx-azure-proof-{uuid4().hex}"
        command = [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--name",
            name,
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=64",
            "--memory=1g",
            "--cpus=0.5",
            "--user=65532:65532",
            "--env",
            "CALYX_EXECUTION_PAYLOAD",
            "--env",
            "CALYX_AZURE_WORKER_TEST_MODE",
            "--env",
            "CALYX_WORKER_EXECUTION_REFERENCE",
            "--env",
            "CALYX_AZURE_WORKER_ENABLED=false",
            self.image,
            "--fake",
        ]
        env = {
            **os.environ,
            "CALYX_EXECUTION_PAYLOAD": json.dumps(payload),
            "CALYX_AZURE_WORKER_TEST_MODE": "provider-free",
            "CALYX_WORKER_EXECUTION_REFERENCE": reference,
        }
        try:
            result = subprocess.run(
                command,
                env=env,
                capture_output=True,
                text=True,
                timeout=max(1, payload["timeout_seconds"]),
                check=False,
            )
        except subprocess.TimeoutExpired:
            subprocess.run(
                ["docker", "rm", "--force", name],
                capture_output=True,
                timeout=10,
                check=False,
            )
            raise
        if result.returncode:
            raise RuntimeError(f"CONTAINER_WORKER_EXIT_{result.returncode}")
        return result.stdout.strip()


def run_proof(runner) -> dict[str, object]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            CalyxProgram.__table__,
            CalyxProgramJob.__table__,
            CalyxProgramDependency.__table__,
            AzureExecutionRecord.__table__,
        ],
    )
    queue = GovernedBuildQueue()
    admitted = queue.submit(
        BuildAdmissionRequest(
            build_id="azure-container-proof",
            architecture_id="architecture:brain",
            intent_ids=["intent:enable-governed-autonomy"],
            decision_ids=["decision:brain-canonical-memory"],
            source_uris=["calyx:container-proof"],
            validation_plan_ids=["validation:actual-container"],
            deterministic_outputs=True,
            preserves_provenance=True,
            separates_evidence_from_inference=True,
        )
    )
    if admitted.status != "admitted":
        raise RuntimeError("BRAIN_CONTAINER_ADMISSION_FAILED")
    config = demo_config()
    client = ContainerAzureClient(runner)
    with Session(engine) as db:
        repo = PersistentProgramRepository(db)
        program = repo.create_program(
            owner="container-proof",
            title="Bounded container verification",
            objective="Verify real entrypoint through the canonical Calyx lease bridge.",
            jobs=[
                ProgramJobSpec(
                    admitted.build_id, AZURE_ROLE, "Verify input", "example/repo"
                ),
                ProgramJobSpec(
                    "next-brain-work", "autonomy_probe", "Next work", "example/repo"
                ),
            ],
            dependencies=[(admitted.build_id, "next-brain-work")],
        )
        repo.start(owner=program.owner, program_id=program.program_id)
        job = PersistentProgramWorker(db).claim(
            worker_id="container-proof",
            owner=program.owner,
            allowed_role_keys=frozenset({AZURE_ROLE}),
        )
        if job is None:
            raise RuntimeError("CALYX_CONTAINER_CLAIM_FAILED")
        assignment = governed_assignment_from_claimed_job(
            db,
            owner=program.owner,
            job=job,
            timeout_seconds=60,
        )
        executor = AzureContainerAppsExecutor(
            db,
            config=config,
            client=client,
            owner=program.owner,
            worker_id=job.lease_owner,
            lease_token=job.lease_token,
            grant_resolver=lambda assignment, digest: AzureExecutionGrant(
                "fake:container-proof-zero-spend",
                assignment.assignment_id,
                assignment.verified_input_checksum(),
                digest,
                config.resource_id,
                canonical_checksum(asdict(config)),
                datetime.now(UTC) + timedelta(seconds=300),
                config.max_cost_microusd,
            ),
        )
        receipt = executor.execute(assignment)
        receipt.verify()
        try:
            executor.execute(assignment)
        except PermissionError as exc:
            if str(exc) != "AZURE_DUPLICATE_DISPATCH":
                raise
        else:
            raise AssertionError("CONTAINER_DUPLICATE_DISPATCH_NOT_FENCED")
        executor.lease_token = "superseded"
        try:
            executor.settle(assignment, receipt)
        except PermissionError:
            pass
        else:
            raise AssertionError("CONTAINER_STALE_SETTLEMENT_NOT_FENCED")
        executor.lease_token = job.lease_token
        executor.settle(assignment, receipt)
        next_job = db.query(CalyxProgramJob).filter_by(job_key="next-brain-work").one()
        record = db.get(AzureExecutionRecord, job.program_job_id)
        assert record.state == "settled"
        assert record.receipt_json
        assert next_job.status == "queued"
        return {
            "brain_admission": admitted.status,
            "worker_mode": receipt.output["result"]["mode"],
            "azure_starts": client.starts,
            "durable_receipt": True,
            "duplicate_fenced": True,
            "stale_settlement_fenced": True,
            "settlement": job.outcome,
            "brain_replenishment_eligible": next_job.status == "queued",
            "azure_calls": 0,
            "production_access": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(run_proof(DockerWorkerRunner(args.image)), sort_keys=True))
    except Exception as exc:  # noqa: BLE001 - CLI boundary, fail nonzero and sanitize
        code = (
            "LOCAL_CONTAINER_ENGINE_MISSING"
            if str(exc) == "LOCAL_CONTAINER_ENGINE_MISSING"
            else type(exc).__name__
        )
        print(
            json.dumps({"state": "blocked", "error": code}),
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Provider-free Brain admission -> durable Calyx execution/settlement proof."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.assignment_factory import (
    governed_assignment_from_claimed_job,
)
from app.calyx_orchestrator.azure_execution_adapter import (
    AZURE_ROLE,
    AzureContainerAppsExecutor,
    AzureExecutionGrant,
    AzureJobConfig,
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
from app.canonical_brain.fixtures import build_canonical_brain_fixture
from app.canonical_brain.scheduler_bridge import (
    SchedulerJobMetadata,
    project_governed_queue,
)
from app.database import Base


def demo_config() -> AzureJobConfig:
    return AzureJobConfig(
        enabled=True,
        subscription_id="fake-subscription",
        resource_group="fake-rg",
        environment_name="fake-env",
        job_name="fake-job",
        job_identity_resource_id=(
            "/subscriptions/fake-subscription/resourceGroups/fake-rg"
            "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/fake-worker"
        ),
        managed_identity_client_id="fake-client",
        container_name="worker",
        image="fake.invalid/calyx@sha256:" + "a" * 64,
        max_cost_microusd=1000,
    )


def run_demo() -> dict[str, object]:
    # This engine is explicit and local; ambient DATABASE_URL/PGHOST is never read.
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
    brain = build_canonical_brain_fixture()
    assert brain.get("architecture:brain") is not None
    queue = GovernedBuildQueue()
    item = queue.submit(
        BuildAdmissionRequest(
            build_id="azure-demo-build",
            architecture_id="architecture:brain",
            intent_ids=["intent:enable-governed-autonomy"],
            decision_ids=["decision:brain-canonical-memory"],
            source_uris=["brain://fixtures/architecture:brain"],
            validation_plan_ids=["validation:provider-free-azure-demo"],
            deterministic_outputs=True,
            preserves_provenance=True,
            separates_evidence_from_inference=True,
        )
    )
    if item.status != "admitted":
        raise PermissionError("BRAIN_DEMO_ADMISSION_FAILED")
    metadata = SchedulerJobMetadata(
        build_id=item.build_id,
        role_key=AZURE_ROLE,
        repository="jsp1440/orchid-calyx-backend",
    )
    project_governed_queue(
        queue=queue.snapshot(), metadata=(metadata,), dependencies=()
    )
    with Session(engine) as db:
        repo = PersistentProgramRepository(db)
        program = repo.create_program(
            owner="fake-demo-owner",
            title="Provider-free Azure execution proof",
            objective="Verify an admitted task without scientific or production authority.",
            jobs=[
                ProgramJobSpec(
                    item.build_id,
                    AZURE_ROLE,
                    "Verify admitted input",
                    metadata.repository,
                    inputs={"brain_build_id": item.build_id},
                ),
                ProgramJobSpec(
                    "replenishment-eligible",
                    "autonomy_probe",
                    "Next governed work",
                    metadata.repository,
                ),
            ],
            dependencies=[(item.build_id, "replenishment-eligible")],
        )
        repo.start(owner=program.owner, program_id=program.program_id)
        job = PersistentProgramWorker(db).claim(
            worker_id="fake-azure-worker",
            owner=program.owner,
            allowed_role_keys=frozenset({AZURE_ROLE}),
        )
        if job is None:
            raise RuntimeError("CALYX_DEMO_ADMISSION_FAILED")
        assignment = governed_assignment_from_claimed_job(
            db, owner=program.owner, job=job
        )
        config = demo_config()
        client = FakeAzureJobClient()
        executor = AzureContainerAppsExecutor(
            db,
            config=config,
            client=client,
            owner=program.owner,
            worker_id=job.lease_owner,
            lease_token=job.lease_token,
            grant_resolver=lambda assignment, digest: AzureExecutionGrant(
                "fake-demo:synthetic-no-spend-grant",
                assignment.assignment_id,
                assignment.verified_input_checksum(),
                digest,
                config.resource_id,
                canonical_checksum(asdict(config)),
                datetime.now(timezone.utc) + timedelta(seconds=300),
                config.max_cost_microusd,
            ),
        )
        receipt = executor.execute(assignment)
        receipt.verify()
        completed = executor.settle(assignment, receipt)
        snapshot = repo.snapshot(owner=program.owner, program_id=program.program_id)
        downstream = next(
            row
            for row in snapshot["jobs"]
            if row["job_key"] == "replenishment-eligible"
        )
        assert completed.outcome == "DELIVERED"
        assert downstream["status"] == "queued"
        return {
            "mode": "provider_free_fake_azure",
            "brain_admission": item.status,
            "calyx_task_id": assignment.assignment_id,
            "azure_starts": client.starts,
            "receipt_verified": True,
            "settlement": completed.outcome,
            "replenishment_eligible": downstream["status"] == "queued",
            "network_calls": 0,
            "azure_resources_created": 0,
            "spend": 0,
            "production_access": False,
            "scientific_publication": False,
        }


if __name__ == "__main__":
    print(json.dumps(run_demo(), sort_keys=True))

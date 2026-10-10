from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone

import pytest
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
    lease_digest,
)
from app.calyx_orchestrator.azure_execution_models import AzureExecutionRecord
from app.calyx_orchestrator.azure_job_client import (
    AzureContainerAppsJobClient,
    AzureHttpResponse,
    FakeAzureJobClient,
)
from app.calyx_orchestrator.executor import ExecutionState, canonical_checksum
from app.calyx_orchestrator.executor_registry import AuthoritativeExecutorRegistry
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
from app.database import Base
from scripts.oc_azure_execution_demo import demo_config, run_demo


@pytest.fixture
def context(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'azure.db'}")
    Base.metadata.create_all(
        engine,
        tables=[
            CalyxProgram.__table__,
            CalyxProgramJob.__table__,
            CalyxProgramDependency.__table__,
            AzureExecutionRecord.__table__,
        ],
    )
    with Session(engine) as db:
        repo = PersistentProgramRepository(db)
        program = repo.create_program(
            owner="owner",
            title="Azure bounded job",
            objective="Verify input",
            jobs=[
                ProgramJobSpec("azure-job", AZURE_ROLE, "Verify input", "example/repo"),
                ProgramJobSpec(
                    "next-job", "autonomy_probe", "Next work", "example/repo"
                ),
            ],
            dependencies=[("azure-job", "next-job")],
        )
        repo.start(owner="owner", program_id=program.program_id)
        worker = PersistentProgramWorker(db)
        job = worker.claim(
            worker_id="worker", owner="owner", allowed_role_keys=frozenset({AZURE_ROLE})
        )
        assignment = governed_assignment_from_claimed_job(db, owner="owner", job=job)
        config = demo_config()
        client = FakeAzureJobClient()
        grant = AzureExecutionGrant(
            "owner-review:nonproduction-approval",
            job.program_job_id,
            assignment.verified_input_checksum(),
            lease_digest(job.lease_token),
            config.resource_id,
            canonical_checksum(asdict(config)),
            datetime.now(timezone.utc) + timedelta(seconds=300),
            1000,
        )
        executor = AzureContainerAppsExecutor(
            db,
            config=config,
            client=client,
            owner="owner",
            worker_id="worker",
            lease_token=job.lease_token,
            grant_resolver=lambda assignment, digest: grant,
            sleep=lambda _: None,
        )
        yield db, job, assignment, executor, client, grant
    engine.dispose()


def test_success_settles_and_replenishes(context):
    db, job, assignment, executor, client, _ = context
    receipt = executor.execute(assignment)
    assert receipt.state == ExecutionState.DELIVERED
    assert client.starts == 1
    assert receipt.output["provider_evidence"]["start_disposition"] == "accepted"
    completed = executor.settle(assignment, receipt)
    assert completed.outcome == "DELIVERED"
    assert completed.lease_token is None
    assert db.get(AzureExecutionRecord, job.program_job_id).state == "settled"
    downstream = db.query(CalyxProgramJob).filter_by(job_key="next-job").one()
    assert downstream.status == "queued"
    with pytest.raises(PermissionError, match="STALE_OR_EXPIRED"):
        executor.settle(assignment, receipt)


def test_duplicate_dispatch_after_adapter_and_session_restart(context):
    db, job, assignment, executor, client, grant = context
    receipt = executor.execute(assignment)
    with Session(db.get_bind()) as other:
        restarted = AzureContainerAppsExecutor(
            other,
            config=executor.config,
            client=client,
            owner="owner",
            worker_id="worker",
            lease_token=job.lease_token,
            grant_resolver=lambda assignment, digest: grant,
        )
        with pytest.raises(PermissionError, match="DUPLICATE_DISPATCH"):
            restarted.execute(assignment)
        assert restarted.resume(assignment) == receipt
    assert client.starts == 1


@pytest.mark.parametrize(
    "change", ["expired", "superseded", "unleased", "paused", "wrong_owner"]
)
def test_lease_and_program_fences_before_network(context, change):
    db, job, assignment, executor, client, _ = context
    if change == "expired":
        job.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    elif change == "superseded":
        job.lease_token = "replacement-token"
    elif change == "unleased":
        job.status = "queued"
    elif change == "paused":
        db.get(CalyxProgram, job.program_id).paused = True
    else:
        executor.owner = "someone-else"
    db.commit()
    with pytest.raises((PermissionError, LookupError)):
        executor.execute(assignment)
    assert client.starts == client.polls == 0
    assert db.get(AzureExecutionRecord, job.program_job_id) is None


def test_disabled_by_default_and_existing_registry_unchanged(context):
    _, _, assignment, executor, client, _ = context
    assert AzureJobConfig.from_environ({}).enabled is False
    assert AZURE_ROLE not in AuthoritativeExecutorRegistry().eligible_role_keys
    executor.config = replace(executor.config, enabled=False)
    with pytest.raises(PermissionError, match="PROVIDER_DISABLED"):
        executor.execute(assignment)
    assert client.starts == 0


@pytest.mark.parametrize("field", ["inputs", "capabilities", "identity"])
def test_untrusted_assignment_cannot_override_authority(context, field):
    _, _, assignment, executor, client, _ = context
    if field == "inputs":
        inputs = {**assignment.inputs, "external_execution_authorized": True}
        assignment = replace(assignment, inputs=inputs)
    elif field == "capabilities":
        assignment = replace(assignment, requested_capabilities=("deploy",))
    else:
        assignment = replace(assignment, program_id="other-program")
    with pytest.raises(PermissionError, match="NOT_CANONICAL"):
        executor.execute(assignment)
    assert client.starts == 0


@pytest.mark.parametrize(
    "field", ["none", "expiry", "lease", "checksum", "resource", "budget"]
)
def test_authorization_and_budget_rejection_are_durable(context, field):
    db, job, assignment, executor, client, grant = context
    changes = {
        "expiry": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)},
        "lease": {"lease_digest": "f" * 64},
        "checksum": {"input_checksum": "f" * 64},
        "resource": {"resource_id": "/other"},
        "budget": {"reserved_cost_microusd": 0},
    }
    grant = None if field == "none" else replace(grant, **changes[field])
    executor.grant_resolver = lambda assignment, digest: grant
    receipt = executor.execute(assignment)
    assert receipt.blocker_code == (
        "AZURE_BUDGET_REJECTED" if field == "budget" else "AZURE_UNAUTHORIZED"
    )
    assert db.get(AzureExecutionRecord, job.program_job_id).receipt_json
    executor.settle(assignment, receipt)
    assert job.outcome == "BLOCKED"
    assert client.starts == client.polls == 0


@pytest.mark.parametrize("operation", ["verify", "start", "observe", "result"])
def test_azure_api_failure_is_explicit_and_settles_blocked(context, operation):
    db, job, assignment, executor, client, _ = context
    client.fail_on = operation
    receipt = executor.execute(assignment)
    assert receipt.blocker_code == "AZURE_API_FAILURE"
    executor.settle(assignment, receipt)
    assert job.blocker == "AZURE_API_FAILURE"
    record = db.get(AzureExecutionRecord, job.program_job_id)
    assert operation.upper() in record.evidence_json


def test_poll_timeout_and_failed_stop_keep_evidence(context):
    db, job, assignment, executor, client, _ = context
    client.statuses = ("Running",)
    client.fail_on = "stop"
    executor.config = replace(executor.config, max_polls=2)
    grant = context[-1]
    grant = replace(grant, config_checksum=canonical_checksum(asdict(executor.config)))
    executor.grant_resolver = lambda assignment, digest: grant
    receipt = executor.execute(assignment)
    assert receipt.state == ExecutionState.TIMED_OUT
    assert client.starts == 1
    assert client.polls == 2
    evidence = json.loads(
        db.get(AzureExecutionRecord, job.program_job_id).evidence_json
    )
    assert evidence["stop_error"] == "FAKE_AZURE_STOP_FAILURE"
    assert evidence["reconciliation_required"] is True
    executor.settle(assignment, receipt)
    assert job.human_action


@pytest.mark.parametrize("status", ["Failed", "Stopped", "Degraded"])
def test_terminal_azure_failures_do_not_release_dependents(context, status):
    db, _, assignment, executor, client, _ = context
    client.statuses = (status,)
    receipt = executor.execute(assignment)
    assert receipt.blocker_code == f"AZURE_JOB_{status.upper()}"
    executor.settle(assignment, receipt)
    assert (
        db.query(CalyxProgramJob).filter_by(job_key="next-job").one().status != "queued"
    )


def test_late_result_cannot_settle_replaced_lease(context):
    db, job, assignment, executor, client, _ = context
    original = client.result

    def late_result(*args):
        receipt = original(*args)
        job.lease_token = "superseded"
        db.commit()
        return receipt

    client.result = late_result
    with pytest.raises(PermissionError, match="STALE_OR_EXPIRED"):
        executor.execute(assignment)
    record = db.get(AzureExecutionRecord, job.program_job_id)
    assert record.state == "fenced"
    assert record.receipt_json is None
    assert client.stops == 1
    assert job.outcome is None


@pytest.mark.parametrize(
    "field", ["assignment", "checksum", "lease", "execution", "output"]
)
def test_result_verification_is_not_azure_status_only(context, field):
    _, _, assignment, executor, client, _ = context
    original = client.result

    def wrong_result(*args):
        receipt = original(*args)
        if field == "assignment":
            return replace(receipt, assignment_id="wrong")
        if field == "checksum":
            return replace(receipt, input_checksum="f" * 64)
        output = dict(receipt.output)
        if field == "lease":
            output["lease_digest"] = "wrong"
        elif field == "execution":
            output["execution_reference"] = "wrong"
        else:
            return replace(receipt, output_checksum="f" * 64)
        return replace(
            receipt, output=output, output_checksum=canonical_checksum(output)
        )

    client.result = wrong_result
    receipt = executor.execute(assignment)
    assert receipt.blocker_code == "AZURE_RESULT_INVALID"
    executor.settle(assignment, receipt)


def test_crash_before_start_response_preserves_unknown_and_never_restarts(context):
    db, job, assignment, executor, client, _ = context

    def crash(*args):
        raise RuntimeError("simulated process interruption")

    client.start = crash
    with pytest.raises(RuntimeError):
        executor.execute(assignment)
    record = db.get(AzureExecutionRecord, job.program_job_id)
    assert record.state == "interrupted"
    assert json.loads(record.evidence_json)["start_disposition"] == "unknown"
    receipt = executor.resume(assignment)
    assert receipt.blocker_code == "AZURE_START_OUTCOME_UNKNOWN"
    executor.settle(assignment, receipt)
    assert client.starts == 0


def test_retry_uses_canonical_new_revision_and_fresh_admission(context):
    db, old, assignment, executor, client, grant = context
    client.fail_on = "verify"
    receipt = executor.execute(assignment)
    executor.settle(assignment, receipt)
    repo = PersistentProgramRepository(db)
    program = repo.create_program(
        owner="owner",
        title="Governed retry revision",
        objective="Retry repaired provider",
        jobs=[
            ProgramJobSpec(
                "azure-job-retry-1",
                AZURE_ROLE,
                "Retry input",
                "example/repo",
                inputs={
                    "retry_of": old.program_job_id,
                    "retry_reason": "provider repaired",
                },
            )
        ],
        dependencies=[],
    )
    repo.start(owner="owner", program_id=program.program_id)
    job = PersistentProgramWorker(db).claim(
        worker_id="worker",
        owner="owner",
        allowed_role_keys=frozenset({AZURE_ROLE}),
    )
    retry = governed_assignment_from_claimed_job(db, owner="owner", job=job)
    assert retry.assignment_id != assignment.assignment_id
    executor.lease_token = job.lease_token
    grant = replace(
        grant,
        program_job_id=job.program_job_id,
        input_checksum=retry.verified_input_checksum(),
        lease_digest=lease_digest(job.lease_token),
    )
    executor.grant_resolver = lambda assignment, digest: grant
    client.fail_on = None
    result = executor.execute(retry)
    executor.settle(retry, result)
    assert job.outcome == "DELIVERED"
    assert old.outcome == "BLOCKED"
    assert db.query(AzureExecutionRecord).count() == 2


def test_brain_to_calyx_fake_azure_demonstration():
    result = run_demo()
    assert result["brain_admission"] == "admitted"
    assert result["receipt_verified"] is True
    assert result["settlement"] == "DELIVERED"
    assert result["replenishment_eligible"] is True
    assert result["network_calls"] == result["spend"] == 0


def test_arm_start_202_poll_and_stop_are_scoped_and_bounded():
    config = demo_config()
    execution = config.resource_id + "/executions/example"
    operation = config.resource_id + "/operationResults/example"
    calls = []
    responses = iter(
        [
            AzureHttpResponse(
                202, {}, {"location": "https://management.azure.com" + operation}
            ),
            AzureHttpResponse(202, {}, {}),
            AzureHttpResponse(200, {"id": execution}, {}),
            AzureHttpResponse(200, {"properties": {"status": "Succeeded"}}, {}),
            AzureHttpResponse(200, {}, {}),
        ]
    )

    def http(method, url, body, timeout):
        calls.append((method, url, body, timeout))
        return next(responses)

    client = AzureContainerAppsJobClient(http, lambda *_: None)
    reference = client.start(config, {"assignment_id": "example"}, 3)
    assert reference == operation
    assert client.observe(config, reference, 3).status == "Processing"
    reference = client.observe(config, reference, 3).execution_reference
    assert client.observe(config, reference, 3).status == "Succeeded"
    client.stop(config, reference, 3)
    assert calls[-1][1].endswith("/executions/example/stop?api-version=2024-03-01")
    assert all(call[-1] == 3 for call in calls)
    assert calls[0][2]["containers"][0]["env"][0]["name"] == "CALYX_EXECUTION_PAYLOAD"


@pytest.mark.parametrize(
    "reference",
    [
        "https://evil.invalid/steal",
        "https://management.azure.com/subscriptions/other",
        "/subscriptions/other",
        "https://management.azure.com@evil.invalid/steal",
    ],
)
def test_arm_rejects_cross_scope_completion_urls(reference):
    from app.calyx_orchestrator.azure_execution_adapter import AzureApiError

    client = AzureContainerAppsJobClient(
        lambda *_: pytest.fail("network called"), lambda *_: None
    )
    with pytest.raises(AzureApiError, match="REFERENCE"):
        client.observe(demo_config(), reference, 1)


def _job_response(config):
    return {
        "id": config.resource_id,
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {config.job_identity_resource_id: {}},
        },
        "properties": {
            "environmentId": (
                f"/subscriptions/{config.subscription_id}/resourceGroups/{config.resource_group}"
                f"/providers/Microsoft.App/managedEnvironments/{config.environment_name}"
            ),
            "configuration": {
                "triggerType": "Manual",
                "replicaRetryLimit": 0,
                "replicaTimeout": 60,
                "manualTriggerConfig": {"parallelism": 1, "replicaCompletionCount": 1},
            },
            "template": {
                "containers": [
                    {
                        "name": config.container_name,
                        "image": config.image,
                        "resources": {"cpu": 0.5, "memory": "1Gi"},
                    }
                ]
            },
        },
    }


@pytest.mark.parametrize(
    "change",
    [
        "valid",
        "environment",
        "identity",
        "scheduled",
        "retries",
        "timeout",
        "replicas",
        "image",
        "command",
        "volume",
        "malformed",
    ],
)
def test_real_client_checks_existing_bounded_job_contract(change):
    from app.calyx_orchestrator.azure_execution_adapter import AzureApiError

    config = demo_config()
    body = _job_response(config)
    properties = body["properties"]
    configuration = properties["configuration"]
    container = properties["template"]["containers"][0]
    if change == "environment":
        properties["environmentId"] = "/wrong"
    elif change == "identity":
        body["identity"]["userAssignedIdentities"] = {}
    elif change == "scheduled":
        configuration["triggerType"] = "Schedule"
    elif change == "retries":
        configuration["replicaRetryLimit"] = 1
    elif change == "timeout":
        configuration["replicaTimeout"] = config.max_runtime_seconds + 1
    elif change == "replicas":
        configuration["manualTriggerConfig"]["parallelism"] = 2
    elif change == "image":
        container["image"] = "mutable:latest"
    elif change == "command":
        container["command"] = ["unapproved-command"]
    elif change == "volume":
        properties["template"]["volumes"] = [{"name": "unapproved"}]
    elif change == "malformed":
        body = {"properties": None}
    client = AzureContainerAppsJobClient(
        lambda *_: AzureHttpResponse(200, body, {}),
        lambda *_: None,
    )
    if change == "valid":
        client.verify_job(config, 3)
    else:
        with pytest.raises(AzureApiError, match="CONTRACT"):
            client.verify_job(config, 3)


def test_concurrent_duplicate_dispatch_has_only_one_start(context):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    db, job, assignment, executor, client, grant = context
    token = job.lease_token
    barrier = threading.Barrier(2)

    def dispatch():
        with Session(db.get_bind()) as session:
            adapter = AzureContainerAppsExecutor(
                session,
                config=executor.config,
                client=client,
                owner="owner",
                worker_id="worker",
                lease_token=token,
                grant_resolver=lambda assignment, digest: grant,
            )
            barrier.wait(timeout=5)
            try:
                return adapter.execute(assignment).state
            except PermissionError as exc:
                return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: dispatch(), range(2)))
    assert sorted(results) == sorted(
        [ExecutionState.DELIVERED, "AZURE_DUPLICATE_DISPATCH"]
    )
    assert client.starts == 1


def test_known_execution_resumes_after_process_interruption(context):
    db, job, assignment, executor, client, _ = context
    original = client.observe

    def disappear(*_):
        raise KeyboardInterrupt("simulate process loss")

    client.observe = disappear
    with pytest.raises(KeyboardInterrupt):
        executor.execute(assignment)
    record = db.get(AzureExecutionRecord, job.program_job_id)
    deadline = json.loads(record.evidence_json)["deadline_at"]
    assert record.execution_reference
    client.observe = original
    receipt = executor.resume(assignment)
    executor.settle(assignment, receipt)
    assert client.starts == 1
    assert json.loads(record.evidence_json)["deadline_at"] == deadline


def test_runtime_deadline_is_enforced_even_before_poll_budget(context):
    _, _, assignment, executor, client, _ = context
    client.statuses = ("Running",)
    now = [0.0]
    executor.monotonic = lambda: now[0]
    executor.sleep = lambda seconds: now.__setitem__(0, now[0] + seconds)
    receipt = executor.execute(replace(assignment, timeout_seconds=1))
    assert receipt.state == ExecutionState.TIMED_OUT
    assert now[0] == 1
    assert client.polls == client.starts == client.stops == 1


def test_resume_does_not_extend_elapsed_original_deadline(context):
    db, job, assignment, executor, client, _ = context
    original = client.observe
    client.observe = lambda *_: (_ for _ in ()).throw(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        executor.execute(assignment)
    record = db.get(AzureExecutionRecord, job.program_job_id)
    evidence = json.loads(record.evidence_json)
    evidence["deadline_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    ).isoformat()
    record.evidence_json = json.dumps(evidence)
    db.commit()
    client.observe = original
    receipt = executor.resume(assignment)
    assert receipt.blocker_code == "AZURE_RECOVERY_FAILED"
    assert client.polls == 0
    assert client.starts == client.stops == 1


def test_settlement_rejects_forged_unrecorded_receipt(context):
    _, _, assignment, executor, _, _ = context
    receipt = executor.execute(assignment)
    output = {**receipt.output, "result": "forged"}
    forged = replace(receipt, output=output, output_checksum=canonical_checksum(output))
    with pytest.raises(PermissionError, match="UNRECORDED_RECEIPT"):
        executor.settle(assignment, forged)


@pytest.mark.parametrize("payload", ["[]", "{}", '{"output":[],"evidence_uris":[]}'])
def test_blob_receipt_shape_fails_closed(payload):
    from app.calyx_orchestrator.azure_execution_adapter import _decode_receipt

    with pytest.raises((ValueError, TypeError)):
        _decode_receipt(payload)


def test_configuration_rejects_invalid_bounds():
    for changes in (
        {"max_runtime_seconds": 0},
        {"max_polls": 0},
        {"api_timeout_seconds": 31},
        {"max_cost_microusd": 0},
        {"image": "mutable:latest"},
        {"job_name": "../another-job"},
        {"managed_identity_client_id": ""},
    ):
        with pytest.raises(ValueError):
            replace(demo_config(), **changes).verify()
    with pytest.raises(ValueError):
        AzureJobConfig.from_environ({"CALYX_AZURE_ENABLED": "maybe"})


def test_cancelled_assignment_does_not_start_azure(context):
    _, job, assignment, executor, client, _ = context
    cancelled = replace(assignment, cancelled=True)
    receipt = executor.execute(cancelled)
    assert receipt.state == ExecutionState.CANCELLED
    executor.settle(cancelled, receipt)
    assert job.outcome == "CANCELLED"
    assert client.starts == 0


def test_authorization_lookup_failure_retains_known_prestart_state(context):
    db, job, assignment, executor, client, _ = context

    def unavailable(*_):
        raise RuntimeError("unavailable approved reservation store")

    executor.grant_resolver = unavailable
    with pytest.raises(RuntimeError):
        executor.execute(assignment)
    record = db.get(AzureExecutionRecord, job.program_job_id)
    assert record.state == "authorization_failed"
    receipt = executor.resume(assignment)
    assert receipt.blocker_code == "AZURE_PRESTART_INTERRUPTED"
    assert json.loads(record.evidence_json)["reconciliation_required"] is False
    assert client.starts == 0


def test_lease_expiring_during_observation_cannot_complete(context):
    db, job, assignment, executor, client, _ = context
    original = client.observe

    def expire(*args):
        observation = original(*args)
        job.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
        return observation

    client.observe = expire
    with pytest.raises(PermissionError, match="STALE_OR_EXPIRED"):
        executor.execute(assignment)
    assert db.get(AzureExecutionRecord, job.program_job_id).state == "fenced"
    assert job.outcome is None
    assert client.starts == client.stops == 1


def test_managed_http_does_not_follow_redirects_or_expose_tokens(monkeypatch):
    from types import SimpleNamespace

    from app.calyx_orchestrator.azure_execution_adapter import AzureApiError
    from app.calyx_orchestrator.azure_job_client import ManagedAzureHttp

    calls = []
    scopes = []

    class Credential:
        def get_token(self, scope):
            scopes.append(scope)
            return SimpleNamespace(token="fake-private-token")

    class Response:
        status_code = 302

        def __init__(self):
            self.headers = {"Location": "https://evil.invalid"}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def iter_content(self, chunk_size):
            return iter([b"{}"])

    def request(*args, **kwargs):
        calls.append((args, kwargs))
        return Response()

    monkeypatch.setattr("requests.request", request)
    http = ManagedAzureHttp(Credential())
    with pytest.raises(AzureApiError, match="HTTP_302") as error:
        http("GET", "https://management.azure.com/fake", None, 3)
    assert "fake-private-token" not in str(error.value)
    assert scopes == ["https://management.azure.com/.default"]
    assert calls[0][1]["allow_redirects"] is False
    assert 0 < calls[0][1]["timeout"] <= 3


def test_arm_and_blob_response_size_and_deadline_are_bounded(monkeypatch):
    import time

    from app.calyx_orchestrator.azure_execution_adapter import AzureApiError
    from app.calyx_orchestrator.azure_job_client import MAX_RESPONSE_BYTES, _content

    class Response:
        def iter_content(self, chunk_size):
            return iter([b"x" * (MAX_RESPONSE_BYTES + 1)])

    with pytest.raises(AzureApiError, match="TOO_LARGE"):
        _content(Response(), time.monotonic() + 3)
    with pytest.raises(AzureApiError, match="DEADLINE"):
        _content(Response(), time.monotonic() - 1)

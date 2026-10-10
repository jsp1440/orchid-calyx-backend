from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.calyx_orchestrator.azure_execution_adapter import _decode_receipt
from app.calyx_orchestrator.azure_job_client import (
    AzureContainerAppsJobClient,
    AzureHttpResponse,
)
from app.calyx_orchestrator.azure_worker import (
    ManagedBlobReceiptWriter,
    WorkerContractError,
    WorkerEnvelope,
    execute_envelope,
    failure_receipt,
    receipt_json,
)
from app.calyx_orchestrator.executor import canonical_checksum
from scripts.oc_azure_container_proof import DockerWorkerRunner, run_proof
from scripts.oc_azure_execution_demo import demo_config


@pytest.fixture
def payload():
    program_id, assignment_id = str(uuid4()), str(uuid4())
    inputs = {
        "program": {
            "program_id": program_id,
            "title": "Bounded verification",
            "objective": "Validate",
        },
        "job": {
            "program_job_id": assignment_id,
            "job_key": "test-job",
            "role_key": "azure_bounded_job",
            "title": "Verify input",
            "repository": "example/repo",
            "branch": None,
            "mutating_intent": False,
            "attempt_count": 1,
        },
        "governance": {
            "mode": "bounded_dry_run",
            "external_execution_authorized": False,
            "repository_code_execution_authorized": False,
            "automatic_merge_authorized": False,
            "deployment_authorized": False,
            "publication_authorized": False,
            "production_graph_mutation_authorized": False,
        },
    }
    return {
        "assignment_id": assignment_id,
        "program_id": program_id,
        "job_key": "test-job",
        "input_checksum": canonical_checksum(inputs),
        "lease_digest": "a" * 64,
        "lease_expires_at": (datetime.now(UTC) + timedelta(seconds=300)).isoformat(),
        "timeout_seconds": 60,
        "inputs": inputs,
        "requested_capabilities": [
            "validate_input",
            "produce_receipt",
            "collect_evidence_uris",
        ],
        "evidence_uris": [
            f"calyx:program/{program_id}",
            f"calyx:program-job/{assignment_id}",
        ],
        "approval_reference": "fake:test-no-spend",
    }


REFERENCE = demo_config().resource_id + "/executions/fake-worker"


def parse(payload):
    return WorkerEnvelope.parse(
        json.dumps(payload), execution_reference=REFERENCE, fake=True
    )


def native_runner(payload, reference, timeout):
    result = subprocess.run(
        [sys.executable, "-m", "app.calyx_orchestrator.azure_worker", "--fake"],
        env={
            **os.environ,
            "CALYX_EXECUTION_PAYLOAD": json.dumps(payload),
            "CALYX_WORKER_EXECUTION_REFERENCE": reference,
            "CALYX_AZURE_WORKER_TEST_MODE": "provider-free",
            "CALYX_AZURE_WORKER_ENABLED": "false",
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_entrypoint_through_canonical_brain_and_calyx_lease_settlement():
    proof = run_proof(native_runner)
    assert proof["brain_admission"] == "admitted"
    assert proof["worker_mode"] == "provider_free_container"
    assert proof["azure_starts"] == 1
    assert proof["settlement"] == "DELIVERED"
    assert proof["durable_receipt"] and proof["duplicate_fenced"]
    assert proof["stale_settlement_fenced"] and proof["brain_replenishment_eligible"]
    assert proof["azure_calls"] == 0


def test_worker_emits_existing_verifiable_execution_receipt(payload):
    receipt = execute_envelope(parse(payload))
    decoded = _decode_receipt(receipt_json(receipt))
    assert decoded == receipt
    assert decoded.input_checksum == payload["input_checksum"]
    assert decoded.output["lease_digest"] == payload["lease_digest"]
    assert decoded.output["production_access"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        "expired",
        "naive_expiry",
        "checksum",
        "lease_digest",
        "id",
        "program",
        "capabilities",
        "governance",
        "mutating",
        "role",
        "operation",
        "attempt",
        "timeout",
        "boolean_timeout",
        "provenance",
        "extra",
    ],
)
def test_worker_rejects_invalid_or_unauthorized_work(payload, mutation):
    if mutation == "expired":
        payload["lease_expires_at"] = (
            datetime.now(UTC) - timedelta(seconds=1)
        ).isoformat()
    elif mutation == "naive_expiry":
        payload["lease_expires_at"] = datetime.now(UTC).replace(tzinfo=None).isoformat()
    elif mutation == "checksum":
        payload["input_checksum"] = "b" * 64
    elif mutation == "lease_digest":
        payload["lease_digest"] = "invalid"
    elif mutation == "id":
        payload["assignment_id"] = "not-a-durable-identity"
    elif mutation == "program":
        payload["inputs"]["program"]["program_id"] = str(uuid4())
    elif mutation == "capabilities":
        payload["requested_capabilities"] = ["shell", "deploy"]
    elif mutation == "governance":
        payload["inputs"]["governance"]["publication_authorized"] = True
    elif mutation == "mutating":
        payload["inputs"]["job"]["mutating_intent"] = True
    elif mutation == "role":
        payload["inputs"]["job"]["role_key"] = "arbitrary-code-worker"
    elif mutation == "operation":
        payload["inputs"]["job"]["operation"] = "run_shell"
    elif mutation == "attempt":
        payload["inputs"]["job"]["attempt_count"] = 4
    elif mutation == "timeout":
        payload["timeout_seconds"] = 3600
    elif mutation == "boolean_timeout":
        payload["timeout_seconds"] = True
    elif mutation == "provenance":
        payload["evidence_uris"] = ["calyx:unrelated"]
    else:
        payload["lease_token"] = "must-never-be-sent"
    with pytest.raises((ValueError, TypeError)):
        parse(payload)


@pytest.mark.parametrize("encoded", ['{"a":1,"a":2}', '{"a":NaN}', "{}", "x" * 16385])
def test_json_boundary_rejects_ambiguity_and_size(encoded):
    with pytest.raises(ValueError):
        WorkerEnvelope.parse(encoded, execution_reference=REFERENCE, fake=True)


def test_worker_checks_deadline_after_verification(payload):
    envelope = parse(payload)
    times = iter([datetime.now(UTC), envelope.deadline + timedelta(seconds=1)])
    with pytest.raises(TimeoutError):
        execute_envelope(envelope, clock=lambda: next(times))


def test_worker_defaults_disabled_and_sanitizes_failure(payload):
    result = subprocess.run(
        [sys.executable, "-m", "app.calyx_orchestrator.azure_worker"],
        env={
            **os.environ,
            "CALYX_AZURE_WORKER_ENABLED": "false",
            "CALYX_EXECUTION_PAYLOAD": json.dumps(payload),
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 2
    assert "WORKER_DISABLED" in result.stderr
    assert payload["lease_digest"] not in result.stderr
    assert not result.stdout


def test_failure_receipt_is_explicit_not_delivered(payload):
    receipt = failure_receipt(parse(payload), "WORKER_INTERRUPTED")
    receipt.verify()
    assert receipt.state == "blocked"
    assert receipt.outcome == "BLOCKED"
    assert receipt.blocker_code == "WORKER_INTERRUPTED"


@pytest.mark.parametrize("status", [201, 412, 403, 302])
def test_managed_receipt_upload_is_immutable_and_scoped(payload, monkeypatch, status):
    calls = []
    scopes = []

    class Credential:
        def get_token(self, scope):
            scopes.append(scope)
            return SimpleNamespace(token="fake-secret")

    class Response:
        status_code = status

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    def put(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr("requests.put", put)
    writer = ManagedBlobReceiptWriter(
        {
            "CALYX_RECEIPT_STORAGE_ACCOUNT": "fakeaccount",
            "CALYX_RECEIPT_CONTAINER": "private-receipts",
            "CALYX_WORKER_IDENTITY_CLIENT_ID": str(uuid4()),
        },
        credential=Credential(),
    )
    envelope = parse(payload)
    receipt = execute_envelope(envelope)
    if status == 201:
        uri = writer.write(envelope, receipt)
        assert uri.startswith("azure-blob:fakeaccount/private-receipts/")
    else:
        with pytest.raises(WorkerContractError, match=f"HTTP_{status}"):
            writer.write(envelope, receipt)
    assert scopes == ["https://storage.azure.com/.default"]
    assert calls[0][1]["headers"]["If-None-Match"] == "*"
    assert calls[0][1]["allow_redirects"] is False
    stored = _decode_receipt(calls[0][1]["data"].decode())
    assert stored.evidence_uris[-1].startswith("azure-blob:")
    assert calls[0][0].endswith(
        f"/{payload['assignment_id']}/{payload['lease_digest']}/receipt.json"
    )


def test_worker_environment_is_exactly_preserved_in_arm_start(payload):
    config = replace(
        demo_config(),
        receipt_storage_account="fakeaccount",
        receipt_container="private-receipts",
        worker_identity_client_id=str(uuid4()),
    )
    config.verify()
    calls = []

    def http(method, url, body, timeout):
        calls.append(body)
        return AzureHttpResponse(200, {"id": REFERENCE}, {})

    client = AzureContainerAppsJobClient(http, lambda *_: None)
    client.start(config, payload, 3)
    env = calls[0]["containers"][0]["env"]
    assert env[:-1] == config.worker_environment()
    assert env[-1]["name"] == "CALYX_EXECUTION_PAYLOAD"


def test_template_matches_requested_deployment_boundary():
    template = json.loads(Path("containers/azure-worker/job.template.json").read_text())
    assert template["metadata"]["subscriptionDisplayName"] == "Azure subscription 1"
    assert template["metadata"]["resourceGroup"] == "RG-ORCHID-CONTINUUM-AGENTS"
    assert template["parameters"]["workerEnabled"]["defaultValue"] is False
    assert template["parameters"]["location"]["defaultValue"] == "westus2"
    assert template["variables"]["jobName"] == "oc-brain-worker"
    job = template["resources"][0]["properties"]
    assert job["workloadProfileName"] == "Consumption"
    assert job["configuration"]["triggerType"] == "Manual"
    assert job["configuration"]["replicaRetryLimit"] == 0
    assert job["configuration"]["manualTriggerConfig"]["parallelism"] == 1
    container = job["template"]["containers"][0]
    assert container["resources"] == {"cpu": 0.5, "memory": "1Gi"}
    assert "command" not in container and "args" not in container


def test_actual_container_runner_refuses_absent_engine(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    with pytest.raises(RuntimeError, match="LOCAL_CONTAINER_ENGINE_MISSING"):
        DockerWorkerRunner("never-pull:test")

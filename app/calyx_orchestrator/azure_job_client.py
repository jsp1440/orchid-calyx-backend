"""Bounded ARM/managed-identity transport and a provider-free fake."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import requests

from .azure_execution_adapter import (
    AZURE_EXECUTOR_KEY,
    AzureApiError,
    AzureJobConfig,
    AzureObservation,
    _decode_receipt,
)
from .engineering_core import TerminalOutcome
from .executor import ExecutionReceipt, ExecutionState, canonical_checksum

API_VERSION = "2024-03-01"
ARM_ORIGIN = "https://management.azure.com"
MAX_RESPONSE_BYTES = 1_000_000


class TokenCredential(Protocol):
    def get_token(self, *scopes: str) -> object: ...


@dataclass(frozen=True, slots=True)
class AzureHttpResponse:
    status: int
    body: Mapping[str, object]
    headers: Mapping[str, str]


def _token(credential: TokenCredential, scope: str) -> str:
    try:
        token = credential.get_token(scope)
    except Exception as exc:
        raise AzureApiError(f"AZURE_MANAGED_AUTH_{type(exc).__name__}") from exc
    token_value = getattr(token, "token", None)
    if not isinstance(token_value, str) or not token_value:
        raise AzureApiError("AZURE_MANAGED_TOKEN_UNAVAILABLE")
    return token_value


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AzureApiError("AZURE_HTTP_DEADLINE_EXCEEDED")
    return remaining


def _content(response: requests.Response, deadline: float) -> bytes:
    content = bytearray()
    for chunk in response.iter_content(chunk_size=65536):
        _remaining(deadline)
        content.extend(chunk)
        if len(content) > MAX_RESPONSE_BYTES:
            raise AzureApiError("AZURE_RESPONSE_TOO_LARGE")
    _remaining(deadline)
    return bytes(content)


def managed_identity_credential(config: AzureJobConfig) -> TokenCredential:
    """Lazy optional dependency; no developer CLI/client-secret fallback."""
    if not config.enabled:
        raise PermissionError("AZURE_PROVIDER_DISABLED")
    config.verify()
    from azure.identity import ManagedIdentityCredential

    return ManagedIdentityCredential(
        client_id=config.managed_identity_client_id,
        connection_timeout=config.api_timeout_seconds,
        read_timeout=config.api_timeout_seconds,
        retry_total=0,
    )


class ManagedAzureHttp:
    def __init__(self, credential: TokenCredential) -> None:
        self.credential = credential

    def __call__(
        self,
        method: str,
        url: str,
        body: Mapping[str, object] | None,
        timeout: float,
    ) -> AzureHttpResponse:
        deadline = time.monotonic() + timeout
        token_value = _token(self.credential, "https://management.azure.com/.default")
        try:
            with requests.request(
                method,
                url,
                json=body,
                headers={"Authorization": f"Bearer {token_value}"},
                timeout=_remaining(deadline),
                allow_redirects=False,
                stream=True,
            ) as response:
                content = _content(response, deadline)
                if response.status_code not in {200, 202, 204}:
                    raise AzureApiError(f"AZURE_HTTP_{response.status_code}")
                value = json.loads(content) if content else {}
                if not isinstance(value, dict):
                    raise AzureApiError("AZURE_RESPONSE_OBJECT_REQUIRED")
                return AzureHttpResponse(
                    response.status_code,
                    value,
                    {key.lower(): value for key, value in response.headers.items()},
                )
        except (requests.RequestException, json.JSONDecodeError) as exc:
            # Provider response bodies and credential error strings can contain secrets.
            raise AzureApiError(f"AZURE_TRANSPORT_{type(exc).__name__}") from exc


class AzureContainerAppsJobClient:
    """Uses only get/start/execution-get/stop on one pre-existing manual job.

    The result reader is a trusted bounded artifact dependency. It must fetch
    the immutable receipt for (assignment_id, lease_digest), never synthesize
    success from the ARM status. No resources or schedules are created here.
    """

    def __init__(
        self,
        http: Callable[
            [str, str, Mapping[str, object] | None, float], AzureHttpResponse
        ],
        result_reader: Callable[[str, str, float], ExecutionReceipt],
    ) -> None:
        self.http, self.result_reader = http, result_reader

    def _call(
        self,
        config: AzureJobConfig,
        method: str,
        path: str,
        timeout: float,
        body: Mapping[str, object] | None = None,
    ) -> AzureHttpResponse:
        if not config.enabled:
            raise PermissionError("AZURE_PROVIDER_DISABLED")
        url = f"{ARM_ORIGIN}{path}?api-version={API_VERSION}"
        return self.http(method, url, body, timeout)

    def verify_job(self, config: AzureJobConfig, timeout: float) -> None:
        response = self._call(config, "GET", config.resource_id, timeout)
        try:
            properties = response.body["properties"]
            configuration = properties["configuration"]
            template = properties["template"]
            identity = response.body["identity"]
            environment_id = (
                f"/subscriptions/{config.subscription_id}/resourceGroups/{config.resource_group}"
                f"/providers/Microsoft.App/managedEnvironments/{config.environment_name}"
            )
            if (
                response.body["id"].lower() != config.resource_id.lower()
                or properties["environmentId"].lower() != environment_id.lower()
                or identity["type"] != "UserAssigned"
                or set(identity["userAssignedIdentities"])
                != {config.job_identity_resource_id}
                or configuration["triggerType"] != "Manual"
                or configuration["replicaRetryLimit"] != 0
                or not 1
                <= configuration["replicaTimeout"]
                <= config.max_runtime_seconds
                or configuration["manualTriggerConfig"]
                != {"parallelism": 1, "replicaCompletionCount": 1}
                or len(template["containers"]) != 1
                or template.get("initContainers")
                or template.get("volumes")
            ):
                raise AzureApiError("AZURE_JOB_CONTRACT_MISMATCH")
            container = template["containers"][0]
            if (
                container["name"] != config.container_name
                or container["image"] != config.image
                or container["resources"].get("cpu") != 0.5
                or container["resources"].get("memory") != "1Gi"
                or any(
                    container.get(key)
                    for key in ("command", "args", "env", "volumeMounts")
                )
            ):
                raise AzureApiError("AZURE_CONTAINER_CONTRACT_MISMATCH")
        except (KeyError, TypeError, AttributeError, IndexError) as exc:
            raise AzureApiError("AZURE_JOB_CONTRACT_UNVERIFIABLE") from exc

    def _reference(self, config: AzureJobConfig, reference: str) -> str:
        parsed = urlsplit(reference)
        if parsed.scheme or parsed.netloc:
            if parsed.scheme != "https" or parsed.netloc != "management.azure.com":
                raise AzureApiError("AZURE_REFERENCE_ORIGIN_INVALID")
            path = parsed.path
        else:
            if parsed.query or parsed.fragment:
                raise AzureApiError("AZURE_REFERENCE_INVALID")
            path = reference
        # Do not follow arbitrary Location URLs, even on management.azure.com.
        prefix = config.resource_id + "/"
        if not path.startswith(prefix) or not re.fullmatch(
            r"(executions|operationResults|operationStatuses)/[A-Za-z0-9_-]+",
            path[len(prefix) :],
        ):
            raise AzureApiError("AZURE_REFERENCE_SCOPE_INVALID")
        return path

    def start(
        self, config: AzureJobConfig, payload: Mapping[str, object], timeout: float
    ) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode()) > 16384:
            raise AzureApiError("AZURE_ASSIGNMENT_PAYLOAD_TOO_LARGE")
        response = self._call(
            config,
            "POST",
            config.resource_id + "/start",
            timeout,
            {
                "containers": [
                    {
                        "name": config.container_name,
                        "image": config.image,
                        "resources": {"cpu": 0.5, "memory": "1Gi"},
                        "env": [{"name": "CALYX_EXECUTION_PAYLOAD", "value": encoded}],
                    }
                ],
            },
        )
        reference = response.body.get("id") or response.headers.get("location")
        if not isinstance(reference, str):
            raise AzureApiError("AZURE_START_REFERENCE_MISSING")
        return self._reference(config, reference)

    def observe(
        self, config: AzureJobConfig, reference: str, timeout: float
    ) -> AzureObservation:
        path = self._reference(config, reference)
        response = self._call(config, "GET", path, timeout)
        if "/executions/" not in path:
            if response.status == 202:
                return AzureObservation("Processing", path, (f"azure-arm:{path}",))
            resolved = response.body.get("id")
            if not isinstance(resolved, str) or "/executions/" not in resolved:
                raise AzureApiError("AZURE_ASYNC_EXECUTION_UNRESOLVED")
            path = self._reference(config, resolved)
            return AzureObservation("Pending", path, (f"azure-arm:{path}",))
        properties = response.body.get("properties")
        status = properties.get("status") if isinstance(properties, dict) else None
        if not isinstance(status, str):
            raise AzureApiError("AZURE_EXECUTION_STATUS_MISSING")
        return AzureObservation(status, path, (f"azure-arm:{path}",))

    def stop(self, config: AzureJobConfig, reference: str, timeout: float) -> None:
        path = self._reference(config, reference)
        if "/executions/" not in path:
            raise AzureApiError("AZURE_STOP_REQUIRES_EXECUTION_ID")
        self._call(config, "POST", path + "/stop", timeout)

    def result(
        self,
        config: AzureJobConfig,
        reference: str,
        assignment_id: str,
        digest: str,
        timeout: float,
    ) -> ExecutionReceipt:
        self._reference(config, reference)
        return self.result_reader(assignment_id, digest, timeout)


class ManagedBlobReceiptReader:
    """Read-only, private Azure Blob receipt retrieval with managed authentication."""

    def __init__(
        self, credential: TokenCredential, *, account: str, container: str
    ) -> None:
        if not re.fullmatch(r"[a-z0-9]{3,24}", account):
            raise ValueError("AZURE_BLOB_ACCOUNT_INVALID")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", container):
            raise ValueError("AZURE_BLOB_CONTAINER_INVALID")
        self.credential = credential
        self.base_url = f"https://{account}.blob.core.windows.net/{container}"

    def __call__(
        self, assignment_id: str, digest: str, timeout: float
    ) -> ExecutionReceipt:
        if not re.fullmatch(r"[a-f0-9-]{36}", assignment_id) or not re.fullmatch(
            r"[a-f0-9]{64}", digest
        ):
            raise AzureApiError("AZURE_ARTIFACT_IDENTITY_INVALID")
        deadline = time.monotonic() + timeout
        token_value = _token(self.credential, "https://storage.azure.com/.default")
        try:
            with requests.get(
                f"{self.base_url}/{assignment_id}/{digest}/receipt.json",
                headers={
                    "Authorization": f"Bearer {token_value}",
                    "x-ms-version": "2024-08-04",
                },
                timeout=_remaining(deadline),
                allow_redirects=False,
                stream=True,
            ) as response:
                if response.status_code != 200:
                    raise AzureApiError(f"AZURE_RESULT_HTTP_{response.status_code}")
                content = _content(response, deadline)
                return _decode_receipt(content.decode("utf-8"))
        except (requests.RequestException, UnicodeDecodeError) as exc:
            raise AzureApiError(f"AZURE_RESULT_TRANSPORT_{type(exc).__name__}") from exc


class FakeAzureJobClient:
    """Deterministic provider-free client; synthetic references are labelled fake."""

    def __init__(self, statuses: tuple[str, ...] = ("Succeeded",)) -> None:
        self.statuses = statuses
        self.starts = 0
        self.polls = 0
        self.stops = 0
        self.fail_on: str | None = None
        self.payload: dict[str, object] = {}

    def _fail(self, operation: str) -> None:
        if self.fail_on == operation:
            raise AzureApiError(f"FAKE_AZURE_{operation.upper()}_FAILURE")

    def verify_job(self, config: AzureJobConfig, timeout: float) -> None:
        self._fail("verify")

    def start(
        self, config: AzureJobConfig, payload: Mapping[str, object], timeout: float
    ) -> str:
        self._fail("start")
        self.starts += 1
        self.payload = dict(payload)
        return f"{config.resource_id}/executions/fake-{self.starts}"

    def observe(
        self, config: AzureJobConfig, reference: str, timeout: float
    ) -> AzureObservation:
        self._fail("observe")
        status = self.statuses[min(self.polls, len(self.statuses) - 1)]
        self.polls += 1
        return AzureObservation(status, reference, (f"fake-azure:logs/{self.starts}",))

    def stop(self, config: AzureJobConfig, reference: str, timeout: float) -> None:
        self._fail("stop")
        self.stops += 1

    def result(
        self,
        config: AzureJobConfig,
        reference: str,
        assignment_id: str,
        digest: str,
        timeout: float,
    ) -> ExecutionReceipt:
        self._fail("result")
        output = {
            "mode": "provider_free_fake_azure",
            "lease_digest": digest,
            "execution_reference": reference,
            "result": "deterministic verification completed",
        }
        return ExecutionReceipt(
            assignment_id,
            self.payload["program_id"],
            self.payload["job_key"],
            AZURE_EXECUTOR_KEY,
            ExecutionState.DELIVERED,
            TerminalOutcome.DELIVERED,
            self.payload["input_checksum"],
            canonical_checksum(output),
            output,
            ("fake-azure:receipt/verified",),
        )

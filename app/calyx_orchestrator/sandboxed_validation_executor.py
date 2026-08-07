from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from .engineering_core import TerminalOutcome
from .executor import ExecutionReceipt, ExecutionState, GovernedAssignment, canonical_checksum
from .repository_evidence_executor import RepositoryEvidenceExecutor

SANDBOXED_VALIDATION_ROLE = "isolated_workspace_executable_validator"
SANDBOX_MARKER = ".calyx-validation-sandbox.json"
SANDBOX_SCHEMA = "calyx-validation-sandbox-v1"
SUPPORTED_CAPABILITIES = frozenset(
    {
        "validate_input",
        "produce_receipt",
        "collect_evidence_uris",
        "repository_code_execution",
    }
)
ALLOWED_TARGET_PREFIXES = ("app/", "tests/")
ALLOWED_PRESETS = frozenset({"pytest", "ruff"})
MAX_TARGETS = 24
MAX_TARGET_BYTES = 2_000_000
MAX_TOTAL_TARGET_BYTES = 8_000_000
MAX_CAPTURE_BYTES = 64_000
MAX_TIMEOUT_SECONDS = 120


@dataclass(frozen=True, slots=True)
class ValidationRequest:
    preset: str
    targets: tuple[str, ...]
    expected_sha256: dict[str, str]
    timeout_seconds: int


class SandboxedExecutableValidationExecutor:
    """Run fixed validation presets only inside an externally enforced sandbox.

    This adapter does not establish an OS/network sandbox by itself. It fails closed
    unless the pre-created workspace contains a trusted marker asserting that network,
    credential access, shell access, and package installation are disabled by the
    runtime boundary. Commands are internal argv presets; caller-supplied command text
    is never executed.
    """

    executor_key = "isolated_workspace_executable_validator_v1"

    def __init__(
        self,
        *,
        workspace_root=None,
        repository_name: str | None = None,
    ) -> None:
        self._reader = RepositoryEvidenceExecutor(
            workspace_root=workspace_root,
            repository_name=repository_name,
        )
        self.workspace_root = self._reader.workspace_root
        self.repository_name = self._reader.repository_name

    def execute(self, assignment: GovernedAssignment) -> ExecutionReceipt:
        if assignment.role_key != SANDBOXED_VALIDATION_ROLE:
            raise PermissionError("SANDBOX_VALIDATION_ROLE_REQUIRED")
        if assignment.cancelled:
            raise PermissionError("SANDBOX_VALIDATION_CANCELLED")
        if assignment.timeout_seconds <= 0:
            raise PermissionError("SANDBOX_VALIDATION_TIMEOUT_INVALID")

        requested = set(assignment.requested_capabilities)
        unsupported = sorted(requested - SUPPORTED_CAPABILITIES)
        if unsupported:
            raise PermissionError(
                f"SANDBOX_VALIDATION_UNSUPPORTED_CAPABILITY:{','.join(unsupported)}"
            )
        if "repository_code_execution" not in requested:
            raise PermissionError("SANDBOX_VALIDATION_EXECUTION_CAPABILITY_REQUIRED")

        job = assignment.inputs.get("job")
        if not isinstance(job, dict):
            raise TypeError("SANDBOX_VALIDATION_JOB_INPUT_REQUIRED")
        if bool(job.get("mutating_intent")):
            raise PermissionError("SANDBOX_VALIDATION_MUTATING_JOB_PROHIBITED")

        repository = str(job.get("repository") or "").strip()
        branch = str(job.get("branch") or "").strip()
        if repository != self.repository_name:
            raise PermissionError("SANDBOX_VALIDATION_REPOSITORY_MISMATCH")
        if not branch.startswith("autonomy/"):
            raise PermissionError("SANDBOX_VALIDATION_AUTONOMY_BRANCH_REQUIRED")

        checkout = self._reader._checkout_identity()
        if checkout.branch != branch:
            raise PermissionError("SANDBOX_VALIDATION_REVISION_MISMATCH")
        self._verify_sandbox_marker(repository=repository, branch=branch)

        request = self._parse_request(job.get("validation"), assignment.timeout_seconds)
        before = self._verify_targets(request)
        argv = self._argv_for(request)
        env = self._scrubbed_environment()

        try:
            completed = subprocess.run(
                argv,
                cwd=self.workspace_root,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=request.timeout_seconds,
                check=False,
                shell=False,
            )
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            completed = None
            timed_out = True
            stdout = _bounded_bytes(exc.stdout or b"")
            stderr = _bounded_bytes(exc.stderr or b"")
        else:
            stdout = _bounded_bytes(completed.stdout)
            stderr = _bounded_bytes(completed.stderr)

        after = self._verify_targets(request)
        if after != before:
            raise RuntimeError("SANDBOX_VALIDATION_TARGET_CHANGED_DURING_EXECUTION")
        checkout_after = self._reader._checkout_identity()
        if checkout_after != checkout:
            raise RuntimeError("SANDBOX_VALIDATION_CHECKOUT_CHANGED_DURING_EXECUTION")

        input_checksum = assignment.verified_input_checksum()
        if timed_out:
            state = ExecutionState.TIMED_OUT
            outcome = TerminalOutcome.BLOCKED
            blocker_code = "SANDBOX_VALIDATION_COMMAND_TIMEOUT"
            return_code = None
        else:
            assert completed is not None
            return_code = completed.returncode
            if return_code == 0:
                state = ExecutionState.DELIVERED
                outcome = TerminalOutcome.DELIVERED
                blocker_code = None
            else:
                state = ExecutionState.BLOCKED
                outcome = TerminalOutcome.BLOCKED
                blocker_code = "SANDBOX_VALIDATION_COMMAND_FAILED"

        output: dict[str, object] = {
            "status": state.value,
            "executed": True,
            "mode": "authoritative_sandboxed_fixed_command_validation",
            "repository": repository,
            "branch": branch,
            "checkout_commit_sha": checkout.commit_sha,
            "sandbox_attested": True,
            "preset": request.preset,
            "targets": [
                {"path": path, "sha256": before[path]} for path in sorted(before)
            ],
            "return_code": return_code,
            "timed_out": timed_out,
            "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
            "stdout_bytes_captured": len(stdout),
            "stderr_bytes_captured": len(stderr),
            "stdout_truncated": len(stdout) == MAX_CAPTURE_BYTES,
            "stderr_truncated": len(stderr) == MAX_CAPTURE_BYTES,
            "command_source": "internal_preset",
            "shell": False,
            "environment_inherited": False,
            "package_installation": False,
            "workspace_write_authorized": False,
            "git_mutation": False,
            "network_authorized": False,
            "credential_access_authorized": False,
        }
        receipt = ExecutionReceipt(
            assignment_id=assignment.assignment_id,
            program_id=assignment.program_id,
            job_key=assignment.job_key,
            executor_key=self.executor_key,
            state=state,
            outcome=outcome,
            input_checksum=input_checksum,
            output_checksum=canonical_checksum(output),
            output=output,
            evidence_uris=tuple(
                [
                    *assignment.evidence_uris,
                    f"repo-commit:{repository}@{checkout.commit_sha}",
                    *[
                        f"validation-input:{path}#{before[path]}"
                        for path in sorted(before)
                    ],
                ]
            ),
            blocker_code=blocker_code,
        )
        receipt.verify()
        return receipt

    def _verify_sandbox_marker(self, *, repository: str, branch: str) -> None:
        try:
            raw, _ = self._reader._read_workspace_file(SANDBOX_MARKER, 32_768)
        except FileNotFoundError as exc:
            raise PermissionError("SANDBOX_VALIDATION_MARKER_REQUIRED") from exc
        try:
            marker = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PermissionError("SANDBOX_VALIDATION_MARKER_INVALID") from exc
        expected = {
            "schema": SANDBOX_SCHEMA,
            "repository": repository,
            "branch": branch,
            "disposable": True,
            "network_disabled": True,
            "credentials_absent": True,
            "shell_disabled": True,
            "package_installation_disabled": True,
            "subprocess_confinement_enforced": True,
        }
        if not isinstance(marker, dict) or any(
            marker.get(key) != value for key, value in expected.items()
        ):
            raise PermissionError("SANDBOX_VALIDATION_MARKER_MISMATCH")

    @staticmethod
    def _parse_request(value: Any, assignment_timeout: int) -> ValidationRequest:
        if not isinstance(value, dict):
            raise TypeError("SANDBOX_VALIDATION_REQUEST_REQUIRED")
        if set(value) - {"preset", "targets", "expected_sha256", "timeout_seconds"}:
            raise ValueError("SANDBOX_VALIDATION_REQUEST_FIELD_NOT_ALLOWED")
        preset = str(value.get("preset") or "").strip()
        if preset not in ALLOWED_PRESETS:
            raise ValueError("SANDBOX_VALIDATION_PRESET_NOT_ALLOWED")
        raw_targets = value.get("targets")
        expected = value.get("expected_sha256")
        if not isinstance(raw_targets, list) or not raw_targets:
            raise TypeError("SANDBOX_VALIDATION_TARGETS_REQUIRED")
        if len(raw_targets) > MAX_TARGETS:
            raise ValueError("SANDBOX_VALIDATION_TARGET_COUNT_EXCEEDED")
        targets = tuple(str(item).strip() for item in raw_targets)
        if any(not item for item in targets) or len(set(targets)) != len(targets):
            raise ValueError("SANDBOX_VALIDATION_TARGETS_INVALID")
        if not isinstance(expected, dict) or set(expected) != set(targets):
            raise ValueError("SANDBOX_VALIDATION_EXPECTED_HASHES_MISMATCH")
        normalized_hashes: dict[str, str] = {}
        for path, digest in expected.items():
            value_digest = str(digest).strip().lower()
            if len(value_digest) != 64 or any(
                character not in "0123456789abcdef" for character in value_digest
            ):
                raise ValueError(f"SANDBOX_VALIDATION_HASH_INVALID:{path}")
            normalized_hashes[str(path)] = value_digest
        requested_timeout = int(value.get("timeout_seconds") or assignment_timeout)
        timeout_seconds = min(requested_timeout, assignment_timeout, MAX_TIMEOUT_SECONDS)
        if timeout_seconds <= 0:
            raise ValueError("SANDBOX_VALIDATION_TIMEOUT_INVALID")
        return ValidationRequest(
            preset=preset,
            targets=targets,
            expected_sha256=normalized_hashes,
            timeout_seconds=timeout_seconds,
        )

    def _verify_targets(self, request: ValidationRequest) -> dict[str, str]:
        hashes: dict[str, str] = {}
        total = 0
        for target in request.targets:
            path = PurePosixPath(target)
            if (
                path.is_absolute()
                or not path.parts
                or any(part in {"", ".", ".."} for part in path.parts)
            ):
                raise PermissionError("SANDBOX_VALIDATION_PATH_ESCAPE")
            normalized = path.as_posix()
            if not normalized.startswith(ALLOWED_TARGET_PREFIXES):
                raise PermissionError(f"SANDBOX_VALIDATION_PATH_NOT_ALLOWED:{normalized}")
            data, size = self._reader._read_workspace_file(normalized, MAX_TARGET_BYTES)
            total += size
            if total > MAX_TOTAL_TARGET_BYTES:
                raise ValueError("SANDBOX_VALIDATION_TOTAL_TARGET_BYTES_EXCEEDED")
            try:
                data.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError(f"SANDBOX_VALIDATION_TARGET_NOT_UTF8:{normalized}") from exc
            digest = hashlib.sha256(data).hexdigest()
            if request.expected_sha256[normalized] != digest:
                raise ValueError(f"SANDBOX_VALIDATION_TARGET_HASH_MISMATCH:{normalized}")
            hashes[normalized] = digest
        return hashes

    @staticmethod
    def _argv_for(request: ValidationRequest) -> tuple[str, ...]:
        if request.preset == "pytest":
            if any(not target.startswith("tests/") for target in request.targets):
                raise PermissionError("SANDBOX_VALIDATION_PYTEST_TARGET_NOT_TEST")
            return (
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                *request.targets,
            )
        if request.preset == "ruff":
            return (
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--no-cache",
                *request.targets,
            )
        raise ValueError("SANDBOX_VALIDATION_PRESET_NOT_ALLOWED")

    def _scrubbed_environment(self) -> dict[str, str]:
        return {
            "PATH": os.path.dirname(sys.executable),
            "PYTHONPATH": str(self.workspace_root),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "CALYX_VALIDATION_SANDBOX": "1",
        }


def _bounded_bytes(value: bytes) -> bytes:
    return value[:MAX_CAPTURE_BYTES]

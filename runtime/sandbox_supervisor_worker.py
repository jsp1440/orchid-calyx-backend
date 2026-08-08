from __future__ import annotations

import contextlib
import hashlib
import json
import os
import selectors
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

MAX_CAPTURE_BYTES = 262_144
MAX_TARGET_BYTES = 4_194_304
DEFAULT_MEMORY = "1024m"
DEFAULT_CPUS = "2.0"
DEFAULT_PIDS = "128"

TRUSTED_SANDBOX_PROBE = r'''
import os, socket
from pathlib import Path
workspace = Path('/workspace')
for key in ('GITHUB_TOKEN','GH_TOKEN','DATABASE_URL','PGPASSWORD','AZURE_CLIENT_SECRET','AWS_SECRET_ACCESS_KEY'):
    assert not os.environ.get(key), f'credential leaked: {key}'
status = Path('/proc/self/status').read_text(encoding='utf-8')
assert 'NoNewPrivs:\t1' in status
for path in (workspace / '.calyx-write-probe', Path('/calyx-root-write-probe')):
    try:
        path.write_text('forbidden', encoding='utf-8')
    except OSError:
        pass
    else:
        raise AssertionError(f'write unexpectedly succeeded: {path}')
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(1.0)
try:
    result = sock.connect_ex(('1.1.1.1', 443))
finally:
    sock.close()
assert result != 0, 'network connection unexpectedly succeeded'
print('CALYX_EXTERNAL_SANDBOX_PROBE_OK')
'''.strip()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _normalize_api_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urllib.parse.urlparse(normalized)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise ValueError("SANDBOX_SUPERVISOR_API_URL_INVALID")
    if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise PermissionError("SANDBOX_SUPERVISOR_HTTPS_REQUIRED")
    return normalized


def _validate_image_digest(value: str) -> str:
    image = value.strip()
    marker = "@sha256:"
    if marker not in image:
        raise ValueError("SANDBOX_SUPERVISOR_IMMUTABLE_IMAGE_REQUIRED")
    _, digest = image.rsplit(marker, 1)
    if not _is_sha256(digest.lower()):
        raise ValueError("SANDBOX_SUPERVISOR_IMAGE_DIGEST_INVALID")
    return image


def _request_digest(request: Mapping[str, Any]) -> str:
    targets = request.get("targets")
    if not isinstance(targets, list):
        raise TypeError("SANDBOX_SUPERVISOR_TARGETS_INVALID")
    normalized_targets = []
    for item in targets:
        if not isinstance(item, Mapping):
            raise TypeError("SANDBOX_SUPERVISOR_TARGET_INVALID")
        normalized_targets.append(
            {
                "path": str(item.get("path") or "").strip(),
                "sha256": str(item.get("sha256") or "").strip().lower(),
            }
        )
    payload = {
        "schema": "calyx-external-validation-request-v1",
        "repository": str(request.get("repository") or "").strip(),
        "branch": str(request.get("branch") or "").strip(),
        "checkout_commit_sha": str(request.get("checkout_commit_sha") or "").strip().lower(),
        "preset": str(request.get("preset") or "").strip().lower(),
        "targets": sorted(normalized_targets, key=lambda item: item["path"]),
        "timeout_seconds": int(request.get("timeout_seconds") or 0),
    }
    return _canonical_sha256(payload)


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    api_base_url: str
    supervisor_token: str
    worker_id: str
    repository: str
    repository_root: Path
    image: str
    docker_binary: str

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> WorkerConfig:
        source = os.environ if environ is None else environ
        token = str(source.get("CALYX_SANDBOX_SUPERVISOR_TOKEN", "")).strip()
        if len(token) < 32:
            raise RuntimeError("SANDBOX_SUPERVISOR_TOKEN_NOT_CONFIGURED")
        worker_id = str(source.get("CALYX_SANDBOX_SUPERVISOR_WORKER_ID", "")).strip()
        if not worker_id:
            raise RuntimeError("SANDBOX_SUPERVISOR_WORKER_ID_NOT_CONFIGURED")
        repository = str(source.get("CALYX_SANDBOX_REPOSITORY", "")).strip()
        if not repository or "/" not in repository:
            raise RuntimeError("SANDBOX_SUPERVISOR_REPOSITORY_NOT_CONFIGURED")
        root = Path(str(source.get("CALYX_SANDBOX_REPOSITORY_ROOT", ""))).expanduser().resolve()
        if not root.is_dir():
            raise RuntimeError("SANDBOX_SUPERVISOR_REPOSITORY_ROOT_INVALID")
        image = _validate_image_digest(str(source.get("CALYX_SANDBOX_IMAGE", "")))
        docker = shutil.which("docker")
        if not docker:
            raise RuntimeError("SANDBOX_SUPERVISOR_DOCKER_UNAVAILABLE")
        return cls(
            api_base_url=_normalize_api_base_url(
                str(source.get("CALYX_SANDBOX_SUPERVISOR_API_BASE_URL", ""))
            ),
            supervisor_token=token,
            worker_id=worker_id,
            repository=repository,
            repository_root=root,
            image=image,
            docker_binary=str(Path(docker).resolve()),
        )


@dataclass(frozen=True, slots=True)
class ProcessResult:
    return_code: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    output_limited: bool = False


class SandboxSupervisorWorker:
    def __init__(
        self,
        config: WorkerConfig,
        *,
        runner: Callable[[Sequence[str], int], ProcessResult] | None = None,
        git_head_reader: Callable[[Path], str] | None = None,
        snapshot_maker: Callable[[Path, str], Any] | None = None,
    ) -> None:
        self.config = config
        if runner is None:
            docker = config.docker_binary
            self._runner: Callable[[Sequence[str], int], ProcessResult] = (
                lambda argv, timeout: _run_docker_bounded(docker, argv, timeout)
            )
        else:
            self._runner = runner
        self._git_head_reader = git_head_reader or _git_head
        self._snapshot_maker = snapshot_maker or _immutable_archive

    @property
    def policy(self) -> dict[str, Any]:
        return {
            "schema": "calyx-external-sandbox-policy-v1",
            "network": "none",
            "container_root": "read-only",
            "repository_mount": "read-only",
            "capabilities": "drop-all",
            "no_new_privileges": True,
            "user": "65534:65534",
            "pids_limit": DEFAULT_PIDS,
            "memory": DEFAULT_MEMORY,
            "cpus": DEFAULT_CPUS,
            "tmpfs": "/tmp:rw,noexec,nosuid,nodev,size=64m",
            "image": self.config.image,
            "arbitrary_shell": False,
            "package_installation": False,
            "credentials_forwarded": False,
            "max_capture_bytes": MAX_CAPTURE_BYTES,
        }

    @property
    def policy_digest(self) -> str:
        return _canonical_sha256(self.policy)

    def run_once(self) -> dict[str, Any]:
        claim = self._claim()
        if not claim.get("claimed"):
            return {"executed": False, "reason": "no_request"}
        request = claim.get("request")
        if not isinstance(request, dict):
            raise TypeError("SANDBOX_SUPERVISOR_CLAIM_MALFORMED")
        receipt = self._process_claim(request)
        completion = self._complete(request, receipt)
        return {
            "executed": True,
            "request_id": request.get("request_id"),
            "outcome": receipt["outcome"],
            "return_code": receipt["return_code"],
            "policy_digest": receipt["policy_digest"],
            "receipt_digest": completion.get("receipt_digest"),
        }

    def _claim(self) -> dict[str, Any]:
        return self._post_json(
            "/sandbox-validation/supervisor/claim",
            {"worker_id": self.config.worker_id},
        )

    def _complete(self, request: Mapping[str, Any], receipt: Mapping[str, Any]) -> dict[str, Any]:
        request_id = str(request.get("request_id") or "")
        claim_token = str(request.get("claim_token") or "")
        if not request_id or not claim_token:
            raise RuntimeError("SANDBOX_SUPERVISOR_CLAIM_IDENTITY_MISSING")
        return self._post_json(
            f"/sandbox-validation/supervisor/requests/{request_id}/complete",
            {
                "worker_id": self.config.worker_id,
                "claim_token": claim_token,
                "receipt": dict(receipt),
            },
        )

    def _process_claim(self, request: Mapping[str, Any]) -> dict[str, Any]:
        request_digest = str(request.get("request_digest") or "").strip().lower()
        if not _is_sha256(request_digest):
            raise RuntimeError("SANDBOX_SUPERVISOR_REQUEST_DIGEST_INVALID")
        try:
            if _request_digest(request) != request_digest:
                raise PermissionError("SANDBOX_SUPERVISOR_REQUEST_DIGEST_MISMATCH")
            self._verify_claim_identity(request)
            commit = str(request.get("checkout_commit_sha") or "").strip().lower()
            with self._snapshot_maker(self.config.repository_root, commit) as snapshot:
                # Verify targets from the immutable snapshot so that the files
                # that are hash-checked are exactly the files that will be executed,
                # eliminating any TOCTOU race with the live worktree.
                targets = self._verify_targets(request, snapshot)
                probe = self._runner(
                    self._docker_prefix(snapshot) + ["python", "-c", TRUSTED_SANDBOX_PROBE],
                    15,
                )
                if probe.return_code != 0 or probe.timed_out or probe.output_limited:
                    return self._receipt(
                        request_digest=request_digest,
                        outcome="timed_out" if probe.timed_out else "blocked",
                        result=probe,
                    )
                command = self._validation_command(str(request.get("preset") or ""), targets)
                timeout_seconds = int(request.get("timeout_seconds") or 0)
                result = self._runner(self._docker_prefix(snapshot) + command, timeout_seconds)
            if result.timed_out:
                outcome = "timed_out"
            elif result.output_limited or result.return_code != 0:
                outcome = "blocked"
            else:
                outcome = "delivered"
            return self._receipt(request_digest=request_digest, outcome=outcome, result=result)
        except (LookupError, PermissionError, RuntimeError, TypeError, ValueError) as exc:
            reason = str(exc).encode("utf-8", errors="replace")
            return self._receipt(
                request_digest=request_digest,
                outcome="blocked",
                result=ProcessResult(return_code=None, stdout=b"", stderr=reason),
            )

    def _verify_claim_identity(self, request: Mapping[str, Any]) -> None:
        if str(request.get("claim_worker") or "") != self.config.worker_id:
            raise PermissionError("SANDBOX_SUPERVISOR_CLAIM_WORKER_MISMATCH")
        if not str(request.get("claim_token") or ""):
            raise PermissionError("SANDBOX_SUPERVISOR_CLAIM_TOKEN_MISSING")
        if str(request.get("repository") or "") != self.config.repository:
            raise PermissionError("SANDBOX_SUPERVISOR_REPOSITORY_MISMATCH")
        branch = str(request.get("branch") or "")
        if not branch.startswith("autonomy/"):
            raise PermissionError("SANDBOX_SUPERVISOR_AUTONOMY_BRANCH_REQUIRED")
        expected_commit = str(request.get("checkout_commit_sha") or "").strip().lower()
        if len(expected_commit) != 40 or any(c not in "0123456789abcdef" for c in expected_commit):
            raise ValueError("SANDBOX_SUPERVISOR_CHECKOUT_COMMIT_INVALID")
        actual_commit = self._git_head_reader(self.config.repository_root).strip().lower()
        if actual_commit != expected_commit:
            raise PermissionError("SANDBOX_SUPERVISOR_CHECKOUT_COMMIT_MISMATCH")

    def _verify_targets(self, request: Mapping[str, Any], snapshot: Path) -> list[str]:
        raw_targets = request.get("targets")
        if not isinstance(raw_targets, list) or not 1 <= len(raw_targets) <= 24:
            raise ValueError("SANDBOX_SUPERVISOR_TARGET_COUNT_INVALID")
        verified: list[str] = []
        seen: set[str] = set()
        for item in raw_targets:
            if not isinstance(item, dict):
                raise TypeError("SANDBOX_SUPERVISOR_TARGET_INVALID")
            path = str(item.get("path") or "").strip()
            expected_hash = str(item.get("sha256") or "").strip().lower()
            if path in seen or not path or path.startswith("/") or ".." in Path(path).parts:
                raise ValueError("SANDBOX_SUPERVISOR_TARGET_PATH_INVALID")
            if not path.startswith(("app/", "tests/")):
                raise PermissionError("SANDBOX_SUPERVISOR_TARGET_PATH_NOT_ALLOWED")
            if not _is_sha256(expected_hash):
                raise ValueError("SANDBOX_SUPERVISOR_TARGET_HASH_INVALID")
            candidate = self._regular_file_without_symlinks(path, snapshot)
            if candidate.stat().st_size > MAX_TARGET_BYTES:
                raise PermissionError("SANDBOX_SUPERVISOR_TARGET_TOO_LARGE")
            actual_hash = _sha256_bytes(candidate.read_bytes())
            if actual_hash != expected_hash:
                raise PermissionError("SANDBOX_SUPERVISOR_TARGET_HASH_MISMATCH")
            seen.add(path)
            verified.append(path)
        preset = str(request.get("preset") or "").strip().lower()
        if preset == "pytest" and any(not path.startswith("tests/") for path in verified):
            raise PermissionError("SANDBOX_SUPERVISOR_PYTEST_TARGET_NOT_TEST")
        return sorted(verified)

    def _regular_file_without_symlinks(self, path: str, root: Path) -> Path:
        current = root
        for part in Path(path).parts:
            current = current / part
            if current.is_symlink():
                raise PermissionError("SANDBOX_SUPERVISOR_TARGET_SYMLINK_PROHIBITED")
        candidate = current.resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise PermissionError("SANDBOX_SUPERVISOR_TARGET_ESCAPE") from exc
        if not candidate.is_file():
            raise LookupError("SANDBOX_SUPERVISOR_TARGET_NOT_REGULAR_FILE")
        return candidate

    def _docker_prefix(self, snapshot: Path) -> list[str]:
        return [
            self.config.docker_binary,
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            "65534:65534",
            "--pids-limit",
            DEFAULT_PIDS,
            "--memory",
            DEFAULT_MEMORY,
            "--cpus",
            DEFAULT_CPUS,
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=64m",
            "--mount",
            f"type=bind,src={snapshot},dst=/workspace,readonly",
            "--workdir",
            "/workspace",
            self.config.image,
        ]

    @staticmethod
    def _validation_command(preset: str, targets: Sequence[str]) -> list[str]:
        normalized = preset.strip().lower()
        if normalized == "pytest":
            return ["python", "-m", "pytest", "-q", "--maxfail=1", *targets]
        if normalized == "ruff":
            return ["python", "-m", "ruff", "check", "--", *targets]
        raise ValueError("SANDBOX_SUPERVISOR_PRESET_NOT_ALLOWED")

    def _receipt(
        self,
        *,
        request_digest: str,
        outcome: str,
        result: ProcessResult,
    ) -> dict[str, Any]:
        return {
            "request_digest": request_digest,
            "authorization_id": f"external-sandbox:{uuid4()}",
            "policy_digest": self.policy_digest,
            "evidence_uri": f"sandbox-worker:{self.config.worker_id}",
            "outcome": outcome,
            "return_code": result.return_code,
            "stdout_sha256": _sha256_bytes(result.stdout),
            "stderr_sha256": _sha256_bytes(result.stderr),
            "issued_at": datetime.now(timezone.utc).isoformat(),
        }

    def _post_json(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            self.config.api_base_url + path,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Calyx-Sandbox-Supervisor-Token": self.config.supervisor_token,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = response.read(1_048_577)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"SANDBOX_SUPERVISOR_API_HTTP_{exc.code}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError("SANDBOX_SUPERVISOR_API_UNAVAILABLE") from exc
        if len(raw) > 1_048_576:
            raise RuntimeError("SANDBOX_SUPERVISOR_API_RESPONSE_TOO_LARGE")
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise TypeError("SANDBOX_SUPERVISOR_API_RESPONSE_INVALID")
        return value


def _git_head(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError("SANDBOX_SUPERVISOR_GIT_HEAD_UNAVAILABLE")
    return result.stdout.strip()


@contextlib.contextmanager
def _immutable_archive(repo_root: Path, commit: str):
    """Context manager: extract *commit* from *repo_root* into a read-only temp dir.

    The yielded directory is an immutable snapshot of the repository at the
    given commit.  It is removed unconditionally on exit.
    """
    tmp = tempfile.mkdtemp(prefix="calyx-sandbox-snapshot-")
    try:
        archive = subprocess.run(
            ["git", "-C", str(repo_root), "archive", "--format=tar", commit],
            check=False,
            capture_output=True,
            timeout=60,
        )
        if archive.returncode != 0:
            raise RuntimeError("SANDBOX_SUPERVISOR_GIT_ARCHIVE_FAILED")
        extract = subprocess.run(
            ["tar", "-x", "-C", tmp],
            input=archive.stdout,
            check=False,
            capture_output=True,
            timeout=60,
        )
        if extract.returncode != 0:
            raise RuntimeError("SANDBOX_SUPERVISOR_GIT_ARCHIVE_EXTRACT_FAILED")
        # Remove write permission from owner so the snapshot is immutable on
        # the host (the Docker --read-only flag protects the container side).
        subprocess.run(
            ["chmod", "-R", "a-w", tmp],
            check=False,
            capture_output=True,
            timeout=30,
        )
        yield Path(tmp)
    finally:
        # Restore write permission so rmtree can delete files.
        subprocess.run(["chmod", "-R", "u+w", tmp], check=False, capture_output=True, timeout=30)
        shutil.rmtree(tmp, ignore_errors=True)


def _stop_container(cidfile: Path, docker_binary: str) -> None:
    """Best-effort: gracefully stop then forcibly kill a container by cidfile."""
    try:
        cid = cidfile.read_text(encoding="ascii").strip()
    except OSError:
        return
    if not cid:
        return
    for cmd in (
        [docker_binary, "stop", "-t", "2", cid],
        [docker_binary, "kill", cid],
    ):
        try:
            subprocess.run(cmd, check=False, capture_output=True, timeout=10)
        except Exception:  # noqa: BLE001, S110
            pass


def _run_docker_bounded(docker_binary: str, argv: Sequence[str], timeout_seconds: int) -> ProcessResult:
    """Like _run_bounded but also terminates the Docker container on abort."""
    if not 1 <= timeout_seconds <= 120:
        raise ValueError("SANDBOX_SUPERVISOR_TIMEOUT_INVALID")
    cidfile_fd, cidfile_path = tempfile.mkstemp(prefix="calyx-cid-")
    os.close(cidfile_fd)
    cidfile = Path(cidfile_path)
    # Inject --cidfile after `docker run` (argv[0]=docker, argv[1]=run)
    patched = list(argv[:2]) + ["--cidfile", str(cidfile)] + list(argv[2:])
    try:
        result = _run_bounded_inner(patched, timeout_seconds, on_abort=lambda: _stop_container(cidfile, docker_binary))
    finally:
        try:
            cidfile.unlink(missing_ok=True)
        except OSError:
            pass
    return result


def _run_bounded(argv: Sequence[str], timeout_seconds: int) -> ProcessResult:
    return _run_bounded_inner(list(argv), timeout_seconds, on_abort=None)


def _run_bounded_inner(
    argv: list[str],
    timeout_seconds: int,
    *,
    on_abort: Callable[[], None] | None,
) -> ProcessResult:
    if not 1 <= timeout_seconds <= 120:
        raise ValueError("SANDBOX_SUPERVISOR_TIMEOUT_INVALID")
    process = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
    )
    assert process.stdout is not None and process.stderr is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + timeout_seconds
    timed_out = False
    output_limited = False
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                if on_abort is not None:
                    on_abort()
                process.kill()
                break
            events = selector.select(timeout=min(remaining, 0.25))
            if not events and process.poll() is not None:
                for registered in list(selector.get_map().values()):
                    selector.unregister(registered.fileobj)
                break
            for key, _ in events:
                chunk = os.read(key.fileobj.fileno(), 65_536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                target = buffers[str(key.data)]
                target.extend(chunk)
                if len(target) > MAX_CAPTURE_BYTES:
                    output_limited = True
                    if on_abort is not None:
                        on_abort()
                    process.kill()
                    break
            if output_limited:
                break
        return_code = process.wait(timeout=5)
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    return ProcessResult(
        return_code=return_code,
        stdout=bytes(buffers["stdout"][:MAX_CAPTURE_BYTES]),
        stderr=bytes(buffers["stderr"][:MAX_CAPTURE_BYTES]),
        timed_out=timed_out,
        output_limited=output_limited,
    )


def main() -> None:
    worker = SandboxSupervisorWorker(WorkerConfig.from_environ())
    print(json.dumps(worker.run_once(), sort_keys=True))


if __name__ == "__main__":
    main()

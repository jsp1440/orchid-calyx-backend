from __future__ import annotations

import contextlib
import hashlib
from pathlib import Path

import pytest

import runtime.sandbox_supervisor_worker as worker_module
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


@contextlib.contextmanager
def _passthrough_snapshot(repo_root: Path, commit: str):
    yield repo_root


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


def _worker(
    root: Path, *, runner, head=COMMIT, clean=True, snapshot=_passthrough_snapshot
):
    return SandboxSupervisorWorker(
        _config(root),
        runner=runner,
        git_head_reader=lambda _: head,
        git_clean_reader=lambda _: clean,
        snapshot_maker=snapshot,
    )


def test_configuration_requires_https_and_immutable_image() -> None:
    assert (
        _normalize_api_base_url("https://calyx.example.org/")
        == "https://calyx.example.org"
    )
    assert _normalize_api_base_url("http://localhost:8000") == "http://localhost:8000"
    with pytest.raises(PermissionError, match="HTTPS_REQUIRED"):
        _normalize_api_base_url("http://calyx.example.org")
    with pytest.raises(ValueError, match="IMMUTABLE_IMAGE_REQUIRED"):
        _validate_image_digest("ghcr.io/example/calyx-validator:latest")
    assert _validate_image_digest(IMAGE) == IMAGE


def test_success_uses_fixed_named_no_network_read_only_containers_and_never_forwards_token(
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

    receipt = _worker(tmp_path, runner=runner)._process_claim(
        _claim("tests/test_example.py", digest)
    )
    assert receipt["return_code"] == 0
    assert len(calls) == 2
    names = []
    for argv, _ in calls:
        assert "--name" in argv
        name = argv[argv.index("--name") + 1]
        assert name.startswith("calyx-sbx-")
        names.append(name)
        assert "--network" in argv and argv[argv.index("--network") + 1] == "none"
        assert "--read-only" in argv
        assert "--cap-drop" in argv and argv[argv.index("--cap-drop") + 1] == "ALL"
        assert "no-new-privileges" in argv
        assert "65534:65534" in argv
        assert IMAGE in argv
        assert TOKEN not in " ".join(argv)
        assert not any(
            "DATABASE_URL=" in item or "GITHUB_TOKEN=" in item for item in argv
        )
    assert len(set(names)) == 2
    validation_argv = calls[1][0]
    assert validation_argv[-6:] == [
        "python",
        "-m",
        "pytest",
        "-q",
        "--maxfail=1",
        "tests/test_example.py",
    ]


def test_dirty_checkout_blocks_before_snapshot_or_container(tmp_path: Path) -> None:
    target = tmp_path / "tests" / "test_example.py"
    target.parent.mkdir(parents=True)
    target.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    calls = []
    snapshot_calls = []

    @contextlib.contextmanager
    def snapshot(repo_root: Path, commit: str):
        snapshot_calls.append((repo_root, commit))
        yield repo_root

    receipt = _worker(
        tmp_path,
        runner=lambda argv, timeout: calls.append((argv, timeout)),
        clean=False,
        snapshot=snapshot,
    )._process_claim(_claim("tests/test_example.py", digest))

    assert receipt["outcome"] == "blocked"
    assert receipt["return_code"] is None
    assert calls == []
    assert snapshot_calls == []
    assert (
        hashlib.sha256(b"SANDBOX_SUPERVISOR_CHECKOUT_DIRTY").hexdigest()
        == receipt["stderr_sha256"]
    )


def test_target_hash_and_execution_are_bound_to_snapshot_not_live_worktree(
    tmp_path: Path,
) -> None:
    host_root = tmp_path / "host"
    snapshot_root = tmp_path / "snapshot"
    host_target = host_root / "tests" / "test_example.py"
    snapshot_target = snapshot_root / "tests" / "test_example.py"
    host_target.parent.mkdir(parents=True)
    snapshot_target.parent.mkdir(parents=True)
    host_target.write_text("raise RuntimeError('host differs')\n", encoding="utf-8")
    snapshot_target.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    digest = hashlib.sha256(snapshot_target.read_bytes()).hexdigest()
    calls: list[list[str]] = []

    @contextlib.contextmanager
    def immutable_snapshot(repo_root: Path, commit: str):
        assert repo_root == host_root
        assert commit == COMMIT
        yield snapshot_root.resolve()

    def runner(argv, timeout):
        calls.append(list(argv))
        return ProcessResult(return_code=0, stdout=b"ok", stderr=b"")

    receipt = _worker(
        host_root,
        runner=runner,
        snapshot=immutable_snapshot,
    )._process_claim(_claim("tests/test_example.py", digest))

    assert receipt["outcome"] == "delivered"
    assert len(calls) == 2
    for argv in calls:
        mount = argv[argv.index("--mount") + 1]
        assert f"src={snapshot_root.resolve()}" in mount
        assert f"src={host_root.resolve()}" not in mount


def test_snapshot_hash_mismatch_blocks_even_when_live_worktree_matches(
    tmp_path: Path,
) -> None:
    host_root = tmp_path / "host"
    snapshot_root = tmp_path / "snapshot"
    host_target = host_root / "tests" / "test_example.py"
    snapshot_target = snapshot_root / "tests" / "test_example.py"
    host_target.parent.mkdir(parents=True)
    snapshot_target.parent.mkdir(parents=True)
    host_target.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    snapshot_target.write_text(
        "def test_changed():\n    assert False\n", encoding="utf-8"
    )
    digest = hashlib.sha256(host_target.read_bytes()).hexdigest()
    calls = []

    @contextlib.contextmanager
    def immutable_snapshot(repo_root: Path, commit: str):
        yield snapshot_root

    receipt = _worker(
        host_root,
        runner=lambda argv, timeout: calls.append((argv, timeout)),
        snapshot=immutable_snapshot,
    )._process_claim(_claim("tests/test_example.py", digest))

    assert receipt["outcome"] == "blocked"
    assert receipt["return_code"] is None
    assert calls == []


def test_hash_mismatch_blocks_before_container_execution(tmp_path: Path) -> None:
    target = tmp_path / "tests" / "test_example.py"
    target.parent.mkdir(parents=True)
    target.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    calls = []

    def runner(argv, timeout):
        calls.append((argv, timeout))
        return ProcessResult(return_code=0, stdout=b"", stderr=b"")

    receipt = _worker(tmp_path, runner=runner)._process_claim(
        _claim("tests/test_example.py", "d" * 64)
    )
    assert receipt["outcome"] == "blocked"
    assert receipt["return_code"] is None
    assert calls == []


def test_checkout_commit_mismatch_blocks_before_container_execution(
    tmp_path: Path,
) -> None:
    target = tmp_path / "tests" / "test_example.py"
    target.parent.mkdir(parents=True)
    target.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    calls = []

    receipt = _worker(
        tmp_path,
        runner=lambda argv, timeout: calls.append((argv, timeout)),
        head="e" * 40,
    )._process_claim(_claim("tests/test_example.py", digest))
    assert receipt["outcome"] == "blocked"
    assert receipt["return_code"] is None
    assert calls == []


def test_symlink_target_is_rejected_even_when_it_resolves_inside_repository(
    tmp_path: Path,
) -> None:
    real = tmp_path / "tests" / "real_test.py"
    real.parent.mkdir(parents=True)
    real.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    link = tmp_path / "tests" / "test_link.py"
    link.symlink_to(real.name)
    digest = hashlib.sha256(real.read_bytes()).hexdigest()
    calls = []

    receipt = _worker(
        tmp_path,
        runner=lambda argv, timeout: calls.append((argv, timeout)),
    )._process_claim(_claim("tests/test_link.py", digest))
    assert receipt["outcome"] == "blocked"
    assert calls == []


def test_tampered_request_digest_blocks_before_container_execution(
    tmp_path: Path,
) -> None:
    target = tmp_path / "tests" / "test_example.py"
    target.parent.mkdir(parents=True)
    target.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    claim = _claim("tests/test_example.py", digest)
    claim["request_digest"] = "f" * 64
    calls = []

    receipt = _worker(
        tmp_path,
        runner=lambda argv, timeout: calls.append((argv, timeout)),
    )._process_claim(claim)
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

    receipt = _worker(tmp_path, runner=runner)._process_claim(
        _claim("tests/test_example.py", digest, preset="bash -c curl attacker.invalid")
    )
    assert receipt["outcome"] == "blocked"
    assert len(calls) == 1
    assert "curl" not in " ".join(calls[0][0])


@pytest.mark.parametrize(
    ("result", "expected_flag"),
    [
        (
            ProcessResult(
                return_code=-9,
                stdout=b"",
                stderr=b"timeout",
                timed_out=True,
            ),
            "timed_out",
        ),
        (
            ProcessResult(
                return_code=-9,
                stdout=b"x" * 10,
                stderr=b"",
                output_limited=True,
            ),
            "output_limited",
        ),
    ],
)
def test_docker_abort_explicitly_stops_and_removes_named_container(
    monkeypatch: pytest.MonkeyPatch,
    result: ProcessResult,
    expected_flag: str,
) -> None:
    docker_calls: list[list[str]] = []
    captured: dict[str, object] = {}

    def fake_subprocess_run(argv, **kwargs):
        docker_calls.append(list(argv))
        return type("Completed", (), {"returncode": 0})()

    def fake_inner(argv, timeout_seconds, *, on_abort):
        assert argv[:2] == ["/usr/bin/docker", "run"]
        assert "--name" in argv
        captured["name"] = argv[argv.index("--name") + 1]
        assert on_abort is not None
        on_abort()
        return result

    monkeypatch.setattr(worker_module.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(worker_module, "_run_bounded_inner", fake_inner)
    name = "calyx-sbx-validation-abcdef123456-123456abcdef"

    actual = worker_module._run_docker_bounded(
        "/usr/bin/docker",
        [
            "/usr/bin/docker",
            "run",
            "--rm",
            "--name",
            name,
            IMAGE,
            "python",
            "-V",
        ],
        5,
    )

    assert getattr(actual, expected_flag) is True
    assert captured["name"] == name
    assert docker_calls == [
        ["/usr/bin/docker", "stop", "-t", "2", name],
        ["/usr/bin/docker", "rm", "-f", name],
        ["/usr/bin/docker", "stop", "-t", "2", name],
        ["/usr/bin/docker", "rm", "-f", name],
    ]


def test_docker_runner_exception_still_removes_named_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    docker_calls: list[list[str]] = []

    def fake_subprocess_run(argv, **kwargs):
        docker_calls.append(list(argv))
        return type("Completed", (), {"returncode": 0})()

    def fake_inner(argv, timeout_seconds, *, on_abort):
        raise RuntimeError("runner failed")

    monkeypatch.setattr(worker_module.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(worker_module, "_run_bounded_inner", fake_inner)
    name = "calyx-sbx-probe-abcdef123456-fedcba654321"

    with pytest.raises(RuntimeError, match="runner failed"):
        worker_module._run_docker_bounded(
            "/usr/bin/docker",
            [
                "/usr/bin/docker",
                "run",
                "--rm",
                "--name",
                name,
                IMAGE,
                "python",
                "-V",
            ],
            5,
        )

    assert docker_calls == [
        ["/usr/bin/docker", "stop", "-t", "2", name],
        ["/usr/bin/docker", "rm", "-f", name],
    ]

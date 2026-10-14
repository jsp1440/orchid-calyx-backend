"""The allowlisted TraitBank validation executor is narrow and fail-closed."""

from __future__ import annotations

import hashlib
import json
import subprocess

import pytest

from app.calyx_orchestrator.executor import GovernedAssignment
from app.calyx_orchestrator.executor_registry import AuthoritativeExecutorRegistry
from app.calyx_orchestrator.traitbank_validation_executor import (
    TRAITBANK_VALIDATION_ROLE,
    TraitBankBatchValidationExecutor,
    parse_targets,
    validate_batch_document,
)

REPOSITORY = "jsp1440/orchid-calyx-backend"
BRANCH = "autonomy/traitbank-unit"


def test_registered_as_read_only_without_code_execution_or_side_effects():
    registered = AuthoritativeExecutorRegistry().require_authoritative(
        TRAITBANK_VALIDATION_ROLE
    )
    assert registered.authoritative is True
    assert (
        registered.external_side_effects,
        registered.workspace_mutation,
        registered.repository_code_execution,
    ) == (False, False, False)


@pytest.mark.parametrize(
    ("raw", "error"),
    [
        ([], TypeError),
        ([{"path": "app/x.json", "sha256": "a" * 64}], PermissionError),
        ([{"path": "data/traitbank/../x.json", "sha256": "a" * 64}], PermissionError),
        ([{"path": "data/traitbank/x.csv", "sha256": "a" * 64}], PermissionError),
        ([{"path": "data/traitbank/x.json", "sha256": "A" * 64}], ValueError),
        ([{"path": "data/traitbank/x.json", "sha256": "a" * 64, "x": 1}], TypeError),
        (
            [
                {"path": f"data/traitbank/{i}.json", "sha256": "a" * 64}
                for i in range(9)
            ],
            ValueError,
        ),
    ],
)
def test_inputs_outside_the_allowlist_are_refused(raw, error):
    with pytest.raises(error):
        parse_targets(raw)


def test_document_verdicts_never_repair_input():
    assert validate_batch_document(b"not json")["model_errors"][0]["code"] == (
        "TRAITBANK_BATCH_NOT_JSON"
    )
    verdict = validate_batch_document(
        json.dumps({"contract_version": "oc-traitbank-v1"}).encode()
    )
    assert verdict["valid"] is False and verdict["model_errors"]


def _repo(tmp_path, body: bytes):
    repo = tmp_path / "repo"
    (repo / "data" / "traitbank").mkdir(parents=True)
    for command in (
        ["init", "-q", "-b", BRANCH],
        ["config", "user.email", "t@example.invalid"],
        ["config", "user.name", "unit"],
    ):
        subprocess.run(["git", "-C", str(repo), *command], check=True)
    (repo / "AGENTS.md").write_text("x\n")
    (repo / "requirements.txt").write_text("")
    (repo / "data/traitbank/batch.json").write_bytes(body)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "x"], check=True)
    return repo


def _assignment(files):
    job = {
        "program_job_id": "job-1",
        "job_key": "build:traitbank-validation:x:1",
        "role_key": TRAITBANK_VALIDATION_ROLE,
        "title": "t",
        "repository": REPOSITORY,
        "branch": BRANCH,
        "mutating_intent": False,
        "attempt_count": 1,
        "files": files,
    }
    return GovernedAssignment(
        assignment_id="job-1",
        program_id="program-1",
        job_key=job["job_key"],
        role_key=TRAITBANK_VALIDATION_ROLE,
        objective="Validate committed TraitBank evidence",
        inputs={"program": {}, "job": job, "governance": {}},
        timeout_seconds=30,
    )


def test_declared_digest_must_match_the_committed_file(tmp_path):
    body = b"{}"
    repo = _repo(tmp_path, body)
    executor = TraitBankBatchValidationExecutor(
        workspace_root=repo, repository_name=REPOSITORY
    )
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        executor.execute(
            _assignment([{"path": "data/traitbank/batch.json", "sha256": "0" * 64}])
        )
    receipt = executor.execute(
        _assignment(
            [
                {
                    "path": "data/traitbank/batch.json",
                    "sha256": hashlib.sha256(body).hexdigest(),
                }
            ]
        )
    )
    assert receipt.output["all_valid"] is False
    assert (
        receipt.output["database_used"] is False
        and receipt.output["publication"] is False
    )

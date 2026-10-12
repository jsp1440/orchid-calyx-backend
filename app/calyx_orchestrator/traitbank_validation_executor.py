"""Read-only TraitBank batch validation as a registered autonomy job.

The first scientific job type the autonomy queue may run. It is allowlisted
and narrow:

* **Inputs:** ``files``: 1-8 ``{path, sha256}`` pairs naming committed
  ``oc-traitbank-v1`` batch JSON under ``data/traitbank/`` or
  ``tests/fixtures/traitbank/`` in the verified checkout.
* **Work:** each file is read through the confined workspace reader, its
  sha256 must equal the declared digest, and it is validated by the pinned
  contract model (``app.traitbank.models.TraitBankBatch``) and the live
  ingestion guards (``app.traitbank.guards.check_batch``). Both are fixed,
  in-tree, pure functions. Nothing is imported or executed from the
  repository being read.
* **Output:** a per-file verdict (counts, model errors, guard violations)
  plus the Brain contract and OAO registry pins in force.
* **Never:** a database, network, subprocess, file write, TraitBank
  ingestion or publication. An invalid batch is a delivered verdict, not a
  repair: nothing is rewritten to make a record pass.
* **Limits:** at most 8 files, 2 MB per file, 4 MB in total, and the
  assignment deadline checked after every file.

Idempotency comes from the queue: the job's identity is the Brain build id
derived from the declared ``(path, sha256)`` set, and a replayed submission
converges on the existing program.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from pydantic import ValidationError

from app.traitbank import contract as traitbank_contract
from app.traitbank.guards import check_batch
from app.traitbank.models import TraitBankBatch

from .engineering_core import TerminalOutcome
from .executor import (
    ExecutionReceipt,
    ExecutionState,
    GovernedAssignment,
    canonical_checksum,
)
from .repository_evidence_executor import RepositoryEvidenceExecutor

TRAITBANK_VALIDATION_ROLE = "traitbank_batch_validator"
ALLOWED_TRAITBANK_PREFIXES = ("data/traitbank/", "tests/fixtures/traitbank/")
MAX_TRAITBANK_FILES = 8
MAX_FILE_BYTES = 2_000_000
MAX_TOTAL_BYTES = 4_000_000
MAX_REPORTED_ERRORS = 50
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class TraitBankTarget:
    path: str
    sha256: str


def parse_target(value: Any) -> TraitBankTarget:
    """Validate one declared input; shared with admission."""
    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        raise TypeError("TRAITBANK_VALIDATION_TARGET_INVALID")
    path, digest = value["path"], value["sha256"]
    if not isinstance(path, str) or not isinstance(digest, str):
        raise TypeError("TRAITBANK_VALIDATION_TARGET_INVALID")
    if not _SHA256.fullmatch(digest):
        raise ValueError("TRAITBANK_VALIDATION_DIGEST_INVALID")
    posix = PurePosixPath(path)
    if (
        posix.is_absolute()
        or not posix.parts
        or any(part in {"", ".", "..", ".git"} for part in posix.parts)
        or not path.endswith(".json")
    ):
        raise PermissionError("TRAITBANK_VALIDATION_PATH_ESCAPE")
    if not posix.as_posix().startswith(ALLOWED_TRAITBANK_PREFIXES):
        raise PermissionError("TRAITBANK_VALIDATION_PATH_NOT_ALLOWED")
    return TraitBankTarget(path=posix.as_posix(), sha256=digest)


def parse_targets(raw: Any) -> tuple[TraitBankTarget, ...]:
    if not isinstance(raw, list) or not raw:
        raise TypeError("TRAITBANK_VALIDATION_FILES_REQUIRED")
    if len(raw) > MAX_TRAITBANK_FILES:
        raise ValueError("TRAITBANK_VALIDATION_FILE_COUNT_EXCEEDED")
    targets = tuple(parse_target(item) for item in raw)
    if len({target.path for target in targets}) != len(targets):
        raise ValueError("TRAITBANK_VALIDATION_DUPLICATE_PATH")
    return targets


def _model_errors(exc: ValidationError) -> list[dict[str, str]]:
    errors = []
    for item in exc.errors(include_url=False)[:MAX_REPORTED_ERRORS]:
        message = str(item.get("msg") or "")
        errors.append(
            {
                "code": message.removeprefix("Value error, ")[:160],
                "where": ".".join(str(part) for part in item.get("loc") or ())[:200],
            }
        )
    return errors


def validate_batch_document(raw: bytes) -> dict[str, Any]:
    """Pure verdict for one batch document (no I/O beyond the given bytes)."""
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {
            "valid": False,
            "batch_key": None,
            "assertions": 0,
            "environment_relations": 0,
            "model_errors": [{"code": "TRAITBANK_BATCH_NOT_JSON", "where": ""}],
            "violations": [],
        }
    try:
        batch = TraitBankBatch.model_validate(document)
    except ValidationError as exc:
        return {
            "valid": False,
            "batch_key": document.get("batch_key")
            if isinstance(document, dict)
            else None,
            "assertions": 0,
            "environment_relations": 0,
            "model_errors": _model_errors(exc),
            "violations": [],
        }
    violations = [v.as_dict() for v in check_batch(batch, live=True)]
    return {
        "valid": not violations,
        "batch_key": batch.batch_key,
        "producer": batch.producer,
        "assertions": len(batch.assertions),
        "environment_relations": len(batch.environment_relations),
        "model_errors": [],
        "violations": violations[:MAX_REPORTED_ERRORS],
    }


class TraitBankBatchValidationExecutor:
    """Authoritative for read-only ``oc-traitbank-v1`` batch verdicts only."""

    executor_key = "traitbank_batch_validator_v1"

    def __init__(
        self, *, workspace_root=None, repository_name: str | None = None
    ) -> None:
        reader = RepositoryEvidenceExecutor(
            workspace_root=workspace_root,
            repository_name=repository_name,
        )
        self.workspace_root = reader.workspace_root
        self.repository_name = reader.repository_name
        self._reader = reader

    def execute(self, assignment: GovernedAssignment) -> ExecutionReceipt:
        started = time.monotonic()
        if assignment.role_key != TRAITBANK_VALIDATION_ROLE:
            raise PermissionError("TRAITBANK_VALIDATION_ROLE_REQUIRED")
        if assignment.cancelled:
            raise PermissionError("TRAITBANK_VALIDATION_CANCELLED")
        if assignment.timeout_seconds <= 0:
            raise PermissionError("TRAITBANK_VALIDATION_TIMEOUT_INVALID")
        job = assignment.inputs.get("job")
        if not isinstance(job, dict):
            raise TypeError("TRAITBANK_VALIDATION_JOB_INPUT_REQUIRED")
        if bool(job.get("mutating_intent")):
            raise PermissionError("TRAITBANK_VALIDATION_MUTATION_PROHIBITED")
        repository = str(job.get("repository") or "").strip()
        branch = str(job.get("branch") or "").strip()
        if repository != self.repository_name:
            raise PermissionError("TRAITBANK_VALIDATION_REPOSITORY_MISMATCH")
        targets = parse_targets(job.get("files"))
        # The pinned Brain contract and OAO registry must load; drift fails closed.
        pins = {
            "contract_version": traitbank_contract.CONTRACT_VERSION,
            "contract_sha256": traitbank_contract.BRAIN_CONTRACT_SHA256,
            "oao_registry_sha256": traitbank_contract.BRAIN_OAO_REGISTRY_SHA256,
        }
        traitbank_contract.contract()
        traitbank_contract.oao_terms()

        checkout = self._reader._checkout_identity()
        if checkout.branch != branch:
            raise PermissionError("TRAITBANK_VALIDATION_REVISION_MISMATCH")
        results: list[dict[str, Any]] = []
        total = 0
        for target in targets:
            try:
                raw, size = self._reader._read_workspace_file(
                    target.path, MAX_FILE_BYTES
                )
            except FileNotFoundError as exc:
                raise FileNotFoundError(
                    f"TRAITBANK_VALIDATION_FILE_MISSING:{target.path}"
                ) from exc
            total += size
            if total > MAX_TOTAL_BYTES:
                raise ValueError("TRAITBANK_VALIDATION_TOTAL_BYTES_EXCEEDED")
            digest = hashlib.sha256(raw).hexdigest()
            if digest != target.sha256:
                raise ValueError(f"TRAITBANK_VALIDATION_HASH_MISMATCH:{target.path}")
            results.append(
                {
                    "path": target.path,
                    "sha256": digest,
                    "size_bytes": size,
                    **validate_batch_document(raw),
                }
            )
            if time.monotonic() - started > assignment.timeout_seconds:
                raise TimeoutError("TRAITBANK_VALIDATION_DEADLINE_EXCEEDED")
        if self._reader._checkout_identity() != checkout:
            raise RuntimeError("TRAITBANK_VALIDATION_CHECKOUT_CHANGED_DURING_SCAN")

        output: dict[str, Any] = {
            "status": "delivered",
            "executed": True,
            "mode": "authoritative_read_only_traitbank_validation",
            "repository": repository,
            "branch": branch,
            "checkout_commit_sha": checkout.commit_sha,
            "contract": pins,
            "live_guards": True,
            "file_count": len(results),
            "all_valid": all(item["valid"] for item in results),
            "results": results,
            "database_used": False,
            "network_used": False,
            "files_written": False,
            "traitbank_ingestion": False,
            "publication": False,
            "repository_code_imported": False,
            "side_effects": [],
        }
        receipt = ExecutionReceipt(
            assignment_id=assignment.assignment_id,
            program_id=assignment.program_id,
            job_key=assignment.job_key,
            executor_key=self.executor_key,
            state=ExecutionState.DELIVERED,
            outcome=TerminalOutcome.DELIVERED,
            input_checksum=assignment.verified_input_checksum(),
            output_checksum=canonical_checksum(output),
            output=output,
            evidence_uris=(
                *assignment.evidence_uris,
                f"repo-commit:{repository}@{checkout.commit_sha}",
                *(
                    f"traitbank-batch:{item['path']}#{item['sha256']}"
                    for item in results
                ),
            ),
        )
        receipt.verify()
        return receipt

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

from app.calyx_orchestrator.factory_policy import (
    CheckerVerdict,
    ValidationEvidence,
    WorkIntent,
)

CHECKER_ASSIGNMENT_TAG = "OC-CHECKER-ASSIGNMENT-V1"
CHECKER_EVIDENCE_TAG = "OC-CHECKER-EVIDENCE-V1"


@dataclass(frozen=True, slots=True)
class CheckerAssignment:
    """Durable record of an independent checker assigned to validate one exact-head work item.

    Persisted as a machine-readable GitHub comment so the record survives session
    disappearance and is reconstructable from the GitHub API alone.
    """

    repository: str
    issue_number: int
    pr_number: int
    head_sha: str
    maker_id: str
    checker_id: str
    material_fingerprint: str

    def __post_init__(self) -> None:
        if not self.repository.strip():
            raise ValueError("REPOSITORY_REQUIRED")
        if self.issue_number <= 0:
            raise ValueError("ISSUE_NUMBER_INVALID")
        if self.pr_number <= 0:
            raise ValueError("PR_NUMBER_INVALID")
        if not self.head_sha.strip():
            raise ValueError("HEAD_SHA_REQUIRED")
        if not self.maker_id.strip():
            raise ValueError("MAKER_ID_REQUIRED")
        if not self.checker_id.strip():
            raise ValueError("CHECKER_ID_REQUIRED")
        if not self.material_fingerprint.strip():
            raise ValueError("FINGERPRINT_REQUIRED")
        if self.checker_id == self.maker_id:
            raise ValueError("CHECKER_MUST_DIFFER_FROM_MAKER")


@dataclass(frozen=True, slots=True)
class CheckerEvidence:
    """Durable record of a checker's verdict on an exact-head assignment.

    Persisted as a machine-readable GitHub comment alongside the assignment.
    Fields are validated against the assignment before the evidence can advance
    the factory gate.
    """

    repository: str
    issue_number: int
    pr_number: int
    checked_head_sha: str
    checker_id: str
    maker_id: str
    verdict: CheckerVerdict
    required_checks_passed: bool
    reason: str
    material_fingerprint: str
    repair_lineage: str | None = None

    def __post_init__(self) -> None:
        if not self.repository.strip():
            raise ValueError("REPOSITORY_REQUIRED")
        if self.issue_number <= 0:
            raise ValueError("ISSUE_NUMBER_INVALID")
        if self.pr_number <= 0:
            raise ValueError("PR_NUMBER_INVALID")
        if not self.checked_head_sha.strip():
            raise ValueError("CHECKED_HEAD_SHA_REQUIRED")
        if not self.checker_id.strip():
            raise ValueError("CHECKER_ID_REQUIRED")
        if not self.maker_id.strip():
            raise ValueError("MAKER_ID_REQUIRED")
        if not self.reason.strip():
            raise ValueError("REASON_REQUIRED")
        if not self.material_fingerprint.strip():
            raise ValueError("FINGERPRINT_REQUIRED")
        if self.checker_id == self.maker_id:
            raise ValueError("CHECKER_MUST_DIFFER_FROM_MAKER")


class CheckerDispatchError(ValueError):
    """Raised when a checker cannot be assigned or evidence is invalid."""


def assign_checker(
    intent: WorkIntent,
    pr_number: int,
    maker_id: str,
    available_checkers: Sequence[str],
) -> CheckerAssignment:
    """Select the first available independent checker and return a durable assignment.

    Raises CheckerDispatchError if no non-maker checker is available.
    Does not cause side effects — callers persist the returned record.
    """
    if not available_checkers:
        raise CheckerDispatchError("NO_CHECKERS_AVAILABLE")

    for candidate in available_checkers:
        if candidate and candidate.strip() and candidate != maker_id:
            return CheckerAssignment(
                repository=intent.repository,
                issue_number=intent.issue_number,
                pr_number=pr_number,
                head_sha=intent.head_sha,
                maker_id=maker_id,
                checker_id=candidate,
                material_fingerprint=intent.material_fingerprint,
            )

    raise CheckerDispatchError("NO_INDEPENDENT_CHECKER_AVAILABLE")


def validate_checker_evidence(
    assignment: CheckerAssignment,
    evidence: CheckerEvidence,
) -> list[str]:
    """Verify that checker evidence matches the assignment on every bound field.

    Returns a list of mismatch reasons. An empty list means the evidence is valid.
    Fails closed: any mismatch blocks factory advancement.
    """
    errors: list[str] = []

    if evidence.repository != assignment.repository:
        errors.append(
            f"REPOSITORY_MISMATCH: expected {assignment.repository!r}, got {evidence.repository!r}"
        )
    if evidence.issue_number != assignment.issue_number:
        errors.append(
            f"ISSUE_NUMBER_MISMATCH: expected {assignment.issue_number}, got {evidence.issue_number}"
        )
    if evidence.pr_number != assignment.pr_number:
        errors.append(
            f"PR_NUMBER_MISMATCH: expected {assignment.pr_number}, got {evidence.pr_number}"
        )
    if evidence.checked_head_sha != assignment.head_sha:
        errors.append(
            f"HEAD_SHA_MISMATCH: expected {assignment.head_sha!r},"
            f" got {evidence.checked_head_sha!r}"
        )
    if evidence.checker_id != assignment.checker_id:
        errors.append(
            f"CHECKER_ID_MISMATCH: expected {assignment.checker_id!r},"
            f" got {evidence.checker_id!r}"
        )
    if evidence.maker_id != assignment.maker_id:
        errors.append(
            f"MAKER_ID_MISMATCH: expected {assignment.maker_id!r},"
            f" got {evidence.maker_id!r}"
        )
    if evidence.material_fingerprint != assignment.material_fingerprint:
        errors.append("FINGERPRINT_MISMATCH")

    return errors


def evidence_to_validation(
    assignment: CheckerAssignment,
    evidence: CheckerEvidence,
) -> ValidationEvidence:
    """Convert durable checker evidence to ValidationEvidence for factory re-evaluation.

    Raises CheckerDispatchError if the evidence does not match the assignment exactly.
    Callers that want a fail-closed default instead of an exception should catch the
    error and construct a PENDING ValidationEvidence themselves.
    """
    errors = validate_checker_evidence(assignment, evidence)
    if errors:
        raise CheckerDispatchError(f"INVALID_CHECKER_EVIDENCE: {'; '.join(errors)}")

    return ValidationEvidence(
        maker_id=evidence.maker_id,
        checker_id=evidence.checker_id,
        checker_verdict=evidence.verdict,
        exact_head_verified=(evidence.checked_head_sha == assignment.head_sha),
        required_checks_passed=evidence.required_checks_passed,
    )


# ---------------------------------------------------------------------------
# GitHub-native serialization
# Assignments and evidence are embedded as structured JSON inside HTML comments
# in PR/issue comment bodies.  The surrounding human-readable text is displayed
# to reviewers; the JSON block is parsed by evidence_to_validation() for
# machine re-evaluation.
# ---------------------------------------------------------------------------


def serialize_assignment(assignment: CheckerAssignment) -> str:
    """Produce a machine-readable GitHub comment body for a checker assignment."""
    payload = {
        "tag": CHECKER_ASSIGNMENT_TAG,
        "repository": assignment.repository,
        "issue_number": assignment.issue_number,
        "pr_number": assignment.pr_number,
        "head_sha": assignment.head_sha,
        "maker_id": assignment.maker_id,
        "checker_id": assignment.checker_id,
        "material_fingerprint": assignment.material_fingerprint,
    }
    json_block = json.dumps(payload, indent=2, sort_keys=True)
    short_sha = assignment.head_sha[:12]
    return (
        f"<!-- {CHECKER_ASSIGNMENT_TAG}\n{json_block}\n-->\n"
        f"[OC-CHECKER-ASSIGNMENT] Checker `{assignment.checker_id}` assigned to validate"
        f" exact head `{short_sha}` for issue #{assignment.issue_number}"
        f" (PR #{assignment.pr_number}). Maker: `{assignment.maker_id}`."
    )


def parse_assignment(comment_body: str) -> CheckerAssignment | None:
    """Extract a CheckerAssignment from a GitHub comment body.

    Returns None if the tag is absent or the JSON is malformed — never raises.
    """
    tag = CHECKER_ASSIGNMENT_TAG
    start = comment_body.find(f"<!-- {tag}")
    if start == -1:
        return None
    end = comment_body.find("-->", start)
    if end == -1:
        return None
    json_text = comment_body[start + len(f"<!-- {tag}") : end].strip()
    try:
        payload = json.loads(json_text)
        return CheckerAssignment(
            repository=str(payload["repository"]),
            issue_number=int(payload["issue_number"]),
            pr_number=int(payload["pr_number"]),
            head_sha=str(payload["head_sha"]),
            maker_id=str(payload["maker_id"]),
            checker_id=str(payload["checker_id"]),
            material_fingerprint=str(payload["material_fingerprint"]),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def serialize_evidence(evidence: CheckerEvidence) -> str:
    """Produce a machine-readable GitHub comment body for checker evidence."""
    payload = {
        "tag": CHECKER_EVIDENCE_TAG,
        "repository": evidence.repository,
        "issue_number": evidence.issue_number,
        "pr_number": evidence.pr_number,
        "checked_head_sha": evidence.checked_head_sha,
        "checker_id": evidence.checker_id,
        "maker_id": evidence.maker_id,
        "verdict": evidence.verdict.value,
        "required_checks_passed": evidence.required_checks_passed,
        "reason": evidence.reason,
        "material_fingerprint": evidence.material_fingerprint,
        "repair_lineage": evidence.repair_lineage,
    }
    json_block = json.dumps(payload, indent=2, sort_keys=True)
    short_sha = evidence.checked_head_sha[:12]
    return (
        f"<!-- {CHECKER_EVIDENCE_TAG}\n{json_block}\n-->\n"
        f"[OC-CHECKER-EVIDENCE] Checker `{evidence.checker_id}` verdict:"
        f" **{evidence.verdict.value.upper()}** on head `{short_sha}`"
        f" for issue #{evidence.issue_number} (PR #{evidence.pr_number})."
        f" {evidence.reason}"
    )


def parse_evidence(comment_body: str) -> CheckerEvidence | None:
    """Extract CheckerEvidence from a GitHub comment body.

    Returns None if the tag is absent or the JSON is malformed — never raises.
    """
    tag = CHECKER_EVIDENCE_TAG
    start = comment_body.find(f"<!-- {tag}")
    if start == -1:
        return None
    end = comment_body.find("-->", start)
    if end == -1:
        return None
    json_text = comment_body[start + len(f"<!-- {tag}") : end].strip()
    try:
        payload = json.loads(json_text)
        verdict = CheckerVerdict(str(payload["verdict"]))
        return CheckerEvidence(
            repository=str(payload["repository"]),
            issue_number=int(payload["issue_number"]),
            pr_number=int(payload["pr_number"]),
            checked_head_sha=str(payload["checked_head_sha"]),
            checker_id=str(payload["checker_id"]),
            maker_id=str(payload["maker_id"]),
            verdict=verdict,
            required_checks_passed=bool(payload["required_checks_passed"]),
            reason=str(payload["reason"]),
            material_fingerprint=str(payload["material_fingerprint"]),
            repair_lineage=payload.get("repair_lineage"),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None

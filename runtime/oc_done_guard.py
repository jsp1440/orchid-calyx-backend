"""The ``oc-done`` false-completion rule.

``oc-done`` is a claim that governed work is finished. The claim is only
admissible when all of the following hold, and the guard fails closed to
``oc-validating`` otherwise:

1. the issue is closed;
2. a completion receipt on the issue names a full 40-hex implementation SHA
   that is reachable from the target branch (``main``);
3. when the issue asks for a change, that receipt reports
   ``changed_file_count > 0`` or a merged pull request references the issue.
   An issue labelled ``oc-validation-only`` is exempt from (3).

The decision is a pure function so it can be tested without GitHub; the
runner in ``scripts/oc_done_guard.py`` supplies the observations.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

DONE_LABEL = "oc-done"
VALIDATING_LABEL = "oc-validating"
VALIDATION_ONLY_LABEL = "oc-validation-only"

FULL_SHA = re.compile(r"^[a-f0-9]{40}$")
_RECEIPT_JSON = re.compile(r"`(\{.*\})`", re.DOTALL)
_RECEIPT_SCHEMAS = frozenset(
    {"oc.swarm-provider-free-result.v1", "oc.completion-receipt.v1"}
)


@dataclass(frozen=True)
class Receipt:
    sha: str | None
    changed_file_count: int | None
    disposition: str | None
    mode: str | None
    schema: str | None


@dataclass(frozen=True)
class Observation:
    number: int
    state: str
    labels: tuple[str, ...]
    receipts: tuple[Receipt, ...] = ()
    merged_pull_request_shas: tuple[str, ...] = ()


@dataclass(frozen=True)
class Decision:
    number: int
    allowed: bool
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)


def parse_receipt_comment(body: str) -> Receipt | None:
    """Extract a completion receipt from an ``[OC-SWARM-V4] ... `{json}` `` comment."""
    match = _RECEIPT_JSON.search(body or "")
    if match is None:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    if (
        not isinstance(payload, Mapping)
        or payload.get("schema") not in _RECEIPT_SCHEMAS
    ):
        return None
    sha = payload.get("implementation_sha") or payload.get("integration_sha")
    sha = str(sha).strip().lower() if sha else None
    write_set = payload.get("write_set") or {}
    count = payload.get("changed_file_count", write_set.get("changed_file_count"))
    return Receipt(
        sha=sha if sha and FULL_SHA.fullmatch(sha) else None,
        changed_file_count=int(count)
        if isinstance(count, int) and not isinstance(count, bool)
        else None,
        disposition=payload.get("disposition") or payload.get("terminal_state"),
        mode=payload.get("mode"),
        schema=payload.get("schema"),
    )


def decide(observation: Observation, sha_on_target: Callable[[str], bool]) -> Decision:
    """Apply the rule. ``sha_on_target`` answers whether a SHA is reachable from main."""
    number = observation.number
    if DONE_LABEL not in observation.labels:
        return Decision(number, True, "not_claimed")
    if observation.state != "closed":
        return Decision(number, False, "issue_open")

    done_receipts = [
        r
        for r in observation.receipts
        if r.disposition in {"done", "completed"} and r.sha
    ]
    if not done_receipts:
        return Decision(number, False, "no_receipt_with_full_sha")

    anchored = [r for r in done_receipts if sha_on_target(r.sha or "")]
    if not anchored:
        return Decision(
            number,
            False,
            "receipt_sha_not_on_target_branch",
            {"shas": sorted({r.sha for r in done_receipts if r.sha})},
        )

    if VALIDATION_ONLY_LABEL in observation.labels:
        return Decision(
            number, True, "validation_only_issue", {"sha": anchored[-1].sha}
        )
    if observation.merged_pull_request_shas:
        return Decision(
            number,
            True,
            "merged_pull_request",
            {"merged": list(observation.merged_pull_request_shas)},
        )
    changed = [r for r in anchored if (r.changed_file_count or 0) > 0]
    if changed:
        return Decision(number, True, "changed_files_receipt", {"sha": changed[-1].sha})
    return Decision(
        number,
        False,
        "no_change_evidence",
        {
            "sha": anchored[-1].sha,
            "changed_file_count": anchored[-1].changed_file_count,
        },
    )


def transitions(decisions: Iterable[Decision]) -> list[dict[str, Any]]:
    """Label transitions for every refused claim: remove oc-done, add oc-validating."""
    return [
        {
            "number": d.number,
            "remove": [DONE_LABEL],
            "add": [VALIDATING_LABEL],
            "reason": d.reason,
            "evidence": d.evidence,
        }
        for d in decisions
        if not d.allowed
    ]

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from .github_coding_executor import RepositorySnapshot
from .github_proposal_mutation_adapter import GitHubTransport, GitHubTransportResponse

_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{3,}")


class GitHubRepositoryConvergenceInspector:
    """Conservative read-only convergence inspection against GitHub metadata.

    Exact mission-id matches drive CONTINUE/CONVERGE classification. Objective
    token overlap is recorded only as overlap evidence; it never by itself marks
    work complete or forces convergence. This avoids fabricating equivalence.
    """

    def __init__(
        self,
        *,
        transport: GitHubTransport,
        repository_allowlist: Sequence[str],
        base_ref: str = "main",
    ) -> None:
        allowlist = frozenset(
            item.strip() for item in repository_allowlist if item.strip()
        )
        if not allowlist:
            raise ValueError("GITHUB_INSPECTOR_REPOSITORY_ALLOWLIST_REQUIRED")
        if base_ref != "main":
            raise ValueError("GITHUB_INSPECTOR_BASE_REF_NOT_ALLOWED")
        self._transport = transport
        self._repository_allowlist = allowlist
        self._base_ref = base_ref

    def inspect(
        self,
        *,
        repository: str,
        objective: str,
        mission_id: str,
    ) -> RepositorySnapshot:
        if repository not in self._repository_allowlist:
            raise PermissionError("GITHUB_INSPECTOR_REPOSITORY_NOT_ALLOWED")
        normalized_mission = mission_id.strip().casefold()
        if not normalized_mission:
            raise ValueError("GITHUB_INSPECTOR_MISSION_ID_REQUIRED")

        base_sha = self._base_sha(repository)
        prs = self._list(repository, "pulls?state=open&per_page=100")
        issues = self._list(repository, "issues?state=open&per_page=100")

        exact_prs: list[int] = []
        overlap_prs: list[int] = []
        for item in prs:
            number = self._number(item)
            text = self._text(item)
            if normalized_mission in text.casefold():
                exact_prs.append(number)
            elif self._objective_overlap(objective, text):
                overlap_prs.append(number)

        related_issues: list[int] = []
        for item in issues:
            if "pull_request" in item:
                continue
            number = self._number(item)
            text = self._text(item)
            if normalized_mission in text.casefold() or self._objective_overlap(
                objective, text
            ):
                related_issues.append(number)

        exact = tuple(sorted(set(exact_prs)))
        overlaps = tuple(sorted({*exact_prs, *overlap_prs}))
        continuation = exact if len(exact) == 1 else ()
        convergence = exact if len(exact) > 1 else ()
        return RepositorySnapshot(
            repository=repository,
            base_ref=self._base_ref,
            base_sha=base_sha,
            related_issue_numbers=tuple(sorted(set(related_issues))),
            overlapping_pr_numbers=overlaps,
            continuation_pr_numbers=continuation,
            convergence_pr_numbers=convergence,
            superseded_pr_numbers=(),
            implementation_complete=False,
        )

    def _base_sha(self, repository: str) -> str:
        response = self._transport.request(
            "GET", f"/repos/{repository}/git/ref/heads/{self._base_ref}"
        )
        self._require_status(response, {200}, "GITHUB_INSPECTOR_BASE_LOOKUP_FAILED")
        payload = self._mapping(response.payload)
        obj = self._mapping(payload.get("object"))
        sha = str(obj.get("sha") or "").strip().lower()
        if len(sha) != 40 or any(
            character not in "0123456789abcdef" for character in sha
        ):
            raise RuntimeError("GITHUB_INSPECTOR_BASE_SHA_INVALID")
        return sha

    def _list(self, repository: str, suffix: str) -> list[Mapping[str, object]]:
        response = self._transport.request("GET", f"/repos/{repository}/{suffix}")
        self._require_status(response, {200}, "GITHUB_INSPECTOR_LIST_FAILED")
        if not isinstance(response.payload, list):
            raise TypeError("GITHUB_INSPECTOR_LIST_RESPONSE_INVALID")
        return [self._mapping(item) for item in response.payload]

    @staticmethod
    def _text(item: Mapping[str, object]) -> str:
        return f"{item.get('title') or ''}\n{item.get('body') or ''}"

    @staticmethod
    def _number(item: Mapping[str, object]) -> int:
        try:
            number = int(item.get("number"))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("GITHUB_INSPECTOR_NUMBER_INVALID") from exc
        if number <= 0:
            raise RuntimeError("GITHUB_INSPECTOR_NUMBER_INVALID")
        return number

    @classmethod
    def _objective_overlap(cls, objective: str, candidate: str) -> bool:
        objective_tokens = {
            token.casefold() for token in _WORD_RE.findall(objective) if len(token) >= 5
        }
        candidate_tokens = {
            token.casefold() for token in _WORD_RE.findall(candidate) if len(token) >= 5
        }
        if not objective_tokens:
            return False
        shared = objective_tokens & candidate_tokens
        return len(shared) >= min(3, len(objective_tokens))

    @staticmethod
    def _mapping(value: object) -> Mapping[str, object]:
        if not isinstance(value, Mapping):
            raise TypeError("GITHUB_INSPECTOR_MAPPING_REQUIRED")
        return value

    @staticmethod
    def _require_status(
        response: GitHubTransportResponse,
        allowed: set[int],
        code: str,
    ) -> None:
        if response.status_code not in allowed:
            raise RuntimeError(f"{code}:{response.status_code}")

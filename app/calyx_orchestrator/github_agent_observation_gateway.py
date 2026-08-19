from __future__ import annotations

from collections.abc import Mapping, Sequence

from .github_agent_ci_policy import RequiredCiCheckPolicy
from .github_agent_lifecycle import GitHubAgentDispatchRecord, PullRequestObservation
from .github_proposal_mutation_adapter import GitHubTransport, GitHubTransportResponse

COPILOT_BOT_LOGIN = "copilot-swe-agent[bot]"


class GitHubIssueLinkedPullRequestObserver:
    """Production `AgentObservationGateway`.

    Resolves the coding agent's draft PR from the durable GitHub issue
    timeline rather than fuzzy title/objective search - the exact pattern
    this repository's own history demonstrates on issue #402 -> PR #404:
    an `assigned` event, then a `cross-referenced` event whose source is a
    Copilot-authored PR, then a `connected` event. Only the `assigned`
    issue number and the resulting linked-PR candidate are ever trusted;
    nothing here is inferred from titles or objective text.

    Once a PR number is durably bound to a dispatch (`dispatch.pull_request_number`
    is no longer None), this observer never re-derives it from the timeline
    again - every subsequent observation re-reads that exact PR by number.
    A PR that is closed without merging, or whose base repository no longer
    matches, is therefore always caught here rather than silently re-resolved
    to a different candidate; a PR *number* that GitHub itself reassigns to a
    different repository/author is caught by the provenance re-check in
    `_fetch_pull_request`, and any downstream identity drift is additionally
    caught by `reconcile_agent_lifecycle`'s own PR-identity guard.
    """

    def __init__(
        self,
        *,
        transport: GitHubTransport,
        required_checks: RequiredCiCheckPolicy,
        bot_login: str = COPILOT_BOT_LOGIN,
    ) -> None:
        self._transport = transport
        self._required_checks = required_checks
        self._bot_login = bot_login

    def observe(self, dispatch: GitHubAgentDispatchRecord) -> PullRequestObservation:
        pr_number = dispatch.pull_request_number
        if pr_number is None:
            pr_number = self._resolve_linked_pr(dispatch)
            if pr_number is None:
                return PullRequestObservation(
                    repository=dispatch.repository,
                    issue_number=dispatch.issue_number,
                )

        pr = self._fetch_pull_request(dispatch.repository, pr_number)
        head_sha = self._head_sha(pr)
        merged = bool(pr.get("merged"))

        if not merged and str(pr.get("state") or "") == "closed":
            raise PermissionError("GITHUB_OBSERVATION_PR_CLOSED_WITHOUT_MERGE")

        if merged:
            return PullRequestObservation(
                repository=dispatch.repository,
                issue_number=dispatch.issue_number,
                pull_request_number=pr_number,
                pull_request_url=str(pr.get("html_url") or ""),
                draft=bool(pr.get("draft")),
                merged=True,
                head_sha=head_sha,
            )

        assessment = self._required_checks.evaluate(self._check_runs(dispatch.repository, head_sha))
        failure_class = None
        if assessment.required_checks_failed:
            failure_class = "required_ci_failure:" + ",".join(assessment.required_checks_failed)

        return PullRequestObservation(
            repository=dispatch.repository,
            issue_number=dispatch.issue_number,
            pull_request_number=pr_number,
            pull_request_url=str(pr.get("html_url") or ""),
            draft=bool(pr.get("draft")),
            merged=False,
            head_sha=head_sha,
            required_checks_known=assessment.required_checks_known,
            required_checks_pending=assessment.required_checks_pending,
            required_checks_failed=assessment.required_checks_failed,
            required_checks_succeeded=assessment.required_checks_succeeded,
            infrastructure_failure=assessment.infrastructure_failure,
            failure_class=failure_class,
        )

    def _resolve_linked_pr(self, dispatch: GitHubAgentDispatchRecord) -> int | None:
        events = self._timeline(dispatch.repository, dispatch.issue_number)
        candidates: set[int] = set()
        for event in events:
            if event.get("event") != "cross-referenced":
                continue
            source = self._loose_mapping(event.get("source"))
            if source.get("type") != "issue":
                continue
            source_issue = self._loose_mapping(source.get("issue"))
            if "pull_request" not in source_issue:
                continue
            user = self._loose_mapping(source_issue.get("user"))
            if user.get("login") != self._bot_login:
                continue
            repo = self._loose_mapping(source_issue.get("repository"))
            full_name = str(repo.get("full_name") or "")
            if full_name and full_name != dispatch.repository:
                continue
            number = source_issue.get("number")
            if isinstance(number, int) and number > 0:
                candidates.add(number)
        if not candidates:
            return None
        if len(candidates) > 1:
            raise RuntimeError("GITHUB_OBSERVATION_AMBIGUOUS_PR_LINKAGE")
        return next(iter(candidates))

    def _fetch_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object]:
        response = self._transport.request("GET", f"/repos/{repository}/pulls/{pr_number}")
        self._require_status(response, {200}, "GITHUB_OBSERVATION_PR_LOOKUP_FAILED")
        pr = self._strict_mapping(response.payload)
        base = self._strict_mapping(pr.get("base"))
        base_repo = self._strict_mapping(base.get("repo"))
        if str(base_repo.get("full_name") or "") != repository:
            raise PermissionError("GITHUB_OBSERVATION_REPOSITORY_MISMATCH")
        user = self._strict_mapping(pr.get("user"))
        if user.get("login") != self._bot_login:
            raise PermissionError("GITHUB_OBSERVATION_PR_PROVENANCE_MISMATCH")
        return pr

    @staticmethod
    def _head_sha(pr: Mapping[str, object]) -> str:
        head = pr.get("head")
        if not isinstance(head, Mapping):
            raise TypeError("GITHUB_OBSERVATION_HEAD_SHA_INVALID")
        sha = str(head.get("sha") or "").strip().lower()
        if len(sha) != 40 or any(character not in "0123456789abcdef" for character in sha):
            raise RuntimeError("GITHUB_OBSERVATION_HEAD_SHA_INVALID")
        return sha

    def _timeline(self, repository: str, issue_number: int) -> Sequence[Mapping[str, object]]:
        response = self._transport.request(
            "GET", f"/repos/{repository}/issues/{issue_number}/timeline?per_page=100"
        )
        self._require_status(response, {200}, "GITHUB_OBSERVATION_TIMELINE_LOOKUP_FAILED")
        if not isinstance(response.payload, list):
            raise TypeError("GITHUB_OBSERVATION_TIMELINE_RESPONSE_INVALID")
        return [self._strict_mapping(item) for item in response.payload]

    def _check_runs(self, repository: str, head_sha: str) -> dict[str, str | None]:
        response = self._transport.request(
            "GET", f"/repos/{repository}/commits/{head_sha}/check-runs?per_page=100"
        )
        self._require_status(response, {200}, "GITHUB_OBSERVATION_CHECK_RUNS_LOOKUP_FAILED")
        payload = self._strict_mapping(response.payload)
        runs = payload.get("check_runs")
        if not isinstance(runs, list):
            raise TypeError("GITHUB_OBSERVATION_CHECK_RUNS_RESPONSE_INVALID")
        result: dict[str, str | None] = {}
        for item in runs:
            entry = self._strict_mapping(item)
            name = str(entry.get("name") or "")
            if not name:
                continue
            conclusion = entry.get("conclusion") if entry.get("status") == "completed" else None
            result[name] = str(conclusion) if conclusion is not None else None
        return result

    @staticmethod
    def _loose_mapping(value: object) -> Mapping[str, object]:
        """For optional nested traversal while scanning unrelated timeline
        events - a malformed/incomplete event unrelated to this dispatch
        must be skipped, not crash the whole observation."""
        return value if isinstance(value, Mapping) else {}

    @staticmethod
    def _strict_mapping(value: object) -> Mapping[str, object]:
        """For payloads this dispatch's own identity depends on - a
        malformed direct API response must fail loudly, not be papered
        over with an empty default."""
        if not isinstance(value, Mapping):
            raise TypeError("GITHUB_OBSERVATION_MAPPING_REQUIRED")
        return value

    @staticmethod
    def _require_status(response: GitHubTransportResponse, allowed: set[int], code: str) -> None:
        if response.status_code not in allowed:
            raise RuntimeError(f"{code}:{response.status_code}")

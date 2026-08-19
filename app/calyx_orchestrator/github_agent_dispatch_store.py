from __future__ import annotations

import json
from collections.abc import Mapping

from sqlalchemy import Integer, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.database import Base

from .github_agent_lifecycle import AgentLifecycleState, GitHubAgentDispatchRecord


class GitHubAgentDispatchRecordRow(Base):
    __tablename__ = "calyx_github_agent_dispatches"
    __table_args__ = (
        UniqueConstraint(
            "program_job_id",
            name="uq_calyx_github_agent_dispatch_program_job",
        ),
    )

    dispatch_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    program_job_id: Mapped[str] = mapped_column(String(128), index=True)
    mission_id: Mapped[str] = mapped_column(String(160), index=True)
    repository: Mapped[str] = mapped_column(String(256), index=True)
    base_sha: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(128))
    issue_number: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(64), index=True)
    branch: Mapped[str | None] = mapped_column(String(240), nullable=True)
    pull_request_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pull_request_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    head_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    repair_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_failure_class: Mapped[str | None] = mapped_column(String(256), nullable=True)
    snapshot_json: Mapped[str] = mapped_column(Text)


_ALLOWED_TRANSITIONS: dict[AgentLifecycleState, frozenset[AgentLifecycleState]] = {
    AgentLifecycleState.AGENT_ASSIGNED: frozenset(
        {
            AgentLifecycleState.AGENT_ASSIGNED,
            AgentLifecycleState.AWAITING_PR,
            AgentLifecycleState.CI_PENDING,
            AgentLifecycleState.BLOCKED,
        }
    ),
    AgentLifecycleState.AWAITING_PR: frozenset(
        {
            AgentLifecycleState.AWAITING_PR,
            AgentLifecycleState.CI_PENDING,
            AgentLifecycleState.BLOCKED,
        }
    ),
    AgentLifecycleState.CI_PENDING: frozenset(
        {
            AgentLifecycleState.CI_PENDING,
            AgentLifecycleState.REPAIR_REQUIRED,
            AgentLifecycleState.READY_FOR_OWNER_REVIEW,
            AgentLifecycleState.MERGED,
            AgentLifecycleState.BLOCKED,
        }
    ),
    AgentLifecycleState.REPAIR_REQUIRED: frozenset(
        {
            AgentLifecycleState.REPAIR_REQUIRED,
            AgentLifecycleState.CI_PENDING,
            AgentLifecycleState.BLOCKED,
        }
    ),
    AgentLifecycleState.READY_FOR_OWNER_REVIEW: frozenset(
        {
            AgentLifecycleState.READY_FOR_OWNER_REVIEW,
            AgentLifecycleState.CI_PENDING,
            AgentLifecycleState.MERGED,
            AgentLifecycleState.BLOCKED,
        }
    ),
    AgentLifecycleState.MERGED: frozenset({AgentLifecycleState.MERGED}),
    AgentLifecycleState.BLOCKED: frozenset({AgentLifecycleState.BLOCKED}),
}


class DurableGitHubAgentDispatchStore:
    """One durable, identity-bound asynchronous dispatch record per Calyx job."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, *, program_job_id: str) -> GitHubAgentDispatchRecord | None:
        row = self.db.scalar(
            select(GitHubAgentDispatchRecordRow).where(
                GitHubAgentDispatchRecordRow.program_job_id == program_job_id
            )
        )
        return None if row is None else self._decode(row)

    def record(self, dispatch: GitHubAgentDispatchRecord) -> GitHubAgentDispatchRecord:
        dispatch.verify()
        existing_row = self.db.scalar(
            select(GitHubAgentDispatchRecordRow).where(
                GitHubAgentDispatchRecordRow.program_job_id == dispatch.program_job_id
            )
        )
        if existing_row is None:
            row = GitHubAgentDispatchRecordRow(**self._columns(dispatch))
            self.db.add(row)
            self.db.commit()
            self.db.refresh(row)
            return self._decode(row)

        existing = self._decode(existing_row)
        self._validate_identity(existing=existing, current=dispatch)
        self._validate_transition(existing=existing, current=dispatch)
        if existing == dispatch:
            return existing

        columns = self._columns(dispatch)
        for key, value in columns.items():
            setattr(existing_row, key, value)
        self.db.commit()
        self.db.refresh(existing_row)
        return self._decode(existing_row)

    @staticmethod
    def _validate_identity(
        *,
        existing: GitHubAgentDispatchRecord,
        current: GitHubAgentDispatchRecord,
    ) -> None:
        if (
            existing.program_job_id != current.program_job_id
            or existing.mission_id != current.mission_id
            or existing.repository != current.repository
            or existing.base_sha != current.base_sha
            or existing.provider != current.provider
            or existing.issue_number != current.issue_number
            or existing.branch != current.branch
        ):
            raise PermissionError("GITHUB_AGENT_DISPATCH_DURABLE_IDENTITY_CHANGED")
        if (
            existing.pull_request_number is not None
            and current.pull_request_number != existing.pull_request_number
        ):
            raise PermissionError("GITHUB_AGENT_DISPATCH_DURABLE_PR_CHANGED")
        if existing.repair_attempts > current.repair_attempts:
            raise PermissionError("GITHUB_AGENT_DISPATCH_REPAIR_COUNT_REGRESSED")

    @staticmethod
    def _validate_transition(
        *,
        existing: GitHubAgentDispatchRecord,
        current: GitHubAgentDispatchRecord,
    ) -> None:
        allowed = _ALLOWED_TRANSITIONS[existing.state]
        if current.state not in allowed:
            raise PermissionError("GITHUB_AGENT_DISPATCH_STATE_REGRESSION")
        if current.repair_attempts > existing.repair_attempts + 1:
            raise PermissionError("GITHUB_AGENT_DISPATCH_REPAIR_COUNT_JUMP")
        if existing.state == AgentLifecycleState.MERGED and current != existing:
            raise PermissionError("GITHUB_AGENT_DISPATCH_MERGED_IMMUTABLE")

    @classmethod
    def _columns(cls, dispatch: GitHubAgentDispatchRecord) -> dict[str, object]:
        snapshot = cls._snapshot(dispatch)
        return {
            "program_job_id": dispatch.program_job_id,
            "mission_id": dispatch.mission_id,
            "repository": dispatch.repository,
            "base_sha": dispatch.base_sha,
            "provider": dispatch.provider,
            "issue_number": dispatch.issue_number,
            "state": dispatch.state.value,
            "branch": dispatch.branch,
            "pull_request_number": dispatch.pull_request_number,
            "pull_request_url": dispatch.pull_request_url,
            "head_sha": dispatch.head_sha,
            "repair_attempts": dispatch.repair_attempts,
            "last_failure_class": dispatch.last_failure_class,
            "snapshot_json": json.dumps(snapshot, sort_keys=True, separators=(",", ":")),
        }

    @staticmethod
    def _snapshot(dispatch: GitHubAgentDispatchRecord) -> dict[str, object]:
        return {
            "program_job_id": dispatch.program_job_id,
            "mission_id": dispatch.mission_id,
            "repository": dispatch.repository,
            "base_sha": dispatch.base_sha,
            "provider": dispatch.provider,
            "issue_number": dispatch.issue_number,
            "state": dispatch.state.value,
            "branch": dispatch.branch,
            "pull_request_number": dispatch.pull_request_number,
            "pull_request_url": dispatch.pull_request_url,
            "head_sha": dispatch.head_sha,
            "repair_attempts": dispatch.repair_attempts,
            "last_failure_class": dispatch.last_failure_class,
        }

    @classmethod
    def _decode(cls, row: GitHubAgentDispatchRecordRow) -> GitHubAgentDispatchRecord:
        try:
            payload = json.loads(row.snapshot_json)
        except (TypeError, ValueError) as exc:
            raise PermissionError("GITHUB_AGENT_DISPATCH_SNAPSHOT_INVALID") from exc
        if not isinstance(payload, Mapping):
            raise TypeError("GITHUB_AGENT_DISPATCH_SNAPSHOT_MAPPING_REQUIRED")
        record = GitHubAgentDispatchRecord(
            program_job_id=str(payload.get("program_job_id") or ""),
            mission_id=str(payload.get("mission_id") or ""),
            repository=str(payload.get("repository") or ""),
            base_sha=str(payload.get("base_sha") or ""),
            provider=str(payload.get("provider") or ""),
            issue_number=int(payload.get("issue_number") or 0),
            state=AgentLifecycleState(str(payload.get("state") or "")),
            branch=None if payload.get("branch") is None else str(payload["branch"]),
            pull_request_number=(
                None
                if payload.get("pull_request_number") is None
                else int(payload["pull_request_number"])
            ),
            pull_request_url=(
                None
                if payload.get("pull_request_url") is None
                else str(payload["pull_request_url"])
            ),
            head_sha=None if payload.get("head_sha") is None else str(payload["head_sha"]),
            repair_attempts=int(payload.get("repair_attempts") or 0),
            last_failure_class=(
                None
                if payload.get("last_failure_class") is None
                else str(payload["last_failure_class"])
            ),
        )
        record.verify()
        expected = cls._snapshot(record)
        if dict(payload) != expected:
            raise PermissionError("GITHUB_AGENT_DISPATCH_SNAPSHOT_DIVERGENCE")
        return record

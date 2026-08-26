"""Service layer for Continuum Engineering Memory v1.

Orchestrates the bounded vertical slice:

    capture sanitized run outcome
      -> store run and derive/promote lesson
      -> retrieve relevant verified memory (scope-isolated, lexical)
      -> record feedback
      -> measure usage and savings

Every mutation is fail-closed: malformed classification, missing provenance,
or an unresolved redaction state raises before anything is persisted.  Every
read and write is confined to a single ``workspace_scope``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import fingerprint as fp
from .models import (
    DATA_CLASSIFICATIONS,
    EVIDENCE_CLASS_NON_SCIENTIFIC,
    LESSON_CANDIDATE,
    LESSON_INVALIDATED,
    LESSON_VERIFIED,
    NON_RETURNABLE_STATUSES,
    RUN_OUTCOMES,
    VERIFICATION_REFUTED,
    VERIFICATION_VERIFIED,
    EngineeringMemoryLesson,
    EngineeringMemoryRetrieval,
    EngineeringMemoryRun,
)
from .redaction import (
    ProtectedLocalityError,
    assert_no_residual_secret,
    redact_payload,
    redact_text,
)
from .retrieval import DEFAULT_CHAR_BUDGET, DEFAULT_LIMIT, ScoredLesson, rank_lessons

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class EngineeringMemoryError(Exception):
    """Base error for the engineering-memory service."""


class MemoryValidationError(EngineeringMemoryError, ValueError):
    """A write violated a fail-closed contract."""


class MemoryNotFoundError(EngineeringMemoryError):
    """A referenced run/lesson/retrieval does not exist within scope."""


class ScopeViolationError(EngineeringMemoryError):
    """An operation crossed a workspace-scope boundary."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _require_scope(scope: str | None) -> str:
    value = (scope or "").strip()
    if not value:
        raise MemoryValidationError("workspace_scope is required")
    return value


def _require_classification(classification: str | None) -> str:
    value = (classification or "").strip()
    if value not in DATA_CLASSIFICATIONS:
        raise MemoryValidationError(
            f"data_classification must be one of {DATA_CLASSIFICATIONS}"
        )
    return value


def _require_non_scientific(evidence_class: str | None) -> str:
    # Engineering memory is never scientific evidence.  Accept the canonical
    # value or an unset value; reject any attempt to relabel it.
    if evidence_class not in (None, "", EVIDENCE_CLASS_NON_SCIENTIFIC):
        raise MemoryValidationError(
            "engineering memory is non_scientific_evidence and cannot be relabeled"
        )
    return EVIDENCE_CLASS_NON_SCIENTIFIC


# ---------------------------------------------------------------------------
# Presentation
# ---------------------------------------------------------------------------


def lesson_to_public_dict(lesson: EngineeringMemoryLesson) -> dict:
    """Serialize a lesson for retrieval responses.

    Always carries provenance, verification/lifecycle metadata, and an explicit
    non-scientific-evidence marker so callers cannot present it as science.
    """

    return {
        "lesson_id": lesson.lesson_id,
        "workspace_scope": lesson.workspace_scope,
        "repository": lesson.repository,
        "module": lesson.module,
        "problem": lesson.problem,
        "cause": lesson.cause,
        "solution": lesson.solution,
        "applicability": lesson.applicability,
        "tags": list(lesson.tags or []),
        "status": lesson.status,
        "verification_status": lesson.verification_status,
        "confidence": lesson.confidence,
        "provenance": {
            "source_run_id": lesson.source_run_id,
            "github": dict(lesson.github_provenance or {}),
        },
        "invalidation": {
            "dependency_fingerprint": lesson.dependency_fingerprint,
            "schema_fingerprint": lesson.schema_fingerprint,
            "file_fingerprints": dict(lesson.file_fingerprints or {}),
            "expires_at": lesson.expires_at.isoformat() if lesson.expires_at else None,
            "invalidated_reason": lesson.invalidated_reason,
        },
        "evidence_class": EVIDENCE_CLASS_NON_SCIENTIFIC,
        "is_scientific_evidence": False,
    }


NON_SCIENTIFIC_DISCLAIMER = (
    "Engineering memory is non_scientific_evidence. It records how software was "
    "built and must never be used as scientific evidence, provenance, or fact."
)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


@dataclass
class RetrieveResult:
    retrieval: EngineeringMemoryRetrieval
    scored: list[ScoredLesson]
    injected_chars: int


class EngineeringMemoryService:
    """Stateless service; all state lives in the passed-in DB session."""

    # -- capture ---------------------------------------------------------

    def capture_run(self, db: Session, payload: dict) -> EngineeringMemoryRun:
        scope = _require_scope(payload.get("workspace_scope"))
        classification = _require_classification(payload.get("data_classification"))
        evidence_class = _require_non_scientific(payload.get("evidence_class"))

        outcome = (payload.get("outcome") or "").strip()
        if outcome not in RUN_OUTCOMES:
            raise MemoryValidationError(f"outcome must be one of {RUN_OUTCOMES}")

        repository = (payload.get("repository") or "").strip()
        if not repository:
            raise MemoryValidationError("repository is required")

        executor = (payload.get("executor") or "").strip()
        if not executor:
            raise MemoryValidationError("executor is required")

        strict_locality = bool(payload.get("strict_locality", False))

        # Redact the only free-text surface we persist.  Raw prompts and
        # conversations are never accepted (see schema extra=forbid) or stored.
        try:
            redaction = redact_payload(
                {"sanitized_summary": payload.get("sanitized_summary") or ""},
                strict_locality=strict_locality,
            )
        except ProtectedLocalityError as exc:
            raise MemoryValidationError(str(exc)) from exc

        summary = redaction.fields["sanitized_summary"]
        assert_no_residual_secret(summary)

        run = EngineeringMemoryRun(
            executor=executor,
            provider=(payload.get("provider") or None),
            workspace_scope=scope,
            repository=repository,
            branch=(payload.get("branch") or None),
            task_ref=(payload.get("task_ref") or None),
            issue_ref=(payload.get("issue_ref") or None),
            pr_ref=(payload.get("pr_ref") or None),
            commit_shas=list(payload.get("commit_shas") or []),
            outcome=outcome,
            checks=dict(payload.get("checks") or {}),
            sanitized_summary=summary,
            tokens_input=payload.get("tokens_input"),
            tokens_output=payload.get("tokens_output"),
            turns=payload.get("turns"),
            elapsed_ms=payload.get("elapsed_ms"),
            data_classification=classification,
            evidence_class=evidence_class,
            redaction_status=redaction.status,
            redaction_report=redaction.report,
        )
        db.add(run)
        db.flush()
        return run

    # -- lessons ---------------------------------------------------------

    def create_lesson(self, db: Session, payload: dict) -> EngineeringMemoryLesson:
        scope = _require_scope(payload.get("workspace_scope"))
        classification = _require_classification(payload.get("data_classification"))
        evidence_class = _require_non_scientific(payload.get("evidence_class"))

        repository = (payload.get("repository") or "").strip()
        if not repository:
            raise MemoryValidationError("repository is required")

        problem = (payload.get("problem") or "").strip()
        solution = (payload.get("solution") or "").strip()
        if not problem or not solution:
            raise MemoryValidationError("problem and solution are required")

        source_run_id = payload.get("source_run_id") or None
        github_provenance = dict(payload.get("github_provenance") or {})
        if not source_run_id and not github_provenance:
            raise MemoryValidationError(
                "provenance is required: supply source_run_id or github_provenance"
            )

        # A referenced source run must exist within the same scope.
        if source_run_id is not None:
            run = db.get(EngineeringMemoryRun, source_run_id)
            if run is None:
                raise MemoryValidationError("source_run_id does not exist")
            if run.workspace_scope != scope:
                raise ScopeViolationError("source run belongs to another scope")

        strict_locality = bool(payload.get("strict_locality", False))
        try:
            redaction = redact_payload(
                {
                    "problem": problem,
                    "cause": payload.get("cause") or "",
                    "solution": solution,
                    "applicability": payload.get("applicability") or "",
                },
                strict_locality=strict_locality,
            )
        except ProtectedLocalityError as exc:
            raise MemoryValidationError(str(exc)) from exc

        fields = redaction.fields
        tags = [str(t).strip() for t in (payload.get("tags") or []) if str(t).strip()]
        # Redact tags too, defensively.
        tags = [redact_text(t).text for t in tags]

        assert_no_residual_secret(
            fields["problem"], fields["cause"], fields["solution"], fields["applicability"]
        )

        lexical_document = self._build_lexical_document(
            fields["problem"],
            fields["cause"],
            fields["solution"],
            fields["applicability"],
            payload.get("module"),
            tags,
        )

        expires_at = payload.get("expires_at")
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at)

        lesson = EngineeringMemoryLesson(
            workspace_scope=scope,
            repository=repository,
            module=(payload.get("module") or None),
            problem=fields["problem"],
            cause=fields["cause"],
            solution=fields["solution"],
            applicability=fields["applicability"],
            tags=tags,
            lexical_document=lexical_document,
            embedding=payload.get("embedding"),
            source_run_id=source_run_id,
            github_provenance=github_provenance,
            status=LESSON_CANDIDATE,
            verification_status="unverified",
            confidence=(payload.get("confidence") or "low"),
            dependency_fingerprint=fp.dependency_fingerprint(payload.get("dependencies")),
            schema_fingerprint=fp.schema_fingerprint(payload.get("schema_marker")),
            file_fingerprints=fp.file_fingerprints(payload.get("files")),
            data_classification=classification,
            evidence_class=evidence_class,
            redaction_status=redaction.status,
            redaction_report=redaction.report,
            expires_at=expires_at,
        )
        db.add(lesson)
        db.flush()
        return lesson

    @staticmethod
    def _build_lexical_document(
        problem: str,
        cause: str,
        solution: str,
        applicability: str,
        module: str | None,
        tags: list[str],
    ) -> str:
        parts = [problem, cause, solution, applicability]
        if module:
            parts.append(module)
        if tags:
            parts.append(" ".join(tags))
        return "\n".join(p for p in parts if p)

    def _get_scoped_lesson(
        self, db: Session, lesson_id: str, scope: str
    ) -> EngineeringMemoryLesson:
        lesson = db.get(EngineeringMemoryLesson, lesson_id)
        if lesson is None:
            raise MemoryNotFoundError("lesson not found")
        if lesson.workspace_scope != scope:
            raise ScopeViolationError("lesson belongs to another scope")
        return lesson

    def verify_lesson(
        self, db: Session, lesson_id: str, scope: str, evidence: dict
    ) -> EngineeringMemoryLesson:
        scope = _require_scope(scope)
        lesson = self._get_scoped_lesson(db, lesson_id, scope)
        if not evidence:
            raise MemoryValidationError("verification evidence is required")
        lesson.status = LESSON_VERIFIED
        lesson.verification_status = VERIFICATION_VERIFIED
        lesson.verification_evidence = dict(evidence)
        # Promotion raises trust unless the caller pins it lower.
        if lesson.confidence == "low":
            lesson.confidence = "medium"
        db.flush()
        return lesson

    def invalidate_lesson(
        self, db: Session, lesson_id: str, scope: str, reason: str
    ) -> EngineeringMemoryLesson:
        scope = _require_scope(scope)
        lesson = self._get_scoped_lesson(db, lesson_id, scope)
        reason = (reason or "").strip() or "manual_invalidation"
        lesson.status = LESSON_INVALIDATED
        lesson.invalidated_reason = reason
        if lesson.verification_status == VERIFICATION_VERIFIED:
            lesson.verification_status = VERIFICATION_REFUTED
        db.flush()
        return lesson

    def invalidate_by_fingerprints(
        self,
        db: Session,
        scope: str,
        *,
        current_dependency: str | None = None,
        current_schema: str | None = None,
        current_files: dict | None = None,
    ) -> list[EngineeringMemoryLesson]:
        """Deterministically invalidate lessons whose fingerprints diverged."""

        scope = _require_scope(scope)
        rows = (
            db.execute(
                select(EngineeringMemoryLesson).where(
                    EngineeringMemoryLesson.workspace_scope == scope,
                    EngineeringMemoryLesson.status.in_(
                        (LESSON_CANDIDATE, LESSON_VERIFIED)
                    ),
                )
            )
            .scalars()
            .all()
        )
        invalidated: list[EngineeringMemoryLesson] = []
        for lesson in rows:
            diverged, reasons = fp.fingerprints_diverged(
                stored_dependency=lesson.dependency_fingerprint,
                stored_schema=lesson.schema_fingerprint,
                stored_files=lesson.file_fingerprints,
                current_dependency=current_dependency,
                current_schema=current_schema,
                current_files=current_files,
            )
            if diverged:
                lesson.status = LESSON_INVALIDATED
                lesson.invalidated_reason = ";".join(reasons)
                invalidated.append(lesson)
        db.flush()
        return invalidated

    # -- retrieval -------------------------------------------------------

    def retrieve(
        self,
        db: Session,
        payload: dict,
        *,
        embedding_adapter=None,
    ) -> RetrieveResult:
        scope = _require_scope(payload.get("workspace_scope"))
        query = (payload.get("query") or "").strip()
        if not query:
            raise MemoryValidationError("query is required")

        limit = int(payload.get("limit") or DEFAULT_LIMIT)
        limit = max(1, min(limit, DEFAULT_LIMIT))  # never exceed 5
        char_budget = int(payload.get("char_budget") or DEFAULT_CHAR_BUDGET)
        module = payload.get("module") or None

        # Redact the query itself before storing/using it.
        query = redact_text(query).text

        now = _utcnow()
        conditions = [
            EngineeringMemoryLesson.workspace_scope == scope,
            EngineeringMemoryLesson.status.notin_(tuple(NON_RETURNABLE_STATUSES)),
        ]
        if module:
            conditions.append(EngineeringMemoryLesson.module == module)

        candidates = (
            db.execute(select(EngineeringMemoryLesson).where(*conditions))
            .scalars()
            .all()
        )
        # Exclude expired-by-time even if the status sweep has not run yet.
        candidates = [
            les
            for les in candidates
            if les.expires_at is None or _as_utc(les.expires_at) > now
        ]

        start = _utcnow()
        scored, injected_chars = rank_lessons(
            query,
            candidates,
            limit=limit,
            char_budget=char_budget,
            embedding_adapter=embedding_adapter,
        )
        latency_ms = int((_utcnow() - start).total_seconds() * 1000)

        retrieval = EngineeringMemoryRetrieval(
            workspace_scope=scope,
            repository=(payload.get("repository") or "").strip(),
            module=module,
            query_text=query,
            retrieved=[
                {
                    "lesson_id": s.lesson.lesson_id,
                    "rank": s.rank,
                    "score": round(s.score, 6),
                    "lexical_score": round(s.lexical_score, 6),
                    "status": s.lesson.status,
                    "verification_status": s.lesson.verification_status,
                }
                for s in scored
            ],
            injected=bool(payload.get("injected", False)),
            injected_char_budget=char_budget,
            injected_chars=injected_chars,
            latency_ms=latency_ms,
        )
        db.add(retrieval)
        db.flush()
        return RetrieveResult(
            retrieval=retrieval, scored=scored, injected_chars=injected_chars
        )

    # -- feedback --------------------------------------------------------

    def record_feedback(
        self, db: Session, retrieval_id: str, scope: str, payload: dict
    ) -> EngineeringMemoryRetrieval:
        scope = _require_scope(scope)
        retrieval = db.get(EngineeringMemoryRetrieval, retrieval_id)
        if retrieval is None:
            raise MemoryNotFoundError("retrieval not found")
        if retrieval.workspace_scope != scope:
            raise ScopeViolationError("retrieval belongs to another scope")

        feedback = (payload.get("feedback") or "").strip()
        allowed = {"helpful", "not_helpful", "unused"}
        if feedback not in allowed:
            raise MemoryValidationError(f"feedback must be one of {sorted(allowed)}")

        retrieval.feedback = feedback
        retrieval.injected = bool(payload.get("injected", retrieval.injected))
        outcome = payload.get("outcome")
        retrieval.feedback_outcome = dict(outcome) if outcome else None
        # NULL stays NULL (unavailable) unless a value is explicitly supplied.
        if "estimated_tokens_saved" in payload and payload["estimated_tokens_saved"] is not None:
            retrieval.estimated_tokens_saved = int(payload["estimated_tokens_saved"])
        db.flush()
        return retrieval

    # -- metrics ---------------------------------------------------------

    def metrics(self, db: Session, scope: str) -> dict:
        """Aggregate usage/savings telemetry for a scope.

        Measured zero and unavailable are kept distinct: a sum over rows that
        all carry NULL telemetry is reported as ``None`` (unavailable), not 0.
        """

        scope = _require_scope(scope)

        runs = (
            db.execute(
                select(EngineeringMemoryRun).where(
                    EngineeringMemoryRun.workspace_scope == scope
                )
            )
            .scalars()
            .all()
        )
        lessons = (
            db.execute(
                select(EngineeringMemoryLesson).where(
                    EngineeringMemoryLesson.workspace_scope == scope
                )
            )
            .scalars()
            .all()
        )
        retrievals = (
            db.execute(
                select(EngineeringMemoryRetrieval).where(
                    EngineeringMemoryRetrieval.workspace_scope == scope
                )
            )
            .scalars()
            .all()
        )

        lesson_status_counts: dict[str, int] = {}
        for lesson in lessons:
            lesson_status_counts[lesson.status] = (
                lesson_status_counts.get(lesson.status, 0) + 1
            )

        injected_count = sum(1 for r in retrievals if r.injected)
        feedback_counts: dict[str, int] = {}
        for r in retrievals:
            if r.feedback:
                feedback_counts[r.feedback] = feedback_counts.get(r.feedback, 0) + 1

        return {
            "workspace_scope": scope,
            "evidence_class": EVIDENCE_CLASS_NON_SCIENTIFIC,
            "runs": {
                "total": len(runs),
                "tokens_input": _sum_or_unavailable(r.tokens_input for r in runs),
                "tokens_output": _sum_or_unavailable(r.tokens_output for r in runs),
                "turns": _sum_or_unavailable(r.turns for r in runs),
            },
            "lessons": {
                "total": len(lessons),
                "by_status": lesson_status_counts,
                "verified": lesson_status_counts.get(LESSON_VERIFIED, 0),
            },
            "retrievals": {
                "total": len(retrievals),
                "injected": injected_count,
                "feedback": feedback_counts,
                "estimated_tokens_saved": _sum_or_unavailable(
                    r.estimated_tokens_saved for r in retrievals
                ),
                "avg_latency_ms": _avg_or_unavailable(r.latency_ms for r in retrievals),
            },
        }


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _sum_or_unavailable(values) -> int | None:
    present = [v for v in values if v is not None]
    if not present:
        return None
    return sum(present)


def _avg_or_unavailable(values) -> float | None:
    present = [v for v in values if v is not None]
    if not present:
        return None
    return round(sum(present) / len(present), 3)

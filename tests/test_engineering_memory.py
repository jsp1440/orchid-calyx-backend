"""Verification suite for Continuum Engineering Memory v1 (issue #1184).

Each test builds an isolated in-memory SQLite database from the ORM metadata,
matching the repository's ``Base.metadata.create_all(engine, tables=[...])``
convention.  The suite proves the safeguards, retrieval semantics, and the
deterministic end-to-end vertical slice required by the issue.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.engineering_memory.fingerprint import dependency_fingerprint
from app.engineering_memory.models import (
    EVIDENCE_CLASS_NON_SCIENTIFIC,
    TABLES,
    EngineeringMemoryLesson,
    EngineeringMemoryRun,
)
from app.engineering_memory.redaction import redact_text
from app.engineering_memory.schemas import RunCreateIn
from app.engineering_memory.service import (
    EngineeringMemoryService,
    MemoryValidationError,
    ScopeViolationError,
    lesson_to_public_dict,
)

SCOPE = "jsp1440/orchid-calyx-backend"
REPO = "jsp1440/orchid-calyx-backend"


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=list(TABLES))
    return sessionmaker(bind=engine)(), engine


def _svc():
    return EngineeringMemoryService()


def _run_payload(**over):
    payload = {
        "executor": "claude",
        "workspace_scope": SCOPE,
        "repository": REPO,
        "outcome": "success",
        "data_classification": "internal_engineering",
        "sanitized_summary": "did a thing",
    }
    payload.update(over)
    return payload


def _lesson_payload(**over):
    payload = {
        "workspace_scope": SCOPE,
        "repository": REPO,
        "module": "app/engineering_memory",
        "problem": "the widget failed to render",
        "solution": "recompute the layout before paint",
        "applicability": "widget rendering",
        "github_provenance": {"issue": "#1184"},
        "data_classification": "internal_engineering",
    }
    payload.update(over)
    return payload


# ---------------------------------------------------------------------------
# Safeguards
# ---------------------------------------------------------------------------


def test_secrets_are_redacted_before_persistence():
    db, _ = _session()
    svc = _svc()
    run = svc.capture_run(
        db,
        _run_payload(
            sanitized_summary="deploy used GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwx1234 today"
        ),
    )
    stored = db.get(EngineeringMemoryRun, run.run_id)
    assert "ghp_abcdefghijklmnopqrstuvwx1234" not in stored.sanitized_summary
    assert "REDACTED_SECRET" in stored.sanitized_summary
    assert stored.redaction_status == "redacted"
    assert "github_token" in stored.redaction_report["secret_labels"]
    # The report must never leak the raw value.
    assert "ghp_abcdefghijklmnopqrstuvwx1234" not in str(stored.redaction_report)


def test_protected_locality_reduced_by_default_and_rejected_when_strict():
    db, _ = _session()
    svc = _svc()
    run = svc.capture_run(
        db, _run_payload(sanitized_summary="found at -0.1807, -78.4678 near the ridge")
    )
    assert "-0.1807" not in run.sanitized_summary
    assert "[REDACTED_COORDINATES]" in run.sanitized_summary
    assert run.redaction_report["locality_count"] == 1

    with pytest.raises(MemoryValidationError):
        svc.capture_run(
            db,
            _run_payload(
                sanitized_summary="protected site 4.5709, -74.2973",
                strict_locality=True,
            ),
        )


def test_raw_prompt_or_conversation_is_rejected_by_schema():
    # extra="forbid" means unmodelled raw prompt/conversation fields are rejected,
    # so raw prompts/conversations are not stored by default.
    with pytest.raises(ValidationError):
        RunCreateIn(**_run_payload(raw_prompt="my secret system prompt"))
    with pytest.raises(ValidationError):
        RunCreateIn(**_run_payload(conversation=[{"role": "user", "content": "hi"}]))


def test_malformed_classification_fails_closed():
    db, _ = _session()
    svc = _svc()
    with pytest.raises(MemoryValidationError):
        svc.capture_run(db, _run_payload(data_classification="totally_made_up"))


def test_lesson_requires_provenance():
    db, _ = _session()
    svc = _svc()
    with pytest.raises(MemoryValidationError):
        svc.create_lesson(
            db, _lesson_payload(github_provenance={}, source_run_id=None)
        )


def test_engineering_memory_cannot_be_relabeled_as_scientific():
    db, _ = _session()
    svc = _svc()
    with pytest.raises(MemoryValidationError):
        svc.capture_run(db, _run_payload(evidence_class="scientific_evidence"))


def test_returned_lesson_marked_non_scientific_with_provenance():
    db, _ = _session()
    svc = _svc()
    run = svc.capture_run(db, _run_payload())
    lesson = svc.create_lesson(db, _lesson_payload(source_run_id=run.run_id))
    public = lesson_to_public_dict(lesson)
    assert public["evidence_class"] == EVIDENCE_CLASS_NON_SCIENTIFIC
    assert public["is_scientific_evidence"] is False
    # Every returned lesson carries source provenance.
    assert public["provenance"]["source_run_id"] == run.run_id
    assert public["provenance"]["github"] == {"issue": "#1184"}


# ---------------------------------------------------------------------------
# Scope isolation
# ---------------------------------------------------------------------------


def test_scope_isolation_prevents_cross_repository_retrieval():
    db, _ = _session()
    svc = _svc()
    svc.create_lesson(
        db,
        _lesson_payload(
            workspace_scope="tenant/a",
            problem="alpha special token missing",
            solution="add alpha token",
        ),
    )
    result = svc.retrieve(
        db, {"workspace_scope": "tenant/b", "repository": REPO, "query": "alpha special token"}
    )
    assert result.scored == []


def test_source_run_from_other_scope_is_rejected():
    db, _ = _session()
    svc = _svc()
    run = svc.capture_run(db, _run_payload(workspace_scope="tenant/a"))
    with pytest.raises(ScopeViolationError):
        svc.create_lesson(
            db, _lesson_payload(workspace_scope="tenant/b", source_run_id=run.run_id)
        )


# ---------------------------------------------------------------------------
# Retrieval semantics
# ---------------------------------------------------------------------------


def test_invalidated_and_expired_lessons_are_not_returned():
    db, _ = _session()
    svc = _svc()
    good = svc.create_lesson(
        db, _lesson_payload(problem="cache stampede on boot", solution="add jitter")
    )
    bad = svc.create_lesson(
        db, _lesson_payload(problem="cache stampede regression", solution="old fix")
    )
    expired = svc.create_lesson(
        db,
        _lesson_payload(
            problem="cache stampede historical",
            solution="expired fix",
            expires_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        ),
    )
    svc.invalidate_lesson(db, bad.lesson_id, SCOPE, "superseded")

    result = svc.retrieve(
        db, {"workspace_scope": SCOPE, "repository": REPO, "query": "cache stampede"}
    )
    ids = {s.lesson.lesson_id for s in result.scored}
    assert good.lesson_id in ids
    assert bad.lesson_id not in ids
    assert expired.lesson_id not in ids


def test_verified_lesson_outranks_comparable_candidate():
    db, _ = _session()
    svc = _svc()
    # Candidate has *stronger* raw lexical overlap; verification must still win.
    candidate = svc.create_lesson(
        db,
        _lesson_payload(
            problem="flaky flaky flaky retry retry timeout timeout timeout",
            solution="increase timeout and retry",
        ),
    )
    verified = svc.create_lesson(
        db, _lesson_payload(problem="flaky retry timeout", solution="increase timeout")
    )
    svc.verify_lesson(db, verified.lesson_id, SCOPE, {"ci": "green"})

    result = svc.retrieve(
        db,
        {"workspace_scope": SCOPE, "repository": REPO, "query": "flaky retry timeout"},
    )
    assert result.scored[0].lesson.lesson_id == verified.lesson_id
    assert result.scored[0].rank == 1
    # sanity: both were retrieved
    assert candidate.lesson_id in {s.lesson.lesson_id for s in result.scored}


def test_retrieval_capped_at_five():
    db, _ = _session()
    svc = _svc()
    for i in range(9):
        svc.create_lesson(
            db,
            _lesson_payload(
                problem=f"database connection pool exhausted variant {i}",
                solution="raise pool size",
            ),
        )
    result = svc.retrieve(
        db,
        {
            "workspace_scope": SCOPE,
            "repository": REPO,
            "query": "database connection pool exhausted",
            "limit": 5,
        },
    )
    assert len(result.scored) <= 5


def test_retrieval_respects_character_budget():
    db, _ = _session()
    svc = _svc()
    long_solution = "x " * 400  # ~800 chars
    for i in range(5):
        svc.create_lesson(
            db,
            _lesson_payload(
                problem=f"memory leak in worker loop {i}",
                solution=long_solution,
            ),
        )
    result = svc.retrieve(
        db,
        {
            "workspace_scope": SCOPE,
            "repository": REPO,
            "query": "memory leak worker loop",
            "char_budget": 1000,
        },
    )
    assert result.injected_chars <= 1000
    # At least one lesson still comes back even though each exceeds a small slice.
    assert len(result.scored) >= 1


# ---------------------------------------------------------------------------
# Fingerprint invalidation
# ---------------------------------------------------------------------------


def test_fingerprint_divergence_invalidates_deterministically():
    db, _ = _session()
    svc = _svc()
    lesson = svc.create_lesson(
        db,
        _lesson_payload(
            problem="build breaks on numpy upgrade",
            solution="pin numpy",
            dependencies={"numpy": "1.26.0"},
        ),
    )
    # Same versions -> no invalidation.
    same = svc.invalidate_by_fingerprints(
        db, SCOPE, current_dependency=dependency_fingerprint({"numpy": "1.26.0"})
    )
    assert same == []
    # Changed versions -> deterministic invalidation.
    changed = svc.invalidate_by_fingerprints(
        db, SCOPE, current_dependency=dependency_fingerprint({"numpy": "2.0.0"})
    )
    assert [le.lesson_id for le in changed] == [lesson.lesson_id]
    refreshed = db.get(EngineeringMemoryLesson, lesson.lesson_id)
    assert refreshed.status == "invalidated"
    assert "dependency_fingerprint_changed" in refreshed.invalidated_reason


# ---------------------------------------------------------------------------
# Metrics: measured zero vs unavailable
# ---------------------------------------------------------------------------


def test_metrics_distinguish_measured_zero_from_unavailable():
    db, _ = _session()
    svc = _svc()
    # No token data supplied -> unavailable (None), not 0.
    svc.capture_run(db, _run_payload())
    m = svc.metrics(db, SCOPE)
    assert m["runs"]["tokens_input"] is None

    # A measured zero must read as 0, not None.
    svc.capture_run(db, _run_payload(tokens_input=0))
    m2 = svc.metrics(db, SCOPE)
    assert m2["runs"]["tokens_input"] == 0
    assert m2["evidence_class"] == EVIDENCE_CLASS_NON_SCIENTIFIC


# ---------------------------------------------------------------------------
# Deterministic end-to-end proof
# ---------------------------------------------------------------------------


def test_end_to_end_vertical_slice():
    """capture -> verified lesson -> retrieve (differently phrased) -> feedback -> metrics."""

    db, _ = _session()
    svc = _svc()

    # 1. Capture a sanitized successful run (with a secret that must be scrubbed).
    run = svc.capture_run(
        db,
        _run_payload(
            executor="codex",
            outcome="success",
            sanitized_summary=(
                "CI failed: pytest could not import fastapi. Installed fastapi<0.116 "
                "into the venv. Do not commit API_KEY=sk_live_0123456789abcdef."
            ),
            tokens_input=1200,
            tokens_output=300,
            turns=4,
        ),
    )
    assert "sk_live_0123456789abcdef" not in run.sanitized_summary

    # 2. Derive and verify a lesson.
    lesson = svc.create_lesson(
        db,
        _lesson_payload(
            module="ci",
            problem="pytest cannot import fastapi in CI",
            cause="app dependencies are not installed in the test environment",
            solution="install fastapi<0.116 into the venv before running pytest",
            applicability="CI pipeline test setup",
            source_run_id=run.run_id,
            tags=["ci", "pytest", "dependencies"],
        ),
    )
    svc.verify_lesson(db, lesson.lesson_id, SCOPE, {"ci_run": "green", "commit": "abc123"})

    # 3. Retrieve from a semantically related, differently-phrased task.
    result = svc.retrieve(
        db,
        {
            "workspace_scope": SCOPE,
            "repository": REPO,
            "query": "test suite fails because fastapi module is missing when running pytest",
            "injected": True,
        },
    )
    assert result.scored, "expected the verified lesson to be retrieved"
    top = result.scored[0]
    assert top.lesson.lesson_id == lesson.lesson_id
    assert top.lesson.status == "verified"
    public = lesson_to_public_dict(top.lesson)
    assert public["provenance"]["source_run_id"] == run.run_id
    assert public["is_scientific_evidence"] is False

    # 4. Record feedback with measured savings.
    svc.record_feedback(
        db,
        result.retrieval.retrieval_id,
        SCOPE,
        {"feedback": "helpful", "injected": True, "estimated_tokens_saved": 900},
    )

    # 5. Verify metrics.
    m = svc.metrics(db, SCOPE)
    assert m["runs"]["total"] == 1
    assert m["runs"]["tokens_input"] == 1200
    assert m["lessons"]["verified"] == 1
    assert m["retrievals"]["total"] == 1
    assert m["retrievals"]["injected"] == 1
    assert m["retrievals"]["feedback"]["helpful"] == 1
    assert m["retrievals"]["estimated_tokens_saved"] == 900


# ---------------------------------------------------------------------------
# Migration convention (upgrade + rollback)
# ---------------------------------------------------------------------------


def test_migration_files_present_and_rollback_defined():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "migrations"
    up = (root / "082_engineering_memory.sql").read_text()
    down = (root / "082_engineering_memory_downgrade.sql").read_text()

    for table in (
        "engineering_memory_runs",
        "engineering_memory_lessons",
        "engineering_memory_retrievals",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in up
        assert f"DROP TABLE IF EXISTS {table}" in down
    # Fail-closed evidence-class guard is enforced at the DB layer too.
    assert "evidence_class = 'non_scientific_evidence'" in up


def test_orm_metadata_round_trips():
    # ORM DDL must create and drop cleanly (downgrade behavior for the dev/test
    # SQLite path, mirroring the Postgres rollback migration).
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=list(TABLES))
    Base.metadata.drop_all(engine, tables=list(TABLES))


def test_redaction_is_idempotent():
    sample = "token GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwx1234 at 4.5709, -74.2973"
    once = redact_text(sample)
    twice = redact_text(once.text)
    assert once.text == twice.text
    assert twice.secret_count == 0


# ---------------------------------------------------------------------------
# Cost-control evaluation
# ---------------------------------------------------------------------------


def test_evaluation_shows_relevance_gain_and_unavailable_costs():
    from app.engineering_memory.evaluation import run_evaluation

    # No telemetry supplied -> token/turn savings must be "unavailable".
    report = run_evaluation()
    baseline = report["conditions"]["baseline"]
    enabled = report["conditions"]["enabled"]
    assert baseline["relevance_hit_rate"] == 0.0
    assert enabled["relevance_hit_rate"] == 1.0  # every task retrieves its lesson
    assert enabled["mean_reciprocal_rank"] == 1.0
    savings = report["token_and_turn_savings"]
    assert savings["source"] == "unavailable"
    assert savings["input_tokens_saved"] == "unavailable"
    assert savings["turns_saved"] == "unavailable"


def test_evaluation_reports_measured_savings_when_supplied():
    from app.engineering_memory.evaluation import run_evaluation

    telemetry = {
        "baseline": {"input_tokens": 5000, "output_tokens": 1200, "turns": 8},
        "enabled": {"input_tokens": 3200, "output_tokens": 1100, "turns": 5},
    }
    report = run_evaluation(telemetry=telemetry)
    savings = report["token_and_turn_savings"]
    assert savings["source"] == "measured"
    assert savings["input_tokens_saved"] == 1800
    assert savings["turns_saved"] == 3

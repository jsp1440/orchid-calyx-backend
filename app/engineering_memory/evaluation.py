"""Reproducible cost-control evaluation for engineering memory.

Compares a fixed task set under two conditions:

* **baseline** — memory disabled (no retrieval, no injected context);
* **enabled** — memory enabled (scope-isolated lexical retrieval).

What this harness measures *deterministically*, with no external LLM:

* retrieval relevance — hit rate and mean reciprocal rank of the expected
  lesson for each differently-phrased task;
* elapsed retrieval time;
* successful completion of the retrieval step.

Token and turn savings are **not** synthesized.  They are computed only from a
supplied ``telemetry`` fixture of measured paired runs; absent that fixture the
report marks them ``"unavailable"`` rather than inventing numbers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base

from .models import TABLES
from .service import EngineeringMemoryService

UNAVAILABLE = "unavailable"


@dataclass
class EvalTask:
    task_id: str
    query: str
    expected_lesson_key: str


@dataclass
class SeedLesson:
    key: str
    problem: str
    solution: str
    tags: list[str] = field(default_factory=list)


# Fixed, deterministic evaluation fixture.  Queries are phrased differently from
# the lessons they should retrieve, to exercise lexical expansion.
SEED_LESSONS: tuple[SeedLesson, ...] = (
    SeedLesson(
        key="fastapi_ci",
        problem="pytest cannot import fastapi in continuous integration",
        solution="install fastapi into the test virtualenv before running pytest",
        tags=["ci", "pytest", "dependencies"],
    ),
    SeedLesson(
        key="pool_exhausted",
        problem="database connection pool exhausted under load",
        solution="raise the sqlalchemy pool size and add pool_pre_ping",
        tags=["database", "sqlalchemy"],
    ),
    SeedLesson(
        key="migration_order",
        problem="foreign key violation when dropping engineering memory tables",
        solution="drop child tables before parent tables in the rollback migration",
        tags=["migration", "postgres"],
    ),
    SeedLesson(
        key="jsonb_sqlite",
        problem="jsonb column type is not supported on the sqlite test fallback",
        solution="use JSON().with_variant(JSONB, 'postgresql') for cross-dialect columns",
        tags=["sqlalchemy", "sqlite", "jsonb"],
    ),
)

EVAL_TASKS: tuple[EvalTask, ...] = (
    EvalTask("t1", "the test suite fails because the fastapi module is missing", "fastapi_ci"),
    EvalTask("t2", "too many database connections, pool ran out during heavy traffic", "pool_exhausted"),
    EvalTask("t3", "rollback fails with a foreign key error deleting memory tables", "migration_order"),
    EvalTask("t4", "sqlite does not understand the jsonb type during tests", "jsonb_sqlite"),
)

SCOPE = "eval/engineering-memory"
REPO = "eval/engineering-memory"


def _memory_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def run_evaluation(
    tasks: tuple[EvalTask, ...] = EVAL_TASKS,
    seeds: tuple[SeedLesson, ...] = SEED_LESSONS,
    telemetry: dict | None = None,
) -> dict:
    """Run the baseline-vs-enabled evaluation and return a structured report."""

    engine = _memory_engine()
    Base.metadata.create_all(engine, tables=list(TABLES))
    db = sessionmaker(bind=engine)()
    svc = EngineeringMemoryService()

    # Seed verified lessons, one per key.
    key_to_id: dict[str, str] = {}
    for seed in seeds:
        lesson = svc.create_lesson(
            db,
            {
                "workspace_scope": SCOPE,
                "repository": REPO,
                "problem": seed.problem,
                "solution": seed.solution,
                "tags": seed.tags,
                "github_provenance": {"fixture": seed.key},
                "data_classification": "internal_engineering",
            },
        )
        svc.verify_lesson(db, lesson.lesson_id, SCOPE, {"fixture": "seeded"})
        key_to_id[seed.key] = lesson.lesson_id

    # --- baseline: memory disabled ------------------------------------
    baseline_hits = 0  # by construction: no retrieval, no relevant context.

    # --- enabled: memory retrieval ------------------------------------
    reciprocal_ranks: list[float] = []
    enabled_hits = 0
    start = time.perf_counter()
    per_task: list[dict] = []
    for task in tasks:
        result = svc.retrieve(
            db,
            {"workspace_scope": SCOPE, "repository": REPO, "query": task.query},
        )
        expected_id = key_to_id[task.expected_lesson_key]
        rank = None
        for scored in result.scored:
            if scored.lesson.lesson_id == expected_id:
                rank = scored.rank
                break
        hit = rank is not None
        enabled_hits += 1 if hit else 0
        reciprocal_ranks.append(1.0 / rank if rank else 0.0)
        per_task.append(
            {
                "task_id": task.task_id,
                "expected": task.expected_lesson_key,
                "hit": hit,
                "rank": rank,
                "returned": len(result.scored),
            }
        )
    enabled_elapsed_ms = round((time.perf_counter() - start) * 1000, 3)

    n = len(tasks)
    report = {
        "task_count": n,
        "conditions": {
            "baseline": {
                "memory_enabled": False,
                "relevance_hit_rate": round(baseline_hits / n, 4) if n else None,
                "mean_reciprocal_rank": 0.0,
                "successful_completion": True,
                "elapsed_ms": UNAVAILABLE,  # no retrieval step performed
            },
            "enabled": {
                "memory_enabled": True,
                "relevance_hit_rate": round(enabled_hits / n, 4) if n else None,
                "mean_reciprocal_rank": round(sum(reciprocal_ranks) / n, 4) if n else None,
                "successful_completion": True,
                "elapsed_ms": enabled_elapsed_ms,
            },
        },
        "per_task": per_task,
        "token_and_turn_savings": _savings(telemetry),
    }
    db.close()
    return report


def _savings(telemetry: dict | None) -> dict:
    """Compute token/turn deltas from measured telemetry only.

    ``telemetry`` shape (all optional):
        {"baseline": {"input_tokens": int, "output_tokens": int, "turns": int},
         "enabled":  {"input_tokens": int, "output_tokens": int, "turns": int}}

    Any metric missing on either side is reported as ``"unavailable"``.
    """

    def delta(metric: str):
        if not telemetry:
            return UNAVAILABLE
        base = (telemetry.get("baseline") or {}).get(metric)
        enab = (telemetry.get("enabled") or {}).get(metric)
        if base is None or enab is None:
            return UNAVAILABLE
        return base - enab

    return {
        "source": "measured" if telemetry else UNAVAILABLE,
        "input_tokens_saved": delta("input_tokens"),
        "output_tokens_saved": delta("output_tokens"),
        "turns_saved": delta("turns"),
        "note": (
            "Token/turn savings require measured paired runs. Without a telemetry "
            "fixture they are reported as unavailable, never fabricated."
        ),
    }


def format_report(report: dict) -> str:
    lines = []
    lines.append("Continuum Engineering Memory — cost-control evaluation")
    lines.append("=" * 56)
    lines.append(f"tasks: {report['task_count']}")
    for name, cond in report["conditions"].items():
        lines.append(
            f"  {name:8s} hit_rate={cond['relevance_hit_rate']} "
            f"mrr={cond['mean_reciprocal_rank']} "
            f"elapsed_ms={cond['elapsed_ms']} "
            f"completed={cond['successful_completion']}"
        )
    sv = report["token_and_turn_savings"]
    lines.append(
        f"  savings  source={sv['source']} input_tokens_saved={sv['input_tokens_saved']} "
        f"output_tokens_saved={sv['output_tokens_saved']} turns_saved={sv['turns_saved']}"
    )
    return "\n".join(lines)

from __future__ import annotations

from threading import Lock

from sqlalchemy import text
from sqlalchemy.orm import Session

from .models import CalyxFinding, CalyxJob
from .program_models import CalyxProgram, CalyxProgramDependency, CalyxProgramJob

_SCHEMA_LOCK = Lock()
_SCHEMA_READY_ENGINES: set[int] = set()


def ensure_orchestrator_schema(db: Session) -> None:
    """Idempotently create the durable Calyx orchestrator tables used by status/jobs.

    Production historically shipped the SQL migration files without guaranteeing that
    every Render database had applied the original orchestrator migration.  This narrow
    bootstrap intentionally creates only the orchestrator/program tables owned by this
    subsystem; it does not call global ``Base.metadata.create_all``.
    """

    bind = db.get_bind()
    engine_key = id(bind)
    if engine_key in _SCHEMA_READY_ENGINES:
        return

    with _SCHEMA_LOCK:
        if engine_key in _SCHEMA_READY_ENGINES:
            return

        # Foreign-key order matters for databases that do not defer DDL resolution.
        for table in (
            CalyxJob.__table__,
            CalyxFinding.__table__,
            CalyxProgram.__table__,
            CalyxProgramJob.__table__,
            CalyxProgramDependency.__table__,
        ):
            table.create(bind=bind, checkfirst=True)

        # Older installations may have the original jobs table but not the autonomy
        # columns introduced later.  PostgreSQL supports safe idempotent repair here.
        if bind.dialect.name == "postgresql":
            with bind.begin() as conn:
                conn.execute(
                    text(
                        """
                        ALTER TABLE calyx_orchestrator_jobs
                            ADD COLUMN IF NOT EXISTS policy_class VARCHAR(40) NOT NULL DEFAULT 'read_only_research',
                            ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ NULL,
                            ADD COLUMN IF NOT EXISTS deadline_at TIMESTAMPTZ NULL
                        """
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_calyx_jobs_policy_status "
                        "ON calyx_orchestrator_jobs(policy_class, status, priority, created_at)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_calyx_jobs_retry_ready "
                        "ON calyx_orchestrator_jobs(status, next_attempt_at, priority) "
                        "WHERE status = 'queued'"
                    )
                )

        _SCHEMA_READY_ENGINES.add(engine_key)

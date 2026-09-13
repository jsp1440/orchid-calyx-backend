"""Add calyx_reservoir_runs and calyx_reservoir_tasks tables.

Additive-only migration: creates the DurableOrchestrate backing tables if
they do not already exist. Safe to run against a production database that
already has other tables. Uses CREATE TABLE IF NOT EXISTS so it is
idempotent if applied more than once.

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-09-13

"""

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers
revision = "a1b2c3d4e5f6"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing = set(inspector.get_table_names())

    # ------------------------------------------------------------------
    # calyx_reservoir_runs — one row per autonomous research run
    # ------------------------------------------------------------------
    if "calyx_reservoir_runs" not in existing:
        op.create_table(
            "calyx_reservoir_runs",
            sa.Column("run_id", sa.String(256), primary_key=True, nullable=False),
            sa.Column("blueprint_id", sa.String(512), nullable=False, server_default=""),
            sa.Column("run_fingerprint", sa.String(128), nullable=True),
            sa.Column("proposed_action", sa.Text, nullable=False, server_default=""),
            sa.Column("configured_width", sa.Integer, nullable=False, server_default="5"),
            sa.Column(
                "run_status",
                sa.String(40),
                nullable=False,
                server_default="in_progress",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        op.create_index(
            "ix_calyx_reservoir_runs_blueprint_id",
            "calyx_reservoir_runs",
            ["blueprint_id"],
        )
        op.create_index(
            "ix_calyx_reservoir_runs_run_fingerprint",
            "calyx_reservoir_runs",
            ["run_fingerprint"],
        )
        op.create_index(
            "ix_calyx_reservoir_runs_run_status",
            "calyx_reservoir_runs",
            ["run_status"],
        )

    # ------------------------------------------------------------------
    # calyx_reservoir_tasks — one row per TaskLeaf per run
    # ------------------------------------------------------------------
    if "calyx_reservoir_tasks" not in existing:
        op.create_table(
            "calyx_reservoir_tasks",
            # Primary key
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            # Run link
            sa.Column(
                "run_id",
                sa.String(256),
                sa.ForeignKey(
                    "calyx_reservoir_runs.run_id",
                    ondelete="CASCADE",
                    name="fk_calyx_reservoir_tasks_run_id",
                ),
                nullable=False,
            ),
            # Task identity
            sa.Column("task_key", sa.String(512), nullable=False),
            sa.Column("title", sa.String(512), nullable=False, server_default=""),
            sa.Column("repo", sa.String(256), nullable=False, server_default=""),
            sa.Column("module", sa.String(256), nullable=False, server_default=""),
            # Priority / authority / risk
            sa.Column("priority", sa.Integer, nullable=False, server_default="2"),
            sa.Column(
                "authority_class",
                sa.String(80),
                nullable=False,
                server_default="bounded_workspace_mutation",
            ),
            sa.Column(
                "consequence_risk", sa.String(20), nullable=False, server_default="low"
            ),
            # JSON fields (cross-dialect; Postgres uses native JSONB via SQLAlchemy JSON)
            sa.Column(
                "providers",
                sa.JSON,
                nullable=False,
                server_default="[]",
            ),
            sa.Column(
                "estimated_size", sa.String(4), nullable=False, server_default="m"
            ),
            sa.Column(
                "dependencies",
                sa.JSON,
                nullable=False,
                server_default="[]",
            ),
            sa.Column(
                "acceptance_criteria",
                sa.JSON,
                nullable=False,
                server_default="[]",
            ),
            sa.Column(
                "resources",
                sa.JSON,
                nullable=False,
                server_default="[]",
            ),
            # Optional issue/PR links
            sa.Column("issue_number", sa.Integer, nullable=True),
            sa.Column("pr_number", sa.Integer, nullable=True),
            # Mutable task state
            sa.Column(
                "state", sa.String(40), nullable=False, server_default="ready"
            ),
            # Lease fields
            sa.Column("leased_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("lease_holder", sa.String(256), nullable=True),
            # Blocked / backoff
            sa.Column("blocked_reason", sa.Text, nullable=True),
            # Completion evidence (JSON dict)
            sa.Column(
                "evidence",
                sa.JSON,
                nullable=False,
                server_default="{}",
            ),
            # Timestamps
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            # Idempotency constraint
            sa.UniqueConstraint(
                "run_id",
                "task_key",
                name="uq_calyx_reservoir_task_run_key",
            ),
        )
        op.create_index(
            "ix_calyx_reservoir_tasks_run_id",
            "calyx_reservoir_tasks",
            ["run_id"],
        )
        op.create_index(
            "ix_calyx_reservoir_tasks_task_key",
            "calyx_reservoir_tasks",
            ["task_key"],
        )
        op.create_index(
            "ix_calyx_reservoir_tasks_state",
            "calyx_reservoir_tasks",
            ["state"],
        )
        op.create_index(
            "ix_calyx_reservoir_tasks_priority",
            "calyx_reservoir_tasks",
            ["priority"],
        )


def downgrade() -> None:
    """Drop the durable reservoir tables (additive removal — existing tables untouched)."""
    bind = op.get_bind()
    inspector = inspect(bind)
    existing = set(inspector.get_table_names())

    if "calyx_reservoir_tasks" in existing:
        op.drop_index("ix_calyx_reservoir_tasks_priority", table_name="calyx_reservoir_tasks")
        op.drop_index("ix_calyx_reservoir_tasks_state", table_name="calyx_reservoir_tasks")
        op.drop_index("ix_calyx_reservoir_tasks_task_key", table_name="calyx_reservoir_tasks")
        op.drop_index("ix_calyx_reservoir_tasks_run_id", table_name="calyx_reservoir_tasks")
        op.drop_table("calyx_reservoir_tasks")

    if "calyx_reservoir_runs" in existing:
        op.drop_index("ix_calyx_reservoir_runs_run_status", table_name="calyx_reservoir_runs")
        op.drop_index("ix_calyx_reservoir_runs_run_fingerprint", table_name="calyx_reservoir_runs")
        op.drop_index("ix_calyx_reservoir_runs_blueprint_id", table_name="calyx_reservoir_runs")
        op.drop_table("calyx_reservoir_runs")

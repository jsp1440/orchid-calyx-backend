import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

import app.calyx_orchestrator.durable_reservoir_models  # noqa: E402
import app.calyx_orchestrator.git_proposal_ci_repair  # noqa: E402
import app.calyx_orchestrator.git_proposal_mutation_journal  # noqa: E402
import app.calyx_orchestrator.github_agent_dispatch_store  # noqa: E402

# Import all modules that extend Base so autogenerate sees every table.
import app.calyx_orchestrator.models  # noqa: E402
import app.calyx_orchestrator.program_models  # noqa: E402
import app.calyx_orchestrator.proposal_authorization_models  # noqa: E402
import app.calyx_orchestrator.sandbox_supervisor_models  # noqa: E402
import app.calyx_orchestrator.specialist_models  # noqa: E402
import app.conversation_memory.models  # noqa: E402
import app.research_workspace.models  # noqa: E402, F401
from app.models import Base  # noqa: E402

target_metadata = Base.metadata

def get_url():
    return os.getenv("DATABASE_URL", "sqlite:///./calyx.db")


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

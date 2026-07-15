"""Additive helper that wires the *unchanged* orchestrator/publisher to the
writable PostgreSQL repository with run-level transactional safety.

This module does not modify any existing component.  It is NOT executed by
BUILD-067 (which ends at validation) and never runs on import.  A future,
separately-authorized production publish calls :func:`publish_to_production`.

Transaction guarantee: the entire run commits once only if every domain
completed and cross-domain validation is healthy; otherwise the whole run is
rolled back.  No partial batches are ever committed.
"""

from __future__ import annotations

from typing import Any

from .checkpoint import STATUS_FAILED
from .orchestrator import DOMAIN_ADAPTERS, BuildOrchestrator, ExecutionMode
from .repository import WritablePostgresGraphRepository
from .sources import PostgresSourceProvider


def publish_to_production(
    dsn: str,
    *,
    adapters=DOMAIN_ADAPTERS,
    activated_domains: frozenset[str] | None = None,
    batch_size: int = 500,
    checkpoint_store: Any | None = None,
    build_run_id: int | None = None,
    commit_every: int | None = None,
    resume: bool = False,
    schema: str = "oc_graph",
) -> dict[str, Any]:
    """Run an authorized production publish with all-or-nothing commit semantics.

    Rolls back and reports ``committed=False`` when any domain fails or the
    graph is unhealthy; commits once when the whole run succeeds.
    """
    repo = WritablePostgresGraphRepository(
        dsn, schema=schema, build_run_id=build_run_id, commit_every=commit_every,
    )
    source = PostgresSourceProvider.from_registry(dsn)
    orch = BuildOrchestrator(
        repo, source, checkpoint_store=checkpoint_store, adapters=tuple(adapters),
        batch_size=batch_size, authorized_to_publish=True,
        activated_domains=activated_domains,
    )
    mode = ExecutionMode.RESUME if resume else ExecutionMode.PUBLISH
    try:
        repo.acquire_publication_lock()
        report = orch.run(mode)
        any_failed = any(
            d.get("status") == STATUS_FAILED for d in report.get("per_domain", [])
        )
        healthy = (report.get("cross_domain_validation") or {}).get("healthy", False)
        if any_failed or not healthy:
            repo.rollback()
            report["committed"] = False
            report["rollback_reason"] = (
                "domain failure" if any_failed else "unhealthy cross-domain validation"
            )
        else:
            repo.commit()
            report["committed"] = True
        return report
    except Exception:
        repo.rollback()
        raise
    finally:
        repo.close()

"""Bounded executor for resumable Knowledge Graph dry runs.

Each call processes at most ``max_batches_per_step`` batches for one unfinished
domain. The persistent SQLite staging graph and JSON session metadata allow a
later request to resume without touching production graph tables.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .publisher import DomainAdapter, publish_domain
from .repository import GraphRepository
from .resumable_dry_run import (
    DryRunSession,
    JsonSessionStore,
    RUN_CANCELLED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_PENDING,
    RUN_RUNNING,
)
from .sources import SourceProvider
from .sqlite_staging import SqliteStagingGraphRepository
from .validation import validate_graph


def staging_path(directory: str, run_id: str) -> str:
    safe = Path(run_id).name
    if safe != run_id:
        raise ValueError("Invalid run identifier")
    return str(Path(directory) / f"{safe}.sqlite3")


def _seed_taxonomy(source_repo: GraphRepository, staging: SqliteStagingGraphRepository) -> int:
    fetch = getattr(source_repo, "taxonomy_nodes", None)
    nodes: Iterable
    if callable(fetch):
        nodes = fetch()
    else:
        nodes = (n for n in source_repo.all_nodes() if n.node_type in {"taxon", "genus"})
    seeded = 0
    for node in nodes:
        staging.upsert_node(node)
        seeded += 1
    return seeded


def create_session(
    store: JsonSessionStore,
    *,
    domains: list[str],
    allowed_domains: set[str],
    batch_size: int,
    max_batches_per_step: int,
) -> DryRunSession:
    unknown = sorted(set(domains) - allowed_domains)
    if unknown:
        raise ValueError(f"Unsupported or unavailable domains: {', '.join(unknown)}")
    session = DryRunSession.create(domains, batch_size, max_batches_per_step)
    store.save(session)
    return session


def resume_session(
    store: JsonSessionStore,
    staging_directory: str,
    graph_repo: GraphRepository,
    source: SourceProvider,
    adapters: dict[str, DomainAdapter],
    run_id: str,
) -> dict:
    session = store.load(run_id)
    if session is None:
        raise KeyError(run_id)
    if session.status in {RUN_COMPLETED, RUN_FAILED, RUN_CANCELLED}:
        return session_report(session, staging_directory)

    staging = SqliteStagingGraphRepository(staging_path(staging_directory, run_id))
    if not session.taxonomy_seeded:
        _seed_taxonomy(graph_repo, staging)
        session.taxonomy_seeded = True
        store.save(session)

    state = next(
        (session.domain_states[d] for d in session.domains if session.domain_states[d].status != RUN_COMPLETED),
        None,
    )
    if state is None:
        session.refresh_status()
        store.save(session)
        return session_report(session, staging_directory)

    adapter = adapters.get(state.domain)
    if adapter is None:
        state.status = RUN_FAILED
        state.error = "No adapter is registered for this domain"
        session.refresh_status()
        store.save(session)
        return session_report(session, staging_directory)

    try:
        if state.available_rows is None:
            state.available_rows = source.count(state.domain)
        state.status = RUN_RUNNING
        session.status = RUN_RUNNING
        store.save(session)

        for _ in range(session.max_batches_per_step):
            current = store.load(run_id)
            if current is None or current.status == RUN_CANCELLED:
                return session_report(current or session, staging_directory)

            rows = source.fetch(state.domain, session.batch_size, state.offset)
            if not rows:
                if state.pass_number == 1:
                    state.pass_number = 2
                    state.offset = 0
                    store.save(session)
                    continue
                state.status = RUN_COMPLETED
                break

            result = publish_domain(staging, adapter, rows)
            if state.pass_number == 1:
                state.first_nodes += result.nodes_written
                state.first_edges += result.edges_written
                state.invalid += len(result.invalid)
            else:
                state.second_nodes += result.nodes_written
                state.second_edges += result.edges_written
            state.offset += len(rows)
            state.batches += 1
            store.save(session)

            if len(rows) < session.batch_size:
                if state.pass_number == 1:
                    state.pass_number = 2
                    state.offset = 0
                else:
                    state.status = RUN_COMPLETED
                store.save(session)
                if state.status == RUN_COMPLETED:
                    break

    except Exception as exc:
        state.status = RUN_FAILED
        state.error = str(exc)

    session.refresh_status()
    store.save(session)
    return session_report(session, staging_directory)


def session_report(session: DryRunSession, staging_directory: str) -> dict:
    staging = SqliteStagingGraphRepository(staging_path(staging_directory, session.run_id))
    validation = validate_graph(staging) if session.taxonomy_seeded else {"healthy": False, "reason": "taxonomy_not_seeded"}
    states = list(session.domain_states.values())
    complete = session.status == RUN_COMPLETED
    zero_delta = complete and all(state.zero_delta for state in states)
    blockers = []
    for state in states:
        if state.status != RUN_COMPLETED:
            blockers.append(f"domain_not_complete:{state.domain}:{state.status}")
        if state.error:
            blockers.append(f"domain_error:{state.domain}:{state.error}")
        if state.second_nodes or state.second_edges:
            blockers.append(
                f"second_pass_delta:{state.domain}:nodes={state.second_nodes}:edges={state.second_edges}"
            )
    if not validation.get("healthy", False):
        blockers.append("staging_graph_integrity_failed")

    return {
        "contract": "calyx-resumable-graph-dry-run-v1",
        "session": session.to_dict(),
        "staging_counts": staging.counts(),
        "validation": validation,
        "zero_delta": zero_delta,
        "publication_authorization_ready": complete and zero_delta and not blockers,
        "blockers": blockers,
        "production_graph_mutation": False,
    }

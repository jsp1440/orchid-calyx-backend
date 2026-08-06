"""Bounded executor for resumable Knowledge Graph dry runs."""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .publisher import DomainAdapter, canonical_key, publish_domain
from .repository import GraphRepository
from .resumable_dry_run import (
    RUN_CANCELLED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_PENDING,
    RUN_RUNNING,
    DryRunSession,
    JsonSessionStore,
)
from .sources import SourceProvider
from .sqlite_staging import SqliteStagingGraphRepository
from .validation import validate_graph

LOCK_STALE_SECONDS = 15 * 60


def staging_path(directory: str, run_id: str) -> str:
    safe = Path(run_id).name
    if safe != run_id:
        raise ValueError("Invalid run identifier")
    return str(Path(directory) / f"{safe}.sqlite3")


def lock_path(directory: str, run_id: str) -> Path:
    safe = Path(run_id).name
    if safe != run_id:
        raise ValueError("Invalid run identifier")
    return Path(directory) / f"{safe}.resume.lock"


@contextmanager
def session_resume_lock(directory: str, run_id: str):
    target = lock_path(directory, run_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    if target.exists() and now - target.stat().st_mtime > LOCK_STALE_SECONDS:
        target.unlink(missing_ok=True)
    try:
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError("resume_already_in_progress") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"run_id": run_id, "pid": os.getpid(), "created_at": now}, handle)
        yield
    finally:
        target.unlink(missing_ok=True)


def _seed_referenced_taxonomy(source_repo: GraphRepository, staging: SqliteStagingGraphRepository, rows: list[dict[str, Any]]) -> int:
    taxon_keys = {
        canonical_key("taxon", row.get("taxon_pk"))
        for row in rows
        if row.get("taxon_pk") is not None
    }
    seeded = 0
    for key in sorted(taxon_keys):
        if staging.get_node_by_key(key) is not None:
            continue
        node = source_repo.get_node_by_key(key)
        if node is not None:
            staging.upsert_node(node)
            seeded += 1
    return seeded


def create_session(store: JsonSessionStore, *, domains: list[str], allowed_domains: set[str], batch_size: int, max_batches_per_step: int) -> DryRunSession:
    unknown = sorted(set(domains) - allowed_domains)
    if unknown:
        raise ValueError(f"Unsupported or unavailable domains: {', '.join(unknown)}")
    session = DryRunSession.create(domains, batch_size, max_batches_per_step)
    store.save(session)
    return session


def resume_session(store: JsonSessionStore, staging_directory: str, graph_repo: GraphRepository, source: SourceProvider, adapters: dict[str, DomainAdapter], run_id: str) -> dict:
    session = store.load(run_id)
    if session is None:
        raise KeyError(run_id)
    if session.status in {RUN_COMPLETED, RUN_FAILED, RUN_CANCELLED}:
        return session_report(session, staging_directory)
    try:
        with session_resume_lock(staging_directory, run_id):
            return _resume_locked(store, staging_directory, graph_repo, source, adapters, run_id)
    except RuntimeError as exc:
        if str(exc) != "resume_already_in_progress":
            raise
        report = session_report(session, staging_directory)
        report["resume_in_progress"] = True
        report["blockers"] = list(report["blockers"]) + ["resume_already_in_progress"]
        report["publication_authorization_ready"] = False
        return report


def _resume_locked(store: JsonSessionStore, staging_directory: str, graph_repo: GraphRepository, source: SourceProvider, adapters: dict[str, DomainAdapter], run_id: str) -> dict:
    session = store.load(run_id)
    if session is None:
        raise KeyError(run_id)
    staging = SqliteStagingGraphRepository(staging_path(staging_directory, run_id))
    state = next((session.domain_states[d] for d in session.domains if session.domain_states[d].status != RUN_COMPLETED), None)
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
            _seed_referenced_taxonomy(graph_repo, staging, rows)
            session.taxonomy_seeded = True
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
    except Exception as exc:  # noqa: BLE001 - session failures are captured in dry-run state
        state.status = RUN_FAILED
        state.error = str(exc)
    session.refresh_status()
    store.save(session)
    return session_report(session, staging_directory)


def _progress(session: DryRunSession) -> dict[str, Any]:
    states = list(session.domain_states.values())
    completed = sum(state.status == RUN_COMPLETED for state in states)
    active = next((state for state in states if state.status == RUN_RUNNING), None)
    return {
        "domains_total": len(states),
        "domains_completed": completed,
        "domain_completion_percent": round((completed / len(states)) * 100, 2) if states else 0.0,
        "active_domain": active.domain if active else None,
        "active_pass": active.pass_number if active else None,
        "active_offset": active.offset if active else None,
        "known_source_rows": sum(state.available_rows or 0 for state in states),
        "batches_completed": sum(state.batches for state in states),
        "next_action": "resume" if session.status in {RUN_PENDING, RUN_RUNNING} else "review",
    }


def session_report(session: DryRunSession, staging_directory: str) -> dict:
    path = Path(staging_path(staging_directory, session.run_id))
    if path.is_file():
        staging = SqliteStagingGraphRepository(str(path), initialize=False)
        counts = staging.counts()
        validation = validate_graph(staging) if session.taxonomy_seeded else {"healthy": False, "reason": "taxonomy_not_seeded"}
    else:
        counts = {"nodes": 0, "edges": 0}
        validation = {"healthy": False, "reason": "staging_not_started"}
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
            blockers.append(f"second_pass_delta:{state.domain}:nodes={state.second_nodes}:edges={state.second_edges}")
    if not validation.get("healthy", False):
        blockers.append("staging_graph_integrity_failed")
    return {
        "contract": "calyx-resumable-graph-dry-run-v2",
        "session": session.to_dict(),
        "progress": _progress(session),
        "staging_started": path.is_file(),
        "staging_counts": counts,
        "validation": validation,
        "zero_delta": zero_delta,
        "resume_in_progress": lock_path(staging_directory, session.run_id).exists(),
        "publication_authorization_ready": complete and zero_delta and not blockers,
        "blockers": blockers,
        "production_graph_mutation": False,
    }

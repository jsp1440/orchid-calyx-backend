"""Unified Knowledge Graph Build Orchestrator (BUILD-060).

A single orchestrator drives the whole scientific graph population pipeline,
reusing the existing repository, publisher, quality, vocabulary and validation
infrastructure.  It does not introduce a second graph framework or a second
repository/publisher abstraction.

Pipeline
--------
1. Preflight audit
2..9. Each domain (occurrences, traits, pollinators, mycorrhiza, conservation,
   climate, literature, images/phenotype) — in registry order
10. Cross-domain validation
11. Final build report

Execution modes
---------------
* ``AUDIT``    — inspect source availability only; no adapter run, no writes.
* ``DRY_RUN``  — run adapters into an in-memory staging graph, validate, report;
  never writes to the production graph.
* ``PUBLISH``  — publish into a writable repository in idempotent batches.
  Disabled unless ``authorized_to_publish=True`` AND ``mode=PUBLISH``.
* ``RESUME``   — re-run PUBLISH but skip domains already marked complete in the
  checkpoint store.

Safety
------
The orchestrator only writes when mode is PUBLISH and publication is explicitly
authorized.  AUDIT and DRY_RUN never mutate any graph.  Dry runs use a fresh
in-memory staging repository seeded read-only with the taxonomy nodes the
domain edges reference, so edge resolution is realistic without touching prod.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .adapters import DOMAIN_ADAPTERS
from .checkpoint import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_SKIPPED,
    Checkpoint,
    InMemoryCheckpointStore,
)
from .publisher import DomainAdapter, PublishResult, publish_domain
from .repository import GraphRepository, InMemoryGraphRepository
from .sources import SourceProvider
from .validation import validate_graph


class ExecutionMode(str, Enum):
    AUDIT = "audit"
    DRY_RUN = "dry_run"
    PUBLISH = "publish"
    RESUME = "resume"


DEFAULT_BATCH_SIZE = 500


@dataclass
class DomainOutcome:
    domain: str
    status: str
    rows_processed: int = 0
    nodes_written: int = 0
    edges_written: int = 0
    skipped_existing_nodes: int = 0
    skipped_existing_edges: int = 0
    invalid: int = 0
    batches: int = 0
    available_rows: int | None = None
    validation: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "status": self.status,
            "rows_processed": self.rows_processed,
            "available_rows": self.available_rows,
            "nodes_written": self.nodes_written,
            "edges_written": self.edges_written,
            "skipped_existing_nodes": self.skipped_existing_nodes,
            "skipped_existing_edges": self.skipped_existing_edges,
            "invalid": self.invalid,
            "batches": self.batches,
            "validation": self.validation,
            "warnings": self.warnings,
            "error": self.error,
        }


class BuildOrchestrator:
    def __init__(
        self,
        repo: GraphRepository,
        source: SourceProvider,
        checkpoint_store: Any | None = None,
        adapters: tuple[DomainAdapter, ...] = DOMAIN_ADAPTERS,
        batch_size: int = DEFAULT_BATCH_SIZE,
        authorized_to_publish: bool = False,
    ) -> None:
        self._repo = repo
        self._source = source
        self._checkpoints = checkpoint_store or InMemoryCheckpointStore()
        self._adapters = adapters
        self._batch_size = max(1, int(batch_size))
        self._authorized = bool(authorized_to_publish)

    # ---- public entrypoint ----
    def run(self, mode: ExecutionMode) -> dict[str, Any]:
        started = time.time()
        preflight = self._preflight(mode)

        if mode == ExecutionMode.AUDIT:
            report = self._finalize(mode, preflight, [], None, started)
            return report

        if mode in (ExecutionMode.PUBLISH, ExecutionMode.RESUME) and not self._authorized:
            preflight["publish_authorized"] = False
            preflight["warnings"].append(
                f"{mode.value.upper()} requested without authorization; no writes performed."
            )
            return self._finalize(mode, preflight, [], None, started)

        resume = mode == ExecutionMode.RESUME
        target = self._target_repo(mode)
        completed = self._checkpoints.completed_domains() if resume else set()

        outcomes: list[DomainOutcome] = []
        for adapter in self._adapters:
            if resume and adapter.domain in completed:
                outcomes.append(DomainOutcome(
                    domain=adapter.domain, status=STATUS_SKIPPED,
                    warnings=["skipped: already completed in checkpoint store"],
                ))
                continue
            outcomes.append(self._run_domain(adapter, target, mode))

        cross = validate_graph(target)
        return self._finalize(mode, preflight, outcomes, cross, started)

    # ---- pipeline stages ----
    def _preflight(self, mode: ExecutionMode) -> dict[str, Any]:
        availability: dict[str, int] = {}
        warnings: list[str] = []
        for adapter in self._adapters:
            try:
                availability[adapter.domain] = self._source.count(adapter.domain)
            except Exception as exc:  # noqa: BLE001 - surfaced as a warning, never fatal
                availability[adapter.domain] = -1
                warnings.append(f"{adapter.domain}: source count failed ({exc})")
        empty = [d for d, c in availability.items() if c == 0]
        if empty:
            warnings.append("no source rows available for: " + ", ".join(sorted(empty)))
        return {
            "mode": mode.value,
            "batch_size": self._batch_size,
            "publish_authorized": self._authorized,
            "domain_order": [a.domain for a in self._adapters],
            "source_availability": availability,
            "warnings": warnings,
        }

    def _target_repo(self, mode: ExecutionMode) -> GraphRepository:
        if mode in (ExecutionMode.PUBLISH, ExecutionMode.RESUME):
            return self._repo  # writable production repository
        # DRY_RUN: staging graph seeded read-only from the source repository.
        staging = InMemoryGraphRepository()
        self._seed_taxonomy(staging)
        return staging

    def _seed_taxonomy(self, staging: InMemoryGraphRepository) -> None:
        """Copy existing taxonomy nodes into staging so edges resolve.

        Read-only: only ``all_nodes`` is called on the source repository.
        Domain edges attach to ``taxon``/``genus`` nodes, which must already
        exist for the publisher to resolve endpoints.
        """
        for node in self._repo.all_nodes():
            if node.node_type in ("taxon", "genus"):
                staging.upsert_node(node)

    def _run_domain(
        self, adapter: DomainAdapter, target: GraphRepository, mode: ExecutionMode
    ) -> DomainOutcome:
        outcome = DomainOutcome(domain=adapter.domain, status=STATUS_COMPLETED)
        try:
            available = self._source.count(adapter.domain)
            outcome.available_rows = available
            offset = 0
            while True:
                rows = self._source.fetch(adapter.domain, self._batch_size, offset)
                if not rows:
                    break
                result = publish_domain(target, adapter, rows)
                self._accumulate(outcome, result, len(rows))
                offset += len(rows)
                if len(rows) < self._batch_size:
                    break
            outcome.validation = validate_graph(target)
        except Exception as exc:  # noqa: BLE001 - captured per domain for resume
            outcome.status = STATUS_FAILED
            outcome.error = str(exc)

        self._checkpoints.save(Checkpoint(
            domain=adapter.domain,
            status=outcome.status,
            rows_processed=outcome.rows_processed,
            stats={
                "nodes_written": outcome.nodes_written,
                "edges_written": outcome.edges_written,
                "skipped_existing_nodes": outcome.skipped_existing_nodes,
                "skipped_existing_edges": outcome.skipped_existing_edges,
                "invalid": outcome.invalid,
                "batches": outcome.batches,
            },
            validation={"total_problems": outcome.validation.get("total_problems")}
            if outcome.validation else {},
        ))
        return outcome

    @staticmethod
    def _accumulate(outcome: DomainOutcome, result: PublishResult, batch_rows: int) -> None:
        outcome.rows_processed += batch_rows
        outcome.nodes_written += result.nodes_written
        outcome.edges_written += result.edges_written
        outcome.skipped_existing_nodes += result.skipped_existing_nodes
        outcome.skipped_existing_edges += result.skipped_existing_edges
        outcome.invalid += len(result.invalid)
        outcome.batches += 1
        if result.invalid:
            outcome.warnings.append(
                f"{len(result.invalid)} invalid spec(s) in a batch (e.g. "
                + ", ".join(sorted(set(result.invalid))[:3]) + ")"
            )

    # ---- reporting ----
    def _finalize(
        self,
        mode: ExecutionMode,
        preflight: dict[str, Any],
        outcomes: list[DomainOutcome],
        cross: dict[str, Any] | None,
        started: float,
    ) -> dict[str, Any]:
        per_domain = [o.to_dict() for o in outcomes]
        totals = {
            "nodes_written": sum(o.nodes_written for o in outcomes),
            "edges_written": sum(o.edges_written for o in outcomes),
            "skipped_existing_nodes": sum(o.skipped_existing_nodes for o in outcomes),
            "skipped_existing_edges": sum(o.skipped_existing_edges for o in outcomes),
            "rows_processed": sum(o.rows_processed for o in outcomes),
            "invalid": sum(o.invalid for o in outcomes),
        }
        warnings = list(preflight.get("warnings", []))
        errors = [f"{o.domain}: {o.error}" for o in outcomes if o.error]
        for o in outcomes:
            warnings.extend(f"{o.domain}: {w}" for w in o.warnings)

        wrote = mode in (ExecutionMode.PUBLISH, ExecutionMode.RESUME) and self._authorized
        growth = {
            "estimated_new_nodes": totals["nodes_written"],
            "estimated_new_edges": totals["edges_written"],
            "basis": "actual" if wrote else "projected_from_" + mode.value,
        }

        return {
            "build": {
                "mode": mode.value,
                "wrote_to_production": wrote,
                "publish_authorized": self._authorized,
                "batch_size": self._batch_size,
                "duration_seconds": round(time.time() - started, 4),
            },
            "preflight": preflight,
            "per_domain": per_domain,
            "totals": totals,
            "cross_domain_validation": cross,
            "estimated_graph_growth": growth,
            "checkpoints": [c.to_dict() for c in self._checkpoints.all()],
            "warnings": warnings,
            "errors": errors,
            "healthy": (not errors) and (cross is None or cross.get("healthy", True)),
        }

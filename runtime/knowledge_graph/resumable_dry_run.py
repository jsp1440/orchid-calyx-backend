"""Resumable, domain-selectable Knowledge Graph dry-run coordination.

Checkpoint files contain validation metadata only. Production graph tables are
never written by this module.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

RUN_PENDING = "pending"
RUN_RUNNING = "running"
RUN_COMPLETED = "completed"
RUN_FAILED = "failed"
RUN_CANCELLED = "cancelled"


@dataclass
class DomainRunState:
    domain: str
    status: str = RUN_PENDING
    pass_number: int = 1
    available_rows: int | None = None
    offset: int = 0
    batches: int = 0
    first_nodes: int = 0
    first_edges: int = 0
    second_nodes: int = 0
    second_edges: int = 0
    invalid: int = 0
    error: str | None = None

    @property
    def zero_delta(self) -> bool:
        return self.status == RUN_COMPLETED and self.second_nodes == 0 and self.second_edges == 0


@dataclass
class DryRunSession:
    run_id: str
    domains: list[str]
    batch_size: int
    max_batches_per_step: int
    status: str = RUN_PENDING
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    taxonomy_seeded: bool = False
    domain_states: dict[str, DomainRunState] = field(default_factory=dict)
    production_graph_mutation: bool = False

    @classmethod
    def create(cls, domains: list[str], batch_size: int, max_batches_per_step: int) -> "DryRunSession":
        clean = list(dict.fromkeys(d.strip() for d in domains if d.strip()))
        if not clean:
            raise ValueError("At least one domain is required")
        return cls(
            run_id=str(uuid.uuid4()),
            domains=clean,
            batch_size=max(1, int(batch_size)),
            max_batches_per_step=max(1, int(max_batches_per_step)),
            domain_states={d: DomainRunState(domain=d) for d in clean},
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DryRunSession":
        states = {
            name: DomainRunState(**{k: v for k, v in value.items() if k != "zero_delta"})
            for name, value in payload.get("domain_states", {}).items()
        }
        return cls(
            run_id=payload["run_id"],
            domains=list(payload["domains"]),
            batch_size=int(payload["batch_size"]),
            max_batches_per_step=int(payload["max_batches_per_step"]),
            status=payload.get("status", RUN_PENDING),
            created_at=float(payload.get("created_at", time.time())),
            updated_at=float(payload.get("updated_at", time.time())),
            taxonomy_seeded=bool(payload.get("taxonomy_seeded", False)),
            domain_states=states,
            production_graph_mutation=bool(payload.get("production_graph_mutation", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["domain_states"] = {
            k: asdict(v) | {"zero_delta": v.zero_delta}
            for k, v in self.domain_states.items()
        }
        return payload

    def refresh_status(self) -> None:
        states = list(self.domain_states.values())
        if self.status == RUN_CANCELLED:
            return
        if any(state.status == RUN_FAILED for state in states):
            self.status = RUN_FAILED
        elif states and all(state.status == RUN_COMPLETED for state in states):
            self.status = RUN_COMPLETED
        elif any(state.status == RUN_RUNNING for state in states):
            self.status = RUN_RUNNING
        else:
            self.status = RUN_PENDING
        self.updated_at = time.time()


class JsonSessionStore:
    """Durable metadata store using one JSON file per validation session."""

    def __init__(self, directory: str):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def path_for(self, run_id: str) -> Path:
        safe = Path(run_id).name
        if safe != run_id:
            raise ValueError("Invalid run identifier")
        return self.directory / f"{safe}.json"

    def save(self, session: DryRunSession) -> None:
        session.updated_at = time.time()
        target = self.path_for(session.run_id)
        fd, temp_path = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(session.to_dict(), handle, indent=2, sort_keys=True)
            os.replace(temp_path, target)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def load(self, run_id: str) -> DryRunSession | None:
        target = self.path_for(run_id)
        if not target.exists():
            return None
        with target.open(encoding="utf-8") as handle:
            return DryRunSession.from_dict(json.load(handle))

    def cancel(self, run_id: str) -> DryRunSession | None:
        session = self.load(run_id)
        if session is None:
            return None
        session.status = RUN_CANCELLED
        for state in session.domain_states.values():
            if state.status not in {RUN_COMPLETED, RUN_FAILED}:
                state.status = RUN_CANCELLED
        self.save(session)
        return session

"""Resumable, domain-selectable Knowledge Graph dry-run coordination.

Checkpoint files contain validation metadata only. Production graph tables are
never written by this module.
"""
from __future__ import annotations

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

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["domain_states"] = {k: asdict(v) | {"zero_delta": v.zero_delta} for k, v in self.domain_states.items()}
        return payload


class JsonSessionStore:
    """Durable metadata store using one JSON file per validation session."""

    def __init__(self, directory: str):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def path_for(self, run_id: str) -> Path:
        return self.directory / f"{run_id}.json"

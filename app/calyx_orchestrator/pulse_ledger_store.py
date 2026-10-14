"""Database-backed Brain pulse ledger (P1 sustained autonomy).

Implements the interface ``calyx_brain.autonomy_pulse.run_pulse`` uses for
its ledger (``load``, ``save``, ``append_receipt``, ``receipts``,
``exclusive``) on the Calyx database. Nothing else changes: the pulse still
selects, submits and reconciles; the Calyx scheduler still claims, leases and
executes. What changes is durability. A restarted or replaced worker resumes
its submission records, per-source backoff and budgets instead of starting
from an empty container-local file and replaying everything.

Exclusivity: on PostgreSQL a session-level ``pg_try_advisory_lock`` keyed by
the ledger key, so two workers on different hosts cannot select the same work
concurrently. Elsewhere (SQLite in tests) a per-process lock.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .program_models import CalyxBrainPulseLedger, CalyxBrainPulseReceipt
from .schema import ensure_orchestrator_schema

_LOCAL_LOCKS: dict[str, threading.Lock] = {}
_LOCAL_LOCKS_GUARD = threading.Lock()


def _advisory_key(ledger_key: str) -> int:
    # Stable signed 64-bit key derived from the ledger key.
    digest = hashlib.sha256(f"calyx-brain-pulse:{ledger_key}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


class DatabasePulseLedger:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        key: str,
        ledger_schema: str,
    ) -> None:
        if not key or len(key) > 120:
            raise ValueError("PULSE_LEDGER_KEY_INVALID")
        self.session_factory = session_factory
        self.key = key
        self.ledger_schema = ledger_schema

    def _empty(self) -> dict[str, Any]:
        return {
            "schema": self.ledger_schema,
            "work": {},
            "backoff": {"consecutive_failures": 0, "until": None},
        }

    def load(self) -> dict[str, Any]:
        with self.session_factory() as db:
            ensure_orchestrator_schema(db)
            row = db.get(CalyxBrainPulseLedger, self.key)
            if row is None:
                return self._empty()
            state = json.loads(row.state_json)
        if state.get("schema") != self.ledger_schema:
            raise ValueError("LEDGER_SCHEMA_UNRECOGNIZED")
        return state

    def save(self, state: Mapping[str, Any]) -> None:
        document = json.dumps(state, sort_keys=True)
        with self.session_factory() as db:
            ensure_orchestrator_schema(db)
            row = db.get(CalyxBrainPulseLedger, self.key)
            if row is None:
                db.add(CalyxBrainPulseLedger(ledger_key=self.key, state_json=document))
            else:
                row.state_json = document
            db.commit()

    def append_receipt(self, receipt: Mapping[str, Any]) -> None:
        with self.session_factory() as db:
            ensure_orchestrator_schema(db)
            db.add(
                CalyxBrainPulseReceipt(
                    ledger_key=self.key,
                    pulse_id=str(receipt.get("pulse_id", ""))[:80],
                    receipt_json=json.dumps(receipt, sort_keys=True, default=str),
                )
            )
            db.commit()

    def receipts(self) -> list[dict[str, Any]]:
        with self.session_factory() as db:
            ensure_orchestrator_schema(db)
            rows = db.scalars(
                select(CalyxBrainPulseReceipt)
                .where(CalyxBrainPulseReceipt.ledger_key == self.key)
                .order_by(CalyxBrainPulseReceipt.recorded_at)
            ).all()
            return [json.loads(row.receipt_json) for row in rows]

    @contextmanager
    def exclusive(self) -> Iterator[bool]:
        with self.session_factory() as db:
            bind = db.get_bind()
        if bind.dialect.name == "postgresql":
            lock_key = _advisory_key(self.key)
            # A dedicated connection holds the session-level advisory lock
            # for the whole pulse; closing it releases the lock even if the
            # worker dies mid-pulse.
            with bind.connect() as connection:
                acquired = bool(
                    connection.execute(
                        text("SELECT pg_try_advisory_lock(:k)"), {"k": lock_key}
                    ).scalar()
                )
                connection.commit()
                try:
                    yield acquired
                finally:
                    if acquired:
                        connection.execute(
                            text("SELECT pg_advisory_unlock(:k)"), {"k": lock_key}
                        )
                        connection.commit()
            return
        with _LOCAL_LOCKS_GUARD:
            lock = _LOCAL_LOCKS.setdefault(self.key, threading.Lock())
        acquired = lock.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                lock.release()

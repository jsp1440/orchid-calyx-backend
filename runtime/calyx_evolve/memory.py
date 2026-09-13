"""REMEMBER stage: durable experimental memory for CALYX-EVOLVE-001.

Memory is what makes the loop worth running.  Without it Calyx re-spends model
and agent effort rediscovering strategies it already refuted.  Two properties
matter more than storage volume:

*Idempotent replay* — a run is keyed by ``replay_key``, a hash over the campaign,
the candidate configuration, the fixture, the evaluator version and the baseline.
Asking for the same experiment twice returns the first durable record and spends
nothing.

*Failed candidates stay queryable* — nothing is deleted on failure.  A refuted
strategy is deduplicated by its novelty key so it is not proposed again, and its
findings remain readable.

Two backends implement the same protocol: an in-process store used by tests and
by deployments without ``DATABASE_URL``, and a PostgreSQL store writing to the
``oc_admin`` schema created by
``migrations/CALYX-EVOLVE-001-experiment-ledger.sql``.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from runtime.calyx_evolve.provenance import content_hash
from runtime.calyx_evolve.redaction import assert_inspectable

PERSISTENCE_MEMORY = "memory"
PERSISTENCE_POSTGRES = "postgres"

TABLE_CAMPAIGNS = "oc_admin.calyx_evolve_campaigns"
TABLE_COGNITION = "oc_admin.calyx_evolve_cognition_items"
TABLE_CANDIDATES = "oc_admin.calyx_evolve_candidates"
TABLE_RUNS = "oc_admin.calyx_evolve_runs"
TABLE_METRICS = "oc_admin.calyx_evolve_metrics"
TABLE_FINDINGS = "oc_admin.calyx_evolve_findings"
TABLE_PROPOSALS = "oc_admin.calyx_evolve_promotion_proposals"


def replay_key(
    *,
    campaign_id: str,
    config_hash: str,
    fixture_hash: str,
    evaluator_version: str,
    scoring_version: str,
    baseline_candidate_id: str | None,
) -> str:
    """Derive the idempotency key for one experiment."""

    return content_hash(
        {
            "campaign_id": campaign_id,
            "config_hash": config_hash,
            "fixture_hash": fixture_hash,
            "evaluator_version": evaluator_version,
            "scoring_version": scoring_version,
            "baseline_candidate_id": baseline_candidate_id,
        }
    )


class ExperimentMemory(Protocol):
    """The durable surface the campaign runner depends on."""

    persistence_mode: str

    def upsert_campaign(self, record: Mapping[str, Any]) -> None: ...
    def get_campaign(self, campaign_id: str) -> dict[str, Any] | None: ...
    def list_campaigns(self) -> list[dict[str, Any]]: ...
    def record_cognition(self, campaign_id: str, items: Iterable[Mapping[str, Any]]) -> None: ...
    def list_cognition(self, campaign_id: str) -> list[dict[str, Any]]: ...
    def upsert_candidate(self, record: Mapping[str, Any]) -> None: ...
    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None: ...
    def list_candidates(self, campaign_id: str) -> list[dict[str, Any]]: ...
    def find_candidate_by_novelty(self, campaign_id: str, novelty_key: str) -> dict[str, Any] | None: ...
    def find_run_by_replay_key(self, key: str) -> dict[str, Any] | None: ...
    def save_run(self, record: Mapping[str, Any]) -> None: ...
    def list_runs(self, campaign_id: str) -> list[dict[str, Any]]: ...
    def save_metrics(self, run_id: str, rows: Iterable[Mapping[str, Any]]) -> None: ...
    def list_metrics(self, run_id: str) -> list[dict[str, Any]]: ...
    def save_findings(self, run_id: str, rows: Iterable[Mapping[str, Any]]) -> None: ...
    def list_findings(self, run_id: str) -> list[dict[str, Any]]: ...
    def save_proposal(self, record: Mapping[str, Any]) -> None: ...
    def list_proposals(self, campaign_id: str) -> list[dict[str, Any]]: ...


def _guard(record: Mapping[str, Any]) -> dict[str, Any]:
    """Reject a record that must not reach durable storage, then copy it."""

    assert_inspectable(record)
    return dict(record)


@dataclass
class InMemoryExperimentMemory:
    """In-process memory used by tests and by DATABASE_URL-less deployments."""

    persistence_mode: str = PERSISTENCE_MEMORY
    campaigns: dict[str, dict[str, Any]] = field(default_factory=dict)
    cognition: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    candidates: dict[str, dict[str, Any]] = field(default_factory=dict)
    runs: dict[str, dict[str, Any]] = field(default_factory=dict)
    metrics: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    findings: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    proposals: dict[str, dict[str, Any]] = field(default_factory=dict)

    def upsert_campaign(self, record: Mapping[str, Any]) -> None:
        payload = _guard(record)
        self.campaigns[str(payload["campaign_id"])] = payload

    def get_campaign(self, campaign_id: str) -> dict[str, Any] | None:
        found = self.campaigns.get(campaign_id)
        return dict(found) if found else None

    def list_campaigns(self) -> list[dict[str, Any]]:
        return [dict(row) for _, row in sorted(self.campaigns.items())]

    def record_cognition(self, campaign_id: str, items: Iterable[Mapping[str, Any]]) -> None:
        bucket = self.cognition.setdefault(campaign_id, [])
        existing = {row["content_hash"] for row in bucket}
        for item in items:
            payload = _guard(item)
            if payload["content_hash"] in existing:
                continue
            bucket.append(payload)
            existing.add(payload["content_hash"])
        bucket.sort(key=lambda row: (row["kind"], row["item_id"]))

    def list_cognition(self, campaign_id: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.cognition.get(campaign_id, [])]

    def upsert_candidate(self, record: Mapping[str, Any]) -> None:
        payload = _guard(record)
        self.candidates[str(payload["candidate_id"])] = payload

    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        found = self.candidates.get(candidate_id)
        return dict(found) if found else None

    def list_candidates(self, campaign_id: str) -> list[dict[str, Any]]:
        return [
            dict(row)
            for _, row in sorted(self.candidates.items())
            if row.get("campaign_id") == campaign_id
        ]

    def find_candidate_by_novelty(self, campaign_id: str, novelty_key: str) -> dict[str, Any] | None:
        for _, row in sorted(self.candidates.items()):
            if row.get("campaign_id") == campaign_id and row.get("novelty_key") == novelty_key:
                return dict(row)
        return None

    def find_run_by_replay_key(self, key: str) -> dict[str, Any] | None:
        for _, row in sorted(self.runs.items()):
            if row.get("replay_key") == key:
                return dict(row)
        return None

    def save_run(self, record: Mapping[str, Any]) -> None:
        payload = _guard(record)
        self.runs[str(payload["run_id"])] = payload

    def list_runs(self, campaign_id: str) -> list[dict[str, Any]]:
        return [
            dict(row)
            for _, row in sorted(self.runs.items())
            if row.get("campaign_id") == campaign_id
        ]

    def save_metrics(self, run_id: str, rows: Iterable[Mapping[str, Any]]) -> None:
        self.metrics[run_id] = [_guard(row) for row in rows]

    def list_metrics(self, run_id: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.metrics.get(run_id, [])]

    def save_findings(self, run_id: str, rows: Iterable[Mapping[str, Any]]) -> None:
        self.findings[run_id] = [_guard(row) for row in rows]

    def list_findings(self, run_id: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.findings.get(run_id, [])]

    def save_proposal(self, record: Mapping[str, Any]) -> None:
        payload = _guard(record)
        self.proposals[str(payload["proposal_id"])] = payload

    def list_proposals(self, campaign_id: str) -> list[dict[str, Any]]:
        return [
            dict(row)
            for _, row in sorted(self.proposals.items())
            if row.get("campaign_id") == campaign_id
        ]


@dataclass
class PostgresExperimentMemory:
    """PostgreSQL-backed memory.

    ``execute`` receives a callback and must invoke it with a live ``dict_row``
    cursor inside a committed transaction — the same contract as
    ``app.routers.owner_operations.db_execute``.
    """

    execute: Callable[[Callable[[Any], Any]], Any]
    persistence_mode: str = PERSISTENCE_POSTGRES

    # --- helpers -------------------------------------------------------------

    def _json(self, payload: Mapping[str, Any]) -> Any:
        from psycopg.types.json import Jsonb

        return Jsonb(dict(payload))

    def _upsert(self, table: str, key_column: str, key: str, payload: Mapping[str, Any]) -> None:
        guarded = _guard(payload)

        def _write(cur: Any) -> None:
            cur.execute(
                f"""
                INSERT INTO {table} ({key_column}, payload, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT ({key_column}) DO UPDATE
                    SET payload = EXCLUDED.payload, updated_at = NOW()
                """,
                (key, self._json(guarded)),
            )

        self.execute(_write)

    def _select_one(self, table: str, column: str, value: str) -> dict[str, Any] | None:
        def _read(cur: Any) -> dict[str, Any] | None:
            cur.execute(f"SELECT payload FROM {table} WHERE {column} = %s LIMIT 1", (value,))
            row = cur.fetchone()
            return dict(row["payload"]) if row else None

        return self.execute(_read)

    def _select_many(self, table: str, column: str, value: str, order: str) -> list[dict[str, Any]]:
        def _read(cur: Any) -> list[dict[str, Any]]:
            cur.execute(
                f"SELECT payload FROM {table} WHERE {column} = %s ORDER BY {order}",
                (value,),
            )
            return [dict(row["payload"]) for row in cur.fetchall()]

        return self.execute(_read) or []

    # --- campaigns -----------------------------------------------------------

    def upsert_campaign(self, record: Mapping[str, Any]) -> None:
        self._upsert(TABLE_CAMPAIGNS, "campaign_id", str(record["campaign_id"]), record)

    def get_campaign(self, campaign_id: str) -> dict[str, Any] | None:
        return self._select_one(TABLE_CAMPAIGNS, "campaign_id", campaign_id)

    def list_campaigns(self) -> list[dict[str, Any]]:
        def _read(cur: Any) -> list[dict[str, Any]]:
            cur.execute(f"SELECT payload FROM {TABLE_CAMPAIGNS} ORDER BY campaign_id")
            return [dict(row["payload"]) for row in cur.fetchall()]

        return self.execute(_read) or []

    # --- cognition -----------------------------------------------------------

    def record_cognition(self, campaign_id: str, items: Iterable[Mapping[str, Any]]) -> None:
        rows = [_guard(item) for item in items]
        if not rows:
            return

        def _write(cur: Any) -> None:
            for row in rows:
                cur.execute(
                    f"""
                    INSERT INTO {TABLE_COGNITION}
                        (campaign_id, item_id, content_hash, payload, created_at)
                    VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT (campaign_id, item_id, content_hash) DO NOTHING
                    """,
                    (campaign_id, str(row["item_id"]), str(row["content_hash"]), self._json(row)),
                )

        self.execute(_write)

    def list_cognition(self, campaign_id: str) -> list[dict[str, Any]]:
        return self._select_many(TABLE_COGNITION, "campaign_id", campaign_id, "item_id, content_hash")

    # --- candidates ----------------------------------------------------------

    def upsert_candidate(self, record: Mapping[str, Any]) -> None:
        self._upsert(TABLE_CANDIDATES, "candidate_id", str(record["candidate_id"]), record)

    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        return self._select_one(TABLE_CANDIDATES, "candidate_id", candidate_id)

    def list_candidates(self, campaign_id: str) -> list[dict[str, Any]]:
        return self._select_many(TABLE_CANDIDATES, "campaign_id", campaign_id, "candidate_id")

    def find_candidate_by_novelty(self, campaign_id: str, novelty_key: str) -> dict[str, Any] | None:
        def _read(cur: Any) -> dict[str, Any] | None:
            cur.execute(
                f"""
                SELECT payload FROM {TABLE_CANDIDATES}
                WHERE campaign_id = %s AND novelty_key = %s
                ORDER BY candidate_id LIMIT 1
                """,
                (campaign_id, novelty_key),
            )
            row = cur.fetchone()
            return dict(row["payload"]) if row else None

        return self.execute(_read)

    # --- runs ----------------------------------------------------------------

    def find_run_by_replay_key(self, key: str) -> dict[str, Any] | None:
        return self._select_one(TABLE_RUNS, "replay_key", key)

    def save_run(self, record: Mapping[str, Any]) -> None:
        guarded = _guard(record)

        def _write(cur: Any) -> None:
            cur.execute(
                f"""
                INSERT INTO {TABLE_RUNS}
                    (run_id, campaign_id, candidate_id, replay_key, terminal_state, payload, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (replay_key) DO NOTHING
                """,
                (
                    str(guarded["run_id"]),
                    str(guarded["campaign_id"]),
                    str(guarded["candidate_id"]),
                    str(guarded["replay_key"]),
                    str(guarded["terminal_state"]),
                    self._json(guarded),
                ),
            )

        self.execute(_write)

    def list_runs(self, campaign_id: str) -> list[dict[str, Any]]:
        return self._select_many(TABLE_RUNS, "campaign_id", campaign_id, "run_id")

    # --- metrics / findings / proposals --------------------------------------

    def save_metrics(self, run_id: str, rows: Iterable[Mapping[str, Any]]) -> None:
        guarded = [_guard(row) for row in rows]
        if not guarded:
            return

        def _write(cur: Any) -> None:
            for row in guarded:
                cur.execute(
                    f"""
                    INSERT INTO {TABLE_METRICS} (run_id, metric_key, payload, created_at)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT (run_id, metric_key) DO NOTHING
                    """,
                    (run_id, str(row["key"]), self._json(row)),
                )

        self.execute(_write)

    def list_metrics(self, run_id: str) -> list[dict[str, Any]]:
        return self._select_many(TABLE_METRICS, "run_id", run_id, "metric_key")

    def save_findings(self, run_id: str, rows: Iterable[Mapping[str, Any]]) -> None:
        guarded = [_guard(row) for row in rows]
        if not guarded:
            return

        def _write(cur: Any) -> None:
            for row in guarded:
                cur.execute(
                    f"""
                    INSERT INTO {TABLE_FINDINGS}
                        (finding_id, run_id, finding_type, payload, created_at)
                    VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT (finding_id) DO NOTHING
                    """,
                    (
                        str(row["finding_id"]),
                        run_id,
                        str(row["finding_type"]),
                        self._json(row),
                    ),
                )

        self.execute(_write)

    def list_findings(self, run_id: str) -> list[dict[str, Any]]:
        return self._select_many(TABLE_FINDINGS, "run_id", run_id, "finding_id")

    def save_proposal(self, record: Mapping[str, Any]) -> None:
        guarded = _guard(record)

        def _write(cur: Any) -> None:
            cur.execute(
                f"""
                INSERT INTO {TABLE_PROPOSALS}
                    (proposal_id, campaign_id, run_id, candidate_id, state, payload, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (proposal_id) DO UPDATE
                    SET payload = EXCLUDED.payload, state = EXCLUDED.state, updated_at = NOW()
                """,
                (
                    str(guarded["proposal_id"]),
                    str(guarded["campaign_id"]),
                    str(guarded["run_id"]),
                    str(guarded["candidate_id"]),
                    str(guarded["state"]),
                    self._json(guarded),
                ),
            )

        self.execute(_write)

    def list_proposals(self, campaign_id: str) -> list[dict[str, Any]]:
        return self._select_many(TABLE_PROPOSALS, "campaign_id", campaign_id, "proposal_id")


def persistence_mode() -> str:
    """Report whether durable Postgres memory is configured."""

    return PERSISTENCE_POSTGRES if os.environ.get("DATABASE_URL") else PERSISTENCE_MEMORY


def build_experiment_memory(
    execute: Callable[[Callable[[Any], Any]], Any] | None = None,
) -> ExperimentMemory:
    """Return the durable store when configured, otherwise the in-process one."""

    if persistence_mode() == PERSISTENCE_POSTGRES:
        if execute is None:
            from app.routers.owner_operations import db_execute

            execute = db_execute
        return PostgresExperimentMemory(execute=execute)
    return InMemoryExperimentMemory()

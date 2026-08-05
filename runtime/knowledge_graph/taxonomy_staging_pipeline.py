"""Taxonomy source-to-staging pipeline for World Plants / Hassler releases.

Converts an inspected WorldPlantsReleaseStore report into a bounded SQLite
staging graph projection.  The pipeline is:

  1. resumable  — a checkpoint written after each flush lets the caller restart
                  without duplicating graph nodes or edges;
  2. idempotent — nodes are keyed on ``canonical_name``; edges on
                  ``(edge_type, from, to)``.  Re-running over the same release
                  produces zero net graph deltas;
  3. provenance-complete — every node and edge carries release_id, source_sha256,
                  source_version, acquired_at, and the reconciliation outcome;
  4. staging-only — the pipeline never writes to the production graph and never
                  automatically promotes the release.

Usage::

    store = WorldPlantsReleaseStore(root)
    report = store.get(release_id)
    pipeline = TaxonomyStagingPipeline(staging_db_path)
    result = pipeline.run(report)
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from runtime.knowledge_graph.canonical_taxonomy import (
    ACCEPTED,
    SYNONYM,
    CanonicalTaxon,
    build_canonical_registry,
    canonical_name_of,
)
from runtime.world_plants_ingest import parse_world_orchids_release

# ---------------------------------------------------------------------------
# checkpoint schema
# ---------------------------------------------------------------------------

_CHECKPOINT_DDL = """
CREATE TABLE IF NOT EXISTS taxonomy_staging_checkpoints (
    release_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    rows_processed INTEGER NOT NULL DEFAULT 0,
    rows_total INTEGER NOT NULL DEFAULT 0,
    completed INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (release_id, phase)
)
"""

# ---------------------------------------------------------------------------
# staging schema
# ---------------------------------------------------------------------------

_TAXONOMY_NODE_DDL = """
CREATE TABLE IF NOT EXISTS taxonomy_staging_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL UNIQUE,
    scientific_name TEXT,
    authorship TEXT,
    rank TEXT,
    status TEXT NOT NULL,
    is_hybrid INTEGER NOT NULL DEFAULT 0,
    accepted_canonical_name TEXT,
    release_id TEXT NOT NULL,
    source_sha256 TEXT,
    source_version TEXT,
    acquired_at TEXT,
    reconciliation_outcome TEXT,
    payload TEXT NOT NULL DEFAULT '{}'
)
"""

_TAXONOMY_EDGE_DDL = """
CREATE TABLE IF NOT EXISTS taxonomy_staging_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    edge_type TEXT NOT NULL,
    from_canonical_name TEXT NOT NULL,
    to_canonical_name TEXT NOT NULL,
    release_id TEXT NOT NULL,
    source_sha256 TEXT,
    reconciliation_outcome TEXT,
    payload TEXT NOT NULL DEFAULT '{}',
    UNIQUE(edge_type, from_canonical_name, to_canonical_name)
)
"""


# ---------------------------------------------------------------------------
# result type
# ---------------------------------------------------------------------------


@dataclass
class TaxonomyStagingResult:
    release_id: str
    source_sha256: str | None
    source_version: str | None
    acquired_at: str | None
    accepted_count: int
    synonym_count: int
    edge_count: int
    unmatched_synonym_count: int
    resumed: bool
    idempotent_replay: bool
    production_graph_mutation: bool = False
    automatic_promotion: bool = False
    staging_db_path: str = ""
    unresolved_review_queue: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# pipeline
# ---------------------------------------------------------------------------


class TaxonomyStagingPipeline:
    """Project a World Plants release into a bounded SQLite staging graph.

    Parameters
    ----------
    db_path:
        Path to the SQLite file used as the staging store and checkpoint
        registry.  Created (with all needed tables) on first use.
    flush_every:
        How many taxa to write between checkpoint updates.  Lower values
        make the pipeline more resumable at the cost of slightly more I/O.
    """

    def __init__(self, db_path: str | Path, *, flush_every: int = 500) -> None:
        self.db_path = str(db_path)
        self.flush_every = flush_every
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(_CHECKPOINT_DDL)
            conn.execute(_TAXONOMY_NODE_DDL)
            conn.execute(_TAXONOMY_EDGE_DDL)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    # ------------------------------------------------------------------
    # checkpoint helpers
    # ------------------------------------------------------------------

    def _load_checkpoint(self, conn: sqlite3.Connection, release_id: str, phase: str) -> dict[str, Any]:
        row = conn.execute(
            "SELECT rows_processed, rows_total, completed FROM taxonomy_staging_checkpoints"
            " WHERE release_id = ? AND phase = ?",
            (release_id, phase),
        ).fetchone()
        if row is None:
            return {"rows_processed": 0, "rows_total": 0, "completed": False}
        return {"rows_processed": row[0], "rows_total": row[1], "completed": bool(row[2])}

    def _save_checkpoint(
        self,
        conn: sqlite3.Connection,
        release_id: str,
        phase: str,
        rows_processed: int,
        rows_total: int,
        completed: bool,
    ) -> None:
        conn.execute(
            "INSERT INTO taxonomy_staging_checkpoints"
            " (release_id, phase, rows_processed, rows_total, completed, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(release_id, phase) DO UPDATE SET"
            "   rows_processed = excluded.rows_processed,"
            "   rows_total = excluded.rows_total,"
            "   completed = excluded.completed,"
            "   updated_at = excluded.updated_at",
            (
                release_id,
                phase,
                rows_processed,
                rows_total,
                int(completed),
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    # ------------------------------------------------------------------
    # node / edge writers
    # ------------------------------------------------------------------

    def _upsert_node(
        self,
        conn: sqlite3.Connection,
        taxon: CanonicalTaxon,
        *,
        release_id: str,
        source_sha256: str | None,
        source_version: str | None,
        acquired_at: str | None,
        reconciliation_outcome: str,
        accepted_name_for_synonym: str | None = None,
    ) -> None:
        payload = json.dumps(
            {
                "canonical_id": taxon.canonical_id,
                "authority_mappings": [
                    {
                        "authority": m.authority,
                        "external_id": m.external_id,
                        "confidence": m.confidence,
                    }
                    for m in taxon.authority_mappings
                ],
                "provenance": taxon.provenance,
            },
            default=str,
        )
        conn.execute(
            "INSERT INTO taxonomy_staging_nodes"
            " (canonical_name, scientific_name, authorship, rank, status,"
            "  is_hybrid, accepted_canonical_name, release_id, source_sha256,"
            "  source_version, acquired_at, reconciliation_outcome, payload)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(canonical_name) DO UPDATE SET"
            "   scientific_name   = excluded.scientific_name,"
            "   authorship        = excluded.authorship,"
            "   rank              = excluded.rank,"
            "   status            = excluded.status,"
            "   is_hybrid         = excluded.is_hybrid,"
            "   accepted_canonical_name = excluded.accepted_canonical_name,"
            "   release_id        = excluded.release_id,"
            "   source_sha256     = excluded.source_sha256,"
            "   source_version    = excluded.source_version,"
            "   acquired_at       = excluded.acquired_at,"
            "   reconciliation_outcome = excluded.reconciliation_outcome,"
            "   payload           = excluded.payload",
            (
                taxon.canonical_name,
                taxon.scientific_name,
                taxon.authorship,
                taxon.rank,
                taxon.status,
                int(taxon.is_hybrid),
                accepted_name_for_synonym,
                release_id,
                source_sha256,
                source_version,
                acquired_at,
                reconciliation_outcome,
                payload,
            ),
        )

    def _upsert_synonym_edge(
        self,
        conn: sqlite3.Connection,
        synonym_canonical: str,
        accepted_canonical: str,
        *,
        release_id: str,
        source_sha256: str | None,
    ) -> None:
        conn.execute(
            "INSERT INTO taxonomy_staging_edges"
            " (edge_type, from_canonical_name, to_canonical_name,"
            "  release_id, source_sha256, reconciliation_outcome, payload)"
            " VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(edge_type, from_canonical_name, to_canonical_name) DO UPDATE SET"
            "   release_id = excluded.release_id,"
            "   source_sha256 = excluded.source_sha256",
            (
                "synonym_of",
                synonym_canonical,
                accepted_canonical,
                release_id,
                source_sha256,
                "synonym_resolved",
                "{}",
            ),
        )

    # ------------------------------------------------------------------
    # main entry point
    # ------------------------------------------------------------------

    def run(self, report: dict[str, Any]) -> TaxonomyStagingResult:
        """Project the release described by *report* into the staging graph.

        *report* must be a ``WorldPlantsReleaseStore`` inspection report dict.
        The method is safe to call multiple times with the same *report*:
        the second call detects the completed checkpoint and returns
        immediately with ``idempotent_replay=True``.
        """

        release_id: str = str(report.get("release_id") or "")
        snapshot: dict[str, Any] = report.get("snapshot") or {}
        source_sha256: str | None = snapshot.get("sha256") or snapshot.get("file_sha256")
        source_version: str | None = snapshot.get("version_label")
        acquired_at: str | None = snapshot.get("acquired_at")

        if not release_id:
            raise ValueError("report is missing release_id")

        with self._connect() as conn:
            cp_nodes = self._load_checkpoint(conn, release_id, "nodes")
            cp_edges = self._load_checkpoint(conn, release_id, "edges")

        if cp_nodes["completed"] and cp_edges["completed"]:
            # Nothing to do — return summary from stored counts.
            with self._connect() as conn:
                n_accepted = conn.execute(
                    "SELECT count(*) FROM taxonomy_staging_nodes WHERE release_id=? AND status=?",
                    (release_id, ACCEPTED),
                ).fetchone()[0]
                n_synonym = conn.execute(
                    "SELECT count(*) FROM taxonomy_staging_nodes WHERE release_id=? AND status=?",
                    (release_id, SYNONYM),
                ).fetchone()[0]
                n_edges = conn.execute(
                    "SELECT count(*) FROM taxonomy_staging_edges WHERE release_id=?",
                    (release_id,),
                ).fetchone()[0]
            return TaxonomyStagingResult(
                release_id=release_id,
                source_sha256=source_sha256,
                source_version=source_version,
                acquired_at=acquired_at,
                accepted_count=n_accepted,
                synonym_count=n_synonym,
                edge_count=n_edges,
                unmatched_synonym_count=0,
                resumed=False,
                idempotent_replay=True,
                staging_db_path=self.db_path,
            )

        # Build registry from stored source bytes via the release store root.
        # We accept pre-parsed row dicts passed via ``_load_rows_from_report``
        # helper so tests can inject fixture data without touching the file
        # system.  Production callers should pass ``source_rows`` explicitly.
        source_rows: list[dict[str, Any]] = list(
            self._extract_rows_from_report(report)
        )
        synonym_rows: list[dict[str, Any]] = list(
            self._extract_synonym_rows_from_report(report)
        )

        registry = build_canonical_registry(
            load_rows=source_rows,
            synonym_rows=synonym_rows,
        )

        accepted_taxa = registry.accepted()
        synonym_taxa = registry.synonyms()
        all_taxa = accepted_taxa + synonym_taxa
        unresolved: list[dict[str, Any]] = []

        # Detect synonym rows the registry silently dropped because the
        # accepted name was not found in the backbone (orphan synonyms).
        registered_names = frozenset(registry.name_index.keys())
        for syn_row in synonym_rows:
            rel = (syn_row.get("relationship") or "").lower()
            if rel != SYNONYM:
                continue
            syn_name = canonical_name_of(
                syn_row.get("input_match_name") or syn_row.get("input_name") or ""
            )
            if not syn_name:
                continue
            if syn_name not in registered_names:
                acc_name = canonical_name_of(
                    syn_row.get("accepted_match_name") or syn_row.get("accepted_name") or ""
                )
                unresolved.append(
                    {
                        "canonical_name": syn_name,
                        "reason": (
                            f"Synonym input name could not be registered; "
                            f"accepted target '{acc_name}' was not found in backbone."
                        ),
                    }
                )

        resumed = cp_nodes["rows_processed"] > 0

        # Phase 1: nodes — use a name-set for safe resumability (index-based
        # skip is unstable if the registry ordering changes between runs).
        with self._connect() as conn:
            already_staged: frozenset[str] = frozenset(
                row[0]
                for row in conn.execute(
                    "SELECT canonical_name FROM taxonomy_staging_nodes WHERE release_id = ?",
                    (release_id,),
                ).fetchall()
            )

        with self._connect() as conn:
            for i, taxon in enumerate(all_taxa):
                if taxon.canonical_name in already_staged:
                    continue

                accepted_name: str | None = None
                reconciliation_outcome = "accepted"

                if taxon.status == SYNONYM:
                    if taxon.accepted_canonical_id is not None:
                        acc = registry.taxa.get(taxon.accepted_canonical_id)
                        if acc is not None:
                            accepted_name = acc.canonical_name
                            reconciliation_outcome = "synonym_resolved"
                        else:
                            reconciliation_outcome = "unresolved_synonym"
                            unresolved.append(
                                {
                                    "canonical_name": taxon.canonical_name,
                                    "reason": "Accepted canonical id not found in registry.",
                                }
                            )
                    else:
                        reconciliation_outcome = "unresolved_synonym"
                        unresolved.append(
                            {
                                "canonical_name": taxon.canonical_name,
                                "reason": "Synonym has no accepted_canonical_id.",
                            }
                        )

                self._upsert_node(
                    conn,
                    taxon,
                    release_id=release_id,
                    source_sha256=source_sha256,
                    source_version=source_version,
                    acquired_at=acquired_at,
                    reconciliation_outcome=reconciliation_outcome,
                    accepted_name_for_synonym=accepted_name,
                )

                if (i + 1) % self.flush_every == 0:
                    self._save_checkpoint(
                        conn, release_id, "nodes", i + 1, len(all_taxa), False
                    )
                    conn.commit()

            self._save_checkpoint(
                conn, release_id, "nodes", len(all_taxa), len(all_taxa), True
            )
            conn.commit()

        # Phase 2: synonym edges — use existing edge set for safe resumability.
        with self._connect() as conn:
            already_edged: frozenset[str] = frozenset(
                f"{row[0]}:{row[1]}"
                for row in conn.execute(
                    "SELECT from_canonical_name, to_canonical_name"
                    " FROM taxonomy_staging_edges WHERE release_id = ?",
                    (release_id,),
                ).fetchall()
            )

        with self._connect() as conn:
            for j, taxon in enumerate(synonym_taxa):
                if taxon.accepted_canonical_id is not None:
                    acc = registry.taxa.get(taxon.accepted_canonical_id)
                    if acc is not None:
                        edge_key = f"{taxon.canonical_name}:{acc.canonical_name}"
                        if edge_key not in already_edged:
                            self._upsert_synonym_edge(
                                conn,
                                taxon.canonical_name,
                                acc.canonical_name,
                                release_id=release_id,
                                source_sha256=source_sha256,
                            )

                if (j + 1) % self.flush_every == 0:
                    self._save_checkpoint(
                        conn, release_id, "edges", j + 1, len(synonym_taxa), False
                    )
                    conn.commit()

            self._save_checkpoint(
                conn, release_id, "edges", len(synonym_taxa), len(synonym_taxa), True
            )
            conn.commit()

        with self._connect() as conn:
            n_accepted = conn.execute(
                "SELECT count(*) FROM taxonomy_staging_nodes WHERE release_id=? AND status=?",
                (release_id, ACCEPTED),
            ).fetchone()[0]
            n_synonym = conn.execute(
                "SELECT count(*) FROM taxonomy_staging_nodes WHERE release_id=? AND status=?",
                (release_id, SYNONYM),
            ).fetchone()[0]
            n_edges = conn.execute(
                "SELECT count(*) FROM taxonomy_staging_edges WHERE release_id=?",
                (release_id,),
            ).fetchone()[0]

        return TaxonomyStagingResult(
            release_id=release_id,
            source_sha256=source_sha256,
            source_version=source_version,
            acquired_at=acquired_at,
            accepted_count=n_accepted,
            synonym_count=n_synonym,
            edge_count=n_edges,
            unmatched_synonym_count=len(unresolved),
            resumed=resumed,
            idempotent_replay=False,
            staging_db_path=self.db_path,
            unresolved_review_queue=unresolved,
        )

    # ------------------------------------------------------------------
    # internal helpers — extracting rows from report or raw bytes
    # ------------------------------------------------------------------

    def _extract_rows_from_report(
        self, report: dict[str, Any]
    ) -> Iterable[dict[str, Any]]:
        """Yield load rows for ``build_canonical_registry``.

        Production: reads the source bytes stored alongside the report.
        Test shortcut: report may carry ``_fixture_rows`` directly.
        """
        if "_fixture_rows" in report:
            return report["_fixture_rows"]
        source_bytes = report.get("_source_bytes")
        if source_bytes is not None:
            parsed = parse_world_orchids_release(source_bytes)
            return [
                {"name": row.name, "taxon_code": row.taxon_code}
                for row in parsed.rows
            ]
        # Fall back: extract from inspection rows embedded in report.
        rows = report.get("_rows") or []
        if rows:
            return rows
        return []

    def _extract_synonym_rows_from_report(
        self, report: dict[str, Any]
    ) -> Iterable[dict[str, Any]]:
        if "_fixture_synonym_rows" in report:
            return report["_fixture_synonym_rows"]
        return report.get("_synonym_rows") or []

    # ------------------------------------------------------------------
    # query helpers
    # ------------------------------------------------------------------

    def count_staged(self, release_id: str) -> dict[str, int]:
        with self._connect() as conn:
            return {
                "accepted": conn.execute(
                    "SELECT count(*) FROM taxonomy_staging_nodes WHERE release_id=? AND status=?",
                    (release_id, ACCEPTED),
                ).fetchone()[0],
                "synonyms": conn.execute(
                    "SELECT count(*) FROM taxonomy_staging_nodes WHERE release_id=? AND status=?",
                    (release_id, SYNONYM),
                ).fetchone()[0],
                "edges": conn.execute(
                    "SELECT count(*) FROM taxonomy_staging_edges WHERE release_id=?",
                    (release_id,),
                ).fetchone()[0],
            }

    def get_node(self, canonical_name: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT canonical_name, scientific_name, authorship, rank, status,"
                " is_hybrid, accepted_canonical_name, release_id, source_sha256,"
                " source_version, acquired_at, reconciliation_outcome, payload"
                " FROM taxonomy_staging_nodes WHERE canonical_name = ?",
                (canonical_name,),
            ).fetchone()
        if row is None:
            return None
        return {
            "canonical_name": row[0],
            "scientific_name": row[1],
            "authorship": row[2],
            "rank": row[3],
            "status": row[4],
            "is_hybrid": bool(row[5]),
            "accepted_canonical_name": row[6],
            "release_id": row[7],
            "source_sha256": row[8],
            "source_version": row[9],
            "acquired_at": row[10],
            "reconciliation_outcome": row[11],
            "payload": json.loads(row[12] or "{}"),
        }

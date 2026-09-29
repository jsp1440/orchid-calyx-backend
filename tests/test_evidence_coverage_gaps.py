"""Evidence-coverage knowledge gaps: counts from the KG, fail-closed, never keyword counts."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from runtime import evidence_coverage_gaps as ecg
from runtime.evidence_coverage_gaps import (
    EVIDENCE_COVERAGE_METHOD,
    EvidenceCoverageGapSource,
    EvidenceCoverageUnavailable,
)
from runtime.knowledge_gap_discovery import (
    DISCOVERY_METHOD,
    KnowledgeGapDiscoveryEngine,
)
from tests.test_species_dossier_routes import YONG_GEE_CLEANED, yong_gee_kg_rows

NOW = datetime(2026, 9, 25, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "runtime" / "knowledge_gaps" / "latest.json"
YG = ecg.YONG_GEE_SOURCE_TABLE


class FakeKG:
    """An in-memory KG: taxa plus (taxon, edge_type, node_type, source_table, evidence_type) edges.

    The cursor answers each read-only statement the source issues by evaluating
    the same semantics in Python; any other SQL is a test failure.
    """

    def __init__(
        self,
        taxa: list[str],
        edges: list[tuple[str, str, str, str | None, str | None]],
        *,
        present: bool = True,
        labels: dict[str, str] | None = None,
    ) -> None:
        self.taxa = taxa
        self.labels = labels or {}
        self.edges = edges
        self.present = present
        self.statements: list[str] = []

    def cursor(self) -> FakeKGCursor:
        return FakeKGCursor(self)


class FakeKGCursor:
    def __init__(self, kg: FakeKG) -> None:
        self.kg = kg
        self._rows: list[dict[str, Any]] = []

    def _covered(self, types: list[str], relations: list[str]) -> set[str]:
        return {
            taxon
            for taxon, edge_type, node_type, _, evidence_type in self.kg.edges
            if (
                edge_type == "supported_by_evidence"
                and node_type == "evidence"
                and (evidence_type or "") in types
            )
            or edge_type in relations
        }

    def _held(self, source: str, types: list[str] | None = None) -> set[str]:
        return {
            taxon
            for taxon, edge_type, node_type, source_table, evidence_type in self.kg.edges
            if edge_type == "supported_by_evidence"
            and node_type == "evidence"
            and source_table == source
            and (types is None or (evidence_type or "") in types)
        }

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.kg.statements.append(sql)
        stripped = sql.strip().upper()
        assert stripped.startswith(
            ("SELECT", "SET TRANSACTION READ ONLY", "SET LOCAL")
        ), sql
        if sql.startswith("SET "):
            self._rows = []
        elif sql == ecg.SQL_PRESENT:
            self._rows = [
                {"nodes_present": self.kg.present, "edges_present": self.kg.present}
            ]
        elif sql == ecg.SQL_TAXON_LABELS:
            self._rows = [
                {"source_pk": t, "display_label": self.kg.labels.get(t)}
                for t in sorted(params[0])
                if t in self.kg.taxa
            ]
        elif sql == ecg.SQL_TAXA_EXAMINED:
            self._rows = [{"n": len(self.kg.taxa)}]
        elif sql == ecg.SQL_EVIDENCE_SOURCES:
            sources = sorted(
                {
                    e[3]
                    for e in self.kg.edges
                    if e[1] == "supported_by_evidence" and e[3]
                }
            )
            self._rows = [
                {"source_table": s, "taxa": len(self._held(s))} for s in sources
            ]
        elif sql == ecg.SQL_DOMAIN_COVERED:
            self._rows = [{"n": len(self._covered(*params))}]
        elif sql == ecg.SQL_DOMAIN_EXAMPLES:
            covered = self._covered(params[0], params[1])
            ids = sorted(t for t in self.kg.taxa if t not in covered)[: params[2]]
            self._rows = [{"source_pk": t} for t in ids]
        elif sql == ecg.SQL_DOMAIN_LACKING_PAGE:
            covered = self._covered(params[0], params[1])
            ids = sorted(
                t for t in self.kg.taxa if t not in covered and t > params[2]
            )[: params[3]]
            self._rows = [{"source_pk": t} for t in ids]
        elif sql == ecg.SQL_SOURCE_DOMAIN_TAXA:
            self._rows = [{"n": len(self._held(params[0], params[1]))}]
        elif sql in (ecg.SQL_PARTIAL_COUNT, ecg.SQL_PARTIAL_EXAMPLES):
            missing = sorted(
                self._held(params[0]) - self._covered(params[1], params[2])
            )
            if sql == ecg.SQL_PARTIAL_COUNT:
                self._rows = [{"n": len(missing)}]
            else:
                self._rows = [{"source_pk": t} for t in missing[: params[3]]]
        else:  # pragma: no cover
            raise AssertionError(f"unexpected SQL: {sql}")

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)


def yong_gee_edges(taxon: str, cleaned: dict[str, str | None]) -> list[tuple]:
    """Edges exactly as the Yong Gee adapter publishes them (reuses the dossier test fake)."""
    return [
        (
            taxon,
            "supported_by_evidence",
            "evidence",
            row["source_table"],
            row["payload_json"]["evidence_type"],
        )
        for row in yong_gee_kg_rows(taxon, cleaned)
    ]


def sample_kg() -> FakeKG:
    # 101: full Yong Gee record. 102: Yong Gee record without morphology/phenology.
    # 103: no evidence at all, but a literature relation. 104: nothing.
    partial = {
        k: v
        for k, v in YONG_GEE_CLEANED.items()
        if k not in {"characteristicsp", "scent", "season"}
    }
    edges = [
        *yong_gee_edges("101", YONG_GEE_CLEANED),
        *yong_gee_edges("102", partial),
        (
            "103",
            "documented_by",
            "publication",
            "oc_graph.taxon_literature_edges",
            None,
        ),
    ]
    return FakeKG(["101", "102", "103", "104"], edges)


def source_for(kg: FakeKG) -> EvidenceCoverageGapSource:
    return EvidenceCoverageGapSource(lambda callback: callback(kg.cursor()))


def test_counts_come_from_the_kg_and_partial_federated_coverage_ranks_first():
    kg = sample_kg()
    payload = source_for(kg).collect(now=NOW)
    assert payload["method"] == EVIDENCE_COVERAGE_METHOD
    assert payload["summary"]["taxa_examined"] == 4
    coverage = payload["domain_coverage"]
    assert (
        coverage["nomenclature"]["taxa_covered"],
        coverage["nomenclature"]["taxa_lacking"],
    ) == (2, 2)
    assert (
        coverage["morphology"]["taxa_covered"],
        coverage["morphology"]["taxa_lacking"],
    ) == (1, 3)
    assert (
        coverage["literature"]["taxa_covered"] == 3
    )  # 101, 102 bibliography + 103 documented_by
    assert coverage["pollinators"]["status"] == "gap"
    assert coverage["distribution"]["locality_gated"] is True
    assert payload["evidence_sources"] == [
        {
            "source_table": YG,
            "source_name": "Gary Yong Gee Orchid Database",
            "taxa_with_evidence": 2,
        }
    ]

    gaps = {gap["gap_id"]: gap for gap in payload["gaps"]}
    morph = gaps["KG-EVCOV-MORPHOLOGY-FEDERATED-GARY-YONG-GEE-WORKBOOK"]
    assert morph["counts"] == {
        "taxa_examined": 4,
        "taxa_held_by_source": 2,
        "taxa_supplied_in_domain_by_source": 1,
        "taxa_held_lacking_domain": 1,
    }
    assert morph["example_taxon_ids"] == ["102"]
    assert morph["candidate_source"]["coverage"] == "partial"
    assert gaps["KG-EVCOV-MORPHOLOGY"]["example_taxon_ids"] == ["102", "103", "104"]
    # No partial gap where the source already covers every taxon it holds.
    assert "KG-EVCOV-NOMENCLATURE-FEDERATED-GARY-YONG-GEE-WORKBOOK" not in gaps
    # Every gap names its method and carries KG counts, never keyword counts.
    for gap in payload["gaps"]:
        assert gap["method"] == EVIDENCE_COVERAGE_METHOD
        assert f"Method: {EVIDENCE_COVERAGE_METHOD}" in gap["evidence"]
        assert "Matched runtime items" not in " ".join(gap["evidence"])
        assert "provisional/candidate" in gap["proposed_action"]

    order = [gap["gap_id"] for gap in payload["gaps"]]
    assert order[0] == "KG-EVCOV-MORPHOLOGY-FEDERATED-GARY-YONG-GEE-WORKBOOK"
    assert order.index(
        "KG-EVCOV-PHENOLOGY-FEDERATED-GARY-YONG-GEE-WORKBOOK"
    ) < order.index("KG-EVCOV-NOMENCLATURE")
    assert order[-1] == "KG-EVCOV-DISTRIBUTION"  # locality-gated domain ranks last
    assert payload == source_for(sample_kg()).collect(now=NOW)  # deterministic


def test_source_is_read_only():
    kg = sample_kg()
    source_for(kg).collect(now=NOW)
    assert kg.statements[0] == "SET TRANSACTION READ ONLY"
    assert all(s.strip().upper().startswith(("SELECT", "SET ")) for s in kg.statements)
    assert not any("excerpt" in s for s in kg.statements)  # no prose is ever read


@pytest.mark.parametrize(
    "source,reason",
    [
        (
            EvidenceCoverageGapSource(
                None, unavailable_reason="DATABASE_URL is not configured"
            ),
            "DATABASE_URL",
        ),
        (
            EvidenceCoverageGapSource(lambda cb: cb(None)),
            "no knowledge-graph connection",
        ),
        (
            EvidenceCoverageGapSource(
                lambda cb: cb(FakeKG([], [], present=False).cursor())
            ),
            "not provisioned",
        ),
        (
            EvidenceCoverageGapSource(lambda cb: cb(FakeKG([], []).cursor())),
            "no active taxon",
        ),
    ],
)
def test_unavailable_kg_raises(source, reason):
    with pytest.raises(EvidenceCoverageUnavailable, match=reason):
        source.collect(now=NOW)


def test_engine_uses_kg_for_discover_gaps_and_research_queue(tmp_path):
    engine = KnowledgeGapDiscoveryEngine(
        output_dir=tmp_path, kg_source=source_for(sample_kg())
    )
    payload = engine.discover(write_cache=False, now=NOW)
    assert payload["gap_source"] == "evidence_coverage_kg"
    assert payload["freshness"]["stale"] is False
    assert payload["freshness"]["method"] == EVIDENCE_COVERAGE_METHOD
    assert not (tmp_path / "latest.json").exists()

    assert engine.gaps()["gaps"][0]["source"] == "evidence_coverage_kg"
    queue = engine.research_queue(limit=3)
    assert queue["gap_source"] == "evidence_coverage_kg"
    first = queue["queue"][0]["mission"]
    assert first == {
        "domain": "morphology",
        "taxon_scope": {"taxa": 1, "example_taxon_ids": ["102"]},
        "missing": "morphology evidence (no supported_by_evidence or relation edge)",
        "candidate_source": {
            "source_table": YG,
            "source_name": "Gary Yong Gee Orchid Database",
            "coverage": "partial",
        },
        "locality_gated": False,
        "evidence_entry_state": ecg.EVIDENCE_ENTRY_STATE,
        "publishes": False,
    }
    assert "freshness" in engine.dashboard() and "freshness" in engine.domains()


def test_engine_fails_closed_to_the_stored_record_never_to_keywords(tmp_path):
    stored = json.loads(RECORD.read_text(encoding="utf-8"))
    (tmp_path / "latest.json").write_text(json.dumps(stored), encoding="utf-8")
    before = (tmp_path / "latest.json").read_text(encoding="utf-8")

    class ExplodingMemory:
        def latest(self):  # the keyword method must not run
            raise AssertionError("keyword method invoked")

    engine = KnowledgeGapDiscoveryEngine(
        output_dir=tmp_path,
        memory_store=ExplodingMemory(),
        kg_source=EvidenceCoverageGapSource(
            None, unavailable_reason="DATABASE_URL is not configured"
        ),
    )
    payload = engine.discover(write_cache=True, now=NOW)
    assert payload["gap_source"] == "stored_record_fail_closed"
    assert payload["freshness"]["stale"] is True
    assert (
        "evidence-coverage KG source unavailable (DATABASE_URL is not configured)"
        in payload["freshness"]["reason"]
    )
    assert "75 days old" in payload["freshness"]["reason"]
    assert (
        payload["freshness"]["method"] == DISCOVERY_METHOD
    )  # the stored record's method, named honestly
    assert (tmp_path / "latest.json").read_text(
        encoding="utf-8"
    ) == before  # never rewritten
    queue = engine.research_queue()
    assert queue["freshness"]["stale"] is True
    assert all(
        item["mission"] is None for item in queue["queue"]
    )  # keyword gaps are not missions


def test_engine_fails_closed_on_a_kg_read_error(tmp_path):
    def broken(_callback):
        raise RuntimeError("connection refused")

    engine = KnowledgeGapDiscoveryEngine(
        output_dir=tmp_path, kg_source=EvidenceCoverageGapSource(broken)
    )
    payload = engine.discover(now=NOW)
    assert payload["gap_source"] == "stored_record_fail_closed"
    assert payload["gaps"] == []
    assert "knowledge-graph read failed: RuntimeError" in payload["freshness"]["reason"]
    assert not (tmp_path / "latest.json").exists()


def test_planner_router_engine_without_database_fails_closed(monkeypatch):
    from runtime import planner_router

    monkeypatch.delenv("DATABASE_URL", raising=False)
    engine = planner_router.gap_engine()
    assert engine.kg_source is not None
    payload = engine.latest(now=NOW)
    assert payload["gap_source"] == "stored_record_fail_closed"
    assert payload["freshness"]["stale"] is True


def test_committed_record_is_not_regenerated_from_a_fake():
    stored = json.loads(RECORD.read_text(encoding="utf-8"))
    assert stored.get("gap_source") is None
    assert stored["freshness"]["method"] == DISCOVERY_METHOD


# -- the SQL against a real Postgres, when one is provided ---------------------------------


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL") or shutil.which("psql") is None,
    reason="TEST_DATABASE_URL not set; SQL semantics covered by the fake KG above",
)
def test_sql_against_postgres_matches_the_fake():
    psycopg = pytest.importorskip("psycopg")
    from psycopg.rows import dict_row

    kg = sample_kg()
    schema_sql = """
        DROP SCHEMA IF EXISTS oc_graph CASCADE; CREATE SCHEMA oc_graph;
        CREATE TABLE oc_graph.kg_nodes (kg_node_id BIGSERIAL PRIMARY KEY, node_type TEXT NOT NULL,
          canonical_key TEXT NOT NULL, source_table TEXT, source_pk TEXT,
          payload_json JSONB NOT NULL DEFAULT '{}'::jsonb, is_active BOOLEAN NOT NULL DEFAULT TRUE,
          UNIQUE (node_type, canonical_key));
        CREATE TABLE oc_graph.kg_edges (kg_edge_id BIGSERIAL PRIMARY KEY, edge_type TEXT NOT NULL,
          from_node_id BIGINT NOT NULL, to_node_id BIGINT NOT NULL, is_active BOOLEAN NOT NULL DEFAULT TRUE);
    """
    with psycopg.connect(os.environ["TEST_DATABASE_URL"], row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(schema_sql)
            ids: dict[str, int] = {}
            for taxon in kg.taxa:
                cur.execute(
                    "INSERT INTO oc_graph.kg_nodes (node_type, canonical_key, source_pk) "
                    "VALUES ('taxon', %s, %s) RETURNING kg_node_id",
                    (f"taxon:{taxon}", taxon),
                )
                ids[taxon] = cur.fetchone()["kg_node_id"]
            for i, (
                taxon,
                edge_type,
                node_type,
                source_table,
                evidence_type,
            ) in enumerate(kg.edges):
                cur.execute(
                    "INSERT INTO oc_graph.kg_nodes (node_type, canonical_key, source_table, payload_json) "
                    "VALUES (%s, %s, %s, %s::jsonb) RETURNING kg_node_id",
                    (
                        node_type,
                        f"{node_type}:{i}",
                        source_table,
                        json.dumps({"evidence_type": evidence_type}),
                    ),
                )
                to_id = cur.fetchone()["kg_node_id"]
                cur.execute(
                    "INSERT INTO oc_graph.kg_edges (edge_type, from_node_id, to_node_id) VALUES (%s, %s, %s)",
                    (edge_type, ids[taxon], to_id),
                )
        conn.commit()

        def db_execute(callback):
            with conn.cursor() as cur:
                result = callback(cur)
            conn.rollback()
            return result

        assert EvidenceCoverageGapSource(db_execute).collect(now=NOW) == source_for(
            kg
        ).collect(now=NOW)


def test_domain_lacking_taxa_pages_read_only_by_keyset_past_covered_taxa():
    kg = sample_kg()
    kg.taxa = [*kg.taxa, "105", "106", "107"]
    source = source_for(kg)
    # 101/102 hold Yong Gee nomenclature evidence; everything else lacks it.
    assert source.domain_lacking_taxa("nomenclature", after_source_pk=None, limit=2) == [
        "103",
        "104",
    ]
    kg.statements.clear()
    assert source.domain_lacking_taxa(
        "nomenclature", after_source_pk="104", limit=10
    ) == ["105", "106", "107"]
    assert kg.statements[0] == "SET TRANSACTION READ ONLY"
    assert kg.statements[1] == f"SET LOCAL statement_timeout = '{ecg.STATEMENT_TIMEOUT}'"
    assert kg.statements[2] == ecg.SQL_DOMAIN_LACKING_PAGE
    assert len(kg.statements) == 3
    # The same lacking-taxa predicate as the gap examples, plus the keyset bound.
    sql = ecg.SQL_DOMAIN_LACKING_PAGE
    assert ecg._COVERED_TAXA in sql and ecg._TAXON in sql
    assert sql.index("t.source_pk > %s") < sql.index("ORDER BY t.source_pk LIMIT %s")
    # Literature counts its relation edge: 103 is covered there.
    assert "103" not in source.domain_lacking_taxa(
        "literature", after_source_pk=None, limit=10
    )


def test_domain_lacking_taxa_param_order_and_limit_clamp():
    calls: list[tuple[str, tuple]] = []

    class Cursor:
        def execute(self, sql, params=()):
            calls.append((sql, params))

        def fetchall(self):
            return [{"source_pk": "10001"}, {"source_pk": None}]

    source = EvidenceCoverageGapSource(lambda callback: callback(Cursor()))
    assert source.domain_lacking_taxa(
        "literature", after_source_pk="10000", limit=10_000
    ) == ["10001"]
    sql, params = calls[-1]
    assert sql == ecg.SQL_DOMAIN_LACKING_PAGE
    literature = next(d for d in ecg.EVIDENCE_DOMAINS if d.name == "literature")
    assert params == (
        list(literature.evidence_types),
        ["documented_by"],
        "10000",
        ecg.MAX_LACKING_PAGE,
    )
    source.domain_lacking_taxa("literature", after_source_pk=None, limit=0)
    assert calls[-1][1][2:] == ("", 1)


def test_domain_lacking_taxa_never_pages_locality_gated_and_fails_closed():
    kg = sample_kg()
    source = source_for(kg)
    assert source.domain_lacking_taxa("distribution", after_source_pk=None, limit=5) == []
    assert kg.statements == []  # no query at all for a locality-gated domain
    with pytest.raises(ValueError, match="unknown evidence domain"):
        source.domain_lacking_taxa("habitat", after_source_pk=None, limit=5)

    def broken(_callback):
        raise RuntimeError("connection reset")

    with pytest.raises(EvidenceCoverageUnavailable, match="read failed"):
        EvidenceCoverageGapSource(broken).domain_lacking_taxa(
            "nomenclature", after_source_pk="1", limit=5
        )
    with pytest.raises(EvidenceCoverageUnavailable, match="DATABASE_URL"):
        EvidenceCoverageGapSource(
            None, unavailable_reason="DATABASE_URL is not configured"
        ).domain_lacking_taxa("nomenclature", after_source_pk="1", limit=5)
    with pytest.raises(EvidenceCoverageUnavailable, match="no knowledge-graph"):
        EvidenceCoverageGapSource(lambda cb: cb(None)).domain_lacking_taxa(
            "nomenclature", after_source_pk="1", limit=5
        )

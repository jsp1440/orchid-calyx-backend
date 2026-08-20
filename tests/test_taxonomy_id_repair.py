"""Regression tests for the pollinator/mycorrhiza taxonomy-id repair package.

Pins the exact shape DATA-INTEGRATION-REPAIR-001 (docs/DATA-INTEGRATION-REPAIR-001.md)
and PR #1020 documented: pollinator edges are 23 of 23 already populated and
correct against ``public.orchid_taxonomy``, and mycorrhiza associations are 2
of 462 populated with the remaining 460 resolvable by a case-folded scientific
name join. Also covers ambiguity, invalid names, idempotency, wrong-endpoint
protection, and zero writes in dry-run mode.
"""

from __future__ import annotations

import re

import pytest

from app.readiness import taxonomy_id_repair as tir


class FakeCursor:
    """A minimal in-memory stand-in for a psycopg cursor.

    ``total_rows``/``populated_count``/``null_rows`` describe one target
    table's mutable state; ``taxonomy`` is the fixed content of
    ``public.orchid_taxonomy`` for this test. A successful ``UPDATE`` removes
    the row from ``null_rows`` and increments ``populated_count``, so a second
    measurement against the same cursor observes the post-write state -- this
    is what the idempotency tests rely on.
    """

    def __init__(self, schema, total_rows=None, populated_count=None, null_rows=None, taxonomy=None):
        self.schema = schema
        self.total_rows = total_rows or {}
        self.populated_count = populated_count or {}
        self.null_rows = {k: list(v) for k, v in (null_rows or {}).items()}
        self.taxonomy = list(taxonomy or [])
        self.writes = []
        self.rowcount = 0
        self._result = None
        self._many = []

    def execute(self, sql, params=()):
        flat = " ".join(sql.split())
        upper = flat.upper()

        if upper.startswith("UPDATE"):
            self.writes.append((flat, params))
            table = re.search(r"UPDATE (\S+)", flat).group(1)
            resolved_id, row_pk = params
            rows = self.null_rows.get(table, [])
            match = next((r for r in rows if r[0] == row_pk), None)
            if match:
                self.null_rows[table] = [r for r in rows if r[0] != row_pk]
                self.populated_count[table] = self.populated_count.get(table, 0) + 1
                self.rowcount = 1
            else:
                self.rowcount = 0
            return

        if "TO_REGCLASS(%S) IS NOT NULL" in upper:
            self._result = (params[0] in self.schema,)
        elif "INFORMATION_SCHEMA.COLUMNS" in upper:
            schema, table = params
            self._many = [(c,) for c in self.schema.get(f"{schema}.{table}", set())]
        elif "PUBLIC.ORCHID_TAXONOMY" in upper and "LIKE LOWER(%S)" in upper:
            prefix = params[0]
            needle = prefix[:-1].lower() if prefix.endswith("%") else prefix.lower()
            self._many = [(tid, name) for tid, name in self.taxonomy if name.lower().startswith(needle)]
        elif "IS NULL AND" in upper:
            table = re.search(r"FROM (\S+) WHERE", flat).group(1)
            self._many = list(self.null_rows.get(table, []))
        elif flat.startswith("SELECT COUNT(*) FROM ") and "IS NOT NULL" in upper:
            table = re.search(r"FROM (\S+) WHERE", flat).group(1)
            self._result = (self.populated_count.get(table, 0),)
        elif flat.startswith("SELECT COUNT(*) FROM "):
            table = flat[len("SELECT COUNT(*) FROM ") :].strip()
            self._result = (self.total_rows.get(table, 0),)
        else:  # pragma: no cover - a query this fake was not taught
            raise AssertionError(f"Unexpected SQL: {flat}")

    def fetchone(self):
        return self._result

    def fetchall(self):
        return self._many


POLLINATOR_TARGET = next(t for t in tir.REPAIR_TARGETS if t.domain == "pollinators")
MYCORRHIZA_TARGET = next(t for t in tir.REPAIR_TARGETS if t.domain == "mycorrhiza")

POLLINATOR_SCHEMA = {
    POLLINATOR_TARGET.table: {"edge_id", "orchid_taxonomy_id", "orchid_scientific_name", "partner_taxon_id"},
    tir.CANONICAL_TAXONOMY_TABLE: {"id", "scientific_name"},
}
MYCORRHIZA_SCHEMA = {
    MYCORRHIZA_TARGET.table: {"association_id", "orchid_taxonomy_id", "orchid_scientific_name", "fungal_taxon_id"},
    tir.CANONICAL_TAXONOMY_TABLE: {"id", "scientific_name"},
}


def test_pollinators_documented_23_of_23_already_populated_needs_no_repair():
    """PR #1020: 23 of 23 orchid_taxonomy_id values already resolve correctly."""
    cur = FakeCursor(
        POLLINATOR_SCHEMA,
        total_rows={POLLINATOR_TARGET.table: 23},
        populated_count={POLLINATOR_TARGET.table: 23},
        null_rows={POLLINATOR_TARGET.table: []},
    )
    measurement = tir.measure_repair_candidates(cur, POLLINATOR_TARGET)
    assert measurement["state"] == "measured"
    assert measurement["before"] == {
        "total_rows": 23,
        "orchid_taxonomy_id_populated": 23,
        "orchid_taxonomy_id_null": 0,
    }
    assert measurement["resolved_candidates"] == []
    assert measurement["ambiguous_queue"] == []
    assert measurement["unresolved_queue"] == []

    plan = tir.build_repair_plan(measurement)
    assert plan["actions"] == []
    sql_text = tir.generate_repair_sql(POLLINATOR_TARGET, plan)
    assert "nothing to do" in sql_text
    assert "UPDATE" not in sql_text
    assert "partner_taxon_id" not in sql_text


def test_mycorrhiza_documented_462_rows_2_populated_460_resolve_by_name():
    """DATA-INTEGRATION-REPAIR-001: 462 rows, 2 carry orchid_taxonomy_id, the
    other 460 carry a resolvable orchid_scientific_name."""
    def _letters(n: int) -> str:
        # A digit-free unique suffix -- the resolver's regex requires letters
        # only, so a numeric suffix like "Genus1" would never match.
        s = ""
        n += 1
        while n > 0:
            n, r = divmod(n - 1, 26)
            s = chr(97 + r) + s
        return s

    null_rows = [(i, f"Genus{_letters(i)} species{_letters(i)}") for i in range(1, 461)]
    taxonomy = [(1000 + i, f"Genus{_letters(i)} species{_letters(i)}") for i in range(1, 461)]
    cur = FakeCursor(
        MYCORRHIZA_SCHEMA,
        total_rows={MYCORRHIZA_TARGET.table: 462},
        populated_count={MYCORRHIZA_TARGET.table: 2},
        null_rows={MYCORRHIZA_TARGET.table: null_rows},
        taxonomy=taxonomy,
    )
    measurement = tir.measure_repair_candidates(cur, MYCORRHIZA_TARGET)
    assert measurement["before"] == {
        "total_rows": 462,
        "orchid_taxonomy_id_populated": 2,
        "orchid_taxonomy_id_null": 460,
    }
    assert len(measurement["resolved_candidates"]) == 460
    assert measurement["ambiguous_queue"] == []
    assert measurement["unresolved_queue"] == []
    assert measurement["after_dry_run_projection"] == {
        "orchid_taxonomy_id_populated": 462,
        "orchid_taxonomy_id_null": 0,
    }
    assert measurement["partner_id_column_never_read_or_written"] == "fungal_taxon_id"

    plan = tir.build_repair_plan(measurement)
    assert len(plan["actions"]) == 460
    # Deterministic ordering: repeated plan construction from the same
    # measurement always yields the same order.
    plan_again = tir.build_repair_plan(measurement)
    assert plan["actions"] == plan_again["actions"]

    sql_text = tir.generate_repair_sql(MYCORRHIZA_TARGET, plan)
    assert "fungal_taxon_id" not in sql_text
    assert "orchid_taxonomy_id IS NULL" in sql_text


def test_ambiguous_name_is_never_resolved_automatically():
    """Fail closed: two taxonomy rows share a normalized identity and neither
    exactly matches the submitted text, so the row must go to the ambiguous
    queue rather than being guessed."""
    cur = FakeCursor(
        MYCORRHIZA_SCHEMA,
        total_rows={MYCORRHIZA_TARGET.table: 1},
        populated_count={MYCORRHIZA_TARGET.table: 0},
        null_rows={MYCORRHIZA_TARGET.table: [(1, "Homonymia orchidacea")]},
        taxonomy=[
            (10, "Homonymia orchidacea Author1"),
            (11, "Homonymia orchidacea Author2"),
        ],
    )
    measurement = tir.measure_repair_candidates(cur, MYCORRHIZA_TARGET)
    assert measurement["resolved_candidates"] == []
    assert len(measurement["ambiguous_queue"]) == 1
    assert measurement["ambiguous_queue"][0]["status"] == "ambiguous"

    plan = tir.build_repair_plan(measurement)
    assert plan["actions"] == []


def test_ambiguous_name_disambiguated_by_exact_text_match_still_resolves():
    """One of two homonymous rows matches the submitted text exactly -- this
    is the one case ambiguity resolves automatically, mirroring
    CanonicalTaxonTargetResolver."""
    cur = FakeCursor(
        MYCORRHIZA_SCHEMA,
        total_rows={MYCORRHIZA_TARGET.table: 1},
        populated_count={MYCORRHIZA_TARGET.table: 0},
        null_rows={MYCORRHIZA_TARGET.table: [(1, "Homonymia orchidacea")]},
        taxonomy=[
            (10, "Homonymia orchidacea"),
            (11, "Homonymia orchidacea Author2"),
        ],
    )
    measurement = tir.measure_repair_candidates(cur, MYCORRHIZA_TARGET)
    assert len(measurement["resolved_candidates"]) == 1
    assert measurement["resolved_candidates"][0]["resolved_orchid_taxonomy_id"] == 10
    assert measurement["ambiguous_queue"] == []


def test_unresolved_name_with_no_taxonomy_match():
    cur = FakeCursor(
        MYCORRHIZA_SCHEMA,
        total_rows={MYCORRHIZA_TARGET.table: 1},
        populated_count={MYCORRHIZA_TARGET.table: 0},
        null_rows={MYCORRHIZA_TARGET.table: [(1, "Nonexistens fictus")]},
        taxonomy=[(10, "Cattleya labiata")],
    )
    measurement = tir.measure_repair_candidates(cur, MYCORRHIZA_TARGET)
    assert measurement["resolved_candidates"] == []
    assert len(measurement["unresolved_queue"]) == 1
    assert measurement["unresolved_queue"][0]["status"] == "unresolved"


def test_invalid_unparseable_name_is_never_resolved():
    cur = FakeCursor(
        MYCORRHIZA_SCHEMA,
        total_rows={MYCORRHIZA_TARGET.table: 1},
        populated_count={MYCORRHIZA_TARGET.table: 0},
        null_rows={MYCORRHIZA_TARGET.table: [(1, "unknown")]},
        taxonomy=[],
    )
    measurement = tir.measure_repair_candidates(cur, MYCORRHIZA_TARGET)
    assert measurement["resolved_candidates"] == []
    assert len(measurement["invalid_queue"]) == 1
    assert measurement["invalid_queue"][0]["status"] == "invalid"


def test_wrong_endpoint_is_refused_before_any_query_runs():
    """The mycorrhiza endpoint response cache is deliberately not a repair
    target. Requesting it must fail before a single query executes."""
    wrong_target = tir.RepairTarget(
        domain="mycorrhiza",
        table="oc_mycorrhiza.species_mycorrhiza_unified_endpoint_cache",
        primary_key="id",
        orchid_taxonomy_id_column="orchid_taxonomy_id",
        orchid_name_column="orchid_scientific_name",
        partner_id_column="fungal_taxon_id",
    )

    class RaisingCursor:
        def execute(self, *a, **k):  # pragma: no cover - must never be called
            raise AssertionError("no query should run for an unknown target")

    with pytest.raises(ValueError, match="not one of the two documented repair targets"):
        tir.measure_repair_candidates(RaisingCursor(), wrong_target)


def test_wrong_endpoint_refused_at_sql_generation_too():
    wrong_target = tir.RepairTarget(
        domain="pollinators",
        table="public.pollinator_relationships",
        primary_key="id",
        orchid_taxonomy_id_column="orchid_taxonomy_id",
        orchid_name_column="orchid_scientific_name",
        partner_id_column="partner_taxon_id",
    )
    with pytest.raises(ValueError):
        tir.generate_repair_sql(wrong_target, {"actions": []})


def test_partner_column_never_appears_in_generated_sql_for_either_target():
    for target, other_col in (
        (POLLINATOR_TARGET, "partner_taxon_id"),
        (MYCORRHIZA_TARGET, "fungal_taxon_id"),
    ):
        plan = {
            "table": target.table,
            "actions": [
                {
                    "row_pk": 1,
                    "resolved_orchid_taxonomy_id": 99,
                    "orchid_scientific_name": "Cattleya labiata",
                    "join_method": "canonical_name_normalized_exact",
                }
            ],
        }
        sql_text = tir.generate_repair_sql(target, plan)
        assert other_col not in sql_text
        assert target.orchid_taxonomy_id_column in sql_text


def test_dry_run_apply_issues_zero_writes():
    plan = {
        "table": MYCORRHIZA_TARGET.table,
        "actions": [
            {
                "row_pk": 1,
                "resolved_orchid_taxonomy_id": 99,
                "orchid_scientific_name": "Cattleya labiata",
                "join_method": "canonical_name_normalized_exact",
            }
        ],
    }

    class RaisingOnWriteCursor:
        def execute(self, sql, params=()):  # pragma: no cover - must never run
            raise AssertionError("dry-run apply must never call execute()")

    result = tir.apply_repair_plan(RaisingOnWriteCursor(), MYCORRHIZA_TARGET, plan, execute=False)
    assert result == {
        "status": "dry_run",
        "table": MYCORRHIZA_TARGET.table,
        "would_update": 1,
    }


def test_execute_only_writes_resolved_rows_never_ambiguous_or_unresolved():
    cur = FakeCursor(
        MYCORRHIZA_SCHEMA,
        total_rows={MYCORRHIZA_TARGET.table: 3},
        populated_count={MYCORRHIZA_TARGET.table: 0},
        null_rows={
            MYCORRHIZA_TARGET.table: [
                (1, "Cattleya labiata"),
                (2, "Homonymia orchidacea"),
                (3, "Nonexistens fictus"),
            ]
        },
        taxonomy=[
            (10, "Cattleya labiata"),
            (11, "Homonymia orchidacea Author1"),
            (12, "Homonymia orchidacea Author2"),
        ],
    )
    measurement = tir.measure_repair_candidates(cur, MYCORRHIZA_TARGET)
    plan = tir.build_repair_plan(measurement)
    assert len(plan["actions"]) == 1  # only row 1 resolves; 2 is ambiguous, 3 unresolved

    result = tir.apply_repair_plan(cur, MYCORRHIZA_TARGET, plan, execute=True)
    assert result["status"] == "executed"
    assert result["planned"] == 1
    assert result["rows_updated"] == 1
    # Rows 2 and 3 are untouched -- still null, never written.
    remaining_pks = {r[0] for r in cur.null_rows[MYCORRHIZA_TARGET.table]}
    assert remaining_pks == {2, 3}
    assert cur.populated_count[MYCORRHIZA_TARGET.table] == 1


def test_idempotent_second_run_after_apply_finds_nothing_left():
    cur = FakeCursor(
        MYCORRHIZA_SCHEMA,
        total_rows={MYCORRHIZA_TARGET.table: 1},
        populated_count={MYCORRHIZA_TARGET.table: 0},
        null_rows={MYCORRHIZA_TARGET.table: [(1, "Cattleya labiata")]},
        taxonomy=[(10, "Cattleya labiata")],
    )
    first = tir.measure_repair_candidates(cur, MYCORRHIZA_TARGET)
    plan = tir.build_repair_plan(first)
    tir.apply_repair_plan(cur, MYCORRHIZA_TARGET, plan, execute=True)

    second = tir.measure_repair_candidates(cur, MYCORRHIZA_TARGET)
    assert second["before"] == {
        "total_rows": 1,
        "orchid_taxonomy_id_populated": 1,
        "orchid_taxonomy_id_null": 0,
    }
    assert second["resolved_candidates"] == []
    second_plan = tir.build_repair_plan(second)
    assert second_plan["actions"] == []
    # Re-running the second (empty) plan is a safe no-op.
    second_result = tir.apply_repair_plan(cur, MYCORRHIZA_TARGET, second_plan, execute=True)
    assert second_result == {
        "status": "executed",
        "table": MYCORRHIZA_TARGET.table,
        "planned": 0,
        "rows_updated": 0,
    }


def test_missing_table_is_unavailable_not_a_silent_zero():
    cur = FakeCursor({tir.CANONICAL_TAXONOMY_TABLE: {"id", "scientific_name"}})
    measurement = tir.measure_repair_candidates(cur, MYCORRHIZA_TARGET)
    assert measurement["state"] == "unavailable"
    assert "does not exist" in measurement["reason"]


def test_missing_canonical_taxonomy_table_is_unavailable():
    cur = FakeCursor({MYCORRHIZA_TARGET.table: {"association_id", "orchid_taxonomy_id", "orchid_scientific_name"}})
    measurement = tir.measure_repair_candidates(cur, MYCORRHIZA_TARGET)
    assert measurement["state"] == "unavailable"
    assert tir.CANONICAL_TAXONOMY_TABLE in measurement["reason"]


def test_missing_required_column_is_unavailable():
    schema = {
        MYCORRHIZA_TARGET.table: {"association_id", "orchid_scientific_name"},  # no orchid_taxonomy_id
        tir.CANONICAL_TAXONOMY_TABLE: {"id", "scientific_name"},
    }
    cur = FakeCursor(schema, total_rows={MYCORRHIZA_TARGET.table: 5})
    measurement = tir.measure_repair_candidates(cur, MYCORRHIZA_TARGET)
    assert measurement["state"] == "unavailable"
    assert "missing required column" in measurement["reason"]


def test_normalization_matches_taxon_target_resolver_policy():
    """This module deliberately keeps a local copy of the normalization regex
    used by app.trait_genomics.taxon_target_resolver rather than importing it
    (to avoid that resolver's psycopg/pydantic import chain). Pin that the
    policy -- not just the regex text -- produces the same normalized form for
    a representative set of names, so the two cannot silently drift apart."""
    cases = [
        ("cattleya   labiata", "Cattleya labiata"),
        ("Cattleya_labiata", "Cattleya labiata"),
        ("PHALAENOPSIS amabilis", "Phalaenopsis amabilis"),
        ("Dendrobium nobile var. alba", "Dendrobium nobile var. alba"),
        ("not a name", None),
    ]
    for raw, expected in cases:
        assert tir._normalize_scientific_name(raw) == expected

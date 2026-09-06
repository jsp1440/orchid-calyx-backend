"""Regression tests for the pollinator/mycorrhiza taxonomy-id repair package.

Pins the exact shape DATA-INTEGRATION-REPAIR-001 (docs/DATA-INTEGRATION-REPAIR-001.md)
and PR #1020 documented: pollinator edges are 23 of 23 already populated and
correct against ``public.orchid_taxonomy``, and mycorrhiza associations are 2
of 462 populated with the remaining 460 resolvable by a case-folded scientific
name join. Also covers ambiguity, invalid names, idempotency, wrong-endpoint
protection, and zero writes in dry-run mode.
"""

from __future__ import annotations

import csv
import io
import os
import re
import tempfile
import uuid

import pytest

import scripts.repair_pollinator_mycorrhiza_taxonomy_ids as repair_cli
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

    def __init__(
        self,
        schema,
        total_rows=None,
        populated_count=None,
        null_rows=None,
        taxonomy=None,
        column_types=None,
    ):
        self.schema = schema
        self.total_rows = total_rows or {}
        self.populated_count = populated_count or {}
        self.null_rows = {k: list(v) for k, v in (null_rows or {}).items()}
        self.taxonomy = list(taxonomy or [])
        # udt_name per "schema.table" -> {column: type}. Absent columns report
        # an empty type, which is how a real catalog read behaves for a column
        # this fake was not told about.
        self.column_types = column_types or {}
        self.writes = []
        self.taxonomy_lookups = 0
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
        elif "INFORMATION_SCHEMA.COLUMNS" in upper and "UDT_NAME" in upper:
            schema, table = params
            qualified = f"{schema}.{table}"
            types = self.column_types.get(qualified, {})
            self._many = [
                (c, types.get(c, "")) for c in sorted(self.schema.get(qualified, set()))
            ]
        elif "INFORMATION_SCHEMA.COLUMNS" in upper:
            schema, table = params
            self._many = [(c,) for c in self.schema.get(f"{schema}.{table}", set())]
        elif "PUBLIC.ORCHID_TAXONOMY" in upper and "LIKE LOWER(%S)" in upper:
            self.taxonomy_lookups += 1
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


# --- generated SQL renders real production values, not Python reprs ---------

MYCORRHIZA_UUID_TYPES = {
    MYCORRHIZA_TARGET.table: {"association_id": "uuid", "orchid_taxonomy_id": "int8"}
}


def _uuid_plan():
    row_pk = uuid.UUID("12345678-1234-5678-1234-567812345678")
    return {
        "table": MYCORRHIZA_TARGET.table,
        "column_types": {"association_id": "uuid", "orchid_taxonomy_id": "int8"},
        "actions": [
            {
                "row_pk": row_pk,
                "resolved_orchid_taxonomy_id": 4242,
                "orchid_scientific_name": "Cattleya labiata",
                "join_method": tir.MATCH_METHOD_EXACT,
                "canonical_source": tir.CANONICAL_TAXONOMY_TABLE,
                "resolved_from_candidates": [4242],
            }
        ],
    }


def test_generated_sql_renders_uuid_primary_keys_as_sql_not_python_repr():
    """A uuid.UUID rendered with repr() becomes ``UUID('...')``, which is not
    SQL. Every value must come out as a quoted literal cast to the column's
    catalog type."""
    sql_text = tir.generate_repair_sql(MYCORRHIZA_TARGET, _uuid_plan())
    assert "UUID(" not in sql_text
    assert "'12345678-1234-5678-1234-567812345678'" in sql_text
    assert "v.row_pk::uuid" in sql_text
    assert "v.resolved_orchid_taxonomy_id::int8" in sql_text
    assert "WARNING" not in sql_text


def test_generated_sql_escapes_quotes_instead_of_switching_quote_style():
    """repr() of a value containing an apostrophe yields a double-quoted
    string, which Postgres reads as an identifier. Doubling the apostrophe is
    the only correct rendering."""
    assert tir._sql_text_literal("O'Brien") == "'O''Brien'"
    assert tir._sql_text_literal(7) == "'7'"
    assert tir._sql_text_literal(uuid.UUID(int=1)) == "'00000000-0000-0000-0000-000000000001'"


def test_sql_literal_refuses_null_and_nul_byte():
    with pytest.raises(ValueError, match="NULL"):
        tir._sql_text_literal(None)
    with pytest.raises(ValueError, match="NUL byte"):
        tir._sql_text_literal("bad\x00value")


def test_generated_sql_warns_loudly_when_column_types_are_unknown():
    """Without a cast, an unknown-typed VALUES literal is text and joining it
    against a uuid key fails. Emit the SQL, but never silently."""
    plan = _uuid_plan()
    plan["column_types"] = {}
    sql_text = tir.generate_repair_sql(MYCORRHIZA_TARGET, plan)
    assert "WARNING" in sql_text
    assert "::uuid" not in sql_text


def test_measurement_reports_catalog_column_types_for_the_cast():
    cur = FakeCursor(
        MYCORRHIZA_SCHEMA,
        total_rows={MYCORRHIZA_TARGET.table: 1},
        populated_count={MYCORRHIZA_TARGET.table: 0},
        null_rows={MYCORRHIZA_TARGET.table: [(1, "Cattleya labiata")]},
        taxonomy=[(10, "Cattleya labiata")],
        column_types=MYCORRHIZA_UUID_TYPES,
    )
    measurement = tir.measure_repair_candidates(cur, MYCORRHIZA_TARGET)
    assert measurement["column_types"] == {
        "association_id": "uuid",
        "orchid_taxonomy_id": "int8",
    }
    sql_text = tir.generate_repair_sql(MYCORRHIZA_TARGET, tir.build_repair_plan(measurement))
    assert "v.row_pk::uuid" in sql_text


def test_cast_suffix_refuses_anything_that_is_not_a_plain_type_name():
    assert tir._cast_suffix("uuid") == "::uuid"
    assert tir._cast_suffix("int8") == "::int8"
    assert tir._cast_suffix("") == ""
    assert tir._cast_suffix(None) == ""
    assert tir._cast_suffix("text; DROP TABLE x") == ""
    assert tir._cast_suffix("_text") == ""  # array type, not handled


# --- provenance-preserving mapping output ----------------------------------


def _mixed_outcome_cursor():
    return FakeCursor(
        MYCORRHIZA_SCHEMA,
        total_rows={MYCORRHIZA_TARGET.table: 4},
        populated_count={MYCORRHIZA_TARGET.table: 0},
        null_rows={
            MYCORRHIZA_TARGET.table: [
                (1, "Cattleya labiata"),
                (2, "Homonymia orchidacea"),
                (3, "Nonexistens fictus"),
                (4, "unknown"),
            ]
        },
        taxonomy=[
            (10, "Cattleya labiata"),
            (11, "Homonymia orchidacea Author1"),
            (12, "Homonymia orchidacea Author2"),
        ],
        column_types=MYCORRHIZA_UUID_TYPES,
    )


def test_provenance_mapping_accounts_for_every_candidate_row():
    """The mapping is a complete account of the measurement -- the rows that
    fail closed appear alongside the writable ones, each with its reason."""
    cur = _mixed_outcome_cursor()
    measurement = tir.measure_repair_candidates(cur, MYCORRHIZA_TARGET)
    mapping = tir.build_provenance_mapping(MYCORRHIZA_TARGET, measurement)

    assert [r["source_row_pk"] for r in mapping] == [1, 2, 3, 4]
    by_pk = {r["source_row_pk"]: r for r in mapping}
    assert by_pk[1]["resolution_status"] == "resolved"
    assert by_pk[1]["action"] == "write_candidate"
    assert by_pk[1]["resolved_orchid_taxonomy_id"] == 10
    assert by_pk[1]["match_method"] == tir.MATCH_METHOD_EXACT
    assert by_pk[2]["resolution_status"] == "ambiguous"
    assert by_pk[2]["action"] == "human_review"
    assert by_pk[2]["candidate_ids"] == "11;12"
    assert by_pk[2]["resolved_orchid_taxonomy_id"] is None
    assert by_pk[3]["resolution_status"] == "unresolved"
    assert by_pk[4]["resolution_status"] == "invalid"

    for record in mapping:
        assert record["repair_package"] == tir.REPAIR_PACKAGE
        assert record["resolution_policy"] == tir.RESOLUTION_POLICY
        assert record["canonical_table"] == tir.CANONICAL_TAXONOMY_TABLE
        assert record["source_table"] == MYCORRHIZA_TARGET.table
        assert record["source_id_column"] == "orchid_taxonomy_id"
        # Every candidate row was NULL before -- a known pre-state, not an
        # unknown one.
        assert record["prior_orchid_taxonomy_id"] is None
        assert record["prior_state"] == "null"
        assert record["reason"]


def test_provenance_mapping_records_that_the_partner_column_is_never_written():
    for target in (POLLINATOR_TARGET, MYCORRHIZA_TARGET):
        schema = POLLINATOR_SCHEMA if target is POLLINATOR_TARGET else MYCORRHIZA_SCHEMA
        cur = FakeCursor(
            schema,
            total_rows={target.table: 1},
            populated_count={target.table: 0},
            null_rows={target.table: [(1, "Cattleya labiata")]},
            taxonomy=[(10, "Cattleya labiata")],
        )
        measurement = tir.measure_repair_candidates(cur, target)
        mapping = tir.build_provenance_mapping(target, measurement)
        assert len(mapping) == 1
        assert mapping[0]["partner_id_column"] == target.partner_id_column
        assert mapping[0]["partner_id_column_written"] is False


def test_provenance_mapping_csv_has_a_stable_header_and_is_deterministic():
    cur = _mixed_outcome_cursor()
    measurement = tir.measure_repair_candidates(cur, MYCORRHIZA_TARGET)
    mapping = tir.build_provenance_mapping(MYCORRHIZA_TARGET, measurement)

    csv_text = tir.mapping_to_csv(mapping)
    assert csv_text == tir.mapping_to_csv(mapping)

    rows = list(csv.DictReader(io.StringIO(csv_text)))
    assert list(rows[0].keys()) == list(tir.MAPPING_FIELDS)
    assert len(rows) == 4
    assert {r["resolution_status"] for r in rows} == {
        "resolved",
        "ambiguous",
        "unresolved",
        "invalid",
    }


def test_provenance_mapping_is_empty_for_an_unavailable_target_not_a_false_zero():
    """An unavailable target yields no mapping rows at all; the measurement
    still reports ``unavailable`` so the caller cannot read the empty artifact
    as 'nothing to repair'."""
    cur = FakeCursor({tir.CANONICAL_TAXONOMY_TABLE: {"id", "scientific_name"}})
    measurement = tir.measure_repair_candidates(cur, MYCORRHIZA_TARGET)
    assert measurement["state"] == "unavailable"
    assert tir.build_provenance_mapping(MYCORRHIZA_TARGET, measurement) == []


def test_provenance_mapping_is_wrong_endpoint_protected():
    wrong_target = tir.RepairTarget(
        domain="mycorrhiza",
        table="oc_mycorrhiza.species_mycorrhiza_unified_endpoint_cache",
        primary_key="id",
        orchid_taxonomy_id_column="orchid_taxonomy_id",
        orchid_name_column="orchid_scientific_name",
        partner_id_column="fungal_taxon_id",
    )
    with pytest.raises(ValueError):
        tir.build_provenance_mapping(wrong_target, {"state": "measured"})


# --- bounded canonical reads ------------------------------------------------


def test_canonical_lookup_runs_once_per_distinct_name_not_once_per_row():
    """462 mycorrhiza rows span 218 taxa (DATA-INTEGRATION-REPAIR-001), and
    this measurement runs against production. Repeated names must not issue
    repeated reads, and the cached outcome must be identical to the
    uncached one."""
    cur = FakeCursor(
        MYCORRHIZA_SCHEMA,
        total_rows={MYCORRHIZA_TARGET.table: 5},
        populated_count={MYCORRHIZA_TARGET.table: 0},
        null_rows={
            MYCORRHIZA_TARGET.table: [
                (1, "Cattleya labiata"),
                (2, "Cattleya labiata"),
                (3, "Cattleya labiata"),
                (4, "Dendrobium nobile"),
                (5, "Dendrobium nobile"),
            ]
        },
        taxonomy=[(10, "Cattleya labiata"), (20, "Dendrobium nobile")],
    )
    measurement = tir.measure_repair_candidates(cur, MYCORRHIZA_TARGET)

    assert cur.taxonomy_lookups == 2  # two distinct names, five rows
    assert measurement["canonical_lookups"] == {
        "null_rows_examined": 5,
        "distinct_names_resolved": 2,
    }
    resolved = {e["row_pk"]: e["resolved_orchid_taxonomy_id"] for e in measurement["resolved_candidates"]}
    assert resolved == {1: 10, 2: 10, 3: 10, 4: 20, 5: 20}
    # Each row carries its own candidate list, not a shared mutable one.
    lists = [e["candidates"] for e in measurement["resolved_candidates"]]
    assert all(a is not b for i, a in enumerate(lists) for b in lists[i + 1 :])


def test_cached_resolution_still_reports_each_row_own_stored_name():
    """The cache is keyed on the whitespace-collapsed name, so two rows whose
    stored text differs only by spacing share an outcome. Provenance must
    still show what each row actually stores."""
    cur = FakeCursor(
        MYCORRHIZA_SCHEMA,
        total_rows={MYCORRHIZA_TARGET.table: 2},
        populated_count={MYCORRHIZA_TARGET.table: 0},
        null_rows={
            MYCORRHIZA_TARGET.table: [
                (1, "Cattleya labiata"),
                (2, "Cattleya   labiata"),
            ]
        },
        taxonomy=[(10, "Cattleya labiata")],
    )
    measurement = tir.measure_repair_candidates(cur, MYCORRHIZA_TARGET)
    assert cur.taxonomy_lookups == 1
    names = {e["row_pk"]: e["orchid_scientific_name"] for e in measurement["resolved_candidates"]}
    assert names == {1: "Cattleya labiata", 2: "Cattleya   labiata"}


# --- write-boundary provenance verification ---------------------------------


class RaisingOnWriteCursor:
    def execute(self, sql, params=()):  # pragma: no cover - must never run
        raise AssertionError("no write should be attempted for an unverifiable plan")


def test_execute_refuses_a_plan_whose_id_is_not_a_canonical_candidate():
    """A substituted id -- a fungal/partner taxon id in particular -- must not
    reach the orchid column even if a plan claims it resolved."""
    plan = _uuid_plan()
    plan["actions"][0]["resolved_orchid_taxonomy_id"] = 999999  # not in candidates
    with pytest.raises(ValueError, match="not among the canonical candidates"):
        tir.apply_repair_plan(RaisingOnWriteCursor(), MYCORRHIZA_TARGET, plan, execute=True)


def test_execute_refuses_a_plan_carrying_no_canonical_provenance():
    plan = _uuid_plan()
    del plan["actions"][0]["canonical_source"]
    with pytest.raises(ValueError, match="canonical source"):
        tir.apply_repair_plan(RaisingOnWriteCursor(), MYCORRHIZA_TARGET, plan, execute=True)


def test_execute_refuses_a_plan_sourced_from_a_different_registry():
    """oc_taxonomy.taxa is a different registry these ids were never meant to
    resolve into (DATA-INTEGRATION-REPAIR-001). A plan claiming it as the
    source is refused."""
    plan = _uuid_plan()
    plan["actions"][0]["canonical_source"] = "oc_taxonomy.taxa"
    with pytest.raises(ValueError, match="canonical source"):
        tir.apply_repair_plan(RaisingOnWriteCursor(), MYCORRHIZA_TARGET, plan, execute=True)


def test_build_repair_plan_produces_a_plan_that_passes_verification():
    cur = _mixed_outcome_cursor()
    measurement = tir.measure_repair_candidates(cur, MYCORRHIZA_TARGET)
    plan = tir.build_repair_plan(measurement)
    assert len(plan["actions"]) == 1
    tir.verify_plan_provenance(MYCORRHIZA_TARGET, plan)  # must not raise
    assert plan["actions"][0]["canonical_source"] == tir.CANONICAL_TAXONOMY_TABLE
    assert plan["actions"][0]["resolved_from_candidates"] == [10]


def test_dry_run_never_verifies_or_writes_even_for_a_tampered_plan():
    """Dry run reports; it does not write, and it does not need to reject."""
    plan = _uuid_plan()
    plan["actions"][0]["resolved_orchid_taxonomy_id"] = 999999
    result = tir.apply_repair_plan(RaisingOnWriteCursor(), MYCORRHIZA_TARGET, plan, execute=False)
    assert result == {
        "status": "dry_run",
        "table": MYCORRHIZA_TARGET.table,
        "would_update": 1,
    }


# --- CLI artifact emission (no database involved) ---------------------------


def test_cli_writes_one_mapping_and_one_sql_artifact_per_target():
    cur = _mixed_outcome_cursor()
    measurement = tir.measure_repair_candidates(cur, MYCORRHIZA_TARGET)
    plan = tir.build_repair_plan(measurement)
    sql_text = tir.generate_repair_sql(MYCORRHIZA_TARGET, plan)

    with tempfile.TemporaryDirectory() as tmp:
        artifacts = repair_cli.write_artifacts(
            MYCORRHIZA_TARGET,
            measurement,
            plan,
            sql_text,
            mapping_out=os.path.join(tmp, "mapping.csv"),
            sql_out=os.path.join(tmp, "repair.sql"),
        )
        assert artifacts["mapping_csv"].endswith("mapping.mycorrhiza.csv")
        assert artifacts["repair_sql"].endswith("repair.mycorrhiza.sql")
        assert artifacts["mapping_rows"] == 4  # every candidate row, not just the writable one
        assert artifacts["planned_updates"] == 1

        with open(artifacts["mapping_csv"], encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 4
        assert {r["resolution_status"] for r in rows} == {
            "resolved",
            "ambiguous",
            "unresolved",
            "invalid",
        }
        with open(artifacts["repair_sql"], encoding="utf-8") as fh:
            written_sql = fh.read()
        assert written_sql == sql_text
        assert "fungal_taxon_id" not in written_sql


def test_cli_artifact_paths_do_not_collide_between_the_two_targets():
    assert repair_cli._artifact_path("out/mapping.csv", "pollinators") == (
        "out/mapping.pollinators.csv"
    )
    assert repair_cli._artifact_path("out/mapping.csv", "mycorrhiza") == (
        "out/mapping.mycorrhiza.csv"
    )


def test_cli_execute_confirmation_token_is_required_and_exact():
    """The owner gate is a fixed token, not a boolean flag -- --execute alone
    can never write."""
    assert repair_cli.EXECUTION_CONFIRMATION == (
        "REPAIR-POLLINATOR-MYCORRHIZA-TAXONOMY-IDS-CONFIRMED"
    )

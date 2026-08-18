"""Tests for the read-only relationship measurement paths.

These pin one invariant above all others: a discovery failure must never be
reported as absence. The audit may say "present", "absent", or "unavailable",
and only a join that actually ran may produce the middle one.
"""

import pytest

from app.readiness import relationship_measurement as rm


class FakeCursor:
    """Answers catalog and count queries against an in-memory schema.

    ``schema`` maps a fully-qualified relation name to its column set. ``rows``
    maps a relation to its row count, and ``joins`` supplies the answer for the
    join-shaped counts so a test can describe linkage without a real planner.
    """

    def __init__(self, schema, rows=None, joins=None):
        self.schema = schema
        self.rows = rows or {}
        self.joins = joins or {}
        self._result = None
        self._many = []

    def execute(self, sql, params=()):
        flat = " ".join(sql.split())
        if "to_regclass(%s) IS NOT NULL" in flat:
            self._result = (params[0] in self.schema,)
        elif "FROM pg_class" in flat:
            name = params[0]
            self._result = ("r", float(self.rows.get(name, 0))) if name in self.schema else None
        elif "information_schema.columns" in flat:
            schema, table = params[0], params[1]
            self._many = [(c,) for c in self.schema.get(f"{schema}.{table}", set())]
        elif flat.startswith("SELECT COUNT(*) FROM ") and " JOIN " in flat:
            self._result = (self.joins.get("matched", 0),)
        elif flat.startswith("SELECT COUNT(DISTINCT"):
            self._result = (self.joins.get("taxa_reached", 0),)
        elif flat.startswith("SELECT COUNT(*) FROM ") and " WHERE " in flat:
            self._result = (self.joins.get("carrying", 0),)
        elif flat.startswith("SELECT COUNT(*) FROM "):
            table = flat[len("SELECT COUNT(*) FROM ") :].strip()
            self._result = (self.rows.get(table, 0),)
        else:  # pragma: no cover - a query the fake was not taught
            raise AssertionError(f"Unexpected SQL: {flat}")

    def fetchone(self):
        return self._result

    def fetchall(self):
        return self._many


TAX = {"oc_taxonomy.taxa": {"taxon_id", "scientific_name"}}


def measure(cur, **kw):
    kw.setdefault("name", "taxonomy_to_test")
    kw.setdefault("taxonomy_tables", rm.TAXONOMY_TABLES)
    kw.setdefault("taxonomy_keys", rm.TAXONOMY_KEYS)
    kw.setdefault("taxonomy_name_columns", rm.TAXONOMY_NAME_COLUMNS)
    kw.setdefault("object_taxon_keys", rm.OBJECT_TAXON_KEYS)
    kw.setdefault("object_name_columns", rm.OBJECT_NAME_COLUMNS)
    return rm.measure_link_relationship(cur, **kw)


def test_id_join_with_matches_is_present():
    cur = FakeCursor(
        {**TAX, "oc_conservation.conservation_records": {"taxon_id", "iucn_category"}},
        rows={"oc_taxonomy.taxa": 31840, "oc_conservation.conservation_records": 500},
        joins={"carrying": 500, "matched": 480, "taxa_reached": 470},
    )
    result = measure(cur, object_tables=("oc_conservation.conservation_records",))
    assert result["state"] == "present"
    assert result["measurement"] == "relational_linkage_by_id"
    assert result["rows_matching_taxonomy"] == 480
    assert result["broken_taxonomy_targets"] == 20
    assert result["taxa_reached"] == 470


def test_join_that_ran_and_matched_nothing_is_absent():
    """The only route to 'absent' -- a real join returning zero."""
    cur = FakeCursor(
        {**TAX, "oc_conservation.conservation_records": {"taxon_id"}},
        rows={"oc_taxonomy.taxa": 31840, "oc_conservation.conservation_records": 40},
        joins={"carrying": 40, "matched": 0, "taxa_reached": 0},
    )
    result = measure(cur, object_tables=("oc_conservation.conservation_records",))
    assert result["state"] == "absent"


def test_missing_object_table_is_unavailable_not_absent():
    cur = FakeCursor(TAX, rows={"oc_taxonomy.taxa": 31840})
    result = measure(cur, object_tables=("oc_conservation.conservation_records",))
    assert result["state"] == "unavailable"
    assert "absent" in result["interpretation"]  # states it is NOT a finding of absence


def test_missing_taxonomy_table_is_unavailable_not_absent():
    cur = FakeCursor({"oc_habitat.taxon_habitats": {"taxon_id"}}, rows={"oc_habitat.taxon_habitats": 5})
    result = measure(cur, object_tables=("oc_habitat.taxon_habitats",))
    assert result["state"] == "unavailable"
    assert "taxonomy" in result["detail"].lower()


def test_no_recognised_join_is_unavailable_not_absent():
    cur = FakeCursor(
        {**TAX, "oc_habitat.taxon_habitats": {"habitat_name", "notes"}},
        rows={"oc_taxonomy.taxa": 31840, "oc_habitat.taxon_habitats": 900},
    )
    result = measure(cur, object_tables=("oc_habitat.taxon_habitats",))
    assert result["state"] == "unavailable"
    assert "no join" in result["detail"].lower()


def test_name_join_is_used_and_labelled_when_no_id_join_exists():
    """A name join is weaker evidence, so it must be reported as what it is."""
    cur = FakeCursor(
        {**TAX, "oc_mycorrhiza.orchid_fungal_associations": {"orchid_scientific_name", "fungal_name"}},
        rows={"oc_taxonomy.taxa": 31840, "oc_mycorrhiza.orchid_fungal_associations": 1200},
        joins={"carrying": 1200, "matched": 900, "taxa_reached": 300},
    )
    result = measure(cur, object_tables=("oc_mycorrhiza.orchid_fungal_associations",))
    assert result["state"] == "present"
    assert result["measurement"] == "relational_linkage_by_name"


def test_required_value_column_absent_makes_it_unavailable():
    """An occurrence table with no elevation column cannot answer an elevation question."""
    cur = FakeCursor(
        {**TAX, "oc_atlas.occurrences": {"taxon_id", "latitude", "longitude"}},
        rows={"oc_taxonomy.taxa": 31840, "oc_atlas.occurrences": 26},
    )
    result = measure(
        cur,
        object_tables=("oc_atlas.occurrences",),
        required_value_columns=("elevation_m", "elevation"),
    )
    assert result["state"] == "unavailable"
    assert "defined by" in result["detail"]


def test_required_value_column_present_is_measured():
    cur = FakeCursor(
        {**TAX, "oc_env.taxon_elevation_profiles": {"taxon_id", "mean_elevation_m"}},
        rows={"oc_taxonomy.taxa": 31840, "oc_env.taxon_elevation_profiles": 4000},
        joins={"carrying": 3800, "matched": 3700, "taxa_reached": 3500},
    )
    result = measure(
        cur,
        object_tables=("oc_env.taxon_elevation_profiles",),
        required_value_columns=("mean_elevation_m",),
    )
    assert result["state"] == "present"
    assert result["value_column"] == "mean_elevation_m"
    # Rows without the attribute are excluded from the relationship count.
    assert result["rows_carrying_relationship"] == 3800


def test_a_far_larger_unselected_candidate_raises_a_masking_warning():
    """The 26-row-vs-580,000-row occurrence problem, as a measurement."""
    cur = FakeCursor(
        {**TAX, "oc_atlas.occurrences": {"taxon_id"}, "public.orchid_occurrence": {"taxon_id"}},
        rows={"oc_taxonomy.taxa": 31840, "oc_atlas.occurrences": 26, "public.orchid_occurrence": 580612},
        joins={"carrying": 26, "matched": 26, "taxa_reached": 20},
    )
    result = measure(
        cur, object_tables=("oc_atlas.occurrences", "public.orchid_occurrence")
    )
    assert result["state"] == "present"
    assert result["object_table"] == "oc_atlas.occurrences"
    assert any("public.orchid_occurrence" in w for w in result["source_warnings"])


def test_a_comparable_unselected_candidate_raises_no_warning():
    cur = FakeCursor(
        {**TAX, "oc_atlas.occurrences": {"taxon_id"}, "public.occurrences": {"taxon_id"}},
        rows={"oc_taxonomy.taxa": 31840, "oc_atlas.occurrences": 5000, "public.occurrences": 5200},
        joins={"carrying": 5000, "matched": 5000, "taxa_reached": 900},
    )
    result = measure(cur, object_tables=("oc_atlas.occurrences", "public.occurrences"))
    assert result["source_warnings"] == []


def test_unsafe_identifiers_are_refused():
    with pytest.raises(ValueError):
        rm._safe("oc_taxonomy.taxa; DROP TABLE users")


def test_every_declared_relationship_reports_a_state_even_when_nothing_exists():
    """A schema the audit knows nothing about yields eight unavailables, not eight absences."""
    cur = FakeCursor({})
    results = rm.measure_declared_relationships(cur)
    assert len(results) == 8
    assert {r["state"] for r in results.values()} == {"unavailable"}


def test_one_broken_relationship_does_not_take_down_the_others():
    class Exploding(FakeCursor):
        def execute(self, sql, params=()):
            if params and params and "habitat" in str(params[0]):
                raise RuntimeError("relation disappeared mid-audit")
            super().execute(sql, params)

    cur = Exploding({})
    results = rm.measure_declared_relationships(cur)
    assert results["taxonomy_to_habitat"]["state"] == "unavailable"
    assert "RuntimeError" in results["taxonomy_to_habitat"]["detail"]
    assert len(results) == 8


def test_mycorrhiza_response_cache_is_the_last_resort_candidate():
    """A cache of HTTP responses must not be measured ahead of the real corpus."""
    spec = next(s for s in rm.RELATIONSHIP_SPECS if s["name"] == "taxonomy_to_mycorrhiza")
    assert spec["object_tables"][-1].endswith("unified_endpoint_cache")
    assert spec["object_tables"][0] == "oc_mycorrhiza.orchid_fungal_associations"


@pytest.mark.parametrize("spec", rm.RELATIONSHIP_SPECS, ids=lambda s: s["name"])
def test_no_spec_can_produce_absence_without_a_join(spec):
    cur = FakeCursor(TAX, rows={"oc_taxonomy.taxa": 31840})
    result = rm.measure_link_relationship(
        cur,
        name=spec["name"],
        taxonomy_tables=rm.TAXONOMY_TABLES,
        taxonomy_keys=rm.TAXONOMY_KEYS,
        taxonomy_name_columns=rm.TAXONOMY_NAME_COLUMNS,
        object_tables=spec["object_tables"],
        object_taxon_keys=rm.OBJECT_TAXON_KEYS,
        object_name_columns=rm.OBJECT_NAME_COLUMNS,
        required_value_columns=spec.get("required_value_columns", ()),
    )
    assert result["state"] != "absent"

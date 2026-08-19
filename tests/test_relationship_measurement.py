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
            self._result = (self._by_join(flat, "matched"),)
        elif flat.startswith("SELECT COUNT(DISTINCT"):
            self._result = (self._by_join(flat, "taxa_reached"),)
        elif flat.startswith("SELECT COUNT(*) FROM ") and " WHERE " in flat:
            self._result = (self._by_join(flat, "carrying"),)
        elif flat.startswith("SELECT COUNT(*) FROM "):
            table = flat[len("SELECT COUNT(*) FROM ") :].strip()
            self._result = (self.rows.get(table, 0),)
        else:  # pragma: no cover - a query the fake was not taught
            raise AssertionError(f"Unexpected SQL: {flat}")

    def _by_join(self, flat, key):
        """Answer per join column, so a test can describe an id join and a name join separately.

        ``joins`` may be flat ({"matched": 5}) or keyed by the object-side column
        ({"orchid_taxonomy_id": {"matched": 0}, "orchid_scientific_name": {...}}).
        """
        for column, values in self.joins.items():
            if isinstance(values, dict) and f"o.{column}" in flat:
                return values.get(key, 0)
        flat_values = {k: v for k, v in self.joins.items() if not isinstance(v, dict)}
        return flat_values.get(key, 0)

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
    assert result["value_columns"] == ["mean_elevation_m"]
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


def test_join_failure_names_the_columns_each_side_actually_has():
    """An unavailable must be actionable, not just a dead end.

    Production returned three of these against real tables. Reporting only "no
    join recognised" would leave the reader to go and inspect the schema by
    hand; naming the columns turns it into a one-line candidate-list fix.
    """
    cur = FakeCursor(
        {**TAX, "oc_mycorrhiza.orchid_fungal_associations": {"assoc_id", "fungal_name", "orchid_name"}},
        rows={"oc_taxonomy.taxa": 31840, "oc_mycorrhiza.orchid_fungal_associations": 1200},
    )
    result = measure(cur, object_tables=("oc_mycorrhiza.orchid_fungal_associations",))
    assert result["state"] == "unavailable"
    assert result["object_columns"] == ["assoc_id", "fungal_name", "orchid_name"]
    assert result["taxonomy_columns"] == ["scientific_name", "taxon_id"]
    # Which taxonomy relations were available is part of the answer, since the
    # audit now tries every one of them rather than a single anchor.
    assert result["taxonomy_tables_present"] == ["oc_taxonomy.taxa"]
    # The taxonomy side had a key; the object side is what failed.
    assert result["object_key_found"] is None
    assert result["object_name_column_found"] is None


def test_missing_value_column_names_what_the_relation_does_carry():
    cur = FakeCursor(
        {**TAX, "oc_atlas.occurrences": {"taxon_id", "latitude", "longitude"}},
        rows={"oc_taxonomy.taxa": 31840, "oc_atlas.occurrences": 26},
    )
    result = measure(
        cur,
        object_tables=("oc_atlas.occurrences",),
        required_value_columns=("elevation_m",),
    )
    assert result["state"] == "unavailable"
    assert result["object_columns"] == ["latitude", "longitude", "taxon_id"]


def test_orchid_side_key_wins_over_partner_side_key():
    """The pollinator edge table keys both ends. Measuring the wrong one counts insects as orchids.

    oc_interactions.orchid_interaction_edges carries orchid_taxonomy_id and
    partner_taxon_id. A relationship *to orchids* must join the orchid end.
    """
    cur = FakeCursor(
        {
            **TAX,
            "oc_interactions.orchid_interaction_edges": {
                "orchid_taxonomy_id",
                "partner_taxon_id",
                "partner_taxon_name",
            },
        },
        rows={"oc_taxonomy.taxa": 31840, "oc_interactions.orchid_interaction_edges": 900},
        joins={"carrying": 900, "matched": 880, "taxa_reached": 400},
    )
    result = measure(cur, object_tables=("oc_interactions.orchid_interaction_edges",))
    assert result["state"] == "present"
    assert result["join"].startswith("oc_interactions.orchid_interaction_edges.orchid_taxonomy_id")
    assert "partner_taxon_id" not in result["join"]


def test_fungal_taxon_id_is_never_used_as_the_orchid_key():
    cur = FakeCursor(
        {
            **TAX,
            "oc_mycorrhiza.orchid_fungal_associations": {
                "orchid_taxonomy_id",
                "fungal_taxon_id",
                "fungal_name",
            },
        },
        rows={"oc_taxonomy.taxa": 31840, "oc_mycorrhiza.orchid_fungal_associations": 1200},
        joins={"carrying": 1200, "matched": 1100, "taxa_reached": 350},
    )
    result = measure(cur, object_tables=("oc_mycorrhiza.orchid_fungal_associations",))
    assert "fungal_taxon_id" not in result["join"]
    assert "orchid_taxonomy_id" in result["join"]


def test_canonical_name_is_recognised_as_the_taxonomy_name_column():
    """oc_taxonomy.taxa names its name column canonical_name, not scientific_name."""
    cur = FakeCursor(
        {
            "oc_taxonomy.taxa": {"taxon_id", "canonical_name"},
            "oc_graph.taxon_literature_edges": {"scientific_name", "title", "doi"},
        },
        rows={"oc_taxonomy.taxa": 31840, "oc_graph.taxon_literature_edges": 5000},
        joins={"carrying": 5000, "matched": 4800, "taxa_reached": 2000},
    )
    result = measure(cur, object_tables=("oc_graph.taxon_literature_edges",))
    assert result["state"] == "present"
    assert result["measurement"] == "relational_linkage_by_name"
    assert "canonical_name" in result["join"]


def test_a_dead_id_column_does_not_produce_absence_when_the_name_join_finds_rows():
    """The production defect this fallback exists for.

    oc_mycorrhiza.orchid_fungal_associations holds 462 rows. Two carry
    orchid_taxonomy_id and neither resolves. The source registry joins that
    table on orchid_scientific_name. An id-only measurement called 462
    documented fungal associations "absent" -- the precise error the whole
    AUDIT-MEASUREMENT line exists to prevent.
    """
    cur = FakeCursor(
        {
            **TAX,
            "oc_mycorrhiza.orchid_fungal_associations": {
                "orchid_taxonomy_id",
                "orchid_scientific_name",
                "fungal_name",
            },
        },
        rows={"oc_taxonomy.taxa": 31840, "oc_mycorrhiza.orchid_fungal_associations": 462},
        joins={
            "orchid_taxonomy_id": {"carrying": 2, "matched": 0, "taxa_reached": 0},
            "orchid_scientific_name": {"carrying": 462, "matched": 440, "taxa_reached": 210},
        },
    )
    result = measure(cur, object_tables=("oc_mycorrhiza.orchid_fungal_associations",))
    assert result["state"] == "present"
    assert result["measurement"] == "relational_linkage_by_name"
    assert result["rows_matching_taxonomy"] == 440
    # Both attempts are recorded, so the dead id column is visible rather than hidden.
    assert len(result["joins_attempted"]) == 2
    assert any(
        "populated and broken" in w for w in result["source_warnings"]
    ), result["source_warnings"]


def test_absence_requires_every_supported_join_to_have_found_nothing():
    cur = FakeCursor(
        {**TAX, "oc_habitat.taxon_habitats": {"taxon_id", "scientific_name"}},
        rows={"oc_taxonomy.taxa": 31840, "oc_habitat.taxon_habitats": 300},
        joins={
            "taxon_id": {"carrying": 0, "matched": 0, "taxa_reached": 0},
            "scientific_name": {"carrying": 0, "matched": 0, "taxa_reached": 0},
        },
    )
    result = measure(cur, object_tables=("oc_habitat.taxon_habitats",))
    assert result["state"] == "absent"
    assert len(result["joins_attempted"]) == 2


def test_the_id_join_still_wins_when_it_finds_rows():
    cur = FakeCursor(
        {**TAX, "oc_conservation.conservation_records": {"taxon_id", "scientific_name"}},
        rows={"oc_taxonomy.taxa": 31840, "oc_conservation.conservation_records": 500},
        joins={
            "taxon_id": {"carrying": 500, "matched": 480, "taxa_reached": 470},
            "scientific_name": {"carrying": 500, "matched": 300, "taxa_reached": 290},
        },
    )
    result = measure(cur, object_tables=("oc_conservation.conservation_records",))
    assert result["measurement"] == "relational_linkage_by_id"
    assert result["rows_matching_taxonomy"] == 480


def test_any_defining_column_counts_not_just_the_first_that_exists():
    """species_environment_profile carries avg_, min_ and max_elevation_m.

    Measuring only the first match would report absence while the other two sat
    populated beside it.
    """
    cur = FakeCursor(
        {
            **TAX,
            "oc_env_intel.species_environment_profile": {
                "taxonomy_id",
                "avg_elevation_m",
                "min_elevation_m",
                "max_elevation_m",
            },
        },
        rows={"oc_taxonomy.taxa": 31840, "oc_env_intel.species_environment_profile": 26788},
        joins={"carrying": 900, "matched": 880, "taxa_reached": 800},
    )
    result = measure(
        cur,
        object_tables=("oc_env_intel.species_environment_profile",),
        required_value_columns=("avg_elevation_m", "min_elevation_m", "max_elevation_m"),
    )
    assert result["state"] == "present"
    assert result["value_columns"] == ["avg_elevation_m", "min_elevation_m", "max_elevation_m"]


# --- DATA-INTEGRATION-REPAIR-001 regressions ---------------------------------
#
# Each of these encodes a linkage that production measured as broken, and the
# specific reason it was broken. They are written against the shapes the
# read-only diagnostic actually found, so a regression reproduces the original
# defect rather than an invented one.

TAX_BOTH = {
    "oc_taxonomy.taxa": {"taxon_id", "canonical_name"},
    "public.orchid_taxonomy": {"id", "scientific_name"},
}


def test_pollinator_ids_resolve_against_the_taxonomy_relation_they_belong_to():
    """23 of 23 orchid_taxonomy_id values resolve into public.orchid_taxonomy, 0 into oc_taxonomy.taxa.

    Anchoring every relationship to a single taxonomy relation reported this as
    measured-absent while all 23 rows were linked, just to a different table.
    """
    cur = FakeCursor(
        {
            **TAX_BOTH,
            "oc_interactions.orchid_interaction_edges": {
                "orchid_taxonomy_id",
                "orchid_scientific_name",
                "partner_taxon_id",
            },
        },
        rows={
            "oc_taxonomy.taxa": 31840,
            "public.orchid_taxonomy": 69485,
            "oc_interactions.orchid_interaction_edges": 23,
        },
        joins={
            # Same object column, different taxonomy relation on each side of
            # the join -- the fake keys on the object column, so both id
            # attempts share these numbers; reach is what separates them.
            "orchid_taxonomy_id": {"carrying": 23, "matched": 23, "taxa_reached": 4},
            "orchid_scientific_name": {"carrying": 23, "matched": 0, "taxa_reached": 0},
        },
    )
    result = measure(cur, object_tables=("oc_interactions.orchid_interaction_edges",))
    assert result["state"] == "present"
    assert result["measurement"] == "relational_linkage_by_id"
    assert result["rows_matching_taxonomy"] == 23
    # Both taxonomy relations were tried, so the choice is evidenced.
    assert len(result["joins_attempted"]) >= 2


def test_habitat_claims_reach_taxonomy_once_the_right_anchor_is_tried():
    """695 claims, 695 resolving into public.orchid_taxonomy and 2 into oc_taxonomy.taxa."""
    cur = FakeCursor(
        {**TAX_BOTH, "public.oc_species_habitat_claims": {"taxonomy_id", "habitat_type"}},
        rows={
            "oc_taxonomy.taxa": 31840,
            "public.orchid_taxonomy": 69485,
            "public.oc_species_habitat_claims": 695,
        },
        joins={"taxonomy_id": {"carrying": 695, "matched": 695, "taxa_reached": 400}},
    )
    result = measure(cur, object_tables=("public.oc_species_habitat_claims",))
    assert result["state"] == "present"
    assert result["rows_matching_taxonomy"] == 695


def test_the_larger_occurrence_corpus_is_measured_first():
    spec = next(s for s in rm.RELATIONSHIP_SPECS if s["name"] == "taxonomy_to_occurrences")
    assert spec["object_tables"][0] == "public.orchid_occurrence"
    # The 26-row relation is kept as a candidate so masking stays visible.
    assert "oc_atlas.occurrences" in spec["object_tables"]


def test_elevation_knows_the_real_column_names_and_keeps_the_projection_as_a_candidate():
    spec = next(s for s in rm.RELATIONSHIP_SPECS if s["name"] == "taxonomy_to_elevation")
    # The curated projection stays a candidate; it is simply not the one that
    # holds the elevations. See test_elevation_reads_the_harvest_... below.
    assert "public.orchid_occurrence" in spec["object_tables"]
    for column in ("elevation_m", "minimum_elevation", "maximum_elevation", "elevation_meters"):
        assert column in spec["required_value_columns"]


def test_a_name_join_that_wins_says_the_id_join_is_weaker_and_by_how_much():
    """Name matching is the documented fallback, so using it must be visible."""
    cur = FakeCursor(
        {
            **TAX_BOTH,
            "oc_mycorrhiza.orchid_fungal_associations": {
                "orchid_taxonomy_id",
                "orchid_scientific_name",
            },
        },
        rows={
            "oc_taxonomy.taxa": 31840,
            "public.orchid_taxonomy": 69485,
            "oc_mycorrhiza.orchid_fungal_associations": 462,
        },
        joins={
            "orchid_taxonomy_id": {"carrying": 2, "matched": 2, "taxa_reached": 2},
            "orchid_scientific_name": {"carrying": 462, "matched": 347, "taxa_reached": 146},
        },
    )
    result = measure(cur, object_tables=("oc_mycorrhiza.orchid_fungal_associations",))
    assert result["measurement"] == "relational_linkage_by_name"
    assert result["rows_matching_taxonomy"] == 347
    assert any(
        "documented fallback" in w and "2" in w for w in result["source_warnings"]
    ), result["source_warnings"]


def test_reach_outranks_join_strength():
    """A 2-row id join must not outrank a 347-row name join.

    Ranking by strength first would report 0.4% coverage as the measurement and
    call that an improvement.
    """
    cur = FakeCursor(
        {**TAX_BOTH, "t.x": {"taxon_id", "scientific_name"}},
        rows={"oc_taxonomy.taxa": 31840, "public.orchid_taxonomy": 69485, "t.x": 462},
        joins={
            "taxon_id": {"carrying": 2, "matched": 2, "taxa_reached": 2},
            "scientific_name": {"carrying": 462, "matched": 347, "taxa_reached": 146},
        },
    )
    result = measure(cur, object_tables=("t.x",))
    assert result["rows_matching_taxonomy"] == 347


def test_blocked_domains_state_the_relation_is_absent_not_merely_unverified():
    from runtime.knowledge_graph import source_registry as sr

    for domain in ("habitat", "elevation"):
        entry = next(q for q in sr.SOURCE_QUERIES if q.domain == domain)
        assert entry.enabled is False, "these domains must stay fail-closed"
        assert "does not exist in production" in (entry.blocked_reason or "")


def test_the_mixed_ingest_spine_is_never_promoted_over_a_real_occurrence_table():
    """public.records is 5,006,022 rows, and most of them are not occurrences.

    Its record_type breakdown includes 96,832 media_record, 64,764
    taxon_profile, 23,692 video and 10,066 vendor_listing alongside 2,776,500
    typed occurrence. Promoting it on size would report videos as orchid
    occurrences. It is listed so the masking check reports it, and measured
    last so it can never be selected while a real occurrence relation exists.
    """
    from app.routers.mission_control import METRIC_CANDIDATES

    spec = next(s for s in rm.RELATIONSHIP_SPECS if s["name"] == "taxonomy_to_occurrences")
    tables = list(spec["object_tables"])
    assert tables[0] == "public.orchid_occurrence"
    assert "public.records" in tables
    assert tables.index("public.records") > tables.index("public.orchid_occurrence")

    metric = METRIC_CANDIDATES["occurrences"]
    assert metric[0] == "public.orchid_occurrence"
    assert metric.index("public.records") > metric.index("public.orchid_occurrence")


# --- Occurrence contamination guards -----------------------------------------
#
# public.records is a universal ingest spine. These prove that when it is
# measured at all, only rows whose declared type is occurrence evidence can
# reach an occurrence or elevation number.

class FilteringCursor(FakeCursor):
    """A cursor that honours the semantic predicate instead of ignoring it.

    ``by_type`` maps a record_type to how many of its rows would match. Any
    COUNT whose SQL carries the record_type filter answers with the sum over
    admitted types only, so a test fails loudly if the filter is dropped.
    """

    def __init__(self, schema, rows, by_type, joins=None):
        super().__init__(schema, rows, joins)
        self.by_type = by_type

    def execute(self, sql, params=()):
        flat = " ".join(sql.split())
        if "record_type IN (" in flat and flat.startswith("SELECT COUNT("):
            admitted = sum(
                n for t, n in self.by_type.items() if f"'{t}'" in flat
            )
            self._result = (admitted,)
            return
        super().execute(sql, params)


PRODUCTION_TYPE_MIX = {
    "occurrence": 2_776_500,
    "observation": 927_446,
    "specimen": 139_330,
    "occurrence_stub": 621_526,
    "occurrence_photo": 103_007,
    "media_record": 96_832,
    "media_observation": 69_575,
    "taxon_profile": 64_764,
    "observation_photo": 53_998,
    "species_profile": 33_650,
    "video": 23_692,
    "conservation_assessment": 16_955,
    "vendor_listing": 10_066,
}


def _measure_records_spine():
    cur = FilteringCursor(
        {
            **TAX_BOTH,
            "public.records": {"scientific_binomial", "record_type", "elevation_m"},
        },
        rows={
            "oc_taxonomy.taxa": 31840,
            "public.orchid_taxonomy": 69485,
            "public.records": sum(PRODUCTION_TYPE_MIX.values()),
        },
        by_type=PRODUCTION_TYPE_MIX,
        joins={"scientific_binomial": {"carrying": 1, "matched": 1, "taxa_reached": 1}},
    )
    return rm.measure_link_relationship(
        cur,
        name="taxonomy_to_occurrences",
        taxonomy_tables=rm.TAXONOMY_TABLES,
        taxonomy_keys=rm.TAXONOMY_KEYS,
        taxonomy_name_columns=rm.TAXONOMY_NAME_COLUMNS,
        object_tables=("public.records",),
        object_taxon_keys=rm.OBJECT_TAXON_KEYS,
        object_name_columns=rm.OBJECT_NAME_COLUMNS,
        row_filters={"public.records": rm.occurrence_predicate("o", "record_type")},
    )


def test_vendor_listings_videos_and_profiles_cannot_reach_an_occurrence_count():
    """The core contamination guard, against the real production type mix."""
    result = _measure_records_spine()
    eligible = result["semantically_eligible_rows"]

    # Only the three admitted types in this mix.
    assert eligible == 2_776_500 + 927_446 + 139_330
    # And demonstrably none of the excluded ones.
    for excluded in ("vendor_listing", "video", "taxon_profile", "species_profile"):
        assert PRODUCTION_TYPE_MIX[excluded] > 0
        assert eligible + PRODUCTION_TYPE_MIX[excluded] != eligible


def test_occurrence_stub_is_excluded_from_the_measured_total():
    """621,526 rows that are withheld pending curation, not counted."""
    result = _measure_records_spine()
    assert result["semantically_eligible_rows"] < sum(PRODUCTION_TYPE_MIX.values())
    assert 621_526 not in (result["semantically_eligible_rows"],)
    assert "occurrence_stub" not in result["semantic_filter"]["predicate"]


def test_media_rows_cannot_double_count_the_occurrences_they_illustrate():
    result = _measure_records_spine()
    predicate = result["semantic_filter"]["predicate"]
    for media in ("occurrence_photo", "observation_photo", "media_record", "media_observation"):
        assert f"'{media}'" not in predicate, media


def test_the_measurement_reports_the_rule_that_produced_its_number():
    """A filtered count is unreadable without the filter, so it travels with it."""
    result = _measure_records_spine()
    assert result["semantic_filter"]["table"] == "public.records"
    assert "record_type IN (" in result["semantic_filter"]["predicate"]


def test_masking_compares_eligible_rows_not_raw_table_size():
    """A 5M spine is not 'larger' than a curated table if most of it is not occurrences.

    Comparing raw size would make the spine look authoritative on every audit
    and push a reader toward exactly the promotion these semantics forbid.
    """
    result = _measure_records_spine()
    assert result["semantically_eligible_rows"] < result["total_object_rows"]


def test_elevation_spec_carries_the_same_occurrence_filter():
    """Elevation must not be sourced from a video or a vendor listing."""
    spec = next(s for s in rm.RELATIONSHIP_SPECS if s["name"] == "taxonomy_to_elevation")
    assert "public.records" in spec["row_filters"]
    predicate = spec["row_filters"]["public.records"]
    for excluded in ("vendor_listing", "video", "taxon_profile", "media_record"):
        assert f"'{excluded}'" not in predicate, excluded


def test_occurrence_spec_carries_the_filter_too():
    spec = next(s for s in rm.RELATIONSHIP_SPECS if s["name"] == "taxonomy_to_occurrences")
    assert "public.records" in spec["row_filters"]
    assert "record_type IN (" in spec["row_filters"]["public.records"]


def test_a_relation_without_a_filter_is_measured_unfiltered():
    """The filter is per-relation; curated tables are not silently narrowed."""
    cur = FakeCursor(
        {**TAX_BOTH, "oc_conservation.conservation_records": {"taxon_id"}},
        rows={"oc_taxonomy.taxa": 31840, "public.orchid_taxonomy": 69485,
              "oc_conservation.conservation_records": 2},
        joins={"taxon_id": {"carrying": 2, "matched": 2, "taxa_reached": 2}},
    )
    result = measure(cur, object_tables=("oc_conservation.conservation_records",))
    assert result["semantic_filter"] is None
    assert result["semantically_eligible_rows"] == result["total_object_rows"]


def test_elevation_reads_the_harvest_where_the_elevations_actually_are():
    """The curated projection holds 7 elevations; the harvest holds 306,359.

    Selecting the projection first answered 7 and presented it as the state of
    the archive. Elevation therefore reads public.records first -- but only
    through the occurrence filter, so this is not a promotion of the spine.
    """
    spec = next(s for s in rm.RELATIONSHIP_SPECS if s["name"] == "taxonomy_to_elevation")
    assert spec["object_tables"][0] == "public.records"
    assert "public.records" in spec["row_filters"]


def test_the_occurrence_metric_does_not_follow_elevation_onto_the_spine():
    """Only elevation reads the harvest first. Occurrences stay on the projection."""
    occ = next(s for s in rm.RELATIONSHIP_SPECS if s["name"] == "taxonomy_to_occurrences")
    assert occ["object_tables"][0] == "public.orchid_occurrence"
    from app.routers.mission_control import METRIC_CANDIDATES

    assert METRIC_CANDIDATES["occurrences"][0] == "public.orchid_occurrence"

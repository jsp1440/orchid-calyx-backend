"""Guards against the executive audit asserting relationship state it never measured.

Before this change ``live_audit_payload`` emitted a hardcoded list of all ten
relationship names whenever *any* subsystem completeness row scored below
healthy. That list was not a relationship measurement at all: the audit reported
``taxonomy_to_images`` as missing in the same payload in which the image metric
scored healthy on 5,071,287 rows. These tests pin the corrected contract --
``missing_relationships`` carries only relationships measured absent, and
anything without a measurement path is reported as ``unmeasured``.

They also cover the metric-source masking check, which exists because
``first_available_count`` selects the first *existing* candidate relation: a
26-row fixture relation earlier in the candidate list silently hid a far larger
corpus behind it.
"""


import pytest

from app.routers import mission_control, owner_operations


class FakeCursor:
    """Minimal cursor answering the catalog queries the metric probe issues."""

    def __init__(self, relations):
        # relations: {fq_name: (relkind, reltuples, exact_count)}
        self.relations = relations
        self._result = None

    def execute(self, sql, params=()):
        flat = " ".join(sql.split())
        if "to_regclass" in flat and "pg_class" not in flat:
            self._result = (params[0] in self.relations,)
        elif "pg_class" in flat:
            entry = self.relations.get(params[0])
            self._result = (entry[0], entry[1]) if entry else None
        elif flat.startswith("SELECT COUNT(*) FROM "):
            table = flat[len("SELECT COUNT(*) FROM ") :]
            self._result = (self.relations[table][2],)
        else:  # pragma: no cover - defensive
            raise AssertionError(f"unexpected SQL: {flat}")

    def fetchone(self):
        return self._result


def test_larger_unselected_candidate_is_reported_as_masking():
    """A tiny selected relation must not silently hide a far larger candidate."""
    cur = FakeCursor(
        {
            "oc_atlas.occurrences": ("r", 26, 26),
            "public.orchid_occurrence": ("r", 580612, 580612),
        }
    )
    result = mission_control.first_available_count(
        cur, ["oc_atlas.occurrences", "public.orchid_occurrence"]
    )

    # Selection semantics are unchanged: the headline number is not silently redefined.
    assert result["table"] == "oc_atlas.occurrences"
    assert result["count"] == 26
    # But the discrepancy is now surfaced instead of being invisible.
    assert len(result["source_warnings"]) == 1
    assert "public.orchid_occurrence" in result["source_warnings"][0]
    assert [c["table"] for c in result["candidates"]] == [
        "oc_atlas.occurrences",
        "public.orchid_occurrence",
    ]


def test_comparable_sized_candidate_is_not_flagged():
    cur = FakeCursor(
        {"a.one": ("r", 1000, 1000), "b.two": ("r", 1200, 1200)}
    )
    result = mission_control.first_available_count(cur, ["a.one", "b.two"])
    assert result["source_warnings"] == []


def test_never_analyzed_relation_reports_unknown_size_not_zero():
    """``reltuples`` of -1 means "never analyzed" and must not read as empty."""
    cur = FakeCursor({"a.one": ("r", 10, 10), "b.two": ("r", -1, 0)})
    result = mission_control.first_available_count(cur, ["a.one", "b.two"])
    unselected = next(c for c in result["candidates"] if c["table"] == "b.two")
    assert unselected["approximate_rows"] is None
    assert result["source_warnings"] == []


def test_view_size_is_not_estimated_from_reltuples():
    cur = FakeCursor({"a.one": ("r", 10, 10), "b.view": ("v", 0, 0)})
    result = mission_control.first_available_count(cur, ["a.one", "b.view"])
    view = next(c for c in result["candidates"] if c["table"] == "b.view")
    assert view["exists"] is True
    assert view["approximate_rows"] is None


def test_missing_candidate_is_reported_absent():
    cur = FakeCursor({"b.two": ("r", 5, 5)})
    result = mission_control.first_available_count(cur, ["a.gone", "b.two"])
    assert result["table"] == "b.two"
    assert result["candidates"][0] == {
        "table": "a.gone",
        "selected": False,
        "exists": False,
        "relkind": None,
        "approximate_rows": None,
    }


@pytest.fixture
def no_database(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(owner_operations, "database_url", lambda: None)


def test_unmeasured_relationships_are_never_reported_as_missing(no_database):
    evidence = owner_operations.relationship_evidence()

    assert set(evidence) == set(owner_operations.AUDIT_RELATIONSHIPS)
    assert all(entry["state"] == "unmeasured" for entry in evidence.values())
    # The critical invariant: an unmeasured relationship is not an absent one.
    assert not any(entry["state"] == "absent" for entry in evidence.values())


def test_audit_payload_separates_absent_from_unmeasured(no_database):
    payload = owner_operations.live_audit_payload("executive")

    assert payload["missing_relationships"] == []
    assert set(payload["unmeasured_relationships"]) == set(
        owner_operations.AUDIT_RELATIONSHIPS
    )
    assert set(payload["relationship_evidence"]) == set(
        owner_operations.AUDIT_RELATIONSHIPS
    )


def test_next_actions_are_derived_not_hardcoded(no_database):
    """The previous payload always returned the same three sentences."""
    payload = owner_operations.live_audit_payload("executive")
    actions = payload["recommended_next_actions"]

    assert actions != [
        "Apply BUILD-051 migration.",
        "Deploy owner-session backend.",
        "Run smoke tests.",
    ]
    assert any("measurement path" in action for action in actions)


def test_markdown_distinguishes_absent_from_unmeasured(no_database):
    payload = owner_operations.live_audit_payload("executive")
    markdown = owner_operations.audit_markdown(payload)

    assert "## Measured-Absent Relationships" in markdown
    assert "- none measured absent" in markdown
    assert "Unmeasured Relationships (state unknown, not a finding of absence)" in markdown
    assert "- taxonomy_to_mycorrhiza" in markdown


def test_relationship_evidence_reports_present_from_live_measurement(monkeypatch):
    """A real measurement must be reported as measured, with its provenance kept."""
    live = {
        "relational": {
            "taxonomy_to_images": {
                "state": "available",
                "taxonomy_table": "public.orchid_taxonomy",
                "image_table": "public.orchid_images",
                "taxonomy_key": "id",
                "image_taxonomy_key": "taxonomy_id",
                "total_images": 5071287,
                "linked_images": {"value": 5000000},
                "taxa_with_images": {"value": 30000},
                "broken_taxonomy_targets": {"value": 25},
            }
        },
        "graph": {
            "edge_table": "oc_graph.kg_edges",
            "integrity": {
                "state": "available",
                "passed": False,
                "null_endpoint_edges": 3,
                "duplicate_edges": 12,
            },
        },
    }
    monkeypatch.setattr(owner_operations, "db_execute", lambda callback: live)

    evidence = owner_operations.relationship_evidence()

    images = evidence["taxonomy_to_images"]
    assert images["state"] == "present"
    assert images["linked_images"] == 5000000
    assert images["provenance"]["image_table"] == "public.orchid_images"
    assert (
        images["provenance"]["join"]
        == "public.orchid_images.taxonomy_id -> public.orchid_taxonomy.id"
    )

    integrity = evidence["knowledge_graph_node_edge_integrity"]
    assert integrity["state"] == "absent"
    assert integrity["duplicate_edges"] == 12

    # Domains with no measurement path stay unmeasured even on a live run.
    assert evidence["taxonomy_to_pollinators"]["state"] == "unmeasured"

from runtime.knowledge_graph.domain_sources import DomainSource
from runtime.knowledge_graph.full_integration import build_publication_plan, inventory_domain


class FakeCursor:
    def __init__(self, tables):
        self.tables = tables
        self._rows = []

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        if "to_regclass" in normalized:
            self._rows = [(params[0] in self.tables,)]
            return
        if "information_schema.columns" in normalized:
            qualified = f"{params[0]}.{params[1]}"
            self._rows = [(c,) for c in self.tables[qualified]["columns"]]
            return
        if normalized.startswith("SELECT COUNT(*) FROM"):
            qualified = normalized.split("FROM", 1)[1].strip()
            self._rows = [(self.tables[qualified]["count"],)]
            return
        raise AssertionError(normalized)

    def fetchone(self):
        return self._rows[0]

    def fetchall(self):
        return list(self._rows)


def test_available_domain_requires_live_source_and_taxon_key():
    cur = FakeCursor({
        "public.orchid_images": {
            "columns": ["id", "taxonomy_id", "image_url"],
            "count": 12,
        }
    })
    result = inventory_domain(
        cur,
        DomainSource("media", "production", "public.orchid_images", "image", "has_image"),
    )
    assert result.state == "available"
    assert result.row_count == 12
    assert result.taxon_key_columns == ("taxonomy_id",)


def test_existing_source_without_taxon_key_is_partial_not_complete():
    cur = FakeCursor({
        "oc_conservation.conservation_records": {
            "columns": ["id", "scientific_name", "status"],
            "count": 4,
        }
    })
    result = inventory_domain(
        cur,
        DomainSource(
            "conservation",
            "production",
            "oc_conservation.conservation_records",
            "conservation_assessment",
            "has_conservation_assessment",
        ),
    )
    assert result.state == "partial"
    assert result.row_count == 4
    assert "resolver mapping" in result.limitation


def test_staging_research_is_withheld():
    result = inventory_domain(
        FakeCursor({}),
        DomainSource("research", "staging_only", "oc_reasoning.*", "research_question", "raises_question"),
    )
    assert result.state == "withheld"
    assert result.row_count is None


def test_publication_plan_never_self_authorizes_writes():
    inventory = {
        "contract": "calyx-full-graph-integration-inventory-v1",
        "domains": [
            {
                "domain": "media",
                "configured_status": "production",
                "state": "available",
                "discovered_sources": ["public.orchid_images"],
                "node_type": "image",
                "edge_type": "has_image",
                "limitation": None,
            },
            {
                "domain": "pollinators",
                "configured_status": "production",
                "state": "partial",
                "discovered_sources": ["oc_globi.interactions"],
                "node_type": "pollinator",
                "edge_type": "associated_with_pollinator",
                "limitation": "resolver required",
            },
        ],
    }
    plan = build_publication_plan(inventory)
    assert plan["executable"] is False
    assert plan["steps"][0]["requires_owner_authorization"] is True
    assert plan["steps"][1]["action"] == "resolve_adapter_blocker"
